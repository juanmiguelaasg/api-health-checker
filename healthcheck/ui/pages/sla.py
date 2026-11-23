from __future__ import annotations

import csv
from tkinter import filedialog

import customtkinter as ctk

from .. import theme as t
from .. import widgets as w
from .base import Page


class SlaPage(Page):
    title = "SLA Report"
    subtitle = "Availability and error budget per endpoint, measured against the SLA target"

    def __init__(self, master, app) -> None:
        super().__init__(master, app)
        body = self.body
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)
        w.ghost_button(self.actions, "Export CSV", self._export, width=130).pack(side="right")

        self.panel = w.Panel(body, "30-day availability", "The white marker is the SLA target")
        self.panel.grid(row=0, column=0, sticky="ew")
        self.panel.body.grid_columnconfigure(0, weight=1)
        self.bars = w.SlaBars(self.panel.body)
        self.bars.grid(row=0, column=0, sticky="ew", padx=8, pady=(4, 4))
        self.summary = ctk.CTkLabel(self.panel.slot, text="", font=w.FONTS.small, text_color=t.MUTED)
        self.summary.pack(side="right")

        self.table = w.DataTable(body, height=8)
        self.table.grid(row=1, column=0, sticky="nsew", pady=(16, 0))
        self.table.set_columns([
            ("name", "Endpoint", 200), ("target", "Target", 80, "e", False),
            ("d1", "24 hours", 90, "e", False), ("d7", "7 days", 90, "e", False),
            ("d30", "30 days", 90, "e", False), ("met", "Met", 90, "center", False),
            ("budget", "Error budget left", 130, "e", False), ("avg", "Avg", 90, "e", False),
            ("p95", "p95", 90, "e", False), ("checks", "Checks", 80, "e", False),
        ])
        self.rows: list[tuple] = []

    def render(self, snap) -> None:
        eps = snap.endpoints
        self.bars.set_rows([(e.name, e.up30, e.sla_target) for e in eps])
        measured = [e for e in eps if e.up30 is not None]
        met = sum(1 for e in measured if e.sla_met)
        self.summary.configure(text=f"{met} / {len(measured)} endpoints on target",
                               text_color=t.GREEN if met == len(measured) else t.ROSE)
        items, self.rows = [], []
        for e in eps:
            budget = e.error_budget
            values = (e.name, f"{e.sla_target:g}%", t.fmt_pct(e.up24, 3), t.fmt_pct(e.up7, 3),
                      t.fmt_pct(e.up30, 3), "–" if e.up30 is None else ("yes" if e.sla_met else "NO"),
                      "–" if budget is None else f"{budget:.0f}%", t.fmt_ms(e.avg), t.fmt_ms(e.p95),
                      len(e.results))
            status = "none" if e.up30 is None else ("ok" if e.sla_met else "down")
            items.append((e.name, values, (status,)))
            self.rows.append(values)
        self.table.sync(items)

    def _export(self) -> None:
        if not self.rows:
            self.app.toast("No data to export yet.", t.AMBER)
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="sla-report.csv",
                                            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            wr = csv.writer(f, delimiter=",")
            wr.writerow(["Endpoint", "SLA target", "24 hours", "7 days", "30 days", "Met", "Error budget", "Avg",
                         "p95", "Checks (last 200)"])
            wr.writerows(self.rows)
        self.app.toast(f"SLA report saved: {path}", t.GREEN)
