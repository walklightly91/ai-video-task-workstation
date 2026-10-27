"""VideoTaskHub 的项目、任务、素材与本地数据存储逻辑（MIT License）。"""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import shutil
import zipfile
from xml.etree import ElementTree
import logging
import sys
import tempfile
from datetime import datetime
from html import escape
from pathlib import Path, PurePosixPath
from typing import Callable
from uuid import uuid4
from credential_protection import protect_sensitive_config, unprotect_sensitive_config


NUMERIC_TXT = re.compile(r"^(\d+)\.txt$", re.IGNORECASE)
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
APP_NAME = "video-task-hub"


def user_data_dir() -> Path:
    """返回各平台的用户级配置目录，避免随程序路径或版本改变。"""
    if os.name == "nt":
        return Path(os.getenv("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path(os.getenv("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / APP_NAME


DEFAULT_DATA_DIR = user_data_dir()
BOOTSTRAP_FILE = DEFAULT_DATA_DIR / "bootstrap.json"


def configured_data_dir() -> Path:
    """从固定引导文件读取可迁移的用户配置目录。"""
    try:
        raw = json.loads(BOOTSTRAP_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and raw.get("data_dir"):
            return Path(str(raw["data_dir"]))
    except (OSError, json.JSONDecodeError):
        pass
    return DEFAULT_DATA_DIR


DATA_DIR = configured_data_dir()
PROJECTS_FILE = DATA_DIR / "projects.json"
INSTRUCTIONS_FILE = DATA_DIR / "instructions.json"
HISTORY_DIR = DATA_DIR / "history"
HISTORY_FILE = HISTORY_DIR / "operations.json"
DEFAULT_LOG_DIR = DEFAULT_DATA_DIR / "logs"
PROJECTS_DIR = DATA_DIR / "projects"
RECENT_FILE = DATA_DIR / "recent_projects.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
MAX_CONFIGURATION_BACKUP_BYTES = 512 * 1024 * 1024


def _startup_log_dir() -> Path:
    """日志路径可由上次保存的系统设置覆盖；错误时安全回退到系统临时目录。"""
    try:
        raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and raw.get("log_dir"):
            return Path(str(raw["log_dir"]))
    except (OSError, json.JSONDecodeError):
        pass
    return DEFAULT_LOG_DIR


LOG_DIR = _startup_log_dir()
LOG_FILE = LOG_DIR / "app.log"


# VideoTaskHub 从全新配置开始：不读取、复制或修改旧版
# dialogue-material-manager 与项目目录 app_data 中的任何用户数据。


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def setup_logging() -> logging.Logger:
    global LOG_DIR, LOG_FILE
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        # 极少数系统会拒绝或临时锁定 Roaming 目录；日志回退不能阻断软件启动。
        LOG_DIR = Path(tempfile.gettempdir()) / APP_NAME / "logs"
        LOG_FILE = LOG_DIR / "app.log"
        LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("video_task_hub")
    if not logger.handlers:
        handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        # 日常运行信息仅在本次会话的内存日志中显示；文件只保留需要排查的警告与异常。
        handler.setLevel(logging.WARNING)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


LOGGER = setup_logging()


def read_system_log() -> str:
    """返回当前系统日志内容，供图形界面显示。"""
    try:
        return LOG_FILE.read_text(encoding="utf-8")
    except OSError:
        return "尚未生成系统日志。"


def clear_system_log() -> None:
    """清空当前日志文件；日志处理器保持可继续写入状态。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text("", encoding="utf-8")


def open_system_path(path: Path) -> None:
    """使用当前系统的文件管理器或默认程序打开日志目录/文件。"""
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def read_json(path: Path, default: list | dict) -> list | dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, data: list | dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def app_settings() -> dict:
    """读取软件级设置，例如 Qt 皮肤；与项目配置相互独立。"""
    return unprotect_sensitive_config(read_json(SETTINGS_FILE, {}))  # type: ignore[return-value]


def save_app_settings(settings: dict) -> None:
    try:
        write_json(SETTINGS_FILE, protect_sensitive_config(settings))
    except OSError:
        # 用户配置目录可能被同步软件、杀毒软件等短暂占用；不应中断界面操作。
        LOGGER.exception("保存软件设置失败：%s", SETTINGS_FILE)


def set_data_directory(target: Path) -> None:
    """复制当前配置到目标目录并写入引导文件；重启后从新目录加载。"""
    target = target.expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    if target != DATA_DIR:
        for source in DATA_DIR.rglob("*") if DATA_DIR.is_dir() else []:
            destination = target / source.relative_to(DATA_DIR)
            if source.is_dir(): destination.mkdir(parents=True, exist_ok=True)
            elif not destination.exists(): destination.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, destination)
    DEFAULT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    BOOTSTRAP_FILE.write_text(json.dumps({"data_dir": str(target)}, ensure_ascii=False, indent=2), encoding="utf-8")


def backup_configuration(output_file: Path) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_file, "w", zipfile.ZIP_DEFLATED) as archive:
        for source in DATA_DIR.rglob("*") if DATA_DIR.is_dir() else []:
            if source.is_file(): archive.write(source, source.relative_to(DATA_DIR))


def _safe_extract_configuration_archive(archive: zipfile.ZipFile, destination_root: Path) -> None:
    """Extract a user-selected backup without allowing Zip Slip or zip bombs."""
    root = destination_root.resolve()
    total_size = 0
    for info in archive.infolist():
        # ZIP uses POSIX separators. Backslashes are rejected as they are path
        # separators on Windows and could bypass a POSIX-only normalisation.
        if not info.filename or "\\" in info.filename:
            raise ValueError("备份包包含不安全的文件路径。")
        relative = PurePosixPath(info.filename)
        if relative.is_absolute() or ".." in relative.parts or any(part.endswith(":") for part in relative.parts):
            raise ValueError("备份包包含越界文件路径。")
        target = (root / Path(*relative.parts)).resolve()
        if target != root and root not in target.parents:
            raise ValueError("备份包尝试写入配置目录之外。")
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        total_size += max(0, int(info.file_size))
        if total_size > MAX_CONFIGURATION_BACKUP_BYTES:
            raise ValueError("备份包解压后超过 512 MB，已拒绝恢复。")
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info, "r") as source, target.open("wb") as output:
            shutil.copyfileobj(source, output, length=1024 * 1024)


def restore_configuration(input_file: Path) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(input_file) as archive:
        _safe_extract_configuration_archive(archive, DATA_DIR)


def initialize_configuration() -> None:
    """清空当前配置数据；不删除原始素材、导出文件及用户的备份包。"""
    # 开发期初始化：彻底回到统一的默认用户目录，不保留旧路径或自定义配置指向。
    if DATA_DIR.is_dir(): shutil.rmtree(DATA_DIR)
    if BOOTSTRAP_FILE.is_file(): BOOTSTRAP_FILE.unlink()
    DEFAULT_DATA_DIR.mkdir(parents=True, exist_ok=True)


def projects() -> list[dict]:
    return read_json(PROJECTS_FILE, [])  # type: ignore[return-value]


def save_project(project: dict) -> dict:
    all_projects = projects()
    project = dict(project)
    project.setdefault("id", str(uuid4()))
    project.setdefault("created_at", now())
    project["updated_at"] = now()
    folder = Path(project.get("input_dir", ""))
    safe_name = re.sub(r'[<>:"/\\|?*]+', "_", project["name"]).strip(". ") or "未命名项目"
    if folder.is_dir():
        project_file = folder / f"{safe_name}.project.json"
    else:
        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        project_file = PROJECTS_DIR / f"{safe_name}_{project['id'][:8]}.project.json"
    project["project_file"] = str(project_file)
    project_file.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
    for index, item in enumerate(all_projects):
        if item["id"] == project["id"]:
            all_projects[index] = project
            break
    else:
        all_projects.append(project)
    write_json(PROJECTS_FILE, all_projects)
    recent = recent_project_ids()
    recent = [project["id"]] + [item for item in recent if item != project["id"]]
    write_json(RECENT_FILE, recent[:10])
    return project


def recent_project_ids() -> list[str]:
    recent = read_json(RECENT_FILE, [])
    # 空列表表示用户已经明确清空最近项目，不能再回退为全部项目。
    if isinstance(recent, list):
        return recent  # type: ignore[return-value]
    return [item["id"] for item in sorted(projects(), key=lambda item: item.get("updated_at", ""), reverse=True)[:10]]


def clear_recent_projects() -> None:
    write_json(RECENT_FILE, [])


def mark_recent_project(project_id: str) -> None:
    """将已保存项目置顶到最近列表，不修改项目文件内容。"""
    if not project_id or not any(item.get("id") == project_id for item in projects()):
        return
    recent = [item for item in recent_project_ids() if item != project_id]
    write_json(RECENT_FILE, [project_id, *recent][:10])


def instructions() -> list[dict]:
    return read_json(INSTRUCTIONS_FILE, [])  # type: ignore[return-value]


def save_instructions(items: list[dict]) -> None:
    write_json(INSTRUCTIONS_FILE, items)


INSTRUCTION_HEADERS = ("指令名称", "分类", "详细指令", "备注")
INSTRUCTION_PACKAGE_MANIFEST = "指令库分类包.json"


def _instruction_package_safe_name(value: str, fallback: str) -> str:
    """Make a Windows-safe display name without changing the logical category."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', '_', str(value or '')).strip(' ._')
    return (cleaned[:80] or fallback)


def export_instruction_package(items: list[dict], folders: list[str], output_dir: Path) -> Path:
    """Export a portable category-folder package, including empty categories.

    The manifest keeps original category paths intact; safe disk names are only
    an implementation detail for Windows file systems.  Each instruction is
    also stored in its own readable JSON file so a package remains inspectable
    and recoverable even outside the application.
    """
    target = Path(output_dir)
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f'导出目录不是空目录：{target}')
    target.mkdir(parents=True, exist_ok=True)
    ordered_folders: list[str] = []
    for folder in [*(folders if isinstance(folders, list) else []), *[str(item.get('folder') or '未分类') for item in items if isinstance(item, dict)]]:
        folder = str(folder or '未分类').strip() or '未分类'
        if folder not in ordered_folders:
            ordered_folders.append(folder)
    folder_dirs: dict[str, Path] = {}
    used_relative: set[str] = set()
    for folder in ordered_folders:
        parts = [part for part in folder.replace('\\', '/').split('/') if part] or ['未分类']
        safe_parts = [_instruction_package_safe_name(part, '未分类') for part in parts]
        relative = Path('分类')
        for part in safe_parts:
            relative /= part
        candidate = relative
        serial = 2
        while candidate.as_posix().lower() in used_relative:
            candidate = relative.parent / f'{relative.name}_{serial}'; serial += 1
        used_relative.add(candidate.as_posix().lower())
        absolute = target / candidate; absolute.mkdir(parents=True, exist_ok=True)
        folder_dirs[folder] = candidate
    records = []
    for number, raw in enumerate((item for item in items if isinstance(item, dict)), 1):
        name = str(raw.get('name') or '').strip()
        if not name:
            continue
        folder = str(raw.get('folder') or '未分类').strip() or '未分类'
        relative_folder = folder_dirs.setdefault(folder, Path('分类') / '未分类')
        (target / relative_folder).mkdir(parents=True, exist_ok=True)
        record = {'name': name, 'folder': folder, 'content': str(raw.get('content') or ''), 'note': str(raw.get('note') or '')}
        file_name = f'{number:03d}_{_instruction_package_safe_name(name, "未命名指令")}.json'
        file_path = target / relative_folder / file_name
        file_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        records.append({**record, 'file': file_path.relative_to(target).as_posix()})
    manifest = {
        'schema': 'videotaskhub-instruction-category-package-v1',
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'folders': [{'path': folder, 'directory': directory.as_posix()} for folder, directory in folder_dirs.items()],
        'instructions': records,
    }
    (target / INSTRUCTION_PACKAGE_MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return target


def import_instruction_package(package_dir: Path) -> tuple[list[dict], list[str]]:
    """Read a category package and return its instructions plus all folders."""
    root = Path(package_dir)
    manifest_path = root / INSTRUCTION_PACKAGE_MANIFEST
    if not root.is_dir() or not manifest_path.is_file():
        raise ValueError(f'未找到“{INSTRUCTION_PACKAGE_MANIFEST}”，请选择完整的指令库分类包文件夹。')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or manifest.get('schema') != 'videotaskhub-instruction-category-package-v1':
        raise ValueError('这不是受支持的指令库分类包。')
    folders = []
    for entry in manifest.get('folders', []):
        path = str(entry.get('path') or '').strip() if isinstance(entry, dict) else ''
        if path and path not in folders:
            folders.append(path)
    result = []
    for entry in manifest.get('instructions', []):
        if not isinstance(entry, dict):
            continue
        # The manifest is self-contained; the per-instruction file is useful
        # for human inspection but never trusted as a path outside this package.
        name = str(entry.get('name') or '').strip()
        if not name:
            continue
        folder = str(entry.get('folder') or '未分类').strip() or '未分类'
        if folder not in folders:
            folders.append(folder)
        result.append({'name': name, 'folder': folder, 'content': str(entry.get('content') or ''), 'note': str(entry.get('note') or '')})
    return result, folders


def export_instruction_items(items: list[dict], output_file: Path, encoding: str = "utf-8") -> None:
    """导出指令库的标准三列表；按文件后缀选择 CSV 或 XLSX。"""
    values = [list(INSTRUCTION_HEADERS)] + [[str(item.get(key, "")) for key in ("name", "folder", "content", "note")] for item in items]
    output_file.parent.mkdir(parents=True, exist_ok=True)
    if output_file.suffix.lower() == ".json":
        output_file.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding=encoding)
        return
    if output_file.suffix.lower() == ".csv":
        with output_file.open("w", encoding=encoding, newline="") as file:
            csv.writer(file).writerows(values)
        return
    _write_simple_xlsx(values, output_file, "指令库", (24, 20, 72, 36))


def import_instruction_items(input_file: Path, encoding: str = "utf-8") -> list[dict]:
    """读取本软件导出的 CSV/XLSX 指令表；空名称行自动忽略。"""
    if input_file.suffix.lower() == ".json":
        raw = json.loads(input_file.read_text(encoding=encoding))
        if not isinstance(raw, list): raise ValueError("JSON 指令文件必须是指令列表。")
        return [{"name":str(item.get("name","")).strip(),"content":str(item.get("content", "")),"note":str(item.get("note", "")),"folder":str(item.get("folder", "未分类"))} for item in raw if isinstance(item,dict) and str(item.get("name","")).strip()]
    if input_file.suffix.lower() == ".csv":
        with input_file.open("r", encoding=encoding, newline="") as file:
            rows = list(csv.reader(file))
    elif input_file.suffix.lower() == ".xlsx":
        with zipfile.ZipFile(input_file) as book:
            xml = book.read("xl/worksheets/sheet1.xml")
        root = ElementTree.fromstring(xml)
        namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        rows = []
        for row in root.findall(".//x:sheetData/x:row", namespace):
            cells = []
            for cell in row.findall("x:c", namespace):
                text = cell.findtext("x:is/x:t", default="", namespaces=namespace)
                cells.append(text)
            rows.append(cells)
    else:
        raise ValueError("仅支持 XLSX、CSV 或 JSON 指令文件。")
    result = []
    for row in rows[1:]:
        row = (row + ["", "", "", ""])[:4]
        if row[0].strip(): result.append({"name": row[0].strip(), "folder": row[1] or "未分类", "content": row[2], "note": row[3]})
    return result


def history() -> list[dict]:
    return read_json(HISTORY_FILE, [])  # type: ignore[return-value]


def clear_history() -> None:
    """清空软件操作历史；不影响项目、素材、导出文件与错误日志。"""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    write_json(HISTORY_FILE, [])
    LOGGER.info("用户清空了操作历史")


def add_history(item: dict) -> None:
    items = history()
    items.insert(0, {"time": now(), **item})
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    write_json(HISTORY_FILE, items)
    LOGGER.info("操作记录：%s | %s", item.get("operation", ""), item.get("result", ""))


def delete_project(project: dict) -> None:
    """删除指定项目的配置文件和全局项目索引，不碰原始素材与导出文件。"""
    project_file = Path(project.get("project_file", ""))
    if project_file.name.endswith(".project.json") and project_file.is_file():
        project_file.unlink()
    write_json(PROJECTS_FILE, [item for item in projects() if item.get("id") != project.get("id")])


def find_image(folder: Path) -> Path | None:
    """按既定优先级寻找和文件夹同名的图片。"""
    for extension in IMAGE_EXTENSIONS:
        candidate = folder / f"{folder.name}{extension}"
        if candidate.is_file():
            return candidate
    return None


def text_files(folder: Path) -> list[tuple[int, Path]]:
    result: list[tuple[int, Path]] = []
    try:
        children = folder.iterdir()
    except OSError:
        return result
    for child in children:
        match = NUMERIC_TXT.fullmatch(child.name) if child.is_file() else None
        if match:
            result.append((int(match.group(1)), child))
    return sorted(result, key=lambda item: (item[0], item[1].name.lower()))


def missing_numbers(numbers: list[int]) -> list[int]:
    if not numbers:
        return []
    expected = set(range(1, max(numbers) + 1))
    return sorted(expected - set(numbers))


def scan(
    root_dir: Path,
    instruction: str,
    encoding: str = "utf-8",
    progress: Callable[[int, int], None] | None = None,
) -> tuple[list[dict], list[str]]:
    """扫描根目录及所有层级，并返回可编辑的 CSV 行和检查信息。"""
    if not root_dir.is_dir():
        raise ValueError(f"扫描目录不存在或不是文件夹：{root_dir}")
    folders = [root_dir] + [path for path in root_dir.rglob("*") if path.is_dir()]
    rows: list[dict] = []
    warnings: list[str] = []
    for position, folder in enumerate(folders, 1):
        if progress:
            progress(position, len(folders))
        image = find_image(folder)
        numbered_files = text_files(folder)
        if not numbered_files and image is None:
            continue
        base = {
            "folder_name": folder.name,
            "folder_path": str(folder.resolve()),
            "image_name": image.name if image else "",
            "image_path": str(image.resolve()) if image else "",
            "command": "",
        }
        if not numbered_files:
            rows.append({**base, "txt_name": "", "image_path": "", "status": "无数字 TXT"})
            warnings.append(f"{folder}: 未找到数字命名的 TXT 文件")
            continue
        numbers = [number for number, _ in numbered_files]
        gaps = missing_numbers(numbers)
        if gaps:
            shown = ", ".join(str(number) for number in gaps)
            warnings.append(f"{folder}: 缺少台词编号 {shown}")
        if image is None:
            warnings.append(f"{folder}: 缺少与文件夹同名的图片")
        for number, txt_file in numbered_files:
            try:
                dialogue = txt_file.read_text(encoding=encoding).strip()
            except (OSError, UnicodeError) as error:
                warnings.append(f"{txt_file}: 无法读取（{error}）")
                dialogue = ""
            status: list[str] = []
            if gaps:
                status.append("编号不连续")
            if image is None:
                status.append("缺少图片")
            if not dialogue:
                status.append("空台词")
            rows.append({
                **base,
                "txt_name": txt_file.name,
                "dialogue": dialogue,
                "command": f"{instruction}{dialogue}",
                "status": "、".join(status) if status else "正常",
            })
    return rows, warnings


CSV_HEADERS = ("文件夹名", "文件夹绝对路径", "台词文件名", "图片名", "图片完整路径", "指令与台词")
CSV_KEYS = ("folder_name", "folder_path", "txt_name", "image_name", "image_path", "command")


def export_csv(rows: list[dict], output_file: Path) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(CSV_HEADERS)
        writer.writerows([[row.get(key, "") for key in CSV_KEYS] for row in rows])


def export_delimited(rows: list[dict], output_file: Path, delimiter: str) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file, delimiter=delimiter)
        writer.writerow(CSV_HEADERS)
        writer.writerows([[row.get(key, "") for key in CSV_KEYS] for row in rows])


def export_xlsx(rows: list[dict], output_file: Path) -> None:
    """用标准 Office Open XML 写入无外部依赖的兼容工作簿。"""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    values = [list(CSV_HEADERS)] + [[str(row.get(key, "")) for key in CSV_KEYS] for row in rows]
    _write_simple_xlsx(values, output_file, "台词素材", (18, 48, 16, 18, 55, 70))


def _write_simple_xlsx(values: list[list[str]], output_file: Path, sheet_name: str, widths: tuple[int, ...]) -> None:
    """写入简单无依赖 XLSX；用于素材表与指令表。"""
    def cell(value: str, col: int, row: int, header: bool = False) -> str:
        ref = f"{chr(65 + col)}{row}"
        style = ' s="1"' if header else ''
        return f'<c r="{ref}" t="inlineStr"{style}><is><t xml:space="preserve">{escape(value)}</t></is></c>'
    sheet_rows = "".join(f'<row r="{r}">' + "".join(cell(value, c, r, r == 1) for c, value in enumerate(line)) + "</row>" for r, line in enumerate(values, 1))
    cols = "".join(f'<col min="{index}" max="{index}" width="{width}" customWidth="1"/>' for index, width in enumerate(widths, 1))
    sheet = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cols>{cols}</cols><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><sheetData>{sheet_rows}</sheetData><autoFilter ref="A1:F{max(len(values), 1)}"/></worksheet>'''
    styles = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="2"><xf xfId="0"/><xf xfId="0" fontId="1" applyFont="1"/></cellXfs></styleSheet>'''
    files = {
        "[Content_Types].xml": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>''',
        "_rels/.rels": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>''',
        "xl/workbook.xml": f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="{escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets></workbook>''',
        "xl/_rels/workbook.xml.rels": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>''',
        "xl/styles.xml": styles, "xl/worksheets/sheet1.xml": sheet,
    }
    with zipfile.ZipFile(output_file, "w", zipfile.ZIP_DEFLATED) as file:
        for name, content in files.items(): file.writestr(name, content)


def export_rows(rows: list[dict], output_file: Path, output_format: str) -> None:
    """先写临时文件，成功后原子替换目标，避免导出失败损坏旧文件。"""
    temporary = output_file.with_name(f".{output_file.stem}.exporting{output_file.suffix}")
    try:
        if output_format == "Excel 工作簿 (.xlsx)":
            export_xlsx(rows, temporary)
        elif output_format == "CSV（分号分隔）":
            export_delimited(rows, temporary, ";")
        elif output_format == "制表符文本 (.tsv)":
            export_delimited(rows, temporary, "\t")
        else:
            export_delimited(rows, temporary, ",")
        os.replace(temporary, output_file)
    finally:
        if temporary.exists():
            temporary.unlink()
