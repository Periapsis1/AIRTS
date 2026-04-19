# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('sounds', 'sounds'), ('sprites', 'sprites')],
    hiddenimports=['numpy', 'pygame', 'systems.ai.base', 'systems.ai.base', 'systems.ai.registry', 'systems.ai.wander', 'ais.coward_bot', 'ais.crash_test_ai', 'ais.easy_ai', 'ais.easy_ai_v1', 'ais.example_ai', 'ais.hard_ai', 'ais.hard_bot_2', 'ais.kite_bot', 'ais.medium_ai', 'ais.medium_ai_v1', 'ais.null_ai', 'ais.terror_bot', 'ais.turtle_ai'],
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
    [],
    exclude_binaries=True,
    name='AIRTS',
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AIRTS',
)
