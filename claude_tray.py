#!/usr/bin/env python3
"""Claude Usage Tray
Login einmalig (sichtbares Edge-Fenster):
  -> faengt interne API-Antworten ab
  -> speichert Cookies + Endpoint
Danach: curl.exe ruft API direkt auf.
Fallback: Playwright scraped headless wenn curl scheitert.
"""

import json
import os
import re
import queue
import subprocess
import sys
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path

_CRASH_PATH = str(Path.home() / ".claude_tray_crash.txt")

def _show_error(title: str, msg: str) -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, title, 0x10)
    except Exception:
        pass
    try:
        with open(_CRASH_PATH, "w", encoding="utf-8") as _f:
            _f.write(f"{title}\n\n{msg}\n")
    except Exception:
        pass

try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError as _e:
    _show_error(
        "Claude Usage - Import-Fehler",
        f"Fehlende Bibliothek: {_e}\n\nBitte start.bat erneut ausfuehren.",
    )
    sys.exit(1)

BROWSER_DIR   = str(Path.home() / ".claude_tray_browser")
SETTINGS_PATH = str(Path.home() / ".claude_tray_settings.json")
API_CFG_PATH  = str(Path.home() / ".claude_tray_api.json")
DEBUG_PATH    = str(Path.home() / ".claude_tray_debug.txt")
LOGIN_URL     = "https://claude.ai/login"
USAGE_URL     = "https://claude.ai/settings/usage"
APP_NAME      = "Claude Usage"
APP_NAME_RESET = "Claude Reset"
ICON_SIZE = 64
REFRESH_SEC   = 60

DEFAULTS = {
    "weekly_pct":  None,
    "session_pct": None,
    "session_reset_at": None,
    "last_fetched": None,
    "last_error":  None,
}

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0"
)
_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--no-first-run",
    "--no-default-browser-check",
]
_STEALTH = """
(() => {
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    delete navigator.__proto__.webdriver;
    window.chrome = {runtime: {}, loadTimes: () => {}, csi: () => {}, app: {}};
    Object.defineProperty(navigator, 'languages', {get: () => ['de-DE','de','en-US','en']});
})();
"""

# Graceful on non-Windows (WSL testing, etc.)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ---------------------------------------------------------------------------
# Settings / config

def load_settings():
    try:
        with open(SETTINGS_PATH) as f:
            return {**DEFAULTS, **json.load(f)}
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULTS)

def save_settings(s):
    with open(SETTINGS_PATH, "w") as f:
        json.dump(s, f, indent=2)

def load_api_cfg():
    try:
        with open(API_CFG_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_api_cfg(cfg):
    with open(API_CFG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


# ---------------------------------------------------------------------------
# Debug helper

def _write_debug(requests=None, responses=None, org_uuid="", usage_endpoint="", extra=""):
    try:
        with open(DEBUG_PATH, "w", encoding="utf-8") as f:
            f.write(f"=== Debug {datetime.now().isoformat()} ===\n")
            f.write(f"org_uuid:       {org_uuid}\n")
            f.write(f"usage_endpoint: {usage_endpoint}\n")
            if extra:
                f.write(f"extra: {extra}\n")
            f.write("\n")
            if requests:
                f.write("=== Requests ===\n")
                for r in requests:
                    f.write(f"{r.get('method','GET')} {r['url']}\n")
                f.write("\n")
            if responses:
                f.write("=== Responses ===\n")
                for r in responses:
                    body = r.get("body", "")
                    if isinstance(body, (dict, list)):
                        body_str = json.dumps(body, indent=2, ensure_ascii=False)
                    else:
                        body_str = str(body)
                    f.write(f"\n[{r.get('status','?')}] {r['url']}\n")
                    f.write(body_str[:4000])
                    f.write("\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Browser context factory

def _make_ctx(pw, headless=False):
    return pw.chromium.launch_persistent_context(
        user_data_dir=BROWSER_DIR,
        channel="msedge",
        headless=headless,
        user_agent=_USER_AGENT,
        args=_LAUNCH_ARGS,
        viewport={"width": 980, "height": 700},
    )


# ---------------------------------------------------------------------------
# Login (einmalig, sichtbares Fenster)

def do_login() -> bool:
    captured_requests  = []
    captured_responses = []

    with sync_playwright() as pw:
        ctx = _make_ctx(pw, headless=False)
        ctx.add_init_script(_STEALTH)
        page = ctx.new_page()

        def on_request(req):
            if "claude.ai" in req.url and "/api/" in req.url:
                captured_requests.append({"url": req.url, "method": req.method})

        def on_response(resp):
            if "claude.ai" in resp.url and "/api/" in resp.url:
                try:
                    captured_responses.append({
                        "url":    resp.url,
                        "status": resp.status,
                        "body":   resp.json(),
                    })
                except Exception:
                    try:
                        text = resp.text()
                        if text.strip():
                            captured_responses.append({
                                "url":    resp.url,
                                "status": resp.status,
                                "body":   text,
                            })
                    except Exception:
                        pass

        page.on("request",  on_request)
        page.on("response", on_response)

        try:
            page.goto(LOGIN_URL, wait_until="domcontentloaded")

            # Wait for user to finish login
            page.wait_for_function(
                "() => {"
                "  const h = window.location.href;"
                "  return h.includes('claude.ai')"
                "      && !h.includes('/login')"
                "      && !h.includes('/sign');"
                "}",
                timeout=600_000,
            )

            # Navigate to usage page — try multiple URL variants
            for try_url in (USAGE_URL, "https://claude.ai/settings", "https://claude.ai/new"):
                try:
                    page.goto(try_url, wait_until="networkidle", timeout=20_000)
                    page.wait_for_timeout(2000)
                    if any(kw in r["url"].lower()
                           for r in captured_requests
                           for kw in ("limit", "rate", "usage", "entitlement", "quota")):
                        break
                except Exception:
                    pass
            page.wait_for_timeout(2000)

            # Try clicking any refresh/reload button
            for sel in [
                'button[aria-label*="Refresh"]',
                'button[aria-label*="refresh"]',
                'button[aria-label*="aktualisieren"]',
                'button[aria-label*="Reload"]',
                '[data-testid*="refresh"]',
            ]:
                try:
                    page.click(sel, timeout=2000)
                    page.wait_for_timeout(2000)
                    break
                except Exception:
                    pass

            # Extract org_uuid from captured requests
            uuid_pat = re.compile(
                r"/api/organizations/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}"
                r"-[0-9a-f]{4}-[0-9a-f]{12})"
            )
            org_uuid = ""
            for req in captured_requests:
                m = uuid_pat.search(req["url"])
                if m:
                    org_uuid = m.group(1)
                    break

            # Get session cookies
            claude_cookies = [
                c for c in ctx.cookies() if "claude.ai" in c.get("domain", "")
            ]
            cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in claude_cookies)

            # Find best usage endpoint from actual responses
            usage_endpoint = _find_best_endpoint(captured_responses)
            if not usage_endpoint:
                for req in captured_requests:
                    if any(kw in req["url"].lower()
                           for kw in ("usage", "limit", "rate", "quota", "entitlement")):
                        usage_endpoint = req["url"]
                        break

            _write_debug(
                requests=captured_requests,
                responses=captured_responses,
                org_uuid=org_uuid,
                usage_endpoint=usage_endpoint,
            )

            save_api_cfg({
                "cookie_str":     cookie_str,
                "org_uuid":       org_uuid,
                "usage_endpoint": usage_endpoint,
                "saved_at":       datetime.now(timezone.utc).isoformat(),
            })
            return True

        except PWTimeout:
            return False
        finally:
            ctx.close()


_SKIP_ENDPOINT_KEYWORDS = ("conversation", "chat", "message_list", "projects", "artifacts")

def _find_best_endpoint(responses: list) -> str:
    for resp in responses:
        url = resp.get("url", "")
        if any(kw in url.lower() for kw in _SKIP_ENDPOINT_KEYWORDS):
            continue
        body = resp.get("body")
        body_str = json.dumps(body) if isinstance(body, (dict, list)) else str(body)
        parsed = _parse_json_or_text(body_str)
        if parsed.get("weekly_pct") is not None or parsed.get("session_pct") is not None:
            return url
    return ""


def api_cfg_valid() -> bool:
    return bool(load_api_cfg().get("cookie_str"))


# ---------------------------------------------------------------------------
# Fetch via curl.exe (kein Browser nötig)

def _curl_get(url: str, cookie_str: str) -> str:
    cmd = [
        "curl.exe", "-s", "-L", "--compressed",
        "-H", f"Cookie: {cookie_str}",
        "-H", f"User-Agent: {_USER_AGENT}",
        "-H", "Accept: application/json, */*",
        "-H", "Referer: https://claude.ai/",
        url,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=20, creationflags=_NO_WINDOW)
    return r.stdout


_UUID_PAT = re.compile(
    r"/api/organizations/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
)

def _resolve_org_uuid(cfg: dict) -> str:
    """Returns org UUID from config or extracts it from stored endpoint URL."""
    uuid = cfg.get("org_uuid", "")
    if uuid:
        return uuid
    m = _UUID_PAT.search(cfg.get("usage_endpoint", ""))
    return m.group(1) if m else ""


def _curl_candidates(cfg: dict) -> list:
    seen, result = set(), []

    def add(url):
        if url and url not in seen:
            seen.add(url)
            result.append(url)

    uuid = _resolve_org_uuid(cfg)
    if uuid:
        base = f"https://claude.ai/api/organizations/{uuid}"
        # /usage first — confirmed working, contains limits[].percent + utilization
        for path in ("/usage", "/rate_limits", "/usage_limits", "/limit_status",
                     "/entitlements", "/active_subscription", "/billing_info", "/limits"):
            add(f"{base}{path}")

    # Generic endpoints
    for path in ("/api/rate_limit_status", "/api/usage_status",
                 "/api/rate_limits", "/api/account"):
        add(f"https://claude.ai{path}")

    # Previously stored endpoint last (may be wrong like chat_conversations)
    ep = cfg.get("usage_endpoint", "")
    if ep and "conversation" not in ep and "chat" not in ep:
        add(ep)

    return result


def _fetch_usage_curl() -> dict:
    cfg        = load_api_cfg()
    cookie_str = cfg.get("cookie_str", "")
    if not cookie_str:
        raise Exception("Keine Cookies — bitte einloggen")

    # Resolve org_uuid even if it was empty in saved config
    resolved_uuid = _resolve_org_uuid(cfg)
    if resolved_uuid and not cfg.get("org_uuid"):
        cfg["org_uuid"] = resolved_uuid
        save_api_cfg(cfg)

    hits = []
    for url in _curl_candidates(cfg):
        try:
            body = _curl_get(url, cookie_str)
            s = body.strip()
            if s.startswith(("{", "[")):
                hits.append((url, body))
        except Exception:
            continue

    _write_debug(
        requests=[{"url": u, "method": "GET"} for u, _ in hits],
        responses=[{"url": u, "body": b, "status": "curl"} for u, b in hits],
        org_uuid=resolved_uuid,
        usage_endpoint=cfg.get("usage_endpoint", ""),
    )

    for url, body in hits:
        parsed = _parse_json_or_text(body)
        if parsed.get("weekly_pct") is not None or parsed.get("session_pct") is not None:
            if url != cfg.get("usage_endpoint"):
                cfg["usage_endpoint"] = url
                save_api_cfg(cfg)
            return parsed

    if not hits:
        raise Exception("Kein Endpoint erreichbar")
    raise Exception("Datenformat unbekannt — debug pruefen")


# ---------------------------------------------------------------------------
# Playwright fallback (headless, nutzt gespeicherte Session)

def _fetch_usage_playwright() -> dict:
    captured = []

    with sync_playwright() as pw:
        try:
            ctx = _make_ctx(pw, headless=True)
        except Exception:
            return {"weekly_pct": None, "session_pct": None}

        try:
            ctx.add_init_script(_STEALTH)
            page = ctx.new_page()

            def on_response(resp):
                if "claude.ai" in resp.url and "/api/" in resp.url:
                    try:
                        captured.append({
                            "url":    resp.url,
                            "body":   resp.json(),
                            "status": resp.status,
                        })
                    except Exception:
                        pass

            page.on("response", on_response)

            try:
                page.goto(USAGE_URL, wait_until="networkidle", timeout=30_000)
                page.wait_for_timeout(3000)
            except Exception:
                pass

            # 1. Try captured API responses
            for resp in captured:
                parsed = _parse_json_or_text(json.dumps(resp["body"]))
                if parsed.get("weekly_pct") is not None or parsed.get("session_pct") is not None:
                    cfg = load_api_cfg()
                    cfg["usage_endpoint"] = resp["url"]
                    save_api_cfg(cfg)
                    return parsed

            # 2. Scrape DOM (progress bars, page text)
            return _scrape_dom(page)

        finally:
            try:
                ctx.close()
            except Exception:
                pass


def _scrape_dom(page) -> dict:
    result = {"weekly_pct": None, "session_pct": None}

    # Try aria progress bars (most reliable)
    try:
        bars = page.query_selector_all('[role="progressbar"], [aria-valuenow]')
        pcts = []
        for bar in bars:
            now  = bar.get_attribute("aria-valuenow")
            maxv = bar.get_attribute("aria-valuemax") or "100"
            if now:
                try:
                    pct = round(float(now) * 100 / float(maxv))
                    if 0 <= pct <= 100:
                        pcts.append(pct)
                except Exception:
                    pass
        if pcts:
            result["weekly_pct"]  = pcts[0]
            result["session_pct"] = pcts[1] if len(pcts) > 1 else None
            return result
    except Exception:
        pass

    # Try page text content
    try:
        text = page.inner_text("body")

        # Text % patterns (e.g. "Weekly 45%")
        parsed = _parse_text(text)
        if parsed.get("weekly_pct") is not None:
            return parsed

        # Fraction patterns (e.g. "45 / 100")
        pairs = re.findall(r'(\d+)\s*/\s*(\d+)', text)
        pcts = []
        for used_s, total_s in pairs:
            u, t = int(used_s), int(total_s)
            if t > 0 and u <= t:
                pct = round(u * 100 / t)
                if 0 <= pct <= 100:
                    pcts.append(pct)
        if pcts:
            result["weekly_pct"]  = pcts[0]
            result["session_pct"] = pcts[1] if len(pcts) > 1 else None
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# JSON / text parsing

def _parse_json_or_text(body: str) -> dict:
    result = {"weekly_pct": None, "session_pct": None, "session_reset_at": None}

    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return _parse_text(body)

    if isinstance(data, list):
        for item in data:
            sub = _parse_json_or_text(json.dumps(item))
            if sub.get("weekly_pct") is not None:
                return sub
        return result

    if not isinstance(data, dict):
        return _parse_text(body)

    # 1. Claude.ai /usage format: limits[].{group/kind, percent}
    r = _parse_limits_array(data)
    if r["weekly_pct"] is not None or r["session_pct"] is not None:
        return r

    # 2. Claude.ai /usage format: five_hour.utilization / seven_day.utilization
    r = _parse_utilization(data)
    if r["weekly_pct"] is not None or r["session_pct"] is not None:
        return r

    # 3. Direct percentage fields
    for key in ("weekly_pct", "weekly", "week", "wochentlich", "weekly_usage"):
        val = _dig(data, key)
        if isinstance(val, (int, float)) and 0 <= val <= 100:
            result["weekly_pct"] = int(round(val))
            break

    for key in ("session_pct", "session", "conversation", "konversation", "session_usage"):
        val = _dig(data, key)
        if isinstance(val, (int, float)) and 0 <= val <= 100:
            result["session_pct"] = int(round(val))
            break

    # 4. used/remaining + limit pairs
    if result["weekly_pct"] is None:
        pcts = _find_pct_pairs(data)
        if pcts:
            result["weekly_pct"]  = pcts[0]
            result["session_pct"] = pcts[1] if len(pcts) > 1 else None

    return result


def _parse_limits_array(data: dict) -> dict:
    """Claude.ai /usage endpoint: limits[].{group, kind, percent, resets_at}"""
    result = {"weekly_pct": None, "session_pct": None, "session_reset_at": None}
    limits = data.get("limits")
    if not isinstance(limits, list):
        return result
    for item in limits:
        if not isinstance(item, dict):
            continue
        if item.get("scope"):
            continue  # per-model limit (e.g. weekly_scoped for one model), not the aggregate
        pct = item.get("percent")
        if not isinstance(pct, (int, float)) or not (0 <= pct <= 100):
            continue
        group = str(item.get("group", "")).lower()
        kind  = str(item.get("kind",  "")).lower()
        if "weekly" in group or "weekly" in kind or "seven" in kind:
            result["weekly_pct"] = int(round(pct))
        elif "session" in group or "session" in kind or "hour" in kind or "five" in kind:
            result["session_pct"] = int(round(pct))
            result["session_reset_at"] = item.get("resets_at")
    return result


def _parse_utilization(data: dict) -> dict:
    """Claude.ai /usage endpoint: five_hour.utilization / seven_day.utilization"""
    result = {"weekly_pct": None, "session_pct": None, "session_reset_at": None}
    fh = data.get("five_hour")
    if isinstance(fh, dict):
        u = fh.get("utilization")
        if isinstance(u, (int, float)) and 0 <= u <= 100:
            result["session_pct"] = int(round(u))
            result["session_reset_at"] = fh.get("resets_at")
    sd = data.get("seven_day")
    if isinstance(sd, dict):
        u = sd.get("utilization")
        if isinstance(u, (int, float)) and 0 <= u <= 100:
            result["weekly_pct"] = int(round(u))
    return result


def _dig(obj, key: str):
    """Case-insensitive recursive key search."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if key.lower() in k.lower():
                return v
            sub = _dig(v, key)
            if sub is not None:
                return sub
    elif isinstance(obj, list):
        for item in obj:
            sub = _dig(item, key)
            if sub is not None:
                return sub
    return None


def _find_pct_pairs(data) -> list:
    text = json.dumps(data)
    pcts = []

    # Pattern A: used/count/current + limit/total/max
    pat_a = re.compile(
        r'"(?:used|count|current|consumed|messages_used)"\s*:\s*(\d+(?:\.\d+)?)'
        r'.{0,300}?'
        r'"(?:limit|total|max|maximum|allowed|messages_limit|message_limit)"\s*:\s*(\d+(?:\.\d+)?)',
        re.DOTALL,
    )
    for m in pat_a.finditer(text):
        used, total = float(m.group(1)), float(m.group(2))
        if total > 0:
            pct = round(used * 100 / total)
            if 0 <= pct <= 100:
                pcts.append(pct)

    # Pattern B: remaining + limit/total (invert: pct = 1 - remaining/limit)
    pat_b = re.compile(
        r'"(?:remaining|left|available)"\s*:\s*(\d+(?:\.\d+)?)'
        r'.{0,300}?'
        r'"(?:limit|total|max|maximum|allowed)"\s*:\s*(\d+(?:\.\d+)?)',
        re.DOTALL,
    )
    for m in pat_b.finditer(text):
        remaining, total = float(m.group(1)), float(m.group(2))
        if total > 0 and remaining <= total:
            pct = round((total - remaining) * 100 / total)
            if 0 <= pct <= 100:
                pcts.append(pct)

    # Pattern C: limit + remaining (reversed order in JSON)
    pat_c = re.compile(
        r'"(?:limit|total|max|maximum|allowed)"\s*:\s*(\d+(?:\.\d+)?)'
        r'.{0,300}?'
        r'"(?:remaining|left|available)"\s*:\s*(\d+(?:\.\d+)?)',
        re.DOTALL,
    )
    for m in pat_c.finditer(text):
        total, remaining = float(m.group(1)), float(m.group(2))
        if total > 0 and remaining <= total:
            pct = round((total - remaining) * 100 / total)
            if 0 <= pct <= 100:
                pcts.append(pct)

    # Deduplicate preserving order
    seen, unique = set(), []
    for p in pcts:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique[:2]


def _parse_text(text: str) -> dict:
    result = {"weekly_pct": None, "session_pct": None}
    for label_re, key in [
        (r"(?:Weekly|Wöchentlich)\D{0,80}?(\d+)\s*%", "weekly_pct"),
        (r"(?:Session|Sitzung)\D{0,80}?(\d+)\s*%",    "session_pct"),
    ]:
        m = re.search(label_re, text, re.IGNORECASE)
        if m:
            result[key] = int(m.group(1))
    if result["weekly_pct"] is None:
        nums = re.findall(r"(\d+)\s*%", text)
        if nums:
            result["weekly_pct"]  = int(nums[0])
            result["session_pct"] = int(nums[1]) if len(nums) > 1 else None
    return result


# ---------------------------------------------------------------------------
# Worker thread

class FetchWorker(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="FetchWorker")
        self._q    = queue.Queue()
        self._resp = queue.Queue()

    def run(self):
        while True:
            op = self._q.get()
            if op == "STOP":
                break
            if op != "USAGE":
                continue

            # Try curl first (fast, no browser)
            try:
                data = _fetch_usage_curl()
                if data.get("weekly_pct") is not None or data.get("session_pct") is not None:
                    self._resp.put(("OK", data))
                    continue
            except Exception:
                pass

            # Fallback: Playwright headless
            try:
                data = _fetch_usage_playwright()
                if data.get("weekly_pct") is not None or data.get("session_pct") is not None:
                    self._resp.put(("OK", data))
                else:
                    self._resp.put(("ERR", "Keine Nutzungsdaten — debug pruefen"))
            except Exception as e:
                self._resp.put(("ERR", str(e)))

    def get_usage(self, timeout=90):
        self._q.put("USAGE")
        try:
            status, result = self._resp.get(timeout=timeout)
            return result if status == "OK" else None
        except queue.Empty:
            return None

    def stop(self):
        self._q.put("STOP")


# ---------------------------------------------------------------------------
# Icon rendering

WHITE  = (255, 255, 255)
BLACK  = (0, 0, 0)
RED    = (220, 60, 60)
BLUE   = (30, 90, 200)

def _load_font(size):
    for path in [r"C:\Windows\Fonts\arialbd.ttf",
                 r"C:\Windows\Fonts\arial.ttf",
                 r"C:\Windows\Fonts\segoeui.ttf"]:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()

_FONT_CACHE: dict = {}

def _font(size: int):
    if size not in _FONT_CACHE:
        _FONT_CACHE[size] = _load_font(size)
    return _FONT_CACHE[size]

def _text_centered(draw, cx, cy, text, fill, font):
    """Draw text centered at (cx, cy); compatible with TrueType and bitmap fonts."""
    try:
        draw.text((cx, cy), text, fill=fill, font=font, anchor="mm")
    except (ValueError, TypeError):
        try:
            bb = draw.textbbox((0, 0), text, font=font)
            w, h = bb[2] - bb[0], bb[3] - bb[1]
            draw.text((cx - w // 2, cy - h // 2 - bb[1]), text, fill=fill, font=font)
        except Exception:
            draw.text((max(0, cx - len(text) * 4), max(0, cy - 8)), text, fill=fill, font=font)


def _text_two_lines(draw, cx, cy, top, bottom, fill, font, gap=2):
    """Draw two centered lines stacked vertically around (cx, cy)."""
    try:
        bb = draw.textbbox((0, 0), top, font=font)
        line_h = bb[3] - bb[1]
    except Exception:
        line_h = 20
    offset = line_h // 2 + gap
    _text_centered(draw, cx, cy - offset, top, fill, font)
    _text_centered(draw, cx, cy + offset, bottom, fill, font)


def make_icon(pct, error=False):
    S    = ICON_SIZE
    img  = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    bg   = RED if error else WHITE
    text = WHITE if error else BLACK

    try:
        draw.rounded_rectangle([0, 0, S - 1, S - 1], radius=10, fill=bg)
    except AttributeError:
        draw.rectangle([0, 0, S - 1, S - 1], fill=bg)

    cx = cy = S // 2

    if error:
        _text_centered(draw, cx, cy, "!", text, _font(48))
        return img

    txt = f"{pct}" if pct is not None else "?"
    num_size = 50 if len(txt) <= 2 else 38
    _text_centered(draw, cx, cy, txt, text, _font(num_size))

    return img


def _reset_parts(reset_at_iso):
    """'2026-07-05T20:49:59+00:00' -> (hours, minutes) remaining until reset."""
    if not reset_at_iso:
        return None
    try:
        reset_dt = datetime.fromisoformat(reset_at_iso)
        now = datetime.now(timezone.utc)
        total_min = max(0, int((reset_dt - now).total_seconds() // 60))
        return divmod(total_min, 60)
    except Exception:
        return None


def _make_reset_tile(text_value, error=False):
    S    = ICON_SIZE
    img  = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    bg   = RED if error else BLUE
    text = WHITE

    try:
        draw.rounded_rectangle([0, 0, S - 1, S - 1], radius=10, fill=bg)
    except AttributeError:
        draw.rectangle([0, 0, S - 1, S - 1], fill=bg)

    cx = cy = S // 2

    if error:
        _text_centered(draw, cx, cy, "!", text, _font(48))
        return img

    if text_value is None:
        _text_centered(draw, cx, cy, "?", text, _font(40))
        return img

    num_size = 50 if len(text_value) <= 2 else 38
    _text_centered(draw, cx, cy, text_value, text, _font(num_size))

    return img


def make_reset_hour_icon(reset_at_iso, error=False):
    parts = _reset_parts(reset_at_iso)
    return _make_reset_tile(str(parts[0]) if parts else None, error=error)


def make_reset_minute_icon(reset_at_iso, error=False):
    parts = _reset_parts(reset_at_iso)
    return _make_reset_tile(f"{parts[1]:02d}" if parts else None, error=error)


# ---------------------------------------------------------------------------
# Tray app

class ClaudeUsageTray:
    def __init__(self):
        self.s          = load_settings()
        self.icon       = None
        self.icon_hour  = None
        self.icon_min   = None
        self._fw        = None
        self._stop      = threading.Event()
        self._relogin   = threading.Event()
        self._fetch_lock = threading.Lock()

    def _start_worker(self):
        self._fw = FetchWorker()
        self._fw.start()

    def _stop_worker(self):
        if self._fw:
            self._fw.stop()
            self._fw = None

    def _fetch(self):
        if not self._fw:
            return
        if not self._fetch_lock.acquire(blocking=False):
            return  # Fetch already running
        try:
            data = self._fw.get_usage(timeout=90)
            has_cached = self.s.get("weekly_pct") is not None
            last_ts    = (self.s.get("last_fetched") or "")[:16]

            if data is None:
                if has_cached:
                    self.s["last_error"] = f"Aktualisierung fehlgeschlagen (Stand: {last_ts})"
                else:
                    self.s["last_error"] = "Fetch fehlgeschlagen — debug pruefen"
                save_settings(self.s)
                self._refresh_icon()
                return

            wp = data.get("weekly_pct")
            sp = data.get("session_pct")
            if wp is None and sp is None:
                if has_cached:
                    self.s["last_error"] = f"Keine neuen Daten (Stand: {last_ts})"
                else:
                    self.s["last_error"] = "Keine Nutzungsdaten — debug pruefen"
                save_settings(self.s)
                self._refresh_icon()
                return

            self.s.update({
                "weekly_pct":   wp,
                "session_pct":  sp,
                "session_reset_at": data.get("session_reset_at"),
                "last_fetched": datetime.now(timezone.utc).isoformat(timespec="minutes"),
                "last_error":   None,
            })
            save_settings(self.s)
            self._refresh_icon()
        finally:
            self._fetch_lock.release()

    def _refresh_icon(self):
        if not self.icon:
            return
        sp  = self.s.get("session_pct")
        err = bool(self.s.get("last_error"))

        self.icon.icon = make_icon(sp, error=err)

        if err:
            self.icon.title = f"Claude Usage — {self.s['last_error']}"
        else:
            ts = self.s.get("last_fetched", "—")
            self.icon.title = f"Session: {sp if sp is not None else '?'}%\nStand: {ts}"

        self._refresh_reset_icons()

    def _refresh_reset_icons(self):
        reset_at = self.s.get("session_reset_at")
        err      = bool(self.s.get("last_error")) and not reset_at
        parts    = _reset_parts(reset_at)
        title    = f"Session Reset in {parts[0]}h {parts[1]:02d}min" if parts else "Reset — keine Daten"

        if self.icon_hour:
            self.icon_hour.icon  = make_reset_hour_icon(reset_at, error=err)
            self.icon_hour.title = title
        if self.icon_min:
            self.icon_min.icon  = make_reset_minute_icon(reset_at, error=err)
            self.icon_min.title = title

    def _on_refresh(self, *_):
        threading.Thread(target=self._fetch, daemon=True).start()

    def _on_relogin(self, *_):
        self._relogin.set()

    def _on_open(self, *_):
        subprocess.Popen(
            ["cmd", "/c", "start", USAGE_URL],
            creationflags=_NO_WINDOW,
        )

    def _on_debug(self, *_):
        if os.path.exists(DEBUG_PATH):
            subprocess.Popen(["notepad.exe", DEBUG_PATH], creationflags=_NO_WINDOW)

    def _on_quit(self, icon, item):
        self._stop.set()
        self._stop_worker()
        if self.icon:
            self.icon.stop()
        if self.icon_hour:
            self.icon_hour.stop()
        if self.icon_min:
            self.icon_min.stop()

    def _loop(self):
        """Background thread: login + periodic fetch. Restarts after exceptions."""
        while not self._stop.is_set():
            try:
                self._relogin.clear()

                if not api_cfg_valid():
                    self.s["last_error"] = "Bitte einloggen..."
                    self._refresh_icon()
                    if not do_login():
                        self.s["last_error"] = "Login abgebrochen"
                        self._refresh_icon()
                        self._stop.wait(60)
                        continue
                    self.s["last_error"] = None

                self._start_worker()
                while not self._stop.is_set() and not self._relogin.is_set():
                    self._fetch()
                    self._relogin.wait(timeout=REFRESH_SEC)
                self._stop_worker()
            except Exception as e:
                self.s["last_error"] = f"Interner Fehler: {e}"
                save_settings(self.s)
                try:
                    with open(DEBUG_PATH, "a", encoding="utf-8") as _f:
                        _f.write(f"\n=== EXCEPTION {datetime.now().isoformat()} ===\n")
                        _f.write(traceback.format_exc())
                except Exception:
                    pass
                self._stop_worker()
                self._refresh_icon()
                self._stop.wait(30)

    def run(self):
        _log("run: make_icon")
        img      = make_icon(self.s.get("session_pct"))
        reset_at = self.s.get("session_reset_at")
        img_hour = make_reset_hour_icon(reset_at)
        img_min  = make_reset_minute_icon(reset_at)
        _log("run: menu")
        menu = pystray.Menu(
            pystray.MenuItem("Aktualisieren",    self._on_refresh, default=True),
            pystray.MenuItem("Claude oeffnen",   self._on_open),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Erneut einloggen", self._on_relogin),
            pystray.MenuItem("Debug-Datei",      self._on_debug),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Beenden",          self._on_quit),
        )
        _log("run: pystray.Icon()")
        self.icon      = pystray.Icon(APP_NAME, img, APP_NAME, menu)
        self.icon_hour = pystray.Icon(APP_NAME_RESET + " Std", img_hour, APP_NAME_RESET + " Std", menu)
        self.icon_min  = pystray.Icon(APP_NAME_RESET + " Min", img_min, APP_NAME_RESET + " Min", menu)
        _log("run: calling icon.run()")

        def _on_ready_hour(icon):
            icon.visible = True
            self._refresh_reset_icons()

        def _on_ready_min(icon):
            icon.visible = True
            self._refresh_reset_icons()

        threading.Thread(
            target=self.icon_hour.run,
            kwargs={"setup": _on_ready_hour},
            daemon=True,
        ).start()

        threading.Thread(
            target=self.icon_min.run,
            kwargs={"setup": _on_ready_min},
            daemon=True,
        ).start()

        def _on_ready(icon):
            _log("_on_ready: setting visible")
            icon.visible = True
            _log("_on_ready: visible set, refreshing")
            self._refresh_icon()
            _log("_on_ready: done, starting loop")
            threading.Thread(target=self._loop, daemon=True).start()

        self.icon.run(setup=_on_ready)
        _log("run: icon.run() returned")


_LOG_PATH = str(Path.home() / ".claude_tray_launch.log")

def _log(msg):
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()} {msg}\n")
    except Exception:
        pass


if __name__ == "__main__":
    open(_LOG_PATH, "w").close()  # reset log each run
    _log("__main__: start")
    try:
        ClaudeUsageTray().run()
        _log("__main__: run() returned normally")
    except Exception:
        msg = traceback.format_exc()
        _log(f"__main__: CRASH\n{msg}")
        _show_error("Claude Usage - Absturz", msg)
