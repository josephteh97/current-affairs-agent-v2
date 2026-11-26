"""
tool_gate.py — the single checkpoint between "the model asked for a tool" and
"the tool runs". See SECURITY.md §1 and §5.

Deny by default. A call runs only if:
  1. the tool is registered in SPECS,
  2. every argument is declared, required ones are present, and all values pass validation,
  3. the per-turn budget for the tool's risk tier is not used up,
  4. for "write" tools, a human approved it (no approver → denied, never auto-approved).

Both agent.py and mcp_agent_server.py call tools only through ToolGate.
Program code that picks its own arguments (e.g. the forced search in agent.py)
may call tools.py directly.
"""

from collections import Counter
from dataclasses import dataclass
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

Approver = Callable[[str, dict], bool]


class ToolGate:
    """
    confirm: asks a human to approve a write call; None means non-interactive,
             so every write is denied.
    budget:  per-turn limits by risk tier; None disables budgeting (for hosts
             with no notion of a turn, e.g. the MCP server).
    """

    def __init__(self, confirm: Optional[Approver], budget: Optional[dict] = DEFAULT_BUDGET):
        self.confirm = confirm
        self.budget = budget
        self.used = Counter()

    def new_turn(self) -> None:
        self.used.clear()

    def check(self, name: str, args) -> tuple:
        """Return (spec, cleaned_args) or raise Denied. Approval happens last."""
        spec = SPECS.get(name)
        if spec is None:
            raise Denied(f"unknown tool '{name}'. Available: {list(SPECS)}")
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
        if spec.risk == "write":
            if self.confirm is None:
                raise Denied(f"{name} needs human approval, which is unavailable in non-interactive mode")
            if not self.confirm(name, clean):
                raise Denied(f"the user declined {name}")
        return spec, clean

    def call(self, name: str, args) -> tuple:
        """Return (observation, ran). Never raises."""
        try:
            spec, clean = self.check(name, args)
        except Denied as e:
            return f"Denied by policy: {e}", False
        self.used[spec.risk] += 1
        try:
            return spec.fn(**clean), True
        except Exception as e:
            return f"Tool error: {e}", False


def ask_in_terminal(name: str, args: dict) -> bool:
    """Interactive approver for the CLI."""
    shown = ", ".join(f"{k}={v!r:.60}" for k, v in args.items())
    try:
        reply = input(f"\n  ⚠ ARIA wants to run {name}({shown})\n    Allow? [y/N] ")
    except EOFError:
        return False
    return reply.strip().lower() == "y"
