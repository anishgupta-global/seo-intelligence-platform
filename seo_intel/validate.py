"""
Validate layer. The only gate into the warehouse: batch sanity checks + per-record
validation. Anything that fails becomes a dead-letter row (an ALERT), never poisoned
data in core tables.
"""
from __future__ import annotations
from .models import Page


def validate_batch(pages: dict[str, Page], log=print):
    """Returns (ok_pages, rejects). Rejects = [(url, reason, page)]."""
    total = len(pages) or 1
    unreachable = [p for p in pages.values() if p.error or p.status == 0]

    # batch-level sanity: if most of the crawl failed, the SOURCE is suspect —
    # quarantine the whole batch rather than trust it.
    if len(unreachable) / total > 0.5:
        log(f"[validate] SANITY FAIL: {len(unreachable)}/{total} pages unreachable "
            f"— batch quarantined (source likely down).")
        return {}, [(p.url, "batch_quarantine", p) for p in pages.values()]

    ok, rejects = {}, []
    for url, pg in pages.items():
        if pg.error or pg.status == 0:
            rejects.append((url, f"unreachable: {pg.error or 'status 0'}", pg))
            continue
        ok[url] = pg
    if rejects:
        log(f"[validate] {len(rejects)} record(s) dead-lettered; {len(ok)} passed.")
    return ok, rejects
