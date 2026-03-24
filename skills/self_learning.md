# Skill: Self-Learning & Continuous Improvement

## Purpose
After every research session and every essay, record what worked and what did not.
On the next run, retrieve that memory and improve. No RL required — this is
**experience replay via structured memory** (SQLite).

---

## Architecture

```
SQLite: agent_memory.db
│
├── source_quality        ← "Reuters scored 5/5 on geopolitics three times"
│   source_name, topic_tag, quality (1–5), reason, timestamp
│
└── writing_feedback      ← "Conclusion felt hollow; thesis not restated sharply"
    component, topic_tag, snippet, feedback, sentiment (+1/-1), timestamp
```

All four learning tools write to or read from this single file.
It persists across every session — the agent's accumulated experience.

---

## Tool Reference

| Tool | When to call | What it does |
|------|-------------|--------------|
| `get_best_sources(topic_tag)` | **Start** of every research session | Returns ranked source table — prioritise top sources |
| `rate_source(name, score, reason, topic_tag)` | **After** reading each source | Adds one rating row; shapes future rankings |
| `recall_writing_feedback(component)` | **Before** writing each section | Returns past mistakes + patterns to repeat |
| `log_writing_feedback(component, feedback, sentiment)` | **After** finishing the essay | Stores one lesson for future runs |

---

## Full Session Protocol

### Phase 1 — Before Searching

```
1. get_best_sources(topic_tag="<relevant topic>")
   → Read the ranked table
   → Prioritise sources with avg ≥ 4.0
   → De-prioritise sources with avg ≤ 2.5 or use count ≥ 3 at low scores
   → If no data yet, use the default outlet list from news_search.md
```

### Phase 2 — While Searching

After reading each article via `web_fetch`, immediately rate it:

```
rate_source(
    source_name  = "Straits Times",
    quality      = 5,
    reason       = "Exclusive quotes from ASEAN ministers; original on-ground reporting.",
    topic_tag    = "geopolitics"
)

rate_source(
    source_name  = "BBC",
    quality      = 2,
    reason       = "Wire re-post with no original reporting; thin on detail.",
    topic_tag    = "geopolitics"
)
```

**Scoring guide:**

| Score | Meaning |
|-------|---------|
| 5 | Original reporting, named sources, exclusive detail, directly relevant |
| 4 | Solid reporting, well-sourced, relevant |
| 3 | Adequate — mostly wire copy or surface coverage |
| 2 | Thin, vague, or only tangentially relevant |
| 1 | Misleading headline, opinion presented as news, or irrelevant |

### Phase 3 — Before Writing Each Section

Before drafting `conclusion`, `counterargument`, `thesis`, etc.:

```
recall_writing_feedback(component="conclusion")
recall_writing_feedback(component="counterargument")
```

Read the output. Apply every "AVOID" note. Repeat every "WORKS" pattern.

### Phase 4 — After Finishing the Essay

Log at least one lesson per section where feedback exists.
Be specific — vague feedback is useless on future recall.

**Good feedback examples:**
```
log_writing_feedback(
    component = "conclusion",
    feedback  = "Ended with a rhetorical question — landed powerfully; reader left with unease.",
    sentiment = "positive",
    topic_tag = "geopolitics"
)

log_writing_feedback(
    component = "counterargument",
    feedback  = "Steel-man was too brief (1 sentence). Needs 2–3 sentences to feel credible before rebuttal.",
    sentiment = "negative",
    content_snippet = "Some argue China's actions are purely defensive...",
    topic_tag = "geopolitics"
)

log_writing_feedback(
    component = "conclusion",
    feedback  = "Restated thesis word-for-word from intro — felt like copy-paste. Rephrase or escalate.",
    sentiment = "negative"
)
```

---

## Self-Improvement Rules

1. **Never repeat a flagged mistake.** If `recall_writing_feedback` returns a negative note
   about a pattern, do not reproduce that pattern — rewrite until the issue is resolved.

2. **Escalate conclusions.** A conclusion must end *further* than it begins.
   It should not summarise — it should arrive somewhere new:
   a final implication, a warning, an open question, or a provocation.

3. **Earn counterarguments.** A counterargument that takes fewer than 3 sentences to present
   is not a steel-man — it is a strawman. Give the opposing view its best form.

4. **Source quality compounds.** If a source scores ≤ 2 across 3+ sessions on the same topic,
   stop using it as a primary source for that topic. It can still be used for corroboration.

5. **Log the win too.** Positive feedback reinforces good patterns. If a thesis structure,
   opening hook, or analogy landed well — log it so it can be reproduced.

---

## What Gets Better Over Time

| Capability | How it improves |
|-----------|----------------|
| Source selection | `get_best_sources` returns higher-quality outlets as ratings accumulate |
| Counterargument quality | Negative logs force deeper steel-manning each iteration |
| Conclusion depth | Negative logs on shallow endings push toward provocation/implication |
| Thesis sharpness | Positive logs on strong thesis patterns get reused and refined |
| Topic-specific sourcing | Per-topic ratings mean geopolitics vs economy use different source hierarchies |

---

## Future Upgrade Path (when ready)

When you want semantic similarity — "find past feedback *like* this section" — add:

```
pip install chromadb sentence-transformers
```

Then embed each `writing_feedback` row and retrieve by cosine similarity instead of
exact component match. The SQLite rows already contain all the data needed for migration;
no schema change required.
