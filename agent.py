"""
ARIA - Agentic Reasoning Intelligence Assistant
Primitive agentic flow using Ollama (llama3.1:8b) + web search

Architecture:
  1. Intent detection  → classify the query
  2. Forced tool use   → for current-events, ALWAYS search first (don't trust model to decide)
  3. ReAct loop        → for complex multi-step tasks
  4. RL-style learning → evaluate each turn, persist lessons, inject rules next session

Usage:
    python agent.py
    python agent.py --model llama3.2
    python agent.py --debug
"""

import json
import re
import sys
import argparse
import os
import warnings
from datetime import datetime
from pathlib import Path

# Suppress the duckduckgo_search package-rename warning globally
warnings.filterwarnings("ignore", message=".*duckduckgo_search.*renamed.*ddgs.*", category=RuntimeWarning)
warnings.filterwarnings("ignore", message=".*renamed to.*ddgs.*", category=RuntimeWarning)

# ── Configuration ─────────────────────────────────────────────────────────────

OLLAMA_BASE_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL   = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
MAX_TOOL_LOOPS  = 5
SKILLS_FILE     = Path(__file__).parent / "agent_skills.md"
MEMORY_FILE     = Path(__file__).parent / "agent_memory.json"

# Keywords that signal the query is about current/recent information
CURRENT_EVENTS_SIGNALS = [
    "today", "right now", "at this moment", "currently", "latest", "recent",
    "breaking", "news", "what happened", "what's happening", "status of",
    "update on", "this week", "this month", "2024", "2025", "2026",
    "war", "election", "president", "prime minister", "government said",
    "announced", "declared", "signed", "passed", "market", "stock price",
    "weather", "earthquake", "attack", "crisis", "summit", "meeting today",
    "said today", "trump", "biden", "xi", "putin", "modi",
]

# ── Web Search Tool ────────────────────────────────────────────────────────────

def web_search(query: str, num_results: int = 5, mode: str = "auto") -> str:
    """
    Search the web using DuckDuckGo.
    mode: "auto" tries news first for current-events, falls back to text
          "news" — news articles only
          "text" — general web results
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                from ddgs import DDGS
            except ImportError:
                from duckduckgo_search import DDGS

        results = []
        with DDGS() as ddgs:
            # For current-events mode, try news endpoint first (more reliable)
            if mode in ("auto", "news"):
                results = list(ddgs.news(query, max_results=num_results))
            # Fall back to text if news is empty or mode is "text"
            if not results and mode != "news":
                results = list(ddgs.text(query, max_results=num_results))

        if not results:
            return f"No results found for: '{query}'. Try rephrasing the query."

        source_label = "News" if mode in ("auto", "news") else "Web"
        lines = [f"[{source_label} search: '{query}']\n"]
        for i, r in enumerate(results, 1):
            url   = r.get("url") or r.get("href", "")
            body  = r.get("body") or r.get("excerpt", "")
            date  = r.get("date", "")
            lines.append(f"[{i}] {r['title']}{' — ' + date if date else ''}")
            lines.append(f"    {url}")
            lines.append(f"    {body}\n")
        return "\n".join(lines)
    except ImportError:
        return "ERROR: install search library — run: pip install duckduckgo-search"
    except Exception as e:
        return f"Search error: {e}"


def write_essay_outline(topic: str, style: str = "academic", sections: int = 3) -> str:
    """Return a structured essay outline."""
    body = ""
    for i in range(1, sections + 1):
        body += f"\n## Body {i}: [Key argument {i} about {topic}]\n- Evidence:\n- Analysis:\n"
    return (
        f"# Essay Outline: {topic}\n\n"
        f"## Introduction\n- Hook:\n- Background:\n- Thesis:\n"
        f"{body}\n"
        f"## Conclusion\n- Restate thesis:\n- Broader significance:\n"
    )


TOOLS = {
    "web_search":         {"fn": web_search,           "args": ["query", "num_results"]},
    "write_essay_outline":{"fn": write_essay_outline,  "args": ["topic", "style", "sections"]},
}

# ── Intent Detection ───────────────────────────────────────────────────────────

_FILLER = re.compile(
    r"\b(what is|what's|what are|how is|how are|who is|who are|where is|"
    r"tell me about|can you tell me|do you know|give me|the latest on|"
    r"what do you know about|the status of|at this moment|right now|"
    r"currently|today|at the moment|these days|lately|recently)\b",
    re.IGNORECASE,
)

def _clean_search_query(text: str) -> str:
    """Remove question filler words to produce a tighter search phrase."""
    q = _FILLER.sub(" ", text.strip()).rstrip("?!.")
    q = re.sub(r"\s{2,}", " ", q).strip()
    return q[:80] if q else text[:80]


def needs_live_search(query: str) -> bool:
    """Return True if the query is clearly about current/recent events."""
    q = query.lower()
    return any(signal in q for signal in CURRENT_EVENTS_SIGNALS)


def is_essay_request(query: str) -> bool:
    q = query.lower()
    return any(kw in q for kw in ["write an essay", "write essay", "essay on", "essay about"])

# ── RL-Style Memory ────────────────────────────────────────────────────────────

def load_memory() -> dict:
    """Load agent memory from disk."""
    if MEMORY_FILE.exists():
        try:
            return json.loads(MEMORY_FILE.read_text())
        except Exception:
            pass
    return {
        "learned_rules": [],
        "stats": {"turns": 0, "searches_done": 0, "hallucinations_caught": 0, "honest_admits": 0},
        "episodes": [],
    }


def save_memory(mem: dict):
    MEMORY_FILE.write_text(json.dumps(mem, indent=2))


def evaluate_turn(query: str, response: str, tools_used: list, mem: dict) -> dict:
    """
    Heuristic reward function.
    Returns {"score": int, "lessons": list[str]}
    Positive score = good behaviour. Negative = bad.
    """
    score = 0
    lessons = []
    q_lower = query.lower()
    r_lower = response.lower()

    needed_search = needs_live_search(query)
    did_search    = "web_search" in tools_used

    # Reward: searched when needed
    if needed_search and did_search:
        score += 3
        mem["stats"]["searches_done"] += 1

    # Penalty: answered current-events from training without searching
    if needed_search and not did_search:
        score -= 3
        mem["stats"]["hallucinations_caught"] += 1
        lessons.append(
            "LESSON: Query was about current/live events but no web_search was used. "
            "Always call web_search for queries about news, ongoing events, recent statements, or anything time-sensitive."
        )

    # Reward: agent cited sources (URLs in response)
    if "http" in r_lower and did_search:
        score += 1

    # Reward: honest admission of uncertainty
    honest_phrases = ["i don't know", "i'm not certain", "my training data", "i cannot confirm",
                      "you should verify", "i'm unsure", "unclear from search"]
    if any(p in r_lower for p in honest_phrases):
        score += 1
        mem["stats"]["honest_admits"] += 1
        lessons.append("LESSON: Admitting uncertainty is correct behaviour — keep doing this.")

    # Penalty: claiming to have searched but actually hallucinated (searched but fabricated sources)
    if did_search and re.search(r"\[your interaction will be recorded\]", r_lower):
        score -= 2

    mem["stats"]["turns"] += 1
    return {"score": score, "lessons": lessons}


def absorb_lessons(lessons: list, mem: dict):
    """Add new lessons to learned_rules, deduplicate."""
    existing = set(mem["learned_rules"])
    for lesson in lessons:
        if lesson not in existing:
            mem["learned_rules"].append(lesson)
            existing.add(lesson)
    # Keep only the 20 most recent rules to avoid prompt bloat
    if len(mem["learned_rules"]) > 20:
        mem["learned_rules"] = mem["learned_rules"][-20:]

# ── System Prompt ──────────────────────────────────────────────────────────────

def build_system_prompt(mem: dict) -> str:
    skills_text = SKILLS_FILE.read_text() if SKILLS_FILE.exists() else ""
    today = datetime.now().strftime("%Y-%m-%d")

    tools_desc = (
        "  - web_search(query, num_results=5): Search DuckDuckGo for live information.\n"
        "  - write_essay_outline(topic, style, sections): Generate a structured essay outline."
    )

    # Inject learned rules from past sessions
    learned_block = ""
    if mem["learned_rules"]:
        rules = "\n".join(f"  • {r}" for r in mem["learned_rules"][-10:])
        learned_block = f"\n## Rules Learned From Past Experience\n{rules}\n"

    stats = mem["stats"]

    return f"""You are ARIA (Agentic Reasoning Intelligence Assistant).
Today's date: {today}
Your training knowledge cutoff: early 2024. Anything after that REQUIRES web search.

## Character & Honesty
- You are honest, direct, and self-aware about your limitations
- If your training data is outdated for a question, SAY SO and use web_search
- Never fabricate news headlines, quotes, URLs, or statistics
- If search results are ambiguous, say "Based on search results, but please verify:"
- Admit uncertainty with phrases like "I'm not certain" rather than guessing

## Skills
{skills_text}

## Available Tools
{tools_desc}

## How to Use Tools — ReAct Format

When you need a tool, output EXACTLY this pattern then STOP (do not write the results yourself):

THOUGHT: [your reasoning]
ACTION: web_search
ACTION_INPUT: {{"query": "your search query"}}

After you receive OBSERVATION results, continue:

THOUGHT: [what the results tell you]
FINAL_ANSWER: [your response, citing sources]

For no-tool responses:
THOUGHT: [reasoning]
FINAL_ANSWER: [response]

## Hard Rules
1. Current events / news / recent statements → ALWAYS use web_search, NEVER answer from memory
2. STOP after ACTION_INPUT — never generate the observation yourself
3. If web_search returns no useful results, say so honestly
4. Do not roleplay being disconnected from the web — you HAVE web_search, USE it
{learned_block}
## Session Stats (self-awareness)
Searches done: {stats['searches_done']} | Honest admissions: {stats['honest_admits']} | Turns: {stats['turns']}
"""

# ── Ollama Client ──────────────────────────────────────────────────────────────

def ollama_chat(messages: list, model: str, stop_sequences: list = None) -> str:
    import urllib.request
    options = {"temperature": 0.7, "num_predict": 2048}
    if stop_sequences:
        options["stop"] = stop_sequences

    payload = json.dumps({
        "model": model,
        "messages": messages,
        "stream": False,
        "options": options,
    }).encode()

    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())["message"]["content"]
    except urllib.error.URLError as e:
        raise ConnectionError(
            f"Ollama unreachable at {OLLAMA_BASE_URL}. Run: ollama serve\n{e}"
        )


def check_ollama(model: str) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=5) as resp:
            data = json.loads(resp.read())
            available = [m["name"].split(":")[0] for m in data.get("models", [])]
            base = model.split(":")[0]
            if base not in available:
                print(f"  Model '{model}' not found. Available: {available}")
                print(f"  Pull it: ollama pull {model}")
                return False
            return True
    except Exception:
        return False

# ── ReAct Parser ───────────────────────────────────────────────────────────────

def normalize_tags(text: str) -> str:
    """Strip markdown bold/italic from ReAct keywords: **ACTION**: → ACTION:"""
    return re.sub(
        r"\*{1,2}(THOUGHT|ACTION|ACTION_INPUT|FINAL_ANSWER|OBSERVATION)\*{1,2}:?",
        r"\1:",
        text,
    )


def parse_react(text: str) -> dict:
    text = normalize_tags(text)
    result = {"type": "unknown", "thought": "", "action": "", "input": {}, "answer": ""}

    m = re.search(r"THOUGHT:\s*(.+?)(?=ACTION:|FINAL_ANSWER:|$)", text, re.DOTALL | re.IGNORECASE)
    if m:
        result["thought"] = m.group(1).strip()

    # FINAL_ANSWER takes priority
    m = re.search(r"FINAL_ANSWER:\s*(.+)", text, re.DOTALL | re.IGNORECASE)
    if m:
        result["type"] = "answer"
        result["answer"] = m.group(1).strip()
        return result

    am = re.search(r"ACTION:\s*(\w+)", text, re.IGNORECASE)
    im = re.search(r"ACTION_INPUT:\s*(\{.+?\})", text, re.DOTALL | re.IGNORECASE)
    if am:
        result["type"] = "action"
        result["action"] = am.group(1).strip()
        if im:
            try:
                result["input"] = json.loads(im.group(1))
            except json.JSONDecodeError:
                raw = im.group(1)
                kv = re.findall(r'"(\w+)"\s*:\s*"([^"]*)"', raw)
                result["input"] = dict(kv) if kv else {"query": raw.strip("{} \n")}
    return result

# ── Agent Core ─────────────────────────────────────────────────────────────────

def run_agent_turn(
    user_input: str,
    conversation: list,
    model: str,
    debug: bool = False,
) -> tuple[str, list]:
    """
    Run one full agentic turn.
    Returns (final_answer, tools_used_list).

    Strategy:
      Step 1 — Forced tool use: if we detect current-events query, call web_search
               immediately and inject results, bypassing the model's format-following.
      Step 2 — ReAct loop: let the model reason and call further tools if needed.
    """
    tools_used = []
    pre_context = ""

    # ── Step 1: Forced web search for current-events queries ──────────────────
    if needs_live_search(user_input):
        # Derive a clean short search query without an extra LLM call
        auto_query = _clean_search_query(user_input)
        print(f"\n  [Auto-search: \"{auto_query}\"]", flush=True)
        search_results = web_search(auto_query, num_results=6, mode="auto")
        tools_used.append("web_search")
        pre_context = (
            f"[LIVE WEB SEARCH RESULTS — fetched automatically for this current-events query]\n"
            f"{search_results}\n"
            f"[END SEARCH RESULTS]\n\n"
            f"Answer the user's question using ONLY the search results above. "
            f"Cite sources (title + URL) for every key claim. "
            f"If the results don't answer the question, say so honestly — do NOT guess."
        )

    # ── Step 2: Build messages and enter ReAct loop ───────────────────────────
    # Augment the user message with pre-fetched context if available
    augmented_input = (pre_context + "User question: " + user_input) if pre_context else user_input
    conversation.append({"role": "user", "content": user_input})

    loop_messages = list(conversation[:-1])  # exclude the last user msg — we use augmented
    loop_messages.append({"role": "user", "content": augmented_input})

    iterations = 0
    while iterations < MAX_TOOL_LOOPS:
        iterations += 1
        raw = ollama_chat(loop_messages, model, stop_sequences=["OBSERVATION:", "\nOBSERVATION:"])

        if debug:
            print(f"\n  ── DEBUG iter={iterations} ──\n{raw}\n  ──────────────────")

        parsed = parse_react(raw)

        if parsed["type"] == "answer":
            answer = parsed["answer"]
            conversation.append({"role": "assistant", "content": answer})
            return answer, tools_used

        if parsed["type"] == "action":
            tool_name = parsed["action"].lower()
            tool_args = parsed["input"]
            print(f"\n  [Tool: {tool_name}({json.dumps(tool_args)[:70]})]", flush=True)

            if tool_name in TOOLS:
                try:
                    observation = TOOLS[tool_name]["fn"](**tool_args)
                    tools_used.append(tool_name)
                except TypeError as e:
                    observation = f"Bad arguments for {tool_name}: {e}"
                except Exception as e:
                    observation = f"Tool error: {e}"
            else:
                observation = f"Unknown tool '{tool_name}'. Available: {list(TOOLS.keys())}"

            loop_messages.append({"role": "assistant", "content": raw})
            loop_messages.append({
                "role": "user",
                "content": f"OBSERVATION:\n{observation}\n\nContinue your reasoning.",
            })
            continue

        # Model didn't follow format — return raw response
        conversation.append({"role": "assistant", "content": raw})
        return raw, tools_used

    # Hit iteration limit — force wrap-up
    loop_messages.append({"role": "user", "content": "Provide your FINAL_ANSWER now."})
    raw = ollama_chat(loop_messages, model)
    parsed = parse_react(raw)
    answer = parsed["answer"] if parsed["type"] == "answer" else raw
    conversation.append({"role": "assistant", "content": answer})
    return answer, tools_used

# ── CLI ────────────────────────────────────────────────────────────────────────

BANNER = """
╔══════════════════════════════════════════════════════════════╗
║          ARIA — Agentic Reasoning Intelligence               ║
║          Primitive Agentic Flow  |  Self-Learning            ║
╠══════════════════════════════════════════════════════════════╣
║  Chat  |  Essay Writing  |  Current Affairs (live search)    ║
╚══════════════════════════════════════════════════════════════╝"""

HELP_TEXT = """
Commands:
  quit / exit    — End session
  clear          — Reset conversation (keeps learned rules)
  debug          — Toggle debug mode
  memory         — Show learned rules & stats
  help           — This message

Examples:
  > What's happening in the US-Iran situation right now?
  > What did Trump say today about tariffs?
  > Write an essay about renewable energy
  > Explain how black holes form
"""


def main():
    parser = argparse.ArgumentParser(description="ARIA Agentic AI")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    model = args.model
    debug = args.debug

    # Load persistent memory
    mem = load_memory()

    print(BANNER)
    print(f"\n  Model: {model}  |  Ollama: {OLLAMA_BASE_URL}")
    print(f"  Debug: {'ON' if debug else 'OFF'}  |  Learned rules: {len(mem['learned_rules'])}")
    print(f"  Type 'help' for commands\n")

    print("  Checking Ollama...", end=" ", flush=True)
    if not check_ollama(model):
        sys.exit(1)
    print("OK\n")

    system_prompt = build_system_prompt(mem)
    conversation  = [{"role": "system", "content": system_prompt}]

    print("  Ready.\n" + "─" * 64)

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nGoodbye!")
            save_memory(mem)
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit"):
            save_memory(mem)
            print("Memory saved. Goodbye!")
            break

        if user_input.lower() == "clear":
            conversation = [{"role": "system", "content": system_prompt}]
            print("  [Conversation cleared. Learned rules kept.]")
            continue

        if user_input.lower() == "debug":
            debug = not debug
            print(f"  [Debug: {'ON' if debug else 'OFF'}]")
            continue

        if user_input.lower() == "memory":
            s = mem["stats"]
            print(f"\n  Stats: turns={s['turns']} searches={s['searches_done']} "
                  f"honest={s['honest_admits']} hallucinations_caught={s['hallucinations_caught']}")
            if mem["learned_rules"]:
                print("  Learned rules:")
                for r in mem["learned_rules"]:
                    print(f"    
                    • {r[:100]}")
            else:
                print("  No learned rules yet.")
            continue

        if user_input.lower() == "help":
            print(HELP_TEXT)
            continue

        if user_input.lower().startswith("model "):
            new_model = user_input[6:].strip()
            if check_ollama(new_model):
                model = new_model
                print(f"  [Model → {model}]")
            continue

        print("\nARIA:", end=" ", flush=True)

        try:
            response, tools_used = run_agent_turn(user_input, conversation, model, debug)
            print(response)

            # ── RL evaluation: score this turn and learn ──────────────────────
            result = evaluate_turn(user_input, response, tools_used, mem)
            if result["lessons"]:
                absorb_lessons(result["lessons"], mem)
                # Silently save; show only in debug
                if debug:
                    print(f"\n  [RL score={result['score']} | new lessons: {len(result['lessons'])}]")
                    for l in result["lessons"]:
                        print(f"    • {l[:100]}")
            save_memory(mem)

            # Rebuild system prompt with new learned rules (takes effect next turn)
            conversation[0]["content"] = build_system_prompt(mem)

        except ConnectionError as e:
            print(f"\n  Connection error: {e}")
        except Exception as e:
            print(f"\n  Error: {e}")
            if debug:
                import traceback
                traceback.print_exc()

    print("─" * 64)


if __name__ == "__main__":
    main()