# China Signal · Xinwen Lianbo

> 看新闻联播，跟踪中国产业政策的叙事偏离

[中文版 README](./README.md)

---

> Everyone is reading *Xinwen Lianbo* — but what exactly are they looking for? This is my daily log of policy winds, industry transmission, and falsifiable hypothesis check-ins.

One evening in August, the nightly news described nuclear power with four words: *积极安全有序发展* — "actively, safely, orderly develop." Our system flagged it immediately: nuclear had just crossed from the **Competition** frame to the **Security** frame. Quiet on the surface. Big for anyone watching China's energy industry.

That's the kind of signal this project is built to catch.

## What this is

Every evening at 7pm, CCTV's 30-minute *Xinwen Lianbo* tells you — deliberately, in order, with chosen words — what the Chinese state wants to happen next. We treat it as a **policy signal channel**: not news to summarize, but a stream to mine.

Each day the pipeline:

1. Picks the **3-4 items** that actually carry policy (skipping obituaries, disasters, fluff)
2. Scores each signal: *who is speaking, is it new, does it have a concrete hook, when can we verify*
3. Writes a one-line **internal validation hypothesis**, e.g. "nuclear enters the Security frame → approval and construction pace becomes the next observable signal"
4. Tracks it in a rolling table and **verifies it later** — did the hypothesis hold, or die?

The question we answer is not "what happened today". It's **"which policy promises are quietly accelerating, being deprioritized, reframed, or silently walked back?"**

The public output is deviation detection across three layers: **plan → narrative → reality**. Internal validation hypotheses stay in the system as falsifiable metrics — they are not shown in the push summary and are not investment advice.

## What you get

A daily Markdown report + a structured tracking table (JSON + rendered). A real row from the tracking table:

| # | Theme | Level | Novelty | Specificity | Window | Frame | Verification |
|---|-------|-------|---------|-------------|--------|-------|--------------|
| 30 | Nuclear construction scale ranks No.1 globally | B | PROGRESS | S1 | Open | Security | New project starts (2026-11-12) |

> Policy-conduction logic: nuclear enters the Security frame (top priority) → approval and construction pace becomes the next observable real-workload checkpoint.

Full sample: [`reports/2026-08-12.md`](reports/2026-08-12.md)

## Start here

- Want to see what is currently tracked? Open [`tracking.md`](tracking.md)
- Want to understand the method and vocabulary? Open [`notes/如何看懂这份雷达.md`](notes/如何看懂这份雷达.md)
- Want the daily reports? Browse [`reports/`](reports/)

## How it works

```mermaid
flowchart TD
    A["Fetch daily transcript"] --> B["LLM analysis: 3-4 signals, four dimensions, internal validation hypotheses"]
    B --> C["Update tracking table: lifecycle events + framework evidence"]
    C --> D["Render tracking table + write daily report"]
    D --> E["Due hypothesis checks"]
    E --> F["Status flow: verified / tracking / decayed"]
    F --> G["Investment leads (user decides)"]
    G --> A
```

The daily loop feeds the tracking table; verification results feed back into theme status; confirmed hypotheses graduate into trackable leads — then the loop repeats.

## Methodology (the important, slightly boring part)

**Four dimensions.** Every signal is scored independently — *Level* (who is speaking: leadership or ministry), *Novelty* (new direction or progress), *Specificity* (numbers/timelines/projects, or vague talk), *Verification window* (when we can check). Different combinations mean different actions.

**Policy window.** Kingdon's multiple streams: when the problem, the solution and the politics all align, concrete rules follow. Tracked as Open / Near / Closed.

**Narrative frames.** Security / Competition / Livelihood / Development. The frame reveals priority: Security = spare no cost, Competition = pour in resources to win, Livelihood = steady progress. **A frame migration is a strong signal** — that's exactly how we caught nuclear.

**Investment hypotheses, not event check-ins.** Every theme carries a falsifiable hypothesis; its verification condition is an event or data point that confirms or kills it. No ceremonial milestones, no circular tests.

**15th Five-Year Plan mapping.** Every signal is located in the plan's 18 parts / 62 chapters, so you always see the larger narrative behind the item.

The full design rationale in English: [`docs/methodology-en.md`](docs/methodology-en.md).

## Run & automate

**Requirements:** Python 3.9+ (3.11+ recommended). No third-party dependencies — all scripts use only the Python standard library (`requirements.txt` contains only comments, by design).

```bash
git clone <your-repo-url>
cd <your-repo>

python -m venv .venv            # optional
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate

python scripts/run_daily.py --mock               # full pipeline demo, no API call (temp-dir output)
python scripts/run_daily.py --date 2026-08-12    # analyze a specific date
python -m unittest discover -s tests -v          # unit tests
```

A real analysis run needs LLM credentials (`LLM_API_KEY`, any OpenAI-compatible endpoint). Full commands, environment variables, scheduling, and GitHub Actions setup live in [`docs/automation_prompt.md`](docs/automation_prompt.md); the historical backtest is documented in [`docs/backtest/`](docs/backtest/). The repo ships CI (`.github/workflows/ci.yml`): syntax check + unit tests on every push/PR.

## Disclaimer

Research and education only. Analysis is based on publicly available broadcast transcripts and is **not investment advice**.

## License

GNU AGPL-3.0 (code, methodology, prompts, framework dictionary). Derivatives must stay open, including network services. See [LICENSE](LICENSE).
