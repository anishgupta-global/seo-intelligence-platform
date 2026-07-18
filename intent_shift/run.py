#!/usr/bin/env python3
"""
Part 3 entrypoint. Runs the diagnostic over one fixture or all of them, prints the
verdict, self-tests against each fixture's expected cause, and pushes a formatted
Slack alert (webhook if SLACK_WEBHOOK_URL is set, else console).

    python -m intent_shift.run                 # run all fixtures (self-test)
    python -m intent_shift.run <fixture.json>  # run one

LIVE mode is automatic when CLAUDE_API_KEY (real intent/content call) and/or
SLACK_WEBHOOK_URL (real alert) are present.
"""
from __future__ import annotations
import sys
import json
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from intent_shift.detector import diagnose
try:
    from seo_intel.config import Settings
    from seo_intel.net import RobustClient
except Exception:
    Settings, RobustClient = None, None

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"

EMOJI = {"technical_decay": "🔴", "cannibalization": "🟠", "ai_overview_intrusion": "🔵",
         "serp_feature_expansion": "🟣", "intent_shift": "🟡", "content_decay": "🟢",
         "volatility": "⚪"}


def format_alert(event, d) -> str:
    e = EMOJI.get(d["issue_type"], "•")
    lines = [
        f"{e} *Ranking drop — {event['keyword']}*",
        f"`{event['page']}`",
        f"Position *{event['old_position']} → {event['new_position']}*",
        f"*Diagnosis:* `{d['issue_type']}`  (confidence {d['confidence_score']}, via {d['resolved_by']})",
        f"*Why:* {d.get('summary','')}",
        f"*Action:* {d['recommended_action']}",
    ]
    if d.get("evidence"):
        lines.append("*Evidence:* " + " · ".join(str(x) for x in d["evidence"][:4]))
    return "\n".join(lines)


def send_slack(settings, text):
    if settings and settings.slack_mode == "live" and RobustClient:
        r = RobustClient(timeout=15).request(
            settings.slack_webhook, method="POST",
            data=json.dumps({"text": text}).encode(),
            headers={"content-type": "application/json"})
        print(f"[alert] Slack POST -> {r.status}")
    else:
        print("[alert] (console — set SLACK_WEBHOOK_URL to post)\n" + "-" * 60)
        print(text)
        print("-" * 60)


def run_one(path: Path, settings):
    event = json.loads(path.read_text(encoding="utf-8"))
    d = diagnose(event, settings)
    expected = event.get("expected_issue_type")
    ok = "✓" if expected == d["issue_type"] else "✗"
    print(f"\n=== {path.name} ===")
    print(f"  scenario : {event.get('scenario')}")
    print(f"  expected : {expected}   got: {d['issue_type']}   {ok}")
    print(f"  verdict  : {d['issue_type']} (conf {d['confidence_score']}, {d['resolved_by']})")
    send_slack(settings, format_alert(event, d))
    return expected == d["issue_type"]


def main():
    settings = Settings() if Settings else None
    if settings:
        print(f"[mode] AI={settings.ai_mode} · Slack={settings.slack_mode}")
    args = sys.argv[1:]
    if args:
        run_one(Path(args[0]), settings)
        return
    fixtures = sorted(FIXTURES.glob("*.json"))
    passed = sum(run_one(f, settings) for f in fixtures)
    print(f"\n{'='*60}\nSELF-TEST: {passed}/{len(fixtures)} scenarios diagnosed as expected\n{'='*60}")


if __name__ == "__main__":
    main()
