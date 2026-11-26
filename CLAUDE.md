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
./run.sh install               # pip install -r requirements.txt
./run.sh check                 # Verify Python ver, ddgs, fastmcp, sqlite3, Ollama
```

In-CLI commands: `clear` (reset conversation, keep learned rules), `memory` (show RL rules + stats), `sources` (show ranked outlets), `model <name>`, `debug`, `help`.

There is no test suite, linter, or build step — this is a pure-Python script project.

## Architecture

The system is structured around a **single source of truth for tools** (`tools.py`) consumed by two different runtimes. Never reimplement a tool in `agent.py` or `mcp_agent_server.py` — fix it in `tools.py` and both consumers inherit the fix.

```
CLI ─→ agent.py ──┐
                  ├─→ tools.py ─→ DuckDuckGo / SQLite / web fetch
MCP client ─→ mcp_agent_server.py ─┘
```

### Layers

- **`tools.py`** — All tool functions: `web_search`, `web_fetch`, `write_essay`, plus the four self-learning tools (`rate_source`, `get_best_sources`, `log_writing_feedback`, `recall_writing_feedback`). Owns the SQLite schema (`agent_memory.db`, tables `source_quality` and `writing_feedback`) — created lazily by `_db()` on first use.
- **`agent.py`** — Ollama ReAct loop. Three things to know:
  1. **Forced tool use**: `needs_live_search()` keyword-matches against `CURRENT_EVENTS_SIGNALS`; if it hits, `run_agent_turn` calls `web_search` *before* the LLM ever sees the query and injects results as `pre_context`. This bypasses the LLM's format-following for reliability on small models.
  2. **ReAct parser** (`parse_react`) expects `THOUGHT/ACTION/ACTION_INPUT/FINAL_ANSWER`. The stop sequence `OBSERVATION:` prevents the model from hallucinating tool results. JSON parse failures fall back to regex key/value extraction.
  3. **RL-style memory** (`agent_memory.json`): `evaluate_turn` scores each turn and `absorb_lessons` writes new rules into `learned_rules` (capped at 20). The system prompt is rebuilt after every turn so new lessons take effect immediately.
- **`mcp_agent_server.py`** — FastMCP wrapper. Registers the seven shared tools via a loop, then adds one MCP-only tool: `remember_context` (key-value writes to `memory.md`). Do not duplicate this tool in `agent.py` — the CLI uses the SQLite/JSON memory instead.
- **`skills/*.md`** — Prompt-injected playbooks loaded by `_load_skills()`. `news_search.md` and `self_learning.md` always load; `essay_writing.md` only loads when `is_essay_request()` matches, to keep context lean for small models.

### Two memory systems (do not conflate)

- `agent_memory.db` (SQLite, owned by `tools.py`): cross-session source quality rankings + writing feedback. Aggregated via `AVG()`/`COUNT()`.
- `agent_memory.json` (owned by `agent.py`): the RL heuristic — `learned_rules`, `stats`, `episodes`. Only used by the CLI, not by the MCP server.

### Intent routing

`is_essay_request()` and `needs_live_search()` are deliberate keyword classifiers, not LLM calls — they run before the model and decide (a) whether to force a search, (b) whether to load `essay_writing.md` into the prompt. When adding new intent categories, extend these lists rather than introducing a separate classifier.

## Conventions

- Hard rule baked into the system prompt: `write_essay` must NEVER be called unprompted. Search queries get summarised with citations; only explicit essay/report/analysis requests get the essay scaffold.
- `write_essay` returns a scaffold with `[Agent: ...]` placeholders that the LLM must expand into prose — it is not a finished essay.
- DuckDuckGo search tries `ddgs.news()` first (better recency), falls back to `ddgs.text()`. The `ddgs` package is preferred; `duckduckgo_search` is the legacy fallback import.
- Python 3.10+ required (enforced by `run.sh`).
