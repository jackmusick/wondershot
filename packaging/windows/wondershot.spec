# PyInstaller spec — one-dir Windows bundle.
#
# Build (from the repo root, venv with pyinstaller + the windows extra):
#   pyinstaller packaging/windows/wondershot.spec --noconfirm
# Stage ffmpeg.exe next to this spec first; the build fails loudly
# without it (a bundle without ffmpeg ships broken video — never ship
# that silently; ffmpegutil._bundled_ffmpeg finds it at runtime).
import os

from PyInstaller.utils.hooks import collect_data_files

# SPECPATH is the spec file's directory (PyInstaller global).
SPEC_DIR = SPECPATH
# Repo root must be on the analysis path: the dev venv installs
# wondershot editable (PEP 660 import hook), which freezing can't see —
# without this the exe dies with ModuleNotFoundError: wondershot.cli.
REPO_ROOT = os.path.abspath(os.path.join(SPEC_DIR, "..", ".."))

ffmpeg = os.path.join(SPEC_DIR, "ffmpeg.exe")
if not os.path.exists(ffmpeg):
    raise SystemExit(
        f"stage ffmpeg.exe at {ffmpeg} before building (gyan.dev "
        "essentials build works)")

a = Analysis(
    [os.path.join(SPEC_DIR, "launch.py")],
    pathex=[REPO_ROOT],
    binaries=[(ffmpeg, ".")],
    datas=collect_data_files("wondershot"),  # data/ + data/icons/
    hiddenimports=[],
    excludes=[
        # Qt payload diet: pulled in by PySide6 but unused by us.
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtCharts",
        "PySide6.QtDataVisualization", "PySide6.QtGraphs",
        "PySide6.QtLocation", "PySide6.QtPositioning",
        "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtSql",
        "PySide6.QtTest", "PySide6.QtBluetooth", "PySide6.QtNfc",
        "PySide6.QtRemoteObjects", "PySide6.QtScxml",
        "PySide6.QtStateMachine", "PySide6.QtTextToSpeech",
        "PySide6.QtWebChannel", "PySide6.QtWebSockets",
        "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtUiTools",
        "tkinter",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="Wondershot",
    console=False,           # GUI app: no console window
    icon=os.path.join(SPEC_DIR, "wondershot.ico")
    if os.path.exists(os.path.join(SPEC_DIR, "wondershot.ico")) else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="Wondershot",
)
