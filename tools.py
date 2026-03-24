"""
tools.py — Single source of truth for all ARIA agent tools.

Both agent.py (Ollama ReAct loop) and mcp_agent_server.py (MCP server)
import from here. Fix a bug once; both consumers get the fix.
"""

import re
import sqlite3
import warnings
from contextlib import closing
from pathlib import Path

DB_PATH = str(Path(__file__).parent / "agent_memory.db")

# ── SQLite helpers ────────────────────────────────────────────────────────────

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

# ── Research tools ────────────────────────────────────────────────────────────

def web_search(query: str, num_results: int = 10, mode: str = "auto") -> str:
    """Search the web using DuckDuckGo.

    mode: 'auto'  — tries news endpoint first (better for current affairs), falls back to text
          'news'  — news articles only
          'text'  — general web results

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
        return "ERROR: search library not installed — run: pip install ddgs"
    except Exception as e:
        return f"Search error: {e}"


def web_fetch(url: str, timeout: int = 15) -> str:
    """Fetch the full text of a news article by URL.
    Use after web_search to read the complete article from a news outlet.
    """
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

# ── Writing tools ─────────────────────────────────────────────────────────────

def write_essay(
    topic: str,
    thesis: str,
    key_arguments: list,
    evidence: list,
    counterargument: str = "",
    style: str = "think-tank",
) -> str:
    """Return a structured think-tank essay scaffold.
    Expand every [Agent:...] placeholder into full prose.

    Args:
        topic:           The news event or policy issue being analysed.
        thesis:          The central argument or position of the essay.
        key_arguments:   List of 2–4 argument headings (strings).
        evidence:        List of evidence items, one per argument (strings).
        counterargument: A steel-man of the opposing view (optional).
        style:           'think-tank' (default) | 'op-ed' | 'briefing'
    """
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
        "think-tank": "Authoritative, evidence-driven, policy-oriented. Cite sources inline. Avoid partisan language.",
        "op-ed":      "Direct and persuasive. First person allowed. Shorter paragraphs. Hook the reader.",
        "briefing":   "Concise. Use bullet points under each section. Aimed at a policymaker audience.",
    }.get(style, "Authoritative and evidence-driven.")

    return f"""# {topic}

> **Style:** {style} — {style_note}

## Executive Summary

[Agent: 2–3 sentences. State the issue, the thesis, and why it matters now.]

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

# ── Self-learning tools (SQLite) ──────────────────────────────────────────────

def rate_source(source_name: str, quality: int, reason: str, topic_tag: str = "general") -> str:
    """Rate a news source 1–5 after reading it. Builds the source quality ranking over time.

    Args:
        source_name: Outlet name, e.g. 'Reuters', 'BBC', 'Straits Times'.
        quality:     1 (poor) → 5 (excellent/authoritative).
        reason:      One specific sentence explaining the score.
        topic_tag:   Broad topic bucket: 'geopolitics', 'economy', etc.
    """
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
    """Return top-ranked news sources by average quality score.
    Call at the START of every research session to prioritise outlets.

    Args:
        topic_tag: Filter by topic ('geopolitics', 'economy', etc.) or 'general' for all.
        limit:     Maximum number of sources to return.
    """
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
    """Log what worked or failed in an essay section. Call after every essay.

    Args:
        component:       'thesis' | 'counterargument' | 'conclusion' | 'argument' |
                         'executive_summary' | 'recommendations' | 'overall'
        feedback:        Specific, actionable note on what worked or failed.
        sentiment:       'positive' (worked well) | 'negative' (needs improvement)
        content_snippet: Optional excerpt (≤300 chars) of the text that was judged.
        topic_tag:       Broad topic bucket for context.
    """
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
        label = "✓ positive" if sentiment == "positive" else "✗ negative"
        return f"Logged [{label}] feedback for '{component}': {feedback[:120]}"
    except Exception as e:
        return f"log_writing_feedback error: {e}"


def recall_writing_feedback(component: str = "all", limit: int = 8) -> str:
    """Retrieve past writing lessons before drafting an essay section.
    Call BEFORE writing each section to load accumulated guidance.

    Args:
        component: Section to recall lessons for, or 'all' for everything recent.
        limit:     Number of most-recent entries to return.
    """
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
            return (
                f"No writing feedback yet for '{component}'. "
                "Use log_writing_feedback() after each essay to build up guidance."
            )

        neg = [r for r in rows if r["sentiment"] == -1]
        pos = [r for r in rows if r["sentiment"] == 1]
        lines = [f"Writing guidance recalled for component='{component}':\n"]
        if neg:
            lines.append("## What to AVOID (past mistakes)")
            for r in neg:
                lines.append(f"  [{r['component']}] {r['feedback']}")
        if pos:
            lines.append("\n## What WORKS (patterns to repeat)")
            for r in pos:
                lines.append(f"  [{r['component']}] {r['feedback']}")
        lines.append("\nApply the above before drafting. Do not repeat flagged mistakes.")
        return "\n".join(lines)
    except Exception as e:
        return f"recall_writing_feedback error: {e}"
