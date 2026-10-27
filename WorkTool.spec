# -*- mode: python ; coding: utf-8 -*-
"""Windows onedir release specification for 智能素材工作站.

This file deliberately builds an onedir release.  The application uses Qt,
Torch, faster-whisper, VLC and optional external media tools; a onefile build
must unpack hundreds of DLLs to a temporary directory on every start and is
not reliable for those runtimes.
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs, copy_metadata


PROJECT_ROOT = Path(SPECPATH).resolve()
datas = []
binaries = []
hiddenimports = [
    # Modules loaded through importlib or from background workers.
    "vlc",
    "faster_whisper",
    "ctranslate2",
    "librosa",
    "soundfile",
    "sentence_transformers",
    "transformers",
    "accelerate",
    "safetensors",
    "qwen_vl_utils",
    "pynvml",
    "llama_cpp",
    "cn_clip",
    "cv2",
    "PIL",
    "pyautogui",
    "pyperclip",
    "markdown",
    "pandas",
    "openpyxl",
]

# These packages contain plugin files, native DLLs or dynamically discovered
# submodules.  collect_all makes the packaged behavior match the project venv.
for package_name in (
    "PyQt6",
    "PIL",
    "cv2",
    "vlc",
    "faster_whisper",
    "ctranslate2",
    "librosa",
    "soundfile",
    "sentence_transformers",
    "transformers",
    "tokenizers",
    "accelerate",
    "safetensors",
    "qwen_vl_utils",
    "pynvml",
    "llama_cpp",
    "cn_clip",
    "pyautogui",
    "pyperclip",
    "markdown",
    "pandas",
    "openpyxl",
):
    try:
        package_datas, package_binaries, package_hiddenimports = collect_all(package_name)
        datas += package_datas
        binaries += package_binaries
        hiddenimports += package_hiddenimports
    except Exception as exc:
        # Optional capabilities are allowed to remain unavailable.  The app
        # already shows a clear in-product hint when a user invokes one.
        print(f"[package] optional collection skipped: {package_name}: {exc}")

# The official PyInstaller hooks already collect Torch's runtime DLLs.  Adding
# every Torch test/development submodule through collect_all takes many minutes
# and bloats the output without being used by this program, so collect native
# libraries only and keep the actual runtime imports explicit above.
for package_name in ("torch", "torchvision", "torchaudio"):
    try:
        binaries += collect_dynamic_libs(package_name)
    except Exception as exc:
        print(f"[package] Torch runtime library collection skipped: {package_name}: {exc}")

for package_name in (
    "transformers",
    "huggingface-hub",
    "tokenizers",
    "sentence-transformers",
    "faster-whisper",
    "ctranslate2",
    "torch",
    "opencv-python",
    "PyQt6",
):
    try:
        datas += copy_metadata(package_name)
    except Exception:
        pass

icon_file = PROJECT_ROOT / "app_icon.ico"
# ICO 供 Windows 可执行文件与任务栏使用；PNG 供 Qt 在源码/封包运行时稳定加载。
for icon_resource in (icon_file, PROJECT_ROOT / "app_icon.png"):
    if icon_resource.is_file():
        datas.append((str(icon_resource), "."))

a = Analysis(
    [str(PROJECT_ROOT / "main-dev.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyQt5"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="智能素材工作站",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(icon_file) if icon_file.is_file() else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="智能素材工作站",
)
