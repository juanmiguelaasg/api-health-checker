from __future__ import annotations

import customtkinter as ctk

from .. import theme as t
from .. import widgets as w
from .base import Page


class EndpointsPage(Page):
    title = "Endpoints"
    subtitle = "Expectations, response time trend and failure history per endpoint"

    def __init__(self, master, app) -> None:
        super().__init__(master, app)
        body = self.body
        body.grid_columnconfigure(0, weight=5, uniform="ep")
        body.grid_columnconfigure(1, weight=6, uniform="ep")
        body.grid_rowconfigure(0, weight=1)
        self.selected_name: str | None = None

        self.table = w.DataTable(body, height=12)
        self.table.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.table.set_columns([
            ("name", "Endpoint", 190), ("status", "Status", 110, "w", False),
            ("http", "HTTP", 60, "e", False), ("ms", "Response", 90, "e", False),
            ("up", "24h", 76, "e", False),
        ])
        self.table.tree.bind("<<TreeviewSelect>>", lambda _e: self._on_select())

        d = ctk.CTkFrame(body, fg_color=t.CARD, corner_radius=14, border_width=1, border_color=t.BORDER)
        d.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        d.grid_columnconfigure(0, weight=1)
        d.grid_rowconfigure(5, weight=1)
        head = ctk.CTkFrame(d, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 0))
        head.grid_columnconfigure(0, weight=1)
        self.d_name = ctk.CTkLabel(head, text="Select an endpoint", font=w.FONTS.h3, text_color=t.TEXT, anchor="w")
        self.d_name.grid(row=0, column=0, sticky="w")
        self.d_pill = w.pill(head, "–", t.DIM)
        self.d_pill.grid(row=0, column=1, sticky="e")
        self.d_url = ctk.CTkLabel(head, text="", font=w.FONTS.mono_small, text_color=t.MUTED, anchor="w")
        self.d_url.grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))

        self.chips = ctk.CTkFrame(d, fg_color="transparent")
        self.chips.grid(row=1, column=0, sticky="w", padx=18, pady=(10, 0))

        stats = ctk.CTkFrame(d, fg_color="transparent")
        stats.grid(row=2, column=0, sticky="ew", padx=20, pady=(14, 0))
        self.stat_vals = {}
        for i, key in enumerate(("Last", "Avg 24h", "p95 24h", "24 hours", "30 days")):
            stats.grid_columnconfigure(i, weight=1, uniform="st")
            ctk.CTkLabel(stats, text=key.upper(), font=w.FONTS.caption, text_color=t.DIM,
                         anchor="w").grid(row=0, column=i, sticky="w")
            v = ctk.CTkLabel(stats, text="–", font=w.FONTS.h2, text_color=t.TEXT, anchor="w")
            v.grid(row=1, column=i, sticky="w")
            self.stat_vals[key] = v

        self.chart = w.LineChart(d, height=150, fmt=lambda v: f"{v:.0f} ms", max_points=100)
        self.chart.grid(row=3, column=0, sticky="ew", padx=12, pady=(14, 0))
        self.bars = w.UptimeBars(d, count=100, height=18)
        self.bars.grid(row=4, column=0, sticky="ew", padx=(74, 22), pady=(8, 0))

        log = ctk.CTkFrame(d, fg_color="transparent")
        log.grid(row=5, column=0, sticky="nsew", padx=18, pady=(14, 18))
        log.grid_columnconfigure(0, weight=1)
        log.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(log, text="RECENT FAILURES", font=w.FONTS.caption, text_color=t.DIM,
                     anchor="w").grid(row=0, column=0, sticky="w")
        self.log = ctk.CTkTextbox(log, font=w.FONTS.mono_small, fg_color=t.SURFACE, text_color=t.MUTED,
                                  border_width=1, border_color=t.BORDER, corner_radius=10, wrap="word", height=90)
        self.log.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        self.log.tag_config("ts", foreground=t.DIM)
        self.log.tag_config("err", foreground=t.ROSE)

    def select(self, name: str) -> None:
        self.selected_name = name
        if name in self.table.tree.get_children():
            self.table.tree.selection_set(name)
            self.table.tree.see(name)
        if self.snapshot:
            self._render_detail(self.snapshot)

    def _on_select(self) -> None:
        sel = self.table.selected()
        if sel and sel != self.selected_name:
            self.selected_name = sel
            if self.snapshot:
                self._render_detail(self.snapshot)

    def render(self, snap) -> None:
        items = []
        for e in snap.endpoints:
            last = e.last
            label, _ = t.STATUS[e.status]
            items.append((e.name, (e.name, label, last["status"] if last and last["status"] else "–",
                                   t.fmt_ms(last["elapsed_ms"]) if last else "–", t.fmt_pct(e.up24, 1)),
                          (e.status,)))
        self.table.sync(items)
        names = [e.name for e in snap.endpoints]
        if self.selected_name not in names and names:
            self.selected_name = names[0]
        if self.selected_name and self.table.selected() != self.selected_name:
            self.table.tree.selection_set(self.selected_name)
        self._render_detail(snap)

    def _render_detail(self, snap) -> None:
        ep = next((e for e in snap.endpoints if e.name == self.selected_name), None)
        if ep is None:
            return
        label, color = t.STATUS[ep.status]
        self.d_name.configure(text=ep.name)
        w.set_pill(self.d_pill, label.upper(), color)
        self.d_url.configure(text=f"{ep.method}  {ep.url}")

        for c in self.chips.winfo_children():
            c.destroy()
        chips = [f"HTTP {', '.join(map(str, ep.expected_status))}", f"≤ {ep.max_ms} ms", f"SLA {ep.sla_target:g}%"]
        if ep.has_schema:
            chips.append("JSON schema")
        chips += [f"contains: {c[:24]}" for c in ep.contains]
        for c in chips:
            ctk.CTkLabel(self.chips, text=f"  {c}  ", font=w.FONTS.small, text_color=t.TEXT, fg_color=t.SURFACE,
                         corner_radius=8, height=24).pack(side="left", padx=2)

        last = ep.last
        self.stat_vals["Last"].configure(text=t.fmt_ms(last["elapsed_ms"]) if last else "–")
        self.stat_vals["Avg 24h"].configure(text=t.fmt_ms(ep.avg))
        self.stat_vals["p95 24h"].configure(text=t.fmt_ms(ep.p95),
                                            text_color=t.ROSE if ep.p95 and ep.p95 > ep.max_ms else t.TEXT)
        self.stat_vals["24 hours"].configure(text=t.fmt_pct(ep.up24))
        self.stat_vals["30 days"].configure(text=t.fmt_pct(ep.up30), text_color=t.GREEN if ep.sla_met else t.ROSE)

        data = [r["elapsed_ms"] for r in ep.results[-100:] if r.get("elapsed_ms") is not None]
        self.chart.set_series([w.Series(ep.name, t.CYAN, data)], threshold=ep.max_ms)
        self.bars.set_results(ep.results)

        failures = [r for r in ep.results if not r["ok"]][-15:][::-1]
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        if not failures:
            self.log.insert("end", "No failures recorded.")
        for r in failures:
            self.log.insert("end", t.fmt_time(r["timestamp"], True) + "  ", "ts")
            self.log.insert("end", f"HTTP {r['status'] or '–'} · {r['attempts']} attempt(s)\n")
            for err in r["errors"]:
                self.log.insert("end", f"   {err}\n", "err")
        self.log.configure(state="disabled")
