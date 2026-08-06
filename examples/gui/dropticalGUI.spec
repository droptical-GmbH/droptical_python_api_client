# -*- mode: python ; coding: utf-8 -*-

import os
import sys

block_cipher = None

app_name = "Droptical API Example Client"
company_name = "droptical GmbH"
copyright_text = "© 2025 droptical GmbH"

project_root = os.path.abspath('../..')
script_path = 'main.py'

# One icon set for both platforms so the app looks the same everywhere.
icon_path = 'assets/app-icon.ico'          # Windows .exe
macos_icon = 'assets/app-icon.icns'        # macOS .app

# Version is read from the installed package so it never drifts from pyproject.
app_version = "2.0.0"
try:
    from importlib.metadata import version as _pkg_version
    app_version = _pkg_version("droptical-api-client")
except Exception:
    pass

# Windows version resource (Company / Product / Copyright shown in the file's
# Details tab). Built only on Windows; any failure falls back to no resource so
# the build can never break over metadata.
version_file = None
if sys.platform == "win32":
    try:
        _n = [int(p) for p in app_version.split("+")[0].split(".")][:4]
        _v = tuple((_n + [0, 0, 0, 0])[:4])
        _vtext = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={_v}, prodvers={_v},
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', '{company_name}'),
      StringStruct('FileDescription', '{app_name}'),
      StringStruct('FileVersion', '{app_version}'),
      StringStruct('InternalName', '{app_name}'),
      StringStruct('LegalCopyright', '{copyright_text}'),
      StringStruct('OriginalFilename', '{app_name}.exe'),
      StringStruct('ProductName', '{app_name}'),
      StringStruct('ProductVersion', '{app_version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)"""
        import tempfile
        _vf = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
        _vf.write(_vtext)
        _vf.close()
        version_file = _vf.name
    except Exception:
        version_file = None

a = Analysis(
    [script_path],
    pathex=[project_root],
    binaries=[],
    datas=[('assets', 'assets')],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=app_name,
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
    icon=icon_path,
    version=version_file,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=app_name,
)

# macOS-only: wrap the collected output in a proper .app bundle (ignored by
# PyInstaller on Windows/Linux). The Info.plist carries the version + copyright
# so Finder's "Get Info" shows real metadata.
app = BUNDLE(
    coll,
    name=f'{app_name}.app',
    icon=macos_icon,
    bundle_identifier='com.droptical.api-example-client',
    version=app_version,
    info_plist={
        'CFBundleName': app_name,
        'CFBundleDisplayName': app_name,
        'CFBundleShortVersionString': app_version,
        'CFBundleVersion': app_version,
        'NSHumanReadableCopyright': copyright_text,
        'NSHighResolutionCapable': True,
    },
)
