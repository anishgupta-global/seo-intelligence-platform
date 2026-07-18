# SEO Intelligence Platform — Workable Reference Implementation

A runnable, zero-dependency (Python stdlib only) implementation of the **Part 2 architecture**.
Its purpose is to *justify the design by executing it*: the folder layout **is** the data-flow
diagram, and every architectural claim (deterministic-first, structured-JSON AI contract,
robustness, observability, "logs into the data stack") is demonstrable on a live site.

```bash
python run_audit.py https://anishgupta.eu --max-pages 60
# open reports/dashboard.html in a browser
```

Runs in **MOCK mode** with zero setup. Add env vars for **LIVE mode**:
`CLAUDE_API_KEY` (real Claude summary) · `SLACK_WEBHOOK_URL` (real Slack post) · `DATAFORSEO_LOGIN/_PASSWORD` (SERP/GEO collectors).

---

## Code layout = the architecture (each module is one layer)

| Data-flow stage | Module | What it proves |
|---|---|---|
| **Collect** | `seo_intel/collect.py` | Redirect-aware crawler + sitemap seeding; API collectors plug in behind the same client |
| **Normalize** | `seo_intel/models.py` | Typed records (dataclasses; pydantic in prod) |
| **Validate** | `seo_intel/validate.py` | Batch sanity + per-record checks → **dead-letter**; nothing unvalidated reaches core tables |
| **Enrich #1 (deterministic)** | `seo_intel/rules.py` | ~22 pure-function checks, **never AI** — the 90% that's boolean/arithmetic |
| **Enrich #2 (AI)** | `seo_intel/ai.py` | Claude over verified facts only; **schema → validate → retry → dead-letter**, confidence-capped, cached |
| **Decision** | `seo_intel/scoring.py` | `Priority = Impact × Value × Confidence × Severity` (multiplicative = anti-fatigue) |
| **Surface** | `seo_intel/surface.py` | Priority-routed Slack (webhook/console) + Markdown + JSON + HTML dashboard |
| **Storage** | `seo_intel/warehouse.py` | SQLite (⇢ PostgreSQL): pages, issues, **job_runs**, **ai_cache**, **dead_letter** |
| **Robustness** | `seo_intel/net.py` | One HTTP primitive: retries + backoff + jitter + **circuit breaker** |
| **Orchestrator** | `seo_intel/pipeline.py` | Wires layers in Part 2 order; writes job_runs; crash → job marked failed |

## Maps to the four Task 2 questions

- **Q1 Data Flow** → the module table above, running end-to-end on a real site.
- **Q2 AI Integration** → `ai.py`: LLM only at Enrich/Surface (executive summary + recommendations); every deterministic check stays in `rules.py`.
- **Q3 Robustness & Observability** → `net.py` (rate-limit/backoff/breaker) + `ai.py` (strict JSON contract: schema→validate→1 retry→dead-letter, confidence cap 0.7) + `warehouse.job_runs` (duration, tokens, cost, status).
- **Q4 Pragmatism** → the notifier is deliberately thin (would be n8n at the edge); the crawler/rules/AI-contract are the robust custom core. Hard boundary preserved.

## Verified run (anishgupta.eu, 60 pages, mock mode)
- 60 pages crawled via sitemap seeding, 120 issues, all P2 (site is technically healthy).
- `job_runs`: status=ok, 20.3s, cost tracked; AI summary cached (re-run = 0 tokens).
- Reports written: `reports/dashboard.html`, `report.md`, `report.json`.

## What's intentionally stubbed (and where it slots in)
- **GSC/GA4 traffic** → scoring uses a depth heuristic for Impact×Value (labelled); real GSC collector drops into `collect.py`.
- **DataForSEO SERP + AI Overviews (GEO)** → `serp.py`-style collector, same client; feeds an intent-shift AI task (that's Part 3).
- **n8n routing** → `surface.notify_slack` is the seam; swap the direct POST for an n8n webhook with no other change.

## Notifications
Alerts are priority-routed (P0 instant, P1/P2 batched) through the Surface layer:
- **Slack** — set `SLACK_WEBHOOK_URL` (else console dry-run).
- **Email** — set `EMAIL_FROM`, `EMAIL_APP_PASSWORD` (Gmail App Password), `EMAIL_TO`
  (override `SMTP_HOST`/`SMTP_PORT` for non-Gmail). Sends a formatted HTML report; dry-runs otherwise.

## Hosting (free, automatic)
`.github/workflows/audit.yml` runs the audit on a **daily cron** (and on-demand via *Run workflow*)
on **GitHub Actions** — free for a public repo, zero dependencies to install. Add your keys as repo
**Actions secrets** (`EMAIL_FROM`, `EMAIL_APP_PASSWORD`, `EMAIL_TO`, optional `CLAUDE_API_KEY`,
`SLACK_WEBHOOK_URL`) and it emails you the results on schedule.

```bash
# publish (one-time)
git init && git add . && git commit -m "SEO Intelligence Platform"
gh repo create seo-intelligence-platform --public --source=. --push
```

## License
MIT © 2026 Anish Gupta. See `LICENSE`.

---
*Companion: `../PART2_Infrastructure_Architecture.md` (the design this executes).*
