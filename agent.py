"""
ARIA - Agentic Reasoning Intelligence Assistant
Agentic flow using Ollama + live web search + self-learning memory

Architecture:
  1. Intent detection  → classify the query (search / essay / general)
  2. Forced tool use   → for current-events, ALWAYS search first
  3. ReAct loop        → for complex multi-step tasks
  4. RL-style learning → evaluate each turn, persist lessons, inject rules next session
  5. SQLite memory     → source quality rankings + writing feedback across sessions

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
import random
import sqlite3
import warnings
from contextlib import closing
from datetime import datetime
from pathlib import Path

# ── Suppress noisy warnings ───────────────────────────────────────────────────
warnings.filterwarnings("ignore", message=".*duckduckgo_search.*renamed.*ddgs.*", category=RuntimeWarning)
warnings.filterwarnings("ignore", message=".*renamed to.*ddgs.*", category=RuntimeWarning)

# ── Configuration ─────────────────────────────────────────────────────────────

OLLAMA_BASE_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL   = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
MAX_TOOL_LOOPS  = 5
SKILLS_DIR      = Path(__file__).parent / "skills"
MEMORY_FILE     = Path(__file__).parent / "agent_memory.json"
DB_PATH         = str(Path(__file__).parent / "agent_memory.db")

# ── Thinking Vocabulary ───────────────────────────────────────────────────────
# 100 vivid words grouped by agent phase. Each _status() call picks randomly.

_WORDS = {
    "searching": [
        "Excavating", "Scouring", "Trawling", "Prospecting", "Unearthing",
        "Spelunking", "Foraging", "Dredging", "Gleaning", "Winnowing",
        "Sifting", "Combing", "Canvassing", "Ferreting", "Sniffing out",
        "Rummaging", "Harvesting", "Panning", "Surveying", "Hunting down",
    ],
    "reading": [
        "Imbibing", "Devouring", "Digesting", "Perusing", "Scrutinising",
        "Absorbing", "Assimilating", "Savouring", "Drinking in", "Ingesting",
        "Unpacking", "Parsing", "Dissecting", "Unwrapping", "Steeping in",
    ],
    "thinking": [
        "Ruminating", "Cogitating", "Deliberating", "Pondering", "Musing",
        "Mulling", "Brooding", "Meditating", "Contemplating", "Incubating",
        "Percolating", "Marinating", "Fermenting", "Distilling", "Crystallising",
        "Coalescing", "Synthesising", "Triangulating", "Extrapolating", "Theorising",
        "Hypothesising", "Surmising", "Calibrating", "Deciphering", "Unravelling",
        "Illuminating", "Conjuring", "Channelling", "Kindling", "Stoking",
    ],
    "writing": [
        "Weaving", "Sculpting", "Architecting", "Forging", "Chiselling",
        "Fashioning", "Moulding", "Composing", "Orchestrating", "Inscribing",
        "Etching", "Rendering", "Burnishing", "Tempering", "Honing",
        "Polishing", "Concocting", "Brewing", "Simmering", "Distilling",
    ],
    "remembering": [
        "Consulting", "Recalling", "Retrieving", "Archiving", "Chronicling",
        "Cataloguing", "Indexing", "Committing", "Encoding", "Decoding",
        "Translating", "Manifesting", "Germinating", "Cultivating", "Refining",
    ],
}

_SUFFIXES = {
    "searching":   ["the intelligence feeds", "the newswires", "the global dispatch",
                    "the archives", "the open sources", "the signal from the noise",
                    "the world's front pages", "the record"],
    "reading":     ["the full dispatch", "the source material", "the primary account",
                    "the raw intelligence", "every line", "the fine print"],
    "thinking":    ["the angles", "the implications", "the deeper current",
                    "the threads", "the evidence", "the argument",
                    "what this means", "the subtext", "the narrative",
                    "the weight of it", "the possibilities"],
    "writing":     ["the argument", "the thesis", "the analysis",
                    "the narrative arc", "the intellectual frame",
                    "the case", "the essay", "the brief"],
    "remembering": ["past wisdom", "the lessons", "the source rankings",
                    "accumulated experience", "the record", "what was learned"],
}


def _status(phase: str, detail: str = "") -> None:
    """Print a vivid single-line status message matched to the current phase."""
    verb   = random.choice(_WORDS.get(phase, _WORDS["thinking"]))
    suffix = random.choice(_SUFFIXES.get(phase, _SUFFIXES["thinking"]))
    extra  = f" — {detail}" if detail else ""
    print(f"\n  ✦ {verb} {suffix}{extra}...", flush=True)

# ── Current-events signals ────────────────────────────────────────────────────

CURRENT_EVENTS_SIGNALS = [
    "today", "right now", "at this moment", "currently", "latest", "recent",
    "breaking", "news", "what happened", "what's happening", "status of",
    "update on", "this week", "this month", "2024", "2025", "2026",
    "war", "election", "president", "prime minister", "government said",
    "announced", "declared", "signed", "passed", "market", "stock price",
    "weather", "earthquake", "attack", "crisis", "summit", "meeting today",
    "said today", "trump", "biden", "xi", "putin", "modi",
]

# ── Tool functions ────────────────────────────────────────────────────────────

def web_search(query: str, num_results: int = 10, mode: str = "auto") -> str:
    """
    Search the web using DuckDuckGo.
    mode: "auto" tries news first (better for current affairs), falls back to text
          "news" — news articles only
          "text" — general web results
    Supports site-scoped queries: 'site:reuters.com Ukraine war'
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
            if mode in ("auto", "news"):
                results = list(ddgs.news(query, max_results=num_results))
            if not results and mode != "news":
                results = list(ddgs.text(query, max_results=num_results))

        if not results:
            return f"No results found for: '{query}'. Try rephrasing the query."

        source_label = "News" if mode in ("auto", "news") else "Web"
        lines = [f"[{source_label} search: '{query}']\n"]
        for i, r in enumerate(results, 1):
            url  = r.get("url") or r.get("href", "")
            body = r.get("body") or r.get("excerpt", "")
            date = r.get("date", "")
            lines.append(f"[{i}] {r['title']}{' — ' + date if date else ''}")
            lines.append(f"    {url}")
            lines.append(f"    {body}\n")
        return "\n".join(lines)
    except ImportError:
        return "ERROR: install search library — run: pip install ddgs"
    except Exception as e:
        return f"Search error: {e}"


def web_fetch(url: str, timeout: int = 15) -> str:
    """Fetch the full text of a news article by URL. Use after web_search to read the full piece."""
    try:
        import urllib.request
        import html as _html
        headers = {"User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", raw, flags=re.DOTALL | re.IGNORECASE)
        title_m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.IGNORECASE | re.DOTALL)
        title = _html.unescape(title_m.group(1).strip()) if title_m else "No title"
        text = re.sub(r"<[^>]+>", " ", raw)
        text = _html.unescape(text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if len(text) > 8000:
            text = text[:8000] + "\n\n[... truncated ...]"
        return f"Title: {title}\nURL: {url}\n\n{text}"
    except Exception as e:
        return f"Fetch error for {url}: {e}"


def write_essay(
    topic: str,
    thesis: str,
    key_arguments: list,
    evidence: list,
    counterargument: str = "",
    style: str = "think-tank",
) -> str:
    """Return a structured think-tank essay scaffold. Expand every [Agent:...] block into full prose."""
    args_block = ""
    for i, (arg, ev) in enumerate(zip(key_arguments, evidence), 1):
        args_block += f"\n### Argument {i}: {arg}\n\n{ev}\n"

    counter_block = ""
    if counterargument:
        counter_block = (
            f"\n## Counterargument & Rebuttal\n\n{counterargument}\n\n"
            "[Agent: rebut above — show why thesis still holds]\n"
        )

    style_note = {
        "think-tank": "Authoritative, evidence-driven, policy-oriented. Cite sources inline.",
        "op-ed":      "Direct and persuasive. First person allowed. Hook the reader.",
        "briefing":   "Concise bullets. Aimed at a policymaker. BLUF at the top.",
    }.get(style, "Authoritative and evidence-driven.")

    return f"""# {topic}

> **Style:** {style} — {style_note}

## Executive Summary

[Agent: 2–3 sentences — issue, thesis, why it matters now.]

## Background & Context

[Agent: key actors, what triggered this, historical/geopolitical backdrop.]

## Thesis

{thesis}

## Analysis
{args_block}
{counter_block}
## Implications & Outlook

[Agent: short-term vs long-term consequences. Regional and global ripple effects.]

## Policy Recommendations

[Agent: 3–5 concrete, actionable recommendations.]

## Conclusion

[Agent: restate thesis. End with a forward-looking provocation — not a summary.]

---
*Sources: [Agent: list all outlets and URLs used]*
"""

# ── Self-Learning Tools (SQLite) ──────────────────────────────────────────────

def _db() -> sqlite3.Connection:
    """Open (or create) the SQLite DB and ensure schema exists. Caller must close."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS source_quality (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            source_name TEXT    NOT NULL,
            topic_tag   TEXT    NOT NULL DEFAULT 'general',
            quality     INTEGER NOT NULL CHECK(quality BETWEEN 1 AND 5),
            reason      TEXT,
            ts          TEXT    DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS writing_feedback (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            component       TEXT    NOT NULL,
            topic_tag       TEXT    NOT NULL DEFAULT 'general',
            content_snippet TEXT,
            feedback        TEXT    NOT NULL,
            sentiment       INTEGER NOT NULL CHECK(sentiment IN (-1, 1)),
            ts              TEXT    DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    return conn


def rate_source(source_name: str, quality: int, reason: str, topic_tag: str = "general") -> str:
    """Rate a news source 1–5 after reading it. Builds the source quality ranking over time."""
    if not 1 <= int(quality) <= 5:
        return "Error: quality must be 1–5."
    try:
        with closing(_db()) as conn:
            conn.execute(
                "INSERT INTO source_quality (source_name, topic_tag, quality, reason) VALUES (?,?,?,?)",
                (source_name.strip(), topic_tag.strip().lower(), int(quality), reason.strip()),
            )
            conn.commit()
        return f"Rated '{source_name}' {quality}/5 [{topic_tag}]: {reason}"
    except Exception as e:
        return f"rate_source error: {e}"


def get_best_sources(topic_tag: str = "general", limit: int = 10) -> str:
    """Return top-ranked news sources by average quality score. Call at the start of research."""
    try:
        with closing(_db()) as conn:
            if topic_tag == "general":
                rows = conn.execute("""
                    SELECT source_name,
                           ROUND(AVG(quality), 2) AS avg_score,
                           COUNT(*)               AS uses,
                           MAX(reason)            AS latest_reason
                    FROM source_quality
                    GROUP BY source_name
                    ORDER BY avg_score DESC, uses DESC
                    LIMIT ?
                """, (limit,)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT source_name,
                           ROUND(AVG(quality), 2) AS avg_score,
                           COUNT(*)               AS uses,
                           MAX(reason)            AS latest_reason
                    FROM source_quality
                    WHERE topic_tag = ?
                    GROUP BY source_name
                    ORDER BY avg_score DESC, uses DESC
                    LIMIT ?
                """, (topic_tag.lower(), limit)).fetchall()

        if not rows:
            return "No source ratings yet. Use rate_source() after each search to build rankings."
        lines = [f"Source rankings [topic={topic_tag}]:\n",
                 f"{'#':<4} {'Source':<25} {'Avg':>5} {'Uses':>5}  Note"]
        lines.append("-" * 72)
        for i, r in enumerate(rows, 1):
            lines.append(
                f"{i:<4} {r['source_name']:<25} {r['avg_score']:>5} {r['uses']:>5}  {r['latest_reason'] or ''}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"get_best_sources error: {e}"


def log_writing_feedback(
    component: str,
    feedback: str,
    sentiment: str,
    content_snippet: str = "",
    topic_tag: str = "general",
) -> str:
    """Log what worked or failed in a section. Call after every essay. sentiment='positive'|'negative'."""
    s_map = {"positive": 1, "negative": -1}
    if sentiment not in s_map:
        return "Error: sentiment must be 'positive' or 'negative'."
    try:
        with closing(_db()) as conn:
            conn.execute(
                "INSERT INTO writing_feedback "
                "(component, topic_tag, content_snippet, feedback, sentiment) VALUES (?,?,?,?,?)",
                (component.strip().lower(), topic_tag.lower(),
                 content_snippet[:300].strip(), feedback.strip(), s_map[sentiment]),
            )
            conn.commit()
        label = "✓" if sentiment == "positive" else "✗"
        return f"Logged [{label}] on '{component}': {feedback[:100]}"
    except Exception as e:
        return f"log_writing_feedback error: {e}"


def recall_writing_feedback(component: str = "all", limit: int = 8) -> str:
    """Retrieve past writing lessons before drafting a section. Call before writing each section."""
    try:
        with closing(_db()) as conn:
            if component == "all":
                rows = conn.execute(
                    "SELECT component, feedback, sentiment, ts FROM writing_feedback "
                    "ORDER BY ts DESC LIMIT ?", (limit,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT component, feedback, sentiment, ts FROM writing_feedback "
                    "WHERE component=? ORDER BY ts DESC LIMIT ?",
                    (component.strip().lower(), limit)
                ).fetchall()
        if not rows:
            return f"No writing feedback yet for '{component}'. Use log_writing_feedback() after essays."
        neg = [r for r in rows if r["sentiment"] == -1]
        pos = [r for r in rows if r["sentiment"] == 1]
        lines = [f"Writing guidance for component='{component}':\n"]
        if neg:
            lines.append("## AVOID (past mistakes)")
            for r in neg:
                lines.append(f"  [{r['component']}] {r['feedback']}")
        if pos:
            lines.append("\n## REPEAT (what worked)")
            for r in pos:
                lines.append(f"  [{r['component']}] {r['feedback']}")
        lines.append("\nApply above before drafting. Do not repeat flagged mistakes.")
        return "\n".join(lines)
    except Exception as e:
        return f"recall_writing_feedback error: {e}"


TOOLS = {
    "web_search":              {"fn": web_search,              "args": ["query", "num_results", "mode"]},
    "web_fetch":               {"fn": web_fetch,               "args": ["url"]},
    "write_essay":             {"fn": write_essay,             "args": ["topic", "thesis", "key_arguments", "evidence", "counterargument", "style"]},
    "rate_source":             {"fn": rate_source,             "args": ["source_name", "quality", "reason", "topic_tag"]},
    "get_best_sources":        {"fn": get_best_sources,        "args": ["topic_tag", "limit"]},
    "log_writing_feedback":    {"fn": log_writing_feedback,    "args": ["component", "feedback", "sentiment", "content_snippet", "topic_tag"]},
    "recall_writing_feedback": {"fn": recall_writing_feedback, "args": ["component", "limit"]},
}

# ── Intent Detection ──────────────────────────────────────────────────────────

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
    """Return True if the user explicitly wants a written piece (essay, report, analysis, etc.)."""
    q = query.lower()
    return any(kw in q for kw in [
        "write an essay", "write essay", "essay on", "essay about",
        "write a report", "write report", "write an analysis", "write analysis",
        "write a brief", "write a briefing", "write an op-ed", "write op-ed",
        "deep-dive", "deep dive", "in-depth analysis", "analytical piece",
        "analyse ", "analyze ", "give me an analysis", "give me a report",
        "think-tank", "thinktank", "policy brief", "research paper",
    ])

# ── RL-Style Memory ───────────────────────────────────────────────────────────

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
    """
    score = 0
    lessons = []
    r_lower = response.lower()

    needed_search = needs_live_search(query)
    did_search    = "web_search" in tools_used

    if needed_search and did_search:
        score += 3
        mem["stats"]["searches_done"] += 1

    if needed_search and not did_search:
        score -= 3
        mem["stats"]["hallucinations_caught"] += 1
        lessons.append(
            "LESSON: Query was about current/live events but no web_search was used. "
            "Always call web_search for queries about news, ongoing events, or anything time-sensitive."
        )

    if "http" in r_lower and did_search:
        score += 1

    honest_phrases = ["i don't know", "i'm not certain", "my training data", "i cannot confirm",
                      "you should verify", "i'm unsure", "unclear from search"]
    if any(p in r_lower for p in honest_phrases):
        score += 1
        mem["stats"]["honest_admits"] += 1
        lessons.append("LESSON: Admitting uncertainty is correct behaviour — keep doing this.")

    mem["stats"]["turns"] += 1
    return {"score": score, "lessons": lessons}


def absorb_lessons(lessons: list, mem: dict):
    """Add new lessons to learned_rules, deduplicate, keep last 20."""
    existing = set(mem["learned_rules"])
    for lesson in lessons:
        if lesson not in existing:
            mem["learned_rules"].append(lesson)
            existing.add(lesson)
    if len(mem["learned_rules"]) > 20:
        mem["learned_rules"] = mem["learned_rules"][-20:]

# ── System Prompt ─────────────────────────────────────────────────────────────

_skills_cache: str = ""


def _load_skills(essay_mode: bool = False) -> str:
    """
    Load skill files from skills/ directory.
    Loads only relevant files to keep the system prompt lean for small models:
      - Always: news_search.md, self_learning.md
      - Essay mode only: essay_writing.md
    Results are cached after the first load.
    """
    global _skills_cache
    if not SKILLS_DIR.exists():
        return ""

    targets = ["news_search.md", "self_learning.md"]
    if essay_mode:
        targets.append("essay_writing.md")

    parts = []
    for name in targets:
        path = SKILLS_DIR / name
        if path.exists():
            parts.append(path.read_text())
    return "\n\n---\n\n".join(parts)


def build_system_prompt(mem: dict, essay_mode: bool = False) -> str:
    skills_text = _load_skills(essay_mode=essay_mode)
    today = datetime.now().strftime("%Y-%m-%d")

    tools_desc = (
        "  ## Research\n"
        "  - web_search(query, num_results=10, mode='auto'): Search DuckDuckGo. Supports site:outlet.com queries.\n"
        "  - web_fetch(url): Fetch full article text from a URL. Use after web_search.\n\n"
        "  ## Writing\n"
        "  - write_essay(topic, thesis, key_arguments, evidence, counterargument='', style='think-tank'): "
        "Get a think-tank essay scaffold. Expand every [Agent:...] block into full prose.\n\n"
        "  ## Self-Learning (call every session to improve over time)\n"
        "  - get_best_sources(topic_tag='general'): Ranked source quality table — call BEFORE searching.\n"
        "  - rate_source(source_name, quality, reason, topic_tag): Rate a source 1–5 — call AFTER reading each article.\n"
        "  - recall_writing_feedback(component='all'): Past writing lessons — call BEFORE writing each section.\n"
        "  - log_writing_feedback(component, feedback, sentiment, content_snippet, topic_tag): Log a lesson — call AFTER finishing the essay."
    )

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
5. NEVER call write_essay unless the user explicitly asks for an essay, analysis piece, report, deep-dive, or briefing. A search or news question → search and summarise with citations only. Do not produce an essay unprompted.
{learned_block}
## Session Stats (self-awareness)
Searches done: {stats['searches_done']} | Honest admissions: {stats['honest_admits']} | Turns: {stats['turns']}
"""

# ── Ollama Client ─────────────────────────────────────────────────────────────

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
            f"Ollama unreachable at {OLLAMA_BASE_URL}. Is it running? Try: ollama serve\n{e}"
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
    except Exception as e:
        print(f"  Cannot reach Ollama at {OLLAMA_BASE_URL}. Start it with: ollama serve")
        print(f"  Error: {e}")
        return False

# ── ReAct Parser ──────────────────────────────────────────────────────────────

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

    m = re.search(r"FINAL_ANSWER:\s*(.+)", text, re.DOTALL | re.IGNORECASE)
    if m:
        result["type"] = "answer"
        result["answer"] = m.group(1).strip()
        return result

    am = re.search(r"ACTION:\s*(\w+)", text, re.IGNORECASE)
    # Use a greedy match from { to the last } to handle nested JSON correctly
    im = re.search(r"ACTION_INPUT:\s*(\{.+\})", text, re.DOTALL | re.IGNORECASE)
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

# ── Agent Core ────────────────────────────────────────────────────────────────

def run_agent_turn(
    user_input: str,
    conversation: list,
    model: str,
    debug: bool = False,
) -> tuple[str, list]:
    """
    Run one full agentic turn. Returns (final_answer, tools_used_list).

    Strategy:
      Step 1 — Forced tool use: if current-events query detected, search immediately
               and inject results, bypassing model format-following for reliability.
      Step 2 — ReAct loop: let the model reason and call further tools if needed.
    """
    tools_used = []
    pre_context = ""
    essay_mode  = is_essay_request(user_input)

    # ── Step 1: Forced web search for current-events queries ──────────────────
    if needs_live_search(user_input):
        auto_query = _clean_search_query(user_input)
        _status("searching", auto_query)
        search_results = web_search(auto_query, num_results=6, mode="auto")
        tools_used.append("web_search")

        if essay_mode:
            pre_context = (
                f"[LIVE WEB SEARCH RESULTS — fetched automatically]\n"
                f"{search_results}\n"
                f"[END SEARCH RESULTS]\n\n"
                f"The user has explicitly requested an essay or analysis. "
                f"Use the search results above as your evidence base, then call write_essay() "
                f"with a clear thesis and structured arguments. Cite sources inline."
            )
        else:
            pre_context = (
                f"[LIVE WEB SEARCH RESULTS — fetched automatically for this current-events query]\n"
                f"{search_results}\n"
                f"[END SEARCH RESULTS]\n\n"
                f"Answer the user's question using ONLY the search results above. "
                f"Summarise and cite sources (title + URL) for every key claim. "
                f"Do NOT call write_essay — this is a search query, not an essay request. "
                f"If the results don't answer the question, say so honestly."
            )

    # ── Step 2: Rebuild system prompt with context-appropriate skills ─────────
    # Update the system message to include/exclude essay skills based on intent
    if conversation and conversation[0]["role"] == "system":
        conversation[0]["content"] = build_system_prompt(
            json.loads(MEMORY_FILE.read_text()) if MEMORY_FILE.exists() else load_memory(),
            essay_mode=essay_mode,
        )

    # ── Step 3: Build messages and enter ReAct loop ───────────────────────────
    augmented_input = (pre_context + "User question: " + user_input) if pre_context else user_input
    conversation.append({"role": "user", "content": user_input})

    loop_messages = list(conversation[:-1])
    loop_messages.append({"role": "user", "content": augmented_input})

    iterations = 0
    while iterations < MAX_TOOL_LOOPS:
        iterations += 1
        _status("thinking")
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
            _tool_phase = {
                "web_search":              "searching",
                "web_fetch":               "reading",
                "write_essay":             "writing",
                "rate_source":             "remembering",
                "get_best_sources":        "remembering",
                "log_writing_feedback":    "remembering",
                "recall_writing_feedback": "remembering",
            }.get(tool_name, "thinking")
            _tool_detail = (tool_args.get("query") or
                            tool_args.get("url", "")[:60] or
                            tool_args.get("topic", ""))
            _status(_tool_phase, _tool_detail)

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

        conversation.append({"role": "assistant", "content": raw})
        return raw, tools_used

    # Hit iteration limit — force wrap-up
    loop_messages.append({"role": "user", "content": "Provide your FINAL_ANSWER now."})
    _status("thinking")
    raw = ollama_chat(loop_messages, model)
    parsed = parse_react(raw)
    answer = parsed["answer"] if parsed["type"] == "answer" else raw
    conversation.append({"role": "assistant", "content": answer})
    return answer, tools_used

# ── CLI ───────────────────────────────────────────────────────────────────────

BANNER = """
╔══════════════════════════════════════════════════════════════╗
║          ARIA — Agentic Reasoning Intelligence               ║
║          Self-Learning  |  Live Search  |  Think-Tank        ║
╠══════════════════════════════════════════════════════════════╣
║  Search  |  Essay Writing  |  Current Affairs                ║
╚══════════════════════════════════════════════════════════════╝"""

HELP_TEXT = """
Commands:
  quit / exit    — End session
  clear          — Reset conversation (keeps learned rules)
  debug          — Toggle debug mode
  memory         — Show learned rules & stats
  sources        — Show source quality rankings from memory
  help           — This message
  model <name>   — Switch Ollama model

Examples:
  > What's happening in the South China Sea right now?
  > Write a think-tank essay about US-China trade tensions
  > Analyse the latest developments in the Middle East
  > Explain how black holes form
"""


def cmd_sources() -> None:
    """Print current source quality rankings."""
    result = get_best_sources(topic_tag="general", limit=20)
    print(f"\n{result}")


def main():
    parser = argparse.ArgumentParser(description="ARIA Agentic AI")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    model = args.model
    debug = args.debug

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
                    print(f"    • {r[:100]}")
            else:
                print("  No learned rules yet.")
            continue

        if user_input.lower() == "sources":
            cmd_sources()
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

        try:
            response, tools_used = run_agent_turn(user_input, conversation, model, debug)
            print(f"\nARIA: {response}")

            result = evaluate_turn(user_input, response, tools_used, mem)
            if result["lessons"]:
                absorb_lessons(result["lessons"], mem)
                if debug:
                    print(f"\n  [RL score={result['score']} | new lessons: {len(result['lessons'])}]")
                    for lesson in result["lessons"]:
                        print(f"    • {lesson[:100]}")
            save_memory(mem)

            # Rebuild system prompt after learning (takes effect next turn)
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
