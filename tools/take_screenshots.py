"""Capture README screenshots into docs/screenshots (uses throwaway settings, never your real ones).

    python tools/take_screenshots.py
"""
import os
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "docs", "screenshots")
DEMO = r"C:\Users\Public\Downloads\iDownload"  # generic path so no personal folder shows in the images
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="idl_cfg_")  # keep the real settings untouched
sys.path.insert(0, ROOT)
os.makedirs(OUT, exist_ok=True)

from PIL import ImageGrab  # noqa: E402

import app  # noqa: E402

a = app.App()
a.out_var.set(r"C:\Users\Public\Downloads")  # generic path for the screenshots
a.attributes("-topmost", True)


def grab(name):
    a.update()
    x, y, w, h = a.winfo_rootx(), a.winfo_rooty(), a.winfo_width(), a.winfo_height()
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).convert("RGB")
    while img.height > 1 and all(img.getpixel((i, img.height - 1)) == (0, 0, 0) for i in range(0, img.width, 40)):
        img = img.crop((0, 0, img.width, img.height - 1))  # trim any off-screen black edge
    img.save(os.path.join(OUT, name))
    print("saved", name, flush=True)


def step1():
    grab("home.png")
    a.url_entry.insert(0, "https://proof.ovh.net/files/10Mb.dat https://picsum.photos/1200/800 "
                          "https://picsum.photos/600/400")
    a.dest_entry.insert(0, DEMO)
    a.start()
    a.after(4500, step2)


def step2():
    grab("downloads.png")
    a.show("settings")
    a.after(600, step3)


def step3():
    grab("settings.png")
    a.theme_sw.deselect()
    a._toggle_theme()
    a.show("downloads")
    a.after(800, step4)


def step4():
    grab("downloads-light.png")
    a.show("home")
    a.after(800, step5)


def step5():
    grab("home-light.png")
    os._exit(0)


a.after(2000, step1)
a.mainloop()
