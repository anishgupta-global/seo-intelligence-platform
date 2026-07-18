#!/usr/bin/env python3
"""
CLI entrypoint for the SEO Intelligence Platform reference implementation.

    python run_audit.py                         # audit default site (mock AI/Slack)
    python run_audit.py https://example.com     # audit any site
    python run_audit.py https://example.com --max-pages 100

LIVE mode is automatic when these env vars are present:
    CLAUDE_API_KEY        -> real Claude executive summary
    SLACK_WEBHOOK_URL     -> posts the alert to Slack for real
    DATAFORSEO_LOGIN/_PASSWORD -> (reserved for SERP/GEO collectors)
"""
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from seo_intel.config import Settings
from seo_intel import pipeline


def main():
    args = [a for a in sys.argv[1:]]
    url = "https://anishgupta.eu"
    max_pages = 250
    i = 0
    while i < len(args):
        if args[i] == "--max-pages" and i + 1 < len(args):
            max_pages = int(args[i + 1]); i += 2
        elif args[i].startswith("http"):
            url = args[i]; i += 1
        else:
            i += 1

    settings = Settings(start_url=url, max_pages=max_pages)
    result = pipeline.run(settings)

    b = result["bands"]
    print("\n" + "=" * 72)
    print(f"AUDIT COMPLETE — {url}   [AI={result['ai_mode']}]")
    print(f"  pages {result['pages']} · issues {result['issues']} · "
          f"P0 {b.get('P0',0)} · P1 {b.get('P1',0)} · P2 {b.get('P2',0)} · "
          f"rejects {result['rejects']}")
    ai = result["ai_summary"]
    print(f"  AI risk={ai.get('risk_level')} · cost=${result['cost']:.4f}")
    print(f"  \"{ai.get('headline','')}\"")
    print("=" * 72)
    print("Reports:")
    for k, v in result["reports"].items():
        print(f"   {k:5} {v}")
    print("\nOpen dashboard.html in a browser to view the visual report.")


if __name__ == "__main__":
    main()
