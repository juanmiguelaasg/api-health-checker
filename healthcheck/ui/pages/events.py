from __future__ import annotations

import customtkinter as ctk

from .. import theme as t
from .. import widgets as w
from .base import Page

FILTERS = {"All": None, "Alerts": "ALERT", "Escalations": "ESCALATION", "Recoveries": "RECOVERY"}


class EventsPage(Page):
    title = "Events"
    subtitle = "Confirmed failures only: alerts, escalations and recoveries"

    def __init__(self, master, app) -> None:
        super().__init__(master, app)
        body = self.body
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)
        self.filter = ctk.CTkSegmentedButton(self.actions, values=list(FILTERS), command=lambda _v: self.on_show(),
                                             font=w.FONTS.small, fg_color=t.SURFACE,
                                             selected_color=t.CARD_HOVER, selected_hover_color=t.CARD_HOVER,
                                             unselected_color=t.SURFACE, unselected_hover_color=t.CARD,
                                             text_color=t.TEXT, height=32)
        self.filter.set("All")
        self.filter.pack(side="right")

        self.counts = ctk.CTkFrame(body, fg_color="transparent")
        self.counts.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        self.count_labels = {}
        for i, (kind, (label, color)) in enumerate(t.EVENT.items()):
            self.counts.grid_columnconfigure(i, weight=1, uniform="cnt")
            card = ctk.CTkFrame(self.counts, fg_color=t.CARD, corner_radius=14, border_width=1, border_color=t.BORDER)
            card.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 8, 0 if i == 2 else 8))
            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(anchor="w", padx=18, pady=(14, 0))
            ctk.CTkFrame(top, width=8, height=8, corner_radius=4, fg_color=color).pack(side="left")
            ctk.CTkLabel(top, text=f"{label.upper()} · 24H", font=w.FONTS.caption,
                         text_color=t.MUTED).pack(side="left", padx=8)
            v = ctk.CTkLabel(card, text="0", font=w.FONTS.metric, text_color=t.TEXT)
            v.pack(anchor="w", padx=18, pady=(2, 14))
            self.count_labels[kind] = v

        self.table = w.DataTable(body, height=14)
        self.table.grid(row=1, column=0, sticky="nsew")
        self.table.set_columns([
            ("time", "Time", 160, "w", False), ("kind", "Type", 110, "w", False),
            ("name", "Endpoint", 190, "w", False), ("msg", "Details", 520),
        ])

    def render(self, snap) -> None:
        import time
        day = time.time() - 86400
        for kind, lbl in self.count_labels.items():
            lbl.configure(text=str(sum(1 for e in snap.events if e["kind"] == kind and e["ts"] > day)))
        kind = FILTERS[self.filter.get()]
        rows = [e for e in snap.events if kind is None or e["kind"] == kind][::-1]
        self.table.sync([
            (f"{e['ts']:.6f}-{e['kind']}-{e.get('name', '')}-{i}", (t.fmt_time(e["ts"], True), t.EVENT.get(e["kind"], (e["kind"],))[0],
                                     e.get("name", ""), e["message"]), (e["kind"],))
            for i, e in enumerate(rows)])
