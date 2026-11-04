# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_all

block_cipher = None

# 数据文件与依赖收集
datas = [
    ('Addon', 'Addon'),
    ('config.example.json', '.'),
]
binaries = []
hiddenimports = [
    'PyQt6',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'mss',
    'openai',
    'rapidocr_onnxruntime',
    'onnxruntime',
]

# 收集 rapidocr_onnxruntime 及其模型、配置文件
ocr_datas, ocr_binaries, ocr_hidden = collect_all('rapidocr_onnxruntime')
datas += ocr_datas
binaries += ocr_binaries
hiddenimports += ocr_hidden

# 收集 onnxruntime 核心动态链接库
ort_datas, ort_binaries, ort_hidden = collect_all('onnxruntime')
datas += ort_datas
binaries += ort_binaries
hiddenimports += ort_hidden

a = Analysis(
    ['run.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    excludes=[
        'torch',
        'torchvision',
        'torchaudio',
        'matplotlib',
        'scipy',
        'pandas',
        'IPython',
        'jupyter',
        'tkinter',
        'onnxruntime.quantization',
    ],
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='WoWChatTranslator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # 不显示控制台黑窗，软件内部【📜 运行控制台】已内置完整实时日志
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
    name='WoWChatTranslator',
)
