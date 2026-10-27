"""Shared, non-admin Seed-VC environment provisioning.

Both the fresh-machine installer and the desktop repair action use this module,
so the two paths cannot drift into separate dependency sets.
"""
from __future__ import annotations

import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

TORCH_VERSION = "2.4.0"
TORCHVISION_VERSION = "0.19.0"
TORCHAUDIO_VERSION = "2.4.0"
# A verified Windows-compatible fallback for machines where the 2.4 CPU wheel
# cannot load fbgemm because of an unavailable OpenMP runtime.
TORCH_COMPAT_VERSION = "2.3.1"
TORCHVISION_COMPAT_VERSION = "0.18.1"
TORCHAUDIO_COMPAT_VERSION = "2.3.1"
TORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"
TORCH_CUDA_INDEX = "https://download.pytorch.org/whl/cu121"
MSVC_RUNTIME_DLLS = (
    "vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll",
    "msvcp140_1.dll", "msvcp140_2.dll", "concrt140.dll",
    # fbgemm.dll in the Windows CPU wheel also imports the LLVM OpenMP
    # runtime.  It is not necessarily installed by the VC++ redist.
    "vcomp140.dll", "libomp140.x86_64.dll",
)


def _subprocess_no_window_kwargs() -> dict:
    """Keep Seed-VC provisioning invisible when called from the desktop GUI.

    ``pythonw.exe`` has no inherited console on Windows.  Starting ``pip`` or a
    venv ``python.exe`` without these flags therefore creates a distracting
    console/Windows Terminal window after the application is already visible.
    The installer still streams its output back to the in-app log.
    """
    if os.name != "nt":
        return {}
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
        return {
            "startupinfo": startupinfo,
            "creationflags": subprocess.CREATE_NO_WINDOW,
        }
    except Exception:
        return {}


def _runtime_env() -> dict:
    """Use a deterministic UTF-8 child environment for readable diagnostics."""
    env = os.environ.copy()
    env.update({
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_PROGRESS_BAR": "off",
    })
    return env


def _run(command: list[str], timeout: int, log: Callable[[str], None], *, no_output_timeout: int = 900) -> None:
    """Run provisioning commands with visible progress and a real stall boundary.

    ``subprocess.run(capture_output=True)`` hid pip's output until a multi-GB
    CUDA download finished.  On a slow or broken connection the desktop then
    looked frozen for up to two hours.  This reader treats both newline and
    carriage-return pip progress as activity, gives a regular in-app heartbeat,
    and aborts only if the child produces no output for a long, bounded period.
    """
    log("$ " + " ".join(str(item) for item in command[2:]))
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", bufsize=1, env=_runtime_env(),
        **_subprocess_no_window_kwargs(),
    )
    events: queue.Queue[Optional[str]] = queue.Queue()

    def _read_output() -> None:
        buffer: list[str] = []
        try:
            assert process.stdout is not None
            while True:
                char = process.stdout.read(1)
                if not char:
                    break
                if char in "\r\n":
                    if buffer:
                        events.put("".join(buffer))
                        buffer.clear()
                else:
                    buffer.append(char)
            if buffer:
                events.put("".join(buffer))
        finally:
            events.put(None)

    threading.Thread(target=_read_output, name="seed-vc-pip-output", daemon=True).start()
    started = last_activity = last_heartbeat = time.monotonic()
    output: list[str] = []
    last_percent = -5
    reader_done = False
    try:
        while not reader_done or process.poll() is None:
            try:
                line = events.get(timeout=1.0)
            except queue.Empty:
                line = ""
            now = time.monotonic()
            if line is None:
                reader_done = True
            elif line:
                cleaned = str(line).strip()
                if cleaned:
                    last_activity = now
                    output.append(cleaned)
                    # Raw pip progress uses carriage returns.  Keep the UI
                    # responsive without adding thousands of near-identical rows.
                    match = re.search(r"(\d{1,3})%", cleaned)
                    if match:
                        percent = max(0, min(100, int(match.group(1))))
                        if percent >= last_percent + 5 or percent == 100:
                            log(cleaned[-700:])
                            last_percent = percent
                    else:
                        log(cleaned[-700:])
            if now - last_heartbeat >= 12:
                elapsed = int(now - started)
                log(f"Installation is still running ({elapsed // 60}m {elapsed % 60:02d}s). Download progress will appear here when the server responds.")
                last_heartbeat = now
            if no_output_timeout and now - last_activity > no_output_timeout:
                process.kill()
                raise TimeoutError(
                    f"The download server sent no progress for {no_output_timeout // 60} minutes; the stalled installation was stopped."
                )
            if now - started > timeout:
                process.kill()
                raise TimeoutError(f"Installation exceeded its {timeout // 60}-minute safety limit and was stopped.")
        returncode = process.wait(timeout=30)
    finally:
        try:
            if process.poll() is None:
                process.kill()
        except Exception:
            pass
        try:
            if process.stdout:
                process.stdout.close()
        except Exception:
            pass
    if returncode:
        detail = "\n".join(output).strip()[-2400:] or "unknown pip failure"
        raise RuntimeError(detail)


def has_nvidia_cuda() -> bool:
    try:
        return subprocess.run(
            ["nvidia-smi", "-L"], capture_output=True, timeout=10,
            env=_runtime_env(), **_subprocess_no_window_kwargs(),
        ).returncode == 0
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


def _torch_import_result(venv_python: str) -> subprocess.CompletedProcess:
    """单独验证 Torch 原生 DLL，而不是等 Seed-VC 运行时才暴露空白失败。"""
    return subprocess.run(
        [venv_python, "-c", "import torch; print(torch.__version__)"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
        env=_runtime_env(), **_subprocess_no_window_kwargs(),
    )


def _looks_like_windows_torch_dll_error(detail: str) -> bool:
    text = str(detail or "").lower()
    return os.name == "nt" and any(token in text for token in (
        "fbgemm.dll", "winerror 126", "error loading", "specified module could not be found",
    ))


def _repair_project_local_msvc_runtime(venv_python: str, log: Callable[[str], None]) -> int:
    """从本机已存在的合法运行库补齐到 Torch 私有目录，不写系统目录、不需管理员。

    Python 3.11 安装器和 Windows 本身通常已经拥有其中一部分 DLL；把可用副本
    放到 ``torch/lib`` 可避免新的 Seed-VC venv 因系统 PATH/运行库注册损坏而
    无法解析 fbgemm 的依赖。找不到的 DLL 不伪造，后续会给出官方修复说明。
    """
    torch_lib = Path(venv_python).parent.parent / "Lib" / "site-packages" / "torch" / "lib"
    if not torch_lib.is_dir():
        return 0
    candidates = [Path(sys.executable).resolve().parent, Path(sys.base_prefix)]
    if os.name == "nt":
        system_root = Path(os.environ.get("SystemRoot", r"C:\\Windows"))
        candidates.extend((system_root / "System32", system_root / "SysWOW64"))
    copied = 0
    for name in MSVC_RUNTIME_DLLS:
        target = torch_lib / name
        if target.is_file() and target.stat().st_size > 16_000:
            continue
        source = next((folder / name for folder in candidates if (folder / name).is_file()), None)
        if source is None:
            continue
        try:
            shutil.copy2(source, target)
            copied += 1
        except OSError:
            continue
    if copied:
        log(f"已补齐 {copied} 个本机 C++ 运行库到 Seed-VC 私有环境，正在重新验证 PyTorch。")
    return copied


def _windows_torch_runtime_hint(venv_python: str) -> str:
    """Describe a known missing fbgemm dependency without guessing at DLL sites."""
    if os.name != "nt":
        return ""
    torch_lib = Path(venv_python).parent.parent / "Lib" / "site-packages" / "torch" / "lib"
    system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    if not (torch_lib / "libomp140.x86_64.dll").is_file() and not (system32 / "libomp140.x86_64.dll").is_file():
        return (
            "未在 Seed-VC 私有环境或 Windows System32 找到 libomp140.x86_64.dll；"
            "该 LLVM OpenMP 依赖可能是 fbgemm.dll 无法加载的原因，"
            "单独重装 VC++ Redistributable 不一定能补齐它。请只从官方 Microsoft/LLVM 安装来源修复，勿下载来历不明的单个 DLL。\n"
        )
    return ""


def _verify_seed_vc_torch(venv_python: str, log: Callable[[str], None]) -> None:
    result = _torch_import_result(venv_python)
    if result.returncode == 0:
        return
    detail = (result.stderr or result.stdout or "PyTorch import failed").strip()
    if _looks_like_windows_torch_dll_error(detail):
        _repair_project_local_msvc_runtime(venv_python, log)
        result = _torch_import_result(venv_python)
        if result.returncode == 0:
            return
        detail = (result.stderr or result.stdout or detail).strip()
        raise RuntimeError(
            "PyTorch native runtime could not load (fbgemm.dll / WinError 126). "
            "The app tried to repair usable local DLLs inside the private Seed-VC environment, but verification still failed.\n"
            + _windows_torch_runtime_hint(venv_python)
            + "Install or repair Microsoft Visual C++ 2015–2022 Redistributable (x64), then manually click “Install / Continue Install Seed-VC”.\n"
            "Official download: https://aka.ms/vc14/vc_redist.x64.exe\n\n"
            + detail[-1400:]
        )
    raise RuntimeError("PyTorch import verification failed:\n" + detail[-1400:])


def _torch_is_importable(venv_python: str) -> tuple[bool, str]:
    """Return the current private runtime state without modifying it."""
    try:
        result = _torch_import_result(venv_python)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if result.returncode == 0:
        return True, (result.stdout or "PyTorch").strip()
    return False, (result.stderr or result.stdout or "PyTorch import failed").strip()


def install_seed_vc_torch(venv_python: str, log: Callable[[str], None], prefer_cuda: Optional[bool] = None) -> str:
    """Install PyTorch without ever removing a working Seed-VC runtime.

    A normal Seed-VC setup is CPU-first.  CUDA migration is intentionally
    performed in a staging venv by :func:`install_seed_vc_cuda_transactional`;
    this function must therefore never replace a healthy existing stack merely
    because a user opened a diagnostic dialog.
    """
    healthy, detail = _torch_is_importable(venv_python)
    if healthy:
        result = subprocess.run(
            [venv_python, "-c", "import torch; print('cuda' if torch.cuda.is_available() else 'cpu')"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
            env=_runtime_env(), **_subprocess_no_window_kwargs(),
        )
        mode = (result.stdout or "cpu").strip().lower()
        log(f"保留已验证可用的 Seed-VC PyTorch（{detail}，{mode}）；不会卸载或替换它。")
        return "cuda" if mode == "cuda" else "cpu"

    # A half-installed or DLL-broken runtime must not be repeatedly uninstalled
    # and reinstalled.  That cycle was the cause of CPU mode being destroyed.
    site_torch = Path(venv_python).parent.parent / "Lib" / "site-packages" / "torch"
    if site_torch.exists():
        if _looks_like_windows_torch_dll_error(detail):
            _repair_project_local_msvc_runtime(venv_python, log)
            healthy, detail = _torch_is_importable(venv_python)
            if healthy:
                log("Seed-VC 私有 C++ 运行库修复完成，已保留原有 PyTorch。")
                return "cpu"
            raise RuntimeError(
                "现有 Seed-VC CPU PyTorch 因 Windows C++ 运行库无法加载，已原样保留，未卸载。\n"
                + _windows_torch_runtime_hint(venv_python)
                + "请安装或修复 Microsoft Visual C++ 2015–2022 Redistributable (x64)，再点击“安装 / 继续安装 Seed-VC”。\n"
                "官方链接：https://aka.ms/vc14/vc_redist.x64.exe\n\n" + detail[-1400:]
            )
        raise RuntimeError("现有 Seed-VC PyTorch 无法验证，已保留以避免丢失 CPU 回退：\n" + detail[-1400:])

    cuda = bool(prefer_cuda) if prefer_cuda is not None else False
    index = TORCH_CUDA_INDEX if cuda else TORCH_CPU_INDEX
    packages = [f"torch=={TORCH_VERSION}", f"torchvision=={TORCHVISION_VERSION}", f"torchaudio=={TORCHAUDIO_VERSION}"]
    log("Installing " + ("NVIDIA CUDA" if cuda else "CPU") + " PyTorch for Seed-VC (fresh environment; no existing runtime is removed)...")
    _run([
        venv_python, "-m", "pip", "install", "--no-cache-dir", "--progress-bar", "raw",
        "--timeout", "30", "--retries", "2", *packages, "--index-url", index,
    ], 5400, log, no_output_timeout=900)
    _verify_seed_vc_torch(venv_python, log)
    return "cuda" if cuda else "cpu"


def install_seed_vc_dependencies(seed_root: str, venv_python: str, log: Callable[[str], None], prefer_cuda: Optional[bool] = None, *, write_marker: bool = True) -> str:
    """Install Seed-VC dependencies without MSVC or administrator privileges."""
    root = Path(seed_root)
    source = root / "requirements.txt"
    if not source.is_file():
        raise FileNotFoundError(f"Seed-VC requirements are missing: {source}")
    filtered = root / ".videotaskhub_requirements.txt"
    # The desktop application calls inference.py directly; it does not host
    # Seed-VC's standalone Gradio WebUI.  Keep Gradio out of the inference
    # environment so Pillow 13 remains installable and enforced.
    excluded = ("torch", "torchvision", "torchaudio", "resemblyzer", "gradio")
    lines = [line for line in source.read_text(encoding="utf-8").splitlines(True) if not line.lstrip().lower().startswith(excluded)]
    filtered.write_text("".join(lines), encoding="utf-8", newline="\n")
    _run([venv_python, "-m", "pip", "install", "--upgrade", "pip"], 1200, log)
    # Install Torch first. Several remaining packages declare a loose Torch
    # dependency; doing this later lets pip download a second, arbitrary build.
    mode = install_seed_vc_torch(venv_python, log, prefer_cuda)
    _run([venv_python, "-m", "pip", "install", "-r", str(filtered)], 7200, log)
    # The original dependency has no CPython 3.11 Windows wheel. This fork has
    # the same import API (``import webrtcvad``) and prebuilt wheels.
    _run([venv_python, "-m", "pip", "install", "--only-binary=:all:", "webrtcvad-wheels==2.0.14"], 1200, log)
    _run([venv_python, "-m", "pip", "install", "--no-deps", "resemblyzer==0.1.4", "munch==4.0.0", "einops==0.8.0", "descript-audio-codec==1.0.0"], 1800, log)
    _verify_seed_vc_torch(venv_python, log)
    _run([venv_python, "-c", "import PIL,munch,einops,webrtcvad; assert tuple(map(int, PIL.__version__.split('.')[:2])) >= (13, 0); from dac.nn.quantize import VectorQuantize"], 180, log)
    if write_marker:
        (root / ".videotaskhub_seed_vc_ready").write_text(mode + "\n", encoding="ascii")
    return mode


def install_seed_vc_cuda_transactional(seed_root: str, active_python: str, log: Callable[[str], None]) -> str:
    """Upgrade CPU Seed-VC to CUDA through a disposable staging environment.

    The active `.venv` is never touched while downloads, dependency setup, and
    CUDA validation are in progress.  Only a fully verified staging venv is
    swapped in; any failure removes the staging directory and leaves CPU mode
    exactly as it was.
    """
    root = Path(seed_root)
    active_venv = Path(active_python).resolve().parent.parent
    if not active_venv.is_dir():
        raise FileNotFoundError(f"Seed-VC active environment not found: {active_venv}")
    if not has_nvidia_cuda():
        raise RuntimeError("未检测到 NVIDIA CUDA 显卡；未修改当前 CPU PyTorch。")
    staging = root / ".venv.cuda-staging"
    backup = root / ".venv.cpu-backup"
    if staging.exists():
        log("正在清理上次未完成的 CUDA 临时环境；现有 CPU 环境不会受影响。")
        shutil.rmtree(staging, ignore_errors=True)
    try:
        log("正在创建独立 CUDA 临时环境；当前 CPU 模式会保持可用，直到 CUDA 验证通过。")
        _run([sys.executable, "-m", "venv", str(staging)], 900, log)
        stage_python = staging / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not stage_python.is_file():
            raise RuntimeError("CUDA 临时环境创建后未找到 Python。")
        install_seed_vc_dependencies(str(root), str(stage_python), log, prefer_cuda=True, write_marker=False)
        probe = subprocess.run(
            [str(stage_python), "-c", "import torch; assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0))"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
            env=_runtime_env(), **_subprocess_no_window_kwargs(),
        )
        if probe.returncode != 0:
            raise RuntimeError("CUDA 临时环境验证失败：\n" + (probe.stderr or probe.stdout or "CUDA unavailable")[-1400:])
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        log("CUDA 临时环境已验证，正在切换；若切换验证失败会自动恢复 CPU 环境。")
        os.replace(active_venv, backup)
        try:
            os.replace(staging, active_venv)
            _verify_seed_vc_torch(str(active_python), log)
            final_probe = subprocess.run(
                [str(active_python), "-c", "import torch; assert torch.cuda.is_available()"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
                env=_runtime_env(), **_subprocess_no_window_kwargs(),
            )
            if final_probe.returncode != 0:
                raise RuntimeError(final_probe.stderr or final_probe.stdout or "CUDA post-switch verification failed")
        except Exception:
            if active_venv.exists():
                shutil.rmtree(active_venv, ignore_errors=True)
            os.replace(backup, active_venv)
            raise
        shutil.rmtree(backup, ignore_errors=True)
        (root / ".videotaskhub_seed_vc_ready").write_text("cuda\n", encoding="ascii")
        return "cuda"
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise
