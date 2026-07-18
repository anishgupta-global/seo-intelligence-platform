"""
The diagnostic engine. Mirrors the Part 2 thesis: deterministic checks resolve
what they can (cheap, certain, auditable); the LLM handles only the one genuine
judgment call. Reuses seo_intel.net.RobustClient for live API calls so timeout /
retry / circuit-breaker behaviour is the SAME battle-tested code, not bespoke.
"""
from __future__ import annotations
import json
from collections import Counter
from urllib.parse import urlparse

from . import schema
from .prompts import SYSTEM, build_user_prompt

# reuse the platform's robustness layer (Part 2) — this is how timeouts are handled
try:
    from seo_intel.net import RobustClient
except Exception:  # allow standalone use
    RobustClient = None

AI_CONFIDENCE_CAP = 0.7


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().replace("www.", "")


def _type_dist(serp: list) -> Counter:
    return Counter(r.get("type", "unknown") for r in serp)


# ---------------------------------------------------------------------------
# DETERMINISTIC LAYER — returns a diagnosis dict, or None if it can't decide.
# Ordered most-certain first.
# ---------------------------------------------------------------------------
def deterministic_diagnose(event: dict):
    op = event.get("our_page", {})
    domain = event.get("domain") or _domain(event["page"])
    new_serp = event["new_serp"]
    oldf = event.get("old_features", {})
    newf = event.get("new_features", {})

    # 1) technical decay — the page itself broke
    reasons = []
    if op.get("status", 200) >= 400:
        reasons.append(f"status {op['status']}")
    if op.get("indexable") is False or "noindex" in (op.get("robots", "")):
        reasons.append("noindex / not indexable")
    if op.get("canonical_self") is False:
        reasons.append("canonical points elsewhere")
    if reasons:
        return schema.make(
            "technical_decay", 0.95,
            "Fix the technical fault immediately (" + "; ".join(reasons) +
            "). The page is being deindexed/blocked — this outranks all other causes.",
            "The client page's own technical state is broken.",
            reasons, "deterministic")

    # 2) cannibalization — two of our own URLs in the new SERP
    ours = [r["url"] for r in new_serp if _domain(r["url"]) == domain]
    if len(ours) >= 2:
        return schema.make(
            "cannibalization", 0.9,
            "Consolidate or differentiate the competing URLs and pick one canonical target for this query.",
            f"{len(ours)} URLs from {domain} compete for the same keyword.",
            ours, "deterministic")

    # 3) AI Overview intrusion (GEO) — an AIO now sits above organic
    if newf.get("ai_overview") and not oldf.get("ai_overview"):
        return schema.make(
            "ai_overview_intrusion", 0.85,
            "Optimise for GEO: make the answer concise/extractable, add schema and entity clarity so the "
            "page is cited IN the AI Overview. Organic wasn't lost — it was pushed below the AIO.",
            "A new AI Overview now occupies the top of the SERP.",
            ["new SERP has an AI Overview; old SERP did not"], "deterministic")

    # 4) SERP-feature expansion — more ads / shopping / video pushed organic down
    def feat_weight(f):
        return f.get("ads", 0) + (3 if f.get("shopping") else 0) + (2 if f.get("video") else 0)
    if feat_weight(newf) - feat_weight(oldf) >= 2 and _type_dist(event["old_serp"]).most_common(1) \
            and _type_dist(new_serp).most_common(1) \
            and _type_dist(event["old_serp"]).most_common(1)[0][0] == _type_dist(new_serp).most_common(1)[0][0]:
        return schema.make(
            "serp_feature_expansion", 0.8,
            "SERP layout changed (more ads/shopping/video), not your page. Little on-page fix; consider "
            "paid coverage or targeting less commercial query variants.",
            "Paid/rich SERP features expanded and displaced organic.",
            [f"feature weight {feat_weight(oldf)} -> {feat_weight(newf)}"], "deterministic")

    # 5) volatility — small move, everything else unchanged
    drop = event["new_position"] - event["old_position"]
    if drop <= 3 and _type_dist(event["old_serp"]) == _type_dist(new_serp) and oldf == newf:
        return schema.make(
            "volatility", 0.6,
            "Likely normal volatility — monitor 7–14 days before acting.",
            f"Small move ({event['old_position']}→{event['new_position']}) with an unchanged SERP.",
            ["SERP composition + features unchanged"], "deterministic")

    return None  # -> hand to the AI layer


# ---------------------------------------------------------------------------
# AI LAYER — only the intent_shift vs content_decay judgment call.
# ---------------------------------------------------------------------------
def _ai_mock(event: dict) -> dict:
    old, new = _type_dist(event["old_serp"]), _type_dist(event["new_serp"])
    old_dom, new_dom = old.most_common(1)[0][0], new.most_common(1)[0][0]
    if old_dom != new_dom:
        share = new[new_dom] / max(1, sum(new.values()))
        return schema.make(
            "intent_shift", min(AI_CONFIDENCE_CAP, 0.45 + share * 0.4),
            f"Intent shifted to '{new_dom}'. Re-map this page to the new format or build a matching one; "
            f"the current '{old_dom}' format no longer fits the query.",
            f"Dominant SERP result type changed: '{old_dom}' → '{new_dom}'.",
            [f"old dominant: {old_dom}", f"new dominant: {new_dom}"], "ai")
    return schema.make(
        "content_decay", min(AI_CONFIDENCE_CAP, 0.6),
        "Refresh and deepen the content — update stats, expand coverage, bump last-modified. Competitors "
        "now rank with fresher/more comprehensive pages in the same format.",
        f"SERP format unchanged ('{new_dom}'); competitors likely fresher/deeper.",
        [f"stable dominant type: {new_dom}", f"our word_count: {event.get('our_page',{}).get('word_count')}"],
        "ai")


def _ai_live(event: dict, settings) -> dict:
    """Real Claude call, reusing the platform's timeout-safe client + the JSON contract."""
    if RobustClient is None:
        return _ai_mock(event)
    client = RobustClient(timeout=60, max_retries=3)
    user = build_user_prompt(event)

    def call(extra=""):
        body = json.dumps({
            "model": settings.claude_model, "max_tokens": 600,
            "system": SYSTEM, "messages": [{"role": "user", "content": user + extra}],
        }).encode()
        r = client.request("https://api.anthropic.com/v1/messages", method="POST", data=body,
                           headers={"x-api-key": settings.claude_api_key,
                                    "anthropic-version": "2023-06-01", "content-type": "application/json"})
        if r.status != 200:
            return None, f"api status {r.status}"
        try:
            data = json.loads(r.body)
            text = "".join(b.get("text", "") for b in data.get("content", []))
            text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            obj = json.loads(text)
        except Exception as e:
            return None, f"parse error: {e}"
        obj.setdefault("summary", "")
        obj.setdefault("evidence", [])
        obj["resolved_by"] = "ai"
        ok, why = schema.validate_diagnosis(obj)
        return (obj, "") if ok else (None, why)

    obj, err = call()
    if obj is None:                                   # one retry echoing the error (hallucination guard)
        obj, err = call(f"\n\nYour previous reply was INVALID ({err}). Return valid JSON only.")
    if obj is None:
        return _ai_mock(event)                        # never publish garbage — deterministic fallback
    obj["confidence_score"] = min(float(obj["confidence_score"]), AI_CONFIDENCE_CAP)
    return obj


def ai_diagnose(event: dict, settings=None) -> dict:
    mode = getattr(settings, "ai_mode", "mock") if settings else "mock"
    return _ai_live(event, settings) if mode == "live" else _ai_mock(event)


# ---------------------------------------------------------------------------
# ORCHESTRATION
# ---------------------------------------------------------------------------
def diagnose(event: dict, settings=None) -> dict:
    d = deterministic_diagnose(event)
    if d is None:
        d = ai_diagnose(event, settings)
    ok, why = schema.validate_diagnosis(d)
    if not ok:
        raise ValueError(f"diagnosis failed schema: {why}")
    return d
