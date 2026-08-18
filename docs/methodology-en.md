# Methodology: Policy Signal Tracking with an Investment-Hypothesis Loop

This document explains the analytical design of the project in plain English. The working language of the analysis itself is Chinese (the source material is Chinese), but the *approach* is language-agnostic and can be applied to any country's official media or policy announcements.

## Why Xinwen Lianbo?

*Xinwen Lianbo* (新闻联播) is China's flagship nightly news broadcast. It is not neutral "news" in the Western sense: it is a curated policy signal channel. What is covered, the order of items, and the exact wording are deliberate choices by the policy apparatus. That makes it a high-quality, low-noise source for "what the state wants to happen next."

We deliberately do **not** try to cover every item. Each day we extract 3-4 signals that pass five criteria:

1. Has a policy carrier (meeting, document, leadership statement, ministry plan)
2. Carries new information (NEW or PROGRESS; repeated filler is rejected)
3. Can be turned into a one-line **validation hypothesis** ("X gets policy support → a concrete, observable industry checkpoint Y")
4. Is verifiable within 1-3 months
5. Adds information beyond what the tracking table already knows

## Four-dimension assessment

Each signal is scored on four independent dimensions (deliberately not merged into a single score, because different combinations imply different actions):

- **Level** — who is speaking: A = top leadership; B = ministry implementation of a top-level decision; C = ministry routine; D = brief mention
- **Novelty** — NEW (first appearance) / PROGRESS (new development of an existing direction) / REPEAT (no new info)
- **Specificity** — S1 = quantitative targets + timeline + projects; S2 = direction only; S3 = vague
- **Verification window** — how soon a check point exists: SHORT (1-4 weeks) / MID (1-3 months) / LONG

On top of these, we add:

- **Policy window** (based on Kingdon's Multiple Streams theory): open / near / closed, depending on whether the problem stream, policy stream and politics stream are all active.
- **Narrative framework**: Security / Competition / Livelihood / Development. The frame tells you the *priority* the state assigns to an issue — Security-frame issues are "spare no cost", Competition-frame issues get resources to win, Livelihood-frame issues advance steadily.

## Anti-drift framework classification

The narrative frame of a signal used to be an LLM's daily guess, which drifts. We made it auditable in two ways:

1. **Dictionary-first judgment**: a fixed keyword dictionary (e.g., "牢牢守住底线", "自主可控" → Security frame) is the primary classifier; the LLM is only a fallback when no dictionary term matches. The same text always yields the same frame.
2. **Mandatory evidence**: every frame label stores the exact keyword or quote that triggered it. A frame with no evidence is marked "pending evidence."

If a new judgment conflicts with a stored judgment and its evidence, the system distinguishes two cases: the narrative genuinely changed (recorded as a **framework migration event** — a strong signal) or the LLM drifted (flagged for human confirmation).

## Theme lifecycle events (auditable analysis, not just reports)

Each tracked theme has two distinct logs:

- **Timeline**: what happened in the world (broadcast events)
- **Lifecycle**: what *we* decided about the theme and why — creation, framework changes, status transitions, novelty updates — each with date, evidence (which broadcast item), and reason

Lifecycle events are append-only. This is what makes the analysis an auditable asset: months later you can reconstruct *why* a theme was classified a certain way, detect judgment drift, and compute statistics such as "how many framework migrations occurred this month" or "what was our verification hit rate" — queries that are impossible with prose-only reports.

## Investment hypothesis verification (not event check-ins)

The end goal is "which policy signal is gaining momentum." Every theme therefore carries a one-line validation hypothesis, and its verification condition is an event or data point that can **confirm or falsify that hypothesis** — not a ceremonial milestone.

Two verification types are forbidden:

- **Pre-announced ceremonial events**: e.g., an opening ceremony whose date the broadcast itself already announced. Checking it off adds zero information. The verification point should be the *economic consequence* (e.g., cargo volume after a canal opens).
- **Circular conditions**: e.g., using "does the export number continue" as a *policy* verification. That is a trend test, tracked separately as industry-data observation, not a policy signal.

## Mapping to the 15th Five-Year Plan

Every signal is mapped to a part/chapter of China's 15th Five-Year Plan (published March 2026). This is a *locating* tool, not the goal: it answers "which strategic narrative does this item belong to, and what priority does the plan assign to it" — the plan's chapter structure is a proxy for the state's resource-priority ordering.

## Outputs

- **Daily report** (Markdown): headline takeaways, per-signal analysis, tracking table delta, lifecycle events, consistency checks, risk notes
- **Tracking table**: one structured record per theme (dimensions, hypothesis, evidence, lifecycle, verification), stored as JSON and rendered to Markdown
- **Consistency checks**: framework-evidence coverage and suspected-drift reports, generated mechanically

## License

This methodology and all accompanying code are licensed under **GNU AGPL-3.0**. You may learn from, modify, and redistribute them, but derivative works must stay open under AGPL-3.0, including network services built on modified versions.
