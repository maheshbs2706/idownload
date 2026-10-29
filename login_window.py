"""In-app YouTube/Google sign-in. Run as a separate process (webview needs the main thread):

    app.py --login <cookies_out.txt> <webview_storage_dir>

Opens a sign-in window, waits until the account is signed in on youtube.com, then writes the
session cookies in Netscape cookies.txt format (what yt-dlp reads) and closes itself.
Diagnostics go to <webview_storage_dir>\\login.log.
"""
import os
import sys
import threading
import time
import traceback
from email.utils import parsedate_to_datetime

import webview

SIGN_IN = "https://accounts.google.com/ServiceLogin?service=youtube&continue=https%3A%2F%2Fwww.youtube.com%2F"
# Cookies Google sets only for a signed-in session
AUTH_COOKIES = {"SID", "SSID", "HSID", "APISID", "SAPISID", "LOGIN_INFO", "__Secure-1PSID", "__Secure-3PSID",
                "__Secure-1PAPISID", "__Secure-3PAPISID"}
FAR_FUTURE = 2147483647


def flatten(cookies):
    """webview's get_cookies() returns SimpleCookie objects; yield (name, Morsel) pairs."""
    for sc in cookies:
        yield from sc.items()


def expiry(morsel):
    raw = morsel["expires"]
    try:
        ts = int(parsedate_to_datetime(raw).timestamp()) if raw else 0
    except (TypeError, ValueError):
        ts = 0
    # session cookies come back with a bogus past date (e.g. 2001); the browser wouldn't return a truly expired one
    return ts if ts > time.time() else FAR_FUTURE


def write_netscape(cookies, path):
    lines = ["# Netscape HTTP Cookie File", "# Written by iDownload", ""]
    for name, m in flatten(cookies):
        domain = m["domain"] or ""
        lines.append("\t".join([
            ("#HttpOnly_" if m["httponly"] else "") + domain,
            "TRUE" if domain.startswith(".") else "FALSE",
            m["path"] or "/",
            "TRUE" if m["secure"] else "FALSE",
            str(expiry(m)),
            name,
            m.value or "",
        ]))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def run(cookie_path, storage_dir):
    os.makedirs(storage_dir, exist_ok=True)
    log_path = os.path.join(storage_dir, "login.log")

    def log(msg):
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")

    open(log_path, "w").close()
    window = webview.create_window("Sign in to YouTube", SIGN_IN, width=520, height=760)
    closed = threading.Event()
    window.events.closed += closed.set
    result = {"ok": False}

    def watch():
        time.sleep(2)
        while not closed.is_set():
            try:
                url = window.get_current_url() or ""
                host = url.split("/")[2] if "://" in url else ""
                # Signed in = back on a youtube.com page (not the accounts.google.com sign-in flow)
                if host.endswith("youtube.com"):
                    cookies = window.get_cookies()
                    names = {n for n, _ in flatten(cookies)}
                    log(f"on {host}: {len(names)} cookies, auth={sorted(names & AUTH_COOKIES)}")
                    if names & AUTH_COOKIES:
                        write_netscape(cookies, cookie_path)
                        result["ok"] = True
                        log("saved; closing")
                        window.destroy()
                        return
                else:
                    log(f"on {host or url[:40]}")
            except Exception:
                log("watch error:\n" + traceback.format_exc())  # keep trying; never give up silently
            time.sleep(1.5)

    # Keep the session so a later "Re-sign in" is one click
    webview.start(watch, private_mode=False, storage_path=os.path.join(storage_dir, "profile"))
    sys.exit(0 if result["ok"] else 1)
