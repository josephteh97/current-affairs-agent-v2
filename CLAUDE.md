# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project: ARIA — Agentic Reasoning Intelligence Assistant

A self-learning current-affairs agent built on a local Ollama LLM (default `llama3.1:8b`) with live web search and SQLite-backed memory. Exposed two ways: a CLI ReAct loop (`agent.py`) and an MCP tool server (`mcp_agent_server.py`).

## Commands

```bash
./run.sh                       # Start the CLI agent (requires `ollama serve` running)
./run.sh --model llama3.2      # Switch model
./run.sh --debug               # Print raw LLM output each ReAct iteration
./run.sh mcp                   # Start the MCP server instead
./run.sh install               # pip install --require-hashes -r requirements.txt
./run.sh check                 # Verify Python ver, ddgs, mcp, sqlite3, Ollama, pip-audit, skills.lock
./run.sh test                  # Run the security tests in tests/
./run.sh --auto                # Non-interactive: deny anything needing approval
./run.sh lock-skills           # Re-hash skills/*.md into skills.lock (after reviewing changes)
./run.sh docker [--auto]       # Run in the locked-down container (docker-compose.yml)
./run.sh docker-test           # Run tests/test_gate.py inside the container
./run.sh egress-log            # Every outbound request the container's proxy allowed/denied
python audit_report.py         # Summarise logs/audit.jsonl; exits 1 if anything needs review
```

In-CLI commands: `clear` (reset conversation, keep learned rules), `memory` (show RL rules + stats), `sources` (show ranked outlets), `model <name>`, `debug`, `help`.

`./run.sh test` runs the security tests in `tests/` (plain scripts, no framework; `test_gate.py` is offline, `test_web_fetch.py` needs internet for one check). There is no linter or build step.

## Architecture

The system is structured around a **single source of truth for tools** (`tools.py`) consumed by two different runtimes. Never reimplement a tool in `agent.py` or `mcp_agent_server.py` — fix it in `tools.py` and both consumers inherit the fix.

```
CLI ─→ agent.py ──┐
                  ├─→ tools.py ─→ DuckDuckGo / SQLite / web fetch
MCP client ─→ mcp_agent_server.py ─┘
```

### Layers

- **`tools.py`** — All tool functions: `web_search`, `web_fetch`, `write_essay`, plus the four self-learning tools (`rate_source`, `get_best_sources`, `log_writing_feedback`, `recall_writing_feedback`). Owns the SQLite schema (`agent_memory.db`, tables `source_quality` and `writing_feedback`) — created lazily by `_db()` on first use.
- **`tool_gate.py`** — The only path from a model-requested tool call to `tools.py`. `SPECS` registers each tool with a risk tier (`none`/`read`/`network`/`write`) and per-argument validators; `ToolGate` denies unknown tools/args, enforces per-turn budgets, and requires human approval for `write` tools and for `web_fetch` of URLs not seen this turn (URL provenance: user message + search results). No approver → denied. Tool output reaching the model is wrapped with `wrap_untrusted()`. Every decision is written by `AuditLog` to `logs/audit.jsonl` (args redacted, results hashed). New tools must be added to `SPECS`, or the model cannot call them. See `SECURITY.md`.
- **`agent.py`** — Ollama ReAct loop. Three things to know:
  1. **Forced tool use**: `needs_live_search()` keyword-matches against `CURRENT_EVENTS_SIGNALS`; if it hits, `run_agent_turn` calls `web_search` *before* the LLM ever sees the query and injects results as `pre_context`. This bypasses the LLM's format-following for reliability on small models.
  2. **ReAct parser** (`parse_react`) expects `THOUGHT/ACTION/ACTION_INPUT/FINAL_ANSWER`. The stop sequence `OBSERVATION:` prevents the model from hallucinating tool results. JSON parse failures fall back to regex key/value extraction.
  3. **RL-style memory** (`agent_memory.json`): `evaluate_turn` scores each turn and `absorb_lessons` writes new rules into `learned_rules` (capped at 20). Only fixed strings in `KNOWN_LESSONS` are accepted or shown — never model/web-derived text, because these rules persist into every future prompt. The system prompt is rebuilt after every turn so new lessons take effect immediately.
- **`mcp_agent_server.py`** — FastMCP wrapper. Registers every tool in `MCP_SPECS` (the shared `SPECS` plus the MCP-only `remember_context`, key-value writes to `memory.json`) through a `ToolGate`. Do not duplicate this tool in `agent.py` — the CLI uses the SQLite/JSON memory instead.
- **`skills/*.md`** — Prompt-injected playbooks loaded by `_load_skills()`. `news_search.md` and `self_learning.md` always load; `essay_writing.md` only loads when `is_essay_request()` matches, to keep context lean for small models.

### Two memory systems (do not conflate)

- `agent_memory.db` (SQLite, owned by `tools.py`): cross-session source quality rankings + writing feedback. Aggregated via `AVG()`/`COUNT()`.
- `agent_memory.json` (owned by `agent.py`): the RL heuristic — `learned_rules`, `stats`, `episodes`. Only used by the CLI, not by the MCP server.

### Intent routing

`is_essay_request()` and `needs_live_search()` are deliberate keyword classifiers, not LLM calls — they run before the model and decide (a) whether to force a search, (b) whether to load `essay_writing.md` into the prompt. When adding new intent categories, extend these lists rather than introducing a separate classifier.

## Conventions

- **Container networking**: the `aria` service has no route out; all traffic goes through the `egress` Squid proxy (`egress/squid.conf`). `web_fetch` honours only `ARIA_EGRESS_PROXY`, never generic `HTTP(S)_PROXY`. Any new outbound feature must work through that proxy.
- **State location**: all mutable files (`agent_memory.db`, `agent_memory.json`, `memory.json`, `logs/`) live in `tools.DATA_DIR` (`$ARIA_DATA_DIR`, default: project folder). Never write elsewhere — the container mounts only that directory.
- **Dependencies**: edit `requirements.in`, then regenerate the hash-locked `requirements.txt` with the `uv pip compile` command in its header. Never hand-edit `requirements.txt`.
- **Skills are code**: after editing `skills/*.md`, run `./run.sh lock-skills`, or the changed skill is silently skipped at load time.

- Hard rule baked into the system prompt: `write_essay` must NEVER be called unprompted. Search queries get summarised with citations; only explicit essay/report/analysis requests get the essay scaffold.
- `write_essay` returns a scaffold with `[Agent: ...]` placeholders that the LLM must expand into prose — it is not a finished essay.
- DuckDuckGo search tries `ddgs.news()` first (better recency), falls back to `ddgs.text()`. Only the `ddgs` package is used (the legacy `duckduckgo_search` fallback was removed to shrink the dependency surface).
- Python 3.10+ required (enforced by `run.sh`).
