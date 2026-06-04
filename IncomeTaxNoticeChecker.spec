# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

datas = [('C:\\Users\\harsh\\AppData\\Local\\Programs\\Python\\Python314\\Lib\\site-packages\\customtkinter', 'customtkinter/')]
datas += collect_data_files('playwright_stealth')


a = Analysis(
    ['income_tax_gui.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=['playwright', 'playwright.sync_api', 'playwright._impl', 'playwright._impl._driver', 'playwright_stealth', 'openpyxl', 'xlsxwriter', 'customtkinter', 'darkdetect', 'pyzipper', 'pycryptodomex', 'Cryptodome'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'torchvision', 'cv2', 'scipy', 'sklearn', 'matplotlib', 'pyarrow', 'jupyter', 'ipython'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='IncomeTaxNoticeChecker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
