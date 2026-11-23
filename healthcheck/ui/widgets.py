"""Custom widgets: canvas charts, stat cards, panels and a dark data table."""
from __future__ import annotations

import math
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk
from typing import Callable, Sequence

import customtkinter as ctk

from . import theme as t

SCALE = 1.0
FONTS = None


def px(value: float) -> int:
    return int(round(value * SCALE))


def round_rect(canvas: tk.Canvas, x1, y1, x2, y2, r, **kw):
    r = max(0.0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)


def nice_max(peak: float, floor: float = 1.0) -> float:
    peak = max(peak * 1.15, floor)
    mag = 10 ** math.floor(math.log10(peak))
    for step in (1, 2, 2.5, 5, 10):
        if peak <= step * mag:
            return step * mag
    return peak


# -----------------------------------------------------------------------------
@dataclass
class Series:
    label: str
    color: str
    data: Sequence[float]


class LineChart(tk.Canvas):
    """Right-aligned time-series chart with optional fill and threshold line."""

    def __init__(self, master, series: Sequence[Series] = (), max_points: int = 60,
                 y_max: float | None = None, min_y_max: float = 1.0, bg: str = t.CARD,
                 height: int = 120, show_labels: bool = True, show_grid: bool = True,
                 fill: bool = True, threshold: float | None = None,
                 fmt: Callable[[float], str] = lambda v: f"{v:.0f}") -> None:
        super().__init__(master, bg=bg, height=px(height), highlightthickness=0, bd=0)
        self.series = list(series)
        self.max_points, self.y_max, self.min_y_max = max_points, y_max, min_y_max
        self.bg, self.show_labels, self.show_grid, self.fill = bg, show_labels, show_grid, fill
        self.threshold, self.fmt = threshold, fmt
        self.bind("<Configure>", lambda _e: self.redraw())

    def set_series(self, series: Sequence[Series], threshold: float | None = None) -> None:
        self.series = list(series)
        self.threshold = threshold
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 20 or h < 20:
            return
        pl = px(62) if self.show_labels else px(2)
        pr, pt, pb = px(10), px(8), px(6)
        pw, ph = w - pl - pr, h - pt - pb
        if self.y_max is not None:
            y_max = self.y_max
        else:
            peak = max((max(s.data) for s in self.series if s.data), default=0.0)
            if self.threshold:
                peak = max(peak, self.threshold)
            y_max = nice_max(peak, self.min_y_max)

        if self.show_grid:
            for i in range(5):
                y = pt + ph * i / 4
                self.create_line(pl, y, w - pr, y, fill=t.GRID, dash=(2, 4) if i < 4 else None)
                if self.show_labels:
                    self.create_text(pl - px(10), y, text=self.fmt(y_max * (4 - i) / 4),
                                     anchor="e", fill=t.DIM, font=(t.FONT, 8))

        if self.threshold:
            ty = pt + ph - min(self.threshold / y_max, 1) * ph
            self.create_line(pl, ty, w - pr, ty, fill=t.mix(t.ROSE, self.bg, 0.35), dash=(5, 4))
            self.create_text(w - pr - px(4), ty - px(8), text=f"limit {self.fmt(self.threshold)}",
                             anchor="e", fill=t.mix(t.ROSE, self.bg, 0.2), font=(t.FONT, 8))

        step = pw / max(self.max_points - 1, 1)
        lines = []
        for s in self.series:
            data = list(s.data)[-self.max_points:]
            if len(data) < 2:
                continue
            n = len(data)
            pts: list[float] = []
            for i, v in enumerate(data):
                pts.append(pl + pw - (n - 1 - i) * step)
                pts.append(pt + ph - (min(max(v, 0.0), y_max) / y_max) * ph)
            lines.append((s, pts))

        if self.fill:
            for s, pts in lines:
                base = pt + ph
                self.create_polygon([pts[0], base, *pts, pts[-2], base],
                                    fill=t.mix(s.color, self.bg, 0.9 if len(lines) > 1 else 0.86), outline="")
        for s, pts in lines:
            self.create_line(*pts, fill=s.color, width=max(1.6, 2.0 * SCALE),
                             smooth=True, capstyle="round", joinstyle="round")
            x, y = pts[-2], pts[-1]
            r = 3.5 * SCALE
            halo = r * 2.2
            self.create_oval(x - halo, y - halo, x + halo, y + halo,
                             fill=t.mix(s.color, self.bg, 0.75), outline="")
            self.create_oval(x - r, y - r, x + r, y + r, fill=s.color, outline="")


class UptimeBars(tk.Canvas):
    """Last N checks as green/amber/red bars (amber = passed after a retry)."""

    def __init__(self, master, count: int = 40, bg: str = t.CARD, height: int = 26) -> None:
        super().__init__(master, bg=bg, height=px(height), highlightthickness=0, bd=0)
        self.count, self.results = count, []
        self.bind("<Configure>", lambda _e: self.redraw())

    def set_results(self, results: Sequence[dict]) -> None:
        self.results = list(results)[-self.count:]
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 20 or h < 6:
            return
        gap = px(2) if w / self.count > px(5) else 1
        bw = (w - gap * (self.count - 1)) / self.count
        offset = self.count - len(self.results)
        for i in range(self.count):
            x1 = i * (bw + gap)
            if i < offset:
                color = t.TRACK
            else:
                r = self.results[i - offset]
                color = t.ROSE if not r["ok"] else (t.AMBER if r.get("attempts", 1) > 1 else t.GREEN)
            round_rect(self, x1, 0, x1 + bw, h, min(px(3), bw / 2), fill=color, outline="")


class SlaBars(tk.Canvas):
    """Horizontal bars: 30-day availability with an SLA target marker."""

    def __init__(self, master, bg: str = t.CARD) -> None:
        super().__init__(master, bg=bg, height=px(120), highlightthickness=0, bd=0)
        self.bg, self.rows = bg, []
        self.bind("<Configure>", lambda _e: self.redraw())

    def set_rows(self, rows: Sequence[tuple[str, float | None, float]]) -> None:
        self.rows = list(rows)
        self.configure(height=px(max(60, 38 * len(self.rows) + 26)))
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        w = self.winfo_width()
        if w < 50 or not self.rows:
            return
        values = [v for _, v, _ in self.rows if v is not None] + [tg for _, _, tg in self.rows]
        lo = min(values)
        floor = max(0.0, min(95.0, math.floor(lo - (100 - lo) * 0.25)))
        label_w, value_w = px(190), px(150)
        x0, x1 = label_w, w - value_w
        span = 100 - floor
        bar_h, row_h = px(12), px(38)
        for i, (name, value, target) in enumerate(self.rows):
            yc = px(16) + i * row_h + row_h / 2 - px(6)
            self.create_text(0, yc, text=name, anchor="w", fill=t.TEXT, font=(t.FONT, 10))
            round_rect(self, x0, yc - bar_h / 2, x1, yc + bar_h / 2, bar_h / 2, fill=t.TRACK, outline="")
            met = value is None or value >= target
            color = t.GREEN if met else t.ROSE
            if value is not None:
                xv = x0 + (x1 - x0) * max(0.0, value - floor) / span
                if xv - x0 > bar_h:
                    round_rect(self, x0, yc - bar_h / 2, xv, yc + bar_h / 2, bar_h / 2, fill=color, outline="")
            xt = x0 + (x1 - x0) * (target - floor) / span
            self.create_line(xt, yc - bar_h, xt, yc + bar_h, fill=t.TEXT, width=max(1, px(2)))
            self.create_text(x1 + px(14), yc, anchor="w", fill=color if value is not None else t.DIM,
                             font=(t.FONT, 10, "bold"), text=t.fmt_pct(value, 3))
            self.create_text(x1 + px(84), yc, anchor="w", fill=t.DIM, font=(t.FONT, 9),
                             text=f"target {target:g}%")
        ya = px(16) + len(self.rows) * row_h
        for frac in (0, .25, .5, .75, 1):
            x = x0 + (x1 - x0) * frac
            self.create_text(x, ya, text=f"{floor + span * frac:g}%", fill=t.DIM, font=(t.FONT, 8))


# -----------------------------------------------------------------------------
class Panel(ctk.CTkFrame):
    def __init__(self, master, title: str, subtitle: str = "", **kw) -> None:
        super().__init__(master, fg_color=t.CARD, corner_radius=14, border_width=1,
                         border_color=t.BORDER, **kw)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 6))
        head.grid_columnconfigure(0, weight=1)
        self.title = ctk.CTkLabel(head, text=title, font=FONTS.h2, text_color=t.TEXT, anchor="w")
        self.title.grid(row=0, column=0, sticky="w")
        self.subtitle = ctk.CTkLabel(head, text=subtitle, font=FONTS.small, text_color=t.MUTED, anchor="w")
        self.subtitle.grid(row=1, column=0, sticky="w")
        self.slot = ctk.CTkFrame(head, fg_color="transparent", width=1, height=1)
        self.slot.grid(row=0, column=1, rowspan=2, sticky="e")
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

    def legend(self, items: Sequence[tuple[str, str]]) -> None:
        for child in self.slot.winfo_children():
            child.destroy()
        for label, color in items:
            box = ctk.CTkFrame(self.slot, fg_color="transparent")
            box.pack(side="left", padx=(12, 0))
            ctk.CTkFrame(box, width=10, height=10, corner_radius=5, fg_color=color).pack(side="left", padx=(0, 6))
            ctk.CTkLabel(box, text=label, font=FONTS.small, text_color=t.MUTED).pack(side="left")


class StatCard(ctk.CTkFrame):
    def __init__(self, master, title: str, accent: str, y_max: float | None = None,
                 min_y_max: float = 1.0) -> None:
        super().__init__(master, fg_color=t.CARD, corner_radius=14, border_width=1, border_color=t.BORDER)
        self.grid_columnconfigure(0, weight=1)
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 0))
        ctk.CTkFrame(top, width=8, height=8, corner_radius=4, fg_color=accent).pack(side="left")
        ctk.CTkLabel(top, text=title.upper(), font=FONTS.caption, text_color=t.MUTED).pack(side="left", padx=8)
        self.badge = ctk.CTkLabel(top, text="", font=FONTS.caption, corner_radius=8, height=20)
        self.badge.pack(side="right")
        self.value = ctk.CTkLabel(self, text="--", font=FONTS.metric, text_color=t.TEXT, anchor="w")
        self.value.grid(row=1, column=0, sticky="w", padx=18, pady=(6, 0))
        self.sub = ctk.CTkLabel(self, text="", font=FONTS.small, text_color=t.MUTED, anchor="w")
        self.sub.grid(row=2, column=0, sticky="w", padx=18)
        self.accent = accent
        self.chart = LineChart(self, [Series("", accent, [])], max_points=60, y_max=y_max,
                               min_y_max=min_y_max, height=42, show_labels=False, show_grid=False)
        self.chart.grid(row=3, column=0, sticky="ew", padx=12, pady=(8, 14))

    def update_card(self, value: str, sub: str, badge: str, data: Sequence[float],
                    badge_color: str | None = None) -> None:
        color = badge_color or self.accent
        self.value.configure(text=value)
        self.sub.configure(text=sub)
        self.badge.configure(text=f"  {badge}  " if badge else "", text_color=color,
                             fg_color=t.mix(color, t.CARD, 0.85) if badge else "transparent")
        self.chart.set_series([Series("", self.accent, list(data))])


def pill(master, text: str, color: str, bg: str = t.CARD) -> ctk.CTkLabel:
    return ctk.CTkLabel(master, text=f"  {text}  ", font=FONTS.caption, text_color=color,
                        fg_color=t.mix(color, bg, 0.85), corner_radius=8, height=22)


def set_pill(label: ctk.CTkLabel, text: str, color: str, bg: str = t.CARD) -> None:
    label.configure(text=f"  {text}  ", text_color=color, fg_color=t.mix(color, bg, 0.85))


def accent_button(master, text: str, command, color: str = t.CYAN, width: int = 120, **kw):
    return ctk.CTkButton(master, text=text, command=command, width=width, height=34, corner_radius=10,
                         fg_color=color, hover_color=t.mix(color, "#ffffff", 0.18),
                         text_color="#0b0e14", font=FONTS.body_bold, **kw)


def ghost_button(master, text: str, command, width: int = 120, **kw):
    return ctk.CTkButton(master, text=text, command=command, width=width, height=34, corner_radius=10,
                         fg_color=t.CARD, hover_color=t.CARD_HOVER, border_width=1, border_color=t.BORDER,
                         text_color=t.TEXT, font=FONTS.body, **kw)


# -----------------------------------------------------------------------------
def configure_ttk(root) -> None:
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("HC.Treeview", background=t.CARD, fieldbackground=t.CARD, foreground=t.TEXT,
                    rowheight=px(32), borderwidth=0, relief="flat", font=(t.FONT, 10))
    style.map("HC.Treeview", background=[("selected", t.mix(t.CYAN, t.CARD, 0.72))],
              foreground=[("selected", "#ffffff")])
    style.configure("HC.Treeview.Heading", background=t.SURFACE, foreground=t.MUTED, relief="flat",
                    borderwidth=0, font=(t.FONT, 9, "bold"), padding=(px(8), px(7)))
    style.map("HC.Treeview.Heading", background=[("active", t.CARD_HOVER)], foreground=[("active", t.TEXT)])
    style.layout("HC.Treeview", [("HC.Treeview.treearea", {"sticky": "nswe"})])


class DataTable(ctk.CTkFrame):
    """Dark ttk.Treeview with click-to-sort headings."""

    def __init__(self, master, height: int = 10, border: bool = True) -> None:
        super().__init__(master, fg_color=t.CARD, corner_radius=12,
                         border_width=1 if border else 0, border_color=t.BORDER)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(self, style="HC.Treeview", show="headings", selectmode="browse", height=height)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        vsb = ctk.CTkScrollbar(self, command=self.tree.yview, button_color=t.BORDER,
                               button_hover_color=t.DIM, width=12, height=40)
        vsb.grid(row=0, column=1, sticky="ns", padx=(2, 4), pady=8)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.tag_configure("odd", background=t.ROW_ALT)
        self.tree.tag_configure("even", background=t.CARD)
        for name, color in (("ok", t.GREEN), ("warn", t.AMBER), ("down", t.ROSE), ("none", t.DIM),
                            ("ALERT", t.ROSE), ("ESCALATION", t.AMBER), ("RECOVERY", t.GREEN)):
            self.tree.tag_configure(name, foreground=color)
        self.sort_col: str | None = None
        self.sort_desc = False
        self._headings: dict[str, str] = {}
        self._columns: list[str] = []
        self._items: list[tuple] = []

    def set_columns(self, columns: Sequence[tuple]) -> None:
        """(id, heading, width, anchor='w', stretch=True)"""
        self._columns = [c[0] for c in columns]
        self.tree.configure(columns=self._columns, displaycolumns=self._columns)
        for col in columns:
            cid, heading, width = col[:3]
            anchor = col[3] if len(col) > 3 else "w"
            stretch = col[4] if len(col) > 4 else True
            self._headings[cid] = heading
            self.tree.heading(cid, text=heading, anchor=anchor, command=lambda c=cid: self._sort_by(c))
            self.tree.column(cid, width=px(width), minwidth=px(50), anchor=anchor, stretch=stretch)

    def _sort_by(self, col: str) -> None:
        self.sort_desc = not self.sort_desc if self.sort_col == col else False
        self.sort_col = col
        for cid, heading in self._headings.items():
            arrow = ("  ▾" if self.sort_desc else "  ▴") if cid == col else ""
            self.tree.heading(cid, text=heading + arrow)
        self.sync(self._items)

    @staticmethod
    def _key(v):
        if v in (None, "", "–"):
            return (2, 0)
        try:
            return (0, float(str(v).replace("%", "").replace("ms", "").replace(" ", "")))
        except ValueError:
            return (1, str(v).lower())

    def sync(self, items: Sequence[tuple]) -> None:
        """items: (iid, values[, extra_tags]); keeps selection and scroll position."""
        self._items = list(items)
        rows = self._items
        if self.sort_col in self._columns:
            idx = self._columns.index(self.sort_col)
            rows = sorted(rows, key=lambda r: self._key(r[1][idx]), reverse=self.sort_desc)
        tree = self.tree
        existing = set(tree.get_children())
        wanted = []
        for i, item in enumerate(rows):
            iid, values = item[0], item[1]
            tags = ("odd" if i % 2 else "even", *(item[2] if len(item) > 2 else ()))
            if iid in existing:
                tree.item(iid, values=values, tags=tags)
            else:
                tree.insert("", "end", iid=iid, values=values, tags=tags)
            if tree.index(iid) != i:
                tree.move(iid, "", i)
            wanted.append(iid)
        stale = existing.difference(wanted)
        if stale:
            tree.delete(*stale)

    def selected(self) -> str | None:
        sel = self.tree.selection()
        return sel[0] if sel else None
