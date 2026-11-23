"""Postman integration and YAML configuration editor."""
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from ...config import load_config
from ...postman import export_collection, import_to_yaml
from .. import theme as t
from .. import widgets as w
from .base import Page

ANSI = re.compile(r"\x1b\[[0-9;]*m")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _card(master, title: str, desc: str, accent: str) -> tuple[ctk.CTkFrame, ctk.CTkFrame]:
    card = ctk.CTkFrame(master, fg_color=t.CARD, corner_radius=14, border_width=1, border_color=t.BORDER)
    card.grid_columnconfigure(0, weight=1)
    top = ctk.CTkFrame(card, fg_color="transparent")
    top.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 0))
    ctk.CTkFrame(top, width=8, height=8, corner_radius=4, fg_color=accent).pack(side="left")
    ctk.CTkLabel(top, text=title, font=w.FONTS.h2, text_color=t.TEXT).pack(side="left", padx=10)
    ctk.CTkLabel(card, text=desc, font=w.FONTS.small, text_color=t.MUTED, anchor="w", justify="left",
                 wraplength=w.px(440)).grid(row=1, column=0, sticky="w", padx=20, pady=(6, 0))
    inner = ctk.CTkFrame(card, fg_color="transparent")
    inner.grid(row=2, column=0, sticky="ew", padx=20, pady=(14, 18))
    inner.grid_columnconfigure(0, weight=1)
    return card, inner


class PostmanPage(Page):
    title = "Postman"
    subtitle = "Export / import collections and run them with Newman"

    def __init__(self, master, app) -> None:
        super().__init__(master, app)
        body = self.body
        body.grid_columnconfigure((0, 1), weight=1, uniform="pm")
        body.grid_rowconfigure(1, weight=1)
        self.coll_path: Path | None = None
        self.env_path: Path | None = None
        self.imported: Path | None = None
        self.proc_q: queue.Queue = queue.Queue()

        card, inner = _card(body, "Export to Postman",
                            "Every endpoint in endpoints.yaml becomes a request with built-in pm.test checks: "
                            "status code, response time, body content and JSON schema. ${BASE_URL} becomes {{BASE_URL}}.",
                            t.AMBER)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.exp_info = ctk.CTkLabel(inner, text="", font=w.FONTS.mono_small, text_color=t.DIM, anchor="w")
        self.exp_info.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        btns = ctk.CTkFrame(inner, fg_color="transparent")
        btns.grid(row=1, column=0, sticky="w")
        w.accent_button(btns, "Export collection", self._export, color=t.AMBER, width=180).pack(side="left")
        w.ghost_button(btns, "Open folder", self._open_folder, width=140).pack(side="left", padx=8)

        card, inner = _card(body, "Import from Postman",
                            "Turns an existing Postman v2.1 collection (folders, environment) into YAML config. "
                            "pm.test status and response-time checks become expectations.", t.VIOLET)
        card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self.coll_lbl = ctk.CTkLabel(inner, text="Collection: –", font=w.FONTS.small, text_color=t.MUTED, anchor="w")
        self.coll_lbl.grid(row=0, column=0, sticky="w")
        self.env_lbl = ctk.CTkLabel(inner, text="Environment: – (optional)", font=w.FONTS.small,
                                    text_color=t.MUTED, anchor="w")
        self.env_lbl.grid(row=1, column=0, sticky="w", pady=(0, 10))
        btns = ctk.CTkFrame(inner, fg_color="transparent")
        btns.grid(row=2, column=0, sticky="w")
        w.ghost_button(btns, "Collection…", self._pick_coll, width=110).pack(side="left")
        w.ghost_button(btns, "Environment…", self._pick_env, width=120).pack(side="left", padx=8)
        self.imp_btn = w.accent_button(btns, "Import", self._import, color=t.VIOLET, width=110)
        self.imp_btn.pack(side="left")
        self.open_imp = w.ghost_button(inner, "Open in editor →", self._open_imported, width=220)

        nm = w.Panel(body, "Newman run", "")
        nm.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(16, 0))
        nm.body.grid_columnconfigure(0, weight=1)
        nm.body.grid_rowconfigure(0, weight=1)
        self.newman_panel = nm
        self.run_btn = w.accent_button(nm.slot, "Run", self._run_newman, color=t.GREEN, width=110)
        self.run_btn.pack(side="right")
        self.out = ctk.CTkTextbox(nm.body, font=w.FONTS.mono_small, fg_color=t.SURFACE, text_color=t.MUTED,
                                  border_width=1, border_color=t.BORDER, corner_radius=10, wrap="none")
        self.out.grid(row=0, column=0, sticky="nsew", padx=6, pady=(0, 6))
        self.out.tag_config("ok", foreground=t.GREEN)
        self.out.tag_config("bad", foreground=t.ROSE)
        self._newman_cmd = self._find_newman()
        self._refresh_newman_state()

    # -- export ----------------------------------------------------------------
    def _export_path(self) -> Path:
        return self.app.monitor.config_path.parent / "postman" / "health-check.postman_collection.json"

    def on_show(self) -> None:
        p = self._export_path()
        self.exp_info.configure(text=f"{p}\n" + (f"last export: {t.fmt_time(p.stat().st_mtime, True)}"
                                                 if p.exists() else "not exported yet"))

    def _export(self) -> None:
        try:
            cfg = load_config(self.app.monitor.config_path)
            p = self._export_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(export_collection(cfg), ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            self.app.toast(f"Export failed: {exc}", t.ROSE)
            return
        self.on_show()
        self.app.toast(f"Exported {len(cfg.endpoints)} requests to the Postman collection.", t.GREEN)

    def _open_folder(self) -> None:
        folder = self._export_path().parent
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)  # type: ignore[attr-defined]

    # -- import ----------------------------------------------------------------
    def _pick_coll(self) -> None:
        p = filedialog.askopenfilename(title="Postman collection", filetypes=[("Postman collection", "*.json")])
        if p:
            self.coll_path = Path(p)
            self.coll_lbl.configure(text=f"Collection: {self.coll_path.name}", text_color=t.TEXT)

    def _pick_env(self) -> None:
        p = filedialog.askopenfilename(title="Postman environment", filetypes=[("Environment", "*.json")])
        if p:
            self.env_path = Path(p)
            self.env_lbl.configure(text=f"Environment: {self.env_path.name}", text_color=t.TEXT)

    def _import(self) -> None:
        if not self.coll_path:
            self.app.toast("Pick a collection first.", t.AMBER)
            return
        out = self.app.monitor.config_path.with_name("endpoints.imported.yaml")
        try:
            n = import_to_yaml(self.coll_path, out, self.env_path)
        except Exception as exc:  # noqa: BLE001
            self.app.toast(f"Import failed: {exc}", t.ROSE)
            return
        self.imported = out
        self.open_imp.grid(row=3, column=0, sticky="w", pady=(10, 0))
        self.app.toast(f"Imported {n} endpoint(s) → {out.name}", t.GREEN)

    def _open_imported(self) -> None:
        if self.imported and self.imported.exists():
            self.app.pages["config"].load_text(self.imported.read_text(encoding="utf-8"),
                                               note=f"Imported content ({self.imported.name}) – saving will "
                                                    f"replace the active configuration.")
            self.app.show("config")

    # -- newman ----------------------------------------------------------------
    @staticmethod
    def _find_newman() -> list[str] | None:
        if shutil.which("newman"):
            return [shutil.which("newman")]
        if shutil.which("npx"):
            return [shutil.which("npx"), "--yes", "newman"]
        return None

    def _refresh_newman_state(self) -> None:
        if self._newman_cmd:
            self.newman_panel.subtitle.configure(text=f"Newman: {self._newman_cmd[0]}")
            self.run_btn.configure(state="normal")
        else:
            self.newman_panel.subtitle.configure(text="Newman is not installed – after Node.js: npm install -g newman",
                                                 text_color=t.AMBER)
            self.run_btn.configure(state="disabled")
            self.out.insert("end", "Newman is Postman's command-line runner. To install:\n"
                                   "  1. Node.js: https://nodejs.org\n  2. npm install -g newman\n\n"
                                   "The 'Newman' job in the Azure DevOps pipeline does this automatically.\n")
            self.out.configure(state="disabled")

    def _run_newman(self) -> None:
        p = self._export_path()
        if not p.exists():
            self._export()
        self.run_btn.configure(state="disabled", text="Running…")
        self.out.configure(state="normal")
        self.out.delete("1.0", "end")
        cmd = self._newman_cmd + ["run", str(p), "--no-color"]

        def work():
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                        encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
                for line in proc.stdout:
                    self.proc_q.put(ANSI.sub("", line))
                self.proc_q.put(("done", proc.wait()))
            except Exception as exc:  # noqa: BLE001
                self.proc_q.put(("done", f"{exc}"))

        threading.Thread(target=work, daemon=True).start()
        self.after(100, self._drain)

    def _drain(self) -> None:
        while True:
            try:
                item = self.proc_q.get_nowait()
            except queue.Empty:
                self.after(100, self._drain)
                return
            if isinstance(item, tuple):
                code = item[1]
                ok = code == 0
                self.out.insert("end", f"\n{'✓ All tests passed' if ok else f'✗ Exit code: {code}'}\n",
                                "ok" if ok else "bad")
                self.out.configure(state="disabled")
                self.run_btn.configure(state="normal", text="Run")
                return
            tag = "bad" if re.search(r"✗|\bfail|AssertionError", item, re.I) else ("ok" if "✓" in item or "√" in item else None)
            self.out.insert("end", item, tag)
            self.out.see("end")


# =============================================================================
class ConfigPage(Page):
    title = "Configuration"
    subtitle = "endpoints.yaml – endpoints, expectations, schedule and alerting"

    KEY = re.compile(r"^(\s*-?\s*)([A-Za-z_][\w\-]*)(:)", re.M)
    COMMENT = re.compile(r"(^|\s)#.*$", re.M)
    VAR = re.compile(r"\$\{[^}]*\}")
    NUM = re.compile(r":\s*(\d+(?:\.\d+)?)\s*$", re.M)

    def __init__(self, master, app) -> None:
        super().__init__(master, app)
        body = self.body
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)
        w.accent_button(self.actions, "Save & reload", self._save, width=180).pack(side="right")
        w.ghost_button(self.actions, "Revert", self.load_file, width=120).pack(side="right", padx=8)

        self.editor = ctk.CTkTextbox(body, font=w.FONTS.mono, fg_color=t.CARD, text_color=t.TEXT,
                                     border_width=1, border_color=t.BORDER, corner_radius=14, wrap="none",
                                     undo=True)
        self.editor.grid(row=0, column=0, sticky="nsew")
        for tag, color in (("key", t.CYAN), ("comment", t.DIM), ("var", t.VIOLET), ("num", t.AMBER)):
            self.editor.tag_config(tag, foreground=color)
        self.editor.bind("<KeyRelease>", lambda _e: self._schedule_highlight())
        self.editor.bind("<Control-s>", lambda _e: (self._save(), "break")[1])
        self.status = ctk.CTkLabel(body, text="", font=w.FONTS.small, text_color=t.MUTED, anchor="w")
        self.status.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self._hl_job = None
        self._loaded = False

    def on_show(self) -> None:
        if not self._loaded:
            self.load_file()

    def load_file(self) -> None:
        path = self.app.monitor.config_path
        self.load_text(path.read_text(encoding="utf-8"), note=f"{path}")

    def load_text(self, text: str, note: str = "") -> None:
        self._loaded = True
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", text)
        self.status.configure(text=note, text_color=t.MUTED)
        self._highlight()

    def _schedule_highlight(self) -> None:
        if self._hl_job:
            self.after_cancel(self._hl_job)
        self._hl_job = self.after(250, self._highlight)

    def _highlight(self) -> None:
        text = self.editor.get("1.0", "end-1c")
        for tag in ("key", "comment", "var", "num"):
            self.editor.tag_remove(tag, "1.0", "end")

        def add(tag, a, b):
            self.editor.tag_add(tag, f"1.0+{a}c", f"1.0+{b}c")
        for m in self.KEY.finditer(text):
            add("key", m.start(2), m.end(2))
        for m in self.NUM.finditer(text):
            add("num", m.start(1), m.end(1))
        for m in self.VAR.finditer(text):
            add("var", m.start(), m.end())
        for m in self.COMMENT.finditer(text):
            add("comment", m.start() + len(m.group(1)), m.end())

    def _save(self) -> None:
        path = self.app.monitor.config_path
        text = self.editor.get("1.0", "end-1c")
        probe = path.with_name(f".validate-{int(time.time())}.yaml")
        try:
            probe.write_text(text, encoding="utf-8")
            cfg = load_config(probe)
        except Exception as exc:  # noqa: BLE001
            self.status.configure(text=f"✗ Invalid configuration, not saved: {exc}", text_color=t.ROSE)
            return
        finally:
            probe.unlink(missing_ok=True)
        backup = path.with_suffix(".yaml.bak")
        if path.exists():
            shutil.copyfile(path, backup)
        path.write_text(text, encoding="utf-8")
        self.app.monitor.reload()
        self.status.configure(text=f"✓ Saved and reloaded – {len(cfg.endpoints)} endpoints "
                                   f"(previous version: {backup.name})", text_color=t.GREEN)
