# -*- mode: python ; coding: utf-8 -*-

import os

datas_list = []
for folder in ['ui', 'core', 'data', 'resources']:
    if os.path.exists(folder):
        datas_list.append((folder, folder))

if os.path.exists('executor.py'):
    datas_list.append(('executor.py', '.'))

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=datas_list,
    hiddenimports=['playwright.sync_api'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,    # <- incluído direto no EXE (onefile)
    a.datas,       # <- incluído direto no EXE (onefile)
    [],
    name='Study_Practices',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
    icon=['resources\\Taty_s-English-Logo.ico'],
    # ONEFILE: empacota tudo em um único .exe
    # sys.executable aponta para o .exe real -> get_app_base_dir() funciona corretamente
)

# ===== REMOVE NAVEGADORES DO PLAYWRIGHT (REDUZ 300+ MB) =====
import shutil
from pathlib import Path

# Em onefile, o PyInstaller extrai para dist/ diretamente
dist_path = Path('dist/_internal')
if not dist_path.exists():
    dist_path = Path('dist')

playwright_browsers = dist_path / 'playwright' / 'driver' / 'package' / '.local-browsers'
if playwright_browsers.exists():
    print(f"\n🗑️  REMOVENDO navegadores do Playwright ({playwright_browsers})...")
    try:
        shutil.rmtree(playwright_browsers)
        print("✅ Navegadores removidos! (~300MB economizados)")
    except Exception as e:
        print(f"⚠️  Aviso ao remover navegadores: {e}")
