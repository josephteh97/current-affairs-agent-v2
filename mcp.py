"""
MCP agent tools server
Exposes: web_search, web_fetch, write_essay, remember_context,
         rate_source, get_best_sources, log_writing_feedback, recall_writing_feedback
Run: python mcp.py
"""

import os
import sqlite3

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(name="Agent MCP Server")

# ---------------------------------------------------------------------------
# Persistent SQLite memory — self-learning store
# ---------------------------------------------------------------------------

_DB_PATH = os.path.join(os.path.dirname(__file__), "agent_memory.db")


def _db() -> sqlite3.Connection:
    """Open (or create) the SQLite DB and ensure schema exists."""
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS source_quality (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            source_name  TEXT    NOT NULL,
            topic_tag    TEXT    NOT NULL DEFAULT 'general',
            quality      INTEGER NOT NULL CHECK(quality BETWEEN 1 AND 5),
            reason       TEXT,
            ts           TEXT    DEFAULT (datetime('now'))
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

@mcp.tool()
def web_search(query: str, num_results: int = 10) -> str:
    """Search the web for current news, facts, and information using DuckDuckGo.
    Use this for any question about recent events, current affairs, or time-sensitive info.
    Supports site-scoped queries e.g. 'site:reuters.com Ukraine war'.
    """
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=num_results))

        if not results:
            return f"No results found for: {query}"

        lines = [f"Search results for: '{query}'\n"]

        for i, r in enumerate(results, 1):
            lines.append(f"[{i}] {r['title']}")
            lines.append(f"    URL: {r['href']}")
            lines.append(f"    {r['body']}\n")

        return "\n".join(lines)

    except ImportError:
        return "Error: ddgs not installed. Run: pip install ddgs"
    except Exception as e:
        return f"Search error: {e}"


@mcp.tool()
def web_fetch(url: str, timeout: int = 15) -> str:
    """Fetch the full text content of a webpage by URL.
    Use this after web_search to read the full article from a news outlet.
    Returns the page title, URL, and extracted body text.
    """
    try:
        import urllib.request
        import html
        import re

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")

        # Strip scripts and styles
        raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", raw, flags=re.DOTALL | re.IGNORECASE)
        # Extract title
        title_match = re.search(r"<title[^>]*>(.*?)</title>", raw, re.IGNORECASE | re.DOTALL)
        title = html.unescape(title_match.group(1).strip()) if title_match else "No title"
        # Strip remaining tags and decode entities
        text = re.sub(r"<[^>]+>", " ", raw)
        text = html.unescape(text)
        # Collapse whitespace
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text.strip()

        # Cap output to avoid flooding context
        max_chars = 8000
        if len(text) > max_chars:
            text = text[:max_chars] + "\n\n[... content truncated ...]"

        return f"Title: {title}\nURL: {url}\n\n{text}"

    except Exception as e:
        return f"Fetch error for {url}: {e}"


@mcp.tool()
def write_essay(
    topic: str,
    thesis: str,
    key_arguments: list,
    evidence: list,
    counterargument: str = "",
    style: str = "think-tank",
) -> str:
    """Return a structured think-tank essay scaffold for the agent to fill in.

    Args:
        topic:           The news event or policy issue being analysed.
        thesis:          The central argument or position of the essay.
        key_arguments:   List of 2–4 argument headings (strings).
        evidence:        List of evidence items, one per argument (strings).
        counterargument: A steel-man of the opposing view (optional).
        style:           Writing style — 'think-tank' (default), 'op-ed', 'briefing'.

    Returns a markdown scaffold the agent should expand into full prose.
    """
    args_block = ""
    for i, (arg, ev) in enumerate(zip(key_arguments, evidence), 1):
        args_block += f"\n### Argument {i}: {arg}\n\n{ev}\n"

    counter_block = ""
    if counterargument:
        counter_block = f"\n## Counterargument & Rebuttal\n\n{counterargument}\n\n[Agent: rebut above, showing why the thesis still holds]\n"

    style_note = {
        "think-tank": "Authoritative, evidence-driven, policy-oriented. Cite sources inline. Avoid partisan language.",
        "op-ed":      "Direct and persuasive. First person allowed. Shorter paragraphs. Hook the reader.",
        "briefing":   "Concise. Use bullet points under each section. Aimed at a policymaker audience.",
    }.get(style, "Authoritative and evidence-driven.")

    scaffold = f"""# {topic}

> **Style:** {style} — {style_note}

## Executive Summary

[Agent: 2–3 sentences. State the issue, the thesis, and why it matters now.]

## Background & Context

[Agent: Briefly explain the news event. Who are the key actors? What triggered this? What is the historical/geopolitical backdrop?]

## Thesis

{thesis}

## Analysis
{args_block}
{counter_block}
## Implications & Outlook

[Agent: What happens next? Short-term vs long-term consequences. Regional and global ripple effects.]

## Policy Recommendations

[Agent: 3–5 concrete, actionable recommendations for governments, institutions, or stakeholders.]

## Conclusion

[Agent: Restate thesis. End with a forward-looking sentence.]

---
*Sources: [Agent: list all outlets and URLs used from web_search / web_fetch]*
"""
    return scaffold


@mcp.tool()
def rate_source(
    source_name: str,
    quality: int,
    reason: str,
    topic_tag: str = "general",
) -> str:
    """Rate a news source after reading it. Call this every time you use a source.

    Args:
        source_name: Human-readable outlet name, e.g. 'Reuters', 'BBC', 'Straits Times'.
        quality:     Integer 1–5 (1 = poor/irrelevant, 3 = adequate, 5 = excellent/authoritative).
        reason:      One sentence explaining the score. Be specific.
                     e.g. "Detailed on-ground reporting with named officials cited."
                     e.g. "Headline misleading; article was opinion, not news."
        topic_tag:   Broad topic bucket — 'geopolitics', 'economy', 'climate', etc.
                     Defaults to 'general'. Used to make source rankings topic-aware.

    Returns a confirmation string.
    """
    if not 1 <= quality <= 5:
        return "Error: quality must be between 1 and 5."
    try:
        with _db() as conn:
            conn.execute(
                "INSERT INTO source_quality (source_name, topic_tag, quality, reason) VALUES (?,?,?,?)",
                (source_name.strip(), topic_tag.strip().lower(), quality, reason.strip()),
            )
        return f"Rated '{source_name}' {quality}/5 under topic '{topic_tag}': {reason}"
    except Exception as e:
        return f"rate_source error: {e}"


@mcp.tool()
def get_best_sources(topic_tag: str = "general", limit: int = 10) -> str:
    """Return the top-ranked news sources by average quality score.

    Call this at the START of every research session to decide which outlets
    to prioritise. If a topic-specific ranking exists it is returned; otherwise
    the overall ranking is used.

    Args:
        topic_tag: Topic to filter by (e.g. 'geopolitics'). Use 'general' for overall.
        limit:     Maximum number of sources to return.

    Returns a ranked table of sources with scores and use counts.
    """
    try:
        with _db() as conn:
            rows = conn.execute("""
                SELECT
                    source_name,
                    ROUND(AVG(quality), 2)  AS avg_score,
                    COUNT(*)                AS uses,
                    MAX(reason)             AS latest_reason
                FROM source_quality
                WHERE topic_tag = ? OR ? = 'general'
                GROUP BY source_name
                ORDER BY avg_score DESC, uses DESC
                LIMIT ?
            """, (topic_tag.lower(), topic_tag.lower(), limit)).fetchall()

        if not rows:
            return (
                "No source ratings recorded yet. "
                "Use rate_source() after each search to build up the ranking."
            )

        lines = [f"Source rankings for topic='{topic_tag}':\n",
                 f"{'Rank':<5} {'Source':<25} {'Avg':<6} {'Uses':<6} {'Latest note'}"]
        lines.append("-" * 75)
        for rank, r in enumerate(rows, 1):
            lines.append(
                f"{rank:<5} {r['source_name']:<25} {r['avg_score']:<6} {r['uses']:<6} {r['latest_reason'] or ''}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"get_best_sources error: {e}"


@mcp.tool()
def log_writing_feedback(
    component: str,
    feedback: str,
    sentiment: str,
    content_snippet: str = "",
    topic_tag: str = "general",
) -> str:
    """Log what worked or did not work in a piece of writing. Call this after every essay.

    Args:
        component:       Which part of the essay: 'thesis', 'counterargument', 'conclusion',
                         'argument', 'executive_summary', 'recommendations', 'overall'.
        feedback:        Specific, actionable note.
                         Good: "Conclusion restated thesis verbatim — felt repetitive. Try a
                                forward-looking provocation instead."
                         Bad:  "Conclusion was not good."
        sentiment:       'positive' if it worked well, 'negative' if it needs improvement.
        content_snippet: Optional excerpt (≤300 chars) of the actual text that was judged.
        topic_tag:       Broad topic bucket for context.

    Returns a confirmation string.
    """
    sentiment_map = {"positive": 1, "negative": -1}
    if sentiment not in sentiment_map:
        return "Error: sentiment must be 'positive' or 'negative'."
    try:
        with _db() as conn:
            conn.execute(
                """INSERT INTO writing_feedback
                   (component, topic_tag, content_snippet, feedback, sentiment)
                   VALUES (?,?,?,?,?)""",
                (
                    component.strip().lower(),
                    topic_tag.strip().lower(),
                    content_snippet[:300].strip(),
                    feedback.strip(),
                    sentiment_map[sentiment],
                ),
            )
        label = "✓ positive" if sentiment == "positive" else "✗ negative"
        return f"Logged [{label}] feedback for '{component}': {feedback[:120]}"
    except Exception as e:
        return f"log_writing_feedback error: {e}"


@mcp.tool()
def recall_writing_feedback(component: str = "all", limit: int = 8) -> str:
    """Retrieve past writing lessons before drafting an essay section.

    Call this BEFORE writing each section to load accumulated guidance.
    The agent should internalise this feedback and avoid repeating past mistakes.

    Args:
        component: Section to retrieve lessons for — 'thesis', 'counterargument',
                   'conclusion', 'argument', 'recommendations', 'overall', or 'all'.
        limit:     Number of most-recent entries to return per component.

    Returns a formatted guidance block.
    """
    try:
        with _db() as conn:
            if component == "all":
                rows = conn.execute("""
                    SELECT component, feedback, sentiment, ts
                    FROM writing_feedback
                    ORDER BY ts DESC
                    LIMIT ?
                """, (limit,)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT component, feedback, sentiment, ts
                    FROM writing_feedback
                    WHERE component = ?
                    ORDER BY ts DESC
                    LIMIT ?
                """, (component.strip().lower(), limit)).fetchall()

        if not rows:
            return (
                f"No writing feedback recorded yet for '{component}'. "
                "Use log_writing_feedback() after each essay to build up guidance."
            )

        positives = [r for r in rows if r["sentiment"] == 1]
        negatives = [r for r in rows if r["sentiment"] == -1]

        lines = [f"Writing guidance recalled for component='{component}':\n"]

        if negatives:
            lines.append("## What to AVOID (past mistakes)")
            for r in negatives:
                lines.append(f"  [{r['component']}] {r['feedback']}")

        if positives:
            lines.append("\n## What WORKS (patterns to repeat)")
            for r in positives:
                lines.append(f"  [{r['component']}] {r['feedback']}")

        lines.append(
            "\nApply the above before drafting. Do not repeat flagged mistakes."
        )
        return "\n".join(lines)
    except Exception as e:
        return f"recall_writing_feedback error: {e}"


@mcp.tool()
def remember_context(key: str, value: str) -> str:
    """Store a piece of information for later reference in the conversation.
    Writes to a simple key-value store in memory.md
    """
    import os
    memory_file = os.path.join(os.path.dirname(__file__), "memory.md")
    try:
        # Read existing
        existing = ""
        if os.path.exists(memory_file):
            with open(memory_file, "r") as f:
                existing = f.read()

        # Update or add key
        import re
        pattern = rf"^## {re.escape(key)}\n.*?(?=^## |\Z)"
        new_entry = f"## {key}\n{value}\n\n"
        if re.search(pattern, existing, flags=re.MULTILINE | re.DOTALL):
            updated = re.sub(pattern, new_entry, existing, flags=re.MULTILINE | re.DOTALL)
        else:
            updated = existing + new_entry

        with open(memory_file, "w") as f:
            f.write(updated)

        return f"Stored: {key} = {value[:100]}..."
    except Exception as e:
        return f"Memory error: {e}"


if __name__ == "__main__":
    print("Starting ARIA MCP Tool Server ...")
    mcp.run()