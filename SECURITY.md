# ARIA Security Policy

This document defines what ARIA is allowed to do. Anything not listed here is **denied by default**.
Every rule is enforced **in code**, not by asking the model to behave. The model is assumed to be
manipulable by any text it reads.

Status legend: ✅ enforced · ❌ not yet enforced (gap — see Known Gaps)

---

## 1. Tools — what can ARIA call?

Only the tools registered in `tools.py` (plus one MCP-only tool). No other tool, shell command,
or plugin may be added without updating this table and review.

| Tool | Risk tier | Side effects | Status |
|---|---|---|---|
| `web_search` | network | Outbound query to DuckDuckGo | ✅ |
| `web_fetch` | network | Outbound HTTP GET to one URL | ✅ |
| `write_essay` | none | Returns a text scaffold | ✅ |
| `get_best_sources` | read | Reads `agent_memory.db` | ✅ |
| `recall_writing_feedback` | read | Reads `agent_memory.db` | ✅ |
| `rate_source` | write | Writes `agent_memory.db` | ✅ |
| `log_writing_feedback` | write | Writes `agent_memory.db` | ✅ |
| `remember_context` (MCP only) | write | Writes `memory.json` (key `[a-z0-9_]{1,40}`, value ≤ 2000 chars, ≤ 100 keys) | ✅ |

Rules:
All model-requested calls go through `tool_gate.py` (`ToolGate`), shared by the CLI and MCP server.
- Unknown tool names and unknown arguments are rejected. ✅
- Argument values are validated (types, ranges, lengths, allowed values). ✅
- No tool may execute code, run shell commands, or install packages. ✅

## 2. Files — what can ARIA access?

The agent (the LLM) has **no general file access**. The program itself touches only these fixed paths,
chosen by code, never by a model-supplied argument:

| Path | Access | Purpose |
|---|---|---|
| `agent_memory.db` | read/write | Source ratings, writing feedback |
| `agent_memory.json` | read/write | Learned rules, stats (CLI only) |
| `memory.json` | read/write | MCP key-value memory |
| `skills/*.md` | read | Prompt playbooks |

Everything else — home directory, `~/.ssh`, `.env`, credentials, system files — is out of scope.
No tool accepts a file path as an argument. `web_fetch` rejects `file://` URLs. ✅

## 3. Network — what hosts can ARIA reach?

ARIA must reach the public web to search for news, so "no network" is not possible. Instead:

| Destination | Allowed | By whom |
|---|---|---|
| DuckDuckGo (via `ddgs`) | ✅ | `web_search` |
| Public news sites, `http`/`https`, ports 80/443 | ✅ | `web_fetch` |
| `localhost:11434` (Ollama) | ✅ | Program code only — never via a tool |
| Loopback, private (10/8, 172.16/12, 192.168/16), link-local (169.254/16, incl. cloud metadata), IPv6 equivalents | ❌ blocked | — |
| Any other scheme (`file`, `ftp`, `gopher`, …) | ❌ blocked | — |

The IP check runs at socket-connect time against the exact IP being connected to (defeats DNS rebinding),
so every redirect hop is checked too. Environment proxies are ignored. Responses are capped at 2 MB. ✅

## 4. Untrusted content — how is it handled?

**All** tool output (search results, fetched pages, stored memory) is untrusted, regardless of source.
We do not try to judge whether content is "malicious" — that cannot be done reliably. Instead:

- Tool output is wrapped in `<tool_output trusted="false">` (forced search: `<search_results trusted="false">`); a fake closing tag inside the content is escaped, and the system prompt states it is data, never instructions. ✅ This lowers, but does not remove, the chance the model obeys injected text — the code-level rules below are the real defence.
- **Provenance rule (CLI):** `web_fetch` may only open URLs that appeared in this turn's search results or in the user's message (exact URL, including query string). Any other URL needs human approval; in `--auto` it is denied. ✅ MCP: off — the server never sees the user's message, so the MCP client's per-call approval is the check.
- Content never causes code execution, package installation, or file access (there are no tools for these). ✅
- Per-turn budget by risk tier (CLI): none 3, read 6, network 6, write 3. ✅

## 5. Human confirmation — which actions need a person?

| Action | Policy |
|---|---|
| Reading/writing arbitrary local files | **Denied** — not confirmable, no tool exists |
| `web_fetch` of a URL outside the provenance rule | CLI: y/N prompt explaining why ✅. `--auto`: denied ✅ |
| `rate_source`, `log_writing_feedback` | CLI: confirm with y/N before writing ✅. MCP: denied unless `ARIA_MCP_ALLOW_WRITES=1`, which delegates approval to the MCP client's per-call prompt ✅ |
| `remember_context` (MCP) | Same as other write tools: denied unless `ARIA_MCP_ALLOW_WRITES=1` ✅ |
| `learned_rules` (injected into every future system prompt) | Only fixed, code-authored lessons (`KNOWN_LESSONS` in `agent.py`) can be stored **or** shown; anything else — including text edited into `agent_memory.json` — is ignored ✅ |
| Non-interactive mode (`--auto`) | Anything requiring confirmation is **denied**, never auto-approved ✅ |

## 6. Audit and cleanup

**Audit log** — every tool call appends one JSON line to `logs/audit.jsonl`: ❌ see G5
```json
{"ts": "...", "tool": "web_fetch", "args": {"url": "..."}, "risk": "network",
 "decision": "allowed|denied|user_approved", "result_len": 5321}
```
Review weekly, or immediately after anything unexpected: look for denied calls, non-public hosts, and memory writes.

**Secrets** — ARIA needs **no** API keys (Ollama is local, DuckDuckGo needs none). Keep it that way:
- No secrets in the repo, `.env`, prompts, memory files, or logs.
- If a future feature needs a key, it is read from the environment by code and never passed to the model.

**Cleanup after a suspected incident:**
1. Stop ARIA and the MCP server.
2. Back up then inspect `agent_memory.json` (`learned_rules`), `agent_memory.db`, `memory.json` for injected content; delete bad entries or reset the files.
3. Review `logs/audit.jsonl` for unexpected hosts or file URLs.
4. Verify `skills/*.md` against `skills.lock` hashes. ❌ see G6
5. If anything may have been read from disk, rotate the relevant credentials (SSH keys, tokens).

## 7. Supply chain

- Dependencies pinned to exact versions with hashes; install with `--require-hashes`. ❌ see G6
- `pip-audit` runs in `./run.sh check`. ❌ see G6
- `skills/*.md` are treated as code: changes require review and a `skills.lock` hash update. ❌ see G6

---

## Known Gaps

| ID | Gap | Fixed by |
|---|---|---|
| ~~G1~~ | ~~`web_fetch` accepts any URL, including `file://` and private IPs~~ — **fixed** (Exercise 1) | Exercise 1 ✅ |
| ~~G2~~ | ~~Tool output is not tagged as untrusted; no provenance rule for `web_fetch`~~ — **fixed** | Exercise 2 ✅ |
| ~~G3~~ | ~~Dispatch passes `**tool_args` unchecked; no risk tiers, confirmation, or budget~~ — **fixed** (`tool_gate.py`) | Exercise 3 ✅ |
| ~~G4~~ | ~~`remember_context` keys unvalidated; `learned_rules` persist without review~~ — **fixed** | Exercise 4 ✅ |
| G5 | No audit log | Exercise 7 |
| G6 | `requirements.txt` uses `>=` ranges, no hashes; skills not hash-locked | Exercise 5 |

Update a row's status to ✅ only when the corresponding test passes. Run them with `./run.sh test` (`tests/`).
