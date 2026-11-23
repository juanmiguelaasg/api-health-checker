from __future__ import annotations

import time
import webbrowser

import customtkinter as ctk

from .. import theme as t
from .. import widgets as w
from .base import Page


class ServiceRow(ctk.CTkFrame):
    def __init__(self, master, app, name: str) -> None:
        super().__init__(master, fg_color="transparent", corner_radius=10, height=52)
        self.app, self.name = app, name
        self.grid_columnconfigure(1, weight=3, uniform="svc")
        self.grid_columnconfigure(2, weight=4, uniform="svc")
        self.dot = ctk.CTkFrame(self, width=10, height=10, corner_radius=5, fg_color=t.DIM)
        self.dot.grid(row=0, column=0, rowspan=2, padx=(12, 12))
        self.title = ctk.CTkLabel(self, text=name, font=w.FONTS.body_bold, text_color=t.TEXT, anchor="w", height=20)
        self.title.grid(row=0, column=1, sticky="sw", pady=(8, 0))
        self.url = ctk.CTkLabel(self, text="", font=w.FONTS.small, text_color=t.DIM, anchor="w", height=18)
        self.url.grid(row=1, column=1, sticky="nw", pady=(0, 8))
        self.bars = w.UptimeBars(self, count=48, height=24)
        self.bars.grid(row=0, column=2, rowspan=2, sticky="ew", padx=16)
        self.ms = ctk.CTkLabel(self, text="–", font=w.FONTS.body_bold, text_color=t.TEXT, width=80, anchor="e")
        self.ms.grid(row=0, column=3, rowspan=2, padx=(0, 8))
        self.up = ctk.CTkLabel(self, text="–", font=w.FONTS.body, text_color=t.MUTED, width=76, anchor="e")
        self.up.grid(row=0, column=4, rowspan=2, padx=(0, 12))
        self.pill = w.pill(self, "–", t.DIM)
        self.pill.grid(row=0, column=5, rowspan=2, padx=(0, 12))
        for wid in (self, self.title, self.url, self.ms, self.up):
            wid.bind("<Button-1>", lambda _e: app.open_endpoint(name))
            wid.bind("<Enter>", lambda _e: self.configure(fg_color=t.CARD_HOVER))
            wid.bind("<Leave>", lambda _e: self.configure(fg_color="transparent"))

    def update_row(self, ep) -> None:
        label, color = t.STATUS[ep.status]
        self.dot.configure(fg_color=color)
        self.url.configure(text=f"{ep.method}  {ep.url}")
        self.bars.set_results(ep.results)
        last = ep.last
        ms = last["elapsed_ms"] if last else None
        self.ms.configure(text=t.fmt_ms(ms), text_color=t.ROSE if ms and ms > ep.max_ms else t.TEXT)
        self.up.configure(text=t.fmt_pct(ep.up24, 1))
        w.set_pill(self.pill, label.upper(), color)


class OverviewPage(Page):
    title = "Overview"
    subtitle = "Live health of your REST endpoints, measured from the outside"

    def __init__(self, master, app) -> None:
        super().__init__(master, app)
        body = self.body
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(2, weight=1)

        w.ghost_button(self.actions, "Status page ↗", self._open_page, width=130).pack(side="right")
        self.clock = ctk.CTkLabel(self.actions, text="", font=w.FONTS.small, text_color=t.MUTED)
        self.clock.pack(side="right", padx=16)

        cards = ctk.CTkFrame(body, fg_color="transparent")
        cards.grid(row=0, column=0, sticky="ew")
        for i in range(4):
            cards.grid_columnconfigure(i, weight=1, uniform="cards")
        self.c_services = w.StatCard(cards, "Services", t.GREEN, min_y_max=1)
        self.c_latency = w.StatCard(cards, "Avg response time", t.CYAN, min_y_max=50)
        self.c_uptime = w.StatCard(cards, "Availability", t.VIOLET, y_max=100)
        self.c_alerts = w.StatCard(cards, "Failures per run", t.ROSE, min_y_max=1)
        for i, c in enumerate((self.c_services, self.c_latency, self.c_uptime, self.c_alerts)):
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0 if i == 3 else 8))

        mid = ctk.CTkFrame(body, fg_color="transparent")
        mid.grid(row=1, column=0, sticky="nsew", pady=16)
        mid.grid_columnconfigure(0, weight=3, uniform="mid")
        mid.grid_columnconfigure(1, weight=2, uniform="mid")
        self.hist = w.Panel(mid, "Response time history", "Per endpoint, last 60 checks")
        self.hist.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.hist.body.grid_columnconfigure(0, weight=1)
        self.chart = w.LineChart(self.hist.body, height=190, fmt=lambda v: f"{v:.0f} ms", fill=False)
        self.chart.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

        self.ev_panel = w.Panel(mid, "Recent events", "Confirmed alerts and recoveries")
        self.ev_panel.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self.ev_panel.body.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(self.ev_panel.slot, text="View all →", width=70, height=26, fg_color="transparent",
                      hover_color=t.CARD_HOVER, text_color=t.CYAN, font=w.FONTS.small,
                      command=lambda: app.show("events")).pack(side="right")
        self.ev_rows: list[ctk.CTkFrame] = []

        self.svc = w.Panel(body, "Services", "Last 48 checks · green = passed, "
                                                   "amber = passed after a retry, red = failed")
        self.svc.grid(row=2, column=0, sticky="nsew")
        self.svc.body.grid_columnconfigure(0, weight=1)
        self.svc.body.grid_rowconfigure(0, weight=1)
        self.svc_list = ctk.CTkScrollableFrame(self.svc.body, fg_color="transparent",
                                               scrollbar_button_color=t.BORDER,
                                               scrollbar_button_hover_color=t.DIM)
        self.svc_list.grid(row=0, column=0, sticky="nsew")
        self.svc_list.grid_columnconfigure(0, weight=1)
        self.rows: dict[str, ServiceRow] = {}

    def _open_page(self) -> None:
        if self.snapshot and self.snapshot.status_page.exists():
            webbrowser.open(self.snapshot.status_page.resolve().as_uri())
        else:
            self.app.toast("The status page is created after the first run.", t.AMBER)

    def render(self, snap) -> None:
        eps = snap.endpoints
        self.clock.configure(text=f"Updated {t.fmt_time(snap.last_run)}" if snap.last_run else "Not run yet")
        runs = snap.runs[-60:]

        n_ok = sum(1 for e in eps if e.status == "ok")
        n_down = sum(1 for e in eps if e.status == "down")
        n_warn = sum(1 for e in eps if e.status == "warn")
        if n_down:
            badge, color = "OUTAGE", t.ROSE
        elif n_warn:
            badge, color = "WARNING", t.AMBER
        elif any(e.results for e in eps):
            badge, color = "OK", t.GREEN
        else:
            badge, color = "", t.DIM
        self.c_services.chart.y_max = max(1, len(eps))
        self.c_services.update_card(f"{n_ok} / {len(eps)}", f"{n_down} down  /  {n_warn} unconfirmed",
                                    badge, [r["ok"] for r in runs], color)

        last_avg = runs[-1]["avg_ms"] if runs else None
        p95s = [e.p95 for e in eps if e.p95 is not None]
        self.c_latency.update_card(t.fmt_ms(last_avg), f"slowest p95 (24h): {t.fmt_ms(max(p95s) if p95s else None)}",
                                   "LIVE" if self.app.monitor.enabled else "PAUSED",
                                   [r["avg_ms"] for r in runs if r.get("avg_ms") is not None])

        ups = [e.up24 for e in eps if e.up24 is not None]
        overall = sum(ups) / len(ups) if ups else None
        met = sum(1 for e in eps if e.sla_met and e.up30 is not None)
        measured = sum(1 for e in eps if e.up30 is not None)
        self.c_uptime.update_card(t.fmt_pct(overall), f"SLA met: {met} / {measured} endpoints (30 days)",
                                  "24H", [r["uptime24"] for r in runs if r.get("uptime24") is not None],
                                  t.GREEN if met == measured else t.ROSE)

        fails = [r["total"] - r["ok"] for r in runs]
        day_events = [e for e in snap.events if e["ts"] > time.time() - 86400 and e["kind"] != "RECOVERY"]
        self.c_alerts.update_card(str(fails[-1]) if fails else "–",
                                  f"{len(day_events)} alerts / escalations in 24h",
                                  f"{len(day_events)} ALERTS" if day_events else "QUIET",
                                  fails, t.ROSE if day_events else t.GREEN)

        series = [w.Series(e.name, t.SERIES[i % len(t.SERIES)],
                           [r["elapsed_ms"] for r in e.results[-60:] if r.get("elapsed_ms") is not None])
                  for i, e in enumerate(eps)]
        self.chart.set_series(series)
        self.hist.legend([(s.label if len(s.label) < 16 else s.label[:14] + "…", s.color) for s in series[:5]])

        self._render_events(snap.events[-6:][::-1])
        self._render_services(eps)

    def _render_events(self, events) -> None:
        for r in self.ev_rows:
            r.destroy()
        self.ev_rows = []
        if not events:
            lbl = ctk.CTkLabel(self.ev_panel.body, text="No events – all quiet.",
                               font=w.FONTS.small, text_color=t.DIM)
            lbl.grid(row=0, column=0, sticky="w", padx=8, pady=8)
            self.ev_rows.append(lbl)
            return
        for i, ev in enumerate(events):
            label, color = t.EVENT.get(ev["kind"], (ev["kind"], t.MUTED))
            row = ctk.CTkFrame(self.ev_panel.body, fg_color="transparent")
            row.grid(row=i, column=0, sticky="ew", padx=6, pady=3)
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkFrame(row, width=8, height=8, corner_radius=4, fg_color=color).grid(row=0, column=0, padx=(2, 10))
            ctk.CTkLabel(row, text=f"{label} · {ev['name']}", font=w.FONTS.small, text_color=t.TEXT,
                         anchor="w", height=20).grid(row=0, column=1, sticky="w")
            ctk.CTkLabel(row, text=t.fmt_ago(ev["ts"]), font=w.FONTS.small, text_color=t.DIM,
                         height=20).grid(row=0, column=2, sticky="e")
            self.ev_rows.append(row)

    def _render_services(self, eps) -> None:
        names = [e.name for e in eps]
        if names != list(self.rows):
            for r in self.rows.values():
                r.destroy()
            self.rows = {}
            for i, name in enumerate(names):
                row = ServiceRow(self.svc_list, self.app, name)
                row.grid(row=i, column=0, sticky="ew", pady=2)
                self.rows[name] = row
        for e in eps:
            self.rows[e.name].update_row(e)
