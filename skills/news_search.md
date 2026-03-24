# Skill: Global News Search

## Purpose
Search for current news and current affairs across major global news outlets using `web_search`.

---

## News Sources to Cover

| Region | Outlet | Search target |
|--------|--------|---------------|
| Global / Wire | Reuters | `site:reuters.com` |
| Global / Wire | Associated Press | `site:apnews.com` |
| USA | Wall Street Journal | `site:wsj.com` |
| USA | New York Times | `site:nytimes.com` |
| USA | ABC News | `site:abcnews.go.com` |
| UK | The Times | `site:thetimes.co.uk` |
| UK | BBC News | `site:bbc.com/news` |
| UK | The Guardian | `site:theguardian.com` |
| Germany | Deutsche Welle (DW) | `site:dw.com` |
| Singapore / SEA | The Straits Times | `site:straitstimes.com` |
| Singapore / SEA | Channel NewsAsia (CNA) | `site:channelnewsasia.com` |
| Australia | ABC News AU | `site:abc.net.au/news` |
| Middle East | Al Jazeera | `site:aljazeera.com` |
| Asia | South China Morning Post | `site:scmp.com` |
| France | France 24 | `site:france24.com` |

---

## How to Use This Skill

### Step 0 — Load source rankings (self-learning hook)
Before searching, call:
```
get_best_sources(topic_tag="<relevant topic e.g. geopolitics>")
```
Prioritise outlets with **avg score ≥ 4.0**. If no data yet, use the table above as the default.
After reading each article, call `rate_source()` — see `self_learning.md` for the protocol.

### Step 1 — Formulate a broad query first
Run a general search to get an overview of the topic:
```
web_search("<topic> news 2025")
```

### Step 2 — Deep-dive into specific outlets
For each relevant outlet, run a site-scoped query:
```
web_search("site:reuters.com <topic>")
web_search("site:straitstimes.com <topic>")
web_search("site:channelnewsasia.com <topic>")
web_search("site:dw.com <topic>")
web_search("site:bbc.com/news <topic>")
```
Repeat for as many outlets as are relevant to the story.

### Step 3 — Visit article URLs
When a result looks relevant, fetch the full article using the URL returned:
```
web_fetch("<URL from search result>")
```
Extract: headline, date, key facts, quotes, and any named sources.

### Step 4 — Cross-reference
Check at least **two independent outlets** per major claim before treating it as confirmed.

### Step 5 — Synthesise
Compile findings into a structured summary:
- **What happened** (core facts)
- **Who is involved** (people, organisations, countries)
- **When and where**
- **Why it matters** (context, implications)
- **Sources used** (outlet name + URL)

---

## Query Patterns

| Goal | Query pattern |
|------|--------------|
| Breaking news on a topic | `"<topic>" news latest` |
| Regional angle | `"<topic>" site:straitstimes.com OR site:channelnewsasia.com` |
| Western perspective | `"<topic>" site:reuters.com OR site:wsj.com OR site:bbc.com` |
| Official statements | `"<topic>" statement OR "press release" site:reuters.com` |
| Background / analysis | `"<topic>" analysis OR explainer site:theguardian.com OR site:dw.com` |
| Multiple outlets at once | `"<topic>" (reuters OR BBC OR "Straits Times" OR CNA OR DW)` |

---

## Rules

1. **Always include the date range** when freshness matters — append `2025` or `2026` to the query.
2. **Never fabricate headlines or quotes.** If `web_fetch` is unavailable or blocked, state only what the search snippet says.
3. **Prefer wire services** (Reuters, AP) for raw facts; use analysis outlets (Guardian, DW, FT) for context.
4. **Flag paywalled articles** — WSJ, NYT, and The Times may return limited content; note this when summarising.
5. **Cover multiple regions** — a story from SEA should include at least one Western outlet and one regional outlet.
6. **Cite every claim** with `[Outlet, URL]`.

---

## Example Workflow

**User query:** "What is the latest on the South China Sea dispute?"

```
1. web_search("South China Sea dispute news 2026")
2. web_search("site:reuters.com South China Sea 2026")
3. web_search("site:straitstimes.com South China Sea")
4. web_search("site:channelnewsasia.com South China Sea")
5. web_search("site:scmp.com South China Sea")
6. web_search("site:aljazeera.com South China Sea")
7. web_fetch(<most relevant URL from each outlet>)
8. Synthesise into structured summary with citations
```
