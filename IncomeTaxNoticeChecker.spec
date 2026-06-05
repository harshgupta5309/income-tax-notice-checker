# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

# Inject our HTML file and required Playwright/Stealth assets into the executable runtime container (_MEIPASS)
import os
import playwright
import playwright_stealth

added_files = [
    ('code.html', '.'),
    (os.path.join(os.path.dirname(playwright.__file__), 'driver'), 'playwright/driver'),
    (os.path.join(os.path.dirname(playwright_stealth.__file__), 'js'), 'playwright_stealth/js')
]

# Exclude unneeded dynamic link dependencies to preserve ~100MB target
# Note: we do NOT exclude numpy/pandas because they are required by our automation reporting backend.
bloat_exclusions = [
    'torch', 'torchvision', 'cv2', 'scipy', 'sklearn', 'matplotlib', 
    'pyarrow', 'jupyter', 'ipython', 'PIL'
]

a = Analysis(
    ['app_gui.py'],
    pathex=[],
    binaries=[],
    datas=added_files,
    hiddenimports=['playwright', 'playwright_stealth', 'openpyxl', 'pandas', 'xlsxwriter', 'pyzipper', 'numpy'],
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
    name='LitigationOS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False, # Hides cmd prompt. Launches the desktop frame cleanly in production GUI mode!
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
