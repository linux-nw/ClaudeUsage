# Claude Usage

**Status:** 🟢 Active

Small Windows tray app that shows your Claude usage (weekly limit and session limit) and the countdown to the reset as icons in the taskbar. After that it needs no browser window.

**Name:** The name says what it does: Claude usage at a glance.

---

## Usage

Requirements: Windows 10 or 11 with Python 3.8 or newer.

1. Run `start.bat`. The script installs the dependencies (from `wheels/` or PyPI), closes old instances and starts the app in the background.
2. On first launch a browser window opens for the login at claude.ai. After that everything runs without a window.
3. Right-click the tray icon: Refresh, Open Claude, Log in again, Debug file, Quit.

Manual: `pip install pystray Pillow playwright` and once `python -m playwright install chromium`, then `run.bat` (or `debug_run.bat` with a visible console).

---

## Repo structure

```
claude_tray.py     the whole app
requirements.txt   Python dependencies
start.bat          starts and installs if needed
setup.bat          installs from wheels/
run.bat            starts without installing
debug_run.bat      starts with a console
wheels/            packages for offline installation
```

---

## Privacy

The app fetches your usage data from claude.ai. Login data and settings are stored as files in your user folder (`~/.claude_tray_*`).

---

## License

[PolyForm Noncommercial 1.0.0](LICENSE). Personal and non-commercial use is free. For commercial use, please get in touch.