"""
Strict output schema for a diagnosis (Part 3 requirement #3).
Every diagnosis — deterministic or AI — must satisfy this before it can be surfaced.
"""
from __future__ import annotations

ISSUE_TYPES = {
    "technical_decay",         # our page broke (noindex / 404 / bad canonical / robots)
    "cannibalization",         # two of our own URLs compete for the query
    "ai_overview_intrusion",   # an AI Overview now occupies the top (GEO) — organic displaced
    "serp_feature_expansion",  # more ads / shopping / video pushed organic down
    "intent_shift",            # Google now favours a different content type (e.g. listicles)
    "content_decay",           # competitors fresher/deeper; our content stale
    "volatility",              # normal fluctuation — no action
}

RESOLVED_BY = {"deterministic", "ai"}

REQUIRED = {
    "issue_type": str,
    "confidence_score": (int, float),
    "recommended_action": str,
}


def validate_diagnosis(obj) -> tuple[bool, str]:
    if not isinstance(obj, dict):
        return False, "diagnosis is not an object"
    for k, t in REQUIRED.items():
        if k not in obj:
            return False, f"missing required key '{k}'"
        if not isinstance(obj[k], t):
            return False, f"'{k}' has wrong type"
    if obj["issue_type"] not in ISSUE_TYPES:
        return False, f"issue_type '{obj['issue_type']}' not in {sorted(ISSUE_TYPES)}"
    c = float(obj["confidence_score"])
    if not (0.0 <= c <= 1.0):
        return False, "confidence_score must be within 0.0–1.0"
    if not obj["recommended_action"].strip():
        return False, "recommended_action is empty"
    return True, ""


def make(issue_type, confidence, action, summary, evidence, resolved_by):
    """Build a schema-valid diagnosis dict."""
    return {
        "issue_type": issue_type,
        "confidence_score": round(float(confidence), 2),
        "recommended_action": action,
        "summary": summary,
        "evidence": evidence,
        "resolved_by": resolved_by,
    }
