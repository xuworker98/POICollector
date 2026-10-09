# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys

project = Path(SPEC).resolve().parent
source = project / 'src' / 'poi_collector'
python_prefix = Path(sys.prefix)
sqlite_runtime = python_prefix / 'Library' / 'bin' / 'sqlite3.dll'
if not sqlite_runtime.is_file():
    raise FileNotFoundError(
        f'SQLite runtime DLL not found: {sqlite_runtime}. '
        'Build with the configured Miniforge Python environment.'
    )

a = Analysis(
    [str(project / 'main.py')],
    pathex=[str(source)],
    # Miniforge keeps sqlite3.dll under Library/bin. PyInstaller detects
    # _sqlite3.pyd but cannot resolve this non-standard DLL search path.
    # Bundle it beside the extracted executable so sqlite3 imports on a
    # clean Windows machine without Miniforge installed.
    binaries=[(str(sqlite_runtime), '.')],
    datas=[
        (str(source / 'res' / 'icon.ico'), '.'),
        (str(source / 'res' / 'map_zoom_in.svg'), '.'),
        (str(source / 'res' / 'map_zoom_out.svg'), '.'),
        (str(source / 'res' / 'map_locate.svg'), '.'),
        (str(source / 'res' / 'map_box.svg'), '.'),
        (str(source / 'res' / 'map_layers.svg'), '.'),
        (str(source / 'res' / 'map_fit.svg'), '.'),
        (str(project / 'data'), 'data'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'pandas', 'numpy', 'shapely', 'pyogrio',
        'PIL', 'lxml', 'Cython', 'pygments', 'setuptools',
        'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.QtBluetooth',
        'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtDesigner',
        'PySide6.QtHelp', 'PySide6.QtLocation', 'PySide6.QtMultimedia',
        'PySide6.QtNetworkAuth', 'PySide6.QtNfc', 'PySide6.QtOpenGL',
        'PySide6.QtPdf', 'PySide6.QtPositioning', 'PySide6.QtQml',
        'PySide6.QtQuick', 'PySide6.QtRemoteObjects', 'PySide6.QtScxml',
        'PySide6.QtSensors', 'PySide6.QtSerialPort', 'PySide6.QtSql',
        'PySide6.QtStateMachine', 'PySide6.QtTest',
        'PySide6.QtWebChannel', 'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets', 'PySide6.QtWebSockets', 'PySide6.QtXml',
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='POICollector_V2.0',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(source / 'res' / 'icon.ico'),
)
