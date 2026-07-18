"""
Enrich layer #2 — the AI layer (Claude). Sits ONLY over verified facts, and only
where language matters (executive summary + prioritised recommendations here).

Demonstrates the Q3 anti-hallucination contract end-to-end:
  strict JSON schema -> parse -> validate -> ONE retry echoing the error -> dead-letter
  + confidence capped at 0.7 (an AI verdict can never outrank a deterministic fact)
  + result cache (never re-bill identical input)
  + token/cost accounting

MOCK mode (no key): produces a deterministic structured summary from the findings,
through the SAME validation path, so the pipeline is complete without secrets.
LIVE mode (CLAUDE_API_KEY): calls the Anthropic Messages API via urllib.
"""
from __future__ import annotations
import json
import hashlib
from collections import Counter

from .net import RobustClient

PROMPT_VERSION = "exec-summary-v1"

# ---- output schema (structural validation; pydantic in production) ----
REQUIRED = {"risk_level": str, "headline": str, "top_actions": list, "confidence": (int, float)}
RISK_LEVELS = {"low", "medium", "high"}
CONFIDENCE_CAP = 0.7


def _valid(obj) -> tuple[bool, str]:
    if not isinstance(obj, dict):
        return False, "not a JSON object"
    for k, t in REQUIRED.items():
        if k not in obj:
            return False, f"missing key '{k}'"
        if not isinstance(obj[k], t):
            return False, f"'{k}' wrong type"
    if obj["risk_level"] not in RISK_LEVELS:
        return False, f"risk_level must be one of {RISK_LEVELS}"
    if not obj["top_actions"] or not all(isinstance(a, dict) and "action" in a for a in obj["top_actions"]):
        return False, "top_actions must be non-empty [{action, why}]"
    return True, ""


def summarize_findings(scored, pages) -> dict:
    """Compress verified facts into a small aggregate — never raw HTML/rows."""
    bands = Counter(s.band for s in scored)
    checks = Counter(s.issue.check for s in scored)
    return {
        "pages": len(pages),
        "issues_total": len(scored),
        "bands": dict(bands),
        "top_checks": checks.most_common(6),
        "top_examples": [{"check": s.issue.check, "url": s.issue.url, "detail": s.issue.detail}
                         for s in scored[:8]],
    }


class AIEngine:
    def __init__(self, settings, warehouse):
        self.s = settings
        self.wh = warehouse
        self.client = RobustClient(timeout=60, max_retries=3)
        self.tokens_in = self.tokens_out = 0
        self.cost = 0.0

    def _cache_key(self, task, payload):
        h = hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        return task, h, PROMPT_VERSION

    def executive_summary(self, findings: dict) -> dict:
        task = "executive_summary"
        ck = self._cache_key(task, findings)
        cached = self.wh.ai_cache_get(*ck)
        if cached:
            return {**cached, "_cached": True}

        result = (self._live(findings) if self.s.ai_mode == "live"
                  else self._mock(findings))

        result["confidence"] = min(float(result.get("confidence", 0.6)), CONFIDENCE_CAP)
        result["_mode"] = self.s.ai_mode
        self.wh.ai_cache_set(*ck, result, self.tokens_in, self.tokens_out, self.cost)
        return result

    # ---------------- MOCK ----------------
    def _mock(self, f: dict) -> dict:
        bands = f["bands"]
        risk = "high" if bands.get("P0") else "medium" if bands.get("P1") else "low"
        actions = []
        for check, n in f["top_checks"][:3]:
            actions.append({"action": f"Resolve {n}× {check.replace('_', ' ')}",
                            "why": "highest-frequency deterministic finding this run"})
        return {
            "risk_level": risk,
            "headline": (f"{f['issues_total']} issues across {f['pages']} pages; "
                         f"{bands.get('P0', 0)} P0 / {bands.get('P1', 0)} P1."),
            "top_actions": actions or [{"action": "No issues found", "why": "site is clean"}],
            "confidence": 0.6,
        }

    # ---------------- LIVE ----------------
    def _live(self, f: dict) -> dict:
        system = ("You are an SEO analyst. You receive VERIFIED, deterministic audit findings "
                  "(already true — do not re-judge them). Write an executive summary. "
                  "Respond with ONLY a JSON object matching this schema, no prose:\n"
                  '{"risk_level":"low|medium|high","headline":"string",'
                  '"top_actions":[{"action":"string","why":"string"}],"confidence":0.0-1.0}')
        user = "Findings:\n" + json.dumps(f, indent=2)
        obj, err = self._call_and_validate(system, user)
        if obj is None:  # one retry echoing the validation error
            obj, err = self._call_and_validate(
                system, user + f"\n\nYour previous output was INVALID ({err}). Return valid JSON only.")
        if obj is None:
            self.wh.dead_letter_ai("executive_summary", f, err)
            return self._mock(f)  # never publish garbage; fall back deterministically
        return obj

    def _call_and_validate(self, system, user):
        body = json.dumps({
            "model": self.s.claude_model,
            "max_tokens": 700,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }).encode()
        resp = self.client.request(
            "https://api.anthropic.com/v1/messages", method="POST", data=body,
            headers={"x-api-key": self.s.claude_api_key,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"})
        if resp.status != 200:
            return None, f"api status {resp.status}: {resp.error or resp.body[:120]}"
        try:
            data = json.loads(resp.body)
            usage = data.get("usage", {})
            self.tokens_in += usage.get("input_tokens", 0)
            self.tokens_out += usage.get("output_tokens", 0)
            self.cost += (self.tokens_in / 1e6 * self.s.price_in_per_m +
                          self.tokens_out / 1e6 * self.s.price_out_per_m)
            text = "".join(b.get("text", "") for b in data.get("content", []))
            text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            obj = json.loads(text)
        except Exception as e:
            return None, f"parse error: {e}"
        ok, why = _valid(obj)
        return (obj, "") if ok else (None, why)
