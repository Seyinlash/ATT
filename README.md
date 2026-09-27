# Assisted Typing Tool (ATT)

Assisted Typing Tool is a Windows desktop app that automates typing and mouse clicking. It is built with Python and Tkinter and uses [`pyautogui`](https://pypi.org/project/PyAutoGUI/) to send real keystrokes and clicks to whichever application you choose-browsers, chats, documents, code editors, and more.

ATT includes two modes:

- **Auto Typer** - types user-provided text with adjustable, human-like timing.
- **Auto Clicker** - repeatedly clicks a selected location using configurable timing and click behavior.

## Features

### Auto Typer

- **GUI text input** - paste or write any text you want typed.
- **Human-like timing** - randomizes delays between keystrokes and adds occasional longer pauses.
- **Adjustable speed** - controls the base delay per character.
- **Start delay countdown** - gives you time to focus the target application before typing begins.
- **Typo simulation** - occasionally types a wrong character, pauses, backspaces, and corrects it. The chance is adjustable per word.
- **Auto-indent correction** - removes unwanted indentation inserted by smart editors before typing the intended leading whitespace.
- **Loop mode** - repeats the same text until stopped.
- **Live time estimate** - shows approximately how long the current text will take to type.
- **Completion timing** - reports how long a completed run actually took.
- **Clear button** - quickly empties the text box.

### Auto Clicker

- **Adjustable click interval** - enter the delay in milliseconds or seconds.
- **Multiple click types** - left, right, middle, or double-click.
- **Flexible targeting** - use the cursor position captured when the countdown ends or enter fixed X/Y coordinates.
- **Location picker** - hover over a target and press `F8` to capture its coordinates.
- **Fixed or infinite runs** - stop after a chosen number of clicks or continue until you press Stop.
- **Optional timing jitter** - randomizes the interval between clicks for less mechanical timing.
- **Live click progress** - displays the current and total click count.

### Shared controls

- **Auto Typer / Auto Clicker switcher** - changes modes from the main window and remembers the last mode used.
- **Floating control window** - an optional borderless, always-on-top panel displays status and progress while a run is active.
- **Pause and resume** - pause either mode between keystrokes or clicks without ending the run.
- **Stop control** - stop from the main window or floating panel.
- **Draggable pop-out** - move the floating panel anywhere on the screen; ATT remembers its last position.
- **Pinned pop-out option** - optionally keep the panel open after a run finishes.
- **Emergency failsafe** - move the mouse to a screen corner to abort automation immediately.
- **Light and dark themes** - the selected theme applies to the main window, Settings, and floating controls.
- **Persistent settings** - ATT automatically saves changes to `~/.auto_typer_settings.json`.

## Requirements

- Windows
- Python 3.x
- [`pyautogui`](https://pypi.org/project/PyAutoGUI/)

Install the dependency:

```bash
pip install pyautogui
```

The `keyboard` package is not required. ATT uses the Windows API to detect `F8` while picking an Auto Clicker location.

## How to use ATT

### Auto Typer

1. Open ATT and select **Auto Typer**.
2. Paste or enter the text you want typed.
3. Open **Settings** to adjust the start delay, typing speed, human-like timing, typo simulation, auto-indent correction, or loop mode.
4. Click **Start**.
5. Before the countdown ends, focus the application where ATT should type.
6. Use the main window or floating panel to pause, resume, or stop the run.

### Auto Clicker

1. Select **Auto Clicker**.
2. Choose the interval, click type, target location, and click count.
3. To capture a fixed location, click **Pick location**, hover over the target, and press `F8`. Press `Esc` to cancel.
4. Open **Settings** if you want to configure interval jitter, the mouse-corner failsafe, or pop-out behavior.
5. Click **Start** and focus the target application before the countdown ends.
6. Stop infinite runs from the main window or floating panel.

Only one mode can run at a time. ATT disables the mode switcher until the active run stops or finishes.

## Running the app

### 1. From the command line

```bash
pip install pyautogui
python auto_typer.py
```

### 2. With a `.bat` file on Windows

Create a file named `Run ATT.bat` in the same folder as `auto_typer.py`:

```bat
@echo off
start "" pythonw "%~dp0auto_typer.py"
```

Double-click `Run ATT.bat` to launch ATT without a visible terminal window. Python and `pyautogui` must still be installed on the computer.

### 3. As a standalone Windows `.exe`

Install [PyInstaller](https://pyinstaller.org/) and build ATT:

```bash
pip install pyinstaller
python -m PyInstaller --onefile --windowed --name "ATT" auto_typer.py
```

The finished executable will be placed in the `dist` folder. It can run on Windows without a separate Python installation.

Windows or antivirus software may warn about a newly built unsigned executable. Only run executables that you built yourself or obtained from a source you trust.

## Notes

- ATT simulates system-wide keyboard and mouse input rather than pasting text directly.
- Some applications may handle simulated input differently.
- Moving the mouse to a screen corner triggers `pyautogui`'s emergency failsafe when that option is enabled.
- Use ATT responsibly and follow the rules of the applications and services where you run it.
- ATT was created as a personal automation tool.

## License

MIT