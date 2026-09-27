"""Assisted Typing Tool (ATT) - desktop typing and clicking automation.

Requires: pyautogui (install with: pip install pyautogui)

All settings persist in ~/.auto_typer_settings.json. Move the mouse to a
screen corner during a run to trigger pyautogui's failsafe (when enabled).
"""

import ctypes
import json
import os
import queue
import random
import re
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

try:
    import pyautogui
except ImportError:
    pyautogui = None


LIGHT = {
    "bg": "#f2f2f2", "fg": "#111111", "text_bg": "#ffffff",
    "text_fg": "#111111", "status_fg": "#555555", "hint_fg": "#777777",
    "accent": "#d7e8ff",
}
DARK = {
    "bg": "#1e1e1e", "fg": "#e8e8e8", "text_bg": "#2b2b2b",
    "text_fg": "#e8e8e8", "status_fg": "#aaaaaa", "hint_fg": "#888888",
    "accent": "#3a506b",
}

SETTINGS_PATH = os.path.join(os.path.expanduser("~"), ".auto_typer_settings.json")
TYPO_CHARS = "abcdefghijklmnopqrstuvwxyz"
DEFAULT_SETTINGS = {
    "dark_mode": False,
    "last_mode": "typer",
    "start_delay": 5.0,
    "char_delay": 0.05,
    "human_mode": True,
    "loop_mode": False,
    "fix_indent": True,
    "typo_mode": False,
    "typo_chance": 6.0,
    "click_interval": 100.0,
    "click_interval_unit": "ms",
    "click_type": "Left",
    "click_location_mode": "Current cursor position",
    "click_x": 0,
    "click_y": 0,
    "click_count_mode": "Fixed number",
    "click_count": 100,
    "click_jitter": 0.0,
    "click_failsafe": True,
    "popout_enabled": True,
    "popout_pinned": False,
    "popout_x": None,
    "popout_y": None,
}


def load_settings():
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        data = {}
    merged = dict(DEFAULT_SETTINGS)
    merged.update(data if isinstance(data, dict) else {})
    return merged


def save_settings(data):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
    except Exception:
        pass


def format_duration(total_seconds):
    if total_seconds < 60:
        return f"{total_seconds:.1f}s"
    mins = int(total_seconds // 60)
    secs = total_seconds % 60
    return f"{mins}m {secs:.0f}s"


class SettingsWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("ATT - Settings")
        self.resizable(False, False)
        self.transient(app.root)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        typer = ttk.Frame(notebook, padding=8)
        clicker = ttk.Frame(notebook, padding=8)
        general = ttk.Frame(notebook, padding=8)
        notebook.add(typer, text="Auto Typer")
        notebook.add(clicker, text="Auto Clicker")
        notebook.add(general, text="General")

        self._label_spin(typer, 0, "Start delay (sec):", app.start_delay, 0, 60, 0.5)
        self._label_spin(typer, 1, "Base delay/char (sec):", app.char_delay, 0, 1, 0.01)
        ttk.Checkbutton(typer, text="Human-like variation (random pauses)",
                        variable=app.human_mode).grid(row=2, column=0, columnspan=2, sticky="w", pady=6)
        ttk.Checkbutton(typer, text="Repeat / loop", variable=app.loop_mode).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=6)
        ttk.Checkbutton(typer, text="Fix editor auto-indent (recommended for VS Code / IDEs)",
                        variable=app.fix_indent).grid(row=4, column=0, columnspan=2, sticky="w", pady=6)
        ttk.Checkbutton(typer, text="Simulate typos, then backspace + correct them",
                        variable=app.typo_mode).grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self._label_spin(typer, 6, "Typo chance (%):", app.typo_chance, 0, 100, 1)

        ttk.Label(clicker, text="The everyday click controls also appear on the main page.",
                  foreground=app.colors["status_fg"]).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self._label_spin(clicker, 1, "Random interval jitter (%):", app.click_jitter, 0, 100, 1)
        ttk.Checkbutton(clicker, text="Enable mouse-corner failsafe",
                        variable=app.click_failsafe).grid(row=2, column=0, columnspan=2, sticky="w", pady=6)

        ttk.Checkbutton(general, text="Enable pop-out control window while running",
                        variable=app.popout_enabled).grid(row=0, column=0, sticky="w", pady=6)
        ttk.Checkbutton(general, text="Keep pop-out open after a run finishes",
                        variable=app.popout_pinned).grid(row=1, column=0, sticky="w", pady=6)

        footer = ttk.Frame(self)
        footer.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(footer, text="Close", command=self._on_close).pack(side="right")
        self.apply_theme()

    @staticmethod
    def _label_spin(parent, row, label, variable, minimum, maximum, increment):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 14), pady=6)
        ttk.Spinbox(parent, from_=minimum, to=maximum, increment=increment,
                    textvariable=variable, width=9).grid(row=row, column=1, sticky="w", pady=6)

    def apply_theme(self):
        self.configure(bg=self.app.colors["bg"])

    def _on_close(self):
        self.app.save_all_settings()
        self.destroy()
        self.app.settings_window = None


class PopoutWindow(tk.Toplevel):
    WIDTH = 220
    HEIGHT = 96

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self._drag_origin = None

        self.body = tk.Frame(self, highlightthickness=1)
        self.body.pack(fill="both", expand=True)
        self.status_label = tk.Label(self.body, textvariable=app.popout_status,
                                     anchor="w", font=("Segoe UI", 10, "bold"))
        self.status_label.pack(fill="x", padx=10, pady=(8, 1))
        self.progress_label = tk.Label(self.body, textvariable=app.popout_progress,
                                       anchor="w", font=("Segoe UI", 8))
        self.progress_label.pack(fill="x", padx=10)
        controls = ttk.Frame(self.body)
        controls.pack(fill="x", padx=8, pady=(5, 7))
        self.pause_btn = ttk.Button(controls, text="Pause", width=9, command=app.toggle_pause)
        self.pause_btn.pack(side="left")
        self.stop_btn = ttk.Button(controls, text="Stop", width=8, command=app.stop_active_run)
        self.stop_btn.pack(side="left", padx=(6, 0))

        for widget in (self, self.body, self.status_label, self.progress_label):
            widget.bind("<ButtonPress-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)
            widget.bind("<ButtonRelease-1>", self._drag_end)

        self.update_idletasks()
        self._position()
        self.apply_theme()
        self._make_no_activate()

    def _position(self):
        x = self.app._safe_int(self.app.popout_x, None)
        y = self.app._safe_int(self.app.popout_y, None)
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        if x is None or y is None:
            x = screen_w - self.WIDTH - 24
            y = screen_h - self.HEIGHT - 64
        x = max(0, min(x, screen_w - self.WIDTH))
        y = max(0, min(y, screen_h - self.HEIGHT))
        self.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")

    def _make_no_activate(self):
        if os.name != "nt":
            return
        try:
            hwnd = self.winfo_id()
            get_style = ctypes.windll.user32.GetWindowLongW
            set_style = ctypes.windll.user32.SetWindowLongW
            exstyle = get_style(hwnd, -20)
            set_style(hwnd, -20, exstyle | 0x08000000 | 0x00000080)  # NOACTIVATE | TOOLWINDOW
        except Exception:
            pass

    def _drag_start(self, event):
        self._drag_origin = (event.x_root, event.y_root, self.winfo_x(), self.winfo_y())

    def _drag_move(self, event):
        if not self._drag_origin:
            return
        sx, sy, wx, wy = self._drag_origin
        self.geometry(f"+{wx + event.x_root - sx}+{wy + event.y_root - sy}")

    def _drag_end(self, _event):
        self._drag_origin = None
        self.app.popout_x.set(self.winfo_x())
        self.app.popout_y.set(self.winfo_y())
        self.app.save_all_settings()

    def set_running(self, running, paused=False):
        self.pause_btn.configure(state="normal" if running else "disabled",
                                 text="Resume" if paused else "Pause")
        self.stop_btn.configure(state="normal" if running else "disabled")

    def apply_theme(self):
        c = self.app.colors
        self.configure(bg=c["bg"])
        self.body.configure(bg=c["bg"], highlightbackground=c["status_fg"])
        self.status_label.configure(bg=c["bg"], fg=c["fg"])
        self.progress_label.configure(bg=c["bg"], fg=c["status_fg"])


class AutoTyperApp:
    def __init__(self, root):
        self.root = root
        root.title("Assisted Typing Tool (ATT)")
        root.geometry("700x700")
        root.minsize(700, 700)

        self.worker_thread = None
        self.active_mode = None
        self.stop_flag = threading.Event()
        self.pause_flag = threading.Event()
        self.ui_queue = queue.Queue()
        self.settings_window = None
        self.popout = None
        self.target_hwnd = None
        self._pick_polling = False
        settings = load_settings()

        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass

        self.dark_mode = tk.BooleanVar(value=settings["dark_mode"])
        self.mode = tk.StringVar(value=settings.get("last_mode", "typer"))
        if self.mode.get() not in ("typer", "clicker"):
            self.mode.set("typer")
        self.start_delay = tk.DoubleVar(value=settings["start_delay"])
        self.char_delay = tk.DoubleVar(value=settings["char_delay"])
        self.human_mode = tk.BooleanVar(value=settings["human_mode"])
        self.loop_mode = tk.BooleanVar(value=settings["loop_mode"])
        self.fix_indent = tk.BooleanVar(value=settings["fix_indent"])
        self.typo_mode = tk.BooleanVar(value=settings["typo_mode"])
        self.typo_chance = tk.DoubleVar(value=settings["typo_chance"])
        self.click_interval = tk.DoubleVar(value=settings["click_interval"])
        self.click_interval_unit = tk.StringVar(value=settings["click_interval_unit"])
        self.click_type = tk.StringVar(value=settings["click_type"])
        self.click_location_mode = tk.StringVar(value=settings["click_location_mode"])
        self.click_x = tk.IntVar(value=settings["click_x"])
        self.click_y = tk.IntVar(value=settings["click_y"])
        self.click_count_mode = tk.StringVar(value=settings["click_count_mode"])
        self.click_count = tk.IntVar(value=settings["click_count"])
        self.click_jitter = tk.DoubleVar(value=settings["click_jitter"])
        self.click_failsafe = tk.BooleanVar(value=settings["click_failsafe"])
        self.popout_enabled = tk.BooleanVar(value=settings["popout_enabled"])
        self.popout_pinned = tk.BooleanVar(value=settings["popout_pinned"])
        self.popout_x = tk.StringVar(value="" if settings["popout_x"] is None else settings["popout_x"])
        self.popout_y = tk.StringVar(value="" if settings["popout_y"] is None else settings["popout_y"])

        self.typer_status = tk.StringVar(value="Ready.")
        self.typer_estimate = tk.StringVar(value="Estimated typing time: -")
        self.clicker_status = tk.StringVar(value="Ready.")
        self.clicker_estimate = tk.StringVar(value="Estimated run time: -")
        self.popout_status = tk.StringVar(value="Ready.")
        self.popout_progress = tk.StringVar(value="0%")

        self._build_top_bar()
        self.content_host = ttk.Frame(root)
        self.content_host.pack(fill="both", expand=True)
        self._build_typer_page()
        self._build_clicker_page()
        self.hint_label = ttk.Label(root, text="Tip: flick the mouse to a screen corner anytime to abort.")
        self.hint_label.pack(anchor="w", padx=10, pady=(0, 8))

        self.apply_theme()
        self.switch_mode(self.mode.get(), save=False)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.text_box.bind("<<Modified>>", self._on_text_modified)

        watched = (
            self.start_delay, self.char_delay, self.human_mode, self.loop_mode,
            self.fix_indent, self.typo_mode, self.typo_chance, self.click_interval,
            self.click_interval_unit, self.click_type, self.click_location_mode,
            self.click_x, self.click_y, self.click_count_mode, self.click_count,
            self.click_jitter, self.click_failsafe, self.popout_enabled,
            self.popout_pinned,
        )
        for var in watched:
            var.trace_add("write", self._setting_changed)
        self.update_estimates()
        self.root.after(40, self._drain_ui_queue)

        if pyautogui is None:
            messagebox.showwarning("Missing dependency", "pyautogui isn't installed.\n\nRun:\n    pip install pyautogui\n\nthen restart this app.")

    @property
    def colors(self):
        return DARK if self.dark_mode.get() else LIGHT

    def _build_top_bar(self):
        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=10, pady=(10, 0))
        self.mode_label = ttk.Label(top, text="Text to type:")
        self.mode_label.pack(side="left")
        self.typer_mode_btn = ttk.Button(top, text="Auto Typer", command=lambda: self.switch_mode("typer"))
        self.typer_mode_btn.pack(side="left", padx=(12, 4))
        self.clicker_mode_btn = ttk.Button(top, text="Auto Clicker", command=lambda: self.switch_mode("clicker"))
        self.clicker_mode_btn.pack(side="left")
        self.dark_check = ttk.Checkbutton(top, text="Dark mode", variable=self.dark_mode,
                                          command=self.on_dark_mode_toggle)
        self.dark_check.pack(side="right")
        self.settings_btn = ttk.Button(top, text="Settings", command=self.open_settings)
        self.settings_btn.pack(side="right", padx=(0, 10))

    def _build_typer_page(self):
        self.typer_page = ttk.Frame(self.content_host)
        text_frame = ttk.Frame(self.typer_page)
        text_frame.pack(fill="both", expand=True, padx=10, pady=(4, 0))
        text_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)
        self.text_box = tk.Text(text_frame, wrap="none", undo=True)
        self.text_box.grid(row=0, column=0, sticky="nsew")
        ys = ttk.Scrollbar(text_frame, orient="vertical", command=self.text_box.yview)
        xs = ttk.Scrollbar(text_frame, orient="horizontal", command=self.text_box.xview)
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        self.text_box.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.typer_status_label = ttk.Label(self.typer_page, textvariable=self.typer_status)
        self.typer_status_label.pack(anchor="w", padx=10, pady=(8, 0))
        ttk.Label(self.typer_page, textvariable=self.typer_estimate).pack(anchor="w", padx=10)
        row = ttk.Frame(self.typer_page)
        row.pack(fill="x", padx=10, pady=6)
        self.typer_start_btn = ttk.Button(row, text="Start", command=self.start_typing)
        self.typer_start_btn.pack(side="left", padx=(0, 8))
        self.typer_stop_btn = ttk.Button(row, text="Stop", command=self.stop_active_run, state="disabled")
        self.typer_stop_btn.pack(side="left", padx=(0, 8))
        self.clear_btn = ttk.Button(row, text="Clear", command=self.clear_text)
        self.clear_btn.pack(side="left")

    def _build_clicker_page(self):
        self.clicker_page = ttk.Frame(self.content_host)
        form = ttk.Frame(self.clicker_page, padding=(10, 18))
        form.pack(fill="both", expand=True)
        form.columnconfigure(1, weight=1)
        pad = {"padx": 8, "pady": 9}

        ttk.Label(form, text="Click interval:").grid(row=0, column=0, sticky="w", **pad)
        interval_row = ttk.Frame(form)
        interval_row.grid(row=0, column=1, sticky="w", **pad)
        ttk.Spinbox(interval_row, from_=1, to=3600, increment=1, textvariable=self.click_interval,
                    width=10).pack(side="left")
        ttk.Combobox(interval_row, textvariable=self.click_interval_unit, values=("ms", "sec"),
                     state="readonly", width=6).pack(side="left", padx=(6, 0))

        ttk.Label(form, text="Click type:").grid(row=1, column=0, sticky="w", **pad)
        ttk.Combobox(form, textvariable=self.click_type,
                     values=("Left", "Right", "Middle", "Double-click"),
                     state="readonly", width=22).grid(row=1, column=1, sticky="w", **pad)

        ttk.Label(form, text="Target location:").grid(row=2, column=0, sticky="w", **pad)
        location_row = ttk.Frame(form)
        location_row.grid(row=2, column=1, sticky="w", **pad)
        self.location_combo = ttk.Combobox(location_row, textvariable=self.click_location_mode,
                                            values=("Current cursor position", "Fixed X / Y"),
                                            state="readonly", width=24)
        self.location_combo.pack(side="left")
        ttk.Button(location_row, text="Pick location", command=self.pick_location).pack(side="left", padx=(8, 0))

        ttk.Label(form, text="Fixed coordinates:").grid(row=3, column=0, sticky="w", **pad)
        xy = ttk.Frame(form)
        xy.grid(row=3, column=1, sticky="w", **pad)
        ttk.Label(xy, text="X").pack(side="left")
        ttk.Spinbox(xy, from_=-9999, to=99999, textvariable=self.click_x, width=8).pack(side="left", padx=(4, 12))
        ttk.Label(xy, text="Y").pack(side="left")
        ttk.Spinbox(xy, from_=-9999, to=99999, textvariable=self.click_y, width=8).pack(side="left", padx=(4, 0))

        ttk.Label(form, text="Click count:").grid(row=4, column=0, sticky="w", **pad)
        count_row = ttk.Frame(form)
        count_row.grid(row=4, column=1, sticky="w", **pad)
        ttk.Combobox(count_row, textvariable=self.click_count_mode,
                     values=("Fixed number", "Infinite (until Stop)"), state="readonly",
                     width=22).pack(side="left")
        ttk.Spinbox(count_row, from_=1, to=999999999, textvariable=self.click_count,
                    width=10).pack(side="left", padx=(8, 0))

        self.clicker_status_label = ttk.Label(self.clicker_page, textvariable=self.clicker_status)
        self.clicker_status_label.pack(anchor="w", padx=10, pady=(8, 0))
        ttk.Label(self.clicker_page, textvariable=self.clicker_estimate).pack(anchor="w", padx=10)
        row = ttk.Frame(self.clicker_page)
        row.pack(fill="x", padx=10, pady=6)
        self.clicker_start_btn = ttk.Button(row, text="Start", command=self.start_clicking)
        self.clicker_start_btn.pack(side="left", padx=(0, 8))
        self.clicker_stop_btn = ttk.Button(row, text="Stop", command=self.stop_active_run, state="disabled")
        self.clicker_stop_btn.pack(side="left")

    def _setting_changed(self, *_args):
        self.update_estimates()
        self.save_all_settings()

    @staticmethod
    def _safe_get(variable, fallback):
        try:
            return variable.get()
        except (tk.TclError, ValueError):
            return fallback

    @staticmethod
    def _safe_int(variable, fallback=0):
        try:
            value = variable.get() if hasattr(variable, "get") else variable
            if value == "":
                return fallback
            return int(float(value))
        except (tk.TclError, TypeError, ValueError):
            return fallback

    def save_all_settings(self):
        save_settings({
            "dark_mode": bool(self._safe_get(self.dark_mode, False)),
            "last_mode": self.mode.get(),
            "start_delay": float(self._safe_get(self.start_delay, 5.0)),
            "char_delay": float(self._safe_get(self.char_delay, 0.05)),
            "human_mode": bool(self._safe_get(self.human_mode, True)),
            "loop_mode": bool(self._safe_get(self.loop_mode, False)),
            "fix_indent": bool(self._safe_get(self.fix_indent, True)),
            "typo_mode": bool(self._safe_get(self.typo_mode, False)),
            "typo_chance": float(self._safe_get(self.typo_chance, 6.0)),
            "click_interval": float(self._safe_get(self.click_interval, 100.0)),
            "click_interval_unit": self.click_interval_unit.get(),
            "click_type": self.click_type.get(),
            "click_location_mode": self.click_location_mode.get(),
            "click_x": self._safe_int(self.click_x),
            "click_y": self._safe_int(self.click_y),
            "click_count_mode": self.click_count_mode.get(),
            "click_count": self._safe_int(self.click_count, 100),
            "click_jitter": float(self._safe_get(self.click_jitter, 0.0)),
            "click_failsafe": bool(self._safe_get(self.click_failsafe, True)),
            "popout_enabled": bool(self._safe_get(self.popout_enabled, True)),
            "popout_pinned": bool(self._safe_get(self.popout_pinned, False)),
            "popout_x": self._safe_int(self.popout_x, None),
            "popout_y": self._safe_int(self.popout_y, None),
        })

    def switch_mode(self, mode, save=True):
        if self.active_mode is not None or mode not in ("typer", "clicker"):
            return
        self.mode.set(mode)
        self.typer_page.pack_forget()
        self.clicker_page.pack_forget()
        if mode == "typer":
            self.mode_label.configure(text="Text to type:")
            self.typer_page.pack(fill="both", expand=True)
        else:
            self.mode_label.configure(text="Auto Clicker:")
            self.clicker_page.pack(fill="both", expand=True)
        self._refresh_mode_styles()
        if save:
            self.save_all_settings()

    def _refresh_mode_styles(self):
        selected = self.mode.get()
        self.typer_mode_btn.configure(style="Selected.TButton" if selected == "typer" else "TButton")
        self.clicker_mode_btn.configure(style="Selected.TButton" if selected == "clicker" else "TButton")

    def _set_mode_switch_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        self.typer_mode_btn.configure(state=state)
        self.clicker_mode_btn.configure(state=state)

    def open_settings(self):
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return
        self.settings_window = SettingsWindow(self)

    def clear_text(self):
        if self.active_mode is not None:
            return
        self.text_box.delete("1.0", "end")
        self.text_box.edit_modified(False)
        self.update_estimates()

    def _on_text_modified(self, _event=None):
        self.text_box.edit_modified(False)
        self.update_estimates()

    def update_estimates(self):
        if not hasattr(self, "text_box"):
            return
        text = self.text_box.get("1.0", "end-1c")
        if not text:
            self.typer_estimate.set("Estimated typing time: -")
        else:
            base = max(float(self._safe_get(self.char_delay, 0.05)), 0.0)
            average = base + (0.03 * 0.275 if self._safe_get(self.human_mode, True) else 0.0)
            total = len(text.replace("\n", "")) * average
            total += text.count("\n") * (base + (0.02 if self._safe_get(self.fix_indent, True) else 0))
            if self._safe_get(self.typo_mode, False):
                eligible = sum(1 for word in re.findall(r"\S+", text) if len(word) >= 3)
                expected = eligible * max(float(self._safe_get(self.typo_chance, 0)), 0) / 100
                total += expected * (2 * average + 0.275)
            self.typer_estimate.set(f"Estimated typing time: ~{format_duration(total)}")

        if self.click_count_mode.get().startswith("Infinite"):
            self.clicker_estimate.set("Estimated run time: until stopped")
        else:
            interval = max(float(self._safe_get(self.click_interval, 100)), 0)
            if self.click_interval_unit.get() == "ms":
                interval /= 1000
            count = max(self._safe_int(self.click_count, 1), 1)
            self.clicker_estimate.set(f"Estimated run time: ~{format_duration(interval * count)}")

    def on_dark_mode_toggle(self):
        self.apply_theme()
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.apply_theme()
        if self.popout is not None and self.popout.winfo_exists():
            self.popout.apply_theme()
        self.save_all_settings()

    def apply_theme(self):
        c = self.colors
        self.root.configure(bg=c["bg"])
        self.style.configure("TFrame", background=c["bg"])
        self.style.configure("TLabel", background=c["bg"], foreground=c["fg"])
        self.style.configure("TCheckbutton", background=c["bg"], foreground=c["fg"])
        self.style.configure("TButton", background=c["bg"], foreground=c["fg"])
        self.style.configure("Selected.TButton", background=c["accent"], foreground=c["fg"])
        self.style.map("Selected.TButton", background=[("active", c["accent"]), ("!disabled", c["accent"])])
        self.style.configure("TSpinbox", fieldbackground=c["text_bg"], foreground=c["text_fg"])
        self.style.configure("TCombobox", fieldbackground=c["text_bg"], foreground=c["text_fg"])
        self.style.configure("TNotebook", background=c["bg"])
        self.style.configure("TNotebook.Tab", background=c["bg"], foreground=c["fg"])
        self.text_box.configure(bg=c["text_bg"], fg=c["text_fg"], insertbackground=c["fg"])
        self.typer_status_label.configure(foreground=c["status_fg"])
        self.clicker_status_label.configure(foreground=c["status_fg"])
        self.hint_label.configure(foreground=c["hint_fg"])
        self._refresh_mode_styles()

    def _begin_run(self, mode, worker, args):
        self.active_mode = mode
        self.stop_flag.clear()
        self.pause_flag.clear()
        self.target_hwnd = None
        self._set_mode_switch_enabled(False)
        self.typer_start_btn.configure(state="disabled")
        self.clicker_start_btn.configure(state="disabled")
        self.clear_btn.configure(state="disabled")
        (self.typer_stop_btn if mode == "typer" else self.clicker_stop_btn).configure(state="normal")
        status = "Preparing to type..." if mode == "typer" else "Preparing to auto-click..."
        self._show_popout(status)
        self.worker_thread = threading.Thread(target=worker, args=args, daemon=True)
        self.worker_thread.start()

    def start_typing(self):
        if pyautogui is None:
            messagebox.showerror("Missing dependency", "Install pyautogui first (pip install pyautogui).")
            return
        text = self.text_box.get("1.0", "end-1c")
        if not text.strip():
            messagebox.showinfo("Nothing to type", "Type or paste something in the box first.")
            return
        config = {
            "start_delay": max(float(self._safe_get(self.start_delay, 5)), 0),
            "base_delay": max(float(self._safe_get(self.char_delay, 0.05)), 0),
            "human": bool(self.human_mode.get()), "loop": bool(self.loop_mode.get()),
            "fix_indent": bool(self.fix_indent.get()), "typo": bool(self.typo_mode.get()),
            "typo_chance": max(float(self._safe_get(self.typo_chance, 0)), 0),
        }
        pyautogui.FAILSAFE = True
        self._begin_run("typer", self._type_worker, (text, config))

    def start_clicking(self):
        if pyautogui is None:
            messagebox.showerror("Missing dependency", "Install pyautogui first (pip install pyautogui).")
            return
        interval = max(float(self._safe_get(self.click_interval, 100)), 0)
        if self.click_interval_unit.get() == "ms":
            interval /= 1000
        count = max(self._safe_int(self.click_count, 1), 1)
        config = {
            "start_delay": max(float(self._safe_get(self.start_delay, 5)), 0),
            "interval": interval,
            "click_type": self.click_type.get(),
            "location_mode": self.click_location_mode.get(),
            "x": self._safe_int(self.click_x), "y": self._safe_int(self.click_y),
            "infinite": self.click_count_mode.get().startswith("Infinite"),
            "count": count,
            "jitter": max(float(self._safe_get(self.click_jitter, 0)), 0) / 100,
            "failsafe": bool(self.click_failsafe.get()),
        }
        pyautogui.FAILSAFE = config["failsafe"]
        self._begin_run("clicker", self._click_worker, (config,))

    def stop_active_run(self):
        if self.active_mode is None:
            return
        self.stop_flag.set()
        self.pause_flag.clear()
        self.popout_status.set("Stopping...")
        if self.active_mode == "typer":
            self.typer_status.set("Stopping...")
        else:
            self.clicker_status.set("Stopping...")
        self._restore_target_focus()

    def toggle_pause(self):
        if self.active_mode is None:
            return
        if self.pause_flag.is_set():
            self.pause_flag.clear()
            status = "Typing..." if self.active_mode == "typer" else "Auto-clicking..."
            self.popout_status.set(status)
            if self.active_mode == "typer":
                self.typer_status.set(status)
            else:
                self.clicker_status.set(status)
            if self.popout:
                self.popout.set_running(True, paused=False)
        else:
            self.pause_flag.set()
            self.popout_status.set("Paused")
            if self.active_mode == "typer":
                self.typer_status.set("Paused.")
            else:
                self.clicker_status.set("Paused.")
            if self.popout:
                self.popout.set_running(True, paused=True)
        self.root.after(10, self._restore_target_focus)

    def _show_popout(self, status):
        if not self.popout_enabled.get():
            return
        if self.popout is None or not self.popout.winfo_exists():
            self.popout = PopoutWindow(self)
        self.popout_status.set(status)
        self.popout_progress.set("0%")
        self.popout.set_running(True)
        self.popout.deiconify()
        self.popout.lift()

    def _close_or_pin_popout(self):
        if self.popout is None or not self.popout.winfo_exists():
            return
        if self.popout_pinned.get():
            self.popout.set_running(False)
        else:
            self.popout.destroy()
            self.popout = None

    def _remember_target_window(self):
        if os.name == "nt":
            try:
                self.target_hwnd = ctypes.windll.user32.GetForegroundWindow()
            except Exception:
                self.target_hwnd = None

    def _restore_target_focus(self):
        if os.name == "nt" and self.target_hwnd:
            try:
                ctypes.windll.user32.SetForegroundWindow(self.target_hwnd)
            except Exception:
                pass

    def _post(self, name, *args):
        self.ui_queue.put((name, args))

    def _drain_ui_queue(self):
        try:
            while True:
                name, args = self.ui_queue.get_nowait()
                if name == "status":
                    mode, text = args
                    (self.typer_status if mode == "typer" else self.clicker_status).set(text)
                    self.popout_status.set(text.rstrip("."))
                elif name == "progress":
                    mode, done, total = args
                    if total:
                        percent = min(100, int(done * 100 / total))
                        unit = "chars" if mode == "typer" else "clicks"
                        self.popout_progress.set(f"{percent}%  •  {done:,} / {total:,} {unit}")
                    else:
                        self.popout_progress.set(f"{done:,} clicks")
                elif name == "finish":
                    self._finish_ui(*args)
        except queue.Empty:
            pass
        try:
            self.root.after(40, self._drain_ui_queue)
        except tk.TclError:
            pass

    def _wait_while_paused(self):
        while self.pause_flag.is_set() and not self.stop_flag.is_set():
            time.sleep(0.03)
        return not self.stop_flag.is_set()

    def _sleep_interruptible(self, seconds):
        remaining = max(seconds, 0)
        last = time.monotonic()
        while remaining > 0:
            if self.stop_flag.is_set():
                return False
            if self.pause_flag.is_set():
                if not self._wait_while_paused():
                    return False
                last = time.monotonic()
                continue
            now = time.monotonic()
            remaining -= now - last
            last = now
            time.sleep(min(0.03, max(remaining, 0)))
        return not self.stop_flag.is_set()

    def _countdown(self, seconds, mode):
        remaining = max(seconds, 0)
        last = time.monotonic()
        last_value = None
        while True:
            if self.stop_flag.is_set():
                return False
            if self.pause_flag.is_set():
                if not self._wait_while_paused():
                    return False
                last = time.monotonic()
                continue
            now = time.monotonic()
            remaining = max(0, remaining - (now - last))
            last = now
            shown = int(remaining + 0.999)
            if shown != last_value and shown > 0:
                self._post("status", mode, f"Starting in {shown}s - click into your target window!")
                last_value = shown
            if remaining <= 0:
                self._remember_target_window()
                return True
            time.sleep(0.03)

    @staticmethod
    def _char_delay_value(base, human):
        delay = base
        if human:
            delay = max(0, random.gauss(base, base * 0.5 + 0.01))
            if random.random() < 0.03:
                delay += random.uniform(0.15, 0.4)
        return delay

    def _type_source_char(self, char, config):
        if not self._wait_while_paused():
            return False
        pyautogui.write(char)
        return self._sleep_interruptible(self._char_delay_value(config["base_delay"], config["human"]))

    def _type_word(self, word, config, advance):
        make_typo = config["typo"] and len(word) >= 3 and random.random() < config["typo_chance"] / 100
        typo_index = random.randint(1, len(word) - 1) if make_typo else -1
        for index, char in enumerate(word):
            if index == typo_index:
                if not self._wait_while_paused():
                    return False
                wrong = random.choice(TYPO_CHARS.replace(char.lower(), "") or TYPO_CHARS)
                pyautogui.write(wrong)
                if not self._sleep_interruptible(self._char_delay_value(config["base_delay"], config["human"])):
                    return False
                if not self._sleep_interruptible(random.uniform(0.15, 0.4)):
                    return False
                pyautogui.press("backspace")
                if not self._sleep_interruptible(self._char_delay_value(config["base_delay"], config["human"])):
                    return False
            if not self._type_source_char(char, config):
                return False
            advance()
        return True

    def _type_worker(self, text, config):
        try:
            if not self._countdown(config["start_delay"], "typer"):
                self._post("finish", "typer", "Stopped.")
                return
            total = len(text)
            started = time.monotonic()
            while True:
                done = 0
                last_post = 0
                self._post("status", "typer", "Typing...")

                def advance(amount=1):
                    nonlocal done, last_post
                    done += amount
                    now = time.monotonic()
                    if now - last_post >= 0.08 or done == total:
                        self._post("progress", "typer", done, total)
                        last_post = now

                lines = text.split("\n")
                for line_number, line in enumerate(lines):
                    if self.stop_flag.is_set():
                        self._post("finish", "typer", "Stopped.")
                        return
                    if line_number > 0:
                        if not self._wait_while_paused():
                            self._post("finish", "typer", "Stopped.")
                            return
                        pyautogui.press("enter")
                        if config["fix_indent"]:
                            if not self._sleep_interruptible(0.02):
                                self._post("finish", "typer", "Stopped.")
                                return
                            pyautogui.hotkey("shift", "home")
                            pyautogui.press("delete")
                        if not self._sleep_interruptible(config["base_delay"]):
                            self._post("finish", "typer", "Stopped.")
                            return
                        advance()
                    for token in re.split(r"(\s+)", line):
                        if not token:
                            continue
                        if token.isspace():
                            for char in token:
                                if not self._type_source_char(char, config):
                                    self._post("finish", "typer", "Stopped.")
                                    return
                                advance()
                        elif not self._type_word(token, config, advance):
                            self._post("finish", "typer", "Stopped.")
                            return
                if not config["loop"] or self.stop_flag.is_set():
                    break
                if not self._sleep_interruptible(1):
                    self._post("finish", "typer", "Stopped.")
                    return
            self._post("finish", "typer", f"Done in {format_duration(time.monotonic() - started)}.")
        except pyautogui.FailSafeException:
            self._post("finish", "typer", "Aborted (mouse hit screen corner).")
        except Exception as exc:
            self._post("finish", "typer", f"Error: {exc}")

    def _click_worker(self, config):
        try:
            if not self._countdown(config["start_delay"], "clicker"):
                self._post("finish", "clicker", "Stopped.")
                return
            if config["location_mode"] == "Current cursor position":
                target_x, target_y = pyautogui.position()
            else:
                target_x, target_y = config["x"], config["y"]
            total = None if config["infinite"] else config["count"]
            completed = 0
            started = time.monotonic()
            self._post("status", "clicker", "Auto-clicking...")
            while not self.stop_flag.is_set() and (total is None or completed < total):
                if not self._wait_while_paused():
                    break
                if config["click_type"] == "Double-click":
                    pyautogui.doubleClick(target_x, target_y, interval=0.08)
                else:
                    pyautogui.click(target_x, target_y, button=config["click_type"].lower())
                completed += 1
                self._post("progress", "clicker", completed, total)
                if total is not None and completed >= total:
                    break
                multiplier = random.uniform(1 - config["jitter"], 1 + config["jitter"])
                if not self._sleep_interruptible(max(0, config["interval"] * multiplier)):
                    break
            if self.stop_flag.is_set():
                message = "Stopped."
            else:
                message = f"Done - {completed:,} clicks in {format_duration(time.monotonic() - started)}."
            self._post("finish", "clicker", message)
        except pyautogui.FailSafeException:
            self._post("finish", "clicker", "Aborted (mouse hit screen corner).")
        except Exception as exc:
            self._post("finish", "clicker", f"Error: {exc}")

    def _finish_ui(self, mode, message):
        (self.typer_status if mode == "typer" else self.clicker_status).set(message)
        self.popout_status.set(message.rstrip("."))
        self.active_mode = None
        self.pause_flag.clear()
        self.typer_start_btn.configure(state="normal")
        self.clicker_start_btn.configure(state="normal")
        self.typer_stop_btn.configure(state="disabled")
        self.clicker_stop_btn.configure(state="disabled")
        self.clear_btn.configure(state="normal")
        self._set_mode_switch_enabled(True)
        self._close_or_pin_popout()

    def pick_location(self):
        if pyautogui is None:
            messagebox.showerror("Missing dependency", "Install pyautogui first.")
            return
        if self.active_mode is not None or self._pick_polling:
            return
        self._pick_polling = True
        self.clicker_status.set("Hover over the target and press F8 (Esc to cancel).")
        if os.name == "nt":
            ctypes.windll.user32.GetAsyncKeyState(0x77)
            ctypes.windll.user32.GetAsyncKeyState(0x1B)
            self.root.after(40, self._poll_pick_key)
        else:
            self.root.bind_all("<F8>", self._capture_location_once)
            self.root.bind_all("<Escape>", self._cancel_pick_once)

    def _poll_pick_key(self):
        if not self._pick_polling:
            return
        if ctypes.windll.user32.GetAsyncKeyState(0x1B) & 1:
            self._cancel_pick()
        elif ctypes.windll.user32.GetAsyncKeyState(0x77) & 1:
            self._capture_location()
        else:
            self.root.after(40, self._poll_pick_key)

    def _capture_location_once(self, _event=None):
        self._capture_location()
        return "break"

    def _cancel_pick_once(self, _event=None):
        self._cancel_pick()
        return "break"

    def _capture_location(self):
        x, y = pyautogui.position()
        self.click_x.set(x)
        self.click_y.set(y)
        self.click_location_mode.set("Fixed X / Y")
        self.clicker_status.set(f"Location captured: X {x}, Y {y}.")
        self._end_pick()

    def _cancel_pick(self):
        self.clicker_status.set("Location pick cancelled.")
        self._end_pick()

    def _end_pick(self):
        self._pick_polling = False
        self.root.unbind_all("<F8>")
        self.root.unbind_all("<Escape>")

    def on_close(self):
        self.stop_flag.set()
        self.save_all_settings()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = AutoTyperApp(root)
    root.mainloop()