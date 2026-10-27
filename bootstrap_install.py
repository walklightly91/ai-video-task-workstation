"""Fresh-machine installer. Requires only a user-installed Python 3.11."""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from seed_vc_runtime import install_seed_vc_dependencies

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
VENV_PYTHON = VENV / "Scripts" / "python.exe"
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024  # Installer archives should never be multi-GB.
MAX_EXTRACTED_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
# Reviewed upstream source snapshot. Never download a moving branch for an
# executable dependency: a new upstream commit must be reviewed and this value
# deliberately updated before it can enter a fresh installation.
SEED_VC_COMMIT = "51383efd921027683c89e5348211d93ff12ac2a8"
# Pinned Windows x64 GPL essentials build.  Do not replace this with Gyan's
# moving ``ffmpeg-release-essentials.zip`` alias: both the immutable package
# URL and its publisher-provided SHA-256 are required for installation trust.
FFMPEG_VERSION = "9.0.2"
FFMPEG_ARCHIVE_URL = "https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.2-essentials_build.zip"
FFMPEG_ARCHIVE_SHA256 = "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba"


def log(message: str) -> None:
    print(message, flush=True)


def run(command: list[str], timeout: int = 7200) -> None:
    log("$ " + " ".join(str(item) for item in command))
    process = subprocess.Popen(command, cwd=ROOT)
    if process.wait(timeout) != 0:
        raise RuntimeError(f"command failed: {command[0]}")


def download_https_archive(
    url: str,
    destination: Path,
    allowed_hosts: set[str],
    *,
    expected_sha256: str | None = None,
) -> None:
    """Download a bounded installer archive only from an expected HTTPS host."""
    if expected_sha256 and (len(expected_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in expected_sha256.lower())):
        raise ValueError("Installer archive checksum is invalid.")
    request = urllib.request.Request(url, headers={"User-Agent": "VideoTaskHub-Installer/1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        final_url = urlparse(response.geturl())
        if final_url.scheme.lower() != "https" or (final_url.hostname or "").lower() not in allowed_hosts:
            raise RuntimeError("Installer download was redirected to an untrusted location.")
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_ARCHIVE_BYTES:
            raise RuntimeError("Installer archive is unexpectedly large.")
        written = 0
        digest = hashlib.sha256() if expected_sha256 else None
        with destination.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_ARCHIVE_BYTES:
                    raise RuntimeError("Installer archive exceeds the allowed size.")
                if digest is not None:
                    digest.update(chunk)
                output.write(chunk)
        if digest is not None and digest.hexdigest().lower() != expected_sha256.lower():
            destination.unlink(missing_ok=True)
            raise RuntimeError("Installer archive checksum verification failed.")


def safe_archive_relative_path(member_name: str, prefix: str = "") -> Path:
    """Return a safe, relative ZIP destination or reject traversal/Windows paths."""
    if prefix and not member_name.startswith(prefix):
        raise ValueError("archive member is outside the expected source directory")
    relative_name = member_name[len(prefix):] if prefix else member_name
    if not relative_name or "\\" in relative_name:
        raise ValueError("archive member has an unsafe path")
    relative = PurePosixPath(relative_name)
    if relative.is_absolute() or ".." in relative.parts or any(part.endswith(":") for part in relative.parts):
        raise ValueError("archive member escapes the installation directory")
    return Path(*relative.parts)


def read_safe_archive_member(archive: zipfile.ZipFile, member_name: str, maximum_bytes: int) -> bytes:
    """Read only a normal, bounded ZIP member needed by the installer."""
    info = archive.getinfo(member_name)
    if info.is_dir() or int(info.file_size) < 0 or int(info.file_size) > maximum_bytes:
        raise RuntimeError("Installer archive member has an unsafe size.")
    # The installer never needs links.  Reject Unix symlink records explicitly
    # instead of relying on how a particular Python/Windows combination treats
    # their payload.
    if ((int(info.external_attr) >> 16) & 0o170000) == 0o120000:
        raise RuntimeError("Installer archive contains an unsupported symbolic link.")
    return archive.read(info)


def download_ffmpeg() -> None:
    target = ROOT / "tools"
    if (target / "ffmpeg.exe").is_file() and (target / "ffprobe.exe").is_file():
        return
    log(f"Installing pinned FFmpeg {FFMPEG_VERSION} into the project folder...")
    with tempfile.TemporaryDirectory(prefix="videotaskhub_ffmpeg_") as temp:
        archive = Path(temp) / "ffmpeg.zip"
        download_https_archive(
            FFMPEG_ARCHIVE_URL,
            archive,
            {"www.gyan.dev"},
            expected_sha256=FFMPEG_ARCHIVE_SHA256,
        )
        with zipfile.ZipFile(archive) as zf:
            ffmpeg = next((name for name in zf.namelist() if name.endswith("/bin/ffmpeg.exe")), "")
            ffprobe = next((name for name in zf.namelist() if name.endswith("/bin/ffprobe.exe")), "")
            if not ffmpeg or not ffprobe:
                raise RuntimeError("The downloaded FFmpeg archive is incomplete.")
            target.mkdir(parents=True, exist_ok=True)
            (target / "ffmpeg.exe").write_bytes(read_safe_archive_member(zf, ffmpeg, 512 * 1024 * 1024))
            (target / "ffprobe.exe").write_bytes(read_safe_archive_member(zf, ffprobe, 512 * 1024 * 1024))


def download_seed_vc(seed_root: Path) -> None:
    if (seed_root / "inference.py").is_file():
        return
    log("Downloading Seed-VC...")
    with tempfile.TemporaryDirectory(prefix="videotaskhub_seed_vc_") as temp:
        archive = Path(temp) / "seed-vc.zip"
        download_https_archive(
            f"https://github.com/Plachtaa/seed-vc/archive/{SEED_VC_COMMIT}.zip",
            archive,
            {"github.com", "codeload.github.com"},
        )
        with zipfile.ZipFile(archive) as zf:
            prefix = next((name.rsplit("/", 1)[0] + "/" for name in zf.namelist() if name.endswith("/inference.py")), "")
            if not prefix:
                raise RuntimeError("The downloaded Seed-VC archive has no inference.py.")
            seed_root.mkdir(parents=True, exist_ok=True)
            total_uncompressed = 0
            for item in zf.namelist():
                if item.startswith(prefix) and not item.endswith("/"):
                    info = zf.getinfo(item)
                    total_uncompressed += max(0, int(info.file_size))
                    if total_uncompressed > MAX_EXTRACTED_ARCHIVE_BYTES:
                        raise RuntimeError("Seed-VC archive expands beyond the installer safety limit.")
                    destination = seed_root / safe_archive_relative_path(item, prefix)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(read_safe_archive_member(zf, item, MAX_EXTRACTED_ARCHIVE_BYTES))


def install_seed_vc() -> None:
    seed_root = ROOT / "seed-vc"
    download_seed_vc(seed_root)
    seed_python = seed_root / ".venv" / "Scripts" / "python.exe"
    if not seed_python.is_file():
        run([str(VENV_PYTHON), "-m", "venv", str(seed_root / ".venv")], 600)
    mode = install_seed_vc_dependencies(str(seed_root), str(seed_python), log)
    log("Seed-VC ready with " + mode.upper() + " PyTorch.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError("This installer requires Python 3.11.")
    if args.verify:
        log("Python 3.11 detected: " + sys.executable)
        return 0
    if not VENV_PYTHON.is_file():
        log("Creating the project virtual environment...")
        run([sys.executable, "-m", "venv", str(VENV)], 600)
    for requirement in ("requirements-base.txt", "requirements-torch-cpu.txt", "requirements-ai.txt"):
        run([str(VENV_PYTHON), "-m", "pip", "install", "-r", str(ROOT / requirement)])
    # 这两项属于媒体/人声替换能力；网络下载、系统 DLL 或独立 Seed-VC
    # 环境出错时，不应把已安装好的主程序也判成不可启动。
    optional_failures: list[str] = []
    for label, installer in (("FFmpeg", download_ffmpeg), ("Seed-VC", install_seed_vc)):
        try:
            installer()
        except Exception as error:
            optional_failures.append(label)
            log(f"OPTIONAL INSTALL FAILED ({label}): {error}")
    if optional_failures:
        log("CORE INSTALLATION COMPLETE. Run 运行-dev.bat to start VideoTaskHub.")
        log("Optional components still need repair: " + ", ".join(optional_failures))
    else:
        log("INSTALLATION COMPLETE. Run 运行-dev.bat to start VideoTaskHub.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        log("INSTALLATION FAILED: " + str(error))
        raise SystemExit(1)
