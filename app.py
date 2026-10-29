import json
import os
import queue
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from tkinter import filedialog

import customtkinter as ctk
from PIL import Image

import core
from version import __version__

# Windowed (no-console) builds have no stdout/stderr; libraries that print would crash.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

APP = "iDownload"
ACCENT = ("#6A4DF4", "#6E56FA")
ACCENT_HOVER = ("#5A3DE0", "#8470FF")
ACCENT_TEXT = ("#5B3FE6", "#8F7BFF")
SIDEBAR = ("#FFFFFF", "#0D0D15")
BG = ("#F4F5FA", "#10101A")
CARD = ("#FFFFFF", "#171724")
FIELD = ("#EEF0F8", "#1E1E2E")
BORDER = ("#DADCE8", "#2A2A3D")
TEXT = ("#15151F", "#F2F2F8")
MUTED = ("#6B6F80", "#9094A8")
SOFT_BTN = ("#E6E8F3", "#262638")
SOFT_HOVER = ("#D8DBEB", "#31314A")
OK, ERR = "#22C55E", "#EF4444"
SETTINGS = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP, "settings.json")
MAX_PARALLEL = 6
LOGIN_APP = "Sign in here (in-app)"
LOGIN_FILE = "cookies.txt file…"
LOGIN_CHOICES = ["No login", LOGIN_APP, "Firefox", "Edge", "Chrome", "Brave", LOGIN_FILE]
DATA_DIR = os.path.dirname(SETTINGS)
APP_COOKIES = os.path.join(DATA_DIR, "youtube_cookies.txt")
WEBVIEW_DIR = os.path.join(DATA_DIR, "webview")
NAV = [("home", "⌂", "Home"), ("downloads", "⬇", "Downloads"), ("settings", "⚙", "Settings"), ("about", "ⓘ", "About")]


def load_settings():
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(s):
    try:
        os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
        with open(SETTINGS, "w", encoding="utf-8") as f:
            json.dump(s, f)
    except OSError:
        pass


def resource(path):
    return os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), path)


def open_folder(path):
    if os.path.isdir(path):
        subprocess.Popen(["explorer", os.path.normpath(path)])


def font(size=13, bold=False):
    return ctk.CTkFont(family="Segoe UI", size=size, weight="bold" if bold else "normal")


class Limiter:
    """Adjustable cap on how many downloads run at once."""

    def __init__(self, n):
        self.n, self.active, self.cv = n, 0, threading.Condition()

    def acquire(self, cancel):
        with self.cv:
            while self.active >= self.n:
                if cancel.is_set():
                    return False
                self.cv.wait(0.2)
            self.active += 1
            return True

    def release(self):
        with self.cv:
            self.active -= 1
            self.cv.notify_all()

    def set(self, n):
        with self.cv:
            self.n = n
            self.cv.notify_all()


class JobCard(ctk.CTkFrame):
    def __init__(self, master, url, out_dir, on_cancel, on_remove):
        super().__init__(master, fg_color=CARD, corner_radius=14, border_width=1, border_color=BORDER)
        self.url, self.done, self.on_remove, self.indeterminate = url, False, on_remove, False
        self.out_dir = out_dir
        self.grid_columnconfigure(1, weight=1)
        self.badge = ctk.CTkLabel(self, text=self._glyph(url), width=44, height=44, corner_radius=12,
                                  fg_color=FIELD, text_color=ACCENT_TEXT, font=font(18, True))
        self.badge.grid(row=0, column=0, rowspan=4, padx=(14, 12), pady=14)
        self.title = ctk.CTkLabel(self, text=url, anchor="w", text_color=TEXT, font=font(14, True))
        self.title.grid(row=0, column=1, sticky="ew", pady=(12, 0))
        self.path = ctk.CTkLabel(self, text="📁 " + os.path.normpath(out_dir), anchor="w", text_color=ACCENT_TEXT,
                                 font=font(11))
        self.path.grid(row=1, column=1, sticky="ew")
        self.status = ctk.CTkLabel(self, text="Queued", anchor="w", text_color=MUTED, font=font(12))
        self.status.grid(row=2, column=1, sticky="ew")
        self.bar = ctk.CTkProgressBar(self, height=7, progress_color=ACCENT, fg_color=FIELD)
        self.bar.set(0)
        self.bar.grid(row=3, column=1, sticky="ew", pady=(6, 14))
        self.btns = ctk.CTkFrame(self, fg_color="transparent")
        self.btns.grid(row=0, column=2, rowspan=4, padx=14)
        self.cancel_btn = ctk.CTkButton(self.btns, text="Cancel", width=84, height=32, corner_radius=9,
                                        fg_color=SOFT_BTN, hover_color=SOFT_HOVER, text_color=TEXT,
                                        font=font(12), command=on_cancel)
        self.cancel_btn.pack(side="right")

    @staticmethod
    def _glyph(url):
        u = url.lower()
        return "▶" if "youtu" in u else "▲" if "drive.google" in u else "⬇"

    def update_progress(self, pct, text, name):
        if name:
            self.title.configure(text=name)
        self.status.configure(text=text, text_color=MUTED)
        if pct is None:
            if not self.indeterminate:
                self.bar.configure(mode="indeterminate")
                self.bar.start()
                self.indeterminate = True
        else:
            if self.indeterminate:
                self.bar.stop()
                self.bar.configure(mode="determinate")
                self.indeterminate = False
            self.bar.set(max(0, min(pct / 100, 1)))

    def finish(self, ok, text, out_dir=None):
        self.done = True
        if self.indeterminate:
            self.bar.stop()
            self.bar.configure(mode="determinate")
            self.indeterminate = False
        self.bar.set(1 if ok else self.bar.get())
        self.bar.configure(progress_color=OK if ok else ERR)
        self.status.configure(text=text, text_color=OK if ok else ERR)
        self.cancel_btn.configure(text="Remove", command=self.on_remove)
        if ok and out_dir:
            ctk.CTkButton(self.btns, text="Open folder", width=96, height=32, corner_radius=9, fg_color=ACCENT,
                          hover_color=ACCENT_HOVER, text_color="white", font=font(12),
                          command=lambda: open_folder(out_dir)).pack(side="right", padx=(0, 8))


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        ctk.set_appearance_mode(self.settings.get("theme", "dark"))
        ctk.set_default_color_theme("blue")
        self.title(f"{APP} {__version__}")
        self.geometry("1120x720")
        self.minsize(900, 620)
        self.configure(fg_color=BG)
        try:
            self.iconbitmap(resource(os.path.join("assets", "icon.ico")))
        except Exception:
            pass

        self.limiter = Limiter(int(self.settings.get("parallel", 3)))
        self.pool = ThreadPoolExecutor(MAX_PARALLEL * 2)
        self.events = queue.Queue()
        self.jobs = {}  # id -> (card, cancel_event)
        self.next_id = 0
        self.out_var = ctk.StringVar(value=self.settings.get("out", os.path.join(os.path.expanduser("~"), "Downloads")))
        self.cookie_file = self.settings.get("cookie_file", "")

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self.main = ctk.CTkFrame(self, fg_color="transparent")
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(0, weight=1)
        self.pages = {}
        for key, builder in (("home", self._page_home), ("downloads", self._page_downloads),
                             ("settings", self._page_settings), ("about", self._page_about)):
            f = ctk.CTkFrame(self.main, fg_color="transparent")
            f.grid(row=0, column=0, sticky="nsew", padx=40, pady=(28, 20))
            f.grid_columnconfigure(0, weight=1)
            builder(f)
            self.pages[key] = f

        self.theme_sw = ctk.CTkSwitch(self.main, text="Dark", command=self._toggle_theme, progress_color=ACCENT,
                                      text_color=MUTED, font=font(12), fg_color=BORDER)
        if ctk.get_appearance_mode() == "Dark":
            self.theme_sw.select()
        self.theme_sw.place(relx=1.0, x=-40, y=36, anchor="ne")

        self.show("home")
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(100, self._pump)

    # ----- shell -----
    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, fg_color=SIDEBAR, corner_radius=0, width=250)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        sb.grid_rowconfigure(2, weight=1)
        sb.grid_columnconfigure(0, weight=1)

        brand = ctk.CTkFrame(sb, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=22, pady=(26, 22))
        ctk.CTkLabel(brand, text="⬇", width=52, height=52, corner_radius=14, fg_color=ACCENT, text_color="white",
                     font=font(26, True)).grid(row=0, column=0, rowspan=2, padx=(0, 12))
        ctk.CTkLabel(brand, text=APP, anchor="w", text_color=TEXT, font=font(21, True)).grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(brand, text=f"v{__version__} · Fast, resumable", anchor="w", text_color=MUTED,
                     font=font(11)).grid(row=1, column=1, sticky="w")

        nav = ctk.CTkFrame(sb, fg_color="transparent")
        nav.grid(row=1, column=0, sticky="ew", padx=16)
        nav.grid_columnconfigure(0, weight=1)
        self.nav_btns = {}
        for i, (key, glyph, label) in enumerate(NAV):
            b = ctk.CTkButton(nav, text=f"  {glyph}   {label}", anchor="w", height=46, corner_radius=12,
                              font=font(15), command=lambda k=key: self.show(k))
            b.grid(row=i, column=0, sticky="ew", pady=3)
            self.nav_btns[key] = b

        promo = ctk.CTkFrame(sb, fg_color=FIELD, corner_radius=14)
        promo.grid(row=3, column=0, sticky="ew", padx=16, pady=20)
        ctk.CTkLabel(promo, text="⚡", width=40, text_color=ACCENT_TEXT, font=font(26, True)).grid(
            row=0, column=0, rowspan=3, padx=(10, 4), pady=14)
        ctk.CTkLabel(promo, text="Faster Downloads", anchor="w", text_color=TEXT, font=font(13, True)).grid(
            row=0, column=1, sticky="w", pady=(14, 0))
        ctk.CTkLabel(promo, text="Multiple threads • Resume", anchor="w", text_color=MUTED, font=font(11)).grid(
            row=1, column=1, sticky="w")
        ctk.CTkLabel(promo, text="Smart & reliable", anchor="w", text_color=MUTED, font=font(11)).grid(
            row=2, column=1, sticky="w", pady=(0, 14))

    def show(self, key):
        self.pages[key].tkraise()
        for k, b in self.nav_btns.items():
            if k == key:
                b.configure(fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="white")
            else:
                b.configure(fg_color="transparent", hover_color=FIELD, text_color=TEXT)
        self.pages[key].lift()
        self.theme_sw.lift()

    def _heading(self, parent, plain, accent="", sub=""):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(row, text=plain, text_color=TEXT, font=font(32, True)).pack(side="left")
        if accent:
            ctk.CTkLabel(row, text=accent, text_color=ACCENT_TEXT, font=font(32, True)).pack(side="left")
        if sub:
            ctk.CTkLabel(parent, text=sub, anchor="w", text_color=MUTED, font=font(14)).grid(
                row=1, column=0, sticky="w", pady=(2, 18))

    # ----- pages -----
    def _page_home(self, p):
        self._heading(p, "Download ", "Anything, Fast", "Paste a link, choose quality (if available) and start downloading.")
        bar = ctk.CTkFrame(p, fg_color=CARD, corner_radius=18, border_width=1, border_color=BORDER)
        bar.grid(row=2, column=0, sticky="ew")
        bar.grid_columnconfigure(0, weight=1)
        field = ctk.CTkFrame(bar, fg_color=FIELD, corner_radius=12)
        field.grid(row=0, column=0, sticky="ew", padx=(14, 10), pady=14)
        field.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(field, text="🔗", width=44, text_color=ACCENT_TEXT, font=font(16)).grid(row=0, column=0)
        self.url_entry = ctk.CTkEntry(field, height=48, border_width=0, fg_color="transparent", text_color=TEXT,
                                      placeholder_text="Paste URL here (YouTube, Google Drive, Images, Videos, any file)…",
                                      font=font(14))
        self.url_entry.grid(row=0, column=1, sticky="ew", padx=(0, 10))
        self.url_entry.bind("<Return>", lambda e: self.start())
        self.url_entry.bind("<<Paste>>", self._paste)
        self.quality = ctk.CTkOptionMenu(bar, values=core.QUALITIES, width=150, height=48, corner_radius=12,
                                         fg_color=FIELD, button_color=FIELD, button_hover_color=SOFT_HOVER,
                                         text_color=TEXT, dropdown_fg_color=CARD, dropdown_text_color=TEXT,
                                         font=font(14), dropdown_font=font(13))
        self.quality.set(self.settings.get("quality", core.QUALITIES[0]))
        self.quality.grid(row=0, column=1, padx=(0, 10))
        ctk.CTkButton(bar, text="⬇  Download", width=160, height=48, corner_radius=12, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, text_color="white", font=font(15, True),
                      command=self.start).grid(row=0, column=2, padx=(0, 14))

        dest = ctk.CTkFrame(p, fg_color="transparent")
        dest.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        dest.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(dest, text="📁  Save to", text_color=MUTED, font=font(12)).grid(row=0, column=0, padx=(6, 10))
        self.dest_entry = ctk.CTkEntry(dest, height=34, corner_radius=9, fg_color=FIELD, border_width=0,
                                       text_color=TEXT, font=font(12), placeholder_text=self._default_out())
        self.dest_entry.grid(row=0, column=1, sticky="ew")
        ctk.CTkButton(dest, text="Browse", width=76, height=34, corner_radius=9, fg_color=SOFT_BTN,
                      hover_color=SOFT_HOVER, text_color=TEXT, font=font(12),
                      command=self._browse_dest).grid(row=0, column=2, padx=(8, 0))
        ctk.CTkButton(dest, text="Reset", width=60, height=34, corner_radius=9, fg_color="transparent",
                      hover_color=FIELD, text_color=MUTED, font=font(12),
                      command=lambda: self.dest_entry.delete(0, "end")).grid(row=0, column=3, padx=(4, 0))
        ctk.CTkLabel(dest, text="Leave empty to use your default folder (Settings). Missing folders are created "
                     "automatically.", anchor="w", text_color=MUTED, font=font(11)).grid(
            row=1, column=1, columnspan=3, sticky="w", padx=2, pady=(3, 0))
        self.out_var.trace_add("write", lambda *a: self.dest_entry.configure(placeholder_text=self._default_out()))

        empty = ctk.CTkFrame(p, fg_color="transparent")
        empty.grid(row=4, column=0, sticky="nsew", pady=(14, 0))
        p.grid_rowconfigure(4, weight=1)
        empty.grid_columnconfigure(0, weight=1)
        hero = Image.open(resource(os.path.join("assets", "hero.png")))
        self.hero = ctk.CTkImage(hero, size=(hero.width, hero.height))
        ctk.CTkLabel(empty, text="", image=self.hero).grid(row=0, column=0, pady=(6, 0))
        ctk.CTkLabel(empty, text="No downloads yet", text_color=TEXT, font=font(22, True)).grid(row=1, column=0)
        ctk.CTkLabel(empty, text="Paste a link above to get started.", text_color=MUTED, font=font(14)).grid(
            row=2, column=0, pady=(2, 14))
        pill = ctk.CTkFrame(empty, fg_color="transparent", corner_radius=22, border_width=1, border_color=BORDER)
        pill.grid(row=3, column=0)
        for i, (g, color, label) in enumerate([("▶", "#EF4444", "YouTube"), ("▲", "#22A06B", "Google Drive"),
                                                ("▣", "#3B82F6", "Images"), ("▶", "#8B5CF6", "Videos"),
                                                ("▤", "#6366F1", "Any file")]):
            chip = ctk.CTkFrame(pill, fg_color="transparent")
            chip.grid(row=0, column=i, padx=(16 if i == 0 else 8, 16 if i == 4 else 8), pady=10)
            ctk.CTkLabel(chip, text=g, width=22, height=22, corner_radius=6, fg_color=color, text_color="white",
                         font=font(11, True)).pack(side="left", padx=(0, 7))
            ctk.CTkLabel(chip, text=label, text_color=TEXT, font=font(12)).pack(side="left")

    def _page_downloads(self, p):
        self._heading(p, "Downloads")
        top = ctk.CTkFrame(p, fg_color="transparent")
        top.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        top.grid_columnconfigure(0, weight=1)
        self.count_lbl = ctk.CTkLabel(top, text="", anchor="w", text_color=MUTED, font=font(13))
        self.count_lbl.grid(row=0, column=0, sticky="w")
        ctk.CTkButton(top, text="Clear finished", width=120, height=32, corner_radius=9, fg_color=SOFT_BTN,
                      hover_color=SOFT_HOVER, text_color=TEXT, font=font(12),
                      command=self._clear_finished).grid(row=0, column=1)
        self.list = ctk.CTkScrollableFrame(p, fg_color="transparent")
        self.list.grid(row=2, column=0, sticky="nsew")
        self.list.grid_columnconfigure(0, weight=1)
        p.grid_rowconfigure(2, weight=1)
        self.empty_lbl = ctk.CTkLabel(self.list, text="Nothing here yet — start a download from Home.",
                                      text_color=MUTED, font=font(14))
        self.empty_lbl.grid(row=0, column=0, pady=60)

    def _card(self, parent, title, sub=""):
        c = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=14, border_width=1, border_color=BORDER)
        c.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(c, text=title, anchor="w", text_color=TEXT, font=font(14, True)).grid(
            row=0, column=0, sticky="w", padx=18, pady=(14, 0))
        if sub:
            ctk.CTkLabel(c, text=sub, anchor="w", text_color=MUTED, font=font(12), wraplength=600, justify="left").grid(
                row=1, column=0, sticky="w", padx=18)
        return c

    def _page_settings(self, p):
        self._heading(p, "Settings")
        r = 1

        c = self._card(p, "Download folder", "Where finished files are saved.")
        c.grid(row=r, column=0, sticky="ew", pady=6)
        row = ctk.CTkFrame(c, fg_color="transparent")
        row.grid(row=2, column=0, sticky="ew", padx=18, pady=(8, 16))
        row.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(row, textvariable=self.out_var, height=38, corner_radius=10, fg_color=FIELD, border_width=0,
                     text_color=TEXT, font=font(13)).grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(row, text="Browse", width=90, height=38, corner_radius=10, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, text_color="white", font=font(13), command=self._browse).grid(
            row=0, column=1, padx=(8, 0))
        self.out_var.trace_add("write", lambda *a: self._save_out())
        r += 1

        c = self._card(p, "Parallel downloads", "How many links download at the same time.")
        c.grid(row=r, column=0, sticky="ew", pady=6)
        row = ctk.CTkFrame(c, fg_color="transparent")
        row.grid(row=2, column=0, sticky="ew", padx=18, pady=(6, 16))
        row.grid_columnconfigure(0, weight=1)
        self.par_lbl = ctk.CTkLabel(row, text="", width=30, text_color=ACCENT_TEXT, font=font(15, True))
        slider = ctk.CTkSlider(row, from_=1, to=MAX_PARALLEL, number_of_steps=MAX_PARALLEL - 1, progress_color=ACCENT,
                               button_color=ACCENT, button_hover_color=ACCENT_HOVER, fg_color=FIELD,
                               command=self._parallel_changed)
        slider.set(self.limiter.n)
        slider.grid(row=0, column=0, sticky="ew")
        self.par_lbl.grid(row=0, column=1, padx=(12, 0))
        self.par_lbl.configure(text=str(self.limiter.n))
        r += 1

        core.DRIVE_WORKERS = int(self.settings.get("drive_files", core.DRIVE_WORKERS))
        c = self._card(p, "Files per Google Drive folder",
                       "How many files of a Drive folder download at once. Higher is faster for many small files, "
                       "but Drive may block you sooner (quota exceeded).")
        c.grid(row=r, column=0, sticky="ew", pady=6)
        row = ctk.CTkFrame(c, fg_color="transparent")
        row.grid(row=2, column=0, sticky="ew", padx=18, pady=(6, 16))
        row.grid_columnconfigure(0, weight=1)
        self.drive_lbl = ctk.CTkLabel(row, text=str(core.DRIVE_WORKERS), width=30, text_color=ACCENT_TEXT,
                                      font=font(15, True))
        dslider = ctk.CTkSlider(row, from_=1, to=8, number_of_steps=7, progress_color=ACCENT, button_color=ACCENT,
                                button_hover_color=ACCENT_HOVER, fg_color=FIELD, command=self._drive_changed)
        dslider.set(core.DRIVE_WORKERS)
        dslider.grid(row=0, column=0, sticky="ew")
        self.drive_lbl.grid(row=0, column=1, padx=(12, 0))
        r += 1

        c = self._card(p, "Login for age-restricted / private videos",
                       "Uses your browser's YouTube sign-in (close the browser first), or a cookies.txt export.")
        c.grid(row=r, column=0, sticky="ew", pady=6)
        row = ctk.CTkFrame(c, fg_color="transparent")
        row.grid(row=2, column=0, sticky="ew", padx=18, pady=(8, 16))
        self.login = ctk.CTkOptionMenu(row, values=LOGIN_CHOICES, width=190, height=38, corner_radius=10,
                                       fg_color=FIELD, button_color=FIELD, button_hover_color=SOFT_HOVER,
                                       text_color=TEXT, dropdown_fg_color=CARD, dropdown_text_color=TEXT,
                                       font=font(13), command=self._login_changed)
        self.login.set(self.settings.get("login", LOGIN_CHOICES[0]))
        self.login.pack(side="left")
        self.signin_btn = ctk.CTkButton(row, text="Sign in", width=100, height=38, corner_radius=10, fg_color=ACCENT,
                                        hover_color=ACCENT_HOVER, text_color="white", font=font(13, True),
                                        command=self._sign_in)
        self.signout_btn = ctk.CTkButton(row, text="Sign out", width=90, height=38, corner_radius=10,
                                         fg_color=SOFT_BTN, hover_color=SOFT_HOVER, text_color=TEXT, font=font(13),
                                         command=self._sign_out)
        self.login_note = ctk.CTkLabel(row, text="", text_color=MUTED, font=font(12))
        self.login_note.pack(side="left", padx=12)
        self._login_changed(self.login.get(), initial=True)

    def _page_about(self, p):
        self._heading(p, "About")
        c = self._card(p, f"{APP} {__version__}", "Fast, resumable downloads for YouTube and 1,800+ video sites, "
                       "Google Drive files and folders, images, and any direct file link.")
        c.grid(row=1, column=0, sticky="ew", pady=6)
        ff = "bundled" if core.ffmpeg_dir() else "from PATH"
        for i, line in enumerate([f"• Video engine: yt-dlp · Drive: gdown · ffmpeg: {ff}",
                                  "• Direct files use 8 parallel connections with automatic retry and resume",
                                  f"• Settings: {SETTINGS}"]):
            ctk.CTkLabel(c, text=line, anchor="w", text_color=MUTED, font=font(12)).grid(
                row=2 + i, column=0, sticky="w", padx=18, pady=(8 if i == 0 else 2, 14 if i == 2 else 0))

    # ----- settings handlers -----
    def _toggle_theme(self):
        mode = "dark" if self.theme_sw.get() else "light"
        ctk.set_appearance_mode(mode)
        self.settings["theme"] = mode
        save_settings(self.settings)

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.out_var.get() or None)
        if d:
            self.out_var.set(os.path.normpath(d))

    def _save_out(self):
        self.settings["out"] = self.out_var.get().strip()
        save_settings(self.settings)

    def _default_out(self):
        return os.path.normpath(self.out_var.get().strip() or os.path.join(os.path.expanduser("~"), "Downloads"))

    def _browse_dest(self):
        d = filedialog.askdirectory(title="Save this download to…", initialdir=self._resolve_out() if
                                    os.path.isdir(self._resolve_out()) else None)
        if d:
            self.dest_entry.delete(0, "end")
            self.dest_entry.insert(0, os.path.normpath(d))

    def _resolve_out(self):
        """Per-download folder if typed/chosen, else the default; ~ and %VARS% expanded."""
        raw = self.dest_entry.get().strip() or self._default_out()
        return os.path.normpath(os.path.expandvars(os.path.expanduser(raw)))

    def _parallel_changed(self, v):
        n = int(round(v))
        self.limiter.set(n)
        self.par_lbl.configure(text=str(n))
        self.settings["parallel"] = n
        save_settings(self.settings)

    def _drive_changed(self, v):
        n = int(round(v))
        core.DRIVE_WORKERS = n
        self.drive_lbl.configure(text=str(n))
        self.settings["drive_files"] = n
        save_settings(self.settings)

    def _login_changed(self, choice, initial=False):
        if choice == LOGIN_FILE and not (initial and self.cookie_file):
            f = filedialog.askopenfilename(title="Select cookies.txt", filetypes=[("cookies.txt", "*.txt"), ("All", "*.*")])
            if f:
                self.cookie_file = f
            elif not self.cookie_file:
                choice = LOGIN_CHOICES[0]
                self.login.set(choice)
        self._refresh_login_ui()
        self.settings.update(login=self.login.get(), cookie_file=self.cookie_file)
        save_settings(self.settings)
        if choice == LOGIN_APP and not initial and not os.path.exists(APP_COOKIES):
            self._sign_in()

    def _refresh_login_ui(self):
        choice = self.login.get()
        self.signin_btn.pack_forget()
        self.signout_btn.pack_forget()
        if choice == LOGIN_APP:
            signed = os.path.exists(APP_COOKIES)
            self.signin_btn.configure(text="Re-sign in" if signed else "Sign in")
            self.signin_btn.pack(side="left", padx=(12, 0), before=self.login_note)
            if signed:
                self.signout_btn.pack(side="left", padx=(8, 0), before=self.login_note)
            note = "✓ signed in" if signed else "not signed in yet"
        elif choice == LOGIN_FILE:
            note = os.path.basename(self.cookie_file)
        else:
            note = "" if choice == LOGIN_CHOICES[0] else "using browser login"
        self.login_note.configure(text=note, text_color=OK if note.startswith("✓") else MUTED)

    def _sign_in(self):
        if getattr(self, "_signing", False):
            return
        self._signing = True
        self.signin_btn.configure(state="disabled", text="Waiting…")
        self.login_note.configure(text="complete the sign-in in the window that opened", text_color=MUTED)
        os.makedirs(WEBVIEW_DIR, exist_ok=True)
        cmd = [sys.executable] + ([] if getattr(sys, "frozen", False) else [os.path.abspath(__file__)])
        cmd += ["--login", APP_COOKIES, WEBVIEW_DIR]

        def worker():
            try:
                code = subprocess.call(cmd, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except OSError:
                code = -1
            self.after(0, lambda: self._sign_in_done(code == 0))

        threading.Thread(target=worker, daemon=True).start()

    def _sign_in_done(self, ok):
        self._signing = False
        self.signin_btn.configure(state="normal")
        self._refresh_login_ui()
        if not ok:
            self.login_note.configure(text="sign-in not completed (window closed, or Google blocked it — "
                                      "try a browser or cookies.txt instead)", text_color=ERR)

    def _sign_out(self):
        import shutil
        for path in (APP_COOKIES,):
            try:
                os.remove(path)
            except OSError:
                pass
        shutil.rmtree(WEBVIEW_DIR, ignore_errors=True)  # forget the embedded browser session too
        self._refresh_login_ui()

    def _cookies(self):
        choice = self.login.get()
        if choice == LOGIN_APP and os.path.exists(APP_COOKIES):
            return ("file", APP_COOKIES)
        if choice == LOGIN_FILE and self.cookie_file:
            return ("file", self.cookie_file)
        if choice in LOGIN_CHOICES[2:-1]:
            return ("browser", choice.lower())
        return None

    # ----- downloads -----
    def _paste(self, _event):
        try:
            text = self.clipboard_get()
        except Exception:
            return "break"
        self.url_entry.insert("insert", re.sub(r"\s+", " ", text.strip()))
        return "break"

    def start(self):
        urls = [u if re.match(r"^\w+://", u) else "https://" + u for u in self.url_entry.get().split()]
        if not urls:
            return
        out, quality, cookies = self._resolve_out(), self.quality.get(), self._cookies()
        try:
            os.makedirs(out, exist_ok=True)  # create the folder (and parents) up front
        except OSError as e:
            self.dest_entry.configure(border_width=1, border_color=ERR)
            self.after(2500, lambda: self.dest_entry.configure(border_width=0))
            from tkinter import messagebox
            messagebox.showerror(APP, f"Can't create the folder:\n{out}\n\n{e.strerror or e}")
            return
        self.settings.update(quality=quality)
        save_settings(self.settings)
        self.url_entry.delete(0, "end")
        self.empty_lbl.grid_remove()
        for url in urls:
            jid, cancel = self.next_id, threading.Event()
            self.next_id += 1
            card = JobCard(self.list, url, out, on_cancel=cancel.set, on_remove=lambda j=jid: self._remove(j))
            card.grid(row=jid, column=0, sticky="ew", pady=5)
            self.jobs[jid] = (card, cancel)
            self.pool.submit(self._run, jid, url, out, quality, cancel, cookies)
        self._update_count()
        self.show("downloads")

    def _run(self, jid, url, out, quality, cancel, cookies):
        def cb(pct, text, name):
            self.events.put((jid, "progress", (pct, text, name)))
        if not self.limiter.acquire(cancel):
            self.events.put((jid, "cancelled", None))
            return
        try:
            if cancel.is_set():
                raise core.Cancelled()
            core.download(url, out, quality, cb, cancel, cookies)
            self.events.put((jid, "done", out))
        except core.Cancelled:
            self.events.put((jid, "cancelled", None))
        except Exception as e:
            self.events.put((jid, "error", str(e)[:200] or type(e).__name__))
        finally:
            self.limiter.release()

    def _pump(self):
        try:
            while True:
                jid, kind, data = self.events.get_nowait()
                if jid not in self.jobs:
                    continue
                card = self.jobs[jid][0]
                if card.done:
                    continue
                if kind == "progress":
                    card.update_progress(*data)
                elif kind == "done":
                    card.finish(True, card.status.cget("text") or "Saved", data)
                elif kind == "cancelled":
                    card.finish(False, "Cancelled")
                elif kind == "error":
                    card.finish(False, data)
                if kind != "progress":
                    self._update_count()
        except queue.Empty:
            pass
        self.after(100, self._pump)

    def _update_count(self):
        active = sum(1 for c, _ in self.jobs.values() if not c.done)
        self.count_lbl.configure(text=f"{len(self.jobs)} total · {active} active" if self.jobs else "")

    def _remove(self, jid):
        card = self.jobs.pop(jid)[0]
        card.destroy()
        if not self.jobs:
            self.empty_lbl.grid()
        self._update_count()

    def _clear_finished(self):
        for jid in [j for j, (c, _) in self.jobs.items() if c.done]:
            self._remove(jid)

    def _close(self):
        for _, cancel in self.jobs.values():
            cancel.set()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.destroy()
        os._exit(0)  # don't wait on downloader threads


if __name__ == "__main__":
    if len(sys.argv) > 3 and sys.argv[1] == "--login":  # sign-in helper process
        import login_window
        login_window.run(sys.argv[2], sys.argv[3])
    else:
        App().mainloop()
