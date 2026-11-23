"""Generate a static HTML/CSS status page (no JavaScript)."""
from __future__ import annotations

import time
from html import escape
from pathlib import Path

from .history import History, sla_report

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--text:#1d2330;--muted:#667085;--border:#e4e7ec;
--ok:#12b76a;--fail:#f04438;--warn:#f79009;--none:#d0d5dd;--line:#2e90fa}
@media (prefers-color-scheme:dark){:root{--bg:#0f1218;--card:#171b23;--text:#e6e9ef;
--muted:#98a2b3;--border:#2a303c;--none:#3a4150}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:960px;margin:0 auto;padding:32px 16px}
h1{font-size:24px;margin:0 0 4px}.sub{color:var(--muted);margin:0 0 24px}
.banner{padding:16px 20px;border-radius:10px;color:#fff;font-weight:600;margin-bottom:24px}
.banner.ok{background:var(--ok)}.banner.fail{background:var(--fail)}.banner.warn{background:var(--warn)}
.card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px 20px;margin-bottom:14px}
.head{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.name{font-weight:600}.url{color:var(--muted);font-size:13px;word-break:break-all}
.pill{border-radius:999px;padding:2px 10px;font-size:13px;font-weight:600;color:#fff;white-space:nowrap}
.pill.ok{background:var(--ok)}.pill.fail{background:var(--fail)}.pill.warn{background:var(--warn)}.pill.none{background:var(--none)}
.bars{display:flex;gap:2px;margin:14px 0 6px;height:28px}
.bars span{flex:1;border-radius:2px;background:var(--none)}
.bars .ok{background:var(--ok)}.bars .fail{background:var(--fail)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin-top:10px;font-size:13px}
.stats b{display:block;font-size:16px}.muted{color:var(--muted)}
.bad{color:var(--fail)}.good{color:var(--ok)}
svg{width:100%;height:48px;display:block;margin-top:8px}
.err{font-size:13px;color:var(--fail);margin-top:8px}
footer{color:var(--muted);font-size:12px;margin-top:24px;text-align:center}
"""

BARS = 60


def _pct(v: float | None) -> str:
    return "–" if v is None else f"{v:.2f}%"


def _ms(v: float | None) -> str:
    return "–" if v is None else f"{v:.0f} ms"


def _sparkline(values: list[float], limit_ms: int) -> str:
    if len(values) < 2:
        return ""
    w, h = 300, 48
    top = max(max(values), limit_ms) * 1.1
    pts = " ".join(f"{i * w / (len(values) - 1):.1f},{h - v / top * h:.1f}" for i, v in enumerate(values))
    ly = h - limit_ms / top * h
    return (f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" role="img" aria-label="Response time history">'
            f'<line x1="0" y1="{ly:.1f}" x2="{w}" y2="{ly:.1f}" stroke="var(--fail)" stroke-dasharray="4 4" '
            f'stroke-width="1" vector-effect="non-scaling-stroke" opacity=".6"/>'
            f'<polyline points="{pts}" fill="none" stroke="var(--line)" stroke-width="2" '
            f'vector-effect="non-scaling-stroke"/></svg>')


def render(config, history: History, refresh_seconds: int | None = None) -> str:
    report = {r["name"]: r for r in sla_report(config, history)}
    cards, n_fail, n_degraded = [], 0, 0

    for ep in config.endpoints:
        results = history.results(ep.name)
        last = results[-1] if results else None
        row = report[ep.name]
        st = row["state"]

        if last is None:
            pill, label = "none", "No data"
        elif st["alerting"]:
            pill, label = "fail", "Outage"
            n_fail += 1
        elif not last["ok"]:
            pill, label = "warn", "Unconfirmed failure"
            n_degraded += 1
        else:
            pill, label = "ok", "Operational"

        recent = results[-BARS:]
        bars = ['<span></span>'] * (BARS - len(recent)) + [
            f'<span class="{"ok" if r["ok"] else "fail"}" title="'
            f'{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["timestamp"]))} – '
            f'{escape("; ".join(r["errors"]) or _ms(r["elapsed_ms"]))}"></span>' for r in recent]
        spark = _sparkline([r["elapsed_ms"] for r in results[-100:] if r.get("elapsed_ms") is not None],
                           ep.max_response_ms)
        sla_cls = "good" if row["met"] else "bad"
        err = (f'<div class="err">{escape("; ".join(last["errors"]))}</div>'
               if last and last["errors"] else "")

        cards.append(f"""
<div class="card">
  <div class="head"><div><div class="name">{escape(ep.name)}</div>
  <div class="url">{escape(ep.method)} {escape(ep.url)}</div></div>
  <span class="pill {pill}">{label}</span></div>
  <div class="bars">{''.join(bars)}</div>
  <div class="muted" style="font-size:12px">Last {BARS} checks</div>
  {spark}
  <div class="stats">
    <div><span class="muted">Last response</span><b>{_ms(last["elapsed_ms"]) if last else "–"}</b></div>
    <div><span class="muted">Avg / p95 (24h)</span><b>{_ms(row["avg"])} / {_ms(row["p95"])}</b></div>
    <div><span class="muted">Uptime 24h</span><b>{_pct(row["24h"])}</b></div>
    <div><span class="muted">7 days</span><b>{_pct(row["7d"])}</b></div>
    <div><span class="muted">30 days / SLA target</span><b class="{sla_cls}">{_pct(row["30d"])} / {ep.sla_target}%</b></div>
  </div>{err}
</div>""")

    if n_fail:
        banner = ("fail", f"{n_fail} service(s) down")
    elif n_degraded:
        banner = ("warn", f"{n_degraded} service(s) reporting errors, awaiting confirmation")
    else:
        banner = ("ok", "All systems operational")

    meta = f'<meta http-equiv="refresh" content="{refresh_seconds}">' if refresh_seconds else ""
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
{meta}<title>API Status</title><style>{CSS}</style></head>
<body><div class="wrap">
<h1>API Status</h1><p class="sub">Updated {now}</p>
<div class="banner {banner[0]}">{banner[1]}</div>
{''.join(cards)}
<footer>Automated API Health-Checker</footer>
</div></body></html>"""


def write_status_page(config, history: History, path: Path | None = None) -> Path:
    path = Path(path or config.settings.status_page)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(config, history, refresh_seconds=config.settings.interval_seconds), encoding="utf-8")
    return path
