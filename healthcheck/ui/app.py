"""Main window: sidebar, page switching, toasts and background-thread control."""
from __future__ import annotations

import queue
import socket
import sys
import threading
import time
import tkinter as tk
from pathlib import Path

import customtkinter as ctk

from .. import __version__
from . import theme as t
from . import widgets as w
from .icon import ensure_icon
from .pages.endpoints import EndpointsPage
from .pages.events import EventsPage
from .pages.overview import OverviewPage
from .pages.sla import SlaPage
from .pages.tools import ConfigPage, PostmanPage
from .state import Monitor

NAV = [
    ("overview", "Overview", OverviewPage),
    ("endpoints", "Endpoints", EndpointsPage),
    ("sla", "SLA Report", SlaPage),
    ("events", "Events", EventsPage),
    ("postman", "Postman", PostmanPage),
    ("config", "Configuration", ConfigPage),
]


class App(ctk.CTk):
    def __init__(self, config_path: str | Path) -> None:
        ctk.set_appearance_mode("dark")
        super().__init__(fg_color=t.BG)
        self.title("API Health-Checker")
        try:
            self.iconbitmap(default=str(ensure_icon()))
        except (tk.TclError, OSError):
            pass
        w.SCALE = max(1.0, self.winfo_fpixels("1i") / 96.0)
        self._fit_to_screen(1340, 860)
        self.minsize(1120, 700)
        w.FONTS = t.init_fonts(self)
        w.configure_ttk(self)

        self.monitor = Monitor(Path(config_path).resolve())
        self.snapshot = None
        self._last_event_ts: float | None = None
        self._unseen = 0
        self._toasts: list[ctk.CTkFrame] = []
        self._pulse = False

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self.content = ctk.CTkFrame(self, fg_color=t.BG, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)
        self.pages = {}
        for key, _label, cls in NAV:
            page = cls(self.content, self)
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = page
        self.current = None
        self.show("overview")

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.monitor.start()
        self.after(150, self._poll)
        self.after(500, self._update_status)

    # -------------------------------------------------------------------------
    def _fit_to_screen(self, width: int, height: int) -> None:
        s = w.SCALE
        sw, sh = self.winfo_screenwidth() / s, self.winfo_screenheight() / s
        width, height = int(min(width, sw * 0.94)), int(min(height, sh * 0.88))
        x, y = int((sw - width) / 2 * s), int(max(0, (sh - height) / 2 - 20) * s)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _build_sidebar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color=t.SURFACE, corner_radius=0, width=w.px(236))
        bar.grid(row=0, column=0, sticky="nsw")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(0, weight=1)
        bar.grid_rowconfigure(2, weight=1)

        brand = ctk.CTkFrame(bar, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=18, pady=(22, 26))
        s = w.px(38)
        logo = tk.Canvas(brand, width=s, height=s, bg=t.SURFACE, highlightthickness=0)
        logo.pack(side="left")
        w.round_rect(logo, 0, 0, s, s, w.px(10), fill=t.mix(t.GREEN, t.SURFACE, 0.8), outline="")
        logo.create_line(*[c * s for p in ((.15, .55), (.35, .55), (.45, .28), (.58, .75), (.68, .45), (.85, .45))
                           for c in p], fill=t.GREEN, width=max(2, w.px(2.4)), capstyle="round", joinstyle="round")
        names = ctk.CTkFrame(brand, fg_color="transparent")
        names.pack(side="left", padx=12)
        ctk.CTkLabel(names, text="API Health", font=w.FONTS.brand, text_color=t.TEXT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(names, text=f"v{__version__}  /  REST · Postman", font=w.FONTS.small, text_color=t.DIM,
                     anchor="w").pack(anchor="w")

        nav = ctk.CTkFrame(bar, fg_color="transparent")
        nav.grid(row=1, column=0, sticky="ew", padx=12)
        ctk.CTkLabel(nav, text="NAVIGATION", font=w.FONTS.caption, text_color=t.DIM, anchor="w").pack(
            fill="x", padx=10, pady=(0, 6))
        self.nav_buttons = {}
        for key, label, _cls in NAV:
            btn = ctk.CTkButton(nav, text=label, anchor="w", height=40, corner_radius=10, font=w.FONTS.body,
                                fg_color="transparent", hover_color=t.CARD_HOVER, text_color=t.MUTED,
                                command=lambda k=key: self.show(k))
            btn.pack(fill="x", pady=2)
            self.nav_buttons[key] = btn
        self.badge = ctk.CTkLabel(self.nav_buttons["events"], text="", font=w.FONTS.caption, fg_color=t.ROSE,
                                  text_color="#0b0e14", corner_radius=9, width=24, height=20)

        ctl = ctk.CTkFrame(bar, fg_color="transparent")
        ctl.grid(row=3, column=0, sticky="ew", padx=14)
        ctl.grid_columnconfigure(0, weight=1)
        self.run_btn = w.accent_button(ctl, "Check now", self.run_now, color=t.GREEN)
        self.run_btn.grid(row=0, column=0, sticky="ew")
        self.auto_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(ctl, text="Auto monitoring", variable=self.auto_var, command=self._toggle_auto,
                      font=w.FONTS.small, text_color=t.MUTED, progress_color=t.GREEN,
                      button_color=t.TEXT, button_hover_color="#ffffff", fg_color=t.TRACK).grid(
            row=1, column=0, sticky="w", pady=(12, 0), padx=4)

        status = ctk.CTkFrame(bar, fg_color=t.CARD, corner_radius=12, border_width=1, border_color=t.BORDER)
        status.grid(row=4, column=0, sticky="ew", padx=14, pady=16)
        status.grid_columnconfigure(1, weight=1)
        self.dot = tk.Canvas(status, width=w.px(12), height=w.px(12), bg=t.CARD, highlightthickness=0)
        self.dot.grid(row=0, column=0, padx=(14, 6), pady=(12, 2))
        self.dot_id = self.dot.create_oval(w.px(1), w.px(1), w.px(11), w.px(11), fill=t.GREEN, outline="")
        self.state_label = ctk.CTkLabel(status, text="Starting…", font=w.FONTS.body_bold, text_color=t.TEXT, anchor="w")
        self.state_label.grid(row=0, column=1, sticky="w", pady=(12, 2))
        self.status_lines = ctk.CTkLabel(status, text="", font=w.FONTS.small, text_color=t.MUTED, anchor="w",
                                         justify="left")
        self.status_lines.grid(row=1, column=0, columnspan=2, sticky="w", padx=14, pady=(0, 12))

    # -------------------------------------------------------------------------
    def show(self, key: str) -> None:
        if self.current:
            self.pages[self.current].visible = False
        self.current = key
        page = self.pages[key]
        page.visible = True
        page.tkraise()
        for k, btn in self.nav_buttons.items():
            btn.configure(fg_color=t.CARD_HOVER if k == key else "transparent",
                          text_color=t.TEXT if k == key else t.MUTED)
        if key == "events":
            self._unseen = 0
            self._refresh_badge()
        page.on_show()

    def open_endpoint(self, name: str) -> None:
        self.show("endpoints")
        self.pages["endpoints"].select(name)

    def run_now(self) -> None:
        self.monitor.run_now()
        self._set_busy(True)

    def _toggle_auto(self) -> None:
        self.monitor.set_enabled(self.auto_var.get())

    def _set_busy(self, busy: bool) -> None:
        self.run_btn.configure(text="Checking…" if busy else "Check now",
                               state="disabled" if busy else "normal")

    # -- toasts ------------------------------------------------------------
    def toast(self, message: str, color: str = t.CYAN, title: str | None = None) -> None:
        f = ctk.CTkFrame(self.content, fg_color=t.CARD_HOVER, corner_radius=12, border_width=1,
                         border_color=t.mix(color, t.CARD, 0.55))
        ctk.CTkFrame(f, width=4, corner_radius=2, fg_color=color).pack(side="left", fill="y", padx=(10, 0), pady=10)
        txt = ctk.CTkFrame(f, fg_color="transparent")
        txt.pack(side="left", padx=(12, 16), pady=10)
        if title:
            ctk.CTkLabel(txt, text=title, font=w.FONTS.body_bold, text_color=t.TEXT, anchor="w",
                         wraplength=w.px(360), justify="left").pack(anchor="w")
        ctk.CTkLabel(txt, text=message, font=w.FONTS.small, text_color=t.MUTED if title else t.TEXT, anchor="w",
                     wraplength=w.px(360), justify="left").pack(anchor="w")
        f.bind("<Button-1>", lambda _e: self._dismiss(f))
        self._toasts.append(f)
        while len(self._toasts) > 4:
            self._dismiss(self._toasts[0])
        self._layout_toasts()
        self.after(7000, lambda: self._dismiss(f))

    def _dismiss(self, f) -> None:
        if f in self._toasts:
            self._toasts.remove(f)
            f.destroy()
            self._layout_toasts()

    def _layout_toasts(self) -> None:
        self.update_idletasks()
        offset = 0
        for f in reversed(self._toasts):
            f.place(relx=1.0, rely=1.0, x=-24, y=-24 - offset, anchor="se")
            f.lift()
            offset += f.winfo_reqheight() + 10

    def _refresh_badge(self) -> None:
        if self._unseen:
            self.badge.configure(text=str(self._unseen) if self._unseen < 100 else "99+")
            self.badge.place(relx=1.0, rely=0.5, x=-10, anchor="e")
        else:
            self.badge.place_forget()

    # -- loops ---------------------------------------------------------------
    def _poll(self) -> None:
        while True:
            try:
                kind, payload = self.monitor.outbox.get_nowait()
            except queue.Empty:
                break
            if kind == "snapshot":
                self._on_snapshot(payload)
            elif kind == "busy":
                self._set_busy(payload)
            elif kind == "error":
                self.toast(payload, t.ROSE, "Error")
        self.after(200, self._poll)

    def _on_snapshot(self, snap) -> None:
        self.snapshot = snap
        newest = max((e["ts"] for e in snap.events), default=0.0)
        if self._last_event_ts is not None:
            fresh = [e for e in snap.events if e["ts"] > self._last_event_ts]
            for ev in fresh[-3:]:
                label, color = t.EVENT.get(ev["kind"], (ev["kind"], t.CYAN))
                self.toast(ev["message"], color, f"{label}: {ev['name']}")
            alerts = sum(1 for e in fresh if e["kind"] != "RECOVERY")
            if alerts and self.current != "events":
                self._unseen += alerts
                self._refresh_badge()
            if alerts and sys.platform == "win32":
                try:
                    import winsound
                    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                except Exception:  # noqa: BLE001
                    pass
        self._last_event_ts = max(newest, self._last_event_ts or 0.0)
        for page in self.pages.values():
            try:
                page.on_snapshot(snap)
            except Exception as exc:  # noqa: BLE001 – keep the UI loop alive
                self.toast(f"{type(page).__name__}: {exc}", t.ROSE, "Render error")

    def _update_status(self) -> None:
        self._pulse = not self._pulse
        m, snap = self.monitor, self.snapshot
        if m.busy:
            state, color, nxt = "Checking…", t.CYAN, "running"
        elif m.enabled:
            state, color = "Monitoring", t.GREEN
            nxt = f"in {max(0, int(m.next_run - time.time()))} s"
        else:
            state, color, nxt = "Paused", t.AMBER, "manual only"
        if snap and any(e.status == "down" for e in snap.endpoints):
            color = t.ROSE
        self.state_label.configure(text=state)
        self.dot.itemconfigure(self.dot_id, fill=color if self._pulse or not m.enabled else t.mix(color, t.CARD, 0.6))
        if snap:
            self.status_lines.configure(text=(
                f"Every {m.interval} s\n"
                f"Next: {nxt}\n"
                f"Last: {t.fmt_time(snap.last_run)}\n"
                f"{len(snap.endpoints)} endpoints  /  {snap.total_checks:,} checks"))
        self.after(1000, self._update_status)

    def _on_close(self) -> None:
        self.monitor.stop()
        self.monitor.join(timeout=3)
        self.destroy()


def _start_demo_api(project_dir: Path, port: int = 8000) -> None:
    """Start the built-in demo API if the port is free (only with --demo)."""
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", port)) == 0:
            return
    sys.path.insert(0, str(project_dir))
    try:
        import mock_api
    except ImportError:
        return
    server = mock_api.serve(port)
    threading.Thread(target=server.serve_forever, daemon=True).start()


def main(config_path: str = "endpoints.yaml", demo: bool = False) -> None:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ApiHealthChecker.Desktop")
        except Exception:  # noqa: BLE001
            pass
    if demo:
        _start_demo_api(Path(config_path).resolve().parent)
    App(config_path).mainloop()
