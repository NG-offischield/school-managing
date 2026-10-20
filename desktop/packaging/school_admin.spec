# PyInstaller recipe of the Windows admin client (docs/desktop-windows.md).
#
#   .venv\Scripts\pyinstaller packaging\school_admin.spec --noconfirm --distpath packaging\dist --workpath packaging\build\pyinstaller
#
# One folder (not one file): faster start, no extraction in %TEMP% at each
# launch, fewer antivirus false alarms. Windowed (no console); errors go to the
# diagnostic log (school_admin/diagnostics.py). Run by packaging\build.ps1.
# ruff: noqa

from pathlib import Path

ROOT = Path(SPECPATH).parent  # desktop/
ICON = Path(SPECPATH) / "build" / "app-icon.ico"
VERSION_FILE = Path(SPECPATH) / "build" / "version_info.txt"

a = Analysis(
    [str(Path(SPECPATH) / "launch.py")],
    pathex=[str(ROOT)],
    # The interface icons (SVG) and the brand folder, found next to the code at run time.
    datas=[(str(ROOT / "school_admin" / "ui" / "assets"), "school_admin/ui/assets")],
    # SVG icons are drawn by Qt's svg image plugin.
    hiddenimports=["PySide6.QtSvg"],
    # Never shipped: tests and development tools.
    excludes=["tkinter", "pytest", "ruff", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SchoolManagingAdmin",
    console=False,
    icon=str(ICON) if ICON.exists() else None,
    version=str(VERSION_FILE) if VERSION_FILE.exists() else None,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="SchoolManagingAdmin", upx=False)
