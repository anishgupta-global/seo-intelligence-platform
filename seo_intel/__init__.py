"""
SEO Intelligence Platform — workable reference implementation.

The package layout mirrors the Part 2 architecture data-flow one module per layer:

    collect.py   -> Collect      (crawler + sitemap + API collectors)
    models.py    -> Normalize    (typed records)
    validate.py  -> Validate     (sanity checks + dead-letter)
    rules.py     -> Enrich #1     (deterministic rule engine — NEVER AI)
    ai.py        -> Enrich #2     (Claude, structured JSON, only where language matters)
    scoring.py   -> Decision      (priority = impact x value x confidence x severity)
    surface.py   -> Surface       (Slack + report + HTML dashboard)
    warehouse.py -> Storage       (SQLite stands in for PostgreSQL)
    net.py       -> Robustness    (retries, backoff, circuit breaker)
    pipeline.py  -> Orchestrator  (wires the layers, writes job_runs / cost)

Runs in MOCK mode with zero setup, or LIVE mode when CLAUDE_API_KEY /
SLACK_WEBHOOK_URL / DATAFORSEO_* env vars are present.
"""
__version__ = "1.0.0"
