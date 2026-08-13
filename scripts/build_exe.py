"""
Build the widget as a Windows executable — no console, no install.

PyInstaller is a build-time tool only; the widget itself still imports nothing
but the standard library, and the executable carries its own Python, so the
machine it runs on needs neither Python nor pip.

    python scripts/build_exe.py            one file: dist/Lagrange Widget.exe
    python scripts/build_exe.py --onedir   a folder, which starts faster
    python scripts/build_exe.py --release  both, named and staged for a release

Two formats because they fail differently. The single file is one download that
runs from anywhere, but it unpacks itself into %TEMP% on every start, which
costs a second and occasionally upsets an antivirus that dislikes unsigned
self-extractors. The folder starts immediately and has nothing to unpack.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lagrange import __version__  # noqa: E402
from scripts import make_icon  # noqa: E402

NAME = "Lagrange Widget"
SLUG = "Lagrange-Widget"          # for download names, which should not need quoting
ENTRY = os.path.join(ROOT, "scripts", "widget_entry.py")
BUILD = os.path.join(ROOT, "build")
DIST = os.path.join(ROOT, "dist")
RELEASE = os.path.join(DIST, "release")
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
      StringStruct('FileDescription', 'Lagrange Widget - live quota meter for Antigravity CLI'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'LagrangeWidget'),
      StringStruct('LegalCopyright', 'MIT licensed'),
      StringStruct('OriginalFilename', 'Lagrange Widget.exe'),
      StringStruct('ProductName', 'Lagrange Widget'),
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


def _freeze(onedir: bool, keep: bool) -> str:
    """Run PyInstaller once; returns the path it produced."""
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onedir" if onedir else "--onefile",
        "--windowed",                       # no console window behind the widget
        "--name", NAME,
        "--icon", ICON,
        "--paths", ROOT,
        "--version-file", _version_file(),
        "--distpath", DIST,
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
        raise SystemExit(result.returncode)
    if not keep:
        shutil.rmtree(os.path.join(BUILD, "pyinstaller"), ignore_errors=True)
    return os.path.join(DIST, NAME if onedir else f"{NAME}.exe")


def _zip_folder(folder: str, archive: str) -> str:
    """Zip a folder build, keeping the folder itself as the top-level entry."""
    base = os.path.dirname(folder)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(folder):
            for name in files:
                path = os.path.join(root, name)
                zf.write(path, os.path.relpath(path, base))
    return archive


def _report(path: str) -> None:
    if os.path.isfile(path):
        print(f"  {path}  ({os.path.getsize(path) / 1024 / 1024:.1f} MB)")
    else:
        print(f"  {path}{os.sep}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Lagrange Widget executable")
    parser.add_argument("--onedir", action="store_true",
                        help="build a folder instead of a single file")
    parser.add_argument("--release", action="store_true",
                        help="build both formats and stage them under dist/release")
    parser.add_argument("--keep", action="store_true", help="keep intermediate files")
    args = parser.parse_args(argv)

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is missing — install it with:\n"
              "    pip install pyinstaller", file=sys.stderr)
        return 1

    make_icon.build(ICON)

    if not args.release:
        print()
        _report(_freeze(args.onedir, args.keep))
        return 0

    single = _freeze(onedir=False, keep=args.keep)
    folder = _freeze(onedir=True, keep=args.keep)

    os.makedirs(RELEASE, exist_ok=True)
    portable = os.path.join(RELEASE, f"{SLUG}-{__version__}-win-portable.exe")
    archive = os.path.join(RELEASE, f"{SLUG}-{__version__}-win-folder.zip")
    shutil.copy2(single, portable)
    _zip_folder(folder, archive)

    print("\nrelease assets:")
    _report(portable)
    _report(archive)
    return 0


if __name__ == "__main__":
    sys.exit(main())
