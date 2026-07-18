"""
Orchestrator. Wires the layers in the exact Part 2 order and records the run in
job_runs (observability). Every stage is re-runnable; a crash marks the job failed
rather than leaving silent partial state.

    Collect -> Validate -> Enrich(rules) -> Enrich(AI) -> Decision -> Storage -> Surface
"""
from __future__ import annotations
from collections import Counter

from .config import Settings
from .net import RobustClient
from .warehouse import Warehouse
from . import collect as collect_mod
from .validate import validate_batch
from .rules import run_rules
from .scoring import score
from .ai import AIEngine, summarize_findings
from .surface import notify_slack, notify_email, write_reports


def run(settings: Settings, log=print) -> dict:
    log(f"[pipeline] target={settings.start_url}")
    log(f"[pipeline] {settings.banner()}")
    wh = Warehouse(settings.db_path)
    client = RobustClient(timeout=settings.timeout)
    run_id = wh.start_job("full_audit", settings.start_url)
    ai = AIEngine(settings, wh)
    try:
        # Collect
        pages, status_map, sitemap = collect_mod.crawl(client, settings, log=log)
        # Validate (gate + dead-letter)
        ok_pages, rejects = validate_batch(pages, log=log)
        if rejects:
            wh.dead_letter(rejects)
        # Enrich #1 — deterministic
        issues = run_rules(ok_pages, status_map, sitemap, settings)
        # Decision
        scored = score(issues, ok_pages)
        # Enrich #2 — AI over verified facts (structured, validated, cost-tracked)
        ai_summary = ai.executive_summary(summarize_findings(scored, ok_pages))
        # Storage
        wh.persist(run_id, ok_pages, scored)
        # Surface
        bands = Counter(s.band for s in scored)
        run_meta = {"pages": len(ok_pages), "issues": len(scored), "bands": dict(bands)}
        reports = write_reports(settings, ok_pages, scored, ai_summary, run_meta)
        notify_slack(settings, scored, ai_summary, run_meta, log=log)
        notify_email(settings, scored, ai_summary, run_meta, log=log)

        wh.finish_job(run_id, "ok", pages=len(ok_pages), issues=len(scored),
                      tokens_in=ai.tokens_in, tokens_out=ai.tokens_out,
                      cost=ai.cost, ai_mode=settings.ai_mode)
        run_meta["duration_s"] = round(__import__("time").time() - wh._t0, 1)
        # patch duration into the HTML/JSON now that we know it
        write_reports(settings, ok_pages, scored, ai_summary, run_meta)
        return {"run_id": run_id, "pages": len(ok_pages), "issues": len(scored),
                "bands": dict(bands), "ai_summary": ai_summary, "reports": reports,
                "rejects": len(rejects), "cost": ai.cost, "ai_mode": settings.ai_mode,
                "scored": scored}
    except Exception as e:
        wh.finish_job(run_id, "failed", error=str(e), ai_mode=settings.ai_mode)
        raise
    finally:
        wh.close()
