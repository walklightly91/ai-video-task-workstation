"""跨平台、与界面/播放器隔离的文件操作服务。

所有路径在进入引擎时一次性冻结并校验；引擎不读取 Qt 的当前行、播放器状态或
任何延迟 UI 状态。Windows 使用系统回收站，Linux/macOS 由 Send2Trash 转交各自
桌面环境的回收站实现。
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class FileOperationError(RuntimeError):
    """文件事务被拒绝或无法完成。"""


@dataclass(frozen=True)
class FileOperationResult:
    source: str
    target: str = ""


class FileOperationEngine:
    """仅负责真实文件系统事务；调用方负责确认与刷新 UI。"""

    def __init__(self, allowed_roots: Iterable[str] = ()):
        roots = []
        for raw_path in allowed_roots or ():
            path = self._absolute(raw_path)
            if path and os.path.isdir(path):
                roots.append(path)
        self._allowed_roots = tuple(dict.fromkeys(roots))

    @staticmethod
    def _absolute(path: str) -> str:
        value = str(path or "").strip()
        # Resolve reparse points before enforcing the allowed-root boundary.
        return os.path.realpath(os.path.abspath(value)) if value else ""

    @staticmethod
    def _same_path(left: str, right: str) -> bool:
        return os.path.normcase(os.path.realpath(os.path.abspath(left))) == os.path.normcase(os.path.realpath(os.path.abspath(right)))

    def _assert_safe(self, path: str, *, must_exist: bool = True) -> str:
        absolute = self._absolute(path)
        if not absolute:
            raise FileOperationError("文件操作缺少有效路径。")
        if must_exist and not os.path.exists(absolute):
            raise FileOperationError(f"文件或文件夹不存在：{absolute}")
        if not self._allowed_roots:
            raise FileOperationError("尚未设置允许操作的素材目录。")
        for root in self._allowed_roots:
            try:
                if os.path.commonpath([absolute, root]) == root:
                    return absolute
            except ValueError:
                continue
        raise FileOperationError("操作目标不属于当前加载的素材目录，已拒绝执行。")

    @staticmethod
    def _validate_name(name: str) -> str:
        value = str(name or "").strip()
        if not value or value in {".", ".."}:
            raise FileOperationError("请输入有效名称。")
        forbidden = "\\/\x00"
        if os.name == "nt":
            forbidden += ':*?"<>|'
        if any(char in value for char in forbidden):
            raise FileOperationError("名称包含当前系统不允许的字符。")
        return value

    @staticmethod
    def _unique_destination(source: str, destination_dir: str) -> str:
        name = os.path.basename(source.rstrip(os.sep))
        stem, suffix = os.path.splitext(name)
        target = os.path.join(destination_dir, name)
        index = 2
        while os.path.exists(target):
            target = os.path.join(destination_dir, f"{stem}_{index}{suffix}")
            index += 1
        return target

    def rename(self, source: str, new_name: str) -> FileOperationResult:
        source = self._assert_safe(source)
        new_name = self._validate_name(new_name)
        target = os.path.join(os.path.dirname(source), new_name)
        self._assert_safe(target, must_exist=False)
        if self._same_path(source, target):
            return FileOperationResult(source, target)
        if os.path.exists(target):
            raise FileOperationError("同目录中已存在同名文件或文件夹。")
        os.rename(source, target)
        return FileOperationResult(source, target)

    def transfer_many(self, sources: Iterable[str], destination_dir: str, *, move: bool) -> list[FileOperationResult]:
        destination_dir = self._assert_safe(destination_dir)
        if not os.path.isdir(destination_dir):
            raise FileOperationError("粘贴目标不是文件夹。")
        frozen_sources = []
        seen = set()
        for raw_source in sources or ():
            source = self._assert_safe(raw_source)
            key = os.path.normcase(source)
            if key not in seen:
                frozen_sources.append(source)
                seen.add(key)
        if not frozen_sources:
            raise FileOperationError("没有可操作的文件。")
        plans = []
        for source in frozen_sources:
            if self._same_path(os.path.dirname(source), destination_dir):
                continue
            if os.path.isdir(source):
                try:
                    if os.path.commonpath([source, destination_dir]) == source:
                        raise FileOperationError("不能把文件夹移动或复制到它自身或其子文件夹中。")
                except ValueError:
                    pass
            plans.append((source, self._unique_destination(source, destination_dir)))
        if not plans:
            raise FileOperationError("所选项目已位于目标文件夹。")
        results = []
        for source, target in plans:
            if move:
                shutil.move(source, target)
            elif os.path.isdir(source):
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
            results.append(FileOperationResult(source, target))
        return results

    def trash_many(self, sources: Iterable[str]) -> list[FileOperationResult]:
        frozen_sources = []
        seen = set()
        for raw_source in sources or ():
            source = self._assert_safe(raw_source)
            key = os.path.normcase(source)
            if key not in seen:
                frozen_sources.append(source)
                seen.add(key)
        if not frozen_sources:
            raise FileOperationError("没有可删除的文件。")
        try:
            from send2trash import send2trash
        except Exception as exc:
            raise FileOperationError("回收站组件不可用，请重新运行安装程序后再试。") from exc
        for source in frozen_sources:
            send2trash(source)
        return [FileOperationResult(source) for source in frozen_sources]

