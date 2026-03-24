# Skill: Think-Tank Essay Writing

## Purpose
After completing news research (see `news_search.md`), synthesise findings into a rigorous,
think-tank style analytical essay — structured argument, real evidence, policy implications.

---

## When to Use This Skill
- After running the **Global News Search** skill and collecting facts + sources
- When the user asks for analysis, commentary, deep-dive, or an essay on a current event
- Output should read like a published piece from CFR, Brookings, IISS, CSIS, or Lowy Institute

---

## Full Pipeline (Research → Essay → Learn)

```
1. Run news_search skill         →  collect facts, quotes, URLs from ≥3 outlets
2. recall_writing_feedback("all") →  load accumulated lessons before writing anything
3. Identify thesis               →  what is the single most important argument?
4. Call write_essay()            →  get the scaffold
5. Before each section           →  recall_writing_feedback("<component>") — apply lessons
6. Expand scaffold               →  fill every section with full prose
7. Cite sources inline           →  [Outlet, URL] after every factual claim
8. After finishing               →  log_writing_feedback() for each section — at least 1 lesson
```

---

## Step-by-Step Instructions

### Step 1 — Derive the Thesis
After research, ask: *"What is the one non-obvious argument that most illuminates this event?"*

Good thesis patterns:
- "X is not merely a [surface issue] but a symptom of [deeper structural force]."
- "The conventional narrative misses [key dynamic]; in reality, [alternative explanation]."
- "Unless [actor] does [action], [consequence] will follow within [timeframe]."

Avoid: "This is a complex issue with many perspectives."

---

### Step 2 — Build 3–4 Arguments
Each argument must be:
- Distinct (no overlap with others)
- Supported by at least one piece of evidence from research
- Linked back to the thesis

**Argument structure per section:**
```
Claim → Evidence (cite source) → So what? (why does this matter for the thesis)
```

---

### Step 3 — Steel-Man the Opposition
Find the strongest version of the counter-view from your research (not a strawman).
Then rebut it: show why your thesis holds despite the objection.

---

### Step 4 — Call `write_essay()`
Pass in all the above to get a structured scaffold:

```python
write_essay(
    topic        = "...",          # the news event
    thesis       = "...",          # your central argument
    key_arguments= ["...", "..."], # 3–4 argument headings
    evidence     = ["...", "..."], # one evidence string per argument
    counterargument = "...",       # best opposing view (optional)
    style        = "think-tank"    # or "op-ed" / "briefing"
)
```

Then **expand every section** of the returned scaffold into full, flowing prose.

---

### Step 5 — Writing Standards

| Element | Requirement |
|---------|-------------|
| Length | 800–1,400 words for think-tank; 500–700 for op-ed; 400–600 for briefing |
| Tone | Authoritative but accessible. No jargon without definition. |
| Evidence | Every factual claim gets an inline citation: `[Reuters, URL]` |
| Quotes | Use sparingly — only for high-impact statements from key figures |
| Hedging | Use when genuinely uncertain: "suggests", "may", "risks" |
| Assertions | Be direct. Avoid "it could be argued that..." — just argue it |
| Perspective | Maintain analytical distance. Critique policy, not people |

---

## Analytical Lenses to Apply

For each story, consider which lenses are relevant and apply at least two:

| Lens | Questions to ask |
|------|-----------------|
| **Geopolitical** | Who gains power? Who loses? What alliances shift? |
| **Economic** | What are the trade, investment, or sanctions implications? |
| **Domestic politics** | How does this play internally for each key actor? |
| **Historical** | What precedent does this set or echo? |
| **Normative/Legal** | What international law or norms are at stake? |
| **Humanitarian** | Who bears the human cost? |

---

## Essay Styles

### `think-tank` (default)
- Full paragraphs, academic register
- Structured: Background → Thesis → Arguments → Counterargument → Implications → Recommendations
- Ends with concrete policy recommendations
- Example outlets: Foreign Affairs, Brookings, IISS, Lowy Institute

### `op-ed`
- Hook in the first sentence (a striking fact, quote, or provocation)
- Shorter paragraphs (2–4 sentences)
- First person allowed sparingly
- No policy recommendations section — embed stance throughout
- Example outlets: NYT Opinion, The Guardian, Straits Times Opinion

### `briefing`
- Bullet points under each heading
- Bold key terms
- "Bottom Line Up Front" (BLUF) at the very top
- Aimed at a time-poor policymaker
- Example outlets: CSIS briefs, Ministry of Foreign Affairs cables

---

## Quality Checklist (before finalising)

- [ ] Thesis is stated explicitly, early, and restated in conclusion
- [ ] Every argument is distinct and directly supports the thesis
- [ ] Every factual claim has a cited source with URL
- [ ] Counterargument is presented fairly before being rebutted
- [ ] Implications section covers both short-term and long-term
- [ ] Policy recommendations are specific and actionable (not "leaders should cooperate")
- [ ] Conclusion ends with a forward-looking sentence, not a summary
- [ ] Word count is within the target range for the chosen style

---

## Example Invocation

**User:** "Write a think-tank essay on the latest South China Sea incident."

```
1. [Run news_search skill for South China Sea]
2. Thesis: "China's latest incursion signals a deliberate escalation strategy timed
   to test the new US administration's resolve in the Indo-Pacific."
3. Arguments:
   - Pattern of incremental grey-zone operations
   - Timing relative to US domestic political transition
   - ASEAN's fragmented response enabling Chinese manoeuvre
4. Counterargument: "China's actions are defensive, responding to US FONOPs."
5. call write_essay(...) → expand scaffold → cite all sources
```
