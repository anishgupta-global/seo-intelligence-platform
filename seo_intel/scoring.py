"""
Decision layer. Priority = Traffic Impact x Business Value x Confidence x Severity.
Multiplicative on purpose: any near-zero factor kills the alert (anti-fatigue).
No GSC traffic data in the local demo -> a page-importance heuristic (depth-based)
stands in for Impact x Value, and it is labelled as such everywhere.
"""
from __future__ import annotations
from .models import Page, Issue, ScoredIssue

CONFIDENCE_DETERMINISTIC = 0.9


def page_importance(url: str, pages: dict[str, Page]) -> float:
    pg = pages.get(url)
    depth = pg.depth if pg else 3
    return round(max(0.2, 1.0 - 0.18 * depth), 2)      # homepage 1.0, decays with depth


def score(issues: list[Issue], pages: dict[str, Page]) -> list[ScoredIssue]:
    out = []
    for iss in issues:
        imp = page_importance(iss.url, pages)
        pr = round(imp * CONFIDENCE_DETERMINISTIC * iss.severity, 3)
        band = "P0" if pr >= 0.55 else "P1" if pr >= 0.30 else "P2" if pr >= 0.12 else "LOG"
        out.append(ScoredIssue(pr, band, iss, imp))
    out.sort(key=lambda s: s.priority, reverse=True)
    return out
