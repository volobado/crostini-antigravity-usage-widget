"""
Build `dist/Lagrange.exe` — one portable file, no console, no install.

PyInstaller is a build-time tool only; the widget itself still imports nothing
but the standard library, and the executable carries its own Python, so the
machine it runs on needs neither Python nor pip.

    python scripts/build_exe.py            build
    python scripts/build_exe.py --onedir   folder build (starts faster)

Antivirus note: single-file PyInstaller executables are unsigned and unpack
themselves into %TEMP%, which some scanners flag on sight. `--onedir` avoids the
unpacking and tends to draw less attention.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lagrange import __version__  # noqa: E402
from scripts import make_icon  # noqa: E402

NAME = "Lagrange"
ENTRY = os.path.join(ROOT, "scripts", "widget_entry.py")
BUILD = os.path.join(ROOT, "build")
ICON = os.path.join(ROOT, "assets", "lagrange.ico")

# Nothing here imports them. `email`, `http` and `xml` are deliberately absent
# from this list: urllib.request pulls them in, and the quota calls go through it.
EXCLUDE = ["numpy", "PIL", "pandas", "pytest", "setuptools", "pip", "pydoc_data",
           "unittest", "doctest"]

VERSION_TEMPLATE = """\
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({major}, {minor}, {patch}, 0),
    prodvers=({major}, {minor}, {patch}, 0),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Volo Bado'),
      StringStruct('FileDescription', 'Live quota meter for Antigravity CLI'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'Lagrange'),
      StringStruct('LegalCopyright', 'MIT licensed'),
      StringStruct('OriginalFilename', 'Lagrange.exe'),
      StringStruct('ProductName', 'Lagrange'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def _version_file() -> str:
    major, minor, patch = (list(map(int, __version__.split("."))) + [0, 0])[:3]
    os.makedirs(BUILD, exist_ok=True)
    path = os.path.join(BUILD, "version_info.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(VERSION_TEMPLATE.format(major=major, minor=minor, patch=patch,
                                         version=__version__))
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Lagrange executable")
    parser.add_argument("--onedir", action="store_true",
                        help="build a folder instead of a single file")
    parser.add_argument("--keep", action="store_true", help="keep intermediate files")
    args = parser.parse_args(argv)

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is missing — install it with:\n"
              "    pip install pyinstaller", file=sys.stderr)
        return 1

    make_icon.build(ICON)

    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onedir" if args.onedir else "--onefile",
        "--windowed",                       # no console window behind the widget
        "--name", NAME,
        "--icon", ICON,
        "--paths", ROOT,
        "--version-file", _version_file(),
        "--distpath", os.path.join(ROOT, "dist"),
        "--workpath", os.path.join(BUILD, "pyinstaller"),
        "--specpath", BUILD,
        "--noupx",
    ]
    for module in EXCLUDE:
        command += ["--exclude-module", module]
    command.append(ENTRY)

    print(" ".join(command), "\n")
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode:
        return result.returncode

    if not args.keep:
        shutil.rmtree(os.path.join(BUILD, "pyinstaller"), ignore_errors=True)

    target = os.path.join(ROOT, "dist", NAME if args.onedir else f"{NAME}.exe")
    if os.path.isfile(target):
        print(f"\n{target}  ({os.path.getsize(target) / 1024 / 1024:.1f} MB)")
    else:
        print(f"\n{target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
