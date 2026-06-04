# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

# Asset additions configuration: Injecting our HTML UI file into the compiled extraction folder (_MEIPASS)
added_files = [
    ('tax-litigation-suite.html', '.')
]

# Highly optimized exclusions list to prevent heavy, unused python packages from ballooning the app footprint
bloat_exclusions = [
    'torch', 'torchvision', 'cv2', 'scipy', 'sklearn', 'matplotlib', 
    'pyarrow', 'jupyter', 'ipython', 'PIL'
]

a = Analysis(
    ['app_gui.py'],
    pathex=[],
    binaries=[],
    datas=added_files,
    hiddenimports=['playwright', 'playwright-stealth', 'openpyxl', 'pandas', 'xlsxwriter'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=bloat_exclusions,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='IncomeTaxNoticeChecker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # This hides the terminal window in production and runs the app in pure GUI mode!
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
