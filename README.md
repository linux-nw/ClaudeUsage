# Claude Usage

A lightweight Windows system tray application that displays real-time Claude API usage statistics and session time remaining. Monitors your weekly and per-session quota utilization without requiring a browser window.

## What It Does

Claude Usage is a background task that:
- **Displays usage percentages** in the system tray (weekly and session limits)
- **Shows session reset countdown** with separate hour/minute indicators
- **One-time login flow** captures your Claude session automatically
- **Lightweight fetching** uses `curl.exe` for efficiency, with Playwright fallback
- **German-friendly** UI with localized labels and error messages
- **No browser needed** after initial login—runs headless in the background

## Stack

- **Language:** Python 3
- **UI Framework:** pystray (system tray icon management) + Pillow (image rendering)
- **Browser automation:** Playwright (login capture, fallback scraping)
- **HTTP client:** curl.exe (fast direct API requests)
- **Runtime:** Windows (command-line via `.bat` scripts)

### Key Dependencies
- **pystray** ≥0.19.5 — system tray icon lifecycle and menu handling
- **Pillow** ≥10.0.0 — dynamic icon rendering with text overlay
- **playwright** — browser context for login interception and headless scraping

## How It's Organized

```
ClaudeUsage/
├── claude_tray.py         Main application (1104 lines)
│                          ├─ Login flow (browser interception)
│                          ├─ API fetching (curl + Playwright fallback)
│                          ├─ JSON/text response parsing
│                          ├─ Icon rendering (Pillow)
│                          └─ Tray management (pystray)
├── requirements.txt       Python dependencies
├── pystray_test.py        Quick sanity test for tray + PIL imports
├── start.bat              Smart launcher (auto-installs, stops old instances)
├── setup.bat              Manual dependency installer from wheels/
├── run.bat                Simple launcher (assumes deps installed)
├── debug_run.bat          Console runner for troubleshooting
└── wheels/                (Optional) pre-downloaded .whl files for offline install
```

### How It Fits Together

**Startup:** `start.bat` (or `run.bat`) spawns `pythonw claude_tray.py` as a background process. The app initializes with saved settings and API config.

**Login:** If no valid API session is stored, the browser opens to `claude.ai/login`. Playwright intercepts API requests to extract:
- Session cookies (stored as `cookie_str`)
- Organization UUID (extracted from request URLs)
- Usage endpoint URL (detected from API responses)

**Polling Loop:** A background thread wakes every 60 seconds to fetch usage data:
1. **Fast path:** `curl.exe` hits the stored usage endpoint with cookies (20s timeout)
2. **Fallback:** If curl fails, Playwright opens a headless browser session, captures API responses, or scrapes the DOM for progress bars
3. **Result:** Weekly % and session % are extracted, settings saved, tray icon updated

**Icon Rendering:** Three tray icons show:
- **Main (session %):** White background with black percentage text
- **Reset hour:** Blue background with hours until session reset
- **Reset minute:** Blue background with minutes remainder

Right-click menu offers: refresh, open Claude, re-login, debug file, quit.

## How to Run It

### Quick Start
```bash
# Windows (from repo root)
start.bat
```

This script will:
1. Check for Python 3
2. Try local wheels from `wheels/` folder
3. Fall back to PyPI if wheels are incompatible
4. Kill any old instances
5. Launch the tray app as a background process

### Manual Setup
```bash
# Option A: Install from local wheels (offline)
setup.bat

# Option B: Install from PyPI
pip install pystray Pillow playwright

# Option C: Playwright browser setup (required once)
python -m playwright install chromium
```

### Running After Setup
```bash
# Simple launch (assumes deps already installed)
run.bat

# Or run with visible console (for debugging)
debug_run.bat

# Or invoke directly
pythonw claude_tray.py
```

### Environment & Configuration

The app stores state in your home directory:
- `~/.claude_tray_settings.json` — usage percentages, last fetch time, errors
- `~/.claude_tray_api.json` — cookies, org UUID, usage endpoint
- `~/.claude_tray_debug.txt` — captured requests/responses from last session
- `~/.claude_tray_browser/` — Playwright persistent browser profile
- `~/.claude_tray_launch.log` — startup/crash logs
- `~/.claude_tray_crash.txt` — error dialog contents (if GUI crashes)

**First run:** The app will prompt you to log in through an Edge/Chromium browser window. Complete the login and navigate to the usage page. The browser session info is automatically captured.

## Troubleshooting

### Icon doesn't appear
- Check that tray icons are visible in Windows settings
- Look for the hidden icon arrow (▲) next to the clock; right-click and show all icons
- Verify Python is running: `tasklist | findstr pythonw`

### "Login abgebrochen" (login cancelled)
- The login browser window stayed open for >10 minutes without completing
- Log in faster, or increase the 600-second timeout in code (line 211)

### "Datenformat unbekannt" (unknown data format)
- Claude API response doesn't match expected JSON schema
- Check `~/.claude_tray_debug.txt` to see what the API returned
- May indicate a Claude.ai UI update; open an issue with debug output

### Playwright won't install / missing chromium
- Run: `python -m playwright install chromium`
- Or ensure `setup.bat` or `start.bat` completed without errors

### Python not found
- Install Python 3.8+ from [python.org](https://www.python.org)
- Add Python to PATH during installation
- Or set `Path` environment variable to your Python `Scripts/` folder

## Try asking

- **How do I re-authenticate if my Claude session expires?** → Right-click the tray icon and select "Erneut einloggen" (Re-login). You'll go through the browser login flow again.

- **What does the blue reset countdown icon show?** → Hours (left icon) and minutes (right icon) remaining until your session quota resets. This uses the `session_reset_at` timestamp from Claude's API.

- **Can I run multiple instances to monitor different Claude accounts?** → The app stores settings in `~/.claude_tray_*` (per-user home directory). Currently, a single instance runs per Windows user. Launching multiple copies will kill the previous one (see `start.bat` line 29).

- **How does the app know which API endpoint to use?** → During login, it captures request URLs. It tries organization-specific endpoints first (e.g., `/api/organizations/{UUID}/usage`), then generic ones. The best working endpoint is saved for future fetches. If it breaks after a Claude.ai update, inspect the debug file and report the issue.

---

**License:** Not specified (add a LICENSE file if sharing publicly)  
**Platform:** Windows 10/11 with Python 3.8+  
**Language:** German (UI) + English (code)
