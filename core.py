"""Download engine: Google Drive, yt-dlp sites (YouTube etc.) and direct files/images.

Every entry point reports through cb(pct, text, name): pct is 0-100 or None (indeterminate),
text is a short status line, name is the file name once known (else None).
"""
import os
import re
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import unquote, urlparse

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
SEGMENTS = 8            # parallel connections per direct file
MIN_SPLIT = 4 << 20     # don't split files under 4 MB
RETRIES = 6
DRIVE_HOSTS = ("drive.google.com", "docs.google.com")
HLS_DASH = ("application/vnd.apple.mpegurl", "application/x-mpegurl", "application/dash+xml")
DRIVE_WORKERS = 4       # files downloaded at once inside a Drive folder (set from the Settings page)
QUALITIES =["Best", "1080p", "720p", "Audio (MP3)"]


class Cancelled(Exception):
    pass


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def human_eta(s):
    s = int(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def ffmpeg_dir():
    """Folder holding ffmpeg: bundled next to the exe when frozen, else None (use PATH)."""
    base = getattr(sys, "_MEIPASS", None)
    return base if base and os.path.exists(os.path.join(base, "ffmpeg.exe")) else None


class Meter:
    """Thread-safe byte counter that turns raw progress into throttled UI updates."""

    def __init__(self, total, cb, name, cancel):
        self.total, self.cb, self.name, self.cancel = total, cb, name, cancel
        self.done, self.t0, self.last = 0, time.time(), 0.0
        self.lock = threading.Lock()

    def add(self, n):
        if self.cancel.is_set():
            raise Cancelled()
        with self.lock:
            self.done += n
            now = time.time()
            if now - self.last < 0.1:
                return
            self.last = now
            speed = self.done / max(now - self.t0, 0.001)
            if self.total:
                eta = (self.total - self.done) / speed if speed else 0
                self.cb(self.done / self.total * 100,
                        f"{human(self.done)} / {human(self.total)} · {human(speed)}/s · {human_eta(eta)} left",
                        self.name)
            else:
                self.cb(None, f"{human(self.done)} · {human(speed)}/s", self.name)


# ---------- Google Drive ----------
def get_drive(url, out_dir, cb, cancel):
    import gdown
    cb(None, "Contacting Google Drive…", None)
    if "/folders/" in url:
        return get_drive_folder(url, out_dir, cb, cancel)
    meter = {}

    def progress(done, total):
        m = meter.get("m")
        if m is None:
            m = meter["m"] = Meter(total, cb, None, cancel)
        m.add(done - m.done)

    # fuzzy=True pulls the file id out of any share-link format; gdown handles the virus-scan confirm page
    path = gdown.download(url=url, output=os.path.join(out_dir, ""), quiet=True, fuzzy=True, resume=True,
                          progress=progress, cancel=cancel)
    if cancel.is_set():
        raise Cancelled()
    if not path:
        raise RuntimeError("Drive refused the download (not shared as 'Anyone with the link', or quota exceeded)")
    cb(100, "Saved", os.path.basename(path))


def get_drive_folder(url, out_dir, cb, cancel):
    import gdown
    files = gdown.download_folder(url=url, quiet=True, skip_download=True)
    if not files:
        raise RuntimeError("Folder is empty or not shared as 'Anyone with the link'")
    # With no output given, gdown roots paths at ./<folder name>; recover that name and re-root under out_dir.
    root = files[0].local_path[:-len(files[0].path)].rstrip("\\/")
    name = os.path.basename(root)
    total, state, lock, t0 = len(files), {"done": 0, "failed": 0}, threading.Lock(), time.time()
    cb(0, f"0 / {total} files", name)

    def fetch(f):
        dest = os.path.join(out_dir, name, *f.path.split("/"))
        ok = os.path.exists(dest)  # finished earlier (gdown renames only on completion)
        if not ok:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            for _ in range(3):
                if cancel.is_set():
                    return
                try:
                    ok = bool(gdown.download(id=f.id, output=dest, quiet=True, resume=True, cancel=cancel))
                except Exception:
                    ok = False
                if ok:
                    break
        if cancel.is_set():
            return
        with lock:
            state["done" if ok else "failed"] += 1
            n = state["done"] + state["failed"]
            rate = n / max(time.time() - t0, 0.001)
            cb(n / total * 100, f"{n} / {total} files · {human_eta((total - n) / rate)} left", name)

    with ThreadPoolExecutor(max(1, DRIVE_WORKERS)) as ex:
        list(ex.map(fetch, files))
    if cancel.is_set():
        raise Cancelled()
    if state["failed"]:
        raise RuntimeError(f"{state['failed']} of {total} files failed (Drive quota or permissions); run again to retry them")
    cb(100, f"Saved {total} files", name)


# ---------- yt-dlp (YouTube + ~1800 sites) ----------
class _Quiet:
    def debug(self, m): pass
    def info(self, m): pass
    def warning(self, m): pass
    def error(self, m): pass


def js_runtimes():
    """JavaScript runtimes yt-dlp can use to solve YouTube's challenges (without one, only thumbnails are offered).

    yt-dlp only auto-enables deno, so enable whichever is present: bundled node (exe build), then PATH.
    """
    found = {}
    bundled = os.path.join(getattr(sys, "_MEIPASS", ""), "node.exe")
    if os.path.exists(bundled):
        found["node"] = {"path": bundled}
    for name in ("deno", "node", "bun"):
        path = shutil.which(name)
        if path and name not in found:
            found[name] = {"path": path}
    return found


def get_media(url, out_dir, quality, cb, cancel, cookies=None):
    import yt_dlp
    fmt = {
        "Best": "bv*+ba/b",
        "1080p": "bv*[height<=1080]+ba/b[height<=1080]",
        "720p": "bv*[height<=720]+ba/b[height<=720]",
        "Audio (MP3)": "ba/b",
    }[quality]
    state = {"name": None}

    def hook(d):
        if cancel.is_set():
            raise Cancelled()
        state["name"] = os.path.basename(d.get("filename", "") or "") or state["name"]
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes", 0)
            speed, eta = d.get("speed"), d.get("eta")
            bits = [f"{human(done)}" + (f" / {human(total)}" if total else "")]
            if speed:
                bits.append(f"{human(speed)}/s")
            if eta is not None:
                bits.append(f"{human_eta(eta)} left")
            cb(done / total * 100 if total else None, " · ".join(bits), state["name"])
        elif d["status"] == "finished":
            cb(100, "Processing…", state["name"])

    opts = {
        "format": fmt,
        "outtmpl": os.path.join(out_dir, "%(title).150B [%(id)s].%(ext)s"),
        "concurrent_fragment_downloads": 8,
        "retries": RETRIES,
        "fragment_retries": RETRIES,
        "continuedl": True,
        "windowsfilenames": True,
        "noplaylist": True,
        "quiet": True,
        "noprogress": True,
        "logger": _Quiet(),
        "progress_hooks": [hook],
    }
    runtimes = js_runtimes()
    if runtimes:
        opts["js_runtimes"] = runtimes
    if cookies:  # ("browser", "firefox") or ("file", "C:\\path\\cookies.txt")
        kind, value = cookies
        opts["cookiesfrombrowser" if kind == "browser" else "cookiefile"] = (value,) if kind == "browser" else value
    ff = ffmpeg_dir()
    if ff:
        opts["ffmpeg_location"] = ff
    if quality == "Audio (MP3)":
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}]
    else:
        opts["merge_output_format"] = "mp4"
    cb(None, "Fetching video info…", None)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as e:
        if cancel.is_set():
            raise Cancelled()
        msg = re.sub(r"\x1b\[[0-9;]*m|^ERROR: ", "", str(e)).strip()
        if re.search(r"not a bot|429|too many requests", msg, re.I):
            msg = ("YouTube is rate-limiting/bot-checking this connection (usually temporary). Wait a while, "
                   "or set 'Login' below to your browser or a cookies.txt file.")
        elif re.search(r"confirm your age|age-restricted|Sign in to confirm|login required|private video", msg, re.I):
            msg = ("Needs a signed-in account (age-restricted/private). Set 'Login' below to your browser "
                   "or a cookies.txt file. " + (f"[{cookies[1]}]" if cookies else ""))
        elif re.search(r"requested format is not available|only images are available", msg, re.I) and not runtimes:
            msg = ("YouTube needs a JavaScript runtime to unlock the video/audio formats. Install Node.js "
                   "(nodejs.org) or Deno (winget install DenoLand.Deno), then restart iDownload.")
        elif cookies and cookies[0] == "browser" and re.search(r"cookie|DPAPI|decrypt|database", msg, re.I):
            msg = (f"Couldn't read {cookies[1]} cookies (close the browser first; Chrome/Edge often block this - "
                   "try Firefox or a cookies.txt file). ") + msg[:80]
        raise RuntimeError(msg)
    title = (info or {}).get("title")
    cb(100, "Saved", title or state["name"])


# ---------- direct files / images ----------
def filename_for(url, resp):
    cd = resp.headers.get("content-disposition", "")
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd) or re.search(r'filename="?([^";]+)"?', cd)
    name = unquote(m.group(1)) if m else unquote(os.path.basename(urlparse(url).path)) or "download"
    return re.sub(r'[<>:"/\\|?*]', "_", name)


def probe(url):
    """Return (final_url, size, accepts_ranges, name, content_type)."""
    r = requests.get(url, headers={**UA, "Range": "bytes=0-0"}, stream=True, allow_redirects=True, timeout=30)
    if r.status_code >= 400:  # some hosts reject Range probes; retry plainly
        r.close()
        r = requests.get(url, headers=UA, stream=True, allow_redirects=True, timeout=30)
    try:
        r.raise_for_status()
        ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
        if r.status_code == 206:
            size, ranges = int(r.headers["content-range"].rsplit("/", 1)[1]), True
        else:
            size, ranges = int(r.headers.get("content-length", 0)), False
        return r.url, size, ranges, filename_for(url, r), ctype
    finally:
        r.close()


def fetch_segment(url, path, start, end, meter):
    """Download bytes [start, end] into path, resuming from the last good byte on failure."""
    pos = start
    for attempt in range(RETRIES):
        try:
            with requests.get(url, headers={**UA, "Range": f"bytes={pos}-{end}"}, stream=True, timeout=30) as r:
                if r.status_code != 206:
                    raise IOError(f"server ignored range (HTTP {r.status_code})")
                with open(path, "r+b") as f:
                    f.seek(pos)
                    for chunk in r.iter_content(1 << 17):
                        f.write(chunk)
                        pos += len(chunk)
                        meter.add(len(chunk))
            if pos > end:
                return
        except Cancelled:
            raise
        except (requests.RequestException, IOError):
            time.sleep(min(2 ** attempt, 15))
    raise RuntimeError("connection kept failing; try again later")


def get_direct(out_dir, probed, cb, cancel):
    url, size, ranges, name, _ = probed
    dest = os.path.join(out_dir, name)
    if os.path.exists(dest) and (not size or os.path.getsize(dest) == size):
        cb(100, "Already downloaded", name)
        return
    part = dest + ".part"
    meter = Meter(size, cb, name, cancel)
    cb(0 if size else None, "Starting…", name)
    try:
        if ranges and size >= MIN_SPLIT:
            with open(part, "wb") as f:
                f.truncate(size)
            step = -(-size // SEGMENTS)
            spans = [(s, min(s + step, size) - 1) for s in range(0, size, step)]
            with ThreadPoolExecutor(len(spans)) as ex:
                futs = [ex.submit(fetch_segment, url, part, s, e, meter) for s, e in spans]
                try:
                    for fu in futs:
                        fu.result()
                except BaseException:
                    cancel.set()  # stop sibling segments
                    raise
        else:
            for attempt in range(RETRIES):
                try:
                    done = os.path.getsize(part) if os.path.exists(part) else 0
                    h = {**UA, **({"Range": f"bytes={done}-"} if done and ranges else {})}
                    with requests.get(url, headers=h, stream=True, timeout=30) as r:
                        r.raise_for_status()
                        if done and r.status_code != 206:
                            done = 0
                        meter.done = done
                        with open(part, "ab" if done else "wb") as f:
                            for chunk in r.iter_content(1 << 17):
                                f.write(chunk)
                                meter.add(len(chunk))
                    break
                except requests.RequestException:
                    if attempt == RETRIES - 1:
                        raise
                    time.sleep(min(2 ** attempt, 15))
        if size and os.path.getsize(part) != size:
            raise RuntimeError("size mismatch after download")
    except Cancelled:
        if os.path.exists(part):
            os.remove(part)
        raise
    os.replace(part, dest)
    cb(100, f"Saved · {human(os.path.getsize(dest))}", name)


# ---------- dispatch ----------
def download(url, out_dir, quality, cb, cancel, cookies=None):
    os.makedirs(out_dir, exist_ok=True)
    if urlparse(url).netloc.lower().endswith(DRIVE_HOSTS):
        return get_drive(url, out_dir, cb, cancel)
    cb(None, "Checking link…", None)
    try:
        probed = probe(url)
    except requests.RequestException:
        probed = None
    if probed and not probed[4].startswith("text/html") and probed[4] not in HLS_DASH:
        return get_direct(out_dir, probed, cb, cancel)  # real file: image, mp4, zip, ...
    return get_media(url, out_dir, quality, cb, cancel, cookies)  # page or stream manifest
