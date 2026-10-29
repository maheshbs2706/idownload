"""Build dist/iDownload-v<version>.exe with PyInstaller (called by build.bat).

Arguments are passed as a list, so Windows path quoting and the ';' separator can't be mangled by cmd.
"""
import os
import shutil
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

import PyInstaller.__main__  # noqa: E402

from version import __version__  # noqa: E402

SEP = os.pathsep  # ';' on Windows


def main():
    args = [
        "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", "iDownload",
        "--icon", os.path.join("assets", "icon.ico"),
        "--add-data", os.path.join("assets", "icon.ico") + SEP + "assets",
        "--add-data", os.path.join("assets", "hero.png") + SEP + "assets",
        "--version-file", "version_info.txt",
        "--collect-all", "customtkinter",
        "--collect-submodules", "yt_dlp",
        "--collect-all", "gdown",
        "--collect-all", "webview",
        "--collect-all", "yt_dlp_ejs",
    ]
    # ffmpeg merges video+audio and makes MP3s; node unlocks YouTube formats. Both keep the exe standalone.
    for exe, why in (("ffmpeg", "the exe won't be able to merge HD video or make MP3s"),
                     ("node", "YouTube downloads in the exe will need Node.js or Deno installed")):
        path = shutil.which(exe)
        if path:
            print(f"Bundling {exe}: {path}")
            args += ["--add-binary", path + SEP + "."]
        else:
            print(f"WARNING: {exe} not found on PATH - {why}.")
    PyInstaller.__main__.run(args + ["app.py"])

    built = os.path.join(ROOT, "dist", "iDownload.exe")
    final = os.path.join(ROOT, "dist", f"iDownload-v{__version__}.exe")
    if os.path.exists(final):
        os.remove(final)
    os.replace(built, final)
    print(f"\nBuilt: {final}")


if __name__ == "__main__":
    main()
