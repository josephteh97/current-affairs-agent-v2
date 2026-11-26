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

**Audit log** ✅ — `ToolGate` appends one JSON line per tool call to `$ARIA_DATA_DIR/logs/audit.jsonl` (CLI and MCP; rotates to `.1` at 5 MB):
```json
{"ts": "...", "session": "...", "host": "cli", "tool": "web_fetch", "risk": "network",
 "decision": "allowed|user_approved|denied|error|program", "args": {"url": "..."},
 "reason": "...", "result_len": 5321, "result_sha256": "…", "blocked": "..."}
```
- Arguments are redacted (private keys, `sk-…`/`ghp_…`/AWS keys, `password=`/`token=`/`api_key=` values) and truncated before writing. Results are stored only as length + hash, never content.
- Program-initiated calls (the forced search) are logged as `program`.
- Review with `python audit_report.py` — it lists denials, network blocks, human approvals and errors, and exits 1 if anything needs review. Run it weekly, or immediately after anything unexpected.

**Secrets** — ARIA needs **no** API keys (Ollama is local, DuckDuckGo needs none). Keep it that way:
- No secrets in the repo, `.env`, prompts, memory files, or logs.
- If a future feature needs a key, it is read from the environment by code and never passed to the model.

**Cleanup after a suspected incident:**
1. Stop ARIA and the MCP server.
2. Back up then inspect `agent_memory.json` (`learned_rules`), `agent_memory.db`, `memory.json` for injected content; delete bad entries or reset the files.
3. Run `python audit_report.py` (or `--session ID`) for unexpected hosts, denials and approvals.
4. Run `./run.sh check` — verifies `skills/*.md` against `skills.lock` and runs `pip-audit`.
5. If anything may have been read from disk, rotate the relevant credentials (SSH keys, tokens).

## 7. Supply chain

- Direct dependencies listed in `requirements.in` (only what the code imports: `ddgs`, `mcp`); unused `fastmcp` and the `duckduckgo-search` fallback were removed. ✅
- `requirements.txt` is generated by `uv pip compile --generate-hashes`: every package, including transitive ones, is pinned with SHA-256 hashes. `./run.sh install` uses `pip install --require-hashes`, so a swapped package is refused. ✅
- `pip-audit` runs in `./run.sh check` and fails the check on any known vulnerability. ✅ (It caught 5 CVEs + 3 PYSEC advisories in `mcp` 1.26.0 → upgraded to 1.30.0.)
- `skills/*.md` are treated as code: `_load_skills` loads a skill only if its SHA-256 matches `skills.lock`; a missing lock loads no skills (fail closed). After reviewing a change: `./run.sh lock-skills`. ✅
- Container base image pinned by digest, not tag. ✅

## 8. Isolation (container)

`./run.sh docker` runs ARIA via `docker-compose.yml`. Verified from inside the container:

| Layer | Status |
|---|---|
| Home directory / `~/.ssh` not mounted — `file://` reads fail even if the code-level block is bypassed | ✅ |
| Root filesystem read-only (code in `/app` and `/etc` not writable); only `./data` → `/data` writable | ✅ |
| Runs as your non-root uid; all Linux capabilities dropped (`CapEff=0`) | ✅ |
| No setuid/setgid binaries in the image (replaces `no-new-privileges`, which breaks exec on this AppArmor host) | ✅ |
| AppArmor `docker-default` enforced; memory 1 GB, 128 processes | ✅ |
| Network egress limited to ports 80/443 at the network level | ❌ see G7 |

Ollama: the container reaches the host via `host.docker.internal`. Ollama listens on `127.0.0.1` by default,
which a container cannot reach. Make it listen on the Docker bridge only — **not** `0.0.0.0`, which would expose
it to your whole network — e.g. `OLLAMA_HOST=172.17.0.1:11434` (Docker's default bridge IP; check with
`ip addr show docker0`) and point the host CLI at the same address with `OLLAMA_URL`.

---

## Known Gaps

| ID | Gap | Fixed by |
|---|---|---|
| ~~G1~~ | ~~`web_fetch` accepts any URL, including `file://` and private IPs~~ — **fixed** (Exercise 1) | Exercise 1 ✅ |
| ~~G2~~ | ~~Tool output is not tagged as untrusted; no provenance rule for `web_fetch`~~ — **fixed** | Exercise 2 ✅ |
| ~~G3~~ | ~~Dispatch passes `**tool_args` unchecked; no risk tiers, confirmation, or budget~~ — **fixed** (`tool_gate.py`) | Exercise 3 ✅ |
| ~~G4~~ | ~~`remember_context` keys unvalidated; `learned_rules` persist without review~~ — **fixed** | Exercise 4 ✅ |
| ~~G5~~ | ~~No audit log~~ — **fixed** (`AuditLog`, `audit_report.py`) | Exercise 7 ✅ |
| ~~G6~~ | ~~`requirements.txt` uses `>=` ranges, no hashes; skills not hash-locked~~ — **fixed** | Exercise 5 ✅ |
| G7 | Container egress is not restricted at the network level (only by `web_fetch`'s code-level policy). Needs an egress proxy or firewall rules allowing 80/443 + the Ollama port only. | Open |
| G8 | `web_search` queries go to DuckDuckGo unfiltered — injected text could place data in a query. Low risk (not an attacker-controlled server). | Accepted |

Update a row's status to ✅ only when the corresponding test passes. Run them with `./run.sh test` (`tests/`).
