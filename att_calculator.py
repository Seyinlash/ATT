"""(ATT) Calculator Edition - standalone desktop automation.

Requires: pyautogui (install with: pip install pyautogui)

All settings persist in ~/.auto_typer_settings.json. Move the mouse to a
screen corner during a run to trigger pyautogui's failsafe (when enabled).
"""

import ctypes
import ast
import hashlib
import hmac
import json
import logging
import os
import queue
import random
import re
import secrets
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

try:
    import pyautogui
except ImportError:
    pyautogui = None


APP_NAME = ""
APP_SHORT_NAME = "ATT"
APP_VERSION = "6.0.0"
COPYRIGHT_TEXT = "© 2026 Seyinlash. All rights reserved."
MIN_WPM = 5
MAX_WPM = 300
DEFAULT_WPM = 80
INDENT_SETTLE_SECONDS = 0.10
LOGGER = logging.getLogger("att")

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
    "wpm": DEFAULT_WPM,
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
    "interface_mode": "calculator",
    "access_control_enabled": False,
    "access_code_salt": "",
    "access_code_hash": "",
}


def load_settings():
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("Could not load settings: %s", exc)
        data = {}
    merged = dict(DEFAULT_SETTINGS)
    merged.update(data if isinstance(data, dict) else {})
    if "wpm" not in data:
        try:
            old_delay = float(data.get("char_delay", DEFAULT_SETTINGS["char_delay"]))
            merged["wpm"] = round(12.0 / old_delay) if old_delay > 0 else MAX_WPM
        except (TypeError, ValueError):
            merged["wpm"] = DEFAULT_WPM
    try:
        merged["wpm"] = validate_wpm(merged["wpm"])
    except ValueError:
        merged["wpm"] = DEFAULT_WPM
    return merged


def save_settings(data):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        return True
    except OSError as exc:
        LOGGER.error("Could not save settings: %s", exc)
        return False


def validate_wpm(value):
    """Return a validated integer WPM value or raise ValueError."""
    if isinstance(value, str):
        value = value.strip()
    if value == "" or value is None:
        raise ValueError("WPM cannot be empty.")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("WPM must be a number.") from exc
    if not numeric.is_integer():
        raise ValueError("WPM must be a whole number.")
    numeric = int(numeric)
    if not MIN_WPM <= numeric <= MAX_WPM:
        raise ValueError(f"WPM must be between {MIN_WPM} and {MAX_WPM}.")
    return numeric


def wpm_to_interval(wpm):
    """Convert standardized WPM to seconds per character.

    Typing tests define one word as five characters (including spaces), so
    seconds/character = 60 / (WPM * 5). Actual words may be longer or shorter;
    the five-character standard keeps the control predictable.
    """
    return 60.0 / (validate_wpm(wpm) * 5.0)


def validate_typing_text(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Type or paste something in the box first.")
    return text


def hash_access_code(code, salt=None):
    if not isinstance(code, str) or not code.isdigit() or not 4 <= len(code) <= 12:
        raise ValueError("The PIN must contain 4 to 12 digits.")
    salt_bytes = bytes.fromhex(salt) if salt else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", code.encode("utf-8"), salt_bytes, 200_000)
    return salt_bytes.hex(), digest.hex()


def verify_access_code(code, salt, expected_hash):
    if not code or not salt or not expected_hash:
        return False
    try:
        _, candidate = hash_access_code(code, salt)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, expected_hash)


def evaluate_calculation(expression):
    """Safely evaluate calculator arithmetic without Python eval()."""
    expression = expression.replace("×", "*").replace("÷", "/")
    if not expression.strip():
        raise ValueError("Enter a calculation.")
    allowed_binary = {
        ast.Add: lambda a, b: a + b,
        ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b,
    }
    allowed_unary = {ast.UAdd: lambda value: value, ast.USub: lambda value: -value}

    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in allowed_binary:
            return allowed_binary[type(node.op)](visit(node.left), visit(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in allowed_unary:
            return allowed_unary[type(node.op)](visit(node.operand))
        raise ValueError("Invalid expression.")

    try:
        result = visit(ast.parse(expression, mode="eval"))
    except ZeroDivisionError as exc:
        raise ValueError("Cannot divide by zero.") from exc
    except (SyntaxError, TypeError, OverflowError) as exc:
        raise ValueError("Invalid expression.") from exc
    if isinstance(result, float) and result.is_integer():
        result = int(result)
    return result


def clear_editor_auto_indent(backend, wait_fn=time.sleep):
    """Clear only the current editor line after Enter.

    Two Home presses normalize smart-Home behavior across VS Code/Monaco and
    browser editors. Selecting Home-to-End removes real or delayed auto-indent
    without selecting content from the preceding line.
    """
    if wait_fn(INDENT_SETTLE_SECONDS) is False:
        return False
    backend.press("home", presses=2, interval=0.01)
    backend.hotkey("shift", "end")
    # Delete is deliberately used instead of Backspace: with no indentation
    # selected, Delete is a no-op while Backspace could join the prior line.
    backend.press("delete")
    return wait_fn(0.02) is not False


def send_unicode_character(character):
    """Send one non-ASCII character with Windows Unicode keyboard events."""
    if os.name != "nt":
        raise RuntimeError("Direct Unicode typing is currently supported on Windows only.")

    from ctypes import wintypes

    class KeyboardInput(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class MouseInput(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG), ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class HardwareInput(ctypes.Structure):
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]

    class InputUnion(ctypes.Union):
        _fields_ = [("ki", KeyboardInput), ("mi", MouseInput), ("hi", HardwareInput)]

    class Input(ctypes.Structure):
        _anonymous_ = ("value",)
        _fields_ = [("type", wintypes.DWORD), ("value", InputUnion)]

    units = character.encode("utf-16-le")
    events = []
    extra = ctypes.c_ulong(0)
    for index in range(0, len(units), 2):
        unit = int.from_bytes(units[index:index + 2], "little")
        events.append(Input(type=1, ki=KeyboardInput(0, unit, 0x0004, 0, ctypes.pointer(extra))))
        events.append(Input(type=1, ki=KeyboardInput(0, unit, 0x0004 | 0x0002, 0, ctypes.pointer(extra))))
    array_type = Input * len(events)
    sent = ctypes.windll.user32.SendInput(len(events), array_type(*events), ctypes.sizeof(Input))
    if sent != len(events):
        raise OSError("Windows could not send the Unicode keyboard event.")


def emit_character(backend, character, unicode_sender=send_unicode_character):
    """Send ASCII through pyautogui and Unicode through the Windows path."""
    if len(character) != 1:
        raise ValueError("emit_character expects exactly one character.")
    if ord(character) < 128:
        backend.write(character)
    else:
        unicode_sender(character)


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
        self.title("Auto Typer / Clicker - Settings")
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
        self._label_spin(typer, 1, "Typing speed (WPM):", app.wpm, MIN_WPM, MAX_WPM, 1)
        ttk.Label(typer, text="Standard WPM uses five characters per word.").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(0, 6))
        ttk.Checkbutton(typer, text="Human-like variation (random pauses)",
                        variable=app.human_mode).grid(row=3, column=0, columnspan=2, sticky="w", pady=6)
        ttk.Checkbutton(typer, text="Repeat / loop", variable=app.loop_mode).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=6)
        ttk.Checkbutton(typer, text="Fix editor auto-indent (recommended for VS Code / IDEs)",
                        variable=app.fix_indent).grid(row=5, column=0, columnspan=2, sticky="w", pady=6)
        ttk.Checkbutton(typer, text="Simulate typos, then backspace + correct them",
                        variable=app.typo_mode).grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self._label_spin(typer, 7, "Typo chance (%):", app.typo_chance, 0, 100, 1)

        ttk.Label(clicker, text="The everyday click controls also appear on the main page.",
                  foreground=app.colors["status_fg"]).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self._label_spin(clicker, 1, "Random interval jitter (%):", app.click_jitter, 0, 100, 1)
        ttk.Checkbutton(clicker, text="Enable mouse-corner failsafe",
                        variable=app.click_failsafe).grid(row=2, column=0, columnspan=2, sticky="w", pady=6)

        ttk.Checkbutton(general, text="Enable pop-out control window while running",
                        variable=app.popout_enabled).grid(row=0, column=0, sticky="w", pady=6)
        ttk.Checkbutton(general, text="Keep pop-out open after a run finishes",
                        variable=app.popout_pinned).grid(row=1, column=0, sticky="w", pady=6)
        if app.calculator_enabled:
            ttk.Label(general, text="Calculator edition: ATT locks automatically.").grid(
                row=2, column=0, sticky="w", pady=(6, 2))
            ttk.Button(general, text="Change unlock PIN",
                       command=app.configure_access_code).grid(row=3, column=0, sticky="w", pady=6)
        ttk.Separator(general).grid(row=4, column=0, sticky="ew", pady=(12, 8))
        ttk.Label(general, text=f"{APP_NAME} (ATT) v{APP_VERSION}").grid(row=5, column=0, sticky="w")
        ttk.Label(general, text=COPYRIGHT_TEXT).grid(row=6, column=0, sticky="w", pady=(2, 0))

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
        except (OSError, AttributeError, tk.TclError) as exc:
            LOGGER.debug("Could not apply no-activate window style: %s", exc)

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
    def __init__(self, root, calculator_enabled=False):
        self.root = root
        self.calculator_enabled = calculator_enabled
        root.title(f"{APP_NAME} (ATT) - Calculator Edition" if calculator_enabled else f"{APP_NAME} (ATT)")
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
        self._wpm_lock = threading.Lock()
        self._live_wpm = validate_wpm(settings.get("wpm", DEFAULT_WPM))

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
        self.wpm = tk.StringVar(value=str(self._live_wpm))
        self.wpm_display = tk.StringVar(value=f"{self._live_wpm} WPM")
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
        self.interface_mode = tk.StringVar(value="calculator" if calculator_enabled else "standard")
        self.access_control_enabled = tk.BooleanVar(
            value=True if calculator_enabled else settings.get("access_control_enabled", False))
        self.access_code_salt = settings.get("access_code_salt", "")
        self.access_code_hash = settings.get("access_code_hash", "")

        self.typer_status = tk.StringVar(value="Ready.")
        self.typer_estimate = tk.StringVar(value="Estimated typing time: -")
        self.clicker_status = tk.StringVar(value="Ready.")
        self.clicker_estimate = tk.StringVar(value="Estimated run time: -")
        self.popout_status = tk.StringVar(value="Ready.")
        self.popout_progress = tk.StringVar(value="0%")

        self.standard_shell = ttk.Frame(root)
        self._build_top_bar(self.standard_shell)
        self.content_host = ttk.Frame(self.standard_shell)
        self.content_host.pack(fill="both", expand=True)
        self._build_typer_page()
        self._build_clicker_page()
        self.hint_label = ttk.Label(self.standard_shell, text="Tip: flick the mouse to a screen corner anytime to abort.")
        self.hint_label.pack(anchor="w", padx=10, pady=(0, 8))
        self.standard_footer = ttk.Label(self.standard_shell, text=COPYRIGHT_TEXT, style="Footer.TLabel")
        self.standard_footer.pack(anchor="center", pady=(0, 7))
        if self.calculator_enabled:
            self._build_calculator_page()

        self.apply_theme()
        self.switch_mode(self.mode.get(), save=False)
        self.switch_interface(self.interface_mode.get(), require_code=False, save=False)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind("<Unmap>", self._on_window_unmap, add="+")
        root.bind("<Map>", self._on_window_map, add="+")
        self.text_box.bind("<<Modified>>", self._on_text_modified)

        watched = (
            self.start_delay, self.human_mode, self.loop_mode,
            self.fix_indent, self.typo_mode, self.typo_chance, self.click_interval,
            self.click_interval_unit, self.click_type, self.click_location_mode,
            self.click_x, self.click_y, self.click_count_mode, self.click_count,
            self.click_jitter, self.click_failsafe, self.popout_enabled,
            self.popout_pinned,
        )
        for var in watched:
            var.trace_add("write", self._setting_changed)
        self.wpm.trace_add("write", self._on_wpm_changed)
        self.update_estimates()
        self._ui_after_id = self.root.after(40, self._drain_ui_queue)

        if pyautogui is None:
            messagebox.showwarning("Missing dependency", "pyautogui isn't installed.\n\nRun:\n    pip install pyautogui\n\nthen restart this app.")

    @property
    def colors(self):
        return DARK if self.dark_mode.get() else LIGHT

    def _build_top_bar(self, parent):
        top = ttk.Frame(parent)
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
        if self.calculator_enabled:
            self.lock_btn = ttk.Button(top, text="Lock", command=self.lock_to_calculator)
            self.lock_btn.pack(side="right", padx=(0, 10))

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
        speed_row = ttk.Frame(self.typer_page)
        speed_row.pack(fill="x", padx=10, pady=(7, 0))
        ttk.Label(speed_row, text="Typing speed:").pack(side="left")
        self.wpm_spin = ttk.Spinbox(speed_row, from_=MIN_WPM, to=MAX_WPM, increment=1,
                                    textvariable=self.wpm, width=7)
        self.wpm_spin.pack(side="left", padx=(7, 6))
        ttk.Label(speed_row, textvariable=self.wpm_display).pack(side="left")
        ttk.Label(speed_row, text="(updates live while typing)", style="Hint.TLabel").pack(
            side="left", padx=(8, 0))
        self.wpm_spin.bind("<FocusOut>", self._validate_wpm_widget)
        self.wpm_spin.bind("<Return>", self._validate_wpm_widget)
        self.typer_status_label = ttk.Label(self.typer_page, textvariable=self.typer_status)
        self.typer_status_label.pack(anchor="w", padx=10, pady=(8, 0))
        ttk.Label(self.typer_page, textvariable=self.typer_estimate).pack(anchor="w", padx=10)
        row = ttk.Frame(self.typer_page)
        row.pack(fill="x", padx=10, pady=6)
        self.typer_start_btn = ttk.Button(row, text="Start", command=self.start_typing)
        self.typer_start_btn.pack(side="left", padx=(0, 8))
        self.typer_pause_btn = ttk.Button(row, text="Pause", command=self.toggle_pause, state="disabled")
        self.typer_pause_btn.pack(side="left", padx=(0, 8))
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
        self.clicker_pause_btn = ttk.Button(row, text="Pause", command=self.toggle_pause, state="disabled")
        self.clicker_pause_btn.pack(side="left", padx=(0, 8))
        self.clicker_stop_btn = ttk.Button(row, text="Stop", command=self.stop_active_run, state="disabled")
        self.clicker_stop_btn.pack(side="left")

    def _build_calculator_page(self):
        self.calculator_page = ttk.Frame(self.root)
        card = ttk.Frame(self.calculator_page, padding=18)
        card.pack(expand=True)
        ttk.Label(card, text="Calculator", style="CalculatorTitle.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 10))
        self.calculator_expression = tk.StringVar(value="")
        self.calculator_message = tk.StringVar(value="Ready")
        self.calculator_display = ttk.Entry(card, textvariable=self.calculator_expression,
                                            width=26, justify="right", font=("Segoe UI", 18),
                                            state="readonly")
        self.calculator_display.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(0, 5), ipady=8)
        ttk.Label(card, textvariable=self.calculator_message, style="Hint.TLabel").grid(
            row=2, column=0, columnspan=4, sticky="e", pady=(0, 8))

        buttons = (
            ("C", 3, 0), ("⌫", 3, 1), ("÷", 3, 2), ("×", 3, 3),
            ("7", 4, 0), ("8", 4, 1), ("9", 4, 2), ("-", 4, 3),
            ("4", 5, 0), ("5", 5, 1), ("6", 5, 2), ("+", 5, 3),
            ("1", 6, 0), ("2", 6, 1), ("3", 6, 2), ("=", 6, 3),
            ("0", 7, 0), (".", 7, 1), ("(", 7, 2), (")", 7, 3),
        )
        for label, row, column in buttons:
            button = ttk.Button(card, text=label, width=7,
                                command=lambda value=label: self._calculator_press(value))
            button.grid(row=row, column=column, padx=3, pady=3, ipady=7, sticky="nsew")
        for column in range(4):
            card.columnconfigure(column, weight=1)

        background = ttk.LabelFrame(self.calculator_page, text="Background automation", padding=8)
        background.pack(fill="x", padx=18, pady=(0, 10))
        ttk.Label(background, textvariable=self.popout_status).pack(side="left")
        self.calculator_pause_btn = ttk.Button(background, text="Pause", command=self.toggle_pause,
                                                state="disabled", width=9)
        self.calculator_pause_btn.pack(side="right", padx=(6, 0))
        self.calculator_stop_btn = ttk.Button(background, text="Stop", command=self.stop_active_run,
                                               state="disabled", width=8)
        self.calculator_stop_btn.pack(side="right")
        footer = ttk.Frame(self.calculator_page)
        footer.pack(fill="x", padx=12, pady=(0, 8))
        ttk.Label(footer, text=COPYRIGHT_TEXT, style="Footer.TLabel").pack(side="left", expand=True)
        self.calculator_unlock_btn = ttk.Button(footer, text="🔒", width=3,
                                                 command=self.request_att_unlock)
        self.calculator_unlock_btn.pack(side="right")
        self.root.bind("<Key>", self._calculator_key, add="+")

    def _calculator_press(self, value):
        if value == "C":
            self.calculator_expression.set("")
            self.calculator_message.set("Ready")
        elif value == "⌫":
            self.calculator_expression.set(self.calculator_expression.get()[:-1])
        elif value == "=":
            try:
                result = evaluate_calculation(self.calculator_expression.get())
                self.calculator_expression.set(str(result))
                self.calculator_message.set("Result")
            except ValueError as exc:
                self.calculator_message.set(str(exc))
        else:
            self.calculator_expression.set(self.calculator_expression.get() + value)
            self.calculator_message.set("Ready")

    def _calculator_key(self, event):
        if not self.calculator_enabled or self.interface_mode.get() != "calculator":
            return None
        if event.keysym in ("Return", "KP_Enter"):
            self._calculator_press("=")
            return "break"
        if event.keysym == "BackSpace":
            self._calculator_press("⌫")
            return "break"
        if event.keysym in ("Escape", "Delete"):
            self._calculator_press("C")
            return "break"
        character = event.char
        if character in "0123456789.+-*/()":
            self._calculator_press({"*": "×", "/": "÷"}.get(character, character))
            return "break"
        return None

    def switch_interface(self, interface, require_code=True, save=True):
        if interface not in ("standard", "calculator"):
            interface = "standard"
        if interface == "calculator" and not self.calculator_enabled:
            interface = "standard"
        if (interface == "standard" and require_code and self.calculator_enabled
                and self.interface_mode.get() != "standard" and self.access_control_enabled.get()):
            if not self.access_code_hash:
                if not self.configure_access_code(require_current=False):
                    return False
            else:
                code = simpledialog.askstring("Unlock", "Enter your PIN:", show="*", parent=self.root)
                if not verify_access_code(code, self.access_code_salt, self.access_code_hash):
                    if code is not None:
                        messagebox.showerror("Access denied", "The PIN is incorrect.", parent=self.root)
                    return False
        self.standard_shell.pack_forget()
        if self.calculator_enabled:
            self.calculator_page.pack_forget()
        self.interface_mode.set(interface)
        if interface == "standard":
            self.standard_shell.pack(fill="both", expand=True)
        else:
            self.calculator_page.pack(fill="both", expand=True)
        self._refresh_interface_styles()
        if save:
            self.save_all_settings()
        return True

    def _refresh_interface_styles(self):
        return

    def request_att_unlock(self):
        return self.switch_interface("standard", require_code=True)

    def lock_to_calculator(self):
        if not self.calculator_enabled:
            return False
        return self.switch_interface("calculator", require_code=False)

    def on_access_control_toggle(self):
        if self.access_control_enabled.get() and not self.access_code_hash:
            if not self.configure_access_code(require_current=False):
                self.access_control_enabled.set(False)
        self.save_all_settings()

    def configure_access_code(self, require_current=True):
        if require_current and self.access_code_hash:
            current = simpledialog.askstring("Change access code", "Enter the current access code:",
                                             show="*", parent=self.root)
            if not verify_access_code(current, self.access_code_salt, self.access_code_hash):
                if current is not None:
                    messagebox.showerror("Access denied", "The current access code is incorrect.", parent=self.root)
                return False
        new_code = simpledialog.askstring("Set PIN", "Enter a new PIN (4-12 digits):",
                                          show="*", parent=self.root)
        if new_code is None:
            return False
        confirmation = simpledialog.askstring("Set PIN", "Enter the new PIN again:",
                                               show="*", parent=self.root)
        if new_code != confirmation:
            messagebox.showerror("PINs do not match", "The two PINs did not match.", parent=self.root)
            return False
        try:
            self.access_code_salt, self.access_code_hash = hash_access_code(new_code)
        except ValueError as exc:
            messagebox.showerror("Invalid PIN", str(exc), parent=self.root)
            return False
        self.access_control_enabled.set(True)
        self.save_all_settings()
        messagebox.showinfo("PIN saved", "The unlock PIN was updated.", parent=self.root)
        return True

    def _setting_changed(self, *_args):
        self.update_estimates()
        self.save_all_settings()

    def _on_wpm_changed(self, *_args):
        try:
            value = validate_wpm(self.wpm.get())
        except ValueError:
            self.wpm_display.set(f"Enter {MIN_WPM}-{MAX_WPM}")
            return
        with self._wpm_lock:
            self._live_wpm = value
        self.wpm_display.set(f"{value} WPM")
        self.update_estimates()
        self.save_all_settings()

    def _validate_wpm_widget(self, _event=None):
        try:
            value = validate_wpm(self.wpm.get())
        except ValueError as exc:
            messagebox.showerror("Invalid WPM", str(exc), parent=self.root)
            with self._wpm_lock:
                value = self._live_wpm
            self.wpm.set(str(value))
            self.wpm_spin.focus_set()
            self.wpm_spin.selection_range(0, "end")
            return "break"
        self.wpm.set(str(value))
        return None

    def _current_wpm(self):
        with self._wpm_lock:
            return self._live_wpm

    def _current_char_interval(self):
        return wpm_to_interval(self._current_wpm())

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
        current_wpm = self._current_wpm()
        save_settings({
            "dark_mode": bool(self._safe_get(self.dark_mode, False)),
            "last_mode": self.mode.get(),
            "start_delay": float(self._safe_get(self.start_delay, 5.0)),
            "char_delay": wpm_to_interval(current_wpm),
            "wpm": current_wpm,
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
            "interface_mode": self.interface_mode.get(),
            "access_control_enabled": bool(self.access_control_enabled.get()),
            "access_code_salt": self.access_code_salt,
            "access_code_hash": self.access_code_hash,
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
            base = self._current_char_interval()
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
        self.style.configure("Footer.TLabel", background=c["bg"], foreground=c["hint_fg"],
                             font=("Segoe UI", 8))
        self.style.configure("Hint.TLabel", background=c["bg"], foreground=c["hint_fg"])
        self.style.configure("CalculatorTitle.TLabel", background=c["bg"], foreground=c["fg"],
                             font=("Segoe UI", 16, "bold"))
        self.text_box.configure(bg=c["text_bg"], fg=c["text_fg"], insertbackground=c["fg"])
        self.typer_status_label.configure(foreground=c["status_fg"])
        self.clicker_status_label.configure(foreground=c["status_fg"])
        self.hint_label.configure(foreground=c["hint_fg"])
        self._refresh_mode_styles()
        self._refresh_interface_styles()

    def _begin_run(self, mode, worker, args):
        if self.active_mode is not None:
            return False
        self.active_mode = mode
        self.stop_flag.clear()
        self.pause_flag.clear()
        self.target_hwnd = None
        self._set_mode_switch_enabled(False)
        self.typer_start_btn.configure(state="disabled")
        self.clicker_start_btn.configure(state="disabled")
        self.clear_btn.configure(state="disabled")
        self.typer_pause_btn.configure(state="normal" if mode == "typer" else "disabled", text="Pause")
        self.clicker_pause_btn.configure(state="normal" if mode == "clicker" else "disabled", text="Pause")
        if self.calculator_enabled:
            self.calculator_pause_btn.configure(state="normal", text="Pause")
            self.calculator_stop_btn.configure(state="normal")
        (self.typer_stop_btn if mode == "typer" else self.clicker_stop_btn).configure(state="normal")
        status = "Preparing to type..." if mode == "typer" else "Preparing to auto-click..."
        self._show_popout(status)
        self.worker_thread = threading.Thread(target=worker, args=args, daemon=True)
        self.worker_thread.start()
        return True

    def start_typing(self):
        if pyautogui is None:
            messagebox.showerror("Missing dependency", "Install pyautogui first (pip install pyautogui).")
            return
        text = self.text_box.get("1.0", "end-1c")
        try:
            validate_typing_text(text)
        except ValueError as exc:
            messagebox.showinfo("Nothing to type", str(exc), parent=self.root)
            return
        try:
            validated_wpm = validate_wpm(self.wpm.get())
        except ValueError as exc:
            messagebox.showerror("Invalid WPM", str(exc), parent=self.root)
            return
        with self._wpm_lock:
            self._live_wpm = validated_wpm
        config = {
            "start_delay": max(float(self._safe_get(self.start_delay, 5)), 0),
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
            self._set_pause_button_text("Pause")
        else:
            self.pause_flag.set()
            self.popout_status.set("Paused")
            if self.active_mode == "typer":
                self.typer_status.set("Paused.")
            else:
                self.clicker_status.set("Paused.")
            if self.popout:
                self.popout.set_running(True, paused=True)
            self._set_pause_button_text("Resume")
        self.root.after(10, self._restore_target_focus)

    def _set_pause_button_text(self, text):
        self.typer_pause_btn.configure(text=text)
        self.clicker_pause_btn.configure(text=text)
        if self.calculator_enabled:
            self.calculator_pause_btn.configure(text=text)

    def _show_popout(self, status, force=False):
        if not force and not self.popout_enabled.get():
            return
        if self.popout is None or not self.popout.winfo_exists():
            self.popout = PopoutWindow(self)
        self.popout_status.set(status)
        self.popout_progress.set("0%")
        self.popout.set_running(True)
        self.popout.deiconify()
        self.popout.lift()

    def _on_window_unmap(self, event):
        if event.widget is not self.root or self.active_mode is None:
            return
        # Tkinter worker threads continue while the main window is minimized.
        # Force a background control panel so Pause/Stop remain reachable even
        # when the user's normal pop-out preference is disabled.
        self.root.after(60, self._ensure_background_controls)

    def _ensure_background_controls(self):
        if self.active_mode is None or self.root.state() != "iconic":
            return
        status = "Paused" if self.pause_flag.is_set() else (
            "Typing..." if self.active_mode == "typer" else "Auto-clicking...")
        self._show_popout(status, force=True)

    def _on_window_map(self, event):
        if (event.widget is self.root and self.active_mode is not None
                and not self.popout_enabled.get() and self.popout is not None
                and self.popout.winfo_exists()):
            self.popout.destroy()
            self.popout = None

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
            except (OSError, AttributeError) as exc:
                LOGGER.debug("Could not read the foreground window: %s", exc)
                self.target_hwnd = None

    def _restore_target_focus(self):
        if os.name == "nt" and self.target_hwnd:
            try:
                ctypes.windll.user32.SetForegroundWindow(self.target_hwnd)
            except (OSError, AttributeError) as exc:
                LOGGER.debug("Could not restore target focus: %s", exc)

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
            self._ui_after_id = self.root.after(40, self._drain_ui_queue)
        except tk.TclError:
            self._ui_after_id = None

    def _cancel_ui_pump(self):
        after_id = getattr(self, "_ui_after_id", None)
        if after_id is not None:
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass
            self._ui_after_id = None

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

    def _char_delay_value(self, human):
        base = self._current_char_interval()
        delay = base
        if human:
            delay = max(0, random.gauss(base, base * 0.5 + 0.01))
            if random.random() < 0.03:
                delay += random.uniform(0.15, 0.4)
        return delay

    def _type_source_char(self, char, config):
        if not self._wait_while_paused():
            return False
        emit_character(pyautogui, char)
        return self._sleep_interruptible(self._char_delay_value(config["human"]))

    def _type_word(self, word, config, advance):
        make_typo = config["typo"] and len(word) >= 3 and random.random() < config["typo_chance"] / 100
        typo_index = random.randint(1, len(word) - 1) if make_typo else -1
        for index, char in enumerate(word):
            if index == typo_index:
                if not self._wait_while_paused():
                    return False
                wrong = random.choice(TYPO_CHARS.replace(char.lower(), "") or TYPO_CHARS)
                pyautogui.write(wrong)
                if not self._sleep_interruptible(self._char_delay_value(config["human"])):
                    return False
                if not self._sleep_interruptible(random.uniform(0.15, 0.4)):
                    return False
                pyautogui.press("backspace")
                if not self._sleep_interruptible(self._char_delay_value(config["human"])):
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
                            if not self._wait_while_paused():
                                self._post("finish", "typer", "Stopped.")
                                return
                            if not clear_editor_auto_indent(pyautogui, self._sleep_interruptible):
                                self._post("finish", "typer", "Stopped.")
                                return
                        if not self._sleep_interruptible(self._current_char_interval()):
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
        self.typer_pause_btn.configure(state="disabled", text="Pause")
        self.clicker_pause_btn.configure(state="disabled", text="Pause")
        if self.calculator_enabled:
            self.calculator_pause_btn.configure(state="disabled", text="Pause")
            self.calculator_stop_btn.configure(state="disabled")
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
        self._cancel_ui_pump()
        self.save_all_settings()
        self.root.destroy()


def run(calculator_enabled=True):
    root = tk.Tk()
    AutoTyperApp(root, calculator_enabled=calculator_enabled)
    root.mainloop()


if __name__ == "__main__":
    run(calculator_enabled=True)
