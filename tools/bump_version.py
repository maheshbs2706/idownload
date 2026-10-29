"""Update version.py and version_info.txt (Windows exe metadata).

    bump_version.py show            print current version
    bump_version.py major|minor|patch
    bump_version.py set 2.3.4-beta  (any custom string; the numeric part feeds exe metadata)
    bump_version.py sync            rewrite version_info.txt from version.py
"""
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
VERSION_PY = os.path.join(ROOT, "version.py")
INFO = os.path.join(ROOT, "version_info.txt")


def current():
    with open(VERSION_PY, encoding="utf-8") as f:
        return re.search(r'"(.+?)"', f.read()).group(1)


def numeric(v):
    nums = [int(x) for x in re.findall(r"\d+", v.split("-")[0])][:4]
    return tuple(nums + [0] * (4 - len(nums)))


def write(v):
    with open(VERSION_PY, "w", encoding="utf-8") as f:
        f.write(f'__version__ = "{v}"\n')
    n = numeric(v)
    with open(INFO, "w", encoding="utf-8") as f:
        f.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={n}, prodvers={n}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'iDownload'),
      StringStruct('FileDescription', 'iDownload - fast video, image and Google Drive downloader'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('InternalName', 'iDownload'),
      StringStruct('OriginalFilename', 'iDownload.exe'),
      StringStruct('ProductName', 'iDownload'),
      StringStruct('ProductVersion', '{v}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    v = current()
    if cmd == "show":
        print(v)
        return
    if cmd == "sync":
        write(v)
        return
    if cmd == "set":
        new = sys.argv[2].lstrip("v")
        if not re.match(r"^\d+(\.\d+)*([-+][\w.]+)?$", new):
            sys.exit("invalid version: " + new)
    elif cmd in ("major", "minor", "patch"):
        ma, mi, pa, _ = numeric(v)
        new = {"major": f"{ma + 1}.0.0", "minor": f"{ma}.{mi + 1}.0", "patch": f"{ma}.{mi}.{pa + 1}"}[cmd]
    else:
        sys.exit("unknown command: " + cmd)
    write(new)
    print(new)


main()
