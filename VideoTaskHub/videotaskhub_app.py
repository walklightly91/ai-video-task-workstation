"""VideoTaskHub 桌面工作台（MIT License；第三方依赖说明见 NOTICE.md）。"""
from __future__ import annotations

import ctypes
import base64
import csv
import logging
import json
import mimetypes
import os
import re
import shutil
import sys
import tempfile
import uuid
import zipfile
from collections import deque
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree

# 双击本文件时也优先使用“安装Qt运行环境.bat”写入项目内的依赖，不强制要求
# 用户把 PySide6、AI 组件安装到系统 Python。启动批处理仍保留，供兼容旧环境使用。
LOCAL_RUNTIME_DIR=Path(__file__).resolve().parent/"work"/"qtdeps"
if LOCAL_RUNTIME_DIR.is_dir() and str(LOCAL_RUNTIME_DIR) not in sys.path:
    sys.path.insert(0,str(LOCAL_RUNTIME_DIR))

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer, QSize, QSignalBlocker, QThread, Signal, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontMetrics, QGuiApplication, QIcon, QKeySequence, QPainter, QPen, QPixmap, QShortcut, QStandardItem, QStandardItemModel, QTextCursor
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QColorDialog, QComboBox, QFileDialog, QInputDialog,
    QCheckBox, QDialog, QFormLayout, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QListView, QMainWindow, QMenu, QMessageBox as QtMessageBox, QProgressBar, QPushButton, QSlider, QTreeWidget, QTreeWidgetItem,
    QLayout, QScrollArea, QSplitter, QSpinBox, QStackedWidget, QStyle, QStyleOptionComboBox, QTabWidget, QTableWidget, QTableWidgetItem, QTableWidgetSelectionRange, QTextEdit, QTreeView, QVBoxLayout, QWidget)
from videotaskhub_data import (DATA_DIR, LOGGER, LOG_DIR, LOG_FILE, add_history, app_settings, backup_configuration,
    clear_history, clear_recent_projects, clear_system_log, delete_project, export_instruction_items, export_rows, history,
    import_instruction_items, initialize_configuration, instructions, mark_recent_project, open_system_path, projects, read_system_log, recent_project_ids,
    restore_configuration, save_app_settings, save_instructions, save_project, scan, set_data_directory, _write_simple_xlsx)
from videotaskhub_core import (ExpandedCellEditorDialog, MaterialSpreadsheet, ProjectAutoMatchThread,
    clean_long_filename, make_unique_path, render_path_template, segment_english_dialogue, smart_wrap_text)

HEADERS = ("文件夹名", "文件夹绝对路径", "台词文件名", "图片名", "图片完整路径", "指令与台词", "检查状态")
KEYS = ("folder_name", "folder_path", "txt_name", "image_name", "image_path", "command", "status")
FORMATS = ("Excel 工作簿 (.xlsx)", "CSV（逗号分隔）", "CSV（分号分隔）", "制表符文本 (.tsv)")
EXT = {FORMATS[0]: ".xlsx", FORMATS[1]: ".csv", FORMATS[2]: ".csv", FORMATS[3]: ".tsv"}
OUTPUT_MODE_TABLE = "table"
OUTPUT_MODE_MULTI_TXT = "multi_txt"
OUTPUT_MODES = (OUTPUT_MODE_TABLE, OUTPUT_MODE_MULTI_TXT)
VIDEO_SUFFIXES = frozenset({".mp4", ".m4v", ".mov", ".avi", ".mkv", ".webm", ".wmv", ".flv", ".mpeg", ".mpg"})
IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".jfif", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"})
THEMES = {
    "天空蓝（默认）": "#356DF3",       # 清朗、可靠，适合日常工作
    "森林绿": "#448F65",               # 生长、稳定
    "薰衣草紫": "#7759C7",             # 创意、从容
    "暖橙": "#D9822B",                 # 活力、推进
    "远山青": "#248A8A",               # 沉静、专注
    "月光银": "#68778D",               # 克制、专业
    "晨曦金": "#B7791F",               # 灵感、行动
    "玫瑰暮色": "#B95C78",             # 温柔、平衡
    "海盐蓝": "#2878C8",               # 清晰、秩序
    "赤陶棕": "#A65A3F",               # 温暖、沉稳
    "午夜星海（夜间）": "#3D78D8",     # 深夜专注
    "极夜紫（夜间）": "#8167D8",       # 创作沉浸
    "墨玉绿（夜间）": "#2C9B7C",       # 护眼、安定
    "曜石灰（夜间）": "#73839A",       # 极简、专业
}
DARK_THEME_NAMES = frozenset({"午夜星海（夜间）", "极夜紫（夜间）", "墨玉绿（夜间）", "曜石灰（夜间）"})
APP_NAME = "VideoTaskHub"
APP_SUBTITLE = "AI 视频任务工作台"
APP_VERSION = "1.4.0"


def application_icon_path():
    """同时兼容源码直启与 PyInstaller 封装后的应用图标资源路径。"""
    return Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parent))/"assets"/"app_icon.ico"


def apply_windows_application_identity():
    """在窗口创建前设置 Windows 任务栏标识，避免直启 .py 显示 Python 图标。"""
    if os.name == "nt":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("com.videotaskhub.desktop")
        except (AttributeError,OSError):
            LOGGER.warning("未能设置 Qt Windows 应用标识")


def configure_readable_menu(menu, accent="#356DF3"):
    """为自定义右键菜单提供不透明、无阴影且高对比度的统一视觉。"""
    color=QColor(accent)
    menu.setAttribute(Qt.WA_TranslucentBackground,False)
    menu.setAttribute(Qt.WA_OpaquePaintEvent,True)
    try:
        menu.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint,True)
    except AttributeError:
        pass
    menu.setFont(QFont("Microsoft YaHei UI",11))
    menu.setStyleSheet(
        f"QMenu{{background:#FFFFFF;color:#172B3A;border:1px solid {color.lighter(145).name()};border-radius:6px;padding:4px;}}"
        "QMenu::item{background:#FFFFFF;color:#172B3A;padding:8px 32px 8px 14px;border-radius:4px;}"
        f"QMenu::item:selected{{background:{color.lighter(185).name()};color:#102A43;font-weight:600;}}"
        "QMenu::item:disabled{color:#7A8793;background:#FFFFFF;}"
        f"QMenu::separator{{height:1px;background:{color.lighter(165).name()};margin:4px 8px;}}"
    )
NAVIGATION_ITEMS = (
    ("material", "素材整理与汇总预览", 8, 6),
    ("project", "项目工作台", 0, 0),
    ("instruction", "指令库", 1, 1),
    ("table", "查看表格", 6, 5),
    ("history", "操作历史", 2, 2),
    ("help", "使用说明", 7, 7),
    ("skin", "皮肤设置", 5, 3),
    ("system", "系统设置", 3, 4),
    ("log", "系统日志", 4, 5),
)


class BackgroundWidget(QWidget):
    """背景图片保持柔和，控件通过半透明卡片保持清晰。"""
    def __init__(self):
        super().__init__(); self.image = QPixmap(); self.opacity = .18; self.base_color = QColor("#EEF8F1")
        self.zoom=1.0; self.offset_x=0; self.offset_y=0; self.drag_origin=None; self.on_transform_changed=None; self.interactive=False
        self.setFocusPolicy(Qt.StrongFocus); self.setCursor(Qt.ArrowCursor)

    def set_interactive(self, enabled: bool):
        self.interactive=enabled; self.drag_origin=None; self.setCursor(Qt.ArrowCursor)

    def set_skin(self, path: str, opacity: int, color: str, zoom: float=1.0, offset_x: int=0, offset_y: int=0):
        self.image = QPixmap(path) if path and Path(path).is_file() else QPixmap()
        self.opacity = max(0, min(100, opacity)) / 100; self.base_color = QColor(color); self.zoom=zoom; self.offset_x=offset_x; self.offset_y=offset_y; self.update()

    def paintEvent(self, event):
        painter = QPainter(self); painter.fillRect(self.rect(), self.base_color)
        if not self.image.isNull():
            base=max(self.width()/self.image.width(),self.height()/self.image.height())
            pixmap=self.image.scaled(max(1,int(self.image.width()*base*self.zoom)),max(1,int(self.image.height()*base*self.zoom)),Qt.KeepAspectRatio,Qt.SmoothTransformation)
            painter.setOpacity(self.opacity); painter.drawPixmap((self.width()-pixmap.width())//2+self.offset_x,(self.height()-pixmap.height())//2+self.offset_y,pixmap)

    def emit_transform(self):
        if self.on_transform_changed: self.on_transform_changed(self.zoom,self.offset_x,self.offset_y)

    def mousePressEvent(self,event):
        if self.interactive and event.button()==Qt.LeftButton: self.drag_origin=event.position().toPoint(); self.setFocus()

    def mouseMoveEvent(self,event):
        if self.interactive and self.drag_origin is not None:
            point=event.position().toPoint(); self.offset_x+=point.x()-self.drag_origin.x(); self.offset_y+=point.y()-self.drag_origin.y(); self.drag_origin=point; self.update(); self.emit_transform()

    def mouseReleaseEvent(self,event):
        self.drag_origin=None; self.setCursor(Qt.ArrowCursor)

    def keyPressEvent(self,event):
        if not self.interactive:
            super().keyPressEvent(event); return
        step=20 if event.modifiers() & Qt.ShiftModifier else 8
        moves={Qt.Key_Left:(-step,0),Qt.Key_Right:(step,0),Qt.Key_Up:(0,-step),Qt.Key_Down:(0,step)}
        if event.key() in moves:
            dx,dy=moves[event.key()]; self.offset_x+=dx; self.offset_y+=dy; self.update(); self.emit_transform(); event.accept(); return
        super().keyPressEvent(event)

    def wheelEvent(self,event):
        if not self.interactive:
            super().wheelEvent(event); return
        self.zoom=max(.5,min(2.5,self.zoom+(0.1 if event.angleDelta().y()>0 else -0.1))); self.update(); self.emit_transform(); event.accept()


def show_internal_image_preview(parent, image_path):
    """在工作台内显示可缩放大图，不依赖系统外部图片查看器。"""
    path=Path(str(image_path or "").strip())
    pixmap=QPixmap(str(path)) if path.is_file() else QPixmap()
    if pixmap.isNull():
        QtMessageBox.warning(parent,"图片预览",f"找不到或无法读取图片：\n{path or '未提供图片路径'}")
        return
    owner=getattr(parent,"_host_main_window",None)
    if not isinstance(owner,QWidget) or not owner.isVisible():owner=parent
    dialog=QDialog(owner);dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose,True);dialog.setWindowTitle(f"图片大图预览 · {path.name}");dialog.resize(1080,780)
    layout=QVBoxLayout(dialog);layout.setContentsMargins(12,12,12,12)
    hint=QLabel(f"{path.name}　·　滚轮或下方滑块可缩放");hint.setWordWrap(True);layout.addWidget(hint)
    scroll=QScrollArea(dialog);scroll.setWidgetResizable(False);label=QLabel();label.setAlignment(Qt.AlignCenter);label.setStyleSheet("background:#161B22;padding:12px;");scroll.setWidget(label);layout.addWidget(scroll,1)
    controls=QHBoxLayout();controls.addWidget(QLabel("缩放："));zoom=QSlider(Qt.Horizontal);zoom.setRange(25,300);zoom.setValue(100);controls.addWidget(zoom,1);zoom_text=QLabel("100%");controls.addWidget(zoom_text)
    fit=QPushButton("适应窗口");original=QPushButton("原始大小");fullscreen=QPushButton("全屏");close=QPushButton("关闭");controls.addWidget(fit);controls.addWidget(original);controls.addWidget(fullscreen);controls.addWidget(close);layout.addLayout(controls)
    def apply_zoom(value):
        factor=max(.25,min(3.0,int(value)/100));scaled=pixmap.scaled(max(1,int(pixmap.width()*factor)),max(1,int(pixmap.height()*factor)),Qt.KeepAspectRatio,Qt.SmoothTransformation);label.setPixmap(scaled);label.resize(scaled.size());zoom_text.setText(f"{int(value)}%")
    def fit_image():
        size=scroll.viewport().size()
        if size.width()>20 and size.height()>20:zoom.setValue(max(25,min(300,int(min(size.width()/pixmap.width(),size.height()/pixmap.height())*100))))
    def toggle_fullscreen():
        if dialog.isFullScreen():dialog.showNormal();fullscreen.setText("全屏")
        else:dialog.showFullScreen();fullscreen.setText("退出全屏")
    zoom.valueChanged.connect(apply_zoom);fit.clicked.connect(fit_image);original.clicked.connect(lambda:zoom.setValue(100));fullscreen.clicked.connect(toggle_fullscreen);close.clicked.connect(dialog.close);apply_zoom(100);QTimer.singleShot(0,fit_image)
    previews=getattr(owner,"_internal_image_preview_dialogs",[]);previews.append(dialog);owner._internal_image_preview_dialogs=previews
    dialog.destroyed.connect(lambda *_:setattr(owner,"_internal_image_preview_dialogs",[item for item in getattr(owner,"_internal_image_preview_dialogs",[]) if item is not dialog]))
    dialog.show()


class ReviewImageLabel(QLabel):
    """审核台缩略图：可从资源管理器直接拖入图片以替换当前记录。"""
    image_dropped=Signal(str)
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.image_path="";self.setAcceptDrops(True);self.setCursor(Qt.CursorShape.PointingHandCursor)
    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls():event.acceptProposedAction()
        else:event.ignore()
    def dropEvent(self,event):
        urls=event.mimeData().urls()
        if not urls:return
        path=Path(urls[0].toLocalFile())
        if path.is_file() and path.suffix.lower() in {".jpg",".jpeg",".jfif",".png",".webp",".bmp",".gif",".tif",".tiff"}:
            self.image_dropped.emit(str(path));event.acceptProposedAction()
        else:event.ignore()
    def mouseDoubleClickEvent(self,event):
        if event.button()==Qt.LeftButton and self.image_path:
            show_internal_image_preview(self.window(),self.image_path);event.accept();return
        super().mouseDoubleClickEvent(event)


class FlowLayout(QLayout):
    """网页式自动换行布局，避免低宽度下操作按钮被挤出屏幕。"""
    def __init__(self,parent=None,margin=0,spacing=6):
        super().__init__(parent);self._items=[];self.setContentsMargins(margin,margin,margin,margin);self.setSpacing(spacing)
    def addItem(self,item):self._items.append(item)
    def count(self):return len(self._items)
    def itemAt(self,index):return self._items[index] if 0<=index<len(self._items) else None
    def takeAt(self,index):return self._items.pop(index) if 0<=index<len(self._items) else None
    def expandingDirections(self):return Qt.Orientations()
    def hasHeightForWidth(self):return True
    def heightForWidth(self,width):return self._do_layout(QRect(0,0,width,0),True)
    def setGeometry(self,rect):super().setGeometry(rect);self._do_layout(rect,False)
    def sizeHint(self):return self.minimumSize()
    def minimumSize(self):
        size=QSize(0,0)
        for item in self._items:size=size.expandedTo(item.minimumSize())
        left,top,right,bottom=self.getContentsMargins();return size+QSize(left+right,top+bottom)
    def _do_layout(self,rect,test_only):
        left,top,right,bottom=self.getContentsMargins();usable=rect.adjusted(left,top,-right,-bottom);x=usable.x();y=usable.y();line_height=0;space=self.spacing()
        for item in self._items:
            hint=item.sizeHint();next_x=x+hint.width()+space
            if next_x-space>usable.right() and line_height>0:
                x=usable.x();y=y+line_height+space;next_x=x+hint.width()+space;line_height=0
            if not test_only:item.setGeometry(QRect(QPoint(x,y),hint))
            x=next_x;line_height=max(line_height,hint.height())
        return y+line_height-rect.y()+bottom


class DoubleClickComboBox(QComboBox):
    """框体双击展开；右侧箭头仍可单击展开，减少误触选择。"""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.setCursor(Qt.ArrowCursor);self._popup_after_combo_release=False;self._popup_after_line_release=False
    def setEditable(self,editable):
        super().setEditable(editable)
        if editable and self.lineEdit():self.lineEdit().installEventFilter(self)
    def show_popup_after_release(self):
        """在双击完整结束后展开，避开不同 Qt 平台对第二次松开的收起处理。"""
        QTimer.singleShot(0,lambda:self.showPopup() if self.isEnabled() else None)
    def show_pending_combo_popup(self):
        if self._popup_after_combo_release:
            self._popup_after_combo_release=False;self.show_popup_after_release()
    def show_pending_line_popup(self):
        if self._popup_after_line_release:
            self._popup_after_line_release=False;self.show_popup_after_release()
    def eventFilter(self,watched,event):
        if watched is self.lineEdit() and event.type()==QEvent.MouseButtonDblClick:
            self._popup_after_line_release=True;QTimer.singleShot(180,self.show_pending_line_popup);return True
        if watched is self.lineEdit() and event.type()==QEvent.MouseButtonRelease and self._popup_after_line_release:
            self._popup_after_line_release=False;self.show_popup_after_release();return True
        if watched is self.lineEdit() and event.type()==QEvent.MouseButtonPress:
            self.setFocus();return True
        return super().eventFilter(watched,event)
    def mousePressEvent(self,event):
        option=QStyleOptionComboBox();self.initStyleOption(option)
        part=self.style().hitTestComplexControl(QStyle.CC_ComboBox,option,event.position().toPoint(),self)
        if part==QStyle.SC_ComboBoxArrow:super().mousePressEvent(event)
        else:self.setFocus();event.accept()
    def mouseDoubleClickEvent(self,event):
        if event.button()==Qt.LeftButton:
            self._popup_after_combo_release=True;QTimer.singleShot(180,self.show_pending_combo_popup)
        event.accept()
    def mouseReleaseEvent(self,event):
        if event.button()==Qt.LeftButton and self._popup_after_combo_release:
            self._popup_after_combo_release=False;event.accept();self.show_popup_after_release();return
        super().mouseReleaseEvent(event)


class FolderDropLineEdit(QLineEdit):
    """接受资源管理器拖入；拖文件时自动使用其所在目录。"""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.setAcceptDrops(True);self.on_folder_dropped=None
    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls():event.acceptProposedAction()
        else:event.ignore()
    def dropEvent(self,event):
        urls=event.mimeData().urls()
        if not urls:return
        raw_path=urls[0].toLocalFile()
        if not raw_path:return
        path=Path(raw_path)
        folder=path if path.is_dir() else path.parent
        self.setText(str(folder));event.acceptProposedAction()
        if self.on_folder_dropped:self.on_folder_dropped(str(folder))


class RuntimeStatusButton(QPushButton):
    """区分单击与双击：单击展开底部状态栏，双击打开完整日志窗口。"""
    singleClicked=Signal()
    doubleClicked=Signal()
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self._click_timer=QTimer(self);self._click_timer.setSingleShot(True);self._click_timer.setInterval(220);self._click_timer.timeout.connect(self.singleClicked);self.clicked.connect(self._defer_single_click)
    def _defer_single_click(self):self._click_timer.start()
    def mouseDoubleClickEvent(self,event):
        self._click_timer.stop();self.doubleClicked.emit();event.accept()


class SessionLogHandler(logging.Handler):
    """仅存活于当前进程的日志缓冲区；退出时主动释放，不写入磁盘。"""
    def __init__(self,limit=1800):
        super().__init__(logging.DEBUG);self.records=deque(maxlen=max(100,int(limit)));self.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    def emit(self,record):
        try:self.records.append(self.format(record))
        except Exception:pass
    def append(self,message,level="INFO"):
        stamp=datetime.now().strftime("%H:%M:%S");self.records.append(f"{stamp} | {level} | {message}")
    def text(self,limit=800):return "\n".join(list(self.records)[-max(1,int(limit)):])
    def clear(self):self.records.clear()


class CopyableTable(QTableWidget):
    """接近常见在线表格的多单元格编辑：复制、剪切、粘贴、删除与自动扩行。"""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.allow_row_expansion=True;self.allow_column_expansion=False;self.on_bulk_changed=None
    def notify_bulk_changed(self):
        if self.on_bulk_changed:self.on_bulk_changed()
    def copy_selected_cells(self,cut=False):
        indexes=self.selectedIndexes()
        if not indexes:return
        rows=range(min(index.row() for index in indexes),max(index.row() for index in indexes)+1);columns=range(min(index.column() for index in indexes),max(index.column() for index in indexes)+1);selected={(index.row(),index.column()) for index in indexes}
        text="\n".join("\t".join(self.item(row,column).text() if (row,column) in selected and self.item(row,column) else "" for column in columns) for row in rows)
        QGuiApplication.clipboard().setText(text)
        if cut:self.clear_selected_cells()
    def clear_selected_cells(self):
        indexes=self.selectedIndexes()
        if not indexes:return
        old=self.blockSignals(True)
        try:
            for index in indexes:
                item=self.item(index.row(),index.column())
                if item:item.setText("")
        finally:self.blockSignals(old)
        self.notify_bulk_changed()
    def delete_selected_rows(self):
        rows=sorted({index.row() for index in self.selectedIndexes()},reverse=True)
        if not rows:return
        old=self.blockSignals(True)
        try:
            for row in rows:self.removeRow(row)
        finally:self.blockSignals(old)
        self.notify_bulk_changed()
    def paste_cells(self):
        start=self.currentIndex()
        if not start.isValid():return
        lines=QGuiApplication.clipboard().text().replace("\r\n","\n").replace("\r","\n").split("\n")
        if lines and lines[-1]=="":lines.pop()
        cells=[line.split("\t") for line in lines]
        if not cells:return
        needed_rows=start.row()+len(cells);needed_columns=start.column()+max(len(line) for line in cells)
        old=self.blockSignals(True)
        try:
            if self.allow_row_expansion and needed_rows>self.rowCount():self.setRowCount(needed_rows)
            if self.allow_column_expansion and needed_columns>self.columnCount():self.setColumnCount(needed_columns)
            for row_offset,line in enumerate(cells):
                for column_offset,value in enumerate(line):
                    row,column=start.row()+row_offset,start.column()+column_offset
                    if row>=self.rowCount() or column>=self.columnCount():continue
                    item=self.item(row,column)
                    if item:item.setText(value)
                    else:self.setItem(row,column,QTableWidgetItem(value))
        finally:self.blockSignals(old)
        self.notify_bulk_changed()
    def open_expanded_cell_editor(self):
        row,column=self.currentRow(),self.currentColumn()
        if row<0 or column<0:return False
        item=self.item(row,column)
        if item is None:item=QTableWidgetItem("");self.setItem(row,column,item)
        header=self.horizontalHeaderItem(column);name=header.text() if header else f"第 {column+1} 列"
        dialog=ExpandedCellEditorDialog(self.window(),f"编辑单元格｜第 {row+1} 行 · {name}",item.text(),self)
        if dialog.exec()!=QDialog.Accepted:return False
        item.setText(dialog.text_value());self.notify_bulk_changed();return True
    def contextMenuEvent(self,event):
        item=self.itemAt(event.pos())
        if item and not item.isSelected():self.clearSelection();item.setSelected(True);self.setCurrentItem(item)
        menu=QMenu(self);window=self.window();configure_readable_menu(menu,getattr(window,"accent","#356DF3"))
        expand_action=menu.addAction("展开编辑当前单元格（F2）");expand_action.setEnabled(bool(item));expand_action.triggered.connect(self.open_expanded_cell_editor)
        menu.addSeparator()
        cut_action=menu.addAction("剪切");cut_action.setEnabled(bool(self.selectedIndexes()));cut_action.triggered.connect(lambda:self.copy_selected_cells(True))
        copy_action=menu.addAction("复制");copy_action.setEnabled(bool(self.selectedIndexes()));copy_action.triggered.connect(self.copy_selected_cells)
        paste_action=menu.addAction("粘贴");paste_action.setEnabled(bool(item));paste_action.triggered.connect(self.paste_cells)
        clear_action=menu.addAction("清空选中单元格");clear_action.setEnabled(bool(self.selectedIndexes()));clear_action.triggered.connect(self.clear_selected_cells)
        delete_rows=menu.addAction("删除选中行");delete_rows.setEnabled(bool(self.selectedIndexes()));delete_rows.triggered.connect(self.delete_selected_rows)
        menu.addSeparator();all_action=menu.addAction("全选");all_action.triggered.connect(self.selectAll);menu.exec(event.globalPos())
    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_F2 and self.open_expanded_cell_editor():event.accept();return
        if event.matches(QKeySequence.Copy):self.copy_selected_cells();event.accept();return
        if event.matches(QKeySequence.Cut):self.copy_selected_cells(True);event.accept();return
        if event.matches(QKeySequence.Paste):
            self.paste_cells()
            event.accept();return
        if event.key() in (Qt.Key_Delete,Qt.Key_Backspace):self.clear_selected_cells();event.accept();return
        super().keyPressEvent(event)


class LegacyMaterialSpreadsheet(QTableWidget):
    """素材流水线专属工作表，与其他页面表格完全隔离的批量编辑引擎。"""
    changed=Signal()
    IMAGE_EXTENSIONS={".jpg",".jpeg",".png",".webp",".bmp",".gif",".tif",".tiff",".jfif"}
    def __init__(self,rows=40,columns=6,parent=None):
        super().__init__(rows,columns,parent);self.setObjectName("materialSpreadsheet")
        # 不能使用 AllEditTriggers：它会在第一次单击时创建单元格编辑器，导致拖选、Ctrl+C/V
        # 都被内嵌 QLineEdit 截走。这里刻意只保留双击、F2 和直接输入三种编辑入口。
        self.setEditTriggers(QAbstractItemView.DoubleClicked|QAbstractItemView.EditKeyPressed|QAbstractItemView.AnyKeyPressed)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection);self.setSelectionBehavior(QAbstractItemView.SelectItems);self.setAlternatingRowColors(True);self.setWordWrap(True);self.setSortingEnabled(False);self.setAcceptDrops(True);self.setDragDropMode(QAbstractItemView.DropOnly);self.setAutoScroll(True);self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel);self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel);self.setContextMenuPolicy(Qt.CustomContextMenu);self.customContextMenuRequested.connect(self.show_sheet_menu);self._bulk=False;self._undo=[];self._redo=[];self._last_snapshot=self.snapshot();self.itemChanged.connect(self.on_item_changed)
    def snapshot(self):
        return [[self.item(row,column).text() if self.item(row,column) else "" for column in range(self.columnCount())] for row in range(self.rowCount())]
    def restore_snapshot(self,snapshot):
        self._bulk=True;self.blockSignals(True)
        try:
            self.setRowCount(max(1,len(snapshot)));self.setColumnCount(max(6,max((len(row) for row in snapshot),default=6)))
            for row,values in enumerate(snapshot):
                for column,value in enumerate(values):self.setItem(row,column,QTableWidgetItem(value))
        finally:self.blockSignals(False);self._bulk=False
        self._last_snapshot=self.snapshot();self.changed.emit()
    def push_undo(self,before):
        if before==self.snapshot():return
        self._undo.append(before)
        if len(self._undo)>80:self._undo.pop(0)
        self._redo.clear();self._last_snapshot=self.snapshot();self.changed.emit()
    def on_item_changed(self,*_):
        if self._bulk:return
        before=self._last_snapshot
        self.push_undo(before)
    def selected_rect(self):
        indexes=self.selectedIndexes()
        if not indexes:return None
        return min(index.row() for index in indexes),max(index.row() for index in indexes),min(index.column() for index in indexes),max(index.column() for index in indexes),{(index.row(),index.column()) for index in indexes}
    def copy_cells(self,cut=False):
        rect=self.selected_rect()
        if not rect:return
        top,bottom,left,right,selected=rect;text="\n".join("\t".join(self.item(row,column).text() if (row,column) in selected and self.item(row,column) else "" for column in range(left,right+1)) for row in range(top,bottom+1));QGuiApplication.clipboard().setText(text)
        if cut:self.clear_cells()
    def paste_cells(self):
        start=self.currentIndex()
        if not start.isValid():self.setCurrentCell(0,0);start=self.currentIndex()
        raw=QGuiApplication.clipboard().text().replace("\r\n","\n").replace("\r","\n");lines=raw.split("\n")
        if lines and lines[-1]=="":lines.pop()
        values=[line.split("\t") for line in lines]
        if not values:return
        before=self.snapshot();needed_rows=start.row()+len(values);needed_columns=start.column()+max(len(row) for row in values)
        self._bulk=True;self.blockSignals(True)
        try:
            if needed_rows>self.rowCount():self.setRowCount(needed_rows)
            if needed_columns>self.columnCount():
                old_columns=self.columnCount();self.setColumnCount(needed_columns)
                for column in range(old_columns,needed_columns):self.setHorizontalHeaderItem(column,QTableWidgetItem(f"扩展列 {column+1}"))
            for row_offset,row_values in enumerate(values):
                for column_offset,value in enumerate(row_values):
                    row,column=start.row()+row_offset,start.column()+column_offset;item=self.item(row,column)
                    if item:item.setText(value)
                    else:self.setItem(row,column,QTableWidgetItem(value))
        finally:self.blockSignals(False);self._bulk=False
        # 先设定当前格，再扩展选区；反过来设定会让 Qt 取消粘贴区域的首格选择。
        self.push_undo(before);self.clearSelection();self.setCurrentCell(start.row(),start.column());self.setRangeSelected(QTableWidgetSelectionRange(start.row(),start.column(),needed_rows-1,needed_columns-1),True)
    def clear_cells(self):
        indexes=self.selectedIndexes()
        if not indexes:return
        before=self.snapshot();self._bulk=True;self.blockSignals(True)
        try:
            for index in indexes:
                item=self.item(index.row(),index.column())
                if item:item.setText("")
        finally:self.blockSignals(False);self._bulk=False
        self.push_undo(before)
    def delete_selected_rows(self):
        rows=sorted({index.row() for index in self.selectedIndexes()},reverse=True)
        if not rows:return
        before=self.snapshot();self._bulk=True;self.blockSignals(True)
        try:
            for row in rows:self.removeRow(row)
            if self.rowCount()<10:self.setRowCount(10)
        finally:self.blockSignals(False);self._bulk=False
        self.push_undo(before)
    def add_rows(self,count=1):
        before=self.snapshot();self._bulk=True;self.blockSignals(True)
        try:self.setRowCount(self.rowCount()+count)
        finally:self.blockSignals(False);self._bulk=False
        self.push_undo(before)
    def clear_sheet(self,minimum_rows=40):
        """清空整个工作表，但保留独立表格的结构与撤销记录。"""
        before=self.snapshot();self._bulk=True;self.blockSignals(True)
        try:
            self.setRowCount(max(1,minimum_rows))
            for row in range(self.rowCount()):
                for column in range(self.columnCount()):self.setItem(row,column,QTableWidgetItem(""))
        finally:self.blockSignals(False);self._bulk=False
        self.clearSelection();self.setCurrentCell(0,0);self.push_undo(before)
    def undo_sheet(self):
        if not self._undo:return
        current=self.snapshot();snapshot=self._undo.pop();self._redo.append(current);self.restore_snapshot(snapshot)
    def redo_sheet(self):
        if not self._redo:return
        current=self.snapshot();snapshot=self._redo.pop();self._undo.append(current);self.restore_snapshot(snapshot)
    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls() or event.mimeData().hasText():event.acceptProposedAction()
        else:event.ignore()
    def dropEvent(self,event):
        index=self.indexAt(event.position().toPoint())
        if not index.isValid():index=self.currentIndex()
        if not index.isValid():index=self.model().index(0,0)
        urls=event.mimeData().urls()
        if urls:
            paths=[url.toLocalFile() for url in urls if url.toLocalFile()]
            if paths:
                before=self.snapshot();self._bulk=True;self.blockSignals(True)
                try:
                    for offset,path in enumerate(paths):
                        row=index.row()+offset
                        if row>=self.rowCount():self.setRowCount(row+1)
                        column=1 if Path(path).suffix.lower() in self.IMAGE_EXTENSIONS and self.columnCount()>1 else index.column();self.setItem(row,column,QTableWidgetItem(path))
                finally:self.blockSignals(False);self._bulk=False
                self.push_undo(before);event.acceptProposedAction();return
        if event.mimeData().hasText():QGuiApplication.clipboard().setText(event.mimeData().text());self.setCurrentIndex(index);self.paste_cells();event.acceptProposedAction();return
        event.ignore()
    def show_sheet_menu(self,point):
        item=self.itemAt(point)
        if item and not item.isSelected():self.clearSelection();item.setSelected(True);self.setCurrentItem(item)
        menu=QMenu(self);configure_readable_menu(menu,getattr(self.window(),"accent","#356DF3"))
        menu.addAction("撤销",self.undo_sheet).setEnabled(bool(self._undo));menu.addAction("重做",self.redo_sheet).setEnabled(bool(self._redo));menu.addSeparator();menu.addAction("剪切",lambda:self.copy_cells(True));menu.addAction("复制",self.copy_cells);menu.addAction("粘贴",self.paste_cells);menu.addAction("清空选中单元格",self.clear_cells);menu.addAction("删除选中行",self.delete_selected_rows);menu.addSeparator();menu.addAction("新增一行",self.add_rows);menu.addAction("全选",self.selectAll);menu.exec(self.viewport().mapToGlobal(point))
    def keyPressEvent(self,event):
        if event.matches(QKeySequence.Copy):self.copy_cells();event.accept();return
        if event.matches(QKeySequence.Cut):self.copy_cells(True);event.accept();return
        if event.matches(QKeySequence.Paste) or (event.modifiers()==(Qt.ControlModifier|Qt.ShiftModifier) and event.key()==Qt.Key_V):self.paste_cells();event.accept();return
        if event.matches(QKeySequence.Undo):self.undo_sheet();event.accept();return
        if event.matches(QKeySequence.Redo):self.redo_sheet();event.accept();return
        if event.key() in (Qt.Key_Delete,Qt.Key_Backspace):self.clear_cells();event.accept();return
        super().keyPressEvent(event)


class MaterialAiMatchThread(QThread):
    """素材流水线的后台图文匹配：支持 OpenAI 兼容视觉 API 与本地 CLIP。"""
    progress=Signal(int,str);matched=Signal(int,str,float);failed=Signal(str);completed=Signal(int,bool,str)
    IMAGE_EXTENSIONS={".jpg",".jpeg",".png",".webp",".bmp",".gif",".tif",".tiff"}
    def __init__(self,rows,image_paths,config,parent=None):
        super().__init__(parent);self.rows=rows;self.image_paths=image_paths;self.config=config;self.stop_requested=False
    def stop(self):self.stop_requested=True
    def remote_pick(self,text,candidates):
        import requests
        api_base=str(self.config.get("api_base","")).strip().rstrip("/");api_key=str(self.config.get("api_key","")).strip();model=str(self.config.get("model","")).strip()
        if not api_base or not api_key or not model:raise ValueError("请先在 AI 配置中填写接口地址、API Key 与模型名称。")
        content=[{"type":"text","text":f"请为下列文案选择最匹配的一张图片。只返回图片编号，不要解释。\n文案：{text}"}]
        for index,path in enumerate(candidates,1):
            mime=mimetypes.guess_type(str(path))[0] or "image/jpeg";data=base64.b64encode(Path(path).read_bytes()).decode("ascii");content.append({"type":"text","text":f"图片编号 {index}"});content.append({"type":"image_url","image_url":{"url":f"data:{mime};base64,{data}"}})
        response=requests.post(api_base+"/chat/completions",headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"},json={"model":model,"messages":[{"role":"user","content":content}],"temperature":0},timeout=120);response.raise_for_status();answer=str(response.json()["choices"][0]["message"]["content"]);match=re.search(r"\d+",answer)
        if not match:raise ValueError(f"AI 未返回图片编号：{answer[:100]}")
        return int(match.group())-1,1.0
    def clip_pick(self,text,candidates,model_cache):
        import torch
        from PIL import Image
        from transformers import CLIPModel,CLIPProcessor
        if not model_cache:
            model_name=str(self.config.get("clip_model","") or "OFA-Sys/chinese-clip-vit-large-patch14");processor=CLIPProcessor.from_pretrained(model_name);model=CLIPModel.from_pretrained(model_name);device="cuda" if torch.cuda.is_available() and self.config.get("clip_gpu",True) else "cpu";model.to(device);model.eval();model_cache.extend((processor,model,device))
        processor,model,device=model_cache;images=[Image.open(path).convert("RGB") for path in candidates];inputs=processor(text=[text],images=images,return_tensors="pt",padding=True).to(device)
        with torch.no_grad():scores=model(**inputs).logits_per_text[0].softmax(dim=0);index=int(scores.argmax().item());return index,float(scores[index].item())
    def run(self):
        used=set();model_cache=[];matched_count=0;success=True;error_text=""
        try:
            for position,(row_index,text) in enumerate(self.rows,1):
                if self.stop_requested:break
                candidates=[path for path in self.image_paths if path not in used]
                if not candidates:break
                candidates=candidates[:min(8,len(candidates))] if self.config.get("mode")=="api" else candidates
                try:index,score=self.remote_pick(text,candidates) if self.config.get("mode")=="api" else self.clip_pick(text,candidates,model_cache);path=candidates[max(0,min(index,len(candidates)-1))];used.add(path);self.matched.emit(row_index,str(path),score)
                except Exception as error:success=False;error_text=str(error);self.failed.emit(error_text);break
                matched_count+=1
                self.progress.emit(round(position*100/max(1,len(self.rows))),f"已匹配 {position}/{len(self.rows)}")
        except Exception as error:success=False;error_text=str(error);self.failed.emit(error_text)
        finally:self.completed.emit(matched_count,success,error_text)


class MaterialAuditThread(QThread):
    """审核台的远程视觉审核线程：只在用户已选择远程 API 时调用，不改动原始素材。"""
    progress=Signal(int);reviewed=Signal(int,str,str,str);failed=Signal(str);completed=Signal()
    def __init__(self,rows,config,parent=None):
        super().__init__(parent);self.rows=rows;self.config=config;self.stop_requested=False
    def stop(self):self.stop_requested=True
    @staticmethod
    def image_url(path):
        try:
            from PIL import Image
            import io
            with Image.open(path) as image:
                image=image.convert("RGB");image.thumbnail((640,640));buffer=io.BytesIO();image.save(buffer,format="JPEG",quality=78);data=base64.b64encode(buffer.getvalue()).decode("ascii")
            return "data:image/jpeg;base64,"+data
        except Exception:
            mime=mimetypes.guess_type(path)[0] or "image/jpeg";return f"data:{mime};base64,"+base64.b64encode(Path(path).read_bytes()).decode("ascii")
    def run(self):
        try:
            import requests
            base=str(self.config.get("api_base","")).strip().rstrip("/");model=str(self.config.get("model","")).strip();keys=[str(value).strip() for value in self.config.get("api_keys",[]) if str(value).strip()] or [str(self.config.get("api_key","")).strip()]
            if not base or not model or not any(keys):raise ValueError("请先在 AI 配置中选择远程视觉 API，并填写接口、模型和 API Key。")
            for index,row in enumerate(self.rows,1):
                if self.stop_requested:break
                extra=str(self.config.get("review_prompt","")).strip();rules=str(self.config.get("review_rules","")).strip()
                prompt=((extra+"\n\n") if extra else "")+("请审核图片是否适合对应文案。仅返回三行：\n"
                        "结论：已通过、文案不贴切、视觉问题、人工复核 四选一\n说明：一句简明理由\n建议：如需修改，给出改图或改文案建议\n\n"
                        f"中文文案：{row['cn']}\n英文文案：{row['en']}\n备注：{row['remark']}"+(f"\n视觉规则：{rules}" if rules else ""))
                payload={"model":model,"messages":[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":self.image_url(row['image'])}}]}],"temperature":0,"max_tokens":220}
                answer="";last_error=""
                for key in keys:
                    try:
                        response=requests.post(base+"/chat/completions",headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},json=payload,timeout=120);response.raise_for_status();answer=str(response.json()["choices"][0]["message"]["content"] or "").strip()
                        if answer:break
                    except Exception as error:last_error=str(error)
                if not answer:raise RuntimeError(last_error or "视觉 API 未返回审核结果")
                status="人工复核";reason="";suggestion=""
                for line in answer.splitlines():
                    line=line.strip()
                    if "结论" in line:
                        conclusion=line.split("：",1)[-1].strip()
                        status=next((value for value in ("已通过","文案不贴切","视觉问题","人工复核") if value in conclusion),"人工复核")
                    elif "说明" in line:reason=line.split("：",1)[-1].strip()
                    elif "建议" in line:suggestion=line.split("：",1)[-1].strip()
                self.reviewed.emit(row["audit_row"],status,reason or answer[:220],suggestion);self.progress.emit(round(index*100/max(1,len(self.rows))))
        except Exception as error:self.failed.emit(str(error))
        finally:self.completed.emit()


class ThemedMessageBox:
    """兼容 QMessageBox 调用，并将应用提示统一交给当前皮肤渲染。

    子页面通常把自己作为 parent；它们本身没有 ``themed_message``。过去这里
    只检查一层 parent，便会退回 Qt 原生 QMessageBox，导致原生黑底与当前
    浅色/夜间皮肤发生冲突。向上寻找实际皮肤宿主后，所有子页面共用同一入口。
    """
    Yes = QtMessageBox.Yes
    No = QtMessageBox.No
    Ok = QtMessageBox.Ok
    _registered_theme_host = None

    @classmethod
    def register_theme_host(cls, host):
        """登记唯一主题宿主，供被嵌入后失去父子层级的页面使用。"""
        cls._registered_theme_host = host

    @classmethod
    def _registered_host(cls):
        host = cls._registered_theme_host
        try:
            return host if host is not None and callable(getattr(host, "themed_message", None)) else None
        except RuntimeError:
            # Qt 对象已释放时不能继续保留旧引用，后续回到安全的普通查找逻辑。
            cls._registered_theme_host = None
            return None

    @staticmethod
    def _theme_host(parent):
        """从任意子控件向上定位负责当前皮肤的主窗口。"""
        current=parent if isinstance(parent,QWidget) else QApplication.activeWindow()
        visited=set()
        while isinstance(current,QWidget) and id(current) not in visited:
            visited.add(id(current))
            if callable(getattr(current,"themed_message",None)):
                return current
            current=current.parentWidget()
        # 嵌入主程序时业务页会被 take/remove 后重新挂载，父级链不再能到达
        # VideoTaskHub 的 App；此时必须使用启动时登记的唯一主题宿主。
        return ThemedMessageBox._registered_host()

    @staticmethod
    def _show(parent, level, title, text):
        host=ThemedMessageBox._theme_host(parent)
        if host is not None:
            return host.themed_message(level, title, text)
        # 仅保留给启动早期、尚未创建主窗口的异常提示；正常业务弹窗不会走到这里。
        fallback = getattr(QtMessageBox, level)
        return fallback(parent, title, text)

    @staticmethod
    def information(parent, title, text): return ThemedMessageBox._show(parent, "information", title, text)
    @staticmethod
    def warning(parent, title, text): return ThemedMessageBox._show(parent, "warning", title, text)
    @staticmethod
    def critical(parent, title, text): return ThemedMessageBox._show(parent, "critical", title, text)
    @staticmethod
    def question(parent, title, text): return ThemedMessageBox._show(parent, "question", title, text)


# 保留原有调用写法，所有应用内提示都会自动采用当前皮肤。
QMessageBox = ThemedMessageBox


class InstructionTree(QTreeWidget):
    """允许把指令文件拖到分类文件夹；实际持久化由窗口回调处理。"""
    def __init__(self, moved_callback, parent=None):
        super().__init__(parent); self.moved_callback=moved_callback
        self.setDragEnabled(True);self.setAcceptDrops(True);self.setDropIndicatorShown(True);self.setDragDropMode(QAbstractItemView.InternalMove)
    def dropEvent(self,event):
        # Qt 完成内部移动后会改变 selectedItems；必须提前保存拖动源，
        # 否则会把目标文件夹误判为正在移动的项目。
        dragged=list(self.selectedItems());target=self.itemAt(event.position().toPoint());super().dropEvent(event)
        if target:self.moved_callback(target,dragged)


class InstructionAlbumList(QListWidget):
    """Accept image files from other software and bitmap/file clipboard content."""
    def __init__(self, receive_callback, parent=None):
        super().__init__(parent);self.receive_callback=receive_callback;self.setAcceptDrops(True);self.viewport().setAcceptDrops(True)
    @staticmethod
    def _payload(mime):
        paths=[]
        if mime.hasUrls():
            paths=[url.toLocalFile() for url in mime.urls() if url.isLocalFile()]
        image=mime.imageData() if mime.hasImage() else None
        return paths,image
    def dragEnterEvent(self,event):
        paths,image=self._payload(event.mimeData())
        if paths or image is not None:event.acceptProposedAction()
        else:event.ignore()
    def dragMoveEvent(self,event):self.dragEnterEvent(event)
    def dropEvent(self,event):
        paths,image=self._payload(event.mimeData())
        if paths or image is not None:self.receive_callback(paths,image,"拖入");event.acceptProposedAction()
        else:event.ignore()
    def keyPressEvent(self,event):
        if event.matches(QKeySequence.StandardKey.Paste):
            paths,image=self._payload(QApplication.clipboard().mimeData())
            if paths or image is not None:self.receive_callback(paths,image,"粘贴");event.accept();return
        super().keyPressEvent(event)


class InstructionAlbumCover(QLabel):
    """A visible cover card that opens the app's own album viewer on double-click."""
    def __init__(self, open_callback, parent=None):
        super().__init__(parent);self.open_callback=open_callback;self.setCursor(Qt.CursorShape.PointingHandCursor)
    def mouseDoubleClickEvent(self,event):
        self.open_callback();event.accept()


class App(QMainWindow):
    def __init__(self):
        super().__init__(); ThemedMessageBox.register_theme_host(self); QApplication.instance().installEventFilter(self); self.rows=[]; self.warnings=[]; self.active=None; self.inst_index=None; self.instruction_editing=False;self.runtime_log_handler=SessionLogHandler();LOGGER.addHandler(self.runtime_log_handler);self.runtime_log_handler.append("VideoTaskHub 本次运行会话已启动"); self.settings=app_settings(); self.settings.setdefault("application_id","video-task-hub"); self.settings.setdefault("settings_schema_version",1); save_app_settings(self.settings); self.ensure_cross_platform_system_paths(); self.repair_unsafe_temp_directory(); self.theme_name=str(self.settings.get("skin_theme","") or "");self.accent=self.settings.get("skin_accent",THEMES["天空蓝（默认）"]);self.theme_name=self.theme_name if self.theme_name in THEMES else next((name for name,value in THEMES.items() if value.lower()==str(self.accent).lower()),"自定义颜色");self.accent=THEMES[self.theme_name] if self.theme_name in THEMES else self.accent;self.dark_theme=self.theme_name in DARK_THEME_NAMES; self.image_zoom=float(self.settings.get("skin_zoom",1)); self.image_x=int(self.settings.get("skin_offset_x",0)); self.image_y=int(self.settings.get("skin_offset_y",0)); self.nav_opacity=int(self.settings.get("skin_nav_opacity",70 if self.settings.get("skin_background") else 100)); self.skin_editing=False
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}");screen=QGuiApplication.primaryScreen();available=screen.availableGeometry() if screen else None;screen_width=available.width() if available else 1366;screen_height=available.height() if available else 768;auto_scale=max(.78,min(1.0,screen_width/1366,screen_height/768));scale_preference=float(self.settings.get("ui_scale_preference",1.0) or 1.0);self.ui_scale=max(.70,min(1.20,auto_scale*scale_preference));default_width=min(1180,max(820,screen_width-32));default_height=min(800,max(560,screen_height-32));minimum_width=min(760,max(360,screen_width));minimum_height=min(520,max(300,screen_height));self.setMinimumSize(minimum_width,minimum_height)
        # 窗口尺寸是用户级偏好：优先使用上次正常关闭时的大小，并自动约束到当前显示器。
        try:saved_width=int(self.settings.get("last_window_width",default_width) or default_width);saved_height=int(self.settings.get("last_window_height",default_height) or default_height)
        except (TypeError,ValueError):saved_width,saved_height=default_width,default_height
        self.resize(min(max(saved_width,minimum_width),max(minimum_width,screen_width-24)),min(max(saved_height,minimum_height),max(minimum_height,screen_height-24))); self.setup_identity(); self.build(); self.install_input_context_menus(self); self.new_project(); self.apply_skin(False); QTimer.singleShot(0,self.restore_navigation_page); LOGGER.info("Qt 版软件启动，版本 %s，界面缩放 %.2f",APP_VERSION,self.ui_scale)

    def setup_identity(self):
        apply_windows_application_identity()
        icon=QIcon(str(application_icon_path()))
        self.setWindowIcon(icon)
        application=QApplication.instance()
        if application:
            application.setWindowIcon(icon)
            application.setApplicationName(APP_NAME)
            application.setApplicationDisplayName(APP_NAME)

    def build(self):
        self.root=BackgroundWidget(); self.setCentralWidget(self.root); outer=QVBoxLayout(self.root);margin=round(10*self.ui_scale);outer.setContentsMargins(margin,margin,margin,margin); outer.setSpacing(margin);main_row=QHBoxLayout();main_row.setSpacing(margin);outer.addLayout(main_row,1)
        side=QFrame(); self.sidebar=side; side.setObjectName("sidebar"); side.setFixedWidth(224); sl=QVBoxLayout(side)
        brand=QLabel(f"✦  {APP_NAME}"); self.brand_label=brand; brand.setObjectName("brand"); brand.setWordWrap(False); sl.addWidget(brand)
        sub=QLabel("AI 视频任务工作台"); self.sidebar_subtitle=sub; sub.setObjectName("sideMuted"); sub.setWordWrap(True); sl.addWidget(sub)
        self.stack=QStackedWidget();self.nav_container=QWidget();self.nav_layout=QVBoxLayout(self.nav_container);self.nav_layout.setContentsMargins(0,0,0,0);self.nav_layout.setSpacing(0);sl.addWidget(self.nav_container);self.nav_buttons=[];self.rebuild_navigation_buttons()
        sl.addStretch(); self.state=QLabel("未保存项目\n仅手动保存项目文件"); self.state.setObjectName("sideMuted"); sl.addWidget(self.state);self.runtime_status_button=RuntimeStatusButton("运行状态");self.runtime_status_button.setObjectName("navButton");self.runtime_status_button.setToolTip("单击展开底部运行状态；双击查看详细运行日志");self.runtime_status_button.setIcon(self.nav_icon(8));self.runtime_status_button.setIconSize(QSize(round(18*self.ui_scale),round(18*self.ui_scale)));self.runtime_status_button.setMinimumHeight(round(40*self.ui_scale));self.runtime_status_button.singleClicked.connect(self.toggle_runtime_status);self.runtime_status_button.doubleClicked.connect(self.show_runtime_log_dialog);sl.addWidget(self.runtime_status_button); self.version=QLabel(f"版本 v{APP_VERSION}"); self.version.setObjectName("sideMuted"); sl.addWidget(self.version); main_row.addWidget(side); main_row.addWidget(self.stack,1)
        for page in (self.project_page(),self.instruction_page(),self.history_page(),self.system_page(),self.log_page(),self.skin_page(),self.table_viewer_page(),self.help_page(),self.material_organizer_page()): self.stack.addWidget(self.scrollable_page(page))
        self.runtime_status_panel=QFrame();self.runtime_status_panel.setObjectName("card");runtime_layout=QVBoxLayout(self.runtime_status_panel);runtime_layout.setContentsMargins(12,8,12,8);runtime_layout.setSpacing(3);runtime_top=QHBoxLayout();self.runtime_status_summary=QLabel("运行状态：就绪");runtime_top.addWidget(self.runtime_status_summary);runtime_top.addStretch();runtime_top.addWidget(self.btn("查看详细日志",self.show_runtime_log_dialog,"openExport"));runtime_top.addWidget(self.btn("收起",self.toggle_runtime_status));runtime_layout.addLayout(runtime_top);self.runtime_log_display=QTextEdit();self.runtime_log_display.setObjectName("runtimeLogDisplay");self.runtime_log_display.setReadOnly(True);self.runtime_log_display.setFixedHeight(round(92*self.ui_scale));runtime_layout.addWidget(self.runtime_log_display);self.runtime_status_panel.setVisible(False);outer.addWidget(self.runtime_status_panel)
        self.runtime_log_timer=QTimer(self);self.runtime_log_timer.setInterval(900);self.runtime_log_timer.timeout.connect(self.refresh_runtime_status);self.runtime_log_timer.start();self.refresh_runtime_status()
        # 主界面空白背景与皮肤页预览使用同一组位置、缩放参数。
        self.root.on_transform_changed=self.preview_transform_changed
        QTimer.singleShot(0,self.update_responsive_navigation)

    def scrollable_page(self,page):
        """网页式页面容器：窗口不足时让页面滚动，而不是裁切输入框和操作区。"""
        scroll=QScrollArea();scroll.setObjectName("pageScroll");scroll.setWidget(page);scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.NoFrame);scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded);scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded);return scroll

    def install_input_context_menus(self, root):
        """统一所有文字输入框的右键菜单，避免系统原生菜单的英文和阴影效果。"""
        for widget in [*root.findChildren(QLineEdit),*root.findChildren(QTextEdit)]:
            if widget.property("chinese_context_menu"):continue
            widget.setProperty("chinese_context_menu",True);widget.setContextMenuPolicy(Qt.CustomContextMenu)
            widget.customContextMenuRequested.connect(lambda point,target=widget:self.show_edit_context_menu(target,point))
    def show_edit_context_menu(self,widget,point):
        menu=QMenu(widget);configure_readable_menu(menu,self.accent)
        has_selection=widget.hasSelectedText() if isinstance(widget,QLineEdit) else widget.textCursor().hasSelection();editable=not widget.isReadOnly()
        if hasattr(widget,"undo"):
            undo=menu.addAction("撤销");undo.setEnabled(editable and widget.isUndoAvailable());undo.triggered.connect(widget.undo)
        if hasattr(widget,"redo"):
            redo=menu.addAction("重做");redo.setEnabled(editable and widget.isRedoAvailable());redo.triggered.connect(widget.redo)
        menu.addSeparator();cut=menu.addAction("剪切");cut.setEnabled(editable and has_selection);cut.triggered.connect(widget.cut);copy=menu.addAction("复制");copy.setEnabled(has_selection);copy.triggered.connect(widget.copy);paste=menu.addAction("粘贴");paste.setEnabled(editable);paste.triggered.connect(widget.paste);menu.addSeparator();all_text=menu.addAction("全选");all_text.triggered.connect(widget.selectAll)
        menu.exec(widget.mapToGlobal(point))
    def folder_icon(self):
        pixmap=QPixmap(18,18);pixmap.fill(Qt.transparent);painter=QPainter(pixmap);painter.setRenderHint(QPainter.Antialiasing);painter.setPen(Qt.NoPen);painter.setBrush(QColor(self.accent));painter.drawRoundedRect(2,5,14,10,2,2);painter.drawRoundedRect(3,3,7,4,1,1);painter.end();return QIcon(pixmap)
    def file_icon(self):
        pixmap=QPixmap(18,18);pixmap.fill(Qt.transparent);painter=QPainter(pixmap);painter.setRenderHint(QPainter.Antialiasing);color=QColor(self.accent);painter.setPen(QPen(color,1.5));painter.setBrush(color.lighter(180));painter.drawRoundedRect(4,2,10,14,1.5,1.5);painter.drawLine(7,7,12,7);painter.drawLine(7,10,12,10);painter.drawLine(7,13,10,13);painter.end();return QIcon(pixmap)
    def copy_icon(self):
        """指令编辑区的复制图标：跟随紫色主按钮使用白色前景，确保清晰统一。"""
        pixmap=QPixmap(18,18);pixmap.fill(Qt.transparent);painter=QPainter(pixmap);painter.setRenderHint(QPainter.Antialiasing);color=QColor("#FFFFFF");painter.setPen(QPen(color,2));painter.setBrush(Qt.NoBrush);painter.drawRoundedRect(2,2,10,12,2,2);painter.drawRoundedRect(6,5,10,11,2,2);painter.drawLine(9,9,13,9);painter.drawLine(9,12,13,12);painter.end();return QIcon(pixmap)
    def nav_icon(self, kind):
        """绘制统一尺寸的线性导航图标，避免不同 Unicode 符号的视觉大小不一致。"""
        pixmap=QPixmap(20,20);pixmap.fill(Qt.transparent);painter=QPainter(pixmap);painter.setRenderHint(QPainter.Antialiasing);painter.setPen(QPen(QColor("white"),1.8))
        if kind==0:
            painter.drawRoundedRect(3,4,14,12,2,2);painter.drawLine(6,8,14,8);painter.drawLine(6,11,12,11)
        elif kind==1:
            for y in (5,10,15):painter.drawEllipse(3,y-1,2,2);painter.drawLine(8,y,17,y)
        elif kind==2:
            painter.drawEllipse(3,3,14,14);painter.drawLine(10,6,10,10);painter.drawLine(10,10,14,12)
        elif kind==3:
            painter.drawEllipse(5,5,10,10);painter.drawLine(10,2,10,4);painter.drawLine(10,16,10,18);painter.drawLine(2,10,4,10);painter.drawLine(16,10,18,10)
        elif kind==4:
            painter.drawRoundedRect(4,4,12,12,2,2);painter.drawLine(7,8,13,8);painter.drawLine(7,12,13,12)
        elif kind==6:
            painter.drawRoundedRect(3,4,14,12,2,2);painter.drawLine(3,8,17,8);painter.drawLine(8,4,8,16);painter.drawLine(13,4,13,16)
        elif kind==7:
            painter.drawEllipse(3,3,14,14);painter.drawLine(10,9,10,15);painter.drawPoint(10,6)
        elif kind==8:
            painter.drawRoundedRect(2,4,16,12,2,2);painter.drawLine(6,8,9,10);painter.drawLine(9,10,6,12);painter.drawLine(11,13,15,13)
        else:
            painter.drawRoundedRect(5,3,10,14,1,1);painter.drawLine(8,7,12,7);painter.drawLine(8,10,12,10);painter.drawLine(8,13,11,13)
        painter.end();return QIcon(pixmap)
    def navigation_order(self):
        """合并已保存顺序与默认项，升级后新增页面也不会从导航中丢失。"""
        default=[item[0] for item in NAVIGATION_ITEMS];saved=self.settings.get("navigation_order",[])
        saved=[str(item) for item in saved] if isinstance(saved,list) else [];ordered=[]
        for item in saved:
            if item in default and item not in ordered:ordered.append(item)
        return ordered+[item for item in default if item not in ordered]
    def rebuild_navigation_buttons(self):
        if not hasattr(self,"nav_layout"):return
        while self.nav_layout.count():
            item=self.nav_layout.takeAt(0);widget=item.widget()
            if widget:widget.deleteLater()
        items={item[0]:item for item in NAVIGATION_ITEMS};self.nav_buttons=[]
        for identifier in self.navigation_order():
            _,text,index,icon_kind=items[identifier];button=self.nav_button(text,index,icon_kind);button.setProperty("nav_id",identifier);self.nav_buttons.append(button);self.nav_layout.addWidget(button)
        self.update_responsive_navigation()
    def configure_navigation_order(self):
        dialog,layout=self.themed_dialog("导航栏排序",560,620);layout.addWidget(QLabel("直接拖拽功能名称调整左侧导航栏的顺序。保存后立即应用，并随用户配置备份、恢复和迁移；不会隐藏任何功能。"))
        entries={item[0]:item for item in NAVIGATION_ITEMS};items=QListWidget();items.setDragDropMode(QAbstractItemView.InternalMove);items.setDefaultDropAction(Qt.MoveAction);items.setSelectionMode(QAbstractItemView.SingleSelection);items.setSpacing(3)
        def fill(order):
            items.clear()
            for identifier in order:
                entry=entries[identifier];row=QListWidgetItem(entry[1]);row.setData(Qt.UserRole,identifier);row.setIcon(self.nav_icon(entry[3]));items.addItem(row)
        fill(self.navigation_order());layout.addWidget(items,1)
        buttons=QHBoxLayout();buttons.addWidget(self.btn("恢复默认顺序",lambda:fill([item[0] for item in NAVIGATION_ITEMS]),"warning"));buttons.addStretch();buttons.addWidget(self.btn("取消",dialog.reject));buttons.addWidget(self.btn("保存并应用",dialog.accept,"primary"));layout.addLayout(buttons)
        if dialog.exec()!=QDialog.Accepted:return
        self.settings["navigation_order"]=[items.item(row).data(Qt.UserRole) for row in range(items.count())];save_app_settings(self.settings);self.rebuild_navigation_buttons();QMessageBox.information(self,"导航栏已更新","新的导航栏顺序已保存并立即应用。")
    def nav_button(self,text,index,icon_kind):
        button=self.btn(text,lambda _=False,i=index:self.show_page(i),"navButton");button.setProperty("nav_text",text);button.setToolTip(text);button.setIcon(self.nav_icon(icon_kind));icon_size=round(18*self.ui_scale);button.setIconSize(QSize(icon_size,icon_size));button.setMinimumHeight(round(40*self.ui_scale));return button

    def expanded_sidebar_width(self):
        """返回足以显示品牌与最长导航文字的固定展开宽度。

        ui_scale 用于内容密度，不能把侧栏缩到连品牌都放不下；否则窗口放大后仍会出现
        半截文字。宽度使用字体实际测量值，并保留图标、内边距和高 DPI 的余量。
        """
        brand_width = 224
        if hasattr(self, "brand_label"):
            # sizeHint 会计入主题样式中的 20px 品牌字体；QFontMetrics 作为样式未应用时的后备。
            brand_width = max(
                self.brand_label.sizeHint().width() + 28,
                QFontMetrics(self.brand_label.font()).horizontalAdvance(f"✦  {APP_NAME}") + 42,
            )
        nav_width = 0
        for button in getattr(self, "nav_buttons", []):
            text = str(button.property("nav_text") or "")
            nav_width = max(nav_width, QFontMetrics(button.font()).horizontalAdvance(text) + 58)
        return max(224, brand_width, nav_width)

    def resizeEvent(self,event):
        super().resizeEvent(event);self.update_responsive_navigation()

    def update_responsive_navigation(self):
        if not hasattr(self,"sidebar"):return
        # 宽度不足时直接切换为图标导航，不显示被裁切的半截品牌文字。
        # 展开后的侧栏不随低分辨率 ui_scale 缩窄，始终满足实际文字宽度。
        compact=self.width()<1050
        self.brand_label.setText("✦" if compact else f"✦  {APP_NAME}");self.brand_label.setAlignment(Qt.AlignCenter if compact else Qt.AlignLeft);self.sidebar_subtitle.setVisible(not compact)
        for widget_name in ("state","version"):
            widget=getattr(self,widget_name,None)
            if widget:widget.setVisible(not compact)
        if hasattr(self,"runtime_status_button"):
            self.runtime_status_button.setText("" if compact else "运行状态");self.runtime_status_button.setStyleSheet("QPushButton#navButton{text-align:center;padding:8px;}" if compact else "")
        # 先恢复完整品牌文本，再读取 sizeHint；否则从图标模式展开时会沿用单个图标的宽度。
        self.sidebar.setFixedWidth(64 if compact else self.expanded_sidebar_width())
        for button in getattr(self,"nav_buttons",[]):
            button.setText("" if compact else str(button.property("nav_text") or ""));button.setStyleSheet("QPushButton#navButton{text-align:center;padding:8px;}" if compact else "")

    def eventFilter(self,watched,event):
        """统一弹窗的键盘确认：输入状态绝不抢占回车或空格。"""
        event_type=event.type()
        if event_type not in (QEvent.MouseButtonDblClick,QEvent.MouseButtonPress,QEvent.KeyPress):
            return False
        if watched is getattr(self,"preview_output",None) and event.type()==QEvent.MouseButtonDblClick:
            self.open_preview_output_directory();event.accept();return True
        # 指令编辑器是长文本输入场景：空格与回车必须始终留给正文。它以非模态
        # 窗口显示；只有先点击软件中该弹窗以外的区域、再按空格或回车才提交，
        # 不能沿用普通确认框的“键盘默认按钮”规则。
        click_away_dialog=getattr(self,"_instruction_click_away_dialog",None)
        if event.type()==QEvent.MouseButtonPress and isinstance(click_away_dialog,QDialog) and click_away_dialog.isVisible() and bool(click_away_dialog.property("instruction_click_away_ready")):
            target=watched if isinstance(watched,QWidget) else None;inside=False
            while target is not None:
                if target is click_away_dialog:inside=True;break
                target=target.parentWidget()
            # “缺少名称”等提示框本身也是独立 QDialog。点击它的“知道了”不能
            # 被当成编辑器外部点击，否则会再次提交空名称并无限弹出提示。
            target_window=watched.window() if hasattr(watched,"window") else None
            if isinstance(target_window,QDialog) and target_window is not click_away_dialog:inside=True
            # 只允许宿主主窗口及其页面区域进入待确认状态；本软件的其它独立
            # 窗口（任务中心、设置、提示等）以及任何外部程序都绝不能触发保存。
            host_main_window=getattr(self,"_host_main_window",None)
            if target_window is not host_main_window:inside=True
            # 点击编辑窗口内的任意控件（包括空白区域）都会回到编辑模式，取消
            # 外部区域留下的待确认状态；单独点击窗口外也绝不立即保存。
            click_away_dialog.setProperty("instruction_click_away_armed",not inside)
            if not inside:
                # 主界面点击只用于武装“空格/回车确认”，不能让非模态编辑窗被
                # 主窗口压到后面；下一轮事件循环将它恢复到本软件最前方并接回焦点。
                QTimer.singleShot(0,lambda current=click_away_dialog:(current.raise_(),current.activateWindow()) if current.isVisible() else None)
        if event.type()==QEvent.KeyPress and event.key() in (Qt.Key_Return,Qt.Key_Enter,Qt.Key_Space) and isinstance(click_away_dialog,QDialog) and click_away_dialog.isVisible() and bool(click_away_dialog.property("instruction_click_away_ready")) and bool(click_away_dialog.property("instruction_click_away_armed")):
            # 部分 Windows/Qt 组合在点击非模态窗口外后仍暂时保留 QTextEdit 焦点，
            # 因而以“已点击外部区域”的明确状态为准；只要重新点回编辑窗口，该
            # 状态便会立即清除，窗口内输入不会误保存。
            commit=getattr(click_away_dialog,"_instruction_editor_commit",None)
            if callable(commit):
                click_away_dialog.setProperty("instruction_click_away_armed",False);commit();event.accept();return True
        watched_dialog=watched.window() if hasattr(watched,"window") else None
        if event.type()==QEvent.MouseButtonPress and isinstance(watched_dialog,QDialog) and bool(watched_dialog.property("keyboard_submit_enabled")):
            # 点击卡片空白、标题或其他非编辑区域后，明确进入“可回车确认”状态；
            # 这样即使 Qt 仍把焦点留在刚才的输入框，也不会错过用户的确认动作。
            input_widget=isinstance(watched,(QLineEdit,QTextEdit,QSpinBox,QComboBox))
            if isinstance(watched,QTableWidget) and watched.state()==QAbstractItemView.EditingState:
                input_widget=True
            watched_dialog.setProperty("keyboard_submit_armed",not input_widget)
        if event.type()==QEvent.KeyPress and event.key() in (Qt.Key_Return,Qt.Key_Enter,Qt.Key_Space):
            focus=QApplication.focusWidget()
            dialog=focus.window() if focus is not None else watched_dialog
            if isinstance(dialog,QDialog) and bool(dialog.property("keyboard_submit_enabled")):
                # 文本、数值和下拉输入保持原生键盘行为；表格只有未编辑状态才触发确认。
                editing=isinstance(focus,(QLineEdit,QTextEdit,QSpinBox,QComboBox))
                if isinstance(focus,QTableWidget) and focus.state()==QAbstractItemView.EditingState:
                    editing=True
                if not editing or bool(dialog.property("keyboard_submit_armed")):
                    button=self.dialog_submit_button(dialog)
                    if button is not None:
                        dialog.setProperty("keyboard_submit_armed",False)
                        button.click();event.accept();return True
        return super().eventFilter(watched,event)

    def dialog_submit_button(self,dialog):
        """找出对话框的保存/确认主操作；不把取消、关闭和危险删除误当作默认操作。"""
        candidates=[]
        keywords=("保存","确认","应用","开始","建立","使用此目录","继续","导入","导出","完成","知道了")
        for order,button in enumerate(dialog.findChildren(QPushButton)):
            if not button.isVisible() or not button.isEnabled():
                continue
            text=button.text().strip()
            if not text or any(word in text for word in ("取消","关闭","删除","清空","覆盖")):
                continue
            score=0
            if button.objectName()=="primary":score+=100
            # “保存修改”即便视觉上采用的是其他颜色，也应比普通 primary 操作优先。
            if any(word in text for word in keywords):score+=150
            if score:candidates.append((score,order,button))
        return max(candidates,key=lambda value:(value[0],value[1]))[2] if candidates else None
    def themed_dialog(self,title,width=460,height=190):
        dialog=QDialog(self);dialog.setProperty("keyboard_submit_enabled",True);dialog.setProperty("keyboard_submit_armed",False);dialog.setWindowTitle(title);screen=QGuiApplication.primaryScreen();available=screen.availableGeometry() if screen else None;max_width=(available.width()-32) if available else width;max_height=(available.height()-32) if available else height;dialog.resize(min(width,max_width),min(height,max_height));dialog.setModal(True);outer=QVBoxLayout(dialog);outer.setContentsMargins(0,0,0,0)
        root=BackgroundWidget();root.set_skin(self.skin_image.text().strip() if hasattr(self,"skin_image") else self.settings.get("skin_background",""),self.opacity.value() if hasattr(self,"opacity") else 18,"#F7F9F8",self.image_zoom,self.image_x,self.image_y);outer.addWidget(root)
        root_layout=QVBoxLayout(root);root_layout.setContentsMargins(16,16,16,16);card=QFrame();card.setObjectName("card");root_layout.addWidget(card);content=QVBoxLayout(card);content.setContentsMargins(20,18,20,18);accent=QColor(self.accent);base=accent.name();dark=accent.darker(130).name();deep=accent.darker(155).name();light=accent.lighter(185).name();export_style="QPushButton#exportConfirm{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 %s,stop:0.46 %s,stop:1 %s);color:white;border:1px solid %s;border-radius:8px;padding:8px 14px;font-weight:700}QPushButton#exportConfirm:hover{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 %s,stop:0.52 %s,stop:1 %s);border-color:%s}QPushButton#exportConfirm:pressed{background:%s;padding-top:9px;padding-bottom:7px}"%(light,base,dark,dark,base,dark,deep,deep,deep);dialog.setStyleSheet(self.style()+export_style);return dialog,content
    def themed_message(self,level,title,text):
        dialog,layout=self.themed_dialog(title,500,210 if len(str(text))>70 else 180);heading=QLabel(title);heading.setObjectName("title");heading.setStyleSheet("font-size:18px;padding:2px 0;");layout.addWidget(heading)
        message=QLabel(str(text));message.setWordWrap(True);message.setTextInteractionFlags(Qt.TextSelectableByMouse);layout.addWidget(message,1)
        buttons=QHBoxLayout();buttons.addStretch()
        if level=="question":
            buttons.addWidget(self.btn("取消",dialog.reject));buttons.addWidget(self.btn("确认",dialog.accept,"primary"));layout.addLayout(buttons);return QMessageBox.Yes if dialog.exec()==QDialog.Accepted else QMessageBox.No
        buttons.addWidget(self.btn({"information":"知道了","warning":"知道了","critical":"关闭"}.get(level,"知道了"),dialog.accept,"primary"));layout.addLayout(buttons);dialog.exec();return QMessageBox.Ok
    def style(self):
        color=QColor(self.accent); a=color.name(); dark=color.darker(130).name(); deeper=color.darker(155).name(); header=color.darker(215).name(); soft=color.lighter(185).name(); pale=color.lighter(210).name(); border=color.lighter(150).name(); red,green,blue,_=color.getRgb(); nav_alpha=round(max(0,min(100,self.nav_opacity))*2.55); sidebar=f"rgba({red},{green},{blue},{nav_alpha})"; sidebar_hover=f"rgba({color.darker(130).red()},{color.darker(130).green()},{color.darker(130).blue()},{min(255,nav_alpha+18)})"
        return f'''QWidget{{color:#183B2B;font:13px "Microsoft YaHei UI";background:transparent}}QStackedWidget{{background:rgba(247,249,248,108);border-radius:14px}}#sidebar{{background:{sidebar};border-radius:18px;border:1px solid rgba(255,255,255,72)}}#brand{{color:white;font-size:20px;font-weight:700;padding:10px 4px;background:transparent}}#sideMuted{{color:white;background:transparent;padding:4px}}QPushButton#navButton{{color:white;text-align:left;border:0;border-radius:10px;padding:12px;background:transparent}}QPushButton#navButton:hover{{background:{sidebar_hover}}}#card{{background:rgba(255,255,255,218);border:1px solid rgba(255,255,255,185);border-radius:14px}}#title{{color:{dark};font-size:22px;font-weight:700;background:rgba(247,249,248,175);border-radius:8px;padding:2px 6px}}QLineEdit,QComboBox,QTextEdit{{background:rgba(255,255,255,238);border:1px solid {border};border-radius:8px;padding:7px}}QLineEdit:disabled{{color:#6B7780;background:rgba(220,226,230,220);border:1px solid #B9C4CA}}QLineEdit:focus,QComboBox:focus,QTextEdit:focus{{border:2px solid {a}}}QPushButton{{background:rgba(255,255,255,232);border:1px solid {border};border-radius:8px;padding:8px 12px}}QPushButton:hover{{background:{pale}}}QPushButton#primary{{background:{a};color:white;border:0;font-weight:700}}QPushButton#primary:hover{{background:{dark}}}QPushButton#openProject{{background:#7562C7;color:white;border:0;font-weight:700}}QPushButton#openProject:hover{{background:#5F4EAA}}QPushButton#selectInput{{background:#2878C8;color:white;border:0;font-weight:700}}QPushButton#selectOutput{{background:#168D80;color:white;border:0;font-weight:700}}QPushButton#loadData{{background:#1A9BC0;color:white;border:0;font-weight:700}}QPushButton#clearPreview{{background:#D9822B;color:white;border:0;font-weight:700}}QPushButton#warning{{background:#D9822B;color:white;border:0;font-weight:700}}QPushButton#export{{background:{dark};color:white;border:0;font-weight:700}}QPushButton#openExport{{background:#249A62;color:white;border:0;font-weight:700}}QPushButton#openExportFolder{{background:#C68A27;color:white;border:0;font-weight:700}}QPushButton#danger{{background:#D84D5E;color:white;border:0}}QTabWidget::pane{{background:rgba(255,255,255,195);border:1px solid {border};border-radius:10px;top:-1px}}QTabBar::tab{{background:rgba(255,255,255,210);border:1px solid {border};border-bottom:0;border-top-left-radius:8px;border-top-right-radius:8px;padding:8px 14px;margin-right:3px}}QTabBar::tab:selected{{background:{soft};color:{deeper};font-weight:700}}QTableWidget,QListWidget,QTreeWidget{{background:rgba(255,255,255,230);border:1px solid {border};border-radius:10px;gridline-color:#8FA3B2;}}QTableWidget::item{{border-right:1px solid #B3C0C9;border-bottom:1px solid #B3C0C9;padding:2px;}}QTreeWidget::item{{padding:7px 5px;min-height:30px}}QTreeWidget::item:selected{{background:{soft};color:{deeper}}}QHeaderView::section{{background:{header};color:#FFFFFF;padding:9px;border:1px solid {dark};font-weight:700}}QListWidget::item{{padding:9px;border-radius:7px}}QListWidget::item:selected{{background:{soft};color:{deeper}}}QProgressBar{{border:0;background:{pale};border-radius:6px;height:10px}}QProgressBar::chunk{{background:{a};border-radius:6px}}QSlider::groove:horizontal{{height:7px;background:{pale};border-radius:3px}}QSlider::sub-page:horizontal{{background:{a};border-radius:3px}}QSlider::add-page:horizontal{{background:{pale};border-radius:3px}}QSlider::handle:horizontal{{background:{a};width:18px;margin:-6px 0;border-radius:9px}}QScrollBar:vertical{{background:{pale};width:18px;margin:5px 2px;border-radius:9px}}QScrollBar::handle:vertical{{background:{a};min-height:52px;border-radius:8px;border:2px solid rgba(255,255,255,120)}}QScrollBar:horizontal{{background:{pale};height:18px;margin:2px 5px;border-radius:9px}}QScrollBar::handle:horizontal{{background:{a};min-width:52px;border-radius:8px;border:2px solid rgba(255,255,255,120)}}QScrollBar::add-line,QScrollBar::sub-line{{width:0;height:0}}'''

    def dark_style_overrides(self):
        """夜间主题的完整工作区覆写，避免仅改变按钮颜色而仍保留刺眼白底。"""
        accent=QColor(self.accent).name();accent_dark=QColor(self.accent).darker(145).name();accent_soft=QColor(self.accent).darker(175).name()
        return """
QWidget{color:#E7EDF6;background:transparent}
QStackedWidget{background:rgba(12,19,31,150)}
#card{background:rgba(22,32,48,235);border:1px solid rgba(142,164,194,95)}
#title{color:#F1F5FA;background:rgba(17,27,42,205)}
QLineEdit,QComboBox,QTextEdit{color:#EDF3FB;background:#172334;border:1px solid #526A87}
QLineEdit:disabled{color:#9AAABA;background:#202C3A;border:1px solid #425569}
QLineEdit:focus,QComboBox:focus,QTextEdit:focus{border:2px solid %(accent)s}
QPushButton{color:#EAF1F8;background:#243246;border:1px solid #536A87}
QPushButton:hover{background:#33465F}
QTabWidget::pane{background:#162235;border:1px solid #526A87}
QTabBar::tab{color:#D9E5F2;background:#223148;border:1px solid #526A87}
QTabBar::tab:selected{color:#FFFFFF;background:%(accent_soft)s}
QTableWidget,QListWidget,QTreeWidget{color:#E8F0F8;background:#172334;border:1px solid #526A87;gridline-color:#607A96}
QTableWidget::item{color:#E8F0F8;background:#172334;border-right:1px solid #49627E;border-bottom:1px solid #49627E}
QTableWidget::item:selected,QTableWidget::item:selected:active,QTableWidget::item:selected:!active{color:#FFFFFF;background:%(accent_dark)s;border:2px solid %(accent)s}
QTableWidget QLineEdit{color:#FFFFFF;background:#0F1927;selection-color:#FFFFFF;selection-background-color:%(accent_dark)s;border:2px solid %(accent)s}
QHeaderView::section{color:#F2F6FA;background:#263750;border-right:1px solid #607A96;border-bottom:1px solid #607A96}
QListWidget::item:selected,QTreeWidget::item:selected{color:#FFFFFF;background:%(accent_dark)s}
QMenu{color:#EAF1F8;background:#1B293B;border:1px solid #526A87}
QMenu::item:selected{color:#FFFFFF;background:%(accent_dark)s}
QScrollBar:vertical,QScrollBar:horizontal{background:#1D2B3D}
QScrollBar::handle:vertical,QScrollBar::handle:horizontal{background:%(accent)s}
""" % {"accent":accent,"accent_dark":accent_dark,"accent_soft":accent_soft}

    def btn(self,text,slot,kind=""):
        button=QPushButton(text); button.setObjectName(kind); button.setCursor(Qt.ArrowCursor)
        if kind=="newProject":button.setStyleSheet("QPushButton{background:#1A9BC0;color:white;border:0;border-radius:8px;padding:8px 12px;font-weight:700}QPushButton:hover{background:#147D9A}")
        elif kind=="saveProject":button.setStyleSheet("QPushButton{background:#7562C7;color:white;border:0;border-radius:8px;padding:8px 12px;font-weight:700}QPushButton:hover{background:#5F4EAA}")
        # QPushButton.clicked 会携带 checked(bool)；所有业务槽函数统一不接收该参数。
        button.clicked.connect(lambda _checked=False, callback=slot: callback()); return button
    def title(self,text):
        label=QLabel(text); label.setObjectName("title"); return label

    def project_page(self):
        page=QWidget(); layout=QVBoxLayout(page); top=QHBoxLayout(); top.addWidget(self.title("项目工作台")); top.addStretch()
        for text,fn,kind in (("＋ 新建项目",self.new_project,"newProject"),("打开项目",self.open_project,"openProject"),("保存项目",self.save_project_file,"saveProject"),("删除项目",self.remove_project,"danger")): top.addWidget(self.btn(text,fn,kind))
        layout.addLayout(top); card=QFrame(); card.setObjectName("card"); form=QFormLayout(card); form.setContentsMargins(16,16,16,16); form.setVerticalSpacing(6)
        self.name=QLineEdit();self.name.setPlaceholderText("请输入项目名称；选择扫描目录后可自动填充"); self.input=FolderDropLineEdit();self.input.setPlaceholderText("请选择、手动输入或拖入扫描文件夹路径");self.input.on_folder_dropped=lambda path:(self.settings.__setitem__("last_input_dir",path),save_app_settings(self.settings),self.defaults()); self.output=FolderDropLineEdit();self.output.setPlaceholderText("请选择、手动输入或拖入输出文件夹路径");self.output.on_folder_dropped=lambda path:(self.settings.__setitem__("last_output_dir",path),save_app_settings(self.settings)); self.filename=QLineEdit();self.filename.setPlaceholderText("留空时自动使用项目名称");self.preview_output=QLineEdit();self.preview_output.setReadOnly(True);self.preview_output.setCursor(Qt.CursorShape.PointingHandCursor);self.preview_output.setToolTip("双击：如果预输出目录已存在，则在资源管理器中打开。");self.preview_output.setPlaceholderText("请先选择扫描目录并填写项目名称"); self.output_mode=DoubleClickComboBox();self.output_mode.addItem("表格文件（输出到指定目录）",OUTPUT_MODE_TABLE);self.output_mode.addItem("多个 TXT 文件（输出到原素材目录）",OUTPUT_MODE_MULTI_TXT);self.output_mode.currentTextChanged.connect(self.output_mode_changed);self.output_mode.currentTextChanged.connect(self.remember_workspace_selectors);self.format=DoubleClickComboBox(); self.format.addItems(FORMATS); self.format.currentTextChanged.connect(self.sync_filename);self.format.currentTextChanged.connect(self.remember_workspace_selectors); self.instruction_category=DoubleClickComboBox(); self.instruction_category.setEditable(True);self.instruction_category.lineEdit().setReadOnly(True);self.instruction_category.lineEdit().setCursor(Qt.ArrowCursor);self.category_folder_action=self.instruction_category.lineEdit().addAction(self.folder_icon(),QLineEdit.LeadingPosition);self.category_folder_action.setVisible(False);self.instruction_category.setPlaceholderText("请选择指令分类");category_view=QTreeView();category_view.setHeaderHidden(True);category_view.setRootIsDecorated(True);category_view.setItemsExpandable(True);category_view.pressed.connect(self.select_instruction_category_index);self.instruction_category.setView(category_view); self.instruction=DoubleClickComboBox(); self.instruction.currentTextChanged.connect(self.apply_instruction);self.instruction.activated.connect(self.apply_instruction);self.instruction.currentTextChanged.connect(self.remember_workspace_selectors); self.encoding=DoubleClickComboBox(); self.encoding.addItems(("utf-8","gbk","gb18030","utf-8-sig"));self.copy_images=QCheckBox("同时导出对应图片");self.copy_images.setToolTip("按最终预览任务复制图片；已完成视频的编号不会复制。");self.merge_export=QCheckBox("合并导出到待制作目录");self.merge_export.setToolTip("将表格或多个 TXT 与图片统一输出到“项目名-待制作”目录。");self.copy_images.toggled.connect(self.remember_workspace_export_options);self.merge_export.toggled.connect(self.merge_export_changed);self.merge_export.toggled.connect(self.remember_workspace_export_options);self.restore_workspace_export_options()
        # 扫描模式与路径配置保持在主页面：普通数字 TXT 和“分段资料包”可随时切换。
        self.scan_mode=DoubleClickComboBox();self.scan_mode.addItem("普通数字 TXT 扫描","standard");self.scan_mode.addItem("分段资料包扫描（图片 + 文案 + 生成词）","segment_bundle")
        self.scan_mode.setToolTip("普通模式：读取文件夹同名图片和数字 TXT。分段资料包模式：读取数字 TXT，并按“图片名-编号.txt”读取对应生成词。")
        self.scan_mode.currentIndexChanged.connect(self.remember_workspace_selectors)
        self.bundle_image_mode=DoubleClickComboBox();self.bundle_image_mode.addItem("分段图片（图片名-编号.jpg，默认）","segment_image");self.bundle_image_mode.addItem("素材原图（图片名.jpg）","source_image")
        self.bundle_image_mode.setToolTip("仅在“分段资料包扫描”时生效。分段图片：1.txt 使用 图片名-1.jpg 与 图片名-1.txt；素材原图：所有分段共用 图片名.jpg，生成词仍为 图片名-1.txt。")
        self.bundle_image_mode.currentIndexChanged.connect(self.remember_workspace_selectors)
        # 输出模式、格式和编码统一收进“输出设置”，主页面优先留给表格和生产资料。
        self.output_mode.setParent(page);self.format.setParent(page);self.encoding.setParent(page);self.copy_images.setParent(page);self.merge_export.setParent(page)
        self.output_mode.hide();self.format.hide();self.encoding.hide();self.copy_images.hide();self.merge_export.hide()
        # 扫描规则紧跟“文件名”：用户先确定本次资料包/项目名称，再选择普通素材
        # 或分段资料包的读取方式，避免把扫描规则误认为是路径设置。
        for label,w in (("扫描目录",self.input),("输出目录",self.output),("预输出目录",self.preview_output),("文件名",self.filename),("扫描模式",self.scan_mode),("资料包图片",self.bundle_image_mode),("指令分类",self.instruction_category),("选择指令",self.instruction)):
            label_widget=QLabel(label);form.addRow(label_widget,w)
            if label=="输出目录":self.output_label=label_widget
            elif label=="文件名":self.filename_label=label_widget
        for field in (self.name,self.input,self.output,self.filename):field.textChanged.connect(self.refresh_preview_output_directory)
        self.format.currentTextChanged.connect(self.refresh_preview_output_directory)
        # 扫描时始终保留完整记录；此选项仅切换预览视图，便于在“待制作”和
        # “全部记录（含已有成品）”之间快速核对，绝不删除任何行或素材。
        self.workspace_pending_only=QCheckBox("筛选待制作")
        self.workspace_pending_only.setToolTip("仅显示尚未有同名视频成品的 TXT 任务；取消勾选可查看全部记录。导出始终不会重复导出已有同名视频的任务。")
        self.workspace_pending_only.setChecked(bool(self.settings.get("workspace_pending_only",False)))
        self.workspace_pending_only.toggled.connect(self.remember_workspace_pending_filter)
        self.workspace_pending_only.toggled.connect(self.apply_workspace_pending_filter)
        controls_host=QWidget();controls=QHBoxLayout(controls_host);controls.setContentsMargins(0,0,0,0);controls.setSpacing(6)
        for text,fn,kind in (("🗂 从素材整理选择",self.choose_material_organized_directory,"primary"),("📁 选择扫描目录",self.choose_input,"primary"),("↻ 加载并更新项目数据",self.load,"primary"),("选择输出目录",self.choose_output,"selectOutput"),("⚙ 输出设置",self.open_output_settings,"warning"),("🧹 清空当前项目数据",self.clear_current,"primary")): controls.addWidget(self.btn(text,fn,kind))
        controls.addWidget(self.workspace_pending_only)
        controls.addWidget(self.btn("筛选菜单",self.toggle_workspace_filter_bar,"warning"))
        segment_images_button=self.btn("导出分段图",self.export_images,"exportImages")
        segment_images_button.setToolTip("按表格中的数字 TXT 任务导出对应的分段图片；每个分段保留一张对应图片。")
        controls.addWidget(segment_images_button)
        # “导出主图”完全按扫描目录工作：递归读取扫描目录及其子文件夹中、文件名
        # 与所在文件夹名称相同的主图；绝不从表格行、资料包分段图或素材来源目录反推图片。
        material_images_button=self.btn("📤 导出主图",self.export_material_main_images,"exportImages")
        material_images_button.setToolTip("递归导出扫描目录及其子文件夹中、与所在文件夹同名的主图。输出到扫描目录同级的“扫描目录名-图片”文件夹；已有文件夹时会先询问是否覆盖同名图片。")
        controls.addWidget(material_images_button);controls.addStretch()
        controls_host.setMinimumWidth(960);controls_scroll=QScrollArea();controls_scroll.setWidget(controls_host);controls_scroll.setWidgetResizable(False);controls_scroll.setFrameShape(QFrame.NoFrame);controls_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff);controls_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded);controls_scroll.setFixedHeight(48);form.addRow(controls_scroll); layout.addWidget(card); self.progress=QProgressBar(); layout.addWidget(self.progress); self.summary=QLabel("选择目录后点击“加载并更新项目数据”。"); layout.addWidget(self.summary)
        # 与常见电子表格一样，筛选条件单独占一行；收起时不挤占数据表空间。
        self.workspace_filter_bar=QFrame();self.workspace_filter_bar.setObjectName("card");filter_layout=QHBoxLayout(self.workspace_filter_bar);filter_layout.setContentsMargins(10,7,10,7);filter_layout.setSpacing(6);filter_layout.addWidget(QLabel("按条件过滤"));self.workspace_filter_field=DoubleClickComboBox();self.workspace_filter_field.setMinimumWidth(135);self.workspace_filter_condition=DoubleClickComboBox();self.workspace_filter_condition.setMinimumWidth(145);self.workspace_filter_value=QLineEdit();self.workspace_filter_value.setPlaceholderText("输入筛选值；“介于”用逗号分隔两个值");self.workspace_filter_value.setClearButtonEnabled(True);self.workspace_filter_value.returnPressed.connect(self.apply_workspace_pending_filter);filter_layout.addWidget(self.workspace_filter_field);filter_layout.addWidget(self.workspace_filter_condition);filter_layout.addWidget(self.workspace_filter_value,1);filter_layout.addWidget(self.btn("应用",self.apply_workspace_pending_filter,"primary"));filter_layout.addWidget(self.btn("清除",self.clear_workspace_filter));filter_layout.addWidget(QLabel("勾选导出："));filter_layout.addWidget(self.btn("全选",self.workspace_select_all));filter_layout.addWidget(self.btn("反选",self.workspace_invert_selection));filter_layout.addWidget(self.btn("取消全选",self.workspace_clear_selection));self.workspace_filter_bar.setVisible(False);layout.addWidget(self.workspace_filter_bar)
        self.refresh_workspace_filter_controls()
        # A 列为图片审核，B 列为导出勾选；两列都不属于项目数据或导出字段。
        self.table=MaterialSpreadsheet(12,len(HEADERS)+2); self.table.minimum_row_count=12; self.table.setHorizontalHeaderLabels(("图片预览","勾选")+HEADERS); self.table.setSelectionBehavior(QTableWidget.SelectItems); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive);self.table.horizontalHeader().sectionResized.connect(self.remember_workspace_table_column_width);self.table.changed.connect(self.sync_workspace_rows_from_table);self.table.cellDoubleClicked.connect(self.workspace_open_image_preview)
        self.table.setColumnWidth(0,72)
        self.table.setColumnWidth(1,54)
        for i,w in enumerate((120,300,120,140,330,400,130),2): self.table.setColumnWidth(i,w)
        preview_panel=QWidget(); preview_panel.setMinimumHeight(150); preview_layout=QVBoxLayout(preview_panel); preview_layout.setContentsMargins(0,0,0,0); preview_layout.addWidget(self.table,1); bottom_host=QWidget();bottom=QHBoxLayout(bottom_host);bottom.setContentsMargins(0,0,0,0);bottom.setSpacing(6); bottom.addWidget(self.btn("＋ 添加一行",self.add_row)); bottom.addWidget(self.btn("删除选中行",self.delete_rows)); bottom.addWidget(self.btn("查看检查提示",self.show_warnings)); bottom.addWidget(self.btn("加载目录数据",self.load,"loadData")); bottom.addWidget(self.btn("清空预览数据",self.clear_preview,"clearPreview"));bottom.addWidget(self.btn("设置表头",self.configure_table_headers,"warning")); bottom.addWidget(self.btn("📤 确认并导出",self.export,"primary")); bottom.addWidget(self.btn("打开导出文件",self.open_exported_file,"openExportFile")); bottom.addWidget(self.btn("打开导出目录",self.open_export_directory,"openExportFolder"));bottom.addStretch();bottom_host.setMinimumWidth(990);bottom_scroll=QScrollArea();bottom_scroll.setWidget(bottom_host);bottom_scroll.setWidgetResizable(False);bottom_scroll.setFrameShape(QFrame.NoFrame);bottom_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff);bottom_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded);bottom_scroll.setFixedHeight(48);preview_layout.addWidget(bottom_scroll)
        # 这里只剩单个预览区，使用 splitter 不会产生可调分隔条；直接加入布局，
        # 避免保留“恢复默认布局”这类无实际效果的入口。
        layout.addWidget(preview_panel,1); return page

    def instruction_page(self):
        page=QWidget(); layout=QHBoxLayout(page); self.instruction_splitter=QSplitter(Qt.Horizontal); self.instruction_splitter.setChildrenCollapsible(False)
        left_card=QFrame(); left_card.setObjectName("card"); left_layout=QVBoxLayout(left_card); left_layout.addWidget(self.title("指令库分类")); self.instruction_search=QLineEdit();self.instruction_search.setPlaceholderText("搜索指令名称、内容、备注或分类…");self.instruction_search.setClearButtonEnabled(True);self.instruction_search.setToolTip("输入关键词会同时搜索分类、指令名称、详细指令和备注；清空后恢复完整指令树。");left_layout.addWidget(self.instruction_search); self.ilist=InstructionTree(self.move_selected_instructions); self.ilist.setHeaderHidden(True); self.ilist.setSelectionMode(QAbstractItemView.ExtendedSelection); self.ilist.itemSelectionChanged.connect(self.select_instruction); self.ilist.itemDoubleClicked.connect(self.handle_tree_double_click); self.ilist.itemExpanded.connect(self._save_instruction_tree_expansion);self.ilist.itemCollapsed.connect(self._save_instruction_tree_expansion);self.ilist.setContextMenuPolicy(Qt.CustomContextMenu); self.ilist.customContextMenuRequested.connect(self.instruction_context_menu);self.instruction_search.textChanged.connect(self.filter_instruction_tree); left_layout.addWidget(self.ilist,1); folders=QHBoxLayout(); folders.addWidget(self.btn("＋ 新建分类",self.new_instruction_folder,"warning")); folders.addWidget(self.btn("删除分类",self.delete_instruction_folder,"danger")); left_layout.addLayout(folders); transfer_form=QFormLayout(); self.transfer_format=DoubleClickComboBox();self.transfer_format.addItems(("Excel 工作簿 (.xlsx)","CSV (.csv)","JSON (.json)"));self.transfer_encoding=DoubleClickComboBox();self.transfer_encoding.addItems(("utf-8","utf-8-sig","gb18030","gbk"));transfer_form.addRow("交换格式",self.transfer_format);transfer_form.addRow("CSV/JSON 编码",self.transfer_encoding);left_layout.addLayout(transfer_form); transfers=QHBoxLayout(); transfers.addWidget(self.btn("导出选中",self.export_selected_instruction,"openExport")); transfers.addWidget(self.btn("导出全部",self.export_all_instructions,"openExport")); transfers.addWidget(self.btn("导入",self.import_instructions,"loadData")); left_layout.addLayout(transfers)
        edit=QFrame(); edit.setObjectName("card"); edit_layout=QVBoxLayout(edit); edit_layout.addWidget(self.title("指令编辑（默认只读）")); form=QFormLayout(); self.iname=QLineEdit(); self.ifolder=QComboBox(); self.icontent=QTextEdit(); self.inote=QTextEdit(); self.inote.setFixedHeight(78); form.addRow("所属分类",self.ifolder); form.addRow("指令名称",self.iname); form.addRow("详细指令",self.icontent); form.addRow("备注",self.inote); edit_layout.addLayout(form); bs=QHBoxLayout(); bs.addWidget(self.btn("＋ 新建指令",self.new_instruction)); bs.addWidget(self.btn("编辑指令",self.edit_instruction,"warning")); bs.addWidget(self.btn("删除指令",self.delete_instruction,"danger")); bs.addStretch(); self.copy_instruction_content_button=self.btn("复制指令内容",self.copy_current_instruction_content,"openExport");self.copy_instruction_content_button.setIcon(self.copy_icon());self.copy_instruction_content_button.setToolTip("复制当前编辑框中的完整指令内容");bs.addWidget(self.copy_instruction_content_button); bs.addWidget(self.btn("保存指令",self.save_instruction,"primary")); edit_layout.addLayout(bs)
        album=QFrame(); album.setObjectName("card"); album.setMinimumWidth(300); album.setMaximumWidth(430); album_layout=QVBoxLayout(album); album_layout.addWidget(self.title("作品封面与相册"))
        self.instruction_album_tip=QLabel("选中左侧的一条指令后，在这里添加作品图片、选择封面或移除图片关联。分类、改名和移动不会影响相册。"); self.instruction_album_tip.setWordWrap(True); album_layout.addWidget(self.instruction_album_tip)
        self.instruction_album_cover=InstructionAlbumCover(self.instruction_album_open_viewer); self.instruction_album_cover.setAlignment(Qt.AlignCenter); self.instruction_album_cover.setWordWrap(True); self.instruction_album_cover.setMinimumHeight(240); self.instruction_album_cover.setMaximumHeight(285); self.instruction_album_cover.setToolTip("双击封面，在本软件内浏览当前指令的相册图片。"); self.instruction_album_cover.setStyleSheet("background:rgba(21,31,43,235); border: 1px solid #8aa0c8; border-radius: 12px; padding: 10px;"); album_layout.addWidget(self.instruction_album_cover)
        album_actions=QHBoxLayout(); album_actions.addWidget(self.btn("＋ 添加图片",self.instruction_album_add_images,"primary")); album_actions.addWidget(self.btn("设为封面",self.instruction_album_set_cover,"warning")); album_actions.addWidget(self.btn("移除图片",self.instruction_album_remove_selected,"danger")); album_layout.addLayout(album_actions)
        self.instruction_album_list=InstructionAlbumList(self.instruction_album_receive); self.instruction_album_list.setViewMode(QListView.ViewMode.IconMode); self.instruction_album_list.setResizeMode(QListView.ResizeMode.Adjust); self.instruction_album_list.setIconSize(QSize(132,132)); self.instruction_album_list.setGridSize(QSize(148,166)); self.instruction_album_list.setSpacing(8); self.instruction_album_list.setWordWrap(True); self.instruction_album_list.setToolTip("图库采用大尺寸方形裁切缩略图，兼容横图、竖图与方图。可直接拖入图片，或从任意软件复制图片后在此按 Ctrl+V 粘贴；双击可在系统查看器中打开。"); self.instruction_album_list.itemDoubleClicked.connect(self.instruction_album_open_selected); album_layout.addWidget(self.instruction_album_list,1)
        self.instruction_splitter.addWidget(left_card); self.instruction_splitter.addWidget(edit); self.instruction_splitter.addWidget(album); self.instruction_splitter.setStretchFactor(0,1); self.instruction_splitter.setStretchFactor(1,3); self.instruction_splitter.setStretchFactor(2,1); self.instruction_splitter.setSizes([400,820,360]); self.set_instruction_editable(False); layout.addWidget(self.instruction_splitter); return page

    def system_page(self):
        page=QWidget(); layout=QVBoxLayout(page); layout.addWidget(self.title("系统设置")); card=QFrame(); card.setObjectName("card"); form=QFormLayout(card); form.setContentsMargins(18,18,18,18)
        self.config_path=QLineEdit(str(DATA_DIR));self.temp_path=QLineEdit(self.settings.get("temp_data_dir",str(DATA_DIR/"temporary"))); self.temp_path.setPlaceholderText("用于未来临时资料；不影响项目和指令库"); self.snapshot_path=QLineEdit(str(self.viewer_temp_directory()));self.snapshot_path.setReadOnly(True);self.snapshot_path.setEnabled(False);self.log_path=QLineEdit(self.settings.get("log_dir",str(LOG_DIR)));self.ui_scale_box=DoubleClickComboBox();
        for label,value in (("自动（按显示器分辨率）",1.0),("更紧凑 80%",.8),("紧凑 90%",.9),("标准 100%",1.0),("放大 110%",1.1),("放大 125%",1.25)):self.ui_scale_box.addItem(label,value)
        saved_scale=float(self.settings.get("ui_scale_preference",1.0) or 1.0);self.ui_scale_box.setCurrentIndex(next((index for index in range(self.ui_scale_box.count()) if abs(float(self.ui_scale_box.itemData(index))-saved_scale)<.01),0))
        form.addRow("用户配置目录",self.config_path); form.addRow("临时资料目录",self.temp_path); form.addRow("表格快照目录",self.snapshot_path); form.addRow("运行日志目录",self.log_path);form.addRow("界面缩放",self.ui_scale_box); form.addRow("背景图片路径",QLabel(self.settings.get("skin_background", "未设置")))
        buttons=QHBoxLayout(); buttons.addStretch();buttons.addWidget(self.btn("导航栏排序",self.configure_navigation_order,"warning"));buttons.addWidget(self.btn("选择配置目录",self.pick_config_dir,"selectOutput")); buttons.addWidget(self.btn("选择临时目录",self.pick_temp_dir,"selectOutput")); buttons.addWidget(self.btn("选择日志目录",self.pick_log_dir,"selectOutput")); buttons.addWidget(self.btn("打开配置目录",lambda:open_system_path(DATA_DIR),"openExportFolder")); buttons.addWidget(self.btn("打开日志目录",lambda:open_system_path(LOG_DIR),"openExportFolder")); buttons.addWidget(self.btn("备份配置",self.backup_config,"openExport"));buttons.addWidget(self.btn("恢复备份配置",self.restore_config,"warning"));buttons.addWidget(self.btn("初始化配置",self.initialize_config,"danger"));buttons.addWidget(self.btn("保存系统设置",self.save_system_settings,"primary")); form.addRow(buttons)
        note=QLabel("项目、指令库和历史记录使用系统标准用户配置目录，确保升级与更换程序位置后仍可保留。Windows 默认在 AppData\\Roaming，macOS 默认在 Library/Application Support，Linux 默认在 ~/.config 或 XDG_CONFIG_HOME。页面不足时可使用页面滚动条查看全部内容；界面缩放会与显示器自动比例叠加，并在保存后下次启动生效。临时资料目录与表格快照目录跨平台均固定在用户配置体系内；日志目录可单独配置。背景图片路径由皮肤设置管理。选择过的扫描、输出、项目和指令文件目录会自动记住。"); note.setWordWrap(True); form.addRow("说明",note); layout.addWidget(card); layout.addStretch(); return page

    def history_page(self):
        page=QWidget(); layout=QVBoxLayout(page); top=QHBoxLayout(); top.addWidget(self.title("操作历史")); top.addStretch(); top.addWidget(self.btn("清空操作历史记录",self.clear_history,"danger")); layout.addLayout(top); history_panel=QWidget();history_layout=QVBoxLayout(history_panel);history_layout.setContentsMargins(0,0,0,0);self.hlist=QListWidget();history_layout.addWidget(self.hlist);recent_card=QFrame();recent_card.setObjectName("card");recent_layout=QVBoxLayout(recent_card);recent_top=QHBoxLayout();recent_top.addWidget(QLabel("最近项目（最多显示 10 个）"));recent_top.addStretch();recent_top.addWidget(self.btn("清空最近项目",self.clear_recent,"danger"));recent_layout.addLayout(recent_top);self.recent=QListWidget();self.recent.itemDoubleClicked.connect(self.open_recent);recent_layout.addWidget(self.recent);self.history_splitter=QSplitter(Qt.Vertical);self.history_splitter.setChildrenCollapsible(False);self.history_splitter.addWidget(history_panel);self.history_splitter.addWidget(recent_card);self.history_splitter.setStretchFactor(0,1);self.history_splitter.setStretchFactor(1,1);self.history_splitter.setSizes([280,280]);layout.addWidget(self.history_splitter,1);return page

    def table_viewer_page(self):
        page=QWidget();layout=QVBoxLayout(page);top=QHBoxLayout();top.addWidget(self.title("查看表格"));top.addStretch();top.addWidget(self.btn("📄 打开表格文件",self.import_viewer_file,"primary"));top.addWidget(self.btn("🖼 匹配图片目录",self.choose_viewer_image_directory,"primary"));top.addWidget(self.btn("保存到原文件",self.save_viewer_file,"primary"));top.addWidget(self.btn("另存为",lambda:self.save_viewer_file(True),"openExport"));top.addWidget(self.btn("⧉ 复制选中单元格",lambda:self.viewer_table.copy_selection(),"viewerCopyCells"));top.addWidget(self.btn("编辑当前单元格",self.edit_current_viewer_cell,"warning"));top.addWidget(self.btn("适应列宽",self.fit_viewer_columns));layout.addLayout(top)
        hint=QLabel("此处与“素材整理”共用完整表格引擎：支持多选、复制/剪切/粘贴、批量填充、拖拽填充柄、撤销/重做与公式。打开表格后会新增最左侧“图片预览”审核列，原始表格列的顺序与宽度不改变；优先读取“图片完整路径”，也可选择图片目录递归按图片名匹配。可直接打开并保存 Excel、CSV、TSV；编辑后仅在点击“保存到原文件”或“另存为”时写入外部文件。双击或 F2 可直接编辑，长文本可使用“编辑当前单元格”。");hint.setWordWrap(True);layout.addWidget(hint)
        self.viewer_table=MaterialSpreadsheet(0,0);self.viewer_table.minimum_row_count=0;self.viewer_table.setAcceptDrops(True);self.viewer_table.viewport().setAcceptDrops(True);self.viewer_table.external_file_drop_callback=self.open_dropped_viewer_file;self.viewer_table.setSelectionMode(QAbstractItemView.ExtendedSelection);self.viewer_table.setSelectionBehavior(QAbstractItemView.SelectItems);self.viewer_table.setWordWrap(True);self.viewer_table.setTextElideMode(Qt.ElideNone);self.viewer_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive);self.viewer_table.verticalHeader().setSectionResizeMode(QHeaderView.Interactive);self.viewer_table.itemSelectionChanged.connect(self.show_viewer_cell_detail);self.viewer_table.changed.connect(self.save_viewer_edit)
        detail=QFrame();self.viewer_detail_panel=detail;detail.setObjectName("card");detail_layout=QVBoxLayout(detail);detail_top=QHBoxLayout();self.viewer_detail_title=QLabel("当前单元格完整内容");detail_top.addWidget(self.viewer_detail_title);detail_top.addStretch();self.viewer_detail_toggle=self.btn("隐藏完整内容",self.toggle_viewer_detail);detail_top.addWidget(self.viewer_detail_toggle);self.viewer_detail_edit_button=self.btn("编辑内容",self.edit_viewer_detail,"warning");detail_top.addWidget(self.viewer_detail_edit_button);detail_top.addWidget(self.btn("复制完整内容",self.copy_viewer_detail,"primary"));detail_layout.addLayout(detail_top);self.viewer_detail=QTextEdit();self.viewer_detail.setReadOnly(True);self.viewer_detail.setPlaceholderText("点击表格中的任意单元格，即可在这里查看完整内容。");detail_layout.addWidget(self.viewer_detail,1)
        self.viewer_splitter=QSplitter(Qt.Vertical);self.viewer_splitter.setChildrenCollapsible(False);self.viewer_splitter.addWidget(self.viewer_table);self.viewer_splitter.addWidget(detail);self.viewer_splitter.setStretchFactor(0,3);self.viewer_splitter.setStretchFactor(1,1);self.viewer_splitter.setSizes([440,180]);layout.addWidget(self.viewer_splitter,1)
        self.viewer_file_status=QLabel("当前未打开外部表格文件；可打开表格后编辑并保存。");self.viewer_file_status.setWordWrap(True);layout.addWidget(self.viewer_file_status);self.viewer_image_status=QLabel("图片审核：打开含图片名或图片路径的表格后，可自动或手动匹配图片预览。");self.viewer_image_status.setWordWrap(True);layout.addWidget(self.viewer_image_status)
        records=QFrame();self.viewer_records_panel=records;records.setObjectName("card");record_layout=QVBoxLayout(records);record_top=QHBoxLayout();record_top.addWidget(QLabel("最近打开与工作台导出的表格文件（最多 100 项）"));record_top.addStretch();self.viewer_records_toggle=self.btn("隐藏最近记录",self.toggle_viewer_records);record_top.addWidget(self.viewer_records_toggle);record_top.addWidget(self.btn("🗂 打开选中表格",self.open_selected_viewer_snapshot,"primary"));record_top.addWidget(self.btn("刷新记录",self.refresh_viewer_snapshots));record_top.addWidget(self.btn("清除记录",self.clear_viewer_snapshots,"danger"));record_layout.addLayout(record_top);self.viewer_snapshots=QTableWidget(0,4);self.viewer_snapshots.setHorizontalHeaderLabels(("时间","类型","名称","文件位置"));self.viewer_snapshots.setEditTriggers(QTableWidget.NoEditTriggers);self.viewer_snapshots.setSelectionBehavior(QTableWidget.SelectRows);self.viewer_snapshots.setSelectionMode(QAbstractItemView.SingleSelection);self.viewer_snapshots.setFocusPolicy(Qt.NoFocus);self.viewer_snapshots.setShowGrid(True);self.viewer_snapshots.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch);self.viewer_snapshots.itemDoubleClicked.connect(lambda *_:self.open_selected_viewer_snapshot());record_layout.addWidget(self.viewer_snapshots);layout.addWidget(records)
        self.set_viewer_detail_visible(not bool(self.settings.get("viewer_detail_hidden",False)))
        self.set_viewer_records_visible(not bool(self.settings.get("viewer_records_hidden",False)))
        return page

    def set_viewer_detail_visible(self,visible,remember=False):
        """折叠或展开长文本详情；标题栏始终保留，避免收起后无法恢复。"""
        if not hasattr(self,"viewer_detail_panel"):return
        self.viewer_detail.setVisible(bool(visible))
        # 卡片本身有上下内边距，48px 会截断标题；保留足够高度显示完整标题栏。
        self.viewer_detail_panel.setMaximumHeight(16777215 if visible else 78)
        if hasattr(self,"viewer_detail_toggle"):
            self.viewer_detail_toggle.setText("收起完整内容" if visible else "展开完整内容")
        if visible and hasattr(self,"viewer_splitter"):
            self.viewer_splitter.setSizes([440,180])
        elif hasattr(self,"viewer_splitter"):
            self.viewer_splitter.setSizes([440,78])
        if remember:
            self.settings["viewer_detail_hidden"]=not bool(visible);save_app_settings(self.settings)

    def toggle_viewer_detail(self):
        self.set_viewer_detail_visible(self.viewer_detail.isHidden(),True)

    def set_viewer_records_visible(self,visible,remember=False):
        """折叠或展开最近记录；标题栏始终保留，避免收起后无法恢复。"""
        if not hasattr(self,"viewer_records_panel"):return
        self.viewer_snapshots.setVisible(bool(visible))
        # 同上：最近记录卡片的标题和操作按钮必须在折叠后始终完整可见。
        self.viewer_records_panel.setMaximumHeight(16777215 if visible else 78)
        if hasattr(self,"viewer_records_toggle"):
            self.viewer_records_toggle.setText("收起最近记录" if visible else "展开最近记录")
        if remember:
            self.settings["viewer_records_hidden"]=not bool(visible);save_app_settings(self.settings)

    def toggle_viewer_records(self):
        self.set_viewer_records_visible(self.viewer_snapshots.isHidden(),True)

    def material_organizer_page(self):
        """完整项目素材整理、匹配、汇总与批量导出流水线。"""
        # 首次运行写入明确的本地模式默认值；已有用户选择（尤其是 api）绝不覆盖。
        ai_defaults=self.settings.get("material_organizer_ai")
        if not isinstance(ai_defaults,dict):
            self.settings["material_organizer_ai"]={"mode":"clip"}
            save_app_settings(self.settings)
        elif not str(ai_defaults.get("mode","") or "").strip():
            ai_defaults["mode"]="clip"
            save_app_settings(self.settings)
        page=QWidget();layout=QVBoxLayout(page);top=QHBoxLayout();top.addWidget(self.title("素材整理与汇总预览"));top.addWidget(QLabel("项目素材整理 · 智能匹配与结果导出"));top.addStretch();layout.addLayout(top)
        pipeline=QFrame();pipeline.setObjectName("card");form=QFormLayout(pipeline);form.setContentsMargins(16,12,16,12)
        self.material_root_input=FolderDropLineEdit(self.settings.get("material_organizer_root",""));self.material_root_input.setPlaceholderText("可直接拖入总目录（其子文件夹可批量建立为项目）");self.material_root_input.textChanged.connect(self.save_material_organizer);root_row=QHBoxLayout();root_row.addWidget(self.material_root_input,1);root_row.addWidget(self.btn("浏览",self.choose_material_root,"selectInput"));form.addRow("监控总素材根目录 (A)",root_row)
        self.material_global_output=FolderDropLineEdit(self.settings.get("material_organizer_output",""));self.material_global_output.setPlaceholderText("所有项目共用的默认整理输出目录，支持 {date}、{yyyy-MM-dd}、{yyyyMMdd}、{project}");self.material_global_output.textChanged.connect(self.save_material_organizer);out_row=QHBoxLayout();out_row.addWidget(self.material_global_output,1);out_row.addWidget(self.btn("浏览",self.choose_material_global_output,"selectOutput"));form.addRow("全局统一存放位置",out_row)
        hint=QLabel("项目自己的“整理后存放位置”留空时自动使用全局路径。路径变量会在实际导出时解析，适合按日期和项目自动归档。 ");hint.setWordWrap(True);form.addRow("说明",hint)
        action_host=QWidget();actions=FlowLayout(action_host,4,6);actions.addWidget(self.btn("图文审核台",self.show_material_summary,"primary"));actions.addWidget(self.btn("导出全部项目汇总",self.export_material_summary,"openExport"));actions.addWidget(self.btn("批量从文件夹建项",self.batch_create_material_projects,"loadData"));actions.addWidget(self.btn("图片库存报告",self.show_material_stock,"warning"));self.material_auto_sort=QCheckBox("匹配完成后自动整理并导出");self.material_auto_sort.setToolTip("开启后，AI 回填图片路径成功会立即按项目输出目录创建整理文件夹、复制图片并导出 CSV。");self.material_auto_sort.setChecked(bool(self.settings.get("material_organizer_auto_sort",True)));self.material_auto_sort.toggled.connect(self.save_material_organizer);actions.addWidget(self.material_auto_sort);actions.addWidget(self.btn("AI 配置",self.material_ai_config,"warning"));actions.addWidget(self.btn("AI 方案管理",self.manage_material_ai_profiles,"warning"));actions.addWidget(self.btn("开始一键批量 AI 匹配",self.start_all_material_ai_match,"primary"));actions.addWidget(self.btn("停止批量 AI 匹配",self.stop_all_material_ai_match,"danger"));actions.addWidget(self.btn("查看批量结果",self.show_material_batch_results,"openExport"));actions.addWidget(self.btn("一键整理全部项目",self.organize_all_material_projects,"openExport"));actions.addWidget(self.btn("导出分段图片",self.export_all_material_segment_images,"openExport"));self.material_auto_split=QCheckBox("整理后自动导出分段英文");self.material_auto_split.setChecked(bool(self.settings.get("material_organizer_auto_split",False)));self.material_auto_split.toggled.connect(self.save_material_organizer);actions.addWidget(self.material_auto_split);actions.addWidget(self.btn("一键导出分段英文",self.export_all_material_split_english,"openExport"));actions.addWidget(self.btn("全局智能 CSV 导入",self.global_material_csv_import,"loadData"));action_host.setMinimumHeight(190);form.addRow(action_host);layout.addWidget(pipeline)
        controls=QFrame();controls.setObjectName("card");control_layout=QHBoxLayout(controls);control_layout.setContentsMargins(16,9,16,9);control_layout.addWidget(QLabel("项目名："));self.material_project_name=QLineEdit();self.material_project_name.setPlaceholderText("输入项目名称后新增");control_layout.addWidget(self.material_project_name,1);control_layout.addWidget(self.btn("＋ 添加项目",self.add_material_project,"primary"));control_layout.addWidget(self.btn("重命名当前项目",self.rename_material_project));control_layout.addWidget(self.btn("删除当前项目",self.delete_material_project,"danger"));control_layout.addWidget(self.btn("清空全部项目数据",self.clear_all_material_projects,"warning"));control_layout.addWidget(self.btn("删除全部项目",self.delete_all_material_projects,"danger"));control_layout.addWidget(self.btn("从工作台预览导入",self.import_workspace_rows_to_material,"warning"));self.material_global_count=QLabel("所有项目素材总计：0 条");self.material_global_count.setObjectName("sideMuted");control_layout.addWidget(self.material_global_count);layout.addWidget(controls)
        progress_row=QHBoxLayout();self.material_pipeline_progress=QProgressBar();self.material_pipeline_progress.setRange(0,100);self.material_pipeline_progress.setValue(0);self.material_pipeline_status=QLabel("就绪：可建立项目、导入数据或启动 AI 匹配");progress_row.addWidget(self.material_pipeline_progress,1);progress_row.addWidget(self.material_pipeline_status);layout.addLayout(progress_row)
        self.material_project_tabs=QTabWidget();self.material_project_tabs.setTabsClosable(True);self.material_project_tabs.setMovable(True);self.material_project_tabs.tabCloseRequested.connect(self.close_material_project);self.material_project_tabs.tabBarDoubleClicked.connect(lambda index:self.rename_material_project() if index>=0 else None);self.material_project_tabs.tabBar().tabMoved.connect(self.save_material_organizer);layout.addWidget(self.material_project_tabs,1);self.material_projects={};self._material_loading=True;self.material_project_tabs.currentChanged.connect(self.remember_material_active_project)
        saved=self.settings.get("material_organizer_projects",[])
        for project in saved if isinstance(saved,list) else []:
            if isinstance(project,dict) and str(project.get("name","")).strip():self.create_material_project(str(project["name"]).strip(),project,insert_at_front=False)
        self._material_loading=False
        last_active=str(self.settings.get("material_organizer_last_active_project","") or "")
        if last_active in self.material_projects:self.material_project_tabs.setCurrentWidget(self.material_projects[last_active]["widget"])
        self.remember_material_active_project(self.material_project_tabs.currentIndex())
        self.refresh_material_global_count()
        return page

    def choose_material_root(self):
        path=QFileDialog.getExistingDirectory(self,"选择总素材根目录",self.material_root_input.text().strip() or self.settings.get("last_input_dir","") or "")
        if path:self.material_root_input.setText(path)

    def choose_material_global_output(self):
        path=QFileDialog.getExistingDirectory(self,"选择全局统一存放位置",self.material_global_output.text().strip() or self.settings.get("last_output_dir","") or "")
        if path:self.material_global_output.setText(path)

    def material_render_path(self,path_template,project=""):
        """先展开路径变量、再生成 Path；绝不把含变量的原文路径直接用于扫描。"""
        text=render_path_template(path_template,project_name=project)
        return Path(text).absolute() if text else None

    def material_safe_name(self,value,fallback="未命名"):
        text="".join("_" if char in '<>:"/\\|?*' else char for char in str(value or "").strip()).strip(". ")
        return text[:120] or fallback

    def material_unique_path(self,folder,stem,extension="",max_component=180,max_full=240):
        """main.py 的 make_unique_path 规则：保留原有输出，不覆盖同名素材。"""
        return Path(make_unique_path(str(Path(folder).absolute()),stem,extension,max_component,max_full))

    def material_project_by_widget(self,widget):
        for name,entry in getattr(self,"material_projects",{}).items():
            if entry.get("widget") is widget:return name
        return ""

    def refresh_material_global_count(self):
        if hasattr(self,"material_global_count"):
            total=sum(len(self.material_rows(name)) for name in getattr(self,"material_projects",{}))
            self.material_global_count.setText(f"所有项目素材总计：{total} 条")

    def remember_material_active_project(self,index=None):
        """记录最近使用的素材项目，供工作台目录选择按最近项目置顶。"""
        if getattr(self,"_material_loading",False) or not hasattr(self,"material_project_tabs"):return
        index=self.material_project_tabs.currentIndex() if index is None else index
        if index is None or index<0:return
        name=self.material_project_tabs.tabText(index).strip()
        if not name:return
        recent=self.settings.get("material_organizer_recent_projects",[])
        recent=[str(item) for item in recent] if isinstance(recent,list) else []
        recent=[item for item in recent if item in self.material_projects and item!=name]
        self.settings["material_organizer_last_active_project"]=name;self.settings["material_organizer_recent_projects"]=[name,*recent][:100]
        save_app_settings(self.settings)

    def material_projects_by_recent_use(self):
        """返回最近使用在前的项目名；旧配置没有历史时保留现有项目顺序。"""
        names=list(getattr(self,"material_projects",{}))
        recent=self.settings.get("material_organizer_recent_projects",[])
        recent=[str(item) for item in recent] if isinstance(recent,list) else []
        ordered=[]
        for name in recent:
            if name in names and name not in ordered:ordered.append(name)
        active=str(self.settings.get("material_organizer_last_active_project","") or "")
        if active in names:
            ordered=[active,*[name for name in ordered if name!=active]]
        return ordered+[name for name in names if name not in ordered]

    def create_material_project(self,name,data=None,insert_at_front=True):
        name=str(name or "").strip()
        if not name or name in self.material_projects:return False
        data=data if isinstance(data,dict) else {};widget=QWidget();widget.setProperty("material_project_name",name);layout=QVBoxLayout(widget);layout.setContentsMargins(10,10,10,10)
        paths=QFrame();paths.setObjectName("card");form=QFormLayout(paths);form.setContentsMargins(12,10,12,10)
        source=FolderDropLineEdit(str(data.get("source","")));source.setPlaceholderText("可选：素材来源目录，可拖入文件夹路径");target=FolderDropLineEdit(str(data.get("output","")));target.setPlaceholderText("可选：单独整理输出目录，留空时使用全局统一存放位置；支持路径变量")
        for field in (source,target):field.textChanged.connect(self.save_material_organizer)
        source_row=QHBoxLayout();source_row.addWidget(source,1);source_row.addWidget(self.btn("📁 选择素材目录",lambda field=source:self.pick_material_folder(field),"primary"));source_row.addWidget(self.btn("打开文件夹",lambda field=source:self.open_material_folder(field),"openExportFolder"));output_row=QHBoxLayout();output_row.addWidget(target,1);output_row.addWidget(self.btn("🗂 选择项目输出目录",lambda field=target:self.pick_material_folder(field),"primary"));output_row.addWidget(self.btn("打开文件夹",lambda project=name:self.open_material_folder(project_name=project),"openExportFolder"));form.addRow("素材来源目录",source_row);form.addRow("整理后存放位置",output_row);layout.addWidget(paths)
        stat=QHBoxLayout();count_label=QLabel("已录入有效素材数：0");stat.addWidget(count_label);stat.addStretch();stat.addWidget(QLabel("英文分段字数："));split_limit=QSpinBox();split_limit.setRange(0,200000);split_limit.setKeyboardTracking(False)
        # 每个已存在项目保留自己的设置；新项目则从最近一次用户修改的数值继承，首次默认 135。
        raw_default=self.settings.get("material_organizer_last_split_limit",135)
        try:default_split_limit=max(0,min(200000,int(raw_default)))
        except (TypeError,ValueError):default_split_limit=135
        project_split_limit=data.get("split_limit",default_split_limit) if isinstance(data,dict) else default_split_limit
        try:project_split_limit=max(0,min(200000,int(project_split_limit)))
        except (TypeError,ValueError):project_split_limit=default_split_limit
        split_limit.setValue(project_split_limit);split_limit.setFixedWidth(100);split_limit.setToolTip("可手动输入或使用上下箭头调节。该数值是每段英文的目标词数，不会从一句完整台词中间硬切；短尾段会自动合并。输入 0 时不切分英文文案，但仍会为每条文案输出 1.txt。 ");stat.addWidget(split_limit);layout.addLayout(stat)
        table=MaterialSpreadsheet(max(40,len(data.get("rows",[]))),6);table.setHorizontalHeaderLabels(("代码","图片路径（拖入 / AI 匹配）","评分","中文文案","英文文案","备注（特殊要求）"));table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        for column,width in enumerate((110,300,90,270,270,220)):table.setColumnWidth(column,width)
        rows=data.get("rows",[]) if isinstance(data.get("rows",[]),list) else []
        table.setRowCount(max(40,len(rows)))
        for row_index,row in enumerate(rows):
            values=row if isinstance(row,list) else []
            for column,value in enumerate((values+[""]*6)[:6]):table.setItem(row_index,column,QTableWidgetItem(str(value)))
        # 兼容旧版核心模块：即使用户尚未同步 core，也不能阻止程序启动。
        if hasattr(table,"reset_history"):table.reset_history()
        def refresh_count(*_):
            count_label.setText(f"已录入有效素材数：{len(self.material_rows(name))}" if name in getattr(self,"material_projects",{}) else "已录入有效素材数：0")
            self.refresh_material_global_count()
        table.changed.connect(lambda:(refresh_count(),self.save_material_organizer()))
        def remember_split_limit(*_):
            value=self.material_split_limit_value(split_limit)
            split_limit.setValue(value)
            self.settings["material_organizer_last_split_limit"]=value
            self.save_material_organizer()
        split_limit.valueChanged.connect(remember_split_limit);layout.addWidget(table,1)
        buttons=QHBoxLayout();buttons.addWidget(self.btn("＋ 添加一行",lambda table=table:table.add_rows()));buttons.addWidget(self.btn("删除选中行",table.delete_selected_rows,"danger"));buttons.addWidget(self.btn("撤销表格",table.undo_sheet));buttons.addWidget(self.btn("重做表格",table.redo_sheet));buttons.addWidget(self.btn("智能导入当前项目",lambda project=name,table=table:self.smart_import_material_project(project,table),"loadData"));buttons.addWidget(self.btn("🧹 清空当前表格",lambda table=table:self.material_clear_table(table),"primary"));move_mode=QCheckBox("移动模式（剪切）")
        # 已保存项目优先保留自己的状态；全新配置的首次项目默认“复制”，避免移动源素材。
        move_enabled=bool(data["move_mode"]) if "move_mode" in data else bool(self.settings.get("material_organizer_last_move_mode",False))
        move_mode.setChecked(move_enabled);move_mode.toggled.connect(self.remember_material_move_mode);buttons.addWidget(move_mode);buttons.addWidget(self.btn("撤销上次整理",self.undo_material_organize));buttons.addWidget(self.btn("✨ AI 智能图文匹配",lambda project=name:self.start_material_ai_match(project),"primary"));buttons.addWidget(self.btn("停止当前 AI 匹配",self.stop_material_ai_match,"danger"));buttons.addStretch();buttons.addWidget(self.btn("仅整理当前项目",lambda project=name:self.organize_material_project(project),"openExport"));buttons.addWidget(self.btn("仅导出当前项目 CSV",lambda project=name:self.export_material_project_csv(project),"openExport"));buttons.addWidget(self.btn("📤 导出当前项目分段英文",lambda project=name:self.export_material_split_english(project),"primary"));layout.addLayout(buttons)
        self.material_projects[name]={"widget":widget,"source":source,"output":target,"table":table,"split_limit":split_limit,"move_mode":move_mode,"count_label":count_label}
        tab_index=0 if insert_at_front else self.material_project_tabs.count()
        self.material_project_tabs.insertTab(tab_index,widget,name)
        refresh_count();self.refresh_material_global_count();return True

    def pick_material_folder(self,field):
        path=QFileDialog.getExistingDirectory(self,"选择文件夹",field.text().strip() or self.settings.get("last_input_dir","") or "")
        if path:field.setText(path)

    def open_material_folder(self, field=None, project_name=""):
        """打开素材项目的来源目录或实际整理输出目录，不自动创建不存在的文件夹。"""
        if project_name:
            # 与整理、CSV、英文分段导出使用完全相同的最终项目路径：先解析
            # 全局/项目覆盖模板及日期变量，再进入项目名目录，不能只打开输出根目录。
            entry=self.material_projects.get(project_name,{})
            project_template=entry.get("output").text().strip() if entry.get("output") else ""
            # 项目留空时，按钮应顺着相同的输出规则打开全局默认根目录；不能因为
            # “项目子目录尚未首次导出”就误报未设置或不存在。
            if not project_template:
                directory=self.material_output_root(project_name)
                label=f"项目“{project_name}”留空时使用的全局统一存放位置"
            else:
                directory=self.material_project_output_directory(project_name)
                label=f"项目“{project_name}”的最终导出位置"
        else:
            text=field.text().strip() if field is not None else ""
            # 来源目录也允许填写日期模板；打开时使用当天展开后的实际目录。
            directory=self.material_render_path(text) if text else None
            label="素材来源目录"
        if not directory:
            if project_name:
                QMessageBox.information(self,"尚未设置目录",f"当前项目的“整理后存放位置”留空时会使用全局统一存放位置；但全局位置也尚未填写。\n\n请填写全局统一存放位置，或直接填写项目“{project_name}”的整理后存放位置。")
            else:
                QMessageBox.information(self,"尚未设置目录",f"请先设置{label}，再打开文件夹。")
            return
        directory=Path(directory)
        if not directory.is_dir():
            QMessageBox.warning(self,"目录不存在",f"{label}当前不存在：\n{directory}\n\n请检查路径，或先完成一次整理导出后再打开。")
            return
        try:
            open_system_path(directory)
        except OSError as error:
            LOGGER.exception("打开素材目录失败：%s",directory)
            QMessageBox.warning(self,"无法打开目录",str(error))

    def material_add_row(self,table):table.insertRow(table.rowCount());self.save_material_organizer()
    def material_delete_rows(self,table):
        for row in sorted({index.row() for index in table.selectedIndexes()},reverse=True):table.removeRow(row)
        self.save_material_organizer()
    def material_clear_table(self,table):
        if QMessageBox.question(self,"清空当前表格","将清空当前素材项目中的全部表格内容。是否继续？")==QMessageBox.Yes:
            if isinstance(table,MaterialSpreadsheet):table.clear_sheet()
            else:table.setRowCount(10)
            self.save_material_organizer()

    def material_rows(self,name):
        entry=self.material_projects.get(name,{});table=entry.get("table");result=[]
        if not table:return result
        for row in range(table.rowCount()):
            values=[table.item(row,column).text().strip() if table.item(row,column) else "" for column in range(6)]
            if any(values):result.append(values)
        return result

    def material_split_limit_value(self,widget_or_entry):
        """读取手动输入的英文分段字数；0 是有效值，代表每条英文只输出一个 1.txt。"""
        widget=widget_or_entry.get("split_limit") if isinstance(widget_or_entry,dict) else widget_or_entry
        raw=widget.text().strip() if widget is not None and hasattr(widget,"text") else ""
        try:return max(0,min(200000,int(raw)))
        except (TypeError,ValueError):return 135

    def remember_material_move_mode(self, enabled):
        """保存最后一次“移动模式”选择，供后续新项目和下次启动继承。"""
        self.settings["material_organizer_last_move_mode"] = bool(enabled)
        self.save_material_organizer()

    def save_material_organizer(self,*_):
        if getattr(self,"_material_loading",False) or not hasattr(self,"material_projects"):return
        # 按标签栏从左到右保存。这样“最后添加的项目在最左侧”的顺序，以及用户
        # 手动拖拽调整后的顺序，重启软件后都能保持不变。
        names=[]
        if hasattr(self,"material_project_tabs"):
            names=[self.material_project_tabs.tabText(index) for index in range(self.material_project_tabs.count())]
        names+=[name for name in self.material_projects if name not in names]
        projects=[]
        for name in names:
            entry=self.material_projects.get(name)
            if not entry:continue
            projects.append({"name":name,"source":entry["source"].text().strip(),"output":entry["output"].text().strip(),"rows":self.material_rows(name),"split_limit":self.material_split_limit_value(entry.get("split_limit")) if entry.get("split_limit") else 135,"move_mode":entry["move_mode"].isChecked() if entry.get("move_mode") else False})
        self.settings["material_organizer_projects"]=projects;self.settings["material_organizer_output"]=self.material_global_output.text().strip() if hasattr(self,"material_global_output") else "";self.settings["material_organizer_root"]=self.material_root_input.text().strip() if hasattr(self,"material_root_input") else "";self.settings["material_organizer_auto_sort"]=self.material_auto_sort.isChecked() if hasattr(self,"material_auto_sort") else False;self.settings["material_organizer_auto_split"]=self.material_auto_split.isChecked() if hasattr(self,"material_auto_split") else False;save_app_settings(self.settings)

    def add_material_project(self):
        name=self.material_project_name.text().strip()
        if not name:QMessageBox.warning(self,"请输入项目名","请先输入项目名称，再添加项目。 ");return
        if not self.create_material_project(name):QMessageBox.warning(self,"无法添加项目",f"项目“{name}”已存在，或名称无效。 ");return
        self.material_project_name.clear();self.material_project_tabs.setCurrentIndex(0);self.save_material_organizer()

    def close_material_project(self,index):
        if index<0:return
        name=self.material_project_tabs.tabText(index);self.material_projects.pop(name,None);self.material_project_tabs.removeTab(index);self.refresh_material_global_count();self.save_material_organizer()
    def delete_material_project(self):
        index=self.material_project_tabs.currentIndex()
        if index<0:return
        name=self.material_project_tabs.tabText(index)
        if QMessageBox.question(self,"删除项目",f"将删除素材项目“{name}”及其表格记录。\n不会删除原始素材或已导出文件。是否继续？")==QMessageBox.Yes:self.close_material_project(index)
    def rename_material_project(self):
        index=self.material_project_tabs.currentIndex()
        if index<0:return
        old=self.material_project_tabs.tabText(index);new,ok=QInputDialog.getText(self,"重命名素材项目","项目名称：",text=old);new=str(new).strip()
        if not ok or not new or new==old:return
        if new in self.material_projects:QMessageBox.warning(self,"项目已存在",f"项目“{new}”已存在，请换一个名称。 ");return
        self.material_projects[new]=self.material_projects.pop(old);self.material_projects[new]["widget"].setProperty("material_project_name",new);self.material_project_tabs.setTabText(index,new);self.save_material_organizer()

    def batch_create_material_projects(self):
        root=self.material_root_input.text().strip() if hasattr(self,"material_root_input") else ""
        if not Path(root).is_dir():root=QFileDialog.getExistingDirectory(self,"选择总素材根目录",self.settings.get("last_input_dir","") or "")
        if not root:return
        root_path=Path(root);dialog,layout=self.themed_dialog("选择要建立的素材项目",760,680)
        note=QLabel("勾选任意层级的文件夹后建立项目。项目名使用相对路径，避免不同父目录下的同名文件夹互相冲突。 ");note.setWordWrap(True);layout.addWidget(note)
        tree=QTreeWidget();tree.setHeaderLabels(("文件夹目录","完整路径"));tree.setSelectionMode(QAbstractItemView.ExtendedSelection);layout.addWidget(tree,1)
        loaded_role=int(Qt.ItemDataRole.UserRole)+1
        def add_folder(parent_item,folder):
            item=QTreeWidgetItem((str(folder.relative_to(root_path)),str(folder)));item.setData(0,Qt.UserRole,str(folder));item.setData(0,loaded_role,False);item.setFlags(item.flags()|Qt.ItemIsUserCheckable);item.setCheckState(0,Qt.Unchecked);parent_item.addChild(item)
            try:has_children=any(child.is_dir() for child in folder.iterdir())
            except OSError:has_children=False
            if has_children:item.addChild(QTreeWidgetItem(("正在展开…","")))
            else:item.setData(0,loaded_role,True)
            return item
        def load_children(item):
            if item.data(0,loaded_role):return
            folder=Path(item.data(0,Qt.UserRole));item.takeChildren()
            try:children=sorted((child for child in folder.iterdir() if child.is_dir()),key=lambda child:child.name.casefold())
            except OSError:children=[]
            for child in children:add_folder(item,child)
            item.setData(0,loaded_role,True)
        def load_all(item):
            load_children(item)
            for index in range(item.childCount()):load_all(item.child(index))
        root_item=QTreeWidgetItem((root_path.name,str(root_path)));root_item.setData(0,Qt.UserRole,str(root_path));root_item.setData(0,loaded_role,False);root_item.setFlags(root_item.flags()|Qt.ItemIsUserCheckable);root_item.setCheckState(0,Qt.Unchecked);tree.addTopLevelItem(root_item);load_children(root_item);tree.itemExpanded.connect(load_children);tree.expandToDepth(1)
        def select_all_folders():load_all(root_item);self._set_material_tree_checks(tree,Qt.Checked)
        buttons=QHBoxLayout();select_all=self.btn("全选",select_all_folders);select_none=self.btn("全不选",lambda:self._set_material_tree_checks(tree,Qt.Unchecked));buttons.addWidget(select_all);buttons.addWidget(select_none);buttons.addStretch();buttons.addWidget(self.btn("取消",dialog.reject));buttons.addWidget(self.btn("建立项目",dialog.accept,"primary"));layout.addLayout(buttons)
        if dialog.exec()!=QDialog.Accepted:return
        selected=[]
        def collect(item):
            if item.checkState(0)==Qt.Checked:selected.append(Path(item.data(0,Qt.UserRole)))
            for index in range(item.childCount()):collect(item.child(index))
        collect(root_item)
        selected=[folder for folder in selected if folder!=root_path]
        if not selected:QMessageBox.information(self,"未选择文件夹","请至少勾选一个子文件夹。 ");return
        added=0;skipped=[]
        for folder in selected:
            project_name=str(folder.relative_to(root_path)).replace("\\"," / ")
            if self.create_material_project(project_name,{"source":str(folder)}):added+=1
            else:skipped.append(project_name)
        self.material_root_input.setText(str(root_path));self.save_material_organizer();QMessageBox.information(self,"批量建项完成",f"已新增 {added} 个项目。"+(f"\n已跳过 {len(skipped)} 个同名项目。" if skipped else ""))

    def _set_material_tree_checks(self,tree,state):
        def apply(item):
            item.setCheckState(0,state)
            for index in range(item.childCount()):apply(item.child(index))
        for index in range(tree.topLevelItemCount()):apply(tree.topLevelItem(index))

    def clear_all_material_projects(self):
        if not self.material_projects:return
        if QMessageBox.question(self,"清空全部项目数据","将清空全部素材项目的表格内容，但保留项目及其路径。是否继续？")!=QMessageBox.Yes:return
        self._material_loading=True
        for entry in self.material_projects.values():
            table=entry["table"]
            if isinstance(table,MaterialSpreadsheet):table.clear_sheet()
            else:table.setRowCount(10)
        self._material_loading=False;self.save_material_organizer();QMessageBox.information(self,"已清空","全部素材项目的表格数据已清空。")

    def delete_all_material_projects(self):
        if not self.material_projects:return
        if QMessageBox.question(self,"删除全部项目","将删除全部素材项目及其保存的表格配置。\n不会删除原始素材和已导出文件。是否继续？")!=QMessageBox.Yes:return
        self.material_projects.clear();self.material_project_tabs.clear();self.save_material_organizer();QMessageBox.information(self,"已删除","全部素材项目已删除。")

    def material_ai_config(self):
        config=dict(self.settings.get("material_organizer_ai",{}));dialog,layout=self.themed_dialog("素材整理 AI 配置",760,640);note=QLabel("默认使用本地 CLIP 极速匹配，不需要填写 API。远程 API 模式支持按行填写多个 Key，遇到限流或认证失败会自动尝试下一个 Key。CLIP 首次运行可能下载模型。 ");note.setWordWrap(True);layout.addWidget(note);form=QFormLayout();mode=DoubleClickComboBox();mode.addItem("本地 CLIP 极速匹配", "clip");mode.addItem("远程视觉 API", "api");mode.setCurrentIndex(0 if str(config.get("mode","clip") or "clip")=="clip" else 1);api_base=QLineEdit(str(config.get("api_base","https://api.openai.com/v1")));keys=config.get("api_keys",[]) if isinstance(config.get("api_keys",[]),list) else [];keys=keys or ([str(config.get("api_key","")).strip()] if str(config.get("api_key","")).strip() else []);api_keys=QTextEdit("\n".join(keys));api_keys.setPlaceholderText("每行一个 API Key；只在远程视觉 API 模式使用");api_keys.setFixedHeight(76);model=QLineEdit(str(config.get("model","gpt-4o-mini")));clip_model=QLineEdit(str(config.get("clip_model","OFA-Sys/chinese-clip-vit-large-patch14")));clip_gpu=QCheckBox("CLIP 优先使用 GPU");clip_gpu.setChecked(bool(config.get("clip_gpu",True)));max_scan=QSpinBox();max_scan.setRange(1,100000);max_scan.setValue(max(1,min(100000,int(config.get("max_scan",300) or 300))));api_interval=QSpinBox();api_interval.setRange(0,3600);api_interval.setValue(max(0,min(3600,int(config.get("api_interval",5) or 5))));api_retries=QSpinBox();api_retries.setRange(0,20);api_retries.setValue(max(0,min(20,int(config.get("api_max_retries",3) or 3))));form.addRow("匹配模式",mode);form.addRow("API 接口地址",api_base);form.addRow("API Key 池",api_keys);form.addRow("API 模型",model);form.addRow("CLIP 模型",clip_model);form.addRow("本地加速",clip_gpu);form.addRow("最大扫描图片数",max_scan);form.addRow("API 请求间隔（秒）",api_interval);form.addRow("API 失败重试次数",api_retries);layout.addLayout(form);buttons=QHBoxLayout();buttons.addStretch();buttons.addWidget(self.btn("取消",dialog.reject));buttons.addWidget(self.btn("保存 AI 配置",dialog.accept,"primary"));layout.addLayout(buttons);self.install_input_context_menus(dialog)
        if dialog.exec()!=QDialog.Accepted:return
        key_list=[line.strip() for line in api_keys.toPlainText().splitlines() if line.strip()];self.settings["material_organizer_ai"]={"mode":mode.currentData(),"api_base":api_base.text().strip(),"api_key":key_list[0] if key_list else "","api_keys":key_list,"model":model.text().strip(),"clip_model":clip_model.text().strip(),"clip_gpu":clip_gpu.isChecked(),"max_scan":max_scan.value(),"api_interval":api_interval.value(),"api_max_retries":api_retries.value()};save_app_settings(self.settings);QMessageBox.information(self,"AI 配置已保存","AI 匹配配置已保存到用户配置目录，下次启动继续使用。")

    def manage_material_ai_profiles(self):
        dialog,layout=self.themed_dialog("素材整理 AI 方案管理",760,520);layout.addWidget(QLabel("可将当前匹配 AI 配置保存为命名方案，并在不同模型、服务商或本地 CLIP 方案之间快速切换。"))
        profile_list=QListWidget();layout.addWidget(profile_list,1)
        profiles=dict(self.settings.get("material_organizer_ai_profiles",{}))
        def refresh():
            profile_list.clear()
            for name,config in sorted(profiles.items()):
                mode="本地 CLIP" if config.get("mode","clip")=="clip" else f"API · {config.get('model','未命名模型')}"
                item=QListWidgetItem(f"{name}  ·  {mode}");item.setData(Qt.UserRole,name);profile_list.addItem(item)
        def save_profile():
            name,ok=QInputDialog.getText(dialog,"保存 AI 方案","方案名称：")
            name=str(name).strip()
            if not ok or not name:return
            profiles[name]=dict(self.settings.get("material_organizer_ai",{}));self.settings["material_organizer_ai_profiles"]=profiles;save_app_settings(self.settings);refresh()
        def apply_profile():
            item=profile_list.currentItem()
            if not item:return
            name=item.data(Qt.UserRole);self.settings["material_organizer_ai"]=dict(profiles[name]);self.settings["material_organizer_ai_active_profile"]=name;save_app_settings(self.settings);QMessageBox.information(dialog,"已应用",f"已应用 AI 方案：{name}")
        def delete_profile():
            item=profile_list.currentItem()
            if not item:return
            name=item.data(Qt.UserRole)
            if QMessageBox.question(dialog,"删除 AI 方案",f"确定删除方案“{name}”吗？")==QMessageBox.Yes:profiles.pop(name,None);self.settings["material_organizer_ai_profiles"]=profiles;save_app_settings(self.settings);refresh()
        def test_current():
            config=dict(self.settings.get("material_organizer_ai",{}))
            if config.get("mode","clip")=="clip":QMessageBox.information(dialog,"本地 CLIP","本地 CLIP 无需远程连接测试；首次匹配时会加载模型。 ");return
            base=str(config.get("api_base","")).rstrip("/");keys=config.get("api_keys",[]) or [config.get("api_key","")]
            if not base or not any(keys):QMessageBox.warning(dialog,"无法测试","请先在 AI 配置中填写接口地址和 API Key。 ");return
            try:
                import requests
                response=requests.get(base+"/models",headers={"Authorization":f"Bearer {keys[0]}"},timeout=20)
                if response.status_code<500:QMessageBox.information(dialog,"连接成功",f"服务已响应（HTTP {response.status_code}）。")
                else:QMessageBox.warning(dialog,"连接失败",f"服务返回 HTTP {response.status_code}。")
            except Exception as error:QMessageBox.warning(dialog,"连接失败",str(error))
        buttons=QHBoxLayout();buttons.addWidget(self.btn("保存当前为方案",save_profile,"primary"));buttons.addWidget(self.btn("应用选中方案",apply_profile,"loadData"));buttons.addWidget(self.btn("测试当前连接",test_current,"warning"));buttons.addWidget(self.btn("删除方案",delete_profile,"danger"));buttons.addStretch();buttons.addWidget(self.btn("关闭",dialog.accept));layout.addLayout(buttons);refresh();dialog.exec()

    def material_review_ai_config(self):
        """审核模型与匹配模型分开保存，避免切换审核服务影响批量匹配。"""
        config=dict(self.settings.get("material_organizer_review_ai") or self.settings.get("material_organizer_ai",{}));dialog,layout=self.themed_dialog("图文审核 AI 配置",720,450)
        note=QLabel("审核使用远程视觉 API；留空时首次会带入匹配 AI 配置，但之后单独保存。支持多 API Key，每行一个。 ");note.setWordWrap(True);layout.addWidget(note);form=QFormLayout();base=QLineEdit(str(config.get("api_base","https://api.openai.com/v1")));keys=QTextEdit("\n".join(config.get("api_keys",[]) or ([config.get("api_key")] if config.get("api_key") else [])));keys.setFixedHeight(90);model=QLineEdit(str(config.get("model","gpt-4o-mini")));interval=QSpinBox();interval.setRange(0,3600);interval.setValue(int(config.get("api_interval",5) or 5));retries=QSpinBox();retries.setRange(0,20);retries.setValue(int(config.get("api_max_retries",3) or 3));form.addRow("API 接口地址",base);form.addRow("API Key 池",keys);form.addRow("审核模型",model);form.addRow("请求间隔（秒）",interval);form.addRow("失败重试次数",retries);layout.addLayout(form);buttons=QHBoxLayout();buttons.addStretch();buttons.addWidget(self.btn("取消",dialog.reject));buttons.addWidget(self.btn("保存审核配置",dialog.accept,"primary"));layout.addLayout(buttons)
        if dialog.exec()!=QDialog.Accepted:return
        key_list=[line.strip() for line in keys.toPlainText().splitlines() if line.strip()];self.settings["material_organizer_review_ai"]={"mode":"api","api_base":base.text().strip(),"api_key":key_list[0] if key_list else "","api_keys":key_list,"model":model.text().strip(),"api_interval":interval.value(),"api_max_retries":retries.value()};save_app_settings(self.settings);QMessageBox.information(self,"审核 AI 配置已保存","图文审核将使用独立配置，不影响图片匹配配置。")

    def material_image_paths(self,name):
        entry=self.material_projects.get(name,{});source=Path(entry.get("source").text().strip()) if entry.get("source") and entry["source"].text().strip() else None
        paths=[]
        if source and source.is_dir():
            try:paths=[path for path in source.rglob("*") if path.is_file() and path.suffix.lower() in MaterialAiMatchThread.IMAGE_EXTENSIONS]
            except OSError:paths=[]
        return paths

    def check_local_ai_runtime(self):
        """在启动线程前验证封装中的本地 CLIP 依赖，避免其他电脑点击后看似无响应。"""
        checks=(("torch","PyTorch 运算库"),("numpy","NumPy 数值库"),("PIL.Image","Pillow 图片库"),("transformers","Transformers CLIP 组件"),("safetensors","Safetensors 权重读取组件"))
        missing=[]
        for module,label in checks:
            try:__import__(module)
            except Exception as error:missing.append(f"{label}（{module}）：{error}")
        if not missing:return True
        details="\n".join(missing)
        message=("本机的本地 AI 匹配运行组件不完整，因此不能启动 CLIP 图文匹配。\n\n"
                 f"缺失或加载失败的组件：\n{details}\n\n"
                 "若这是封包后的程序，请使用更新后的 VideoTaskHub.spec 重新构建完整绿色版；"
                 "若运行源码，请先安装 requirements-ai.txt。也可以在“AI 配置”中改用已配置的远程视觉 API。")
        LOGGER.error("本地 AI 运行环境检查失败：%s",details);self.runtime_log_handler.append("素材整理｜本地 AI 运行组件不完整："+"；".join(missing),"ERROR");QMessageBox.warning(self,"本地 AI 组件缺失",message)
        return False

    def start_material_ai_match(self,name):
        # AI 只补齐图片路径为空的文案。用户已经填入的图片（无论来自手工指定、
        # 不同来源目录还是上一次核对结果）均是明确选择，必须保留且从候选池排除。
        running_thread=getattr(self,"material_ai_thread",None)
        # QThread 结束与 finished 回调之间存在极短窗口；只要当前项目标记尚未由
        # release_thread 清除，也必须继续排队，不能覆盖仍待清理的线程引用。
        if running_thread and (running_thread.isRunning() or getattr(self,"_material_ai_current_project",None)):
            # 用户可快速切换项目连续点击同一个“AI 智能图文匹配”按钮。AI 模型和
            # 表格回填必须串行，故将后续项目放入同一队列，而不是提示用户等待。
            queue=getattr(self,"_material_ai_queue",[])
            if not isinstance(queue,list):queue=[]
            current=str(getattr(self,"_material_ai_current_project","") or "")
            if name==current:
                self.material_pipeline_status.setText(f"AI 图文匹配正在执行：{name}")
            elif name in queue:
                self.material_pipeline_status.setText(f"AI 图文匹配已在队列中：{name}（前方 {queue.index(name)+1} 个项目）")
            else:
                queue.append(name);self._material_ai_queue=queue
                if getattr(self,"_material_batch_active",False):self._material_ai_total=getattr(self,"_material_ai_total",0)+1
                self.material_pipeline_status.setText(f"已加入 AI 图文匹配队列：{name}（前方 {len(queue)} 个项目）")
                self.runtime_log_handler.append(f"素材整理｜已排队 AI 图文匹配：{name}，前方 {len(queue)} 个项目")
            return True
        entry=self.material_projects.get(name,{})
        if not entry:
            LOGGER.warning("AI 匹配启动失败：找不到素材项目 %s",name)
            self.runtime_log_handler.append(f"素材整理｜无法启动 AI 匹配：项目不存在（{name}）","ERROR")
            QMessageBox.warning(self,"无法启动 AI 匹配",f"找不到素材项目“{name}”。请刷新页面后重试。")
            return False
        table=entry["table"];scripts=[]
        preserved_paths=[]
        for row in range(table.rowCount()):
            cn=table.item(row,3).text().strip() if table.item(row,3) else "";en=table.item(row,4).text().strip() if table.item(row,4) else "";remark=table.item(row,5).text().strip() if table.item(row,5) else ""
            image_path=table.item(row,1).text().strip() if table.item(row,1) else ""
            if not (cn or en or remark):continue
            if image_path:
                # 粘贴来的 file:/// 路径也要识别为同一张本地图片，避免它再次
                # 进入 AI 候选池并占用其它空白文案的图片。
                local_image_path=QUrl(image_path).toLocalFile() if image_path.casefold().startswith("file:") else image_path
                preserved_paths.append(local_image_path or image_path)
                continue
            scripts.append({"row":row,"cn":cn,"en":en,"remark":remark})
        if not scripts:
            QMessageBox.information(self,"无需 AI 匹配",f"项目“{name}”的全部文案行均已有图片路径。\nAI 不会覆盖已填写的图片路径；如需重新匹配，请先清空对应行的图片路径。")
            return False
        source=entry["source"].text().strip() if entry.get("source") else ""
        if not Path(source).is_dir():
            root=self.material_root_input.text().strip() if hasattr(self,"material_root_input") else "";candidate=Path(root)/name if root else None
            if candidate and candidate.is_dir():source=str(candidate);entry["source"].setText(source)
            else:QMessageBox.warning(self,"素材目录无效",f"项目“{name}”仍有 {len(scripts)} 条文案未填写图片路径。\n请为这些空白行填写图片路径，或填写有效的素材来源目录后再执行 AI 匹配。");return False
        # 只有开启“匹配完成后自动整理”时，本次 AI 匹配才会立即写入整理目录。
        # 因此在启动前先核对同名代码目录，避免用户无意间得到 code_2 等重复目录。
        conflict_mode="new"
        if self.material_auto_sort.isChecked():
            conflict_mode=self.confirm_material_output_conflicts([name],"AI 匹配前检查")
            if not conflict_mode:return False
        config=dict(self.settings.get("material_organizer_ai",{}));mode=str(config.get("mode","clip") or "clip").strip().casefold()
        if mode not in {"clip","api"}:
            LOGGER.warning("未知的素材 AI 匹配模式 %r，已回退到本地 CLIP",mode)
            mode="clip";config["mode"]="clip";self.settings["material_organizer_ai"]=config;save_app_settings(self.settings)
        api_keys=[str(value).strip() for value in config.get("api_keys",[]) if str(value).strip()] if isinstance(config.get("api_keys",[]),list) else []
        if not api_keys and str(config.get("api_key","")).strip():api_keys=[str(config.get("api_key","")).strip()]
        if mode=="api" and (not str(config.get("api_base","")).strip() or not api_keys):QMessageBox.warning(self,"请先配置 AI","请先在“AI 配置”中填写远程视觉 API 的接口地址、至少一个 API Key 与模型。 ");return False
        if mode=="clip" and not self.check_local_ai_runtime():return False
        self.material_pipeline_progress.setVisible(True);self.material_pipeline_progress.setValue(0);self.material_pipeline_status.setText(f"正在启动 AI 图文匹配：{name}（待补图 {len(scripts)} 条，已保留 {len(preserved_paths)} 条，模式：{'本地 CLIP' if mode=='clip' else '远程视觉 API'}）");self.runtime_log_handler.append(f"素材整理｜开始 AI 图文匹配：{name}，待补图 {len(scripts)} 条，保留已有图片路径 {len(preserved_paths)} 条，模式 {mode}");self._material_match_error="";self._material_match_count=0;self._material_match_unmatched=[]
        try:
            thread=ProjectAutoMatchThread(name,source,scripts,api_keys[0] if api_keys else "",str(config.get("api_base","")).strip(),str(config.get("model","") or "gpt-4o-mini"),engine_mode=mode,max_scan=max(int(config.get("max_scan",300) or 300),len(scripts)+len(preserved_paths)),clip_model_name=str(config.get("clip_model","") or "OFA-Sys/chinese-clip-vit-large-patch14"),clip_use_gpu=bool(config.get("clip_gpu",True)),api_interval=int(config.get("api_interval",5) or 5),max_retries=int(config.get("api_max_retries",3) or 3),api_keys=api_keys,ai_config=config,excluded_image_paths=preserved_paths)
        except Exception as error:
            LOGGER.exception("创建 AI 匹配线程失败")
            self.material_pipeline_status.setText(f"AI 匹配未启动：{error}")
            self.runtime_log_handler.append(f"素材整理｜AI 线程创建失败：{error}","ERROR")
            QMessageBox.warning(self,"AI 匹配未启动",f"无法创建 AI 匹配任务：\n{error}")
            return False
        self.material_ai_thread=thread;self._material_ai_current_project=name
        def apply_result(project,result):
            if project!=name:return
            count=0;matched_rows=set()
            for image_path,info in (result or {}).items():
                row=info.get("row",-1) if isinstance(info,dict) else info
                if not isinstance(row,int) or not 0<=row<table.rowCount():continue
                table.setItem(row,1,QTableWidgetItem(str(image_path)))
                if isinstance(info,dict):table.setItem(row,2,QTableWidgetItem(f"{info.get('score',0)}分: {info.get('reason','')}"))
                count+=1;matched_rows.add(row)
            unmatched_rows=[script["row"] for script in scripts if script["row"] not in matched_rows]
            available_images=max(0,int(getattr(thread,"available_image_count",0) or 0))
            unmatched_reason=(f"未匹配：候选图片不足（可用 {available_images} 张，待补图 {len(scripts)} 条）" if available_images<len(scripts) else "未匹配：图片读取或模型计算失败（请查看运行日志）")
            for row in unmatched_rows:
                # 文案行绝不删除；把未命中的原因直接写入评分列，用户可补图后再次匹配。
                current_path=table.item(row,1).text().strip() if table.item(row,1) else ""
                if not current_path:table.setItem(row,2,QTableWidgetItem(unmatched_reason))
            self._material_match_unmatched=unmatched_rows;self._material_match_count=count;self.save_material_organizer();self.runtime_log_handler.append(f"素材整理｜{name} 已回填 {count} 条图片路径；未匹配 {len(unmatched_rows)} 条")
            if getattr(self,"_material_batch_active",False):self._material_batch_results.append({"project":name,"status":"完成","matched":count,"message":"已回填图片路径","output":str(self.material_output_root(name) or "")})
            if count and self.material_auto_sort.isChecked():
                done=self.organize_material_project(name,False,conflict_mode);organized_dirs=entry.get("_last_organized_dirs",{});split_files=self.export_material_split_english(name,False,organized_dirs).get("files",0) if self.material_auto_split.isChecked() else 0;self.material_pipeline_status.setText(f"AI 已回填 {count} 条并整理输出 {done} 条"+(f"，英文分段 {split_files} 个" if self.material_auto_split.isChecked() else "")+f"：{name}")
            else:self.material_pipeline_status.setText(f"AI 已回填 {count} 条图片路径，未匹配 {len(unmatched_rows)} 条：{name}")
            add_history({"project":name,"operation":"AI 智能图文匹配","result":f"回填 {count} 条图片路径，未匹配 {len(unmatched_rows)} 条","file":source})
        def report_error(project,message):
            if project!=name:return
            self._material_match_error=str(message);LOGGER.warning("素材 AI 匹配：%s",message);self.runtime_log_handler.append(f"素材整理｜{name} AI 匹配失败：{message}","ERROR");self.material_pipeline_status.setText(f"AI 匹配失败：{message}")
            if getattr(self,"_material_batch_active",False):self._material_batch_results.append({"project":name,"status":"失败","matched":0,"message":str(message),"output":""})
            else:QMessageBox.warning(self,"AI 匹配失败",f"项目“{name}”匹配失败：\n{message}")
        def finish():
            if getattr(thread,"_stop",False):
                self.material_pipeline_progress.setValue(0);self.material_pipeline_status.setText(f"已中断 AI 匹配：{name}；已完成的匹配结果会保留。");self.runtime_log_handler.append(f"素材整理｜用户中断 AI 匹配：{name}","WARNING")
                self._material_ai_done=getattr(self,"_material_ai_done",0)+1
                if getattr(self,"_material_ai_cancelled",False):self._material_batch_active=False
                return
            if not self._material_match_error and self._material_match_count==0:self.material_pipeline_status.setText(f"AI 匹配完成，但没有产生匹配结果：{name}")
            self.material_pipeline_progress.setValue(100)
            self.runtime_log_handler.append(f"素材整理｜AI 匹配任务结束：{name}"+(f"，失败：{self._material_match_error}" if self._material_match_error else ""))
            self._material_ai_done=getattr(self,"_material_ai_done",0)+1
            # 下一项由 QThread.finished 的 release_thread 调度；此时线程可能仍在
            # 运行，过早启动会把排队项目误判成“正在匹配”。
        def report_runtime(message,_color):
            self.material_pipeline_status.setText(message);self.runtime_log_handler.append(f"素材整理｜{message}")
        def report_started():
            self.material_pipeline_status.setText(f"AI 匹配已启动，正在扫描图片：{name}")
            self.runtime_log_handler.append(f"素材整理｜AI 匹配线程已启动：{name}")
        def release_thread():
            # 原生 QThread.finished 仅负责对象生命周期，业务完成由 task_finished 处理。
            if getattr(self,"material_ai_thread",None) is thread:
                self.material_ai_thread=None;self._material_ai_current_project=""
            thread.deleteLater()
            # 必须等待 QThread 的 finished 真正发出、引用清空后再取下一项；否则
            # 下一项目会误判为“上一项仍在运行”而无法启动。
            if getattr(self,"_material_ai_queue",[]) and not getattr(self,"_material_ai_cancelled",False):QTimer.singleShot(0,self.start_next_material_ai_match)
        thread.progress.connect(self.material_pipeline_progress.setValue);thread.log.connect(report_runtime);thread.result.connect(apply_result);thread.error.connect(report_error);thread.started.connect(report_started);thread.task_finished.connect(finish);thread.finished.connect(release_thread)
        try:
            thread.start()
        except Exception as error:
            LOGGER.exception("启动 AI 匹配线程失败")
            self.material_ai_thread=None;self._material_ai_current_project="";self.material_pipeline_status.setText(f"AI 匹配未启动：{error}");self.runtime_log_handler.append(f"素材整理｜AI 线程启动失败：{error}","ERROR");QMessageBox.warning(self,"AI 匹配未启动",f"无法启动 AI 匹配任务：\n{error}");return False
        QTimer.singleShot(250,lambda current=thread,project=name:self._confirm_material_ai_started(current,project))
        return True

    def _confirm_material_ai_started(self,thread,name):
        """短延迟确认线程没有在启动阶段异常退出，避免用户只看到一次无响应点击。"""
        if getattr(self,"material_ai_thread",None) is not thread:
            return
        if thread.isRunning():
            return
        if not getattr(self,"_material_match_error",""):
            message=f"AI 匹配线程未能保持运行：{name}。请查看运行状态或系统日志。"
            LOGGER.warning(message);self.runtime_log_handler.append("素材整理｜"+message,"ERROR");self.material_pipeline_status.setText(message)

    def material_ai_finished(self,name,matched_count=0,success=True,error_message=""):
        self.save_material_organizer()
        if not success:
            self.material_pipeline_status.setText(f"AI 匹配失败：{name}，成功回填 {matched_count} 条。请检查 AI 配置或日志。")
            add_history({"project":name,"operation":"AI 智能图文匹配","result":f"失败，已回填 {matched_count} 条：{error_message}","file":""})
            QMessageBox.warning(self,"AI 匹配失败",f"项目“{name}”仅回填 {matched_count} 条，未执行自动整理。\n\n原因：{error_message or '未知错误'}")
        else:
            self.material_pipeline_progress.setValue(100);add_history({"project":name,"operation":"AI 智能图文匹配","result":f"已回填 {matched_count} 条图片路径","file":""})
            if self.material_auto_sort.isChecked():
                output=self.material_output_root(name)
                if output:
                    done=self.organize_material_project(name,False)
                    split_files=self.export_material_split_english(name,False,self.material_projects.get(name,{}).get("_last_organized_dirs",{})).get("files",0) if self.material_auto_split.isChecked() else 0
                    self.material_pipeline_status.setText(f"AI 匹配并整理完成：{name}；回填 {matched_count} 条，已整理 {done} 条"+(f"，英文分段 {split_files} 个。" if self.material_auto_split.isChecked() else "。"))
                else:
                    self.material_pipeline_status.setText(f"AI 已回填 {matched_count} 条，但未整理：请填写全局或项目输出目录。")
                    QMessageBox.warning(self,"尚未整理输出","AI 图片匹配已完成，但未填写输出目录，软件不会写入文件。\n请填写“全局统一存放位置”或当前项目的“整理后存放位置”，再点击“仅整理当前项目”。")
            else:self.material_pipeline_status.setText(f"AI 匹配完成：{name}；已回填 {matched_count} 条图片路径（未开启自动整理）。")
        # 下一项目统一在 QThread.finished 后调度，避免与尚未释放的线程抢占。

    def start_all_material_ai_match(self):
        """按当前项目顺序依次执行每个项目的 ``AI 智能图文匹配`` 完整流程。

        批量入口不能先按图片数量过滤项目；那会让用户点击“一键批量”后，部分
        项目根本没有走到各自按钮的目录、文案、AI 配置与整理前置检查。这里仅
        负责排队，真正的启动始终复用 start_material_ai_match(name)。
        """
        pending=list(self.material_projects)
        if not pending:QMessageBox.warning(self,"没有可匹配项目","请先建立至少一个素材项目。 ");return
        self._material_ai_cancelled=False;self._material_batch_active=True;self._material_batch_results=[];self._material_ai_total=len(pending);self._material_ai_done=0;self._material_ai_queue=pending;self.start_next_material_ai_match()
    def stop_all_material_ai_match(self):
        self.stop_material_ai_match(True)
    def stop_material_ai_match(self,batch=False):
        # 项目内按钮只停止当前任务，保留用户随后手动排入的项目；只有顶部
        # “停止批量”才取消整个队列。
        remaining=len(getattr(self,"_material_ai_queue",[]))
        if batch:self._material_ai_cancelled=True;self._material_ai_queue=[]
        else:self._material_ai_cancelled=False;remaining=0
        thread=getattr(self,"material_ai_thread",None)
        if not thread or not thread.isRunning():
            if not batch:QMessageBox.information(self,"没有正在执行的匹配","当前没有正在运行的 AI 图片匹配任务。")
            return
        thread.stop();label="批量 AI 匹配" if batch or remaining else "当前 AI 匹配"
        self.material_pipeline_status.setText(f"已请求停止{label}；正在取消后台处理，已完成的结果会保留。"+(f" 已取消排队项目 {remaining} 个。" if remaining else ""));self.runtime_log_handler.append(f"素材整理｜用户请求停止{label}","WARNING")
    def start_next_material_ai_match(self):
        if getattr(self,"_material_ai_cancelled",False):
            self.material_pipeline_status.setText("批量 AI 匹配已停止");self._material_batch_active=False;return
        while getattr(self,"_material_ai_queue",[]):
            name=self._material_ai_queue.pop(0)
            if self.start_material_ai_match(name):return
            # 与手动点击同一按钮时相同：目录、文案或 AI 配置不满足条件便不会启动。
            # 批量运行仍要把该项目记入结果和总进度，避免它被过滤后无声消失。
            self._material_ai_done=getattr(self,"_material_ai_done",0)+1
            if getattr(self,"_material_batch_active",False):self._material_batch_results.append({"project":name,"status":"跳过","matched":0,"message":"未通过单项目 AI 匹配的前置检查","output":""})
        done=getattr(self,'_material_ai_done',0);total=getattr(self,'_material_ai_total',0);self.material_pipeline_status.setText(f"批量 AI 匹配已完成：{done}/{total} 个项目")
        if getattr(self,"_material_batch_active",False) and total:
            self.settings["material_organizer_last_batch_results"]=list(getattr(self,"_material_batch_results",[]));save_app_settings(self.settings)
            self.show_material_batch_results();QMessageBox.information(self,"批量 AI 匹配完成",f"已完成 {done}/{total} 个项目的 AI 图文匹配。\n详细结果已在“查看批量结果”中保留。")
        self._material_batch_active=False

    def show_material_batch_results(self):
        records=list(getattr(self,"_material_batch_results",[]) or self.settings.get("material_organizer_last_batch_results",[]))
        if not records:QMessageBox.information(self,"批量任务结果","当前还没有批量 AI 匹配记录。 ");return
        dialog,layout=self.themed_dialog("批量 AI 匹配结果",1120,620);summary=QLabel(f"本次共 {len(records)} 个项目：完成 {sum(1 for item in records if item['status']=='完成')} 个，失败 {sum(1 for item in records if item['status']=='失败')} 个，跳过 {sum(1 for item in records if item['status']=='跳过')} 个。");layout.addWidget(summary)
        table=QTableWidget(len(records),5);table.setHorizontalHeaderLabels(("项目","状态","回填数量","说明","输出目录"));table.setEditTriggers(QAbstractItemView.NoEditTriggers);table.setSelectionBehavior(QAbstractItemView.SelectRows);table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        for row,item in enumerate(records):
            for column,value in enumerate((item["project"],item["status"],str(item["matched"]),item["message"],item["output"])):table.setItem(row,column,QTableWidgetItem(value))
            color="#DDF4E5" if item["status"]=="完成" else ("#FFF1CC" if item["status"]=="跳过" else "#F9D8DD")
            for column in range(5):table.item(row,column).setBackground(QColor(color))
        for column,width in enumerate((180,100,100,300,400)):table.setColumnWidth(column,width)
        layout.addWidget(table,1);buttons=QHBoxLayout();buttons.addStretch();buttons.addWidget(self.btn("复制选中行",lambda:self.copy_generic_table_cells(table)));buttons.addWidget(self.btn("关闭",dialog.accept));layout.addLayout(buttons);dialog.exec()

    def material_output_root(self,name):
        entry=self.material_projects.get(name,{})
        template=entry.get("output").text().strip() if entry.get("output") else ""
        template=template or (self.material_global_output.text().strip() if hasattr(self,"material_global_output") else "")
        # material_render_path 会先把 {date}、{yyyy-MM-dd}、{yyyyMMdd}、{project}
        # 等变量展开为当天/项目的真实路径；后续扫描只使用这个真实目录。
        return self.material_render_path(template,name)

    def material_output_template(self,name):
        """返回项目实际使用的原始模板，供预检清单展示，不参与文件扫描。"""
        entry=self.material_projects.get(name,{})
        project_template=entry.get("output").text().strip() if entry.get("output") else ""
        if project_template:return project_template
        return self.material_global_output.text().strip() if hasattr(self,"material_global_output") else ""

    def material_project_output_directory(self,name):
        """得到项目的真实整理目录：先解析变量，再追加项目名。"""
        root=self.material_output_root(name)
        return root/clean_long_filename(name) if root else None

    def material_output_conflict_records(self,names):
        """扫描项目最终整理目录中与表格“代码”同名的文件夹。

        路径模板仅用于展示；扫描始终使用 material_output_root() 的已解析结果，
        例如 D:\\FY\\Flow\\{yyyy-MM-dd} + 小明 会扫描
        D:\\FY\\Flow\\2026-08-30\\小明，而不是把花括号当作目录名。
        """
        records=[]
        for name in names:
            target=self.material_project_output_directory(name)
            template=self.material_output_template(name)
            codes=[];seen=set()
            for values in self.material_rows(name):
                code=clean_long_filename(values[0],120) if values and values[0].strip() else ""
                if code and code.casefold() not in seen:codes.append(code);seen.add(code.casefold())
            matches=[]
            if target and target.is_dir():
                for code in codes:
                    candidate=target/code
                    if candidate.is_dir():matches.append((code,candidate))
            if not target:status="未设置整理后存放位置"
            elif not codes:status="表格没有有效代码，无需比对"
            elif not target.is_dir():status="目标项目目录尚未创建"
            elif matches:status=f"发现 {len(matches)} 个同名代码文件夹"
            else:status="未发现同名代码文件夹"
            records.append({"project":name,"template":template,"target":target,"codes":codes,"matches":matches,"status":status})
        return records

    def confirm_material_output_conflicts(self,names,title="整理前检查"):
        """显示整理目录预检并返回 new / overwrite；取消时返回 None。"""
        records=self.material_output_conflict_records(names)
        conflicts=[record for record in records if record["matches"]]
        show_all=len(names)>1
        if not conflicts and not show_all:return "new"
        dialog,layout=self.themed_dialog(title,1180,650)
        heading=QLabel("已在写入前扫描各项目的最终整理目录。不会创建、移动或修改任何文件。");heading.setWordWrap(True);layout.addWidget(heading)
        if conflicts:
            note=QLabel("检测到同名代码文件夹。请选择处理模式：新增模式会保留旧目录，并输出 code_2 等新目录；完全覆盖模式会删除列出的同名代码目录及其中全部内容后重建，无法通过“撤销上次整理”恢复旧内容。")
        else:
            note=QLabel("所有项目均已扫描，未发现与当前表格代码同名的整理文件夹，可以安全继续。")
        note.setWordWrap(True);layout.addWidget(note)
        table=QTableWidget(len(records),5);table.setHorizontalHeaderLabels(("项目","配置的整理路径模板","本次实际扫描目录","同名代码文件夹","检查结果"));table.setEditTriggers(QAbstractItemView.NoEditTriggers);table.setSelectionBehavior(QAbstractItemView.SelectRows);table.setWordWrap(False);table.setToolTip("双击任意项目行可打开该项目的最终整理目录。")
        for row,record in enumerate(records):
            values=(record["project"],record["template"] or "（未设置）",str(record["target"] or "（未设置）"),"、".join(code for code,_path in record["matches"]) or "无",record["status"])
            color="#F9D8DD" if record["matches"] else "#DDF4E5" if record["target"] and record["target"].is_dir() else "#FFF2C2"
            for column,value in enumerate(values):
                item=QTableWidgetItem(str(value));item.setToolTip(str(value));item.setBackground(QColor(color));table.setItem(row,column,item)
        for column,width in enumerate((150,260,350,220,220)):table.setColumnWidth(column,width)
        table.cellDoubleClicked.connect(lambda row,_column:self.open_material_preflight_target(records[row]))
        layout.addWidget(table,1)
        buttons=QHBoxLayout();buttons.addWidget(self.btn("取消",dialog.reject));buttons.addStretch()
        if conflicts:
            buttons.addWidget(self.btn("新增模式（保留旧目录）",lambda:dialog.done(1),"primary"))
            buttons.addWidget(self.btn("完全覆盖同名目录",lambda:dialog.done(2),"danger"))
        else:
            buttons.addWidget(self.btn("继续 AI 匹配" if "AI" in title else "继续整理",lambda:dialog.done(1),"primary"))
        layout.addLayout(buttons)
        result=dialog.exec()
        if result==2:
            count=sum(len(record["matches"]) for record in conflicts)
            warning=f"将完全删除并重建 {count} 个同名代码目录。目录中已有图片、TXT 和其他文件都会被删除，且旧内容无法撤销恢复。\n\n是否确认使用完全覆盖模式？"
            return "overwrite" if self.themed_message("question","确认完全覆盖",warning)==QMessageBox.Yes else None
        return "new" if result==1 else None

    def open_material_preflight_target(self,record):
        """供整理前检查表格双击使用：打开已解析后的项目最终目录。"""
        directory=record.get("target") if isinstance(record,dict) else None
        if not directory or not Path(directory).is_dir():
            QMessageBox.information(self,"目录尚未创建",f"该项目本次实际扫描目录尚未创建：\n{directory or '未设置'}\n\n可先取消并检查路径，或继续整理后再打开。")
            return
        try:open_system_path(Path(directory))
        except OSError as error:
            LOGGER.exception("无法打开整理前检查目录：%s",directory);QMessageBox.warning(self,"无法打开目录",str(error))

    def material_split_text(self,text,limit):
        text=re.sub(r"\s+"," ",str(text or "").strip())
        if not text:return []
        parts=[];current=""
        for sentence in re.split(r"(?<=[.!?。！？])\s*",text):
            if not sentence:continue
            if current and len(current)+1+len(sentence)>limit:parts.append(current);current=sentence
            else:current=(current+" "+sentence).strip()
        if current:parts.append(current)
        return parts or [text]

    def export_material_split_english(self,name,show_message=True,organized_dirs=None):
        """按 main.py 的原始规则写入：输出根目录 / 项目 / 代码 / 序号.txt。"""
        rows=self.material_rows(name);root=self.material_output_root(name)
        if not rows:
            if show_message:QMessageBox.warning(self,"没有可导出数据",f"项目“{name}”没有素材数据。 ")
            return {"files":0,"groups":0,"output_dir":""}
        if not root:
            if show_message:QMessageBox.warning(self,"请选择输出目录","请填写全局统一存放位置，或当前项目的整理后存放位置。 ")
            return {"files":0,"groups":0,"output_dir":""}
        limit=self.material_split_limit_value(self.material_projects[name]);base=root/clean_long_filename(name);files=groups=0
        try:
            for index,(code,_image,_score,_cn,en,_note) in enumerate(rows,1):
                if not en.strip():continue
                safe_code=clean_long_filename(code,120) if code else f"item_{index}"
                group=(organized_dirs or {}).get(index) or base/safe_code;group=Path(group);group.mkdir(parents=True,exist_ok=True);groups+=1
                # 0 是“保持整条英文文案”的明确模式：不进入切分算法，但仍使用 1.txt
                # 的数字命名规则，以便后续图片/视频任务继续一一对应。
                # 分段字数是英文“词数”目标，不是字符硬上限：整句优先、允许小幅
                # 超出，并自动消除两三个词的短尾段，避免视频模型无法生成语音。
                segments=[en.strip()] if limit==0 else segment_english_dialogue(en,limit) or [en.strip()]
                for segment_index,segment in enumerate(segments,1):(group/f"{segment_index}.txt").write_text(segment,encoding="utf-8");files+=1
            add_history({"project":name,"operation":"导出当前项目分段英文","result":f"导出 {files} 个分段文件","file":str(base)})
            if show_message:QMessageBox.information(self,"导出完成",f"项目“{name}”已导出 {files} 个英文分段文件。\n{base}")
        except OSError as error:QMessageBox.warning(self,"导出失败",str(error))
        return {"files":files,"groups":groups,"output_dir":str(base)}

    def export_all_material_split_english(self):
        total_files=total_groups=0
        for name in list(self.material_projects):
            result=self.export_material_split_english(name,False);total_files+=result["files"];total_groups+=result["groups"]
        QMessageBox.information(self,"批量导出完成",f"已完成 {len(self.material_projects)} 个项目的分段英文导出：{total_groups} 组，{total_files} 个文件。")

    def export_material_segment_images(self,name,show_message=True,conflict_mode="overwrite"):
        """从已整理项目内按“数字 TXT + 同目录图片”生成分段图片副本。"""
        root=self.material_output_root(name)
        if not root:
            if show_message:QMessageBox.warning(self,"请选择输出目录","请填写全局统一存放位置，或当前项目的整理后存放位置。 ")
            return {"folders":0,"images":0,"missing":0,"output_dir":""}
        safe_name=clean_long_filename(name);project_dir=(root/safe_name).absolute()
        base=project_dir/f"{safe_name}-图片"
        # 路径模板含日期时，次日再次导出应找回已有的整理目录，而不是误用当天空目录。
        if not project_dir.is_dir():
            entry=self.material_projects.get(name,{})
            template=entry.get("output").text().strip() if entry.get("output") else ""
            template=template or (self.material_global_output.text().strip() if hasattr(self,"material_global_output") else "")
            if "{" in template:
                prefix=template.split("{",1)[0].rstrip("\\\\/")
                search_root=self.material_render_path(prefix)
                candidates=[]
                if search_root and search_root.is_dir():
                    for current,dirs,_files in os.walk(search_root):
                        dirs[:]=[item for item in dirs if not item.endswith("-图片")]
                        for folder in dirs:
                            if folder != safe_name:continue
                            candidate=Path(current)/folder
                            if any(Path(filename).suffix.lower()==".txt" and Path(filename).stem.isdigit() for _cur,_sub,files in os.walk(candidate) for filename in files):candidates.append(candidate)
                if candidates:
                    project_dir=max(candidates,key=lambda item:item.stat().st_mtime);base=project_dir/f"{safe_name}-图片"
                    LOGGER.info("项目 %s 已使用已有整理目录：%s",name,project_dir)
        if not project_dir.is_dir():
            message=f"未找到项目“{name}”的整理结果目录：\n{project_dir}"
            if show_message:QMessageBox.warning(self,"提示",message)
            return {"folders":0,"images":0,"missing":0,"output_dir":str(base)}
        # 新增模式不触碰之前的图片副本目录；完全覆盖模式则以最新整理结果重建它。
        if conflict_mode=="new" and base.exists():base=self.material_unique_path(project_dir,base.name,"",180,240)
        image_exts={".jpg",".jpeg",".jfif",".png",".webp",".bmp",".gif",".tif",".tiff"};folders=images=missing=errors=0
        try:
            if conflict_mode=="overwrite" and base.is_dir() and not base.is_symlink():shutil.rmtree(base)
            base.mkdir(parents=True,exist_ok=True)
            for current,_dirs,filenames in os.walk(project_dir):
                numeric=sorted((Path(filename).stem for filename in filenames if Path(filename).suffix.lower()==".txt" and Path(filename).stem.isdigit()),key=int)
                if not numeric:continue
                image_files=sorted((filename for filename in filenames if Path(filename).suffix.lower() in image_exts),key=str.casefold)
                if not image_files:missing+=len(numeric);continue
                folders+=1;current_path=Path(current);prefix=clean_long_filename(current_path.name,120)
                selected=next((filename for filename in image_files if Path(filename).stem.casefold()==current_path.name.casefold()),image_files[0])
                source=current_path/selected
                for number in numeric:
                    try:shutil.copy2(source,base/f"{prefix}-{number}{source.suffix}");images+=1
                    except OSError as error:errors+=1;LOGGER.exception("图片副本导出失败：%s",error)
            add_history({"project":name,"operation":"导出当前项目分段图片","result":f"复制 {images} 张图片","file":str(base)})
            if show_message:
                message=f"已导出 {images} 张图片，处理 {folders} 个素材文件夹；缺少图片 {missing} 条。\n{base}"
                if errors:message+=f"\n另有 {errors} 张图片复制失败，请查看系统日志。"
                QMessageBox.information(self,"导出完成",message)
        except OSError as error:QMessageBox.warning(self,"导出失败",str(error))
        return {"folders":folders,"images":images,"missing":missing,"output_dir":str(base)}

    def export_all_material_segment_images(self):
        images=missing=folders=0
        for name in list(self.material_projects):
            result=self.export_material_segment_images(name,False);images+=result["images"];missing+=result["missing"];folders+=result.get("folders",0)
        QMessageBox.information(self,"批量图片导出完成",f"已导出 {images} 张分段图片，处理 {folders} 个素材文件夹；缺少图片 {missing} 条。")

    def organize_all_material_projects(self):
        if not self.material_projects:QMessageBox.information(self,"没有项目","请先建立素材项目。 ");return
        # 批量整理前必须完整展示每个项目的最终目录扫描结果，让用户决定继续或取消。
        # 这里传入所有项目，confirm_material_output_conflicts 会在无冲突时也保留完整清单。
        names=list(self.material_projects)
        conflict_mode=self.confirm_material_output_conflicts(names,"一键整理前检查")
        if not conflict_mode:return
        history_before=len(getattr(self,"_material_undo_history",[]));total=split_files=images=missing=0;processed=0
        for name in names:
            count=self.organize_material_project(name,False,conflict_mode);total+=count;processed+=1
            if self.material_auto_split.isChecked():split_files+=self.export_material_split_english(name,False,self.material_projects.get(name,{}).get("_last_organized_dirs",{})).get("files",0)
            result=self.export_material_segment_images(name,False,conflict_mode=conflict_mode);images+=result.get("images",0);missing+=result.get("missing",0)
        outputs=self.write_material_batch_summary(conflict_mode)
        # “一键整理”对用户而言是一项操作：撤销时必须一次回退整批产物，不能逐项目残留。
        transactions=getattr(self,"_material_undo_history",[]);created=transactions[history_before:]
        if created:
            combined=[entry for transaction in created for entry in transaction]
            self._material_undo_history=transactions[:history_before]+[combined]
        message=f"已处理 {processed} 个项目，共整理 {total} 条素材。\n已导出分段图片 {images} 张"+(f"（缺少 {missing} 张）" if missing else "")
        if self.material_auto_split.isChecked():message+=f"\n已自动导出英文分段 {split_files} 个文件。"
        if outputs:message+=f"\n\n全部项目汇总：\n{outputs[0]}\n{outputs[1]}"
        QMessageBox.information(self,"批量整理完成",message)

    def import_workspace_rows_to_material(self):
        if not self.rows:QMessageBox.warning(self,"没有可导入数据","请先在“项目工作台”加载目录数据，生成预览后再导入。 ");return
        default=self.name.text().strip() or "工作台导入";name,ok=QInputDialog.getText(self,"导入工作台预览","导入到素材项目：",text=default)
        if not ok or not str(name).strip():return
        name=str(name).strip()
        if name not in self.material_projects:self.create_material_project(name,{"source":self.input.text().strip()})
        table=self.material_projects[name]["table"];rows=[]
        for item in self.rows:
            txt=str(item.get("txt_name","")).strip();code=Path(txt).stem if txt else "";rows.append([code,str(item.get("image_path","")).strip(),"",str(item.get("dialogue","")).strip(),"",str(item.get("status","")).strip()])
        self._material_loading=True;table.setRowCount(max(10,len(rows)))
        for row_index,values in enumerate(rows):
            for column,value in enumerate(values):table.setItem(row_index,column,QTableWidgetItem(value))
        self._material_loading=False;self.material_project_tabs.setCurrentWidget(self.material_projects[name]["widget"]);self.save_material_organizer();QMessageBox.information(self,"导入完成",f"已导入 {len(rows)} 条工作台预览数据到“{name}”。")

    def _material_smart_import_dialog(self, project_name="", target_table=None):
        """与旧 main.py 对齐的全功能 CSV 粘贴/识别导入器，单项目和全局共用。"""
        is_global=target_table is None
        title="全局智能 CSV 导入" if is_global else f"智能导入数据 — {project_name}"
        dialog,layout=self.themed_dialog(title,1240,780)
        hint=QLabel("可从 Excel、Google 表格直接粘贴多行多列数据。软件会自动识别项目名、代码、图片路径、中英文文案和备注列，并以颜色标记；需要时可在下方手动更改识别结果。")
        hint.setWordWrap(True);layout.addWidget(hint)
        tools=QHBoxLayout();header=QCheckBox("第一行是表头");header.setChecked(True);prefer=QCheckBox("优先识别常用列位（13/6/7/8）");prefer.setChecked(True);tools.addWidget(header);tools.addWidget(prefer)
        table=CopyableTable(30,20);table.setHorizontalHeaderLabels(tuple(f"列 {index}" for index in range(1,21)));table.setSelectionBehavior(QAbstractItemView.SelectItems);table.setSelectionMode(QAbstractItemView.ExtendedSelection);table.setEditTriggers(QAbstractItemView.DoubleClicked|QAbstractItemView.EditKeyPressed|QAbstractItemView.AnyKeyPressed);table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        def load_file():
            filename,_=QFileDialog.getOpenFileName(dialog,"选择导入文件","","Excel 工作簿 (*.xlsx);;CSV/文本文件 (*.csv *.txt *.tsv);;所有文件 (*.*)")
            if not filename:return
            source=Path(filename)
            if source.suffix.lower()==".xlsx":
                try:
                    from openpyxl import load_workbook
                    workbook=load_workbook(source,read_only=True,data_only=False);sheet=workbook.active;rows=[["" if value is None else str(value) for value in row] for row in sheet.iter_rows(values_only=True)];workbook.close()
                except Exception as error:QMessageBox.warning(dialog,"读取 Excel 失败",str(error));return
            else:
                text=None
                for encoding in ("utf-8-sig","utf-8","gb18030","gbk"):
                    try:text=source.read_text(encoding=encoding);break
                    except UnicodeError:continue
                if text is None:QMessageBox.warning(dialog,"读取失败","无法识别 CSV 文件编码。 ");return
                try:rows=list(csv.reader(text.splitlines(),delimiter="\t" if text[:2048].count("\t")>text[:2048].count(",") else ","))
                except csv.Error as error:QMessageBox.warning(dialog,"读取失败",str(error));return
            columns=max([len(row) for row in rows] or [1]);table.blockSignals(True);table.setColumnCount(max(20,columns));table.setHorizontalHeaderLabels(tuple(f"列 {index}" for index in range(1,table.columnCount()+1)));table.setRowCount(max(30,len(rows)))
            for row_index,row in enumerate(rows):
                for column,value in enumerate(row):table.setItem(row_index,column,QTableWidgetItem(value.strip()))
            table.blockSignals(False);analyze();QMessageBox.information(dialog,"已载入",f"已读取 {len(rows)} 行数据。")
        tools.addWidget(self.btn("导入 CSV 文件",load_file,"loadData"));tools.addWidget(self.btn("＋ 加行",lambda:table.insertRow(table.rowCount())));tools.addWidget(self.btn("清空表格",lambda:(table.setRowCount(30),analyze()),"danger"));tools.addStretch();layout.addLayout(tools);layout.addWidget(table,1)
        mapping=QFormLayout();combos=[];labels=("项目名列","代码列","图片路径列","中文文案列","英文文案列","备注列")
        for label in labels:
            box=DoubleClickComboBox();combos.append(box);mapping.addRow(label,box)
        layout.addLayout(mapping)
        automatic=True
        def get_text(row,column):
            item=table.item(row,column);return item.text().strip() if item else ""
        def get_text_target(target,row,column):
            item=target.item(row,column);return item.text().strip() if item else ""
        def score_columns():
            headers=[get_text(0,column).lower() for column in range(table.columnCount())]
            detected={"project":-1,"code":-1,"path":-1,"cn":-1,"en":-1,"note":-1}
            header_words={"project":("项目","project","proj"),"code":("代码","code","编号","id"),"path":("图片","image","path","路径"),"cn":("中文","chinese","cn","文案","script"),"en":("英文","english","en"),"note":("备注","remark","note","要求","说明")}
            for key,words in header_words.items():detected[key]=next((column for column,value in enumerate(headers) if any(word in value for word in words)),-1)
            for column in range(table.columnCount()):
                values=[get_text(row,column) for row in range(1 if header.isChecked() else 0,min(table.rowCount(),101)) if get_text(row,column)]
                if not values:continue
                joined=" ".join(values);sample=values[:20]
                if detected["path"]<0 and sum(1 for value in sample if ("/" in value or "\\" in value) and value.lower().endswith((".jpg",".jpeg",".png",".webp",".bmp",".gif",".tif",".tiff")))>=1:detected["path"]=column
                if detected["code"]<0:
                    score=sum(bool(re.search(r"[A-Za-z]",value))*5+bool(re.search(r"\d",value))*5+(2 if "-" in value or "_" in value else 0) for value in sample)
                    if score>=max(12,len(sample)*7):detected["code"]=column
                if detected["cn"]<0 and any("\u4e00"<=char<="\u9fff" for char in joined):detected["cn"]=column
                elif detected["en"]<0 and re.search(r"[A-Za-z]",joined):detected["en"]=column
            if prefer.isChecked():
                defaults={"code":12,"cn":5,"en":6,"note":7}
                for key,column in defaults.items():
                    if detected[key]<0 and column<table.columnCount() and any(get_text(row,column) for row in range(table.rowCount())):detected[key]=column
            return detected
        def analyze():
            nonlocal automatic
            if not automatic:return
            detected=score_columns();table.blockSignals(True)
            try:
                colors={"project":"#ede9fe","code":"#dbeafe","path":"#ffedd5","cn":"#dcfce7","en":"#fef9c3","note":"#f3f4f6"}
                for column in range(table.columnCount()):
                    color=next((colors[key] for key,value in detected.items() if value==column),"#ffffff")
                    for row in range(table.rowCount()):
                        if table.item(row,column):table.item(row,column).setBackground(QColor(color))
                for box,(key,column) in zip(combos,detected.items()):
                    box.blockSignals(True);box.clear();box.addItem("不导入",-1);[box.addItem(f"列 {index}",index-1) for index in range(1,table.columnCount()+1)];box.setCurrentIndex(max(0,box.findData(column)));box.blockSignals(False)
            finally:table.blockSignals(False)
        def manual_changed(*_):
            nonlocal automatic
            automatic=False
        for box in combos:box.currentIndexChanged.connect(manual_changed)
        table.itemChanged.connect(lambda *_:analyze());header.toggled.connect(lambda *_:analyze());prefer.toggled.connect(lambda *_:analyze());analyze()
        options=QHBoxLayout();overwrite=QCheckBox("覆盖已有内容");overwrite.setChecked(True);overwrite_empty=QCheckBox("允许空值覆盖（谨慎）");options.addWidget(overwrite);options.addWidget(overwrite_empty)
        if is_global:
            create_missing=QCheckBox("项目不存在时自动创建");create_missing.setChecked(True);options.addWidget(create_missing)
        options.addStretch();options.addWidget(self.btn("取消",dialog.reject));options.addWidget(self.btn("开始智能导入",dialog.accept,"primary"));layout.addLayout(options)
        if dialog.exec()!=QDialog.Accepted:return
        indices=[box.currentData() for box in combos];project_col,code_col,path_col,cn_col,en_col,note_col=indices
        if code_col is None or code_col<0:QMessageBox.warning(self,"无法导入","请先选择“代码列”。");return
        def normalized_code(value):return re.sub(r"[^A-Za-z0-9]+","",str(value or "").upper())
        def codes_match(left,right):
            left,right=normalized_code(left),normalized_code(right)
            return bool(left and right and (left==right or left.endswith(right) or right.endswith(left)))
        imported=0;self._material_loading=True
        try:
            for row in range(1 if header.isChecked() else 0,table.rowCount()):
                get=lambda column:get_text(row,column) if isinstance(column,int) and column>=0 else ""
                code=get(code_col)
                if not code:continue
                name=get(project_col) if is_global else project_name
                name=name or "导入项目"
                if name not in self.material_projects:
                    if not is_global or create_missing.isChecked():self.create_material_project(name)
                    else:continue
                target=self.material_projects[name]["table"] if is_global else target_table
                existing=next((index for index in range(target.rowCount()) if codes_match(get_text_target(target,index,0),code)),-1)
                empty=next((index for index in range(target.rowCount()) if not any(get_text_target(target,index,column) for column in range(6))),target.rowCount())
                target_row=existing if existing>=0 else empty
                if target_row>=target.rowCount():target.insertRow(target_row)
                has_content=any(get_text_target(target,target_row,column) for column in range(1,6))
                target.setItem(target_row,0,QTableWidgetItem(code))
                if has_content and not overwrite.isChecked():continue
                values=(get(path_col),"",get(cn_col),get(en_col),get(note_col))
                for column,value in enumerate(values,1):
                    if value or overwrite_empty.isChecked():target.setItem(target_row,column,QTableWidgetItem(value))
                imported+=1
        finally:self._material_loading=False
        self.save_material_organizer();QMessageBox.information(self,"导入完成",f"已导入或更新 {imported} 条素材数据。")

    def smart_import_material_project(self,project_name,table):
        self._material_smart_import_dialog(project_name,table)

    def global_material_csv_import(self):
        self._material_smart_import_dialog()

    def load_material_csv_file(self,table):
        filename,_=QFileDialog.getOpenFileName(self,"选择 CSV 文件","","CSV 文件 (*.csv *.txt);;所有文件 (*.*)")
        if not filename:return
        content=None
        for encoding in ("utf-8-sig","utf-8","gb18030","gbk"):
            try:content=Path(filename).read_text(encoding=encoding);break
            except UnicodeError:continue
        if content is None:QMessageBox.warning(self,"读取失败","无法识别 CSV 文件编码。 ");return
        rows=list(csv.reader(content.splitlines()));columns=max([len(row) for row in rows] or [8]);table.setColumnCount(columns);table.setHorizontalHeaderLabels(tuple(f"列 {index}" for index in range(1,columns+1)));table.setRowCount(len(rows))
        for row_index,row in enumerate(rows):
            for column,value in enumerate(row):table.setItem(row_index,column,QTableWidgetItem(value))
        headers=[value.strip().lower() for value in (rows[0] if rows else [])]
        keywords=(("项目","project"),("代码","code","编号"),("图片","image","path","路径"),("中文","cn","chinese"),("英文","en","english"),("备注","remark","note","要求"))
        for box,words in zip(getattr(table,"material_import_combos",[]),keywords):
            column=next((index for index,value in enumerate(headers) if any(word in value for word in words)),-1)
            if column>=0:box.setCurrentIndex(box.findData(column))

    def material_all_rows(self):
        return [[name,*row] for name in self.material_projects for row in self.material_rows(name)]

    def locate_material_image(self,project,code,raw_path=""):
        """图片路径失效时，在项目来源与整理输出中按原文件名/代码找回真实文件。"""
        raw=Path(str(raw_path or ""));names=[raw.name] if raw.name else []
        if code:
            names.extend(f"{code}{suffix}" for suffix in (".jpg",".jpeg",".png",".webp",".bmp",".gif",".tif",".tiff"))
        entry=self.material_projects.get(project,{})
        roots=[]
        if entry.get("source") and entry["source"].text().strip():roots.append(Path(entry["source"].text().strip()))
        output=self.material_output_root(project)
        if output:roots.append(output/clean_long_filename(project))
        for root in roots:
            if not root.is_dir():continue
            for candidate_name in names:
                try:
                    found=next((item for item in root.rglob(candidate_name) if item.is_file()),None)
                    if found:return str(found)
                except OSError:continue
        return ""

    def show_material_summary(self):
        records=[]
        for project,entry in self.material_projects.items():
            source_table=entry["table"]
            for source_row in range(source_table.rowCount()):
                values=[source_table.item(source_row,column).text().strip() if source_table.item(source_row,column) else "" for column in range(6)]
                if any(values):records.append((project,source_row,values))
        if not records:QMessageBox.information(self,"图文审核台","当前没有素材项目数据。请先建立项目并录入素材。 ");return
        dialog,layout=self.themed_dialog("图文审核台",1500,900);dialog.setWindowFlags(dialog.windowFlags()|Qt.WindowMinMaxButtonsHint|Qt.WindowCloseButtonHint)
        states=dict(self.settings.get("material_organizer_review_states",{}));notes=dict(self.settings.get("material_organizer_review_notes",{}));suggestions=dict(self.settings.get("material_organizer_review_suggestions",{}));title=QLabel(f"图文审核台：共 {len(records)} 条素材");title.setObjectName("title");layout.addWidget(title)
        filters=QHBoxLayout();summary=QLabel();filters.addWidget(summary,1);filters.addWidget(QLabel("搜索"));search=QLineEdit();search.setPlaceholderText("项目、代码、文案、备注…");search.setClearButtonEnabled(True);filters.addWidget(search);filters.addWidget(QLabel("状态"));state_filter=DoubleClickComboBox();state_filter.addItems(("全部状态","待审核","已通过","文案不贴切","视觉问题","人工复核","需复核","图片缺失"));filters.addWidget(state_filter);filters.addWidget(QLabel("图片大小"));zoom=QSlider(Qt.Horizontal);zoom.setRange(70,280);zoom.setValue(112);zoom.setFixedWidth(130);filters.addWidget(zoom);layout.addLayout(filters)
        tools=QHBoxLayout();tools.addWidget(self.btn("关键词扫描",lambda:self.material_keyword_scan(review_table,states,notes),"warning"));tools.addWidget(self.btn("编辑词库",self.edit_material_review_keywords));tools.addWidget(self.btn("视觉规则",lambda:self.edit_material_review_text("visual_rules","视觉规则","每行一条视觉审核要求，例如：人物表情与文案情绪一致。")));tools.addWidget(self.btn("审核预设管理",self.manage_material_review_presets,"warning"));tools.addWidget(self.btn("审核 AI 配置",self.material_review_ai_config,"warning"));tools.addWidget(self.btn("智能初检",lambda:self.material_review_precheck(review_table,states,notes),"loadData"));tools.addWidget(self.btn("AI 图文审核",lambda:self.start_material_ai_review(review_table,states,notes,dialog),"primary"));tools.addStretch();layout.addLayout(tools)
        # 审核台改为复用完整电子表格引擎；审核专用的列顺序、宽度和图片格高度保持原样。
        review_table=MaterialSpreadsheet(0,11);review_table.minimum_row_count=0;review_table.setHorizontalHeaderLabels(("项目名","代码","图片预览","图片路径","评分","中文文案","英文文案","备注","审核状态","审核说明","修改建议"));review_table.setSelectionBehavior(QAbstractItemView.SelectItems);review_table.setSelectionMode(QAbstractItemView.ExtendedSelection);review_table.setEditTriggers(QAbstractItemView.DoubleClicked|QAbstractItemView.EditKeyPressed|QAbstractItemView.AnyKeyPressed);review_table.setWordWrap(True);review_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        for column,width in enumerate((150,120,140,330,110,280,280,220,110,250,250)):review_table.setColumnWidth(column,width)
        layout.addWidget(review_table,1)
        def record_key(project,row,values):return f"{project}\t{row}\t{values[0] if values else ''}"
        def fill_table(*_):
            keyword=search.text().strip().casefold();wanted=state_filter.currentText();review_table.setRowCount(0);counts={"已通过":0,"需复核":0,"图片缺失":0,"待审核":0}
            for project,source_row,values in records:
                key=record_key(project,source_row,values);image=values[1] if len(values)>1 else ""
                if image and not Path(image).is_file():image=self.locate_material_image(project,values[0],image) or image
                status=str(states.get(key) or ("图片缺失" if not image or not Path(image).is_file() else "待审核"));counts[status]=counts.get(status,0)+1
                searchable=" ".join([project,*values,status,notes.get(key,""),suggestions.get(key,"")]).casefold()
                if keyword and keyword not in searchable:continue
                if wanted!="全部状态" and status!=wanted:continue
                row=review_table.rowCount();review_table.insertRow(row);review_table.setRowHeight(row,zoom.value()+18)
                source=(project,source_row,key)
                for col,text in ((0,project),(1,values[0]),(3,image),(4,values[2]),(5,values[3]),(6,values[4]),(7,values[5]),(8,status),(9,notes.get(key,"")),(10,suggestions.get(key,""))):
                    item=QTableWidgetItem(str(text));item.setData(Qt.UserRole,source);review_table.setItem(row,col,item)
                thumb=ReviewImageLabel("无图片\n（可拖入替换）");thumb.image_path=image;thumb.setAlignment(Qt.AlignCenter);thumb.setToolTip((image or "无图片")+"\n双击：在软件内放大")
                if image and Path(image).is_file():
                    pix=QPixmap(image)
                    if not pix.isNull():thumb.setPixmap(pix.scaled(zoom.value(),zoom.value(),Qt.KeepAspectRatio,Qt.SmoothTransformation))
                path_item=review_table.item(row,3)
                def apply_dropped_image(value,item=path_item,label=thumb):
                    if item:item.setText(value)
                    pixmap=QPixmap(value)
                    if not pixmap.isNull():label.setText("");label.image_path=value;label.setPixmap(pixmap.scaled(zoom.value(),zoom.value(),Qt.KeepAspectRatio,Qt.SmoothTransformation));label.setToolTip(value+"\n双击：在软件内放大")
                thumb.image_dropped.connect(apply_dropped_image)
                review_table.setCellWidget(row,2,thumb)
                color={"已通过":"#DDF4E5","需复核":"#FFF2C2","图片缺失":"#F9D8DD","待审核":"#E8F0FF"}.get(status,"#FFFFFF")
                for col in range(review_table.columnCount()):
                    item=review_table.item(row,col)
                    if item:item.setBackground(QColor(color))
            summary.setText(f"总计 {len(records)} 条 ｜ 已通过 {counts.get('已通过',0)} ｜ 需复核 {counts.get('需复核',0)} ｜ 图片缺失 {counts.get('图片缺失',0)} ｜ 待审核 {counts.get('待审核',0)}")
        def save_changes():
            for row in range(review_table.rowCount()):
                anchor=review_table.item(row,0)
                if not anchor:continue
                project,source_row,key=anchor.data(Qt.UserRole);target=self.material_projects.get(project,{}).get("table")
                if not target or source_row>=target.rowCount():continue
                for audit_column,target_column in ((1,0),(3,1),(4,2),(5,3),(6,4),(7,5)):
                    item=review_table.item(row,audit_column);target.setItem(source_row,target_column,QTableWidgetItem(item.text() if item else ""))
                status_item=review_table.item(row,8);note_item=review_table.item(row,9);suggestion_item=review_table.item(row,10);states[key]=status_item.text().strip() if status_item else "待审核";notes[key]=note_item.text().strip() if note_item else "";suggestions[key]=suggestion_item.text().strip() if suggestion_item else ""
            self.settings["material_organizer_review_states"]=states;self.settings["material_organizer_review_notes"]=notes;self.settings["material_organizer_review_suggestions"]=suggestions;self.save_material_organizer();save_app_settings(self.settings);add_history({"project":"素材整理与汇总","operation":"保存图文审核","result":f"保存 {review_table.rowCount()} 条审核数据","file":""});QMessageBox.information(dialog,"审核已保存","审核状态、说明、建议及表格修改已同步回项目并保存。 ");fill_table()
        search.textChanged.connect(fill_table);state_filter.currentTextChanged.connect(fill_table);zoom.valueChanged.connect(fill_table);fill_table()
        def replace_selected_image():
            rows=sorted({index.row() for index in review_table.selectedIndexes()})
            if not rows:QMessageBox.information(dialog,"未选择数据","请先选择一条或多条审核记录。 ");return
            filename,_=QFileDialog.getOpenFileName(dialog,"选择替换图片","","图片文件 (*.jpg *.jpeg *.jfif *.png *.webp *.bmp *.gif *.tif *.tiff);;所有文件 (*.*)")
            if not filename:return
            for row in rows:
                item=review_table.item(row,3)
                if item:item.setText(filename)
            QMessageBox.information(dialog,"已替换图片路径",f"已为 {len(rows)} 条选中记录填入图片路径；点击“保存修改”后同步到项目。")
        buttons=QHBoxLayout();buttons.addWidget(self.btn("选择图片替换",replace_selected_image,"selectInput"));buttons.addWidget(self.btn("全部通过",lambda:self.material_set_review_status(review_table,states,"已通过",True),"primary"));buttons.addWidget(self.btn("选中通过",lambda:self.material_set_review_status(review_table,states,"已通过"),"primary"));buttons.addWidget(self.btn("选中复核",lambda:self.material_set_review_status(review_table,states,"人工复核"),"warning"));buttons.addWidget(self.btn("复制选中单元格",lambda:self.copy_generic_table_cells(review_table)));buttons.addStretch();buttons.addWidget(self.btn("保存修改",save_changes,"openExport"));buttons.addWidget(self.btn("关闭",dialog.accept));layout.addLayout(buttons);dialog.exec()

    def material_set_review_status(self,table,states,status,all_rows=False):
        rows=range(table.rowCount()) if all_rows else sorted({index.row() for index in table.selectedIndexes()})
        for row in rows:
            anchor=table.item(row,0);state_item=table.item(row,8)
            if anchor and state_item:states[anchor.data(Qt.UserRole)[2]]=status;state_item.setText(status)

    def edit_material_review_keywords(self):
        dialog,layout=self.themed_dialog("审核关键词词库",680,520);layout.addWidget(QLabel("每行一个关键词。关键词扫描会在中文文案、英文文案与备注中查找，并标记为“需复核”。"));edit=QTextEdit("\n".join(self.settings.get("material_organizer_review_keywords",[])));layout.addWidget(edit,1);buttons=QHBoxLayout();buttons.addStretch();buttons.addWidget(self.btn("取消",dialog.reject));buttons.addWidget(self.btn("保存词库",dialog.accept,"primary"));layout.addLayout(buttons)
        if dialog.exec()==QDialog.Accepted:self.settings["material_organizer_review_keywords"]=[line.strip() for line in edit.toPlainText().splitlines() if line.strip()];save_app_settings(self.settings)

    def edit_material_review_text(self,kind,title,hint):
        setting_key=f"material_organizer_review_{kind}";dialog,layout=self.themed_dialog(title,720,540);label=QLabel(hint);label.setWordWrap(True);layout.addWidget(label);edit=QTextEdit(str(self.settings.get(setting_key,"")));layout.addWidget(edit,1);buttons=QHBoxLayout();buttons.addStretch();buttons.addWidget(self.btn("取消",dialog.reject));buttons.addWidget(self.btn("保存",dialog.accept,"primary"));layout.addLayout(buttons)
        if dialog.exec()==QDialog.Accepted:self.settings[setting_key]=edit.toPlainText().strip();save_app_settings(self.settings)

    def manage_material_review_presets(self):
        dialog,layout=self.themed_dialog("审核预设管理",880,610);layout.addWidget(QLabel("预设会同时保存视觉规则与审核提示词，可用于不同类型素材的快速切换。"));presets=dict(self.settings.get("material_organizer_review_presets",{}));preset_list=QListWidget();layout.addWidget(preset_list,1)
        def refresh():
            preset_list.clear()
            for name in sorted(presets):
                item=QListWidgetItem(name);item.setData(Qt.UserRole,name);preset_list.addItem(item)
        def save_current():
            name,ok=QInputDialog.getText(dialog,"保存审核预设","预设名称：")
            name=str(name).strip()
            if not ok or not name:return
            presets[name]={"rules":str(self.settings.get("material_organizer_review_visual_rules","")).strip(),"prompt":str(self.settings.get("material_organizer_review_prompt","")).strip()};self.settings["material_organizer_review_presets"]=presets;save_app_settings(self.settings);refresh()
        def apply_selected():
            item=preset_list.currentItem()
            if not item:return
            preset=presets.get(item.data(Qt.UserRole),{});self.settings["material_organizer_review_visual_rules"]=str(preset.get("rules","") or "");self.settings["material_organizer_review_prompt"]=str(preset.get("prompt","") or "");save_app_settings(self.settings);QMessageBox.information(dialog,"已应用审核预设",f"已应用“{item.data(Qt.UserRole)}”。")
        def delete_selected():
            item=preset_list.currentItem()
            if not item:return
            name=item.data(Qt.UserRole)
            if QMessageBox.question(dialog,"删除审核预设",f"确定删除“{name}”吗？")==QMessageBox.Yes:presets.pop(name,None);self.settings["material_organizer_review_presets"]=presets;save_app_settings(self.settings);refresh()
        buttons=QHBoxLayout();buttons.addWidget(self.btn("编辑当前视觉规则",lambda:self.edit_material_review_text("visual_rules","视觉规则","每行一条视觉审核要求。")));buttons.addWidget(self.btn("编辑当前提示词",lambda:self.edit_material_review_text("prompt","审核提示词","输入额外审核规则。")));buttons.addWidget(self.btn("保存当前为预设",save_current,"primary"));buttons.addWidget(self.btn("应用选中预设",apply_selected,"loadData"));buttons.addWidget(self.btn("删除预设",delete_selected,"danger"));buttons.addStretch();buttons.addWidget(self.btn("关闭",dialog.accept));layout.addLayout(buttons);refresh();dialog.exec()

    def material_keyword_scan(self,table,states,notes):
        keywords=[str(value).strip() for value in self.settings.get("material_organizer_review_keywords",[]) if str(value).strip()]
        if not keywords:QMessageBox.information(self,"关键词扫描","词库为空，请先编辑词库。 ");return
        hits=0
        for row in range(table.rowCount()):
            anchor=table.item(row,0);text=" ".join(table.item(row,column).text() if table.item(row,column) else "" for column in (5,6,7));matched=[word for word in keywords if word.casefold() in text.casefold()]
            if anchor and matched:
                key=anchor.data(Qt.UserRole)[2];states[key]="需复核";table.item(row,8).setText("需复核");note="关键词命中："+"、".join(matched);notes[key]=note;table.item(row,9).setText(note);hits+=1
        QMessageBox.information(self,"关键词扫描完成",f"已标记 {hits} 条需要复核的数据；点击“保存修改”后同步到项目。")

    def material_review_precheck(self,table,states,notes):
        changed=0
        for row in range(table.rowCount()):
            anchor=table.item(row,0);image=table.item(row,3).text().strip() if table.item(row,3) else "";cn=table.item(row,5).text().strip() if table.item(row,5) else "";en=table.item(row,6).text().strip() if table.item(row,6) else "";key=anchor.data(Qt.UserRole)[2] if anchor else ""
            if not image or not Path(image).is_file():status,note="图片缺失","图片路径为空或文件不存在"
            elif not (cn or en):status,note="需复核","缺少中文或英文文案"
            else:status,note="待审核","图片与文案基础检查通过，等待人工或 AI 复核"
            if anchor:states[key]=status;notes[key]=note;table.item(row,8).setText(status);table.item(row,9).setText(note);changed+=1
        QMessageBox.information(self,"智能初检完成",f"已检查 {changed} 条数据；该初检核对文件存在性和文案完整性。点击“保存修改”后同步到项目。")

    def start_material_ai_review(self,table,states,notes,dialog):
        config=dict(self.settings.get("material_organizer_review_ai") or self.settings.get("material_organizer_ai",{}));config["review_rules"]=str(self.settings.get("material_organizer_review_visual_rules","")).strip();config["review_prompt"]=str(self.settings.get("material_organizer_review_prompt","")).strip()
        if str(config.get("mode","clip") or "clip")!="api":QMessageBox.information(dialog,"需要远程视觉 API","请先点击“审核 AI 配置”填写远程视觉 API 的接口、模型和 API Key。CLIP 模式仍可用于批量图片匹配。 ");return
        selected=sorted({index.row() for index in table.selectedIndexes()});targets=selected or list(range(table.rowCount()));rows=[]
        for row in targets:
            image=table.item(row,3).text().strip() if table.item(row,3) else ""
            if not image or not Path(image).is_file():continue
            rows.append({"audit_row":row,"image":image,"cn":table.item(row,5).text().strip() if table.item(row,5) else "","en":table.item(row,6).text().strip() if table.item(row,6) else "","remark":table.item(row,7).text().strip() if table.item(row,7) else ""})
        if not rows:QMessageBox.warning(dialog,"没有可审核图片","请选择包含有效图片路径的记录，或先在审核台填入图片路径。 ");return
        progress=QProgressBar();progress.setRange(0,100);progress.setValue(0);dialog.layout().insertWidget(2,progress)
        thread=MaterialAuditThread(rows,config,dialog);self.material_audit_thread=thread
        def apply_result(row,status,reason,suggestion):
            anchor=table.item(row,0);state_item=table.item(row,8);note_item=table.item(row,9)
            if not anchor or not state_item or not note_item:return
            key=anchor.data(Qt.UserRole)[2];states[key]=status;notes[key]=reason.strip();state_item.setText(status);note_item.setText(notes[key]);suggestion_item=table.item(row,10)
            if suggestion_item:suggestion_item.setText(suggestion.strip())
        def fail(message):QMessageBox.warning(dialog,"AI 图文审核失败",message)
        def done():progress.setValue(100);progress.deleteLater();self.material_audit_thread=None
        thread.progress.connect(progress.setValue);thread.reviewed.connect(apply_result);thread.failed.connect(fail);thread.completed.connect(done);thread.start()

    def copy_generic_table_cells(self,table):
        indexes=table.selectedIndexes()
        if not indexes:return
        rows=sorted({index.row() for index in indexes});columns=sorted({index.column() for index in indexes});selected={(index.row(),index.column()) for index in indexes};text="\n".join("\t".join(table.item(row,column).text() if (row,column) in selected and table.item(row,column) else "" for column in columns) for row in rows);QGuiApplication.clipboard().setText(text)

    def show_material_stock(self):
        if not self.material_projects:QMessageBox.information(self,"图片库存报告","当前没有素材项目。 ");return
        dialog,layout=self.themed_dialog("图片库存报告",1080,650);summary=QLabel();summary.setObjectName("title");layout.addWidget(summary);table=QTableWidget(0,7);table.setHorizontalHeaderLabels(("项目名","素材目录","目录图片总数","已匹配行数","待匹配文案","剩余图片","状态"));table.setEditTriggers(QAbstractItemView.NoEditTriggers);table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        for column,width in enumerate((180,360,120,120,120,110,180)):table.setColumnWidth(column,width)
        layout.addWidget(table,1)
        def refresh():
            table.setRowCount(0);total_images=total_matched=short_projects=0
            for name,entry in self.material_projects.items():
                source=Path(entry["source"].text().strip());rows=self.material_rows(name);images=0
                if source.is_dir():
                    try:images=sum(1 for path in source.rglob("*") if path.is_file() and path.suffix.lower() in {".jpg",".jpeg",".jfif",".png",".webp",".bmp",".gif",".tif",".tiff"})
                    except OSError:images=0
                matched=sum(1 for values in rows if values[1] and Path(values[1]).is_file());scripts=sum(1 for values in rows if values[3] or values[4] or values[5]);needed=max(0,scripts-matched);remaining=max(0,images-matched)
                if not source.is_dir():status,color="未设置有效目录","#FFF2C2"
                elif not images:status,color="目录无图片","#F9D8DD";short_projects+=1
                elif needed>remaining:status,color=f"缺 {needed-remaining} 张","#F9D8DD";short_projects+=1
                elif not needed:status,color="已全部匹配","#DDF4E5"
                elif remaining<=3:status,color=f"仅剩 {remaining} 张","#FFF2C2"
                else:status,color=f"图片充足（剩余 {remaining} 张）","#DDF4E5"
                row=table.rowCount();table.insertRow(row)
                for column,value in enumerate((name,str(source) if source else "（未设置）",str(images),str(matched),str(needed),str(remaining),status)):
                    item=QTableWidgetItem(value);item.setBackground(QColor(color));table.setItem(row,column,item)
                total_images+=images;total_matched+=matched
            summary.setText(f"共 {len(self.material_projects)} 个项目 ｜ 目录图片 {total_images} 张 ｜ 已匹配 {total_matched} 条 ｜ 图片不足项目 {short_projects} 个")
        refresh();buttons=QHBoxLayout();buttons.addWidget(self.btn("刷新统计",refresh,"loadData"));buttons.addStretch();buttons.addWidget(self.btn("关闭",dialog.accept));layout.addLayout(buttons);dialog.exec()

    def export_material_summary(self):
        states=dict(self.settings.get("material_organizer_review_states",{}));notes=dict(self.settings.get("material_organizer_review_notes",{}));suggestions=dict(self.settings.get("material_organizer_review_suggestions",{}));rows=[]
        for project,entry in self.material_projects.items():
            table=entry["table"]
            for source_row in range(table.rowCount()):
                values=[table.item(source_row,column).text().strip() if table.item(source_row,column) else "" for column in range(6)]
                if not any(values):continue
                key=f"{project}\t{source_row}\t{values[0]}";status=str(states.get(key) or ("图片缺失" if not values[1] or not Path(values[1]).is_file() else "待审核"));rows.append([project,*values,status,notes.get(key,""),suggestions.get(key,"")])
        if not rows:QMessageBox.warning(self,"没有可导出数据","请先在素材项目中录入数据，再导出汇总。 ");return
        raw_root=self.material_global_output.text().strip() if hasattr(self,"material_global_output") else ""
        default_root=self.material_render_path(raw_root) if raw_root else Path(self.settings.get("last_material_export_dir") or self.settings.get("last_output_dir","") or Path.cwd())
        default=str(default_root/"全部项目素材汇总.xlsx");path,_=QFileDialog.getSaveFileName(self,"导出全部项目汇总",default,"Excel 工作簿 (*.xlsx);;CSV 文件 (*.csv)")
        if not path:return
        target=Path(path);values=[["项目名","代码","图片路径","评分","中文文案","英文文案","备注","审核状态","审核说明","修改建议"],*rows]
        try:
            target.parent.mkdir(parents=True,exist_ok=True)
            if target.suffix.lower()==".csv":
                with target.open("w",encoding="utf-8-sig",newline="") as file:csv.writer(file).writerows(values)
            else:_write_simple_xlsx([[str(value) for value in row] for row in values],target,"全部项目汇总",(20,18,55,12,42,42,30,16,42))
            self.settings["last_material_export_dir"]=str(target.parent);save_app_settings(self.settings);add_history({"project":"素材整理与汇总","operation":"导出全部项目汇总","result":f"导出 {len(rows)} 条素材","file":str(target)});QMessageBox.information(self,"导出完成",f"已导出 {len(rows)} 条素材汇总：\n{target}")
        except OSError as error:QMessageBox.warning(self,"导出失败",str(error))

    def write_material_batch_summary(self,conflict_mode="new"):
        """一键整理时自动生成与 main.py 一致的 Excel + CSV 总汇总。"""
        rows=[];first_root=None
        for project,entry in self.material_projects.items():
            root=self.material_output_root(project)
            if first_root is None and root:first_root=root
            for values in self.material_rows(project):
                if values[0] or values[3] or values[4]:rows.append([project,values[0],values[3],values[4]])
        if not rows or not first_root:return []
        try:
            first_root.mkdir(parents=True,exist_ok=True)
            xlsx=(first_root/"全部项目汇总_中英对照.xlsx") if conflict_mode=="overwrite" else self.material_unique_path(first_root,"全部项目汇总_中英对照",".xlsx",120,240);csv_path=(first_root/"全部项目汇总_中英对照.csv") if conflict_mode=="overwrite" else self.material_unique_path(first_root,"全部项目汇总_中英对照",".csv",120,240)
            values=[["项目名","代码","中文文案","英文文案"],*rows]
            _write_simple_xlsx(values,xlsx,"全部项目汇总",(22,22,48,48))
            with csv_path.open("w",encoding="utf-8-sig",newline="") as file:csv.writer(file).writerows(values)
            self._material_undo_history=getattr(self,"_material_undo_history",[])+[[('file','',str(xlsx)),('file','',str(csv_path))]]
            add_history({"project":"素材整理与汇总","operation":"一键整理全部项目汇总","result":f"导出 {len(rows)} 条素材","file":str(xlsx)})
            return (str(xlsx),str(csv_path))
        except OSError as error:
            LOGGER.exception("全部项目汇总导出失败：%s",error);return []

    def export_material_project_csv(self,name,show_message=True):
        rows=self.material_rows(name)
        root=self.material_output_root(name)
        if not rows:
            if show_message:QMessageBox.warning(self,"没有可导出数据",f"项目“{name}”没有素材数据。 ")
            return []
        if not root:
            if show_message:QMessageBox.warning(self,"请选择输出目录","请填写全局统一存放位置，或当前项目的整理后存放位置。 ")
            return []
        target_dir=root/clean_long_filename(name);csv_rows=[[row[0],row[3],row[4]] for row in rows if row[0] or row[3] or row[4]]
        if not csv_rows:
            if show_message:QMessageBox.warning(self,"没有可导出数据",f"项目“{name}”没有代码或中英文文案可导出。 ")
            return []
        try:
            target_dir.mkdir(parents=True,exist_ok=True)
            code_en=self.material_unique_path(target_dir,f"{name}_仅代码英文",".csv",120,240)
            comparison=self.material_unique_path(target_dir,f"{name}_中英对照汇总",".csv",120,240)
            with code_en.open("w",encoding="utf-8-sig",newline="") as file:csv.writer(file).writerows([[row[0],row[2]] for row in csv_rows])
            with comparison.open("w",encoding="utf-8-sig",newline="") as file:csv.writer(file).writerows([["代码","中文文案","英文文案"],*csv_rows])
            add_history({"project":name,"operation":"导出当前项目 CSV","result":f"导出 {len(csv_rows)} 条素材","file":str(comparison)})
            if show_message:QMessageBox.information(self,"导出完成",f"项目“{name}”CSV 已导出：\n\n1. {code_en}\n2. {comparison}")
        except OSError as error:QMessageBox.warning(self,"导出失败",str(error))
        return csv_rows

    def organize_material_project(self,name,show_message=True,conflict_mode="new"):
        # 与 main.py run_single_heygen_project 保持同一准则：只有图片真实存在的行才会创建输出目录。
        if name not in self.material_projects:return 0
        entry=self.material_projects[name];root=self.material_output_root(name)
        if not root:
            if show_message:QMessageBox.warning(self,"请选择输出目录",f"请设置项目“{name}”的整理后存放位置，或填写全局统一存放位置。")
            return 0
        output_root=root/clean_long_filename(name);history=[];csv_rows=[];count=0;copied=0;organized_dirs={};processed_codes=set()
        for index,(code,image,_score,cn,en,_note) in enumerate(self.material_rows(name),1):
            source=Path(image)
            if not image or not source.is_file():continue
            output_root.mkdir(parents=True,exist_ok=True);item_name=clean_long_filename(code,120) if code else f"item_{index}";canonical_dir=output_root/item_name
            if conflict_mode=="overwrite" and item_name not in processed_codes:
                if canonical_dir.is_symlink():LOGGER.warning("为安全起见，跳过符号链接整理目录：%s",canonical_dir);continue
                if canonical_dir.is_dir():shutil.rmtree(canonical_dir)
                item_dir=canonical_dir
            else:item_dir=self.material_unique_path(output_root,item_name,"",120,240)
            processed_codes.add(item_name)
            if conflict_mode=="overwrite":target_image=item_dir/(clean_long_filename(item_name,120)+source.suffix);cn_file=item_dir/(clean_long_filename(cn or "中文文案",180)+".txt");en_file=item_dir/(clean_long_filename(en or "英文文案",180)+".txt")
            else:target_image=self.material_unique_path(item_dir,item_name,source.suffix,120,240);cn_file=self.material_unique_path(item_dir,cn or "中文文案",".txt",180,240);en_file=self.material_unique_path(item_dir,en or "英文文案",".txt",180,240)
            if en_file==cn_file:en_file=self.material_unique_path(item_dir,f"{en or '英文文案'}_英文",".txt",180,240)
            try:
                item_dir.mkdir(parents=True,exist_ok=True)
                if entry.get("move_mode") and entry["move_mode"].isChecked():shutil.move(source,target_image);history.append(("move",str(source),str(target_image)))
                else:shutil.copy2(source,target_image);history.append(("copy",str(source),str(target_image)))
                cn_file.write_text(cn,encoding="utf-8");history.append(("file","",str(cn_file)));en_file.write_text(smart_wrap_text(en,60,merge_single_linebreaks=True),encoding="utf-8");history.append(("file","",str(en_file)));organized_dirs[index]=item_dir;csv_rows.append([code,cn,en]);count+=1;copied+=1
            except OSError as error:LOGGER.exception("素材整理失败：%s",error)
        if csv_rows:
            try:
                code_en=(output_root/f"{clean_long_filename(name,120)}_仅代码英文.csv") if conflict_mode=="overwrite" else self.material_unique_path(output_root,f"{name}_仅代码英文",".csv",120,240);comparison=(output_root/f"{clean_long_filename(name,120)}_中英对照汇总.csv") if conflict_mode=="overwrite" else self.material_unique_path(output_root,f"{name}_中英对照汇总",".csv",120,240)
                with code_en.open("w",encoding="utf-8-sig",newline="") as file:csv.writer(file).writerows([[row[0],row[2]] for row in csv_rows])
                with comparison.open("w",encoding="utf-8-sig",newline="") as file:csv.writer(file).writerows([["代码","中文文案","英文文案"],*csv_rows])
                history.extend((("file","",str(code_en)),("file","",str(comparison))))
            except OSError as error:LOGGER.exception("CSV 写入失败：%s",error)
        entry["_last_organized_dirs"]=organized_dirs
        if history:self._material_undo_history=getattr(self,"_material_undo_history",[])+[history]
        add_history({"project":name,"operation":"整理当前项目","result":f"整理 {count} 条，复制图片 {copied} 张","file":str(output_root)})
        if show_message:QMessageBox.information(self,"素材整理完成",f"已整理 {count} 条素材，复制图片 {copied} 张。\n\n输出目录：\n{output_root}" if count else f"项目“{name}”没有可处理的素材（只有图片路径真实存在的行才会输出）。")
        return count

    def undo_material_organize(self):
        transactions=getattr(self,"_material_undo_history",[])
        if not transactions:QMessageBox.information(self,"没有可撤销记录","当前没有可撤销的素材整理操作。 ");return
        history=transactions.pop()
        restored=0
        for kind,source,target in reversed(history):
            try:
                path=Path(target)
                if kind=="move" and path.exists():Path(source).parent.mkdir(parents=True,exist_ok=True);shutil.move(path,source);restored+=1
                elif kind in ("copy","file") and path.exists():path.unlink();restored+=1
            except OSError:LOGGER.exception("撤销素材整理失败")
        self._material_undo_history=transactions;QMessageBox.information(self,"撤销完成",f"已撤销最近一次整理产生的 {restored} 项操作。")

    def help_page(self):
        """内置、离线可阅读的使用说明，随程序一并发布。"""
        page=QWidget();layout=QVBoxLayout(page);top=QHBoxLayout();top.addWidget(self.title("使用说明"));top.addStretch()
        version=QLabel(f"{APP_NAME}  ·  版本 v{APP_VERSION}");version.setObjectName("sideMuted");version.setStyleSheet(f"color:{QColor(self.accent).darker(130).name()};font-weight:700;padding:6px 10px;");top.addWidget(version);layout.addLayout(top)
        card=QFrame();card.setObjectName("card");card_layout=QVBoxLayout(card);hint=QLabel("本说明可离线查看。建议首次使用时按“快速开始”完成一次扫描、预览与导出。");hint.setWordWrap(True);card_layout.addWidget(hint)
        guide=QTextEdit();guide.setReadOnly(True);guide.setTextInteractionFlags(Qt.TextSelectableByMouse);guide.setHtml("""
<style>body{line-height:1.65;}h2{color:#2450A6;margin-top:18px;}h3{color:#183B2B;margin-top:12px;}li{margin:5px 0;}code{background:#EDF2F7;padding:2px 4px;}</style>
<h2>1. 软件用途与推荐流程</h2>
<p><strong>VideoTaskHub</strong>用于批量整理图片、人物文案与台词素材：先在“素材整理与汇总预览”建立素材项目、填写或匹配图文资料，再在“项目工作台”读取数字台词、筛选未完成任务，并输出表格、TXT 与对应图片，供后续 AI 生成视频使用。</p>
<ol><li>建立或导入素材项目，整理图片路径、代码、中文/英文文案。</li><li>需要时使用 AI 图文匹配，核对匹配结果。</li><li>在项目工作台扫描数字台词 TXT，编辑预览数据。</li><li>按表格、多个 TXT、图片或待制作合并目录的方式导出。</li></ol>
<h2>2. 素材整理与汇总预览</h2>
<h3>建立项目与录入资料</h3>
<ul><li>填写<strong>监控总素材根目录</strong>后，可使用“批量从文件夹建项”，从子文件夹快速建立多个项目。</li><li>每个项目可单独填写素材来源目录和整理后存放位置；留空时会使用全局统一存放位置。路径支持 <code>{date}</code>、<code>{yyyy-MM-dd}</code>、<code>{yyyyMMdd}</code>、<code>{project}</code> 变量。</li><li>表格列依次为代码、图片路径、评分、中文文案、英文文案、备注。支持直接粘贴 Google 表格/Excel 的多行多列数据。</li><li>英文分段字数按项目独立保存；新建项目会继承最近一次设置值。</li></ul>
<h3>AI 智能图片匹配</h3>
<ul><li>在“AI 配置”中默认使用本地 CLIP 极速匹配；也可配置远程视觉 API、多个 Key、重试次数与间隔。</li><li>点击项目内<strong>AI 智能图文匹配</strong>，软件会扫描图片并把匹配结果回填到图片路径和评分列。</li><li>点击<strong>停止当前 AI 匹配</strong>可中断单项目任务；顶部“停止批量 AI 匹配”可同时停止当前任务并取消队列。当前网络请求或模型计算会在安全返回点结束，已完成结果会保留。</li><li>可打开“图文审核台”人工复核、替换图片、标记状态与保存审核意见。</li></ul>
<h3>整理与汇总导出</h3>
<ul><li>“仅整理当前项目”会按代码建立目录并复制/移动图片、输出中英文资料；移动模式可在项目中切换。</li><li>可导出当前项目 CSV、分段英文、全部项目汇总、图片库存报告和分段图片；“撤销上次整理”仅撤销最近一次由本软件产生的复制/移动操作。</li><li>勾选“匹配完成后自动整理并导出”或“整理后自动导出分段英文”后，会保留最后一次勾选状态。</li></ul>
<h2>3. 项目工作台：台词扫描与待制作导出</h2>
<ol><li>点击“新建项目”，输入名称；若名称为空但已选择扫描目录，软件会使用目录名。也可建立空项目。</li><li>选择、手动输入或直接拖入<strong>扫描目录</strong>与<strong>输出目录</strong>。点击“加载并更新项目数据”读取目录，并显示可编辑预览。</li><li>先选择<strong>指令分类</strong>，再选择该分类直属的指令；详细指令会直接与台词拼接，不额外插入分隔符。</li><li>检查预览后点击“确认并导出”。导出内容始终以当前预览表格为准，而不是重新扫描出的旧数据。</li></ol>
<h3>识别与跳过规则</h3>
<ul><li>递归读取所有层级中的数字命名 TXT，例如 <code>1.txt</code>、<code>2.txt</code>。</li><li>同一素材文件夹优先使用同名 PNG，其次为 JPG、JPEG；常规图片格式均可识别。</li><li>若同时存在 <code>2.txt</code> 和同名视频（如 <code>2.mp4</code>），该任务视为已完成，会从预览、表格与图片导出中跳过。</li><li>若一个文件夹有多个已完成和未完成编号，只保留未完成编号；没有数字 TXT 的文件夹不生成待制作任务。</li><li>编号缺失、图片缺失等会显示在“检查状态”，可用“查看检查提示”汇总核对。</li></ul>
<h3>输出模式与图片</h3>
<ul><li><strong>表格文件</strong>：导出一个 XLSX、CSV 或 TSV。使用“设置表头”可选择列、双击改列名、拖拽调整输出顺序；设置会保存到用户配置。</li><li><strong>多个 TXT 文件</strong>：每条台词输出一个 TXT，默认回到原素材目录；合并模式下输出到待制作目录。</li><li>勾选<strong>同时导出对应图片</strong>时，一条未完成数字 TXT 对应复制一张图片；也可用“导出图片”单独输出。</li><li>勾选<strong>合并导出到待制作目录</strong>时，表格/TXT 与图片统一放入“项目名-待制作”目录。遇到同名文件会展示覆盖、创建新目录或选择其他目录的清单。</li></ul>
<h2>4. 通用表格操作与查看表格</h2>
<ul><li>所有主要表格共用同一引擎：单击选中，Ctrl/Shift 多选，Ctrl+C/X/V 复制剪切粘贴，Delete 清空，Ctrl+Z/Y 撤销重做；双击、F2 或直接输入可编辑。</li><li>可拖拽选区右下角填充柄进行横向/纵向填充；如 <code>小明001</code> 下拉可生成连续编号。支持常见公式与 A1 单元格引用。</li><li>“查看表格”可打开 XLSX、CSV、TSV，在软件中编辑后点击<strong>保存到原文件</strong>写回，或用<strong>另存为</strong>保存新文件。外部文件不会被自动覆盖。</li><li>最近打开与工作台导出的表格文件会保留最多 100 条记录；文件被移动或删除时，软件会提示并允许从其他位置重新选择文件。</li></ul>
<h2>5. 指令库</h2>
<ul><li>可建立一级和二级分类。右击分类可新建分类或指令；分类为空时才能删除。</li><li>双击指令或点击“编辑指令”才进入可编辑状态，避免误改。指令可拖拽移动到任意分类。</li><li>支持导入、导出、合并指令；默认 XLSX，也支持 CSV、JSON。导入/导出前会进入可编辑预览，可只选择部分指令处理。</li></ul>
<h2>6. 记录、运行状态与设置</h2>
<ul><li><strong>操作历史</strong>记录项目和导出相关操作；最近项目可快速打开已保存项目。</li><li>左下角<strong>运行状态</strong>：单击展开底部实时执行日志；双击打开独立的大型日志窗口，不影响继续操作软件。该日志仅保留本次会话，软件关闭即释放。</li><li><strong>系统日志</strong>仅保留警告、异常和重要报错，可刷新、清空、打开日志文件或目录。</li><li><strong>系统设置</strong>可选择配置/临时/日志目录，备份、恢复或初始化配置；“导航栏排序”可拖拽调整左侧功能顺序并立即应用。</li><li><strong>皮肤设置</strong>可更换主题、背景图、透明度、导航雾化程度与背景位置。保存皮肤后位置会锁定。</li></ul>
<h2>7. 项目保存与常见提示</h2>
<ul><li>“保存项目”才会写入 <code>.project.json</code>；打开项目后会恢复路径、文件名、指令、导出选项与预览数据。</li><li>“清空当前项目数据”只清空当前界面，不删除素材和已导出文件；“删除项目”只删除项目文件及项目列表记录。</li><li>导出前建议先重新加载目录、检查预览和检查状态。若导出目标已存在，请在冲突预览中确认覆盖或创建新目录。</li><li>遇到报错时，先打开“运行状态”查看本次执行过程，再到“系统日志”查看可长期保留的重要错误记录。</li></ul>
""");card_layout.addWidget(guide,1);layout.addWidget(card,1);return page

    def log_page(self):
        page=QWidget(); layout=QVBoxLayout(page); top=QHBoxLayout(); top.addWidget(self.title("系统日志")); top.addStretch(); top.addWidget(self.btn("刷新日志",self.refresh_log,"primary")); top.addWidget(self.btn("清空日志",self.clear_log,"danger")); top.addWidget(self.btn("打开日志文件",self.open_log_file)); top.addWidget(self.btn("打开日志目录",self.open_log_directory)); layout.addLayout(top); hint=QLabel(f"日志保存在系统临时目录：{LOG_FILE}"); hint.setWordWrap(True); layout.addWidget(hint); self.log_view=QTextEdit(); self.log_view.setReadOnly(True); self.log_view.setPlaceholderText("软件启动、操作异常等信息会显示在这里。"); layout.addWidget(self.log_view,1); return page

    def skin_page(self):
        page=QWidget(); layout=QVBoxLayout(page); layout.addWidget(self.title("皮肤设置")); card=QFrame(); card.setObjectName("card"); form=QFormLayout(card); form.setContentsMargins(18,18,18,18)
        self.skin_image=QLineEdit(self.settings.get("skin_background","")); self.skin_image.setPlaceholderText("可选：选择一张本地图片作为软件背景"); image_controls=QHBoxLayout(); image_controls.addWidget(self.skin_image,1); image_controls.addWidget(self.btn("选择背景图",self.choose_skin_image)); image_controls.addWidget(self.btn("清除背景图",self.clear_skin_image)); form.addRow("背景图片",image_controls)
        self.opacity=QSlider(Qt.Horizontal); self.opacity.setRange(0,100); self.opacity.setValue(int(self.settings.get("skin_opacity",18))); self.opacity_label=QLabel(f"{self.opacity.value()}%"); self.opacity.valueChanged.connect(self.opacity_changed); opacity_controls=QHBoxLayout(); opacity_controls.addWidget(self.opacity,1); opacity_controls.addWidget(self.opacity_label); form.addRow("背景透明度",opacity_controls)
        self.nav_opacity_slider=QSlider(Qt.Horizontal); self.nav_opacity_slider.setRange(0,100); self.nav_opacity_slider.setValue(self.nav_opacity); self.nav_opacity_label=QLabel(f"{self.nav_opacity}%"); self.nav_opacity_slider.valueChanged.connect(self.nav_opacity_changed); nav_controls=QHBoxLayout(); nav_controls.addWidget(self.nav_opacity_slider,1); nav_controls.addWidget(self.nav_opacity_label); form.addRow("导航雾化程度",nav_controls)
        self.theme_box=QComboBox(); self.theme_box.addItems((*THEMES.keys(),"自定义颜色")); matching=self.theme_name if self.theme_name in THEMES else "自定义颜色"; self.theme_box.setCurrentText(matching); self.theme_box.currentTextChanged.connect(self.choose_theme); theme_controls=QHBoxLayout(); theme_controls.addWidget(self.theme_box); theme_controls.addWidget(self.btn("选择颜色",self.pick_color)); theme_controls.addWidget(self.btn("从背景提取配色",self.extract_background_color)); form.addRow("软件配色",theme_controls)
        theme_note=QLabel("浅色：天空蓝（清朗）、森林绿（稳定）、薰衣草紫（创意）、远山青（专注）、月光银（专业）、晨曦金（灵感）、玫瑰暮色（平衡）、海盐蓝（秩序）、赤陶棕（沉稳）。夜间：午夜星海（深夜专注）、极夜紫（创作沉浸）、墨玉绿（护眼安定）、曜石灰（极简专业）。");theme_note.setWordWrap(True);form.addRow("主题寓意",theme_note)
        self.zoom_slider=QSlider(Qt.Horizontal); self.zoom_slider.setRange(50,250); self.zoom_slider.setValue(round(self.image_zoom*100)); self.zoom_label=QLabel(f"{self.zoom_slider.value()}%"); self.zoom_slider.valueChanged.connect(self.zoom_changed); zoom_controls=QHBoxLayout(); zoom_controls.addWidget(self.zoom_slider,1); zoom_controls.addWidget(self.zoom_label); zoom_controls.addWidget(self.btn("居中复位",self.reset_background_position)); form.addRow("背景缩放",zoom_controls)
        note=QLabel("背景图仅作为柔和底纹。点击“调整背景位置”后，预览区或软件背景空白处均可拖拽图片；方向键可微调位置，按住 Shift 加快移动，滚轮可缩放。导航雾化程度越低，背景图越能透入导航栏；保存皮肤后会锁定位置。表格与主要操作区保持半透明浅色卡片，以保证文字和按钮清晰可用。"); note.setWordWrap(True); form.addRow("调整说明",note)
        self.skin_preview=BackgroundWidget(); self.skin_preview.setMinimumHeight(220); self.skin_preview.on_transform_changed=self.preview_transform_changed; form.addRow("背景预览（可拖拽）",self.skin_preview)
        actions=QHBoxLayout(); actions.addStretch(); actions.addWidget(self.btn("调整背景位置",self.unlock_background_position)); actions.addWidget(self.btn("恢复天空蓝默认风格",self.reset_skin)); actions.addWidget(self.btn("保存皮肤设置",lambda:self.apply_skin(True),"primary")); form.addRow(actions); layout.addWidget(card); layout.addStretch(); return page

    def show_page(self,index):
        self.stack.setCurrentIndex(index)
        # 每次切换都即时保存，关闭软件时即使没有触发其它操作也能恢复最后页面。
        if 0 <= int(index) < self.stack.count():
            self.settings["last_navigation_index"] = int(index)
            save_app_settings(self.settings)
        if index!=5: self.set_background_editable(False)
        if index==0:self.refresh_recent()
        elif index==1:self.refresh_instruction_list()
        elif index==2:self.refresh_history()
        elif index==4:self.refresh_log()
        elif index==6:self.refresh_viewer_snapshots()

    def restore_navigation_page(self):
        """启动后恢复上次关闭时所在导航；没有记录时默认进入素材整理。"""
        try:
            # 素材整理与汇总预览是首屏功能（导航索引 8）。已有记录即使为项目工作台 0 也必须保留。
            index=int(self.settings.get("last_navigation_index",8))
        except (TypeError,ValueError):
            index=8
        if not 0 <= index < self.stack.count():
            index=8 if self.stack.count() > 8 else 0
        self.show_page(index)

    def selected_instruction_category(self):
        if not hasattr(self,"instruction_category"):return "全部分类"
        return getattr(self,"_selected_instruction_category",self.settings.get("last_instruction_category","全部分类"))
    def show_selected_category(self,path,label):
        self.instruction_category.setEditText(label)
        if hasattr(self,"category_folder_action"):
            self.category_folder_action.setIcon(self.folder_icon());self.category_folder_action.setVisible(path!="全部分类")
    def select_instruction_category_index(self,index):
        path=index.data(Qt.UserRole) or "全部分类";self._selected_instruction_category=path;self.settings["last_instruction_category"]=path;save_app_settings(self.settings)
        self.show_selected_category(path,"全部分类" if path=="全部分类" else index.data(Qt.DisplayRole).replace("📁  ",""));self.instruction_category.hidePopup();self.refresh_instruction_options();self.remember_workspace_selectors()
    def refresh_instruction_options(self,*_):
        categories=self.instruction_folders();current_category=self.selected_instruction_category()
        if hasattr(self,"instruction_category"):
            model=QStandardItemModel(self.instruction_category);root=model.invisibleRootItem();all_item=QStandardItem("全部分类");all_item.setData("全部分类",Qt.UserRole);root.appendRow(all_item);nodes={"":root}
            for folder in categories:
                parent_path=""
                for part in folder.split("/"):
                    path=part if not parent_path else parent_path+"/"+part
                    if path not in nodes:
                        node=QStandardItem(part);node.setIcon(self.folder_icon());node.setData(path,Qt.UserRole);nodes[parent_path].appendRow(node);nodes[path]=node
                    parent_path=path
            self.instruction_category.blockSignals(True);self.instruction_category.setModel(model);target=all_item
            for path,node in nodes.items():
                if path==current_category:target=node;break
            self._selected_instruction_category=target.data(Qt.UserRole) or "全部分类";self.instruction_category.setCurrentIndex(0);self.show_selected_category(self._selected_instruction_category,"全部分类" if target is all_item else target.text());self.instruction_category.view().expandAll();self.instruction_category.blockSignals(False)
        current=self.instruction.currentText();category=self.selected_instruction_category();values=[item.get("name","") for item in instructions() if category=="全部分类" or (item.get("folder", "未分类") or "未分类")==category]; self.instruction.blockSignals(True); self.instruction.clear()
        # 固定放在第一项：用户无需建立空指令，也能明确选择“只导出台词”。
        self.instruction.addItem("不使用指令","")
        for name in values:self.instruction.addItem(self.file_icon(),name,name)
        self.instruction.setCurrentText(current if current in values else "不使用指令"); self.instruction.blockSignals(False)
        # 列表重建时信号被屏蔽；显式刷新才能让编辑后的指令立即回填工作台。
        self.apply_instruction()
    def refresh_workspace_instruction_catalog(self):
        """安全刷新项目页的指令目录，不覆盖该页项目表格、目录或选择状态。"""
        if not hasattr(self,"instruction") or getattr(self,"_refreshing_workspace_instruction_catalog",False):return
        self._refreshing_workspace_instruction_catalog=True
        try:
            selected_name=self.instruction.currentData() or self.instruction.currentText()
            selected_category=self.selected_instruction_category()
            self.refresh_instruction_options()
            # 分类和指令仍存在时必须原样保留；只有被删除的分类/指令才由
            # refresh_instruction_options 回退到“全部分类 / 不使用指令”。
            if selected_category==self.selected_instruction_category() and selected_name and self.instruction.findText(selected_name)>=0:
                self.instruction.setCurrentText(selected_name)
            self.apply_instruction()
        finally:self._refreshing_workspace_instruction_catalog=False
    def instruction_folders(self):
        """保留分类创建/显示顺序，重命名时不因排序而改变上下位置。"""
        result=[]
        for folder in [*(self.settings.get("instruction_folders",[]) if isinstance(self.settings.get("instruction_folders",[]),list) else []),*[item.get("folder","未分类") or "未分类" for item in instructions()]]:
            if isinstance(folder,str) and folder and folder not in result:result.append(folder)
        return result
    def save_instruction_folders(self,folders):
        ordered=[]
        for folder in folders:
            if isinstance(folder,str) and folder and folder not in ordered:ordered.append(folder)
        self.settings["instruction_folders"]=ordered;save_app_settings(self.settings)

    def _save_instruction_tree_expansion(self,*_):
        """将用户最后一次展开状态写入配置，重启后也不改变其定位习惯。"""
        if getattr(self,"_restoring_instruction_tree_expansion",False) or not hasattr(self,"ilist"):return
        expanded=[]
        def collect(node):
            data=node.data(0,Qt.UserRole)
            if isinstance(data,dict) and data.get("folder") and node.isExpanded():expanded.append(data["folder"])
            for child_index in range(node.childCount()):collect(node.child(child_index))
        for root_index in range(self.ilist.topLevelItemCount()):collect(self.ilist.topLevelItem(root_index))
        self.settings["instruction_tree_expanded_paths"]=expanded;save_app_settings(self.settings)

    def refresh_instruction_list(self):
        # 刷新数据前先记住用户手动折叠的分类。指令较多时，不能因为新增、编辑、
        # 删除或移动一条指令，就把所有分类重新展开而丢失定位上下文。
        identity_records=instructions();seen_ids=set();identity_changed=False
        for identity_record in identity_records:
            if not isinstance(identity_record,dict):continue
            identity=str(identity_record.get("id","") or "")
            if not identity or identity in seen_ids:
                identity_record["id"]=uuid.uuid4().hex;identity_changed=True
            seen_ids.add(str(identity_record.get("id","") or ""))
        if identity_changed:save_instructions(identity_records)
        current_records=instructions();current_index=getattr(self,"inst_index",None);selected_instruction_id=str(current_records[current_index].get("id","") or "") if isinstance(current_index,int) and 0<=current_index<len(current_records) and isinstance(current_records[current_index],dict) else ""
        saved_expanded=self.settings.get("instruction_tree_expanded_paths",[])
        expanded_paths={str(path):True for path in saved_expanded if isinstance(path,str) and path}
        had_existing_tree=self.ilist.topLevelItemCount()>0
        def remember_expansion(node):
            data=node.data(0,Qt.UserRole)
            if isinstance(data,dict) and data.get("folder"):
                expanded_paths[data["folder"]]=node.isExpanded()
            for child_index in range(node.childCount()):remember_expansion(node.child(child_index))
        for root_index in range(self.ilist.topLevelItemCount()):remember_expansion(self.ilist.topLevelItem(root_index))
        scroll_value=self.ilist.verticalScrollBar().value()
        self._restoring_instruction_tree_expansion=True;self.ilist.blockSignals(True);self.ilist.clear();nodes={};folders=self.instruction_folders()
        def ensure_folder(path):
            if path in nodes:return nodes[path]
            parent_path,_,label=path.rpartition("/");parent=ensure_folder(parent_path) if parent_path else None
            node=QTreeWidgetItem([label or path]);node.setIcon(0,self.folder_icon());node.setData(0,Qt.UserRole,{"folder":path});font=QFont();font.setPointSize(max(9,round(12*float(getattr(self,"host_ui_scale",1.0) or 1.0))));font.setBold(True);node.setFont(0,font);node.setForeground(0,QColor(self.accent));(parent.addChild(node) if parent else self.ilist.addTopLevelItem(node));nodes[path]=node;return node
        for folder in folders:ensure_folder(folder)
        for index,item in enumerate(instructions()):
            folder=item.get("folder", "未分类") or "未分类";parent=nodes.get(folder)
            if parent:
                child=QTreeWidgetItem([item.get("name","")]);cover=self.instruction_album_cover_path(item) if hasattr(self,"instruction_album_cover_path") else None;child.setIcon(0,QIcon(str(cover)) if cover else self.file_icon());child.setData(0,Qt.UserRole,index);font=QFont();font.setPointSize(max(9,round(12*float(getattr(self,"host_ui_scale",1.0) or 1.0))));child.setFont(0,font);parent.addChild(child)
        # 首次打开也读取上次持久化的状态；新安装或新建分类默认收起，只有用户主动
        # 展开才会写入配置，避免大量分类在首次进入时铺满整棵树。
        for path,node in nodes.items():node.setExpanded(bool(expanded_paths.get(path,False)))
        self.ilist.blockSignals(False);self._restoring_instruction_tree_expansion=False;self.ilist.verticalScrollBar().setValue(scroll_value);self.refresh_instruction_options()
        # 设封面、添加/移除相册图片也需要刷新左侧的封面小图标，但绝不能让当前
        # 指令从视觉上“消失”。按稳定 ID 恢复选择并展开其所属分类。
        if selected_instruction_id:
            restored_index=next((index for index,item in enumerate(instructions()) if isinstance(item,dict) and str(item.get("id","") or "")==selected_instruction_id),None)
            if restored_index is not None:
                def restore_selection(node):
                    if node.data(0,Qt.UserRole)==restored_index:return node
                    for child_index in range(node.childCount()):
                        found=restore_selection(node.child(child_index))
                        if found:return found
                    return None
                target=next((found for root_index in range(self.ilist.topLevelItemCount()) if (found:=restore_selection(self.ilist.topLevelItem(root_index))) is not None),None)
                if target:
                    parent=target.parent()
                    while parent is not None:parent.setExpanded(True);parent=parent.parent()
                    self.ilist.setCurrentItem(target);target.setSelected(True)
        if hasattr(self,"instruction_search"):self.filter_instruction_tree(self.instruction_search.text())
        tabs=getattr(self,"_project_workspace_tabs",None)
        if tabs is not None and not getattr(self,"_instruction_catalog_syncing",False):tabs.synchronize_instruction_catalog(self)

    def filter_instruction_tree(self,query=""):
        """即时筛选分类、名称、正文和备注；不改变用户原先保存的展开状态。"""
        if not hasattr(self,"ilist"):return
        needle=str(query or "").strip().casefold();items=instructions()
        self.ilist.blockSignals(True)
        try:
            def show_all(node):
                node.setHidden(False)
                for child_index in range(node.childCount()):show_all(node.child(child_index))
            def filter_node(node,parent_matches=False):
                data=node.data(0,Qt.UserRole)
                if isinstance(data,int):
                    record=items[data] if 0<=data<len(items) else {}
                    haystack="\n".join(str(record.get(key,"") or "") for key in ("folder","name","content","note")).casefold()
                    visible=bool(parent_matches or needle in haystack);node.setHidden(not visible);return visible
                folder=str(data.get("folder","") if isinstance(data,dict) else node.text(0))
                own_match=needle in folder.casefold();child_visible=False
                for child_index in range(node.childCount()):
                    child_visible=filter_node(node.child(child_index),parent_matches or own_match) or child_visible
                visible=bool(own_match or child_visible);node.setHidden(not visible)
                if visible:node.setExpanded(True)
                return visible
            if not needle:
                for root_index in range(self.ilist.topLevelItemCount()):show_all(self.ilist.topLevelItem(root_index))
                saved={str(path) for path in self.settings.get("instruction_tree_expanded_paths",[]) if isinstance(path,str)}
                def restore(node):
                    data=node.data(0,Qt.UserRole)
                    if isinstance(data,dict) and data.get("folder"):node.setExpanded(data["folder"] in saved)
                    for child_index in range(node.childCount()):restore(node.child(child_index))
                for root_index in range(self.ilist.topLevelItemCount()):restore(self.ilist.topLevelItem(root_index))
            else:
                for root_index in range(self.ilist.topLevelItemCount()):filter_node(self.ilist.topLevelItem(root_index))
        finally:self.ilist.blockSignals(False)
    def remember_workspace_export_options(self,*_):
        """保存工作台最后一次图片/合并导出选择；项目切换和重启后均沿用。"""
        if getattr(self,"_restoring_workspace_export_options",False) or not hasattr(self,"copy_images"):
            return
        self.settings["workspace_copy_images"]=self.copy_images.isChecked()
        self.settings["workspace_merge_export"]=self.merge_export.isChecked()
        save_app_settings(self.settings)

    def restore_workspace_export_options(self,copy_images=None,merge_export=None,remember=False):
        """恢复全局最后选择；首次或初始化后默认导出图片并合并到待制作目录。"""
        if not hasattr(self,"copy_images"):
            return
        copy_value=bool(self.settings.get("workspace_copy_images",True) if copy_images is None else copy_images)
        merge_value=bool(self.settings.get("workspace_merge_export",True) if merge_export is None else merge_export)
        self._restoring_workspace_export_options=True
        try:
            self.copy_images.setChecked(copy_value or merge_value)
            self.merge_export.setChecked(merge_value)
            self.copy_images.setEnabled(not merge_value)
        finally:
            self._restoring_workspace_export_options=False
        if hasattr(self,"output_label"):
            self.merge_export_changed(merge_value)
        if remember:
            self.remember_workspace_export_options()

    def remember_workspace_selectors(self,*_):
        """保存工作台最后选择的分类、指令、输出模式和表格格式。"""
        if getattr(self,"_restoring_workspace_selectors",False) or not hasattr(self,"output_mode"):
            return
        self.settings["last_instruction_category"]=self.selected_instruction_category()
        self.settings["workspace_instruction_name"]=self.instruction.currentData() or self.instruction.currentText()
        self.settings["workspace_output_mode"]=self.output_mode_key()
        self.settings["workspace_scan_mode"]=self.scan_mode.currentData() if hasattr(self,"scan_mode") else "standard"
        self.settings["workspace_segment_bundle_image_mode"]=self.bundle_image_mode.currentData() if hasattr(self,"bundle_image_mode") else "segment_image"
        selected_format=self.format.currentText()
        if selected_format in FORMATS:
            self.settings["workspace_output_format"]=selected_format
        save_app_settings(self.settings)

    def restore_workspace_selectors(self):
        """恢复软件级最后选择；删除过的分类或指令会安全回退到可用项。"""
        if not hasattr(self,"output_mode"):
            return
        self._restoring_workspace_selectors=True
        try:
            saved_category=str(self.settings.get("last_instruction_category","全部分类") or "全部分类")
            self._selected_instruction_category=saved_category
            self.refresh_instruction_options()
            saved_instruction=str(self.settings.get("workspace_instruction_name","") or "")
            if self.instruction.findText(saved_instruction)>=0:
                self.instruction.setCurrentText(saved_instruction)
            saved_format=str(self.settings.get("workspace_output_format",FORMATS[0]) or FORMATS[0])
            if hasattr(self,"scan_mode"):
                index=self.scan_mode.findData(str(self.settings.get("workspace_scan_mode","standard") or "standard"))
                self.scan_mode.setCurrentIndex(index if index>=0 else 0)
            if hasattr(self,"bundle_image_mode"):
                index=self.bundle_image_mode.findData(str(self.settings.get("workspace_segment_bundle_image_mode","segment_image") or "segment_image"))
                self.bundle_image_mode.setCurrentIndex(index if index>=0 else 0)
            self.set_output_mode(self.settings.get("workspace_output_mode",OUTPUT_MODE_TABLE))
            # 切换到 TXT 模式时 output_mode_changed 会缓存当时的格式；随后恢复用户真实偏好。
            self._table_format=saved_format if saved_format in FORMATS else FORMATS[0]
            if self.output_mode_key()==OUTPUT_MODE_TABLE:
                self.format.setCurrentText(self._table_format)
        finally:
            self._restoring_workspace_selectors=False
        self.refresh_output_mode_labels()

    def new_project(self):
        self.active=None; self.rows=[]; self.warnings=[]; self._workspace_all_rows=[]
        if hasattr(self,"name"):
            for x in (self.name,self.input,self.output,self.filename):x.clear()
            self._inactive_output_directory=""
            self.encoding.setCurrentText("utf-8");self.restore_workspace_export_options();self.restore_workspace_selectors();self.column_layout=self.system_column_layout();self.output_mode_changed(); self.fill_table(); self.progress.setValue(0); self.summary.setText("新建空项目：仅“保存项目”会写入项目文件。"); self.state.setText("未保存项目\n仅手动保存项目文件"); self.refresh_recent()
    def defaults(self):
        path=self.input.text().strip()
        if path and not self.name.text().strip():self.name.setText(Path(path).name)
        if path and not self.output.text().strip():self.output.setText(path)
        stem=Path(self.filename.text()).stem if self.filename.text().strip() else self.name.text().strip()
        if stem and self.output_mode_key()==OUTPUT_MODE_TABLE:self.filename.setText(stem+EXT[self.format.currentText()])
    def output_mode_key(self,value=None):
        value=self.output_mode.currentData() if value is None else value
        if value in OUTPUT_MODES:return value
        return OUTPUT_MODE_MULTI_TXT if "TXT" in str(value) else OUTPUT_MODE_TABLE
    def set_output_mode(self,value):
        key=self.output_mode_key(value);index=self.output_mode.findData(key)
        self.output_mode.setCurrentIndex(max(0,index))
    def refresh_output_mode_labels(self):
        if not hasattr(self,"output_mode") or not hasattr(self,"merge_export"):return
        current=self.output_mode_key();merged=self.merge_export.isChecked();self.output_mode.blockSignals(True);self.output_mode.clear()
        self.output_mode.addItem("表格文件（输出到待制作目录）" if merged else "表格文件（输出到指定目录）",OUTPUT_MODE_TABLE)
        self.output_mode.addItem("多个 TXT 文件（输出到待制作目录）" if merged else "多个 TXT 文件（输出到原素材目录）",OUTPUT_MODE_MULTI_TXT)
        self.output_mode.setCurrentIndex(0 if current==OUTPUT_MODE_TABLE else 1);self.output_mode.blockSignals(False);self.output_mode_changed()
    def refresh_preview_output_directory(self,*_):
        """仅提示默认输出位置；最终路径仍以导出冲突窗口中的用户选择为准。"""
        if not hasattr(self,"preview_output"):return
        table_mode=self.output_mode_key()==OUTPUT_MODE_TABLE;merged=hasattr(self,"merge_export") and self.merge_export.isChecked()
        if merged:
            directory=self.waiting_export_directory()
            value=str(directory) if directory else "请先填写输出目录或扫描目录"
        elif table_mode:
            value=self.output.text().strip() or "请填写输出目录"
        else:value="原素材文件夹（按每条待制作任务分别输出）"
        self.preview_output.setText(value)
    def open_preview_output_directory(self):
        """双击预输出目录时仅打开已经存在的实际目录，绝不创建或改写路径。"""
        table_mode=self.output_mode_key()==OUTPUT_MODE_TABLE;merged=hasattr(self,"merge_export") and self.merge_export.isChecked()
        if merged:directory=self.waiting_export_directory()
        elif table_mode:directory=self.material_render_path(self.output.text().strip()) if self.output.text().strip() else None
        else:directory=self.material_render_path(self.input.text().strip()) if self.input.text().strip() else None
        if directory and Path(directory).is_dir():
            try:open_system_path(Path(directory))
            except OSError as error:LOGGER.exception("打开预输出目录失败：%s",directory);QMessageBox.warning(self,"无法打开预输出目录",str(error))
    def sync_filename(self):
        if hasattr(self,"filename"):self.defaults()
    def open_output_settings(self):
        """将较少调整的输出规则收进独立弹窗，释放主工作台表格空间。"""
        dialog,layout=self.themed_dialog("输出设置",510,360)
        hint=QLabel("这里设置本次项目的输出模式、表格格式、TXT 编码和导出内容。设置会随项目保存，并记住为下次新项目的默认值。")
        hint.setWordWrap(True);layout.addWidget(hint)
        form=QFormLayout();mode=DoubleClickComboBox();output_format=DoubleClickComboBox();encoding=DoubleClickComboBox();copy_images=QCheckBox("同时导出对应图片");merge_export=QCheckBox("合并导出到待制作目录")
        mode.addItem("表格文件（输出到待制作目录）" if self.merge_export.isChecked() else "表格文件（输出到指定目录）",OUTPUT_MODE_TABLE)
        mode.addItem("多个 TXT 文件（输出到待制作目录）" if self.merge_export.isChecked() else "多个 TXT 文件（输出到原素材目录）",OUTPUT_MODE_MULTI_TXT)
        mode.setCurrentIndex(0 if self.output_mode_key()==OUTPUT_MODE_TABLE else 1)
        encoding.addItems(("utf-8","gbk","gb18030","utf-8-sig"));encoding.setCurrentText(self.encoding.currentText())
        saved_format=getattr(self,"_table_format",self.format.currentText() if self.format.currentText() in FORMATS else FORMATS[0])
        def refresh_format(*_):
            table_mode=mode.currentData()==OUTPUT_MODE_TABLE;output_format.blockSignals(True);output_format.clear()
            if table_mode:
                output_format.addItems(FORMATS);output_format.setCurrentText(saved_format if saved_format in FORMATS else FORMATS[0]);output_format.setEnabled(True)
            else:
                output_format.addItem(".txt（多个 TXT 模式固定）");output_format.setEnabled(False)
            output_format.blockSignals(False)
        refresh_format();mode.currentIndexChanged.connect(refresh_format)
        copy_images.setChecked(self.copy_images.isChecked());merge_export.setChecked(self.merge_export.isChecked())
        def sync_export_options(enabled):
            if enabled:copy_images.setChecked(True)
            copy_images.setEnabled(not enabled)
        sync_export_options(merge_export.isChecked());merge_export.toggled.connect(sync_export_options)
        form.addRow("输出模式",mode);form.addRow("输出格式",output_format);form.addRow("TXT 编码",encoding);form.addRow("导出图片",copy_images);form.addRow("导出目录",merge_export);layout.addLayout(form)
        buttons=QHBoxLayout();buttons.addStretch();buttons.addWidget(self.btn("取消",dialog.reject));buttons.addWidget(self.btn("保存输出设置",dialog.accept,"primary"));layout.addLayout(buttons)
        if dialog.exec()!=QDialog.Accepted:return
        chosen_format=output_format.currentText()
        if chosen_format in FORMATS:self._table_format=chosen_format
        self.set_output_mode(mode.currentData())
        if self.output_mode_key()==OUTPUT_MODE_TABLE:self.format.setCurrentText(self._table_format)
        self.merge_export.setChecked(merge_export.isChecked());self.copy_images.setChecked(copy_images.isChecked() or merge_export.isChecked())
        self.encoding.setCurrentText(encoding.currentText());self.output_mode_changed();self.remember_workspace_selectors();self.remember_workspace_export_options()
        self.summary.setText("输出设置已更新；主表格与当前预览数据保持不变。")
    def output_mode_changed(self,*_):
        table_mode=self.output_mode_key()==OUTPUT_MODE_TABLE;merged=hasattr(self,"merge_export") and self.merge_export.isChecked()
        output_active=table_mode
        self.output_label.setText("输出目录")
        if output_active:
            if not self.output.text().strip() and getattr(self,"_inactive_output_directory",""):self.output.setText(self._inactive_output_directory)
            self.output.setEnabled(True);self.output.setPlaceholderText("请选择或输入输出目录")
        else:
            if self.output.text().strip():self._inactive_output_directory=self.output.text().strip()
            self.output.clear();self.output.setEnabled(False);self.output.setPlaceholderText("输出目录（合并模式）" if merged else "输出到原素材目录（按每条待制作任务分别输出）")
        self.output.setToolTip("合并模式默认按输出目录生成“输出目录-待制作”；最终仍可在导出确认窗口中选择其他目录" if merged else "多个 TXT 文件会分别输出到原素材目录" if not table_mode else "表格文件输出目录");self.filename.setVisible(table_mode);self.filename_label.setVisible(table_mode)
        self.format.blockSignals(True)
        if table_mode:
            current=getattr(self,"_table_format",FORMATS[0]);self.format.clear();self.format.addItems(FORMATS);self.format.setCurrentText(current if current in FORMATS else FORMATS[0]);self.format.setEnabled(True)
            if hasattr(self,"format_label"):self.format_label.setText("输出格式")
            self.defaults()
        else:
            if self.format.currentText() in FORMATS:self._table_format=self.format.currentText()
            self.format.clear();self.format.addItem(".txt");self.format.setEnabled(False)
            if hasattr(self,"format_label"):self.format_label.setText("输出格式")
        self.format.blockSignals(False)
        self.refresh_preview_output_directory()
    def merge_export_changed(self,enabled):
        if enabled:self.copy_images.setChecked(True)
        self.copy_images.setEnabled(not enabled)
        if hasattr(self,"output_label"):self.refresh_output_mode_labels()
    def confirm_scan_directory_load(self,directory,source_name=""):
        """询问目录选择是仅改路径，还是作为一套全新的工作台数据载入。"""
        dialog,layout=self.themed_dialog("载入扫描目录",700,300)
        title=QLabel("是否加载并更新全部项目数据？")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        source_hint=f"\n来源项目：{source_name}" if source_name else ""
        hint=QLabel(
            f"已选择扫描目录：\n{directory}{source_hint}\n\n"
            "“加载并更新全部数据”会按新项目载入：清空旧预览和当前项目状态，并同步更新项目名称、输出目录、预输出目录及文件名。\n"
            "“仅填入扫描目录”只替换扫描目录，其余已填写内容与预览数据保持不变。"
        )
        hint.setWordWrap(True);layout.addWidget(hint,1)
        buttons=QHBoxLayout();buttons.addStretch()
        buttons.addWidget(self.btn("取消",dialog.reject))
        only_input=self.btn("仅填入扫描目录",lambda:dialog.done(1))
        full_load=self.btn("加载并更新全部数据",lambda:dialog.done(2),"primary")
        buttons.addWidget(only_input);buttons.addWidget(full_load);layout.addLayout(buttons)
        return dialog.exec()==2

    def apply_scan_directory_selection(self,directory,source_name="",source_label="选择扫描目录"):
        """统一处理两个扫描目录入口，避免“全量载入”和“仅填写”行为不一致。"""
        directory=str(directory or "").strip()
        if not directory:return
        self.settings["last_input_dir"]=directory;save_app_settings(self.settings)
        if not self.confirm_scan_directory_load(directory,source_name):
            # 用户明确选择“否”时，只更新这一项；不要隐式改名称、输出目录、文件名或预览。
            self.input.setText(directory)
            self.summary.setText(f"已更新扫描目录：{directory}\n其余项目数据保持不变。")
            return
        self.new_project()
        self.input.setText(directory)
        self.name.setText(source_name.strip() if source_name.strip() else Path(directory).name)
        self.output.setText(directory)
        self.defaults()
        self.refresh_preview_output_directory()
        # 全量载入不仅更新项目字段，也立即扫描目录并将结果填入预览表，
        # 避免从“素材整理选择”返回后还要额外点击一次“加载目录数据”。
        self.load()

    def choose_input(self):
        directory=QFileDialog.getExistingDirectory(self,"选择扫描目录",self.settings.get("last_input_dir",self.input.text().strip()))
        if directory:self.apply_scan_directory_selection(directory,source_label="选择的扫描目录")
    def choose_material_organized_directory(self):
        """选择素材项目最终生成目录（解析变量后再追加项目名）作为扫描目录。"""
        available=[]
        for project_name in self.material_projects_by_recent_use():
            directory=self.material_project_output_directory(project_name)
            if directory:
                available.append((project_name,Path(directory)))
        if not available:
            QMessageBox.information(self,"暂无可选目录","请先在“素材整理与汇总预览”中建立项目，并填写项目的“整理后存放位置”或全局统一存放位置。")
            return
        dialog,layout=self.themed_dialog("选择素材整理项目目录",760,480)
        hint=QLabel("列表按最近使用的素材项目排列。选择后会把项目最终生成目录填入扫描目录：先解析路径变量，再追加项目名。例如 D:\\Flow\\{yyyy-MM-dd}-测试 + 小明，会使用 D:\\Flow\\2026-08-30-测试\\小明。目录尚未创建时仍可选择。")
        hint.setWordWrap(True);layout.addWidget(hint)
        listing=QListWidget();listing.setObjectName("material_organized_project_list");listing.setSelectionMode(QAbstractItemView.SingleSelection);listing.setAlternatingRowColors(True);listing.setSpacing(0)
        # 这是独立的嵌入式弹窗，不能依赖主页面的列表样式；在此明确铺设整行
        # 交替底色和细分隔线，长路径也能一眼辨认属于哪条项目记录。
        dark_theme=bool(self.property("host_theme_is_dark"))
        if dark_theme:
            row_color,alternate_color,border_color,text_color,selected_color=("#182435","#203149","#49647f","#eaf2fa","#345f87")
        else:
            row_color,alternate_color,border_color,text_color,selected_color=("#f9fcff","#eef5fb","#c5d5e5","#173a5e","#d9ebfa")
        listing.setStyleSheet(f'''QListWidget#material_organized_project_list {{ background:{row_color}; color:{text_color}; border:1px solid {border_color}; border-radius:7px; outline:0; }}
QListWidget#material_organized_project_list::item {{ background:{row_color}; color:{text_color}; border:0; border-bottom:1px solid {border_color}; padding:10px 12px; min-height:42px; }}
QListWidget#material_organized_project_list::item:alternate {{ background:{alternate_color}; }}
QListWidget#material_organized_project_list::item:hover,QListWidget#material_organized_project_list::item:selected {{ background:{selected_color}; color:{text_color}; border-left:3px solid {border_color}; }}''')
        for project_name,directory in available:
            item=QListWidgetItem(f"{project_name}\n{directory}")
            item.setData(Qt.UserRole,str(directory));item.setData(Qt.UserRole+1,project_name);item.setToolTip(str(directory));item.setIcon(self.folder_icon())
            listing.addItem(item)
        listing.setCurrentRow(0);listing.itemDoubleClicked.connect(lambda _item:dialog.accept());layout.addWidget(listing,1)
        buttons=QHBoxLayout();buttons.addStretch();buttons.addWidget(self.btn("取消",dialog.reject));buttons.addWidget(self.btn("使用此目录",dialog.accept,"primary"));layout.addLayout(buttons)
        if dialog.exec()!=QDialog.Accepted:return
        item=listing.currentItem()
        if not item:return
        directory=str(item.data(Qt.UserRole) or "").strip()
        if not directory:return
        project_name=str(item.data(Qt.UserRole+1) or "").strip()
        self.apply_scan_directory_selection(directory,project_name,"素材整理项目目录")
    def choose_output(self):
        directory=QFileDialog.getExistingDirectory(self,"选择输出目录",self.settings.get("last_output_dir",self.output.text().strip()))
        if directory:self.output.setText(directory); self.settings["last_output_dir"]=directory; save_app_settings(self.settings)
    def instruction_text(self):
        selected=str(self.instruction.currentData() or self.instruction.currentText() or "")
        return next((x.get("content","") for x in instructions() if x.get("name")==selected),"")
    def mark_existing_video_dialogues(self,rows,warnings):
        """标记已有同名视频的数字 TXT；预览可筛选，导出仍安全跳过。"""
        video_stems_by_folder={};existing=0
        for row in rows:
            txt_name=row.get("txt_name","");folder_path=row.get("folder_path","")
            if not txt_name or not folder_path:continue
            folder=Path(folder_path)
            if folder not in video_stems_by_folder:
                try:video_stems_by_folder[folder]={file.stem.casefold() for file in folder.iterdir() if file.is_file() and file.suffix.casefold() in VIDEO_SUFFIXES}
                except OSError:video_stems_by_folder[folder]=set()
            if Path(txt_name).stem.casefold() in video_stems_by_folder[folder]:
                row["_existing_video"]=True;existing+=1
                previous=str(row.get("status","") or "").strip()
                row["status"]="已有同名视频" if previous in ("","正常") else previous+"、已有同名视频"
        return rows,warnings,existing

    @staticmethod
    def _workspace_row_key(row):
        return (str((row or {}).get("folder_path","") or "").casefold(),str((row or {}).get("txt_name","") or "").casefold())

    def remember_workspace_pending_filter(self,*_):
        if not hasattr(self,"workspace_pending_only"):return
        self.settings["workspace_pending_only"]=bool(self.workspace_pending_only.isChecked());save_app_settings(self.settings)

    def toggle_workspace_filter_bar(self):
        bar=getattr(self,"workspace_filter_bar",None)
        if bar is not None:bar.setVisible(not bar.isVisible())

    def refresh_workspace_filter_controls(self):
        """Populate the filter menu from the current export columns without exposing internal keys."""
        if not hasattr(self,"workspace_filter_field"):return
        previous=self.workspace_filter_field.currentData();self.workspace_filter_field.blockSignals(True);self.workspace_filter_field.clear();self.workspace_filter_field.addItem("全部可见列","__all__")
        for column in self.selected_export_columns() if hasattr(self,"column_layout") else self.default_column_layout():
            self.workspace_filter_field.addItem(str(column.get("label") or column.get("key") or "列"),str(column.get("key") or ""))
        index=self.workspace_filter_field.findData(previous)
        self.workspace_filter_field.setCurrentIndex(index if index>=0 else 0);self.workspace_filter_field.blockSignals(False)
        if not hasattr(self,"workspace_filter_condition") or self.workspace_filter_condition.count():return
        for label,key in (("无","none"),("为空","empty"),("不为空","not_empty"),("文本包含","contains"),("文本不包含","not_contains"),("文本开头","starts"),("文本结尾","ends"),("文本相符","equals"),("不等于","not_equals"),("日期为","date_equals"),("日期前","date_before"),("日期后","date_after"),("大于","greater"),("大于或等于","greater_equal"),("小于","less"),("小于或等于","less_equal"),("介于（逗号分隔）","between"),("不在其中（逗号分隔）","not_in")):
            self.workspace_filter_condition.addItem(label,key)

    @staticmethod
    def workspace_filter_number(value):
        try:return float(str(value).strip().replace(",",""))
        except (TypeError,ValueError):return None

    @staticmethod
    def workspace_filter_date(value):
        text=str(value or "").strip()
        for pattern in ("%Y-%m-%d","%Y/%m/%d","%Y.%m.%d","%Y-%m-%d %H:%M:%S"):
            try:return datetime.strptime(text,pattern)
            except ValueError:pass
        return None

    def workspace_filter_text(self,row,key):
        if key=="__all__":return "\n".join(str(row.get(column.get("key"),"") or "") for column in self.selected_export_columns())
        return str(row.get(key,"") or "")

    def workspace_row_matches_filter(self,row):
        if not hasattr(self,"workspace_filter_condition"):return True
        condition=str(self.workspace_filter_condition.currentData() or "none");needle=self.workspace_filter_value.text().strip() if hasattr(self,"workspace_filter_value") else "";key=str(self.workspace_filter_field.currentData() or "__all__");value=self.workspace_filter_text(row,key);folded=value.casefold();wanted=needle.casefold()
        if condition=="none":return True
        if condition=="empty":return not value.strip()
        if condition=="not_empty":return bool(value.strip())
        if condition=="contains":return wanted in folded
        if condition=="not_contains":return wanted not in folded
        if condition=="starts":return folded.startswith(wanted)
        if condition=="ends":return folded.endswith(wanted)
        if condition=="equals":return folded==wanted
        if condition=="not_equals":return folded!=wanted
        if condition=="not_in":return folded not in {part.strip().casefold() for part in needle.split(",") if part.strip()}
        if condition in {"date_equals","date_before","date_after"}:
            current,target=self.workspace_filter_date(value),self.workspace_filter_date(needle)
            if not current or not target:return False
            return current.date()==target.date() if condition=="date_equals" else (current<target if condition=="date_before" else current>target)
        number,target=self.workspace_filter_number(value),self.workspace_filter_number(needle)
        if condition=="between":
            parts=[self.workspace_filter_number(part) for part in needle.split(",",1)]
            return number is not None and len(parts)==2 and None not in parts and min(parts)<=number<=max(parts)
        if number is None or target is None:return False
        return {"greater":number>target,"greater_equal":number>=target,"less":number<target,"less_equal":number<=target}.get(condition,False)

    def clear_workspace_filter(self):
        if hasattr(self,"workspace_filter_field"):self.workspace_filter_field.setCurrentIndex(0)
        if hasattr(self,"workspace_filter_condition"):self.workspace_filter_condition.setCurrentIndex(0)
        if hasattr(self,"workspace_filter_value"):self.workspace_filter_value.clear()
        self.apply_workspace_pending_filter()

    def workspace_set_selection(self,selected=None,invert=False):
        if not hasattr(self,"table"):return
        self.collect();self._filling_workspace_table=True;self.table.blockSignals(True)
        try:
            for row_index,row in enumerate(self.rows):
                value=(not bool(row.get("_export_selected",False))) if invert else bool(selected)
                row["_export_selected"]=value;item=self.table.item(row_index,1)
                if item:item.setCheckState(Qt.Checked if value else Qt.Unchecked)
        finally:self.table.blockSignals(False);self._filling_workspace_table=False
        self._sync_workspace_all_rows_from_visible();self.update_workspace_selection_summary()

    def workspace_select_all(self):self.workspace_set_selection(True)
    def workspace_clear_selection(self):self.workspace_set_selection(False)
    def workspace_invert_selection(self):self.workspace_set_selection(invert=True)

    def update_workspace_selection_summary(self):
        if not hasattr(self,"summary"):return
        visible=len(getattr(self,"rows",[]) or []);selected=sum(1 for row in getattr(self,"rows",[]) if row.get("_export_selected"));total=len(getattr(self,"_workspace_all_rows",self.rows) or [])
        self.summary.setText(f"筛选结果：显示 {visible}/{total} 条；已勾选 {selected} 条，导出时仅处理已勾选记录。")

    def _sync_workspace_all_rows_from_visible(self):
        """把当前表格的人工编辑写回完整扫描缓存，筛选切换不会吞掉已编辑内容。"""
        all_rows=getattr(self,"_workspace_all_rows",None)
        if not isinstance(all_rows,list):return
        by_key={self._workspace_row_key(row):index for index,row in enumerate(all_rows)}
        for row in self.rows:
            key=self._workspace_row_key(row)
            if key in by_key:all_rows[by_key[key]]=dict(row)
            else:all_rows.append(dict(row));by_key[key]=len(all_rows)-1

    def apply_workspace_pending_filter(self,*_,refresh=True):
        """按同名成品视频过滤预览；仅改变可见行，不改变完整扫描缓存。"""
        if not hasattr(self,"table"):return
        if refresh and not getattr(self,"_workspace_filter_switching",False):
            self.collect();self._sync_workspace_all_rows_from_visible()
        all_rows=list(getattr(self,"_workspace_all_rows",self.rows) or [])
        pending_only=bool(getattr(self,"workspace_pending_only",None) and self.workspace_pending_only.isChecked())
        self._workspace_filter_switching=True
        try:
            self.rows=[dict(row) for row in all_rows if (not pending_only or not bool(row.get("_existing_video"))) and self.workspace_row_matches_filter(row)]
            if refresh:self.fill_table()
        finally:self._workspace_filter_switching=False
        if refresh:self.update_workspace_selection_summary()

    def scan_segment_bundle_directory(self,root_dir,instruction,encoding="utf-8",progress=None,image_mode="segment_image"):
        """扫描分段资料包，并按用户选择关联“素材原图”或“分段图片”。"""
        root=Path(root_dir)
        if not root.is_dir():raise ValueError(f"扫描目录不存在或不是文件夹：{root}")
        folders=[root]+[path for path in root.rglob("*") if path.is_dir()]
        rows=[];warnings=[];numeric=re.compile(r"^(\d+)\.txt$",re.IGNORECASE)
        for position,folder in enumerate(folders,1):
            if progress:progress(position,len(folders))
            try:children=[path for path in folder.iterdir() if path.is_file()]
            except OSError as error:warnings.append(f"{folder}: 无法读取（{error}）");continue
            numbered=sorted(((int(match.group(1)),path) for path in children if (match:=numeric.fullmatch(path.name))),key=lambda item:(item[0],item[1].name.casefold()))
            if not numbered:continue
            images=sorted((path for path in children if path.suffix.casefold() in IMAGE_SUFFIXES),key=lambda path:path.name.casefold())
            numbers=[number for number,_path in numbered];gaps=[number for number in range(1,max(numbers)+1) if number not in set(numbers)] if numbers else []
            if gaps:warnings.append(f"{folder}: 缺少台词编号 {', '.join(map(str,gaps))}")
            if not images:warnings.append(f"{folder}: 缺少图片，无法关联分段文案与生成词")
            for number,dialogue_file in numbered:
                try:dialogue=dialogue_file.read_text(encoding=encoding).strip()
                except (OSError,UnicodeError) as error:warnings.append(f"{dialogue_file}: 无法读取（{error}）");dialogue=""
                image=None;prompt_file=None;status=[]
                # 单段子文件夹兼容：只有一个数字文案、一个图片，且图片同名 TXT
                # 存在时，图片同名 TXT 就是该唯一分段的生成词。例如 1.txt、
                # 封面-01.png、封面-01.txt。多分段资料仍严格使用原有编号规则。
                single_segment_sidecar=(len(numbered)==1 and len(images)==1 and (folder/f"{images[0].stem}.txt").is_file())
                if single_segment_sidecar:
                    image=images[0];prompt_file=folder/f"{image.stem}.txt";status.append("单段资料包：已按图片同名读取生成词")
                elif image_mode=="source_image":
                    # 原图模式：仅把“图片名-编号.txt”存在的图片认作素材原图。
                    # 不能用“末尾是否数字”判断，因为项目原图本身也常以 -11 结尾。
                    source_pairs=[(candidate,folder/f"{candidate.stem}-{number}.txt") for candidate in images if (folder/f"{candidate.stem}-{number}.txt").is_file()]
                    if len(source_pairs)==1:image,prompt_file=source_pairs[0]
                    elif len(source_pairs)>1:status.append("多个素材原图都存在同编号生成词，无法唯一关联")
                    elif len(images)==1:image=images[0];status.append("缺少对应生成词")
                    else:status.append("无法根据“素材图片名-编号.txt”确认素材原图")
                else:
                    # 分段图片模式：1.txt 必须对应 图片名-1.jpg；同名 .txt 就是生成词。
                    segment_images=[candidate for candidate in images if candidate.stem.endswith(f"-{number}")]
                    matched=[candidate for candidate in segment_images if (folder/f"{candidate.stem}.txt").is_file()]
                    if len(matched)==1:image=matched[0];prompt_file=folder/f"{image.stem}.txt"
                    elif len(matched)>1:status.append("多个分段图片都存在同编号生成词，无法唯一关联")
                    elif len(segment_images)==1:image=segment_images[0];status.append("缺少对应生成词")
                    elif not images:status.append("缺少图片")
                    else:status.append("缺少对应的“图片名-编号”分段图片")
                prompt=""
                if prompt_file:
                    try:prompt=prompt_file.read_text(encoding=encoding).strip()
                    except (OSError,UnicodeError) as error:warnings.append(f"{prompt_file}: 无法读取（{error}）");status.append("生成词无法读取")
                    if not prompt:status.append("生成词为空")
                if gaps:status.insert(0,"编号不连续")
                if not dialogue:status.append("空台词")
                rows.append({"folder_name":folder.name,"folder_path":str(folder.resolve()),"txt_name":dialogue_file.name,"image_name":image.name if image else "","image_path":str(image.resolve()) if image else "","dialogue":dialogue,"generated_prompt":prompt,"generated_prompt_name":prompt_file.name if prompt_file else "","estimated_speech_duration":self.estimate_dialogue_duration(dialogue),"command":f"{instruction}{dialogue}","status":"、".join(dict.fromkeys(status)) if status else "正常"})
        return rows,warnings

    def load(self):
        self.defaults(); path=self.input.text().strip()
        if not path:QMessageBox.warning(self,"缺少扫描目录","请选择或输入扫描目录。");return
        if self.rows and QMessageBox.question(self,"重新加载目录","重新加载将替换预览中的未导出修改，是否继续？")!=QMessageBox.Yes:return
        self.progress.setValue(0)
        try:
            def tick(a,b):self.progress.setValue(a*100//max(b,1)); QApplication.processEvents()
            bundle_mode=bool(hasattr(self,"scan_mode") and self.scan_mode.currentData()=="segment_bundle")
            bundle_image_mode=self.bundle_image_mode.currentData() if hasattr(self,"bundle_image_mode") else "segment_image"
            rows,warnings=(self.scan_segment_bundle_directory(Path(path),self.instruction_text(),self.encoding.currentText(),tick,bundle_image_mode) if bundle_mode else scan(Path(path),self.instruction_text(),self.encoding.currentText(),tick));
            for row in rows:row["estimated_speech_duration"]=self.estimate_dialogue_duration(row.get("dialogue", ""))
            self._workspace_all_rows,self.warnings,skipped=self.mark_existing_video_dialogues(rows,warnings)
            for row in self._workspace_all_rows:row.setdefault("_export_selected",True)
            self.rows=[dict(row) for row in self._workspace_all_rows];self.apply_workspace_pending_filter(refresh=False)
            # 若“筛选待制作”把本次结果全部隐藏，表格会像“没有加载”一样空白。
            # 扫描成功的资料必须可见：自动显示全部记录，并持久化该可见状态。
            auto_show_all=bool(self._workspace_all_rows and not self.rows and self.workspace_pending_only.isChecked())
            if auto_show_all:
                self.workspace_pending_only.blockSignals(True);self.workspace_pending_only.setChecked(False);self.workspace_pending_only.blockSignals(False)
                self.settings["workspace_pending_only"]=False;save_app_settings(self.settings)
                self.apply_workspace_pending_filter(refresh=False)
        except Exception as error:LOGGER.exception("Qt 扫描失败"); QMessageBox.critical(self,"加载失败",str(error));return
        self.fill_table(); mode_note=("分段资料包模式：已按“图片名-编号.jpg + 图片名-编号.txt”读取。" if 'bundle_mode' in locals() and bundle_mode and bundle_image_mode=="segment_image" else "分段资料包模式：已按“素材图片名.jpg + 素材图片名-编号.txt”读取。" if 'bundle_mode' in locals() and bundle_mode else "");self.summary.setText(f"已加载 {len(self.rows)}/{len(self._workspace_all_rows)} 条记录，{len(self.warnings)} 条检查提示。"+("原先“筛选待制作”会隐藏全部结果，现已自动显示全部记录。" if 'auto_show_all' in locals() and auto_show_all else (f"其中 {skipped} 条已有同名视频；{'当前已按待制作筛选隐藏。' if self.workspace_pending_only.isChecked() else '可勾选“筛选待制作”隐藏。'}" if skipped else "可编辑后导出。"))+("\n"+mode_note if mode_note else "")); add_history({"project":self.name.text(),"operation":"加载并更新项目数据","result":self.summary.text()});self.touch_recent_project()
    def fill_table(self):
        # 预览表头始终以系统表头配置为准：保存设置、重新加载、打开项目和重启后都会同步。
        # 朗读时长是由台词推导的显示值，不保留旧算法留下的缓存；每次刷新表格
        # 都据当前台词重新计算，升级后已打开的项目也会立即显示新口径。
        for row in self.rows:
            row["estimated_speech_duration"]=self.estimate_dialogue_duration(row.get("dialogue", ""))
        self.column_layout=self.system_column_layout();columns=self.selected_export_columns();self._filling_workspace_table=True;self.table.blockSignals(True)
        try:
            # 预览保持最少空白行时，setRowCount 不会删除仍在范围内的旧单元格。
            # 每次载入都先清空，避免较少的新结果与旧预览混在同一张表里。
            self.refresh_workspace_filter_controls();self.table.clearContents();self.table.setColumnCount(len(columns)+2);self.table.setHorizontalHeaderLabels(["图片预览","勾选"]+[column["label"] for column in columns]);self.table.setColumnWidth(0,72);self.table.setColumnWidth(1,54);self.table.setRowCount(max(len(self.rows),int(getattr(self.table,"minimum_row_count",0))))
            for r,row in enumerate(self.rows):
                self.workspace_render_image_preview(r,row)
                checked=QTableWidgetItem("");checked.setFlags(checked.flags() & ~Qt.ItemIsEditable);checked.setCheckState(Qt.Checked if row.get("_export_selected",True) else Qt.Unchecked);checked.setToolTip("勾选后才会参与导出");self.table.setItem(r,1,checked)
                for c,column in enumerate(columns,2):self.table.setItem(r,c,QTableWidgetItem(str(row.get(column["key"],""))))
            for r in range(len(self.rows),self.table.rowCount()):self.workspace_render_image_preview(r,{})
        finally:
            self.table.blockSignals(False);self._filling_workspace_table=False
        self.apply_workspace_table_column_sizes(columns)
        if hasattr(self.table,"reset_history"):self.table.reset_history()

    def apply_workspace_table_column_sizes(self,columns):
        """仅为未手动调整的列估算初始宽度，绝不覆盖用户拖拽后的结果。"""
        header=self.table.horizontalHeader();header.setStretchLastSection(False)
        self._workspace_table_column_keys=("_preview","_selected")+tuple(str(column.get("key") or "") for column in columns)
        saved=self.settings.get("workspace_table_column_widths",{}) if isinstance(getattr(self,"settings",None),dict) else {}
        saved={str(key):int(value) for key,value in (saved or {}).items() if str(key) and isinstance(value,(int,float)) and 48<=int(value)<=2400}
        self._applying_workspace_column_sizes=True
        try:
            header.setSectionResizeMode(0,QHeaderView.Fixed);self.table.setColumnWidth(0,72);header.setSectionResizeMode(1,QHeaderView.Fixed);self.table.setColumnWidth(1,54)
            for index,column in enumerate(columns,2):
                key=str(column.get("key") or "")
                header.setSectionResizeMode(index,QHeaderView.Interactive)
                if key in saved:
                    self.table.setColumnWidth(index,saved[key]);continue
                # 路径可能很长，初次加载按内容估算并限制上限；随后始终允许拖动。
                header.setSectionResizeMode(index,QHeaderView.ResizeToContents);self.table.resizeColumnToContents(index)
                default_width=min(300,max(95,self.table.columnWidth(index)))
                if key=="command":default_width=max(460,default_width)
                self.table.setColumnWidth(index,default_width);header.setSectionResizeMode(index,QHeaderView.Interactive)
        finally:
            self._applying_workspace_column_sizes=False

    def remember_workspace_table_column_width(self,index,old_width,new_width):
        """记录用户在项目工作台表头上的拖拽宽度，刷新/重启后仍按该宽度显示。"""
        if getattr(self,"_applying_workspace_column_sizes",False) or index<2:return
        keys=getattr(self,"_workspace_table_column_keys",())
        if index>=len(keys):return
        key=str(keys[index] or "")
        if not key:return
        widths=self.settings.get("workspace_table_column_widths",{}) if isinstance(getattr(self,"settings",None),dict) else {}
        widths=dict(widths) if isinstance(widths,dict) else {}
        widths[key]=max(48,min(2400,int(new_width)))
        self.settings["workspace_table_column_widths"]=widths
        timer=getattr(self,"_workspace_column_width_save_timer",None)
        if timer is None:
            timer=QTimer(self);timer.setSingleShot(True);timer.timeout.connect(lambda:save_app_settings(self.settings));self._workspace_column_width_save_timer=timer
        timer.start(350)

    def workspace_preview_image_path(self,row):
        """工作台预览只使用扫描时已确认的完整图片路径，绝不猜测或遍历目录。"""
        path=str((row or {}).get("image_path","") or "").strip()
        candidate=Path(path) if path else None
        return str(candidate) if candidate and candidate.is_file() and candidate.suffix.casefold() in IMAGE_SUFFIXES else ""

    def workspace_render_image_preview(self,row,record):
        """把原比例缩略图放入紧凑首列；缺图时保留空白，不显示提示文字。"""
        path=self.workspace_preview_image_path(record)
        item=QTableWidgetItem("");item.setFlags(item.flags() & ~Qt.ItemIsEditable);item.setToolTip(path or "未找到图片")
        self.table.setItem(row,0,item)
        thumbnail=ReviewImageLabel();thumbnail.image_path=path;thumbnail.setAlignment(Qt.AlignCenter);thumbnail.setToolTip((path or "未找到图片")+"\n双击：在软件内放大");thumbnail.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,True)
        row_height=max(38,self.table.fontMetrics().lineSpacing()+14)
        if path:
            pixmap=QPixmap(path)
            if not pixmap.isNull():
                scaled=pixmap.scaled(64,56,Qt.KeepAspectRatio,Qt.SmoothTransformation)
                thumbnail.setPixmap(scaled)
                # 竖图略高、横图更紧凑；始终限制在较低的行高，给台词保留空间。
                row_height=max(row_height,min(64,scaled.height()+8))
        self.table.setCellWidget(row,0,thumbnail);self.table.setRowHeight(row,row_height)

    def workspace_open_image_preview(self,row,column):
        """工作台缩略图由表格直接接管双击，避免 QLabel 被 Qt 容器截获事件。"""
        if int(column)!=0:return
        try:
            path=self.workspace_preview_image_path(self.rows[int(row)] if 0<=int(row)<len(self.rows) else {})
            if path:show_internal_image_preview(self,path)
            else:QtMessageBox.information(self,"图片预览","当前行没有可打开的有效图片路径。")
        except Exception as error:
            LOGGER.exception("打开工作台图片预览失败");QtMessageBox.warning(self,"图片预览",str(error))

    def sync_workspace_rows_from_table(self,*_):
        """增强表格的编辑、粘贴、填充和撤销完成后，同步回工作台草稿数据。"""
        if getattr(self,"_filling_workspace_table",False) or not hasattr(self,"table"):
            return
        self.collect()
    def collect(self):
        result=[]
        columns=self.selected_export_columns()
        for r in range(self.table.rowCount()):
            if r>=len(self.rows) and not any((self.table.item(r,c).text().strip() if self.table.item(r,c) else "") for c in range(2,self.table.columnCount())):continue
            row=dict(self.rows[r]) if r<len(self.rows) else {}
            checked=self.table.item(r,1);row["_export_selected"]=bool(checked and checked.checkState()==Qt.Checked)
            for c,column in enumerate(columns,2):row[column["key"]]=self.table.item(r,c).text() if self.table.item(r,c) else ""
            result.append(row)
        self.rows=result
        if not getattr(self,"_workspace_filter_switching",False):self._sync_workspace_all_rows_from_visible()
        return result
    def add_row(self):
        self.collect();self.table.add_rows();row_index=max(0,self.table.rowCount()-1);self.workspace_render_image_preview(row_index,{});checked=QTableWidgetItem("");checked.setFlags(checked.flags() & ~Qt.ItemIsEditable);checked.setCheckState(Qt.Checked);checked.setToolTip("勾选后才会参与导出");self.table.setItem(row_index,1,checked);self.collect();self.table.setCurrentCell(row_index,2)
    def delete_rows(self):
        if not self.table.selectedIndexes():return
        # QTableWidget 删除后会把后续视觉行上移。若仍拿旧 self.rows 的同一索引
        # collect()，第 N 行就会错误继承“被删行”的 image_path，造成导出图片
        # 漏复制、错复制。先以当前表格为准同步，再同步删除两份行模型，最后才删 UI 行。
        self.collect()
        deleted_indexes={index.row() for index in self.table.selectedIndexes() if 0<=index.row()<len(self.rows)}
        if not deleted_indexes:return
        deleted_keys={self._workspace_row_key(self.rows[index]) for index in deleted_indexes}
        self.rows=[row for index,row in enumerate(self.rows) if index not in deleted_indexes]
        if isinstance(getattr(self,"_workspace_all_rows",None),list):
            self._workspace_all_rows=[row for row in self._workspace_all_rows if self._workspace_row_key(row) not in deleted_keys]
        self.table.delete_selected_rows();self.collect()
    def show_warnings(self):QMessageBox.information(self,"检查提示","未发现检查问题。" if not self.warnings else "\n".join("• "+x for x in self.warnings))
    def export_record_data(self,rows):
        columns=self.selected_export_columns() if hasattr(self,"column_layout") else self.default_column_layout()
        return {"headers":[column["label"] for column in columns],"rows":[[str(row.get(column["key"],"")) for column in columns] for row in rows]}
    def remember_export(self,mode,name,location,rows):
        # 项目工作台的每个页签都有独立控制器。导出时必须先合并磁盘中最新记录，
        # 否则页签 A、B 各自拿着旧 settings 保存，会把彼此的临时项目导出记录覆盖掉。
        latest=app_settings()
        if isinstance(latest,dict):self.settings.update(latest)
        records=self.settings.get("export_records",[])
        if not isinstance(records,list):records=[]
        records.insert(0,{"time":datetime.now().strftime("%Y-%m-%d %H:%M:%S"),"mode":mode,"name":name,"location":str(location),"data":self.export_record_data(rows)})
        path=Path(location);actual_directory=path.parent if path.suffix else path
        project_key=self.export_project_key();project_directories=self.settings.get("project_export_directories",{});project_directories=project_directories if isinstance(project_directories,dict) else {}
        record={"directory":str(actual_directory),"mode":mode,"time":datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        project_directories[project_key]=record;self.settings["project_export_directories"]=project_directories;self.settings["last_export_directory"]=record;self.settings["export_records"]=records[:20];save_app_settings(self.settings)
        # 工作台导出的表格也进入“查看表格”的最近文件列表，方便直接再次打开编辑。
        if path.is_file() and path.suffix.casefold() in {".xlsx", ".csv", ".tsv"}:
            self.remember_viewer_file(path, f"工作台导出：{mode}")
    def export_project_key(self):
        if isinstance(self.active,dict) and self.active.get("id"):return "project:"+str(self.active["id"])
        return "workspace:"+self.name.text().strip()+"|"+(self.input.text().strip() or getattr(self,"_inactive_output_directory", ""))
    def last_project_export_record(self):
        records=self.settings.get("project_export_directories",{});record=records.get(self.export_project_key(),{}) if isinstance(records,dict) else {}
        return record if isinstance(record,dict) else {}
    def refresh_export_records(self):
        if not hasattr(self,"export_records"):return
        latest=app_settings()
        if isinstance(latest,dict):self.settings.update(latest)
        self.export_records.setRowCount(0);records=self.settings.get("export_records",[])
        for row,record in enumerate(records if isinstance(records,list) else []):
            self.export_records.insertRow(row)
            for column,key in enumerate(("time","mode","name","location")):
                item=QTableWidgetItem(str(record.get(key,"")));item.setData(Qt.UserRole,row);self.export_records.setItem(row,column,item)
    def viewer_temp_directory(self):
        """返回可写的表格快照目录；配置目录失效时不能阻断主界面启动。"""
        configured=Path(self.settings.get("temp_data_dir",str(DATA_DIR/"temporary")))/"table-viewer"
        # 用户可能曾以管理员身份运行，或迁移后保留了无写入权限的目录。依次
        # 验证配置路径、用户主目录回退路径和系统临时回退路径，确保表格页面
        # 不会因创建快照目录失败而让整个应用无法启动。
        candidates=(
            configured,
            Path.home()/".video-task-hub"/"temporary"/"table-viewer",
            Path(tempfile.gettempdir())/"video-task-hub"/"table-viewer",
        )
        last_error=None
        for directory in candidates:
            try:
                directory.mkdir(parents=True,exist_ok=True)
                probe=directory/f".write-check-{os.getpid()}"
                probe.touch(exist_ok=False)
                probe.unlink()
                if directory != configured:
                    LOGGER.warning("表格快照目录不可写，已临时使用回退目录：%s",directory)
                return directory
            except OSError as error:
                last_error=error
                LOGGER.warning("表格快照目录不可用：%s（%s）",directory,error)
        # 正常情况下前两个回退路径一定可用；保留明确错误以便启动保护弹窗提示。
        raise OSError(f"无法创建可写的表格快照目录：{last_error}")
    def ensure_cross_platform_system_paths(self):
        """为 Windows、macOS、Linux 首次启动建立稳定的用户级临时资料目录。"""
        changed=False
        if not str(self.settings.get("temp_data_dir","") or "").strip():
            self.settings["temp_data_dir"]=str(DATA_DIR/"temporary");changed=True
        if not str(self.settings.get("log_dir","") or "").strip():
            self.settings["log_dir"]=str(LOG_DIR);changed=True
        try:Path(self.settings["temp_data_dir"]).mkdir(parents=True,exist_ok=True)
        except OSError:LOGGER.exception("无法创建临时资料目录：%s",self.settings.get("temp_data_dir"))
        if changed:save_app_settings(self.settings)
    def repair_unsafe_temp_directory(self):
        """将系统随机 Temp 子目录中的快照迁移到稳定的用户配置目录。"""
        configured=str(self.settings.get("temp_data_dir","") or "").strip()
        if not configured:return
        try:
            configured_path=Path(configured).resolve();system_temp=Path(tempfile.gettempdir()).resolve()
            is_system_temp=configured_path==system_temp or system_temp in configured_path.parents
        except OSError:is_system_temp=False
        if not is_system_temp:return
        stable_directory=DATA_DIR/"temporary";moved=self.migrate_viewer_temp_records(stable_directory)
        self.settings["temp_data_dir"]=str(stable_directory);save_app_settings(self.settings);LOGGER.warning("检测到不稳定的系统临时目录，已迁移 %s 份表格快照到 %s",moved,stable_directory)
    def viewer_table_data(self):
        preview_column=1 if getattr(self,"_viewer_preview_column",False) else 0
        headers=list(getattr(self,"_viewer_source_headers",[]) or [])
        if len(headers)!=self.viewer_table.columnCount()-preview_column:
            headers=[self.viewer_table.horizontalHeaderItem(column+preview_column).text() if self.viewer_table.horizontalHeaderItem(column+preview_column) else f"列 {column+1}" for column in range(self.viewer_table.columnCount()-preview_column)]
        rows=[]
        for row in range(self.viewer_table.rowCount()):
            values=[]
            for column in range(preview_column,self.viewer_table.columnCount()):
                item=self.viewer_table.item(row,column)
                values.append(item.data(Qt.UserRole+11) if item and item.data(Qt.UserRole+11) else item.text() if item else "")
            rows.append(values)
        return headers,rows

    def viewer_image_columns(self):
        """从常见中文/英文表头定位图片名称和完整路径列（表格内索引已包含预览列）。"""
        headers=list(getattr(self,"_viewer_source_headers",[]) or [])
        name_columns=[];path_columns=[]
        for source_column,header in enumerate(headers):
            key=str(header).strip().casefold().replace(" ","").replace("_","")
            table_column=source_column+1 if getattr(self,"_viewer_preview_column",False) else source_column
            if any(token in key for token in ("图片完整路径","图片路径","imagepath","imagefile","imageurl")):path_columns.append(table_column)
            if any(token in key for token in ("图片名","图片名称","imagename","imagefilename","filename")):name_columns.append(table_column)
        return name_columns,path_columns

    def viewer_image_candidates(self,row,name_columns,path_columns):
        names=[];direct="";base=Path(getattr(self,"_viewer_file_path","") or ".").parent
        for column in path_columns:
            item=self.viewer_table.item(row,column);value=item.text().strip() if item else ""
            if not value:continue
            candidate=Path(value)
            if not candidate.is_absolute():candidate=base/candidate
            if candidate.is_file() and candidate.suffix.casefold() in IMAGE_SUFFIXES:direct=str(candidate);break
            names.append(Path(value).name)
        for column in name_columns:
            item=self.viewer_table.item(row,column);value=item.text().strip() if item else ""
            if value:names.append(Path(value).name)
        return direct,[name for name in names if name]

    def viewer_standard_row_height(self):
        """查看表格默认显示约五行文字，兼顾换行审核与一次可见的行数。"""
        if not hasattr(self,"viewer_table"):return 108
        return max(96,self.viewer_table.fontMetrics().lineSpacing()*5+12)

    def viewer_render_image_preview(self,row,path=""):
        # 预览列只显示图片本身，不再叠加“已匹配/未匹配”等文字；匹配信息仍在
        # 下方状态栏和鼠标提示中可查看，避免文字遮挡图片审核。
        item=QTableWidgetItem("");item.setFlags(item.flags() & ~Qt.ItemIsEditable);item.setToolTip(path or "未找到对应图片");self.viewer_table.setItem(row,0,item)
        label=ReviewImageLabel();label.image_path=path;label.setAlignment(Qt.AlignCenter);label.setMinimumSize(96,96);label.setToolTip((path or "未找到对应图片")+"\n双击：在软件内放大");label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,True)
        if path:
            pixmap=QPixmap(path)
            if not pixmap.isNull():label.setPixmap(pixmap.scaled(96,96,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        self.viewer_table.setCellWidget(row,0,label);self.viewer_table.setRowHeight(row,self.viewer_standard_row_height())

    def match_viewer_images(self,directory=None):
        """递归建立图片名称索引；仅以文件名精确匹配，绝不按相近名称猜测。"""
        if not hasattr(self,"viewer_table") or not getattr(self,"_viewer_preview_column",False):return 0,[],False
        name_columns,path_columns=self.viewer_image_columns();has_reference=bool(name_columns or path_columns)
        if not has_reference:
            self.viewer_image_status.setText("图片审核：未检测到“图片名”或“图片路径/图片完整路径”表头，无法匹配图片预览。")
            return 0,[],False
        image_by_name={};image_by_stem={}
        root=Path(directory) if directory else None
        if root and root.is_dir():
            try:
                for path in root.rglob("*"):
                    if path.is_file() and path.suffix.casefold() in IMAGE_SUFFIXES:
                        image_by_name.setdefault(path.name.casefold(),str(path))
                        image_by_stem.setdefault(path.stem.casefold(),str(path))
            except OSError as error:LOGGER.warning("递归扫描审核图片目录失败：%s",error)
        matched=0;unmatched=[];self._viewer_image_paths={}
        for row in range(self.viewer_table.rowCount()):
            direct,names=self.viewer_image_candidates(row,name_columns,path_columns);found=direct
            if not found:
                for name in names:
                    found=image_by_name.get(name.casefold())
                    if not found and not Path(name).suffix:found=image_by_stem.get(Path(name).stem.casefold())
                    if found:break
            if found:matched+=1;self._viewer_image_paths[row]=found
            elif names:unmatched.append(names[0])
            self.viewer_render_image_preview(row,found or "")
        location=f"目录：{root}" if root else "仅使用表格中的图片完整路径"
        self.viewer_image_status.setText(f"图片审核：已匹配 {matched}/{self.viewer_table.rowCount()} 条；未匹配 {len(unmatched)} 条。{location}")
        return matched,unmatched,True

    def choose_viewer_image_directory(self):
        if not hasattr(self,"viewer_table") or self.viewer_table.rowCount()==0:
            QMessageBox.information(self,"没有表格数据","请先打开表格文件，再选择图片所在目录进行匹配。 ");return
        start=self.settings.get("last_viewer_image_dir",self.settings.get("last_table_dir","") or "")
        directory=QFileDialog.getExistingDirectory(self,"选择图片所在目录（将递归匹配）",start)
        if not directory:return
        self.settings["last_viewer_image_dir"]=directory;save_app_settings(self.settings);matched,unmatched,valid=self.match_viewer_images(directory)
        if valid and unmatched:
            sample="\n".join(unmatched[:12]);more=f"\n…另有 {len(unmatched)-12} 条" if len(unmatched)>12 else ""
            QMessageBox.warning(self,"存在图片名称不匹配",f"已匹配 {matched} 条，但以下图片名称未在所选目录及子目录中找到：\n{sample}{more}\n\n请确认表格中的图片名与实际文件名（含扩展名）一致，或重新选择正确图片目录。")
        elif valid:QMessageBox.information(self,"图片匹配完成",f"已递归匹配 {matched} 条图片，并显示在表格第一列。")
    def remember_viewer_file(self,path,source="外部打开"):
        """记录实际表格文件，不复制内容到临时目录，避免记录与外部文件脱节。"""
        path=Path(path)
        if path.suffix.casefold() not in {".xlsx",".csv",".tsv"}:return
        try:location=str(path.resolve())
        except OSError:location=str(path.absolute())
        records=self.settings.get("viewer_file_records",[]);records=records if isinstance(records,list) else []
        records=[record for record in records if str(record.get("file","")).casefold()!=location.casefold()]
        record={"time":datetime.now().strftime("%Y-%m-%d %H:%M:%S"),"source":str(source),"name":path.name,"file":location}
        records.insert(0,record);self.settings["viewer_file_records"]=records[:100];save_app_settings(self.settings);self._viewer_record=record;self.refresh_viewer_snapshots()
    def refresh_viewer_snapshots(self):
        if not hasattr(self,"viewer_snapshots"):return
        self.viewer_snapshots.setRowCount(0);records=self.settings.get("viewer_file_records",[])
        for row,record in enumerate(records if isinstance(records,list) else []):
            self.viewer_snapshots.insertRow(row)
            for column,key in enumerate(("time","source","name","file")):
                item=QTableWidgetItem(str(record.get(key,"")));item.setData(Qt.UserRole,row);item.setFlags(item.flags() & ~Qt.ItemIsEditable);self.viewer_snapshots.setItem(row,column,item)
    def clear_viewer_snapshots(self):
        records=self.settings.get("viewer_file_records",[]);records=records if isinstance(records,list) else []
        if not records:
            self.refresh_viewer_snapshots();QMessageBox.information(self,"没有表格记录","当前没有可清除的最近表格文件记录。");return
        if QMessageBox.question(self,"清除表格记录",f"将清除 {len(records)} 条最近打开或导出的表格文件记录。\n\n不会删除任何 Excel、CSV、TSV 文件，也不会关闭当前正在编辑的表格。是否继续？")!=QMessageBox.Yes:return
        self.settings["viewer_file_records"]=[];save_app_settings(self.settings);self._viewer_record={};self.refresh_viewer_snapshots();QMessageBox.information(self,"表格记录已清除",f"已清除 {len(records)} 条表格文件记录。")
    def fit_viewer_columns(self):
        self.viewer_table.resizeColumnsToContents()
        if getattr(self,"_viewer_preview_column",False):self.viewer_table.setColumnWidth(0,112)
        start=1 if getattr(self,"_viewer_preview_column",False) else 0
        for column in range(start,self.viewer_table.columnCount()):self.viewer_table.setColumnWidth(column,max(110,min(420,self.viewer_table.columnWidth(column))))
    def show_viewer_cell_detail(self):
        if hasattr(self,"viewer_detail") and not self.viewer_detail.isReadOnly():return
        item=self.viewer_table.currentItem()
        if not item:self.viewer_detail.clear();self.viewer_detail_title.setText("当前单元格完整内容");return
        if getattr(self,"_viewer_preview_column",False) and item.column()==0:
            path=getattr(self,"_viewer_image_paths",{}).get(item.row(),"");self.viewer_detail_title.setText(f"图片预览（第 {item.row()+1} 行）");self.viewer_detail.setPlainText(path or "未找到对应图片。可点击“匹配图片目录”选择图片所在目录后递归匹配。");return
        header=self.viewer_table.horizontalHeaderItem(item.column());name=header.text() if header else f"第 {item.column()+1} 列";self.viewer_detail_title.setText(f"当前单元格完整内容：{name}（第 {item.row()+1} 行）");self.viewer_detail.setPlainText(item.text())
    def copy_viewer_detail(self):QGuiApplication.clipboard().setText(self.viewer_detail.toPlainText())
    def edit_viewer_detail(self):
        """直接在下方完整内容区编辑；再次点击同一按钮才提交，避免误写表格。"""
        if not hasattr(self,"viewer_detail") or not hasattr(self,"viewer_table"):return
        if not self.viewer_detail.isReadOnly():
            target=getattr(self,"_viewer_detail_edit_target",None)
            if target is None:return
            row,column,item=target
            if item is not None and item is self.viewer_table.item(row,column):item.setText(self.viewer_detail.toPlainText())
            self.viewer_detail.setReadOnly(True);self._viewer_detail_edit_target=None;self.viewer_detail_edit_button.setText("编辑内容");self.show_viewer_cell_detail();return
        item=self.viewer_table.currentItem()
        if not item:QMessageBox.information(self,"请选择单元格","请先点击需要编辑的单元格。");return
        if getattr(self,"_viewer_preview_column",False) and item.column()==0:
            QMessageBox.information(self,"图片预览列","图片预览列仅用于审核，不能编辑。请编辑图片名称或图片路径列。");return
        self._viewer_detail_edit_target=(item.row(),item.column(),item);self.viewer_detail.setReadOnly(False);self.viewer_detail.setFocus();self.viewer_detail_edit_button.setText("保存内容")
    def update_viewer_file_status(self):
        if not hasattr(self,"viewer_file_status"):return
        path=getattr(self,"_viewer_file_path",None)
        if path:
            self.viewer_file_status.setText(f"当前文件：{path}"+("  （有未保存修改）" if getattr(self,"_viewer_dirty",False) else "  （已保存）"))
        else:self.viewer_file_status.setText("当前为内存表格；请使用“另存为”写入 Excel、CSV 或 TSV 文件。")
    def edit_current_viewer_cell(self):
        item=self.viewer_table.currentItem()
        if not item:QMessageBox.information(self,"请选择单元格","请先点击需要查看或编辑的单元格。");return
        if getattr(self,"_viewer_preview_column",False) and item.column()==0:
            QMessageBox.information(self,"图片预览列","图片预览列仅用于审核，不会写入外部表格。请编辑图片名称或图片路径列后，再点击“匹配图片目录”。");return
        dialog,layout=self.themed_dialog("编辑单元格内容",760,540);hint=QLabel("此处可编辑较长内容。修改会保留在当前表格中；只有点击页面顶部的“保存到原文件”或“另存为”时才会写入外部文件。可直接复制、粘贴和全选。");hint.setWordWrap(True);layout.addWidget(hint);editor=QTextEdit(item.text());layout.addWidget(editor,1);buttons=QHBoxLayout();buttons.addStretch();buttons.addWidget(self.btn("取消",dialog.reject));buttons.addWidget(self.btn("应用修改",dialog.accept,"primary"));layout.addLayout(buttons);self.install_input_context_menus(dialog)
        if dialog.exec()==QDialog.Accepted:item.setText(editor.toPlainText())
    def save_viewer_edit(self,*_):
        if getattr(self,"_viewer_loading",False):return
        self._viewer_dirty=True;self.show_viewer_cell_detail();self.update_viewer_file_status()
    def viewer_show_data(self,headers,rows,title="",save_snapshot=False,source="软件临时编辑"):
        self._viewer_loading=True;self._viewer_preview_column=True;self._viewer_source_headers=[str(header) for header in headers];self._viewer_image_paths={}
        with QSignalBlocker(self.viewer_table):
            self.viewer_table.clear();self.viewer_table.setColumnCount(len(headers)+1);self.viewer_table._smart_fill_enabled_columns=set(range(1,len(headers)+1));self.viewer_table.setHorizontalHeaderLabels(["图片预览",*[str(header) for header in headers]]);self.viewer_table.setRowCount(len(rows))
            for row_index,row in enumerate(rows):
                for column,value in enumerate(row):
                    text=str(value if value is not None else "");item=QTableWidgetItem(text);item.setToolTip(text);item.setTextAlignment(Qt.AlignLeft|Qt.AlignTop)
                    if text.startswith("="):item.setData(Qt.UserRole+11,text)
                    self.viewer_table.setItem(row_index,column+1,item)
                self.viewer_render_image_preview(row_index,"")
        self._viewer_loading=False;self.viewer_table.reset_history();self.fit_viewer_columns();self.show_viewer_cell_detail()
        self._viewer_dirty=False;self._viewer_file_path=None;self.update_viewer_file_status()
        if title:self.summary.setText(title) if hasattr(self,"summary") else None
    def read_csv_table(self,path):
        last_error=None
        for encoding in ("utf-8-sig","utf-8","gb18030","gbk"):
            try:
                with path.open("r",encoding=encoding,newline="") as file:
                    sample=file.read(4096);file.seek(0)
                    try:dialect=csv.Sniffer().sniff(sample,delimiters=",;\t")
                    except csv.Error:dialect=csv.excel
                    return list(csv.reader(file,dialect))
            except (OSError,UnicodeError) as error:last_error=error
        raise OSError(f"无法读取表格文件：{last_error}")
    def read_xlsx_table(self,path):
        # 优先使用 openpyxl：可正确读取宽表、公式和大多数常见 Excel 单元格类型。
        try:
            from openpyxl import load_workbook
            workbook=load_workbook(path,read_only=True,data_only=False)
            sheet=workbook.active
            values=[["" if cell.value is None else cell.value for cell in row] for row in sheet.iter_rows()]
            workbook.close()
            return values
        except ImportError:
            LOGGER.warning("未安装 openpyxl，使用兼容 XLSX 读取器：%s",path)
        except Exception:
            LOGGER.exception("openpyxl 读取失败，尝试兼容 XLSX 读取器：%s",path)
        namespace="{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
        with zipfile.ZipFile(path) as archive:
            shared=[]
            if "xl/sharedStrings.xml" in archive.namelist():
                shared=["".join(node.itertext()) for node in ElementTree.fromstring(archive.read("xl/sharedStrings.xml")).findall(namespace+"si")]
            sheets=sorted(name for name in archive.namelist() if name.startswith("xl/worksheets/") and name.endswith(".xml"))
            if not sheets:raise ValueError("Excel 文件中未找到工作表")
            root=ElementTree.fromstring(archive.read(sheets[0]));result=[]
            for row in root.findall(".//"+namespace+"row"):
                values=[]
                for cell in row.findall(namespace+"c"):
                    ref=cell.get("r","");letters="".join(char for char in ref if char.isalpha());column=0
                    for char in letters:column=column*26+ord(char.upper())-64
                    while len(values)<max(column-1,0):values.append("")
                    cell_type=cell.get("t","");value=cell.findtext(namespace+"v","")
                    if cell_type=="s" and value.isdigit() and int(value)<len(shared):value=shared[int(value)]
                    elif cell_type=="inlineStr":value="".join(cell.find(namespace+"is").itertext()) if cell.find(namespace+"is") is not None else ""
                    values.append(value)
                result.append(values)
        return result

    def write_viewer_file(self,path):
        """将当前完整表格写入外部文件；xlsx 保留其他工作表，仅替换当前活动工作表内容。"""
        path=Path(path);headers,rows=self.viewer_table_data();suffix=path.suffix.casefold()
        if suffix not in {".xlsx",".csv",".tsv"}:raise ValueError("仅支持保存为 .xlsx、.csv 或 .tsv 文件。")
        path.parent.mkdir(parents=True,exist_ok=True)
        if suffix==".xlsx":
            try:
                from openpyxl import Workbook,load_workbook
            except ImportError:
                # 无额外依赖时仍可保存常见的窄表；完整兼容保存建议安装 openpyxl。
                _write_simple_xlsx([[str(value) for value in headers],*[[str(value) for value in row] for row in rows]],path,"工作表",tuple(18 for _ in headers));return
            workbook=load_workbook(path) if path.exists() else Workbook()
            sheet=workbook.active
            if sheet.max_row:sheet.delete_rows(1,sheet.max_row)
            sheet.append([str(value) for value in headers])
            for row in rows:sheet.append(list(row))
            workbook.save(path);workbook.close();return
        delimiter="\t" if suffix==".tsv" else ","
        with path.open("w",encoding="utf-8-sig",newline="") as file:
            writer=csv.writer(file,delimiter=delimiter);writer.writerow(headers);writer.writerows(rows)

    def save_viewer_file(self,save_as=False):
        path=getattr(self,"_viewer_file_path",None)
        if save_as or not path:
            start=Path(self.settings.get("last_table_dir",str(DATA_DIR)))/(path.name if path else "编辑表格.xlsx")
            filename,_=QFileDialog.getSaveFileName(self,"另存表格文件" if save_as or not path else "保存表格文件",str(start),"Excel 工作簿 (*.xlsx);;CSV 文件 (*.csv);;制表符文件 (*.tsv)")
            if not filename:return
            path=Path(filename)
            if not path.suffix:path=path.with_suffix(".xlsx")
        try:
            self.write_viewer_file(path);self._viewer_file_path=Path(path);self._viewer_dirty=False;self.settings["last_table_dir"]=str(Path(path).parent);save_app_settings(self.settings);self.remember_viewer_file(path,"软件保存" if not save_as else "软件另存为");self.update_viewer_file_status();QMessageBox.information(self,"表格已保存",f"已将当前表格写入：\n{path}")
        except Exception as error:
            LOGGER.exception("保存表格失败：%s",path);QMessageBox.warning(self,"保存表格失败",str(error))

    def open_viewer_file(self,path):
        path=Path(path);suffix=path.suffix.casefold()
        values=self.read_xlsx_table(path) if suffix==".xlsx" else self.read_csv_table(path)
        if not values:raise ValueError("表格中没有可显示的数据")
        self.viewer_show_data(values[0],values[1:],path.name,False,str(path));self._viewer_file_path=path;self._viewer_dirty=False;self.remember_viewer_file(path,"打开外部表格");self.update_viewer_file_status();matched,unmatched,valid=self.match_viewer_images(path.parent)
        if valid and unmatched:
            sample="\n".join(unmatched[:8]);more=f"\n…另有 {len(unmatched)-8} 条" if len(unmatched)>8 else ""
            answer=self.themed_message("question","图片名称未完全匹配",f"已在表格所在目录及子目录中匹配到 {matched} 条图片，仍有 {len(unmatched)} 条未匹配：\n{sample}{more}\n\n是否选择图片所在目录继续递归匹配？")
            if answer==QMessageBox.Yes:self.choose_viewer_image_directory()
        self.stack.setCurrentIndex(6)
    def import_viewer_file(self):
        filename,_=QFileDialog.getOpenFileName(self,"导入表格文件",self.settings.get("last_table_dir",""),"表格文件 (*.xlsx *.csv *.tsv);;Excel 工作簿 (*.xlsx);;CSV 文件 (*.csv);;制表符文件 (*.tsv)")
        if not filename:return
        self.open_dropped_viewer_file(filename)

    def open_dropped_viewer_file(self,path):
        """按钮选择与资源管理器拖入共用同一读取入口，避免两条链路行为分叉。"""
        try:self.open_viewer_file(Path(path));self.settings["last_table_dir"]=str(Path(path).parent);save_app_settings(self.settings)
        except Exception as error:LOGGER.exception("读取表格失败");QMessageBox.warning(self,"导入表格失败",str(error))
    def open_selected_viewer_snapshot(self):
        selected=self.viewer_snapshots.selectedItems()
        if not selected:return
        records=self.settings.get("viewer_file_records",[]);index=selected[0].data(Qt.UserRole)
        if not isinstance(records,list) or not isinstance(index,int) or index<0 or index>=len(records):return
        path=Path(str(records[index].get("file","") or ""))
        if path.is_file():
            try:self.open_viewer_file(path)
            except Exception as error:LOGGER.exception("打开记录表格失败");QMessageBox.warning(self,"无法打开表格",f"无法读取表格文件：\n{path}\n\n{error}")
            return
        answer=self.themed_message("question","表格文件不存在",f"记录中的表格文件不存在，可能已被移动、删除或当前磁盘未连接：\n\n{path}\n\n是否从其他位置选择表格文件打开？")
        if answer==QMessageBox.Yes:self.import_viewer_file()
    def view_selected_export_record(self):
        selected=self.export_records.selectedItems()
        if not selected:return
        records=self.settings.get("export_records",[]);record=records[selected[0].data(Qt.UserRole)]
        path=Path(record.get("location","") or "")
        try:
            if path.is_file() and path.suffix.casefold() in {".xlsx",".csv",".tsv"}:self.open_viewer_file(path)
            else:
                data=record.get("data",{});self.viewer_show_data(data.get("headers",[]),data.get("rows",[]))
        except Exception as error:LOGGER.exception("打开导出记录失败");QMessageBox.warning(self,"无法查看导出记录",str(error))
    def clear_preview(self):
        if not self.rows and not any(self.table.item(row,column) for row in range(self.table.rowCount()) for column in range(1,self.table.columnCount())):return
        if QMessageBox.question(self,"清空预览数据","仅清空当前预览表格和检查提示。\n\n项目名称、路径、文件名、指令与已保存项目文件不会受到影响。是否继续？")!=QMessageBox.Yes:return
        self.rows=[];self.warnings=[];self._workspace_all_rows=[];self.table.blockSignals(True)
        try:
            # 与重新加载共用“先清内容、后画空预览格”的原则，保证表格、内存
            # 草稿和检查提示同时归零，不留下最少行数中的旧文字。
            self.table.clearContents();self.table.setRowCount(max(12,int(getattr(self.table,"minimum_row_count",12))))
            for row in range(self.table.rowCount()):self.workspace_render_image_preview(row,{})
        finally:self.table.blockSignals(False)
        self.progress.setValue(0);self.summary.setText("预览数据已清空。可点击“加载目录数据”重新读取扫描目录。");add_history({"project":self.name.text(),"operation":"清空预览数据","result":"已清空预览表格与检查提示"});self.touch_recent_project()
    def apply_instruction(self,*_):
        """同步当前指令到完整项目缓存和筛选后的可见表格。"""
        if not hasattr(self,"rows") or getattr(self,"_applying_workspace_instruction",False):return
        self._applying_workspace_instruction=True
        try:
            # 先保留表格中其他列的手工编辑，再替换“指令+台词”。
            if hasattr(self,"table") and not getattr(self,"_filling_workspace_table",False):self.collect()
            content=self.instruction_text();changed=False
            all_rows=getattr(self,"_workspace_all_rows",None);targets=[]
            if isinstance(all_rows,list):targets.append(all_rows)
            if self.rows is not all_rows:targets.append(self.rows)
            for rows in targets:
                for row in rows:
                    if row.get("txt_name") and "dialogue" in row:
                        command=content+str(row.get("dialogue","") or "")
                        if row.get("command")!=command:row["command"]=command;changed=True
            if changed and self.rows and hasattr(self,"table"):self.fill_table()
        finally:self._applying_workspace_instruction=False
    def sync_workspace_instruction_preview(self,saved_name,previous_name=""):
        """保存指令后即时回填当前项目的预览，不重新扫描目录或改动生产数据。"""
        if not hasattr(self,"instruction") or not hasattr(self,"rows"):return
        current_name=self.instruction.currentText().strip()
        if current_name not in {str(saved_name or ""),str(previous_name or "")}:
            return
        # 改名时同步工作台的当前选择；同名编辑则保留用户已有选择不闪动。
        if previous_name and previous_name!=saved_name and current_name==previous_name:
            self.refresh_instruction_options();self.instruction.setCurrentText(saved_name)
        self.apply_instruction()
        self.summary.setText("指令已更新，当前项目的“指令+台词”预览已即时同步；未重新扫描目录。")
    @staticmethod
    def dialogue_timing_metrics(dialogue, units_per_minute=None, include_video_envelope=True):
        """估算 Flow 短视频口播的实际占用时长，而非舒缓配音时长。

        越南语按音节、英文按单词、中文按字计数。此前所有语言一律按 135
        单位/分钟并额外预留较长首尾时间，会把正常的 8 秒 Flow 口播错误估成
        11--13 秒；本方法改用语言感知的短口播语速与轻量停顿。显式传入
        ``units_per_minute`` 时仍以调用方的值为准，便于已有工作流保持可控。
        """
        text=str(dialogue or "").strip()
        if not text:
            return {"units":0,"speech_seconds":0.0,"pause_seconds":0.0,"envelope_seconds":0.0,"natural_seconds":0.0}
        try:
            requested_rate=int(units_per_minute) if units_per_minute not in (None, "") else 0
        except (TypeError,ValueError):
            requested_rate=0
        # CJK 单字、Unicode 词（含越南语变音符号）与数字分别处理；不能再以
        # [A-Za-z] 或单个拉丁字母作为越南语的发音单位。
        token_pattern=re.compile(r"[\u3400-\u9fff]|\d+(?:(?:[-/:]\d+)+|(?:[.,]\d+)?)(?:[%％])?|[^\W\d_]+(?:['’\-][^\W\d_]+)*",re.UNICODE)
        spoken_units=0
        has_cjk=False
        has_vietnamese=False
        has_latin_word=False
        for match in token_pattern.finditer(text):
            token=match.group(0)
            if "\u3400" <= token[0] <= "\u9fff":
                has_cjk=True
                spoken_units+=1
            elif token[0].isdigit():
                digits=sum(char.isdigit() for char in token)
                connectors=sum(token.count(mark) for mark in "-/:")
                decimal_mark=1 if "." in token or "," in token else 0
                percent_mark=2 if token.endswith(("%","％")) else 0
                spoken_units+=max(1,digits+connectors+decimal_mark+percent_mark)
            else:
                has_latin_word=True
                if re.search(r"[À-ỹĂăÂâĐđÊêÔôƠơƯư]",token):
                    has_vietnamese=True
                spoken_units+=1
        # 大多数越南语句子并不是每个词都有变音符号，例如 “Amen”。只要全文
        # 出现越南语变音字母，就把同一段的拉丁词都按越语短口播计算。
        if requested_rate:
            rate=max(60,min(300,requested_rate)); language="自定义"
        elif has_vietnamese:
            rate=190; language="越南语"
        elif has_cjk:
            rate=225; language="中文"
        elif has_latin_word:
            rate=175; language="英文/拉丁语"
        else:
            rate=180; language="通用"
        # Flow 短口播的标点通常由模型压缩为极短换气。保留必要的节奏，不能再
        # 用舒缓配音的停顿去否定 8 秒分段。
        soft_pause=0.05*len(re.findall(r"[，,、]+",text))
        clause_pause=0.09*len(re.findall(r"[；;：:]+",text))
        # 英文句号只在不是小数或省略号的一部分时算作句末停顿。
        terminal_periods=len(re.findall(r"(?<![.\d])\.(?![.\d])",text))
        full_pause=0.16*(len(re.findall(r"[。！？!?]+",text))+terminal_periods)
        ellipsis_pause=0.24*len(re.findall(r"…+|\.\.\.+",text))
        line_pause=0.10*len(re.findall(r"\n+",text))
        pause_seconds=soft_pause+clause_pause+full_pause+ellipsis_pause+line_pause
        speech_seconds=spoken_units*60.0/rate
        # 保留一小段口型起落余量；此前固定 0.70 秒会明显放大短句误差。
        envelope_seconds=0.22 if include_video_envelope else 0.0
        natural_seconds=max(0.4,speech_seconds+pause_seconds+envelope_seconds)
        return {"units":spoken_units,"speech_seconds":speech_seconds,"pause_seconds":pause_seconds,"envelope_seconds":envelope_seconds,"natural_seconds":natural_seconds,"rate":rate,"language":language}

    @classmethod
    def estimate_dialogue_duration(cls,dialogue):
        """项目工作台显示 Flow 成片估算，并保留语言与速率依据供用户核对。"""
        timing=cls.dialogue_timing_metrics(dialogue)
        if not timing["units"]:return ""
        return (f"Flow 成片约 {timing['natural_seconds']:.1f} 秒"
                f"（{timing['units']} 个朗读单位，{timing['language']} {timing['rate']} 单位/分，含轻停顿）")
    def default_column_layout(self):
        """项目工作台的首次/恢复默认表头：先看图片与指令，路径信息按需展开。"""
        labels={
            "image_name":"图片名", "command":"指令+台词", "image_path":"图片路径",
            "txt_name":"文本名", "generated_prompt":"生成词", "estimated_speech_duration":"预计朗读时长", "generated_prompt_name":"生成词文件", "folder_path":"文本路径", "folder_name":"文件夹名",
            "status":"检查状态",
        }
        enabled={"image_name","command","generated_prompt","estimated_speech_duration","txt_name","image_path","status"}
        # 生成词后直接显示口播时长；文本名必须位于图片路径之前，便于核对
        # “哪段文案对应哪张图片”。
        order=("image_name","command","generated_prompt","estimated_speech_duration","txt_name","image_path","generated_prompt_name","folder_path","folder_name","status")
        return [{"key":key,"label":labels[key],"enabled":key in enabled} for key in order]
    def normalized_column_layout(self,layout):
        defaults={item["key"]:item for item in self.default_column_layout()};items=[];seen=set()
        for item in layout if isinstance(layout,list) else []:
            key=item.get("key") if isinstance(item,dict) else None
            if key in defaults and key not in seen:
                default=defaults[key];items.append({"key":key,"label":str(item.get("label",default["label"])) or default["label"],"enabled":bool(item.get("enabled",default["enabled"]))});seen.add(key)
        for key,default in defaults.items():
            if key not in seen:items.append(dict(default))
        return items
    def system_column_layout(self):
        """表头是软件级偏好，随用户配置迁移，不依赖单个项目文件。"""
        layout=self.normalized_column_layout(self.settings.get("table_column_layout"))
        # 旧版已保存的个性化表头不会自动拿到新增列，也会保留“图片路径在
        # 文本名前”的旧顺序。做一次明确迁移；之后用户仍可在设置表头中自行拖动。
        if int(self.settings.get("workspace_column_layout_version",0) or 0)<2:
            by_key={item["key"]:item for item in layout}
            order=[item["key"] for item in layout]
            for key in ("txt_name","image_path","estimated_speech_duration"):
                if key in order:order.remove(key)
            prompt_index=order.index("generated_prompt")+1 if "generated_prompt" in order else len(order)
            order.insert(prompt_index,"estimated_speech_duration")
            order.insert(prompt_index+1,"txt_name")
            order.insert(prompt_index+2,"image_path")
            layout=[by_key[key] for key in order if key in by_key]
            self.settings["table_column_layout"]=layout
            self.settings["workspace_column_layout_version"]=2
            save_app_settings(self.settings)
        return layout
    def save_system_column_layout(self,layout):
        self.column_layout=self.normalized_column_layout(layout)
        self.settings["table_column_layout"]=self.column_layout
        save_app_settings(self.settings)
    def configure_table_headers(self):
        dialog,layout=self.themed_dialog("设置表头",530,590);layout.addWidget(QLabel("勾选要导出的列；双击名称可修改表头；可直接拖动行调整导出顺序。保存后会作为软件默认表头，迁移配置时也会一并带走。"));items=QListWidget();items.setDragEnabled(True);items.setAcceptDrops(True);items.viewport().setAcceptDrops(True);items.setDropIndicatorShown(True);items.setDragDropOverwriteMode(False);items.setDragDropMode(QAbstractItemView.InternalMove);items.setDefaultDropAction(Qt.MoveAction);items.setSelectionMode(QAbstractItemView.SingleSelection)
        for column in self.system_column_layout():
            item=QListWidgetItem(column["label"]);item.setData(Qt.UserRole,column["key"]);item.setFlags(item.flags()|Qt.ItemIsUserCheckable|Qt.ItemIsEditable|Qt.ItemIsDragEnabled);item.setCheckState(Qt.Checked if column["enabled"] else Qt.Unchecked);items.addItem(item)
        layout.addWidget(items,1);buttons=QHBoxLayout();reset=self.btn("恢复默认",lambda:self.reset_header_list(items));buttons.addWidget(reset);buttons.addStretch();buttons.addWidget(self.btn("取消",dialog.reject));buttons.addWidget(self.btn("保存设置",dialog.accept,"primary"));layout.addLayout(buttons)
        if dialog.exec()!=QDialog.Accepted:return
        default_labels={column["key"]:column["label"] for column in self.default_column_layout()}
        self.save_system_column_layout([{"key":items.item(index).data(Qt.UserRole),"label":items.item(index).text().strip() or default_labels[items.item(index).data(Qt.UserRole)],"enabled":items.item(index).checkState()==Qt.Checked} for index in range(items.count())]);self.fill_table();self.summary.setText("表头设置已保存为系统默认，并已应用到预览与后续导出。")
    def reset_header_list(self,widget):
        widget.clear()
        for column in self.default_column_layout():
            item=QListWidgetItem(column["label"]);item.setData(Qt.UserRole,column["key"]);item.setFlags(item.flags()|Qt.ItemIsUserCheckable|Qt.ItemIsEditable|Qt.ItemIsDragEnabled);item.setCheckState(Qt.Checked if column["enabled"] else Qt.Unchecked);widget.addItem(item)
    def selected_export_columns(self):
        # 表头属于系统级偏好，避免项目草稿或旧内存状态覆盖最新配置。
        layout=self.system_column_layout() if hasattr(self,"settings") else self.default_column_layout()
        self.column_layout=layout
        return [column for column in layout if column["enabled"]]
    def export_table_with_layout(self,rows,target,output_format):
        columns=self.selected_export_columns()
        if not columns:raise ValueError("请在“设置表头”中至少勾选一列后再导出。")
        values=[[column["label"] for column in columns]]+[[str(row.get(column["key"],"")) for column in columns] for row in rows];target.parent.mkdir(parents=True,exist_ok=True)
        if output_format==FORMATS[0]:_write_simple_xlsx(values,target,"台词素材",tuple(22 for _ in columns));return
        delimiter=";" if output_format==FORMATS[2] else "\t" if output_format==FORMATS[3] else ","
        with target.open("w",encoding="utf-8-sig",newline="") as file:csv.writer(file,delimiter=delimiter).writerows(values)
    def project_export_directory(self,suffix):
        project_name=self.name.text().strip() or Path(self.input.text().strip()).name or "未命名项目";return Path(self.input.text().strip())/(project_name+suffix)
    def waiting_export_directory(self):
        """合并导出的默认目录优先跟随输出目录，未填写时回退扫描目录。"""
        source=self.output.text().strip() or getattr(self,"_inactive_output_directory","") or self.input.text().strip()
        if not source:return None
        base=Path(source);return base.with_name(base.name+"-待制作")
    def next_available_directory(self,directory):
        stamp=datetime.now().strftime("%Y%m%d%H%M%S");candidate=directory.with_name(f"{directory.name}-{stamp}");index=2
        while candidate.exists():candidate=directory.with_name(f"{directory.name}-{stamp}-{index:02d}");index+=1
        return candidate
    def resolve_export_conflicts(self,targets,directory,title,new_directory_base=None):
        existing=[target for target in targets if target.exists()]
        created=[target for target in targets if not target.exists()];dialog,layout=self.themed_dialog(title,680,500);target_label=QLabel(f"导出目录／新目录基准：{directory}");target_label.setWordWrap(True);layout.addWidget(target_label);layout.addWidget(QLabel(f"本次将导出 {len(targets)} 个文件：覆盖 {len(existing)} 个，创建 {len(created)} 个。"));details=QTextEdit();details.setReadOnly(True);details.setPlainText("【将覆盖】\n"+("\n".join(str(path) for path in existing) if existing else "无")+"\n\n【将创建】\n"+("\n".join(str(path) for path in created) if created else "无"));details.setMinimumHeight(240);layout.addWidget(details,1);hint=QLabel("可滚动查看完整清单。选择“创建新目录”或“其他目录”后，会重新显示最终目录下的清单，点击“确认导出”才会实际写入文件。");hint.setWordWrap(True);layout.addWidget(hint);buttons=QHBoxLayout();buttons.addWidget(self.btn("取消",dialog.reject));other=self.btn("选择其他目录",lambda:dialog.done(3));new_button=self.btn("创建新目录",lambda:dialog.done(2),"warning");overwrite=self.btn("确认导出" if not existing else "覆盖同名文件",lambda:dialog.done(1),"exportConfirm");buttons.addStretch();buttons.addWidget(other);buttons.addWidget(new_button);buttons.addWidget(overwrite);layout.addLayout(buttons);result=dialog.exec()
        if result==1:return directory,"write"
        if result==2:
            candidate=self.next_available_directory(new_directory_base or directory)
            message=f"将预览新的导出目录：\n{candidate}\n\n此时不会创建文件夹；只有在最终点击“确认导出”后，才会连同文件一起创建。是否继续？"
            return (candidate,"new") if QMessageBox.question(self,"确认创建新目录",message)==QMessageBox.Yes else (directory,"refresh")
        if result==3:
            chosen=QFileDialog.getExistingDirectory(self,"选择导出目录",str(directory.parent))
            # 系统文件夹选择框的“取消”只表示放弃本次选目录；返回当前预览，
            # 不应中断仍在进行中的导出确认流程。
            return (Path(chosen),"other") if chosen else (directory,"refresh")
        return None,"cancel"
    def image_export_targets(self,rows,destination=None):
        destination=Path(destination) if destination else self.project_export_directory("-图片");targets=[];used=set()
        for row in rows:
            image_path=Path(row.get("image_path","") or "");txt_name=row.get("txt_name","")
            if not txt_name or not image_path.is_file():continue
            # 不同子目录里常有 1.jpg + 1.txt。原先都会变成“1-1.jpg”，循环复制
            # 会静默覆盖前图，最终物理图片数少于表格行数。保持首个旧命名，冲突项
            # 追加稳定序号，确保每一条待制作记录都保留一张独立图片。
            base=image_path.stem+"-"+Path(txt_name).stem
            target=destination/(base+image_path.suffix);serial=2
            while str(target).casefold() in used:
                target=destination/(f"{base}_{serial}"+image_path.suffix);serial+=1
            used.add(str(target).casefold());targets.append((image_path,target))
        return destination,targets
    def export_images(self,rows=None,destination=None,quiet=False):
        if isinstance(rows,bool):rows=None
        if rows is None and not self.rows:
            QMessageBox.warning(self,"请先加载项目数据","请先选择扫描目录并点击“加载并更新项目数据”或“加载目录数据”，确认预览中出现待制作任务后，再导出图片。");return False
        rows=([row for row in self.collect() if row.get("_export_selected")] if rows is None else rows)
        if not rows:
            if not quiet:QMessageBox.warning(self,"未勾选导出项","请先在 B 列勾选至少一条记录；也可在“筛选菜单”中使用全选、反选或取消全选。")
            return False
        destination,targets=self.image_export_targets(rows,destination)
        if not targets:QMessageBox.warning(self,"没有可复制的图片","预览中没有可用的“图片完整路径”和数字台词文件。请先加载项目数据，并确认未完成任务已识别到图片后再导出。");return False
        target_paths=[target for _,target in targets];new_directory_base=destination
        if not quiet:
            while True:
                chosen,action=self.resolve_export_conflicts(target_paths,destination,"图片文件冲突",new_directory_base)
                if action=="cancel":return False
                if action=="refresh":continue
                if action=="write":break
                if action=="other":new_directory_base=chosen
                destination,targets=self.image_export_targets(rows,chosen);target_paths=[target for _,target in targets]
        existing=[target for target in target_paths if target.exists()]
        try:
            destination.mkdir(parents=True,exist_ok=True)
            for source,target in targets:shutil.copy2(source,target)
        except Exception as error:LOGGER.exception("复制图片失败");QMessageBox.critical(self,"图片导出失败",str(error));return False
        self.remember_export("对应图片",f"{len(targets)} 张图片",destination,rows);add_history({"project":self.name.text(),"operation":"导出对应图片","result":f"{'覆盖' if existing else '成功'}：{len(targets)} 张","file":str(destination)});self.touch_recent_project()
        if not quiet:QMessageBox.information(self,"图片导出完成",f"已复制 {len(targets)} 张对应图片。\n{destination}")
        return True
    def material_main_image_scan_directory(self):
        """返回用户填写的扫描目录；主图导出不读取任何其它来源路径。"""
        configured=self.input.text().strip()
        if not configured:return None
        if configured.casefold().startswith("file:"):
            configured=QUrl(configured).toLocalFile() or configured
        scan_directory=Path(configured).expanduser()
        return scan_directory if scan_directory.is_dir() else None
    def material_main_image_export_directory(self):
        """主图输出固定在扫描目录同级，不能使用日期变量或整理输出目录。"""
        scan_directory=self.material_main_image_scan_directory()
        if scan_directory is None:return None
        folder_name=scan_directory.name.strip()
        if not folder_name:return None
        return scan_directory.parent/(folder_name+"-图片")
    def material_main_image_targets(self,_rows=None):
        """递归导出扫描范围内每个文件夹的同名主图，不把 -1/-2 分段图当成主图。"""
        destination=self.material_main_image_export_directory()
        scan_directory=self.material_main_image_scan_directory()
        if destination is None or scan_directory is None:return None,[]
        # 主图以“图片名称 == 图片所在文件夹名”判定。递归扫描是为了覆盖资料包的
        # 子文件夹；例如 A\\B\\B.jpg 会导出，A\\B\\B-1.jpg 不会被误当成主图。
        sources=[]
        for directory,subdirectories,filenames in os.walk(scan_directory):
            subdirectories.sort(key=str.casefold)
            directory_path=Path(directory)
            directory_name=directory_path.name.casefold()
            for filename in sorted(filenames,key=str.casefold):
                path=directory_path/filename
                if path.suffix.lower() in IMAGE_SUFFIXES and path.stem.casefold()==directory_name:
                    sources.append(path)
        sources.sort(key=lambda path:str(path.relative_to(scan_directory)).casefold())
        # 扫描目录内的同名文件夹在正常情况下名称各异。若用户确实存在跨层同名
        # 文件夹，保留相对目录以避免两个不同主图在导出时静默互相覆盖。
        duplicate_names={path.name.casefold() for path in sources if sum(other.name.casefold()==path.name.casefold() for other in sources)>1}
        targets=[]
        for source in sources:
            if source.name.casefold() in duplicate_names:
                target=destination/source.relative_to(scan_directory)
            else:
                target=destination/source.name
            targets.append((source,target))
        return destination,targets
    def export_material_main_images(self):
        """按扫描目录的同名主图规则导出；不依赖当前表格或素材整理项目。"""
        destination,targets=self.material_main_image_targets()
        if destination is None:
            QMessageBox.warning(self,"缺少扫描目录","请先填写有效的扫描目录，再导出主图。");return False
        if not targets:
            scan_directory=self.material_main_image_scan_directory()
            QMessageBox.warning(self,"没有可导出的主图",f"扫描目录及其子文件夹中未找到与所在文件夹同名的主图：\n{scan_directory}\n\n需要的文件名示例：\n{scan_directory.name}.jpg\n子文件夹\\子文件夹名.jpg");return False
        # 目标“项目名-图片”目录存在时，无论其中是否已有同名文件都先确认；确认
        # 后仅覆盖本次同名图片，不删除目录中的其它文件。
        if destination.exists():
            answer=QMessageBox.question(self,"主图目录已存在",f"目标目录已存在：\n{destination}\n\n是否覆盖本次导出的同名主图？\n未涉及的其它文件会保留。")
            if answer!=QMessageBox.Yes:return False
        existing=sum(1 for _source,target in targets if target.exists())
        try:
            destination.mkdir(parents=True,exist_ok=True)
            for source,target in targets:
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(source,target)
        except Exception as error:
            LOGGER.exception("导出素材主图失败");QMessageBox.critical(self,"导出失败",str(error));return False
        self.remember_export("主图",f"{len(targets)} 张图片",destination,[])
        add_history({"project":self.name.text(),"operation":"导出主图","result":f"{'覆盖' if existing else '成功'}：{len(targets)} 张","file":str(destination)})
        self.touch_recent_project()
        QMessageBox.information(self,"主图导出完成",f"已导出 {len(targets)} 张主图。\n\n输出目录：{destination}"+(f"\n已覆盖 {existing} 张同名图片。" if existing else ""))
        return True
    def payload(self):
        self.collect();self._sync_workspace_all_rows_from_visible()
        # 项目文件只保存项目设置，不再保存易过期的扫描结果。素材可能被移动、删除或
        # 重新整理，恢复旧表格既无法可靠对应最新文件，也容易让用户误用历史数据。
        return {**(self.active or {}),"name":self.name.text().strip(),"input_dir":self.input.text().strip(),"output_dir":self.output.text().strip() or getattr(self,"_inactive_output_directory", ""),"output_name":self.filename.text().strip(),"scan_mode":self.scan_mode.currentData() if hasattr(self,"scan_mode") else "standard","segment_bundle_image_mode":self.bundle_image_mode.currentData() if hasattr(self,"bundle_image_mode") else "segment_image","output_mode":self.output_mode_key(),"output_format":self.format.currentText(),"copy_images":self.copy_images.isChecked(),"merge_export":self.merge_export.isChecked(),"column_layout":self.column_layout,"instruction_category":self.selected_instruction_category(),"instruction_name":self.instruction.currentText(),"encoding":self.encoding.currentText(),"workspace_pending_only":self.workspace_pending_only.isChecked(),"draft_rows":[],"draft_warnings":[]}
    def save_project_file(self):
        self.defaults()
        if not self.name.text().strip():QMessageBox.warning(self,"缺少项目名称","请填写项目名称。");return
        self.active=save_project(self.payload()); self.state.setText(f"当前项目\n{self.active['name']}"); add_history({"project":self.name.text(),"operation":"保存项目","result":"已保存项目设置（表格数据不保存）","file":self.active["project_file"]}); QMessageBox.information(self,"项目已保存",self.active["project_file"]);self.refresh_recent()
    def load_project_data(self,project):
        self.active=project
        for w,k in ((self.name,"name"),(self.input,"input_dir"),(self.output,"output_dir"),(self.filename,"output_name")):w.setText(project.get(k,""))
        self.set_output_mode(project.get("output_mode",self.settings.get("workspace_output_mode",OUTPUT_MODE_TABLE)));self.format.setCurrentText(project.get("output_format",self.settings.get("workspace_output_format",FORMATS[0])));scan_index=self.scan_mode.findData(str(project.get("scan_mode",self.settings.get("workspace_scan_mode","standard")) or "standard")) if hasattr(self,"scan_mode") else -1;self.scan_mode.setCurrentIndex(scan_index if scan_index>=0 else 0) if hasattr(self,"scan_mode") else None;image_index=self.bundle_image_mode.findData(str(project.get("segment_bundle_image_mode",self.settings.get("workspace_segment_bundle_image_mode","segment_image")) or "segment_image")) if hasattr(self,"bundle_image_mode") else -1;self.bundle_image_mode.setCurrentIndex(image_index if image_index>=0 else 0) if hasattr(self,"bundle_image_mode") else None;self.restore_workspace_export_options(project.get("copy_images",None),project.get("merge_export",None),remember=True);self.refresh_output_mode_labels();self.column_layout=self.system_column_layout();self.encoding.setCurrentText(project.get("encoding","utf-8"));self._selected_instruction_category=project.get("instruction_category",self.settings.get("last_instruction_category","全部分类"));self.refresh_instruction_options();self.instruction.setCurrentText(project.get("instruction_name",self.settings.get("workspace_instruction_name",self.instruction.currentText())));self.remember_workspace_selectors();self._workspace_all_rows=[];self.rows=[];self.warnings=[];self.workspace_pending_only.blockSignals(True);self.workspace_pending_only.setChecked(bool(project.get("workspace_pending_only",self.settings.get("workspace_pending_only",False))));self.workspace_pending_only.blockSignals(False);self.fill_table();self.summary.setText("项目设置已恢复；表格保持为空。需要最新数据时，请点击“加载并更新项目数据”。");self.state.setText(f"当前项目\n{project.get('name','')}");self.touch_recent_project()
    def open_project(self):
        filename,_=QFileDialog.getOpenFileName(self,"打开项目",self.settings.get("last_project_dir",""),"项目文件 (*.project.json)")
        if not filename:return
        try:self.settings["last_project_dir"]=str(Path(filename).parent);save_app_settings(self.settings);self.load_project_data(json.loads(Path(filename).read_text(encoding="utf-8")))
        except Exception as error:LOGGER.exception("打开项目失败"); QMessageBox.critical(self,"打开失败",str(error))
    def remove_project(self):
        if not self.active:QMessageBox.information(self,"没有可删除的项目","请先打开或保存项目。");return
        if QMessageBox.question(self,"删除项目","仅删除 .project.json 和项目列表记录，不删除素材和导出文件。是否继续？")==QMessageBox.Yes:delete_project(self.active);self.new_project()
    def clear_current(self):
        if QMessageBox.question(self,"清空当前项目数据","清空当前界面数据，不删除已保存项目文件。是否继续？")==QMessageBox.Yes:self.new_project()
    def multi_txt_targets(self,rows,destination=None):
        targets=[]
        for row in rows:
            folder_path=row.get("folder_path","");txt_name=row.get("txt_name","")
            if not folder_path or not txt_name:continue
            folder=Path(folder_path);number=Path(txt_name).stem;folder_name=row.get("folder_name","") or folder.name
            safe_name="".join("_" if char in '<>:"/\\|?*' else char for char in folder_name).strip(". ") or "未命名文件夹"
            targets.append((row,(Path(destination) if destination else folder)/(safe_name+"-"+number+".txt")))
        return targets
    def export_multiple_txt(self,rows,destination=None,quiet=False):
        targets=self.multi_txt_targets(rows,destination)
        if not targets:QMessageBox.warning(self,"没有可输出的台词","多文件模式需要包含台词文件名和原始文件夹路径的记录。");return
        directory=Path(destination) if destination else None;target_paths=[target for _,target in targets]
        if not quiet:
            base_directory=directory or self.project_export_directory("-待制作");new_directory_base=base_directory
            while True:
                chosen,action=self.resolve_export_conflicts(target_paths,base_directory,"TXT 文件冲突",new_directory_base)
                if action=="cancel":return
                if action=="refresh":continue
                if action=="write":break
                if action=="other":new_directory_base=chosen
                directory=chosen;targets=self.multi_txt_targets(rows,directory);target_paths=[target for _,target in targets];base_directory=directory
        existing=[target for target in target_paths if target.exists()]
        try:
            for row,target in targets:
                target.parent.mkdir(parents=True,exist_ok=True);target.write_text(row.get("command","") or "",encoding=self.encoding.currentText())
        except Exception as error:LOGGER.exception("Qt 多文件导出失败");QMessageBox.critical(self,"导出失败",str(error));return
        location=directory or self.input.text().strip() or targets[0][1].parent;self.remember_export("多个 TXT 文件",f"{len(targets)} 个 TXT 文件",location,rows);add_history({"project":self.name.text(),"operation":"确认并导出（多个 TXT 文件）","result":f"{'覆盖' if existing else '成功'}：{len(targets)} 个 TXT 文件","file":str(targets[0][1].parent)});self.touch_recent_project()
        if not quiet:QMessageBox.information(self,"导出完成",f"已输出 {len(targets)} 个 TXT 文件。\n\n示例：{targets[0][1]}")
    def export(self):
        self.defaults(); rows=[row for row in self.collect() if row.get("_export_selected")]
        if not rows:
            QMessageBox.warning(self,"未勾选导出项","请先在 B 列勾选至少一条记录。可使用“筛选菜单”中的全选、反选或取消全选。")
            return
        completed_rows=[row for row in rows if row.get("_existing_video")]
        rows=[row for row in rows if not row.get("_existing_video")]
        if not rows:
            hint="当前记录均已有同名视频，已保留在表格供检查，默认不重复导出。" if completed_rows else "请先加载目录或手动添加行。"
            QMessageBox.warning(self,"没有可导出数据",hint);return
        merged_directory=self.waiting_export_directory() if self.merge_export.isChecked() else None
        if self.merge_export.isChecked() and merged_directory is None:QMessageBox.warning(self,"缺少输出位置","请先填写输出目录或扫描目录，以生成待制作目录。");return
        if self.output_mode_key()==OUTPUT_MODE_MULTI_TXT:
            if merged_directory:
                new_directory_base=merged_directory
                while True:
                    text_targets=[target for _,target in self.multi_txt_targets(rows,merged_directory)];image_targets=[target for _,target in self.image_export_targets(rows,merged_directory)[1]] if self.copy_images.isChecked() else []
                    chosen,action=self.resolve_export_conflicts([*text_targets,*image_targets],merged_directory,"待制作目录文件冲突",new_directory_base)
                    if action=="cancel":return
                    if action=="refresh":continue
                    if action=="write":break
                    if action=="other":new_directory_base=chosen
                    merged_directory=chosen
                self.export_multiple_txt(rows,chosen,True)
                if self.copy_images.isChecked():self.export_images(rows,chosen,True)
                QMessageBox.information(self,"合并导出完成",f"已将 {len(text_targets)} 个 TXT 文件"+(f" 和 {len(image_targets)} 张图片" if image_targets else "")+f" 统一输出到：\n{chosen}");return
            self.export_multiple_txt(rows);return
        if not self.name.text().strip() or (not merged_directory and not self.output.text().strip()):QMessageBox.warning(self,"信息不完整","请填写项目名称和输出目录；勾选合并导出时仅需填写项目名称。");return
        directory=merged_directory or Path(self.output.text());target=directory/self.filename.text();image_targets=[target for _,target in self.image_export_targets(rows,directory)[1]] if self.copy_images.isChecked() and merged_directory else []
        if merged_directory:
            new_directory_base=directory
            while True:
                chosen,action=self.resolve_export_conflicts([target,*image_targets],directory,"待制作目录文件冲突",new_directory_base)
                if action=="cancel":return
                if action=="refresh":continue
                if action=="write":break
                if action=="other":new_directory_base=chosen
                directory=chosen;target=directory/self.filename.text();image_targets=[image_target for _,image_target in self.image_export_targets(rows,directory)[1]] if self.copy_images.isChecked() else []
        else:
            new_directory_base=directory
            while True:
                chosen,action=self.resolve_export_conflicts([target],directory,"表格文件冲突",new_directory_base)
                if action=="cancel":return
                if action=="refresh":continue
                if action=="write":break
                if action=="other":new_directory_base=chosen
                directory=chosen;target=directory/self.filename.text()
        existed=target.exists()
        try:self.export_table_with_layout(rows,target,self.format.currentText())
        except Exception as error:LOGGER.exception("Qt 导出失败");QMessageBox.critical(self,"导出失败",str(error));return
        self.remember_export("表格文件",target.name,target,rows);add_history({"project":self.name.text(),"operation":"确认并导出","result":f"{'覆盖导出' if existed else '成功'}：{len(rows)} 条","file":str(target)});self.touch_recent_project()
        if self.copy_images.isChecked():self.export_images(rows,directory if merged_directory else None,bool(merged_directory))
        QMessageBox.information(self,"合并导出完成" if merged_directory else "导出完成",f"已写入 {len(rows)} 条记录。\n{target}"+(f"\n图片已统一输出到：{directory}" if merged_directory and self.copy_images.isChecked() else ""))
    def open_exported_file(self):
        if self.output_mode_key()==OUTPUT_MODE_MULTI_TXT:QMessageBox.information(self,"多个 TXT 文件模式","当前模式会分别输出每条内容；请使用“打开导出目录”查看输出位置。");return
        self.defaults(); waiting_directory=self.waiting_export_directory(); output=str(waiting_directory) if self.merge_export.isChecked() and waiting_directory else self.output.text().strip(); filename=self.filename.text().strip()
        if not output or not filename: QMessageBox.information(self,"未找到导出文件","请先填写输出目录和文件名，或先完成一次导出。"); return
        target=Path(output)/filename
        if not target.is_file(): QMessageBox.information(self,"未找到导出文件",f"当前输出目录中未找到文件：\n{target}\n\n请先确认并导出，或检查输出目录和文件名。"); return
        try: open_system_path(target)
        except OSError as error: LOGGER.exception("打开导出文件失败"); QMessageBox.warning(self,"无法打开导出文件",str(error))
    def open_export_directory(self):
        if self.merge_export.isChecked():
            directory=self.waiting_export_directory()
            if directory is None or not directory.is_dir():QMessageBox.information(self,"未找到待制作目录",f"当前待制作目录不存在：\n{directory or '请先填写输出目录或扫描目录'}\n\n请先确认并导出，或检查输出目录和扫描目录。");return
            try:open_system_path(directory)
            except OSError as error:LOGGER.exception("打开待制作目录失败");QMessageBox.warning(self,"无法打开导出目录",str(error))
            return
        if self.output_mode_key()==OUTPUT_MODE_MULTI_TXT:
            directory=Path(self.input.text().strip())
            if not directory.is_dir():QMessageBox.information(self,"未找到扫描目录","多文件模式的 TXT 会输出到各自素材文件夹。请先选择有效的扫描目录。");return
            try:open_system_path(directory)
            except OSError as error:LOGGER.exception("打开扫描目录失败");QMessageBox.warning(self,"无法打开扫描目录",str(error))
            return
        output=self.output.text().strip()
        if not output: QMessageBox.information(self,"未填写输出目录","请先选择或输入输出目录。"); return
        directory=Path(output)
        if not directory.is_dir(): QMessageBox.information(self,"未找到导出目录",f"当前输出目录不存在：\n{directory}\n\n请先确认并导出，或检查输出目录。"); return
        try: open_system_path(directory)
        except OSError as error: LOGGER.exception("打开导出目录失败"); QMessageBox.warning(self,"无法打开导出目录",str(error))
    def refresh_recent(self):
        if not hasattr(self,"recent"):return
        self.recent.clear(); byid={x["id"]:x for x in projects()}
        number=1
        for ident in recent_project_ids():
            if ident in byid:
                project=byid[ident]; item=QListWidgetItem(f"{number:02d}  |  {project.get('name','')}  ·  {project.get('updated_at','')}\n{project.get('input_dir','')}"); item.setData(Qt.UserRole,ident); self.recent.addItem(item); number+=1
    def touch_recent_project(self):
        """项目操作后立即同步最近列表；未手动保存的项目不会被隐式保存。"""
        if self.active and self.active.get("id"):
            mark_recent_project(self.active["id"])
        self.refresh_recent()
    def open_recent(self,item):
        ident=item.data(Qt.UserRole);project=next((x for x in projects() if x.get("id")==ident),None)
        if project:self.load_project_data(project)
    def clear_recent(self):
        if QMessageBox.question(self,"清空最近项目","仅清空最近列表，不删除项目文件。是否继续？")==QMessageBox.Yes:clear_recent_projects();self.refresh_recent()
    def set_instruction_editable(self,editable):
        self.instruction_editing=editable
        for widget in (self.iname,self.icontent,self.inote): widget.setReadOnly(not editable)
        self.ifolder.setEnabled(editable)

    def suggest_instruction_name(self,content):
        """从详细指令首个有效主题句生成名称，减少新建指令的重复填写。"""
        text=str(content or "").replace("\r", "\n")
        for raw_line in text.split("\n"):
            line=raw_line.strip().lstrip("#>*-•0123456789.、)） ").strip()
            if not line:continue
            # 优先取首个完整短句；保留原语言，避免中英文指令被错误翻译。
            parts=re.split(r"[。！？!?；;\n]",line,1)
            candidate=re.sub(r"\s+"," ",parts[0]).strip(" ：:-—")
            if candidate:
                return candidate[:28].rstrip("，,、 ")+("…" if len(candidate)>28 else "")
        return ""

    def new_instruction(self):
        folder=self.selected_folder()
        if not folder and len(self.ilist.selectedItems())==1:
            node=self.ilist.selectedItems()[0];parent=node.parent();parent_data=parent.data(0,Qt.UserRole) if parent else None
            if isinstance(parent_data,dict):folder=parent_data.get("folder","")
        self.open_instruction_editor(folder=folder)
    def refresh_folder_choices(self):
        folders=self.instruction_folders();current=self.ifolder.currentText() if hasattr(self,"ifolder") else "未分类";self.ifolder.clear();self.ifolder.addItems(folders or ["未分类"]);self.ifolder.setCurrentText(current if current in folders else (folders[0] if folders else "未分类"))
    def instruction_album_root(self):
        """All images live in one managed pool; instruction albums only store stable IDs."""
        root=Path(DATA_DIR)/"instruction_album_assets";root.mkdir(parents=True,exist_ok=True);return root
    def instruction_album_path(self,entry):
        name=Path(str(entry.get("file_name","") or "")).name if isinstance(entry,dict) else ""
        return self.instruction_album_root()/name if name else None
    def ensure_instruction_record_id(self,items,index):
        """Repair legacy/copied duplicate IDs before any ID-addressed album write."""
        if not isinstance(index,int) or not 0<=index<len(items) or not isinstance(items[index],dict):return False
        record=items[index];identifier=str(record.get("id","") or "")
        duplicate=not identifier or any(item_index!=index and isinstance(item,dict) and str(item.get("id","") or "")==identifier for item_index,item in enumerate(items))
        if duplicate:
            record["id"]=uuid.uuid4().hex
            return True
        return False
    def selected_instruction_record(self):
        index=getattr(self,"inst_index",None);items=instructions()
        if not isinstance(index,int) or not 0<=index<len(items):return None
        item=items[index]
        if not isinstance(item,dict):return None
        changed=self.ensure_instruction_record_id(items,index)
        if not isinstance(item.get("album"),list):item["album"]=[];changed=True
        if "cover_id" not in item:item["cover_id"]="";changed=True
        if changed:save_instructions(items)
        return item
    def save_instruction_album_record(self,record):
        """Write the edited record back by ID; never replace it with a fresh stale read."""
        if not isinstance(record,dict):return False
        records=instructions();record_id=str(record.get("id","") or "");fallback=getattr(self,"inst_index",None)
        # The visible current record wins.  Never choose the first same-ID row:
        # old copied data may contain duplicate IDs and that would overwrite an
        # unrelated instruction when setting a cover.
        if isinstance(fallback,int) and 0<=fallback<len(records) and isinstance(records[fallback],dict) and str(records[fallback].get("id","") or "")==record_id:index=fallback
        else:
            matches=[i for i,value in enumerate(records) if isinstance(value,dict) and str(value.get("id","") or "")==record_id]
            if len(matches)!=1:return False
            index=matches[0]
        self.ensure_instruction_record_id(records,index)
        record["id"]=str(records[index].get("id") or uuid.uuid4().hex)
        records[index]=record;self.inst_index=index;save_instructions(records);return True
    def instruction_album_cover_path(self,item):
        if not isinstance(item,dict):return None
        album=[entry for entry in item.get("album",[]) if isinstance(entry,dict)];cover_id=str(item.get("cover_id","") or "")
        for entry in [*(entry for entry in album if str(entry.get("id","") or "")==cover_id),*(entry for entry in album if str(entry.get("id","") or "")!=cover_id)]:
            path=self.instruction_album_path(entry)
            if path and path.is_file():return path
        return None
    def instruction_album_thumbnail_icon(self,path,size=132):
        """Square, centre-cropped album thumbnail: mixed image ratios remain readable."""
        if not path or not Path(path).is_file():return QIcon()
        pixmap=QPixmap(str(path))
        if pixmap.isNull():return QIcon()
        target=QSize(size,size)
        scaled=pixmap.scaled(target,Qt.KeepAspectRatioByExpanding,Qt.SmoothTransformation)
        left=max(0,(scaled.width()-size)//2);top=max(0,(scaled.height()-size)//2)
        return QIcon(scaled.copy(left,top,size,size))
    def refresh_instruction_album(self):
        if not hasattr(self,"instruction_album_list"):return
        self.instruction_album_list.clear();item=self.selected_instruction_record()
        if not item:
            self.instruction_album_cover.setPixmap(QPixmap());self.instruction_album_cover.setText("尚未选择指令\n\n请先点击左侧的一条指令")
            return
        cover=self.instruction_album_cover_path(item)
        if cover:
            pixmap=QPixmap(str(cover))
            if not pixmap.isNull():self.instruction_album_cover.setPixmap(pixmap.scaled(self.instruction_album_cover.size() if self.instruction_album_cover.width()>40 else QSize(360,180),Qt.KeepAspectRatio,Qt.SmoothTransformation));self.instruction_album_cover.setText("")
        else:self.instruction_album_cover.setPixmap(QPixmap());self.instruction_album_cover.setText("“%s” 暂未设置封面\n点击“＋ 添加图片”开始"%(item.get("name") or "当前指令"))
        for entry in item.get("album",[]):
            if not isinstance(entry,dict):continue
            path=self.instruction_album_path(entry);row=QListWidgetItem(self.instruction_album_thumbnail_icon(path),str(entry.get("original_name") or entry.get("file_name") or "图片"));row.setData(Qt.UserRole,str(entry.get("id","") or ""));row.setToolTip(str(path) if path and path.is_file() else "图片文件已不存在");self.instruction_album_list.addItem(row)
    def instruction_album_receive(self,paths=None,clipboard_image=None,source_name="添加"):
        item=self.selected_instruction_record()
        if not item:QMessageBox.information(self,"请选择指令","请先在左侧选中一条指令，再添加作品图片。");return
        allowed={".png",".jpg",".jpeg",".webp",".bmp",".gif",".tif",".tiff"};album=item.setdefault("album",[]);added=0
        for raw in paths or []:
            source=Path(raw);suffix=source.suffix.lower()
            if not source.is_file() or suffix not in allowed:continue
            asset_id=uuid.uuid4().hex;file_name=asset_id+suffix
            try:
                shutil.copy2(source,self.instruction_album_root()/file_name);album.append({"id":asset_id,"file_name":file_name,"original_name":source.name,"added_at":datetime.now().isoformat(timespec="seconds")});added+=1
                if not item.get("cover_id"):item["cover_id"]=asset_id
            except Exception as error:LOGGER.warning("指令相册图片导入失败：%s",error)
        if clipboard_image is not None:
            asset_id=uuid.uuid4().hex;file_name=asset_id+".png"
            try:
                if clipboard_image.save(str(self.instruction_album_root()/file_name),"PNG"):
                    album.append({"id":asset_id,"file_name":file_name,"original_name":"剪贴板图片.png","added_at":datetime.now().isoformat(timespec="seconds")});added+=1
                    if not item.get("cover_id"):item["cover_id"]=asset_id
            except Exception as error:LOGGER.warning("指令相册剪贴板图片导入失败：%s",error)
        if added:
            self.save_instruction_album_record(item);self.refresh_instruction_list();self.refresh_instruction_album()
            if source_name=="添加":QMessageBox.information(self,"已添加图片",f"已添加 {added} 张作品图片。")
        elif source_name=="添加":QMessageBox.warning(self,"未添加图片","没有可读取的图片文件。")
    def instruction_album_add_images(self):
        paths,_=QFileDialog.getOpenFileNames(self,"添加作品图片","","图片文件 (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff);;所有文件 (*.*)")
        if paths:self.instruction_album_receive(paths,None,"添加")
    def instruction_album_set_cover(self):
        item=self.selected_instruction_record();selected=self.instruction_album_list.currentItem() if hasattr(self,"instruction_album_list") else None
        if not item or selected is None:QMessageBox.information(self,"选择图片","请先在相册中点击一张图片，再设为封面。");return
        item["cover_id"]=str(selected.data(Qt.UserRole) or "");self.save_instruction_album_record(item);self.refresh_instruction_list();self.refresh_instruction_album()
    def instruction_album_remove_selected(self):
        item=self.selected_instruction_record();selected=self.instruction_album_list.currentItem() if hasattr(self,"instruction_album_list") else None
        if not item or selected is None:QMessageBox.information(self,"选择图片","请先在相册中点击要移除的图片。");return
        asset_id=str(selected.data(Qt.UserRole) or "");item["album"]=[entry for entry in item.get("album",[]) if not isinstance(entry,dict) or str(entry.get("id","") or "")!=asset_id]
        if str(item.get("cover_id","") or "")==asset_id:item["cover_id"]=str((item["album"][0].get("id","") if item["album"] else "") or "")
        self.save_instruction_album_record(item);self.refresh_instruction_list();self.refresh_instruction_album()
    def instruction_album_open_viewer(self,*_):
        item=self.selected_instruction_record()
        entries=[entry for entry in (item.get("album",[]) if isinstance(item,dict) else []) if isinstance(entry,dict) and (self.instruction_album_path(entry) or Path()).is_file()]
        if not entries:
            QMessageBox.information(self,"暂无相册图片","当前指令还没有可查看的相册图片。")
            return
        cover_id=str(item.get("cover_id","") or "");position=next((i for i,entry in enumerate(entries) if str(entry.get("id","") or "")==cover_id),0)
        dialog,layout=self.themed_dialog("相册查看 · "+str(item.get("name") or "当前指令"),980,720);dialog.setProperty("keyboard_submit_enabled",False)
        hint=QLabel("使用“上一张 / 下一张”浏览相册；此查看器不会修改图片或指令内容。")
        hint.setWordWrap(True);layout.addWidget(hint)
        image=QLabel();image.setAlignment(Qt.AlignCenter);image.setMinimumSize(580,430);image.setStyleSheet("background:rgba(20,28,38,235);border-radius:10px;padding:10px;");layout.addWidget(image,1)
        status=QLabel();status.setAlignment(Qt.AlignCenter);layout.addWidget(status)
        controls=QHBoxLayout();previous=self.btn("← 上一张",lambda:None,"warning");next_button=self.btn("下一张 →",lambda:None,"primary");close=self.btn("关闭",dialog.accept);controls.addWidget(previous);controls.addWidget(next_button);controls.addStretch();controls.addWidget(close);layout.addLayout(controls)
        def render(index):
            nonlocal position
            position=index%len(entries);entry=entries[position];path=self.instruction_album_path(entry);pixmap=QPixmap(str(path))
            if pixmap.isNull():image.setText("图片无法读取");image.setPixmap(QPixmap())
            else:image.setPixmap(pixmap.scaled(image.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation));image.setText("")
            status.setText(f"{position+1} / {len(entries)}　{entry.get('original_name') or path.name}")
        previous.clicked.connect(lambda:render(position-1));next_button.clicked.connect(lambda:render(position+1));render(position);dialog.exec()
    def instruction_album_open_selected(self,*_):
        item=self.selected_instruction_record();selected=self.instruction_album_list.currentItem() if hasattr(self,"instruction_album_list") else None
        if not item or selected is None:return
        asset_id=str(selected.data(Qt.UserRole) or "")
        for entry in item.get("album",[]):
            if isinstance(entry,dict) and str(entry.get("id","") or "")==asset_id:
                path=self.instruction_album_path(entry)
                if path and path.is_file():QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
                return
    def select_instruction(self):
        selected=self.ilist.selectedItems()
        if len(selected)!=1:return
        index=selected[0].data(0,Qt.UserRole)
        if isinstance(index,dict):
            self.inst_index=None;self.iname.clear();self.icontent.clear();self.inote.clear();self.refresh_folder_choices();self.ifolder.setCurrentText(index["folder"]);self.set_instruction_editable(False);self.refresh_instruction_album();return
        if not isinstance(index,int):return
        items=instructions();self.inst_index=index;x=items[index];self.iname.setText(x.get("name", ""));self.refresh_folder_choices();self.ifolder.setCurrentText(x.get("folder", "未分类") or "未分类");self.icontent.setPlainText(x.get("content", ""));self.inote.setPlainText(x.get("note", ""));self.set_instruction_editable(False);self.refresh_instruction_album()
    def edit_instruction(self):
        if self.inst_index is None: QMessageBox.information(self,"未选择指令","请先选择或双击一条指令。"); return
        self.open_instruction_editor(index=self.inst_index)
    def open_instruction_editor(self,index=None,folder=""):
        """以大窗口编辑指令，避免在工作区误触并保留完整内容的阅读空间。"""
        existing=getattr(self,"_instruction_click_away_dialog",None)
        if isinstance(existing,QDialog) and existing.isVisible():
            if existing.isMinimized():existing.showNormal()
            existing.raise_();existing.activateWindow();return
        items=instructions();current=items[index] if isinstance(index,int) and 0<=index<len(items) else {}
        dialog,layout=self.themed_dialog("编辑指令" if current else "新建指令",760,590)
        # 编辑指令时，空格和回车属于内容输入，绝不允许触发默认保存按钮。
        # 非模态显示让“点击此弹窗以外的软件区域即保存”成为可实现、可预期的行为。
        dialog.setProperty("keyboard_submit_enabled",False);dialog.setProperty("instruction_click_away_ready",False);dialog.setProperty("instruction_click_away_armed",False);dialog.setModal(False);dialog.setWindowModality(Qt.NonModal)
        hint=QLabel("请填写指令名称、所属分类与详细指令。名称栏按 Enter 可直接保存；详细指令和备注中使用 Ctrl+Enter 保存，普通 Enter 保留为换行。保存后将立即写入指令库。");hint.setWordWrap(True);layout.addWidget(hint)
        form=QFormLayout();category=QComboBox();folders=self.instruction_folders() or ["未分类"];category.addItems(folders);category.setCurrentText(current.get("folder","") or folder or folders[0]);name=QLineEdit(current.get("name", ""));content=QTextEdit();content.setPlainText(str(current.get("content", "") or ""));content.setMinimumHeight(240);note=QTextEdit();note.setPlainText(str(current.get("note", "") or ""));note.setFixedHeight(86);form.addRow("所属分类",category);form.addRow("指令名称",name);form.addRow("详细指令",content);form.addRow("备注",note);layout.addLayout(form,1)
        # btn() 的通用连接器会无条件调用传入槽函数；这里先提供安全空操作，
        # 再在下方连接带校验的真实保存回调，避免点击时错误调用 None 而崩溃。
        # 此窗口曾把“取消”作为首个自动默认按钮；Windows/Qt 在 QLineEdit、
        # QComboBox 等控件按 Enter 时会把它误当成默认操作，造成编辑被取消。
        # 保存是唯一默认按钮，取消只能由用户明确点击或按 Esc 触发。
        buttons=QHBoxLayout();buttons.addStretch();cancel_button=self.btn("取消",dialog.reject);cancel_button.setAutoDefault(False);cancel_button.setDefault(False);buttons.addWidget(cancel_button);save_button=self.btn("保存指令",lambda:None,"primary");save_button.setAutoDefault(True);save_button.setDefault(True);buttons.addWidget(save_button);layout.addLayout(buttons)
        target_index=index
        def commit_instruction(show_validation=False):
            nonlocal target_index
            # 两步窗口外确认只是“尝试保存”；新建指令尚未填写名称时保持编辑
            # 状态即可，不能把一次外部按键变成打断输入的错误弹窗。
            detail=content.toPlainText();note_text=note.toPlainText().strip()
            resolved_name=name.text().strip() or self.suggest_instruction_name(detail) or self.suggest_instruction_name(note_text)
            if not resolved_name:
                if show_validation:QMessageBox.warning(self,"无法保存空指令","指令名称、详细指令和备注均为空，请至少填写一项内容。")
                return
            if not name.text().strip():name.setText(resolved_name)
            record=dict(current) if isinstance(current,dict) else {}
            record.update({"id":str(record.get("id") or uuid.uuid4().hex),"name":resolved_name,"folder":category.currentText() or "未分类","content":detail,"note":note_text})
            record.setdefault("album",[]);record.setdefault("cover_id","")
            duplicate=next((item for item_index,item in enumerate(items) if item_index!=target_index and isinstance(item,dict) and str(item.get("name","") or "").strip().casefold()==resolved_name.casefold()),None)
            if duplicate:
                QMessageBox.warning(dialog,"指令名称已存在",f'指令库中已经有“{duplicate.get("name")}”。\n\n请使用一个不同的名称，避免分类、搜索、相册和工作台引用发生歧义。')
                return
            if current:items[target_index]=record
            else:target_index=len(items);items.append(record)
            previous_name=str(current.get("name","") or "");save_instructions(items);self.refresh_instruction_list();self.sync_workspace_instruction_preview(record["name"],previous_name);self.inst_index=target_index;self.iname.setText(record["name"]);self.refresh_folder_choices();self.ifolder.setCurrentText(record["folder"]);self.icontent.setPlainText(record["content"]);self.inote.setPlainText(record["note"]);self.set_instruction_editable(False);self._instruction_click_away_dialog=None;dialog.accept()
        save_button.clicked.connect(lambda:commit_instruction(True))
        # 名称是单行输入，Enter 必须保存而不能落到取消；正文仍允许 Enter 换行，
        # 需要从正文保存时可使用 Ctrl+Enter，兼顾快捷保存与多行指令格式。
        name.returnPressed.connect(lambda:commit_instruction(True))
        save_shortcut=QShortcut(QKeySequence("Ctrl+Return"),dialog);save_shortcut.activated.connect(lambda:commit_instruction(True));dialog._instruction_save_shortcut=save_shortcut
        dialog._instruction_editor_commit=commit_instruction;self._instruction_click_away_dialog=dialog;dialog.finished.connect(lambda *_:setattr(self,"_instruction_click_away_dialog",None));dialog.show();dialog.raise_();dialog.activateWindow();name.setFocus();QTimer.singleShot(180,lambda current=dialog:current.setProperty("instruction_click_away_ready",True) if current.isVisible() else None)
    def save_instruction(self):
        # 弹框编辑器打开时，底层页面仍在后台可见。任何快捷键、默认按钮或旧连接
        # 都不得绕过弹框直接调用这里，否则会对尚未填写名称的新建指令反复报错。
        editor_dialog=getattr(self,"_instruction_click_away_dialog",None)
        if isinstance(editor_dialog,QDialog) and editor_dialog.isVisible():return
        if not self.instruction_editing:QMessageBox.information(self,"只读模式","请双击指令或点击“编辑指令”后再保存。");return
        detail=self.icontent.toPlainText();note_text=self.inote.toPlainText().strip();resolved_name=self.iname.text().strip() or self.suggest_instruction_name(detail) or self.suggest_instruction_name(note_text)
        if not resolved_name:QMessageBox.warning(self,"无法保存空指令","指令名称、详细指令和备注均为空，请至少填写一项内容。");return
        if not self.iname.text().strip():self.iname.setText(resolved_name)
        items=instructions();existing=items[self.inst_index] if isinstance(self.inst_index,int) and 0<=self.inst_index<len(items) and isinstance(items[self.inst_index],dict) else {};x=dict(existing);x.update({"id":str(x.get("id") or uuid.uuid4().hex),"name":resolved_name,"folder":self.ifolder.currentText() or "未分类","content":detail,"note":note_text});x.setdefault("album",[]);x.setdefault("cover_id","")
        duplicate=next((item for item_index,item in enumerate(items) if item_index!=self.inst_index and isinstance(item,dict) and str(item.get("name","") or "").strip().casefold()==resolved_name.casefold()),None)
        if duplicate:QMessageBox.warning(self,"指令名称已存在",f'指令库中已经有“{duplicate.get("name")}”。请使用一个不同的名称。');return
        previous_name=""
        if self.inst_index is None or self.inst_index>=len(items):items.append(x);index=len(items)-1
        else:previous_name=str(items[self.inst_index].get("name","") or "");items[self.inst_index]=x;index=self.inst_index
        save_instructions(items);self.refresh_instruction_list();self.sync_workspace_instruction_preview(x["name"],previous_name);self.set_instruction_editable(False);self.refresh_instruction_album()
    def delete_instruction(self,index=None):
        items=instructions();index=self.inst_index if index is None else index
        if index is None or index>=len(items):QMessageBox.information(self,"未选择指令","请先在左侧选择要删除的指令。");return
        if QMessageBox.question(self,"确认删除指令",f"即将删除指令“{items[index].get('name','当前指令')}”。\n\n删除后无法恢复，是否确认删除？")!=QMessageBox.Yes:return
        items.pop(index);save_instructions(items);self.inst_index=None;self.iname.clear();self.icontent.clear();self.inote.clear();self.refresh_folder_choices();self.set_instruction_editable(False);self.refresh_instruction_list()
    def selected_folder(self):
        selected=self.ilist.selectedItems()
        if len(selected)==1 and isinstance(selected[0].data(0,Qt.UserRole),dict):return selected[0].data(0,Qt.UserRole)["folder"]
        return ""
    def themed_text_dialog(self,title,label,initial=""):
        dialog,layout=self.themed_dialog(title,440,180);layout.addWidget(QLabel(label));field=QLineEdit(initial);layout.addWidget(field);buttons=QHBoxLayout();buttons.addStretch();buttons.addWidget(self.btn("取消",dialog.reject));buttons.addWidget(self.btn("确认",dialog.accept,"primary"));layout.addLayout(buttons);field.setFocus();return (field.text().strip(),True) if dialog.exec()==QDialog.Accepted else ("",False)
    def themed_choice_dialog(self,title,label,choices,current=""):
        dialog,layout=self.themed_dialog(title,460,190);layout.addWidget(QLabel(label));field=QComboBox();field.addItems(choices);field.setCurrentText(current if current in choices else (choices[0] if choices else ""));layout.addWidget(field);buttons=QHBoxLayout();buttons.addStretch();buttons.addWidget(self.btn("取消",dialog.reject));buttons.addWidget(self.btn("确认",dialog.accept,"primary"));layout.addLayout(buttons);field.setFocus();return (field.currentText(),True) if dialog.exec()==QDialog.Accepted else ("",False)
    def _instruction_context_target_folder(self,item):
        data=item.data(0,Qt.UserRole) if item else None
        if isinstance(data,dict):return data.get("folder","")
        parent=item.parent() if item else None;parent_data=parent.data(0,Qt.UserRole) if parent else None
        return parent_data.get("folder","") if isinstance(parent_data,dict) else ""
    def _instruction_unique_name(self,base,existing):
        candidate=(base or "未命名指令").strip()+" 副本";number=2
        while candidate in existing:candidate=(base or "未命名指令").strip()+f" 副本 {number}";number+=1
        return candidate
    def _instruction_unique_folder(self,base,existing):
        candidate=(base or "新分类").strip()+" 副本";number=2
        while candidate in existing:candidate=(base or "新分类").strip()+f" 副本 {number}";number+=1
        return candidate
    def _copy_instruction_context(self,item,cut=False):
        data=item.data(0,Qt.UserRole) if item else None
        if isinstance(data,int):
            values=instructions()
            if not (0<=data<len(values)):return
            self._instruction_clipboard={"kind":"instruction","cut":bool(cut),"items":[dict(values[data])]}
        elif isinstance(data,dict):
            folder=data.get("folder","")
            if not folder:return
            self._instruction_clipboard={"kind":"folder","cut":bool(cut),"folder":folder,"folders":[path for path in self.instruction_folders() if path==folder or path.startswith(folder+"/")],"items":[dict(entry) for entry in instructions() if (entry.get("folder","") or "")==folder or (entry.get("folder","") or "").startswith(folder+"/")]}
        else:return
        self._instruction_clipboard_source=item
    def _paste_instruction_context(self,target_folder):
        clip=getattr(self,"_instruction_clipboard",None) or {}
        if not target_folder or not clip:return
        folders=self.instruction_folders();items=instructions();kind=clip.get("kind");cut=bool(clip.get("cut"))
        if kind=="instruction":
            changed=False;existing={entry.get("name","") for entry in items}
            for entry in clip.get("items",[]):
                record=dict(entry);source_folder=record.get("folder","") or "未分类"
                if cut and source_folder==target_folder:continue
                if cut:
                    for current in items:
                        if current.get("name","")==record.get("name","") and (current.get("folder","") or "未分类")==source_folder:
                            current["folder"]=target_folder;changed=True;break
                else:
                    record["name"]=self._instruction_unique_name(record.get("name",""),existing);existing.add(record["name"]);record["folder"]=target_folder;items.append(record);changed=True
            if changed:save_instructions(items);self.refresh_instruction_list()
            if cut:self._instruction_clipboard=None
            return
        if kind!="folder":return
        source=str(clip.get("folder","") or "")
        if not source or target_folder==source or target_folder.startswith(source+"/"):
            QMessageBox.warning(self,"无法粘贴分类","不能把分类粘贴到自身或自己的子分类中。");return
        base=source.rsplit("/",1)[-1];root=target_folder+"/"+(base if cut else self._instruction_unique_folder(base,{path.rsplit("/",1)[-1] for path in folders if path.rsplit("/",1)[0] if "/" in path}))
        if cut and any(path==root or path.startswith(root+"/") for path in folders if path!=source and not path.startswith(source+"/")):
            QMessageBox.warning(self,"分类名称冲突",f"目标分类下已存在“{base}”。");return
        def relocated(path):return root+path[len(source):] if path==source or path.startswith(source+"/") else path
        if cut:
            new_folders=[relocated(path) for path in folders]
            for entry in items:entry["folder"]=relocated(entry.get("folder","") or "未分类")
            self.save_instruction_folders(new_folders);save_instructions(items);self._instruction_clipboard=None
        else:
            copied_folders=[relocated(path) for path in clip.get("folders",[])];folders.extend(path for path in copied_folders if path not in folders)
            existing={entry.get("name","") for entry in items}
            for entry in clip.get("items",[]):
                record=dict(entry);record["name"]=self._instruction_unique_name(record.get("name",""),existing);existing.add(record["name"]);record["folder"]=relocated(record.get("folder","") or source);items.append(record)
            self.save_instruction_folders(folders);save_instructions(items)
        self.refresh_instruction_list()
    def _move_instruction_context(self,item):
        folders=self.instruction_folders();current=self._instruction_context_target_folder(item)
        choices=[folder for folder in folders if folder!=current]
        if not choices:QMessageBox.information(self,"没有可移动目标","请先创建另一个分类。 ");return
        target,ok=self.themed_choice_dialog("移动到分类","目标分类：",choices,choices[0])
        if not ok:return
        self._copy_instruction_context(item,cut=True);self._paste_instruction_context(target)
    def _copy_instruction_text(self,index):
        values=instructions()
        if not isinstance(index,int) or not (0<=index<len(values)):return
        entry=values[index];text=entry.get("content","") or ""
        QApplication.clipboard().setText(text)
    def copy_current_instruction_content(self):
        """复制编辑框现有全文，包含尚未保存的修改，方便直接交给 AI 使用。"""
        text=self.icontent.toPlainText() if hasattr(self,"icontent") else ""
        if not text.strip():
            QMessageBox.information(self,"没有可复制的内容","当前指令内容为空。")
            return
        QApplication.clipboard().setText(text)
        button=getattr(self,"copy_instruction_content_button",None)
        if button is not None:
            button.setText("已复制")
            QTimer.singleShot(1200,lambda target=button:target.setText("复制指令内容") if target is not None else None)
    def _export_instruction_context(self,item):
        data=item.data(0,Qt.UserRole) if item else None;values=instructions()
        if isinstance(data,int) and 0<=data<len(values):self.preview_instruction_export([values[data]]);return
        if isinstance(data,dict):
            folder=data.get("folder","");self.preview_instruction_export([entry for entry in values if (entry.get("folder","") or "")==folder or (entry.get("folder","") or "").startswith(folder+"/")])
    def instruction_context_menu(self,position):
        item=self.ilist.itemAt(position)
        if not item:return
        if item not in self.ilist.selectedItems():self.ilist.setCurrentItem(item)
        data=item.data(0,Qt.UserRole);target_folder=self._instruction_context_target_folder(item);menu=QMenu(self);configure_readable_menu(menu,self.accent)
        if isinstance(data,dict):
            new_folder=menu.addAction("新建子分类");new_instruction=menu.addAction("新建指令");rename=menu.addAction("重命名分类")
        else:
            edit=menu.addAction("编辑指令");duplicate=menu.addAction("复制为新指令");copy_text=menu.addAction("复制指令内容")
        menu.addSeparator();cut=menu.addAction("剪切");copy=menu.addAction("复制");paste=menu.addAction("粘贴到此分类");paste.setEnabled(bool(getattr(self,"_instruction_clipboard",None)) and bool(target_folder));move=menu.addAction("移动到分类…")
        menu.addSeparator();export=menu.addAction("导出此项");refresh=menu.addAction("刷新指令库");menu.addSeparator();remove=menu.addAction("删除分类" if isinstance(data,dict) else "删除指令")
        action=menu.exec(self.ilist.viewport().mapToGlobal(position))
        if isinstance(data,dict):
            if action==new_folder:self.new_instruction_folder()
            elif action==new_instruction:self.new_instruction_in_folder(data["folder"])
            elif action==rename:self.handle_tree_double_click(item)
        else:
            if action==edit:self.open_instruction_editor(index=data)
            elif action==duplicate:self._copy_instruction_context(item,cut=False);self._paste_instruction_context(target_folder)
            elif action==copy_text:self._copy_instruction_text(data)
        if action==cut:self._copy_instruction_context(item,cut=True)
        elif action==copy:self._copy_instruction_context(item,cut=False)
        elif action==paste:self._paste_instruction_context(target_folder)
        elif action==move:self._move_instruction_context(item)
        elif action==export:self._export_instruction_context(item)
        elif action==refresh:self.refresh_instruction_list()
        elif action==remove:
            if isinstance(data,dict):self.delete_instruction_folder()
            else:self.delete_instruction(data)
    def new_instruction_in_folder(self,folder):
        self.open_instruction_editor(folder=folder)
    def new_instruction_folder(self):
        parent=self.selected_folder();name,ok=self.themed_text_dialog("新建指令分类","分类名称：")
        if not ok or not name.strip() or "/" in name:return
        folder=(parent+"/" if parent else "")+name.strip()
        if folder in self.instruction_folders():QMessageBox.information(self,"分类已存在",f"分类“{folder}”已经存在。请使用其他名称。");return
        self.save_instruction_folders(self.instruction_folders()+[folder]);self.refresh_instruction_list()
    def delete_instruction_folder(self):
        selected=self.ilist.selectedItems()
        if len(selected)!=1 or not isinstance(selected[0].data(0,Qt.UserRole),dict):QMessageBox.warning(self,"未选择分类","请先选择一个分类文件夹，再执行删除。");return
        folder=selected[0].data(0,Qt.UserRole)["folder"]
        direct=[item for item in instructions() if (item.get("folder","") or "")==folder]
        nested=[item for item in instructions() if (item.get("folder","") or "").startswith(folder+"/")]
        if direct or nested:
            names="、".join(item.get("name","未命名指令") for item in (direct+nested)[:3]);more="" if len(direct)+len(nested)<=3 else " 等"
            QMessageBox.warning(self,"无法删除分类",f"分类“{folder}”及其子分类中共有 {len(direct)+len(nested)} 条指令（例如：{names}{more}）。\n\n为保护指令数据，不能删除该分类。请先将指令移动到其他分类，或删除指令后再试。");return
        if any(path.startswith(folder+"/") for path in self.instruction_folders()):QMessageBox.warning(self,"无法删除分类",f"分类“{folder}”仍包含子分类。请先删除其中的空子分类后再试。");return
        if QMessageBox.question(self,"删除分类",f"删除空分类“{folder}”？")==QMessageBox.Yes:
            self.save_instruction_folders([path for path in self.instruction_folders() if path!=folder]);self.refresh_instruction_list()
    def handle_tree_double_click(self,item,*_):
        data=item.data(0,Qt.UserRole)
        if isinstance(data,dict):
            old=data["folder"];name,ok=self.themed_text_dialog("重命名分类","分类名称：",old.rsplit("/",1)[-1])
            if not ok or not name.strip() or "/" in name:return
            new=(old.rsplit("/",1)[0]+"/" if "/" in old else "")+name.strip();folders=self.instruction_folders(); affected=[path for path in folders if path==old or path.startswith(old+"/")]; unchanged=[path for path in folders if path not in affected]; renamed=[new+path[len(old):] for path in affected]
            if len(set(renamed))!=len(renamed) or any(path in unchanged for path in renamed):QMessageBox.information(self,"分类名称冲突",f"不能改为“{new}”，该路径或其子路径已存在。为保护指令归属，未执行改名。");return
            items=instructions()
            for entry in items:
                folder=entry.get("folder","") or "未分类"
                if folder==old or folder.startswith(old+"/"):entry["folder"]=new+folder[len(old):]
            ordered_renamed=[new+path[len(old):] if path==old or path.startswith(old+"/") else path for path in folders]
            save_instructions(items);self.save_instruction_folders(ordered_renamed);self.refresh_instruction_list()
        else:self.edit_instruction()
    def move_selected_instructions(self,target,dragged_items=None):
        data=target.data(0,Qt.UserRole);folder=data.get("folder") if isinstance(data,dict) else (target.parent().data(0,Qt.UserRole).get("folder") if target.parent() and isinstance(target.parent().data(0,Qt.UserRole),dict) else None)
        if not folder:return
        selected=dragged_items if dragged_items is not None else self.ilist.selectedItems();folder_sources=[item.data(0,Qt.UserRole)["folder"] for item in selected if isinstance(item.data(0,Qt.UserRole),dict)]
        # 多选时只处理最上层分类；其子分类会跟随父级一起移动一次。
        folder_sources=[path for path in folder_sources if not any(path.startswith(parent+"/") for parent in folder_sources if parent!=path)]
        if folder_sources:
            if any(folder==source or folder.startswith(source+"/") for source in folder_sources):
                QMessageBox.warning(self,"无法移动分类","不能将分类移动到自身或自己的子分类中。");self.refresh_instruction_list();return
            folders=self.instruction_folders();new_roots={source:folder+"/"+source.rsplit("/",1)[-1] for source in folder_sources}
            if any(root in folders and root not in folder_sources for root in new_roots.values()):
                QMessageBox.warning(self,"分类名称冲突","目标分类下已存在同名子分类，未执行移动。");self.refresh_instruction_list();return
            def relocated(path):
                for source,new_root in new_roots.items():
                    if path==source or path.startswith(source+"/"):return new_root+path[len(source):]
                return path
            updated_folders=[relocated(path) for path in folders]
            if len(set(updated_folders))!=len(updated_folders):
                QMessageBox.warning(self,"分类名称冲突","移动后会产生重名分类，未执行移动。");self.refresh_instruction_list();return
            items=instructions()
            for entry in items:
                current=entry.get("folder","") or "未分类";entry["folder"]=relocated(current)
            save_instructions(items);self.save_instruction_folders(updated_folders);self.refresh_instruction_list();return
        items=instructions();changed=False
        for item in selected:
            index=item.data(0,Qt.UserRole)
            if isinstance(index,int) and (items[index].get("folder","") or "未分类")!=folder:items[index]["folder"]=folder;changed=True
        if changed:save_instructions(items)
        self.refresh_instruction_list()
    def export_instruction_items(self,items,label):
        if not items: QMessageBox.information(self,"没有指令","没有可导出的指令。"); return
        format_name=self.transfer_format.currentText(); suffix={"Excel 工作簿 (.xlsx)":".xlsx","CSV (.csv)":".csv","JSON (.json)":".json"}[format_name]; start=str(Path(self.settings.get("last_instruction_dir",str(DATA_DIR)))/("指令库"+suffix)); filters="Excel 工作簿 (*.xlsx);;CSV 文件 (*.csv);;JSON 文件 (*.json)"
        filename,_=QFileDialog.getSaveFileName(self,"导出"+label,start,filters)
        if not filename:return
        target=Path(filename)
        if target.suffix.lower() not in (".csv",".xlsx",".json"): target=target.with_suffix(suffix)
        try: export_instruction_items(items,target,self.transfer_encoding.currentText());self.settings["last_instruction_dir"]=str(target.parent);save_app_settings(self.settings);QMessageBox.information(self,"导出完成",f"已导出 {len(items)} 条指令。\n{target}")
        except Exception as error: LOGGER.exception("导出指令失败");QMessageBox.warning(self,"导出失败",str(error))
    def export_selected_instruction(self):
        indices=[item.data(0,Qt.UserRole) for item in self.ilist.selectedItems() if isinstance(item.data(0,Qt.UserRole),int)]
        if not indices: QMessageBox.information(self,"未选择指令","请先选择一条或多条指令（可按 Ctrl 多选）。"); return
        self.preview_instruction_export([instructions()[index] for index in indices])
    def export_all_instructions(self): self.preview_instruction_export(instructions())
    def preview_instruction_export(self,items):
        self.preview_instruction_import(items,"导出预览",export_mode=True)
    def import_instructions(self):
        folders=self.instruction_folders()
        if not folders:
            QMessageBox.information(self,"尚无分类","请先创建一个指令分类，再导入指令。");return
        selected_folder=self.selected_folder()
        folder,ok=self.themed_choice_dialog("选择导入分类","导入到分类：",folders,selected_folder)
        if not ok:return
        filename,_=QFileDialog.getOpenFileName(self,"导入指令",self.settings.get("last_instruction_dir",""),"Excel 工作簿 (*.xlsx);;CSV 文件 (*.csv);;JSON 文件 (*.json)")
        if not filename:return
        try: incoming=import_instruction_items(Path(filename),self.transfer_encoding.currentText())
        except Exception as error: LOGGER.exception("读取指令导入文件失败");QMessageBox.warning(self,"导入失败",str(error));return
        for item in incoming:item["folder"]=folder
        self.settings["last_instruction_dir"]=str(Path(filename).parent);save_app_settings(self.settings);self.preview_instruction_import(incoming,Path(filename).name)
    def preview_instruction_import(self,incoming,source,export_mode=False):
        existing={item.get("name","") for item in instructions()}; duplicates=sum(1 for item in incoming if item.get("name","") in existing)
        dialog,layout=self.themed_dialog("导出预览" if export_mode else "导入 / 合并指令预览",860,520); layout.addWidget(QLabel(f"来源：{source}；读取 {len(incoming)} 条。可勾选并编辑后再{'导出' if export_mode else '导入'}。"))
        mode=QComboBox(); mode.addItems(("合并：重名指令覆盖现有内容","合并：保留现有指令，跳过重名","替换：用导入内容替换整个指令库"));
        if not export_mode: layout.addWidget(mode)
        table=QTableWidget(len(incoming),5); table.setHorizontalHeaderLabels(("选择","指令名称","分类","详细指令","备注")); table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for row,item in enumerate(incoming):
            check=QTableWidgetItem();check.setCheckState(Qt.Checked);table.setItem(row,0,check)
            for col,key in enumerate(("name","folder","content","note"),1): table.setItem(row,col,QTableWidgetItem(item.get(key,"")))
        layout.addWidget(table,1); buttons=QHBoxLayout(); buttons.addStretch(); cancel=self.btn("取消",dialog.reject); confirm=self.btn("确认导出" if export_mode else "确认导入",dialog.accept,"primary");buttons.addWidget(cancel);buttons.addWidget(confirm);layout.addLayout(buttons)
        if dialog.exec()!=QDialog.Accepted:return
        incoming=[{"name":table.item(row,1).text(),"folder":table.item(row,2).text() or "未分类","content":table.item(row,3).text(),"note":table.item(row,4).text()} for row in range(table.rowCount()) if table.item(row,0).checkState()==Qt.Checked and table.item(row,1).text().strip()]
        if export_mode:self.export_instruction_items(incoming,"预览选择的指令");return
        mode_index=mode.currentIndex(); current=instructions()
        if mode_index==2: merged=incoming
        else:
            by_name={item.get("name",""):dict(item) for item in current}
            for item in incoming:
                if item["name"] not in by_name or mode_index==0: by_name[item["name"]]=item
            merged=list(by_name.values())
        save_instructions(merged);add_history({"project":"","operation":"导入/合并指令","result":f"{len(incoming)} 条来源数据，现有 {len(merged)} 条指令"});self.refresh_instruction_options();self.refresh_instruction_list();self.new_instruction();QMessageBox.information(self,"指令库已更新",f"已完成导入/合并，当前共有 {len(merged)} 条指令。")
    def pick_temp_dir(self):
        directory=QFileDialog.getExistingDirectory(self,"选择临时资料目录",self.temp_path.text())
        if directory:self.temp_path.setText(directory)
    def pick_config_dir(self):
        directory=QFileDialog.getExistingDirectory(self,"选择用户配置目录",self.config_path.text())
        if directory:self.config_path.setText(directory)
    def pick_log_dir(self):
        directory=QFileDialog.getExistingDirectory(self,"选择日志目录",self.log_path.text())
        if directory:self.log_path.setText(directory)
    def migrate_viewer_temp_records(self,new_temp_root):
        """切换临时资料目录时迁移表格快照，并同步记录里的绝对路径。"""
        old_root=Path(self.settings.get("temp_data_dir",str(DATA_DIR/"temporary")))/"table-viewer";new_root=Path(new_temp_root)/"table-viewer"
        if old_root.resolve()==new_root.resolve():return 0
        new_root.mkdir(parents=True,exist_ok=True);moved=0;records=self.settings.get("viewer_temp_records",[])
        for record in records if isinstance(records,list) else []:
            source=Path(record.get("file","") or "")
            if not source.is_file():continue
            destination=new_root/source.name
            if destination.exists():destination=new_root/(source.stem+"-"+datetime.now().strftime("%Y%m%d%H%M%S%f")+source.suffix)
            try:shutil.move(str(source),str(destination));record["file"]=str(destination);moved+=1
            except OSError:LOGGER.exception("迁移临时表格快照失败：%s",source)
        self.settings["viewer_temp_records"]=records if isinstance(records,list) else []
        return moved
    def save_system_settings(self):
        path=self.temp_path.text().strip()
        if path: Path(path).mkdir(parents=True,exist_ok=True)
        log_path=self.log_path.text().strip()
        if log_path: Path(log_path).mkdir(parents=True,exist_ok=True)
        target=self.config_path.text().strip();moved=self.migrate_viewer_temp_records(path) if path else 0;scale=float(self.ui_scale_box.currentData()) if hasattr(self,"ui_scale_box") else 1.0;self.settings.update({"temp_data_dir":path,"log_dir":log_path,"ui_scale_preference":scale});save_app_settings(self.settings)
        if hasattr(self,"snapshot_path"):self.snapshot_path.setText(str(Path(path)/"table-viewer") if path else str(DATA_DIR/"temporary"/"table-viewer"))
        if target and Path(target).resolve()!=DATA_DIR.resolve(): set_data_directory(Path(target))
        QMessageBox.information(self,"系统设置已保存",f"设置已保存。{'已迁移 '+str(moved)+' 份临时表格记录。' if moved else ''}若更改了配置目录、日志目录或界面缩放，请重启软件后加载新配置。")
    def backup_config(self):
        filename,_=QFileDialog.getSaveFileName(self,"备份配置",str(DATA_DIR/"video-task-hub-backup.zip"),"配置备份 (*.zip)")
        if filename:
            try:backup_configuration(Path(filename));QMessageBox.information(self,"备份完成",filename)
            except Exception as error:QMessageBox.warning(self,"备份失败",str(error))
    def restore_config(self):
        filename,_=QFileDialog.getOpenFileName(self,"恢复配置备份","","配置备份 (*.zip)")
        if filename and QMessageBox.question(self,"恢复配置","恢复会覆盖同名配置文件，建议先备份。继续？")==QMessageBox.Yes:
            try:restore_configuration(Path(filename));QMessageBox.information(self,"恢复完成","配置已恢复，请重启软件加载。")
            except Exception as error:QMessageBox.warning(self,"恢复失败",str(error))
    def initialize_config(self):
        if QMessageBox.question(self,"初始化配置","将清空当前项目列表、指令库、历史和皮肤设置。不会删除素材、导出文件或备份包。继续？")==QMessageBox.Yes:
            initialize_configuration();QMessageBox.information(self,"初始化完成","配置已初始化，请重启软件。")
    def refresh_history(self):
        self.hlist.clear()
        for x in history():self.hlist.addItem(f"{x.get('time','')}  |  {x.get('project','')}  |  {x.get('operation','')}\n{x.get('result','')}  {x.get('file','')}")
    def clear_history(self):
        if QMessageBox.question(self,"清空操作历史记录","将清空全部操作历史。\n\n不会删除项目、素材、导出文件或系统日志。继续？")==QMessageBox.Yes:clear_history();self.refresh_history()
    def refresh_runtime_status(self):
        """刷新仅属于当前软件进程的执行日志，不把常规运行记录持久化。"""
        text=self.runtime_log_handler.text() if hasattr(self,"runtime_log_handler") else ""
        lines=[line for line in text.splitlines() if line.strip()]
        latest=lines[-1] if lines else "暂无运行日志，软件处于就绪状态。"
        if hasattr(self,"runtime_status_summary"):self.runtime_status_summary.setText("运行状态："+latest[-220:])
        if hasattr(self,"runtime_log_display") and self.runtime_status_panel.isVisible():
            shown="\n".join(lines[-160:]) or "暂无运行日志。"
            if self.runtime_log_display.toPlainText()!=shown:
                self.runtime_log_display.setPlainText(shown);self.runtime_log_display.moveCursor(QTextCursor.End)
    def toggle_runtime_status(self):
        if not hasattr(self,"runtime_status_panel"):return
        visible=not self.runtime_status_panel.isVisible();self.runtime_status_panel.setVisible(visible)
        if visible:self.refresh_runtime_status()
    def show_runtime_log_dialog(self):
        existing=getattr(self,"runtime_log_dialog",None)
        if existing and existing.isVisible():existing.raise_();existing.activateWindow();return
        dialog,layout=self.themed_dialog("详细运行日志（本次会话）",1120,720);dialog.setModal(False);dialog.setWindowModality(Qt.NonModal);self.runtime_log_dialog=dialog;hint=QLabel("显示本次启动后的实时执行日志，包括扫描、导入、导出、AI 匹配及异常。关闭软件后这些常规运行日志会自动释放；重要警告与错误仍可在“系统日志”中查看。");hint.setWordWrap(True);layout.addWidget(hint)
        display=QTextEdit();display.setObjectName("runtimeLogDisplay");display.setReadOnly(True);layout.addWidget(display,1)
        def refresh_dialog():
            display.setPlainText(self.runtime_log_handler.text() or "暂无本次会话运行日志。")
            display.moveCursor(QTextCursor.End)
        timer=QTimer(dialog);timer.setInterval(700);timer.timeout.connect(refresh_dialog);timer.start();dialog.finished.connect(timer.stop);dialog.finished.connect(lambda *_:setattr(self,"runtime_log_dialog",None));buttons=QHBoxLayout();buttons.addWidget(self.btn("刷新",refresh_dialog,"loadData"));buttons.addWidget(self.btn("查看系统错误日志",self.open_log_file,"openExport"));buttons.addWidget(self.btn("打开日志目录",self.open_log_directory,"openExportFolder"));buttons.addStretch();buttons.addWidget(self.btn("关闭",dialog.close,"primary"));layout.addLayout(buttons);refresh_dialog();dialog.show();dialog.raise_();dialog.activateWindow()
    def refresh_log(self):self.log_view.setPlainText(read_system_log());self.log_view.moveCursor(QTextCursor.End)
    def clear_log(self):
        if QMessageBox.question(self,"清空系统日志","将清空当前日志文件中的全部内容。\n\n此操作不会删除项目、指令库或操作历史，是否继续？")!=QMessageBox.Yes:return
        try:clear_system_log();self.refresh_log();QMessageBox.information(self,"系统日志已清空","日志内容已全部清理。后续软件操作会重新记录新的日志。")
        except OSError as error:LOGGER.exception("清空系统日志失败");QMessageBox.warning(self,"清空日志失败",str(error))
    def open_log_file(self):
        try:open_system_path(LOG_FILE)
        except OSError as error:LOGGER.exception("打开日志文件失败");QMessageBox.warning(self,"无法打开日志文件",str(error))
    def open_log_directory(self):
        try:open_system_path(LOG_DIR)
        except OSError as error:LOGGER.exception("打开日志目录失败");QMessageBox.warning(self,"无法打开日志目录",str(error))
    def set_background_editable(self,editable):
        self.skin_editing=editable; self.root.set_interactive(editable)
        if hasattr(self,"skin_preview"): self.skin_preview.set_interactive(editable)
    def unlock_background_position(self):
        if not self.skin_image.text().strip(): QMessageBox.information(self,"没有背景图片","请先选择背景图片后再调整位置。"); return
        self.set_background_editable(True)
    def choose_skin_image(self):
        filename,_=QFileDialog.getOpenFileName(self,"选择背景图片","","图片文件 (*.png *.jpg *.jpeg *.webp *.bmp *.gif)")
        if filename:
            source=Path(filename); assets=DATA_DIR/"assets"/"backgrounds";assets.mkdir(parents=True,exist_ok=True); target=assets/("background"+source.suffix.lower());shutil.copy2(source,target);self.skin_image.setText(str(target));self.reset_background_position();self.nav_opacity_slider.setValue(70);self.set_background_editable(True);self.apply_skin(False)
    def clear_skin_image(self):self.skin_image.clear();self.set_background_editable(False);self.reset_background_position();self.apply_skin(False)
    def choose_theme(self,name):
        if name in THEMES:self.theme_name=name;self.accent=THEMES[name];self.dark_theme=name in DARK_THEME_NAMES;self.apply_skin(False)
    def pick_color(self):
        color=QColorDialog.getColor(QColor(self.accent),self,"选择软件配色")
        if color.isValid():self.theme_name="自定义颜色";self.dark_theme=False;self.accent=color.name();self.theme_box.setCurrentText("自定义颜色");self.apply_skin(False)
    def extract_background_color(self):
        image=QPixmap(self.skin_image.text().strip())
        if image.isNull():QMessageBox.information(self,"无法提取配色","请先选择一张有效的背景图片。");return
        self.theme_name="自定义颜色";self.dark_theme=False;self.accent=image.toImage().scaled(1,1).pixelColor(0,0).name();self.theme_box.setCurrentText("自定义颜色");self.apply_skin(False)
    def opacity_changed(self,value):self.opacity_label.setText(f"{value}%");self.apply_skin(False)
    def nav_opacity_changed(self,value):self.nav_opacity=value;self.nav_opacity_label.setText(f"{value}%");self.apply_skin(False)
    def zoom_changed(self,value):self.set_background_editable(True);self.image_zoom=value/100;self.zoom_label.setText(f"{value}%");self.apply_skin(False)
    def preview_transform_changed(self,zoom,offset_x,offset_y):
        self.image_zoom=zoom;self.image_x=offset_x;self.image_y=offset_y;self.zoom_slider.blockSignals(True);self.zoom_slider.setValue(round(zoom*100));self.zoom_slider.blockSignals(False);self.zoom_label.setText(f"{round(zoom*100)}%");self.apply_skin(False)
    def reset_background_position(self):
        self.image_zoom=1;self.image_x=0;self.image_y=0
        if hasattr(self,"zoom_slider"):self.zoom_slider.blockSignals(True);self.zoom_slider.setValue(100);self.zoom_slider.blockSignals(False);self.zoom_label.setText("100%")
        self.apply_skin(False)
    def reset_skin(self):self.skin_image.clear();self.opacity.setValue(18);self.nav_opacity_slider.setValue(100);self.theme_name="天空蓝（默认）";self.dark_theme=False;self.accent=THEMES["天空蓝（默认）"];self.theme_box.setCurrentText("天空蓝（默认）");self.reset_background_position();self.apply_skin(True)
    def apply_skin(self,save):
        image=self.skin_image.text().strip() if hasattr(self,"skin_image") else self.settings.get("skin_background",""); opacity=self.opacity.value() if hasattr(self,"opacity") else int(self.settings.get("skin_opacity",18)); base="#101722" if self.dark_theme else "#F7F9F8";self.root.set_skin(image,opacity,base,self.image_zoom,self.image_x,self.image_y)
        if hasattr(self,"skin_preview"):self.skin_preview.set_skin(image,100,base,self.image_zoom,self.image_x,self.image_y)
        # 在 Qt 的系统 DPI 缩放之上追加分辨率比例字体，低分辨率保持可读且不裁切。
        scaled_font=max(11,round(13*self.ui_scale));menu_border=QColor(self.accent).lighter(145).name();menu_selected=QColor(self.accent).lighter(185).name();header_color=QColor(self.accent).darker(215).name();self.setStyleSheet(self.style()+f"\nQWidget{{font-size:{scaled_font}px;}}\nQTableWidget{{color:#172B3A;background:#FFFFFF;gridline-color:#7F94A3;selection-background-color:{self.accent};selection-color:#FFFFFF;}}QTableWidget::item{{color:#172B3A;background:#FFFFFF;border-right:1px solid #AABAC5;border-bottom:1px solid #AABAC5;padding:2px;}}QTableWidget::item:selected,QTableWidget::item:selected:active,QTableWidget::item:selected:!active{{color:#FFFFFF;background:{QColor(self.accent).darker(145).name()};border:2px solid #0F3D7A;}}QTableWidget QLineEdit{{color:#172B3A;background:#FFFFFF;selection-color:#FFFFFF;selection-background-color:{QColor(self.accent).darker(145).name()};border:2px solid {self.accent};border-radius:2px;padding:1px 3px;}}QHeaderView::section{{color:#FFFFFF;background:{header_color};border-right:1px solid {self.accent};border-bottom:1px solid {self.accent};font-weight:700;padding:6px;}}QMenu{{background:#FFFFFF;color:#172B3A;border:1px solid {menu_border};border-radius:6px;padding:4px;}}QMenu::item{{background:#FFFFFF;color:#172B3A;padding:8px 32px 8px 14px;border-radius:4px;}}QMenu::item:selected{{background:{menu_selected};color:#102A43;font-weight:600;}}QMenu::item:disabled{{background:#FFFFFF;color:#7A8793;}}QMenu::separator{{height:1px;background:#C9D4DD;margin:4px 8px;}}")
        if self.dark_theme:self.setStyleSheet(self.style()+f"\nQWidget{{font-size:{scaled_font}px;}}"+self.dark_style_overrides())
        if hasattr(self,"ilist"):self.refresh_instruction_list()
        if save:self.settings.update({"skin_background":image,"skin_opacity":opacity,"skin_accent":self.accent,"skin_theme":self.theme_name,"skin_zoom":self.image_zoom,"skin_offset_x":self.image_x,"skin_offset_y":self.image_y,"skin_nav_opacity":self.nav_opacity});save_app_settings(self.settings);self.set_background_editable(False);QMessageBox.information(self,"皮肤设置已保存","新的背景、透明度、导航雾化和配色已保存，背景位置已锁定。")

    def closeEvent(self,event):
        """退出前写入导航、工作台选择和正常窗口尺寸。"""
        try:
            self.settings["last_navigation_index"] = int(self.stack.currentIndex())
            geometry=self.normalGeometry() if self.isMaximized() else self.geometry()
            self.settings["last_window_width"]=int(geometry.width())
            self.settings["last_window_height"]=int(geometry.height())
            self.remember_workspace_export_options()
            self.remember_workspace_selectors()
            save_app_settings(self.settings)
        except Exception:
            LOGGER.exception("保存最后界面状态失败")
        # 会话运行日志绝不落盘；关闭窗口时先停止刷新并移除监听器，释放所有内存记录。
        timer=getattr(self,"runtime_log_timer",None)
        if timer:timer.stop()
        dialog=getattr(self,"runtime_log_dialog",None)
        if dialog:dialog.close()
        handler=getattr(self,"runtime_log_handler",None)
        if handler:
            try:LOGGER.removeHandler(handler);handler.clear();handler.close()
            except Exception:pass
        super().closeEvent(event)


if __name__ == "__main__":
    # 必须先设定身份和全局图标：直接双击 .py 时任务栏不会继承 python.exe 图标。
    apply_windows_application_identity()
    app=QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setWindowIcon(QIcon(str(application_icon_path())))
    try:
        window=App()
    except Exception as error:
        # 从资源管理器双击 .py 时，控制台通常会立即关闭。保留可见的错误对话框，
        # 方便用户知道缺什么或把错误内容反馈出来，而不是看到空窗口后无提示退出。
        detail=f"软件启动失败：\n{error}\n\n请使用“启动VideoTaskHub.bat”启动；若仍失败，请在“系统日志”或终端窗口中查看详细信息。"
        try:
            QtMessageBox.critical(None,"VideoTaskHub 启动失败",detail)
        finally:
            raise
    window.show()
    sys.exit(app.exec())
