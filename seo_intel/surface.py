"""
Surface layer. Priority-routed Slack alerts (webhook or console), a Markdown +
JSON report, and a self-contained HTML dashboard. In the full architecture n8n
owns routing; here the notifier POSTs directly to keep the demo self-contained.
"""
from __future__ import annotations
import json
import smtplib
from email.message import EmailMessage
from collections import Counter
from .net import RobustClient


def _slack_blocks(target, scored, ai_summary, run_meta):
    bands = Counter(s.band for s in scored)
    p0 = [s for s in scored if s.band == "P0"][:5]
    lines = [f"*SEO audit — {target}*",
             f"{run_meta['pages']} pages · {len(scored)} issues · "
             f"P0 {bands.get('P0',0)} · P1 {bands.get('P1',0)} · P2 {bands.get('P2',0)}",
             f"_AI ({ai_summary.get('_mode','mock')}): {ai_summary.get('headline','')}_"]
    if p0:
        lines.append("*P0 — act now:*")
        for s in p0:
            lines.append(f"• `{s.issue.check}` — {s.issue.url}\n   {s.issue.detail}")
    lines.append("*Top recommendations:*")
    for a in ai_summary.get("top_actions", [])[:3]:
        lines.append(f"• {a['action']} — _{a.get('why','')}_")
    return "\n".join(lines)


def notify_slack(settings, scored, ai_summary, run_meta, log=print):
    text = _slack_blocks(settings.start_url, scored, ai_summary, run_meta)
    if settings.slack_mode == "live":
        client = RobustClient(timeout=15, max_retries=3)
        r = client.request(settings.slack_webhook, method="POST",
                           data=json.dumps({"text": text}).encode(),
                           headers={"content-type": "application/json"})
        log(f"[surface] Slack POST -> status {r.status}")
    else:
        log("[surface] Slack (console mode — set SLACK_WEBHOOK_URL to post for real):")
        log("-" * 60 + "\n" + text + "\n" + "-" * 60)


def _email_html(settings, scored, ai_summary, run_meta):
    bands = Counter(s.band for s in scored)
    p0 = [s for s in scored if s.band == "P0"][:8]
    p0_rows = "".join(
        f"<tr><td style='color:#c0392b;font-weight:700'>{s.issue.check}</td>"
        f"<td>{s.issue.url.replace('https://','')}</td><td>{s.issue.detail}</td></tr>" for s in p0)
    acts = "".join(f"<li><b>{a['action']}</b> — {a.get('why','')}</li>"
                   for a in ai_summary.get("top_actions", [])[:5])
    return f"""<div style="font:14px/1.6 system-ui,sans-serif;color:#1a1a1a;max-width:640px">
<h2 style="margin:0 0 4px">SEO Audit — {settings.start_url}</h2>
<p style="color:#666;margin:0 0 16px">{run_meta['pages']} pages · {len(scored)} issues ·
 <b>P0 {bands.get('P0',0)}</b> · P1 {bands.get('P1',0)} · P2 {bands.get('P2',0)} ·
 AI risk: {ai_summary.get('risk_level','?')}</p>
<div style="background:#f4f6fa;border-left:4px solid #2d6cdf;padding:12px 16px;border-radius:6px">
 <b>Summary:</b> {ai_summary.get('headline','')}<ul>{acts}</ul></div>
{f'<h3>P0 — act now</h3><table cellpadding=6 style="border-collapse:collapse;font-size:13px"><tr style="color:#888"><th align=left>Check</th><th align=left>Page</th><th align=left>Detail</th></tr>{p0_rows}</table>' if p0 else '<p>No P0 issues.</p>'}
<p style="color:#999;font-size:12px;margin-top:20px">Automated by SEO Intelligence Platform · mode: AI={ai_summary.get('_mode')}</p>
</div>"""


def notify_email(settings, scored, ai_summary, run_meta, log=print):
    bands = Counter(s.band for s in scored)
    subject = (f"SEO Audit — {settings.start_url.replace('https://','')} — "
               f"P0 {bands.get('P0',0)} · P1 {bands.get('P1',0)} · {len(scored)} issues")
    text = _slack_blocks(settings.start_url, scored, ai_summary, run_meta)
    if settings.email_mode != "live":
        log(f"[surface] Email OFF (dry-run). Would send to <EMAIL_TO> · subject: {subject}")
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.email_from
    msg["To"] = settings.email_to
    msg.set_content(text)
    msg.add_alternative(_email_html(settings, scored, ai_summary, run_meta), subtype="html")
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as s:
            s.starttls()
            s.login(settings.email_from, settings.email_app_password)
            s.send_message(msg)
        log(f"[surface] Email sent -> {settings.email_to}")
    except Exception as e:
        log(f"[surface] Email FAILED: {e}")


def write_reports(settings, pages, scored, ai_summary, run_meta):
    bands = Counter(s.band for s in scored)
    checks = Counter(s.issue.check for s in scored)
    out = settings.out_dir

    # ---- JSON ----
    (out / "report.json").write_text(json.dumps({
        "target": settings.start_url, "run": run_meta, "ai_summary": ai_summary,
        "bands": dict(bands), "checks": dict(checks),
        "top": [{"priority": s.priority, "band": s.band, "check": s.issue.check,
                 "url": s.issue.url, "detail": s.issue.detail} for s in scored[:60]],
    }, indent=2), encoding="utf-8")

    # ---- Markdown ----
    md = [f"# SEO Audit — {settings.start_url}",
          f"_{run_meta['pages']} pages · {len(scored)} issues · AI mode: {ai_summary.get('_mode')}_\n",
          f"**AI summary ({ai_summary.get('risk_level','?')} risk):** {ai_summary.get('headline','')}\n",
          "## Recommendations"]
    for a in ai_summary.get("top_actions", []):
        md.append(f"- **{a['action']}** — {a.get('why','')}")
    md += ["\n## Issues by type", "| Check | Count |", "|---|---|"]
    for c, n in checks.most_common():
        md.append(f"| {c} | {n} |")
    md += ["\n## Top 40 findings", "| Priority | Band | Check | Page | Detail |", "|---|---|---|---|---|"]
    for s in scored[:40]:
        u = s.issue.url.replace("https://", "")
        md.append(f"| {s.priority:.3f} | {s.band} | {s.issue.check} | {u[:44]} | {s.issue.detail[:60]} |")
    (out / "report.md").write_text("\n".join(md), encoding="utf-8")

    # ---- HTML dashboard (self-contained) ----
    rows = "".join(
        f"<tr class='{s.band}'><td>{s.priority:.3f}</td><td><b>{s.band}</b></td>"
        f"<td>{s.issue.check}</td><td>{s.issue.url.replace('https://','')}</td>"
        f"<td>{s.issue.detail}</td></tr>" for s in scored[:120])
    acts = "".join(f"<li><b>{a['action']}</b> — {a.get('why','')}</li>"
                   for a in ai_summary.get("top_actions", []))
    html = f"""<!doctype html><meta charset=utf-8><title>SEO Audit — {settings.start_url}</title>
<style>
 body{{font:14px/1.5 system-ui,sans-serif;margin:0;background:#0b0e14;color:#e6e9ef}}
 header{{padding:20px 28px;background:#111725;border-bottom:1px solid #223}}
 h1{{margin:0;font-size:18px}} .sub{{color:#8b93a7;font-size:13px;margin-top:4px}}
 .cards{{display:flex;gap:12px;padding:20px 28px;flex-wrap:wrap}}
 .card{{background:#111725;border:1px solid #223;border-radius:10px;padding:14px 18px;min-width:120px}}
 .card .n{{font-size:24px;font-weight:700}} .card .l{{color:#8b93a7;font-size:12px}}
 .ai{{margin:0 28px 16px;padding:14px 18px;background:#0f1a2e;border:1px solid #1d3a63;border-radius:10px}}
 table{{width:calc(100% - 56px);margin:0 28px 28px;border-collapse:collapse;font-size:13px}}
 th,td{{text-align:left;padding:7px 10px;border-bottom:1px solid #1c2333;vertical-align:top}}
 th{{color:#8b93a7;font-weight:600}} tr.P0 td:nth-child(2){{color:#ff6b6b}}
 tr.P1 td:nth-child(2){{color:#ffa94d}} tr.P2 td:nth-child(2){{color:#ffd43b}}
</style>
<header><h1>SEO Intelligence — {settings.start_url}</h1>
<div class=sub>{run_meta['pages']} pages · {len(scored)} issues · run {run_meta.get('duration_s','?')}s · AI={ai_summary.get('_mode')}</div></header>
<div class=cards>
 <div class=card><div class=n>{bands.get('P0',0)}</div><div class=l>P0 critical</div></div>
 <div class=card><div class=n>{bands.get('P1',0)}</div><div class=l>P1 high</div></div>
 <div class=card><div class=n>{bands.get('P2',0)}</div><div class=l>P2 moderate</div></div>
 <div class=card><div class=n>{run_meta['pages']}</div><div class=l>pages crawled</div></div>
</div>
<div class=ai><b>AI summary ({ai_summary.get('risk_level','?')} risk):</b> {ai_summary.get('headline','')}
<ul>{acts}</ul></div>
<table><tr><th>Priority</th><th>Band</th><th>Check</th><th>Page</th><th>Detail</th></tr>{rows}</table>"""
    (out / "dashboard.html").write_text(html, encoding="utf-8")
    return {"json": out / "report.json", "md": out / "report.md", "html": out / "dashboard.html"}
