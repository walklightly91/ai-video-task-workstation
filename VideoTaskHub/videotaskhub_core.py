"""VideoTaskHub 核心模块（从 main.py 参考实现机械抽取）。

本文件可独立随桌面端发布；运行时不依赖 main.py。重新同步时运行 videotaskhub_legacy_extract.py。
"""
from __future__ import annotations
import base64
import ast
import csv
import hashlib
import io
import math
import os
import re
import time
import threading
import traceback
import warnings
from threading import Lock, Event
from html.parser import HTMLParser

from PySide6.QtCore import QEvent, QEventLoop, QItemSelectionModel, QRect, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QAbstractItemDelegate, QAbstractItemView, QCheckBox, QComboBox, QDialog, QHeaderView, QHBoxLayout, QLabel, QMessageBox, QMenu, QPushButton, QTableWidget, QTableWidgetItem, QTableWidgetSelectionRange, QTextEdit, QVBoxLayout

pyqtSignal=Signal
PYQT_VERSION=6
HTTP_VERIFY=True
_API_THROTTLE_LOCK=Lock()
_API_NEXT_ALLOWED_TS={}
_ExtendedSelection=QAbstractItemView.SelectionMode.ExtendedSelection
_SelectItems=QAbstractItemView.SelectionBehavior.SelectItems
_Interactive=QHeaderView.ResizeMode.Interactive
_DoubleClicked=QAbstractItemView.EditTrigger.DoubleClicked
_SelectedClicked=QAbstractItemView.EditTrigger.SelectedClicked
_EditKeyPressed=QAbstractItemView.EditTrigger.EditKeyPressed
_AnyKeyPressed=QAbstractItemView.EditTrigger.AnyKeyPressed
_LeftButton=Qt.MouseButton.LeftButton
_UserRole=Qt.ItemDataRole.UserRole
_Key_C=Qt.Key.Key_C
_Key_V=Qt.Key.Key_V
_Key_X=Qt.Key.Key_X
_Key_Z=Qt.Key.Key_Z
_Key_Y=Qt.Key.Key_Y
_Key_Delete=Qt.Key.Key_Delete
_Key_Return=Qt.Key.Key_Return
_Key_Enter=Qt.Key.Key_Enter
_ControlModifier=Qt.KeyboardModifier.ControlModifier
def write_debug(*_args, **_kwargs): pass

from datetime import datetime
def render_path_template(path_template, variables=None, project_name=''):
    raw = str(path_template or '').strip().strip('"').strip("'")
    if not raw:
        return ''
    try:
        raw = os.path.expandvars(os.path.expanduser(raw))
    except Exception:
        pass
    try:
        now = datetime.now()
    except Exception:
        now = None
    mapping = {}
    if now is not None:
        mapping.update({'{date}': now.strftime('%Y-%m-%d'), '{yyyy-MM-dd}': now.strftime('%Y-%m-%d'), '{yyyyMMdd}': now.strftime('%Y%m%d'), '{yyyyMM}': now.strftime('%Y%m'), '{time}': now.strftime('%H-%M-%S'), '{hhmmss}': now.strftime('%H%M%S')})
    try:
        mapping['{cwd}'] = os.getcwd()
    except Exception:
        mapping['{cwd}'] = ''
    try:
        mapping['{home}'] = os.path.expanduser('~')
    except Exception:
        mapping['{home}'] = ''
    if project_name:
        try:
            safe_project = clean_long_filename(str(project_name or ''), 120)
        except Exception:
            safe_project = str(project_name or '')
        mapping['{project}'] = safe_project
    if isinstance(variables, dict):
        for k, v in variables.items():
            key = str(k or '')
            if not key:
                continue
            token = key if key.startswith('{') and key.endswith('}') else '{' + key + '}'
            mapping[token] = '' if v is None else str(v)
    for token, value in mapping.items():
        if token and token in raw:
            raw = raw.replace(token, value)
    try:
        return os.path.normpath(raw)
    except Exception:
        return raw

def normalize_api_base(api_base, default=''):
    return (api_base or default or '').strip().rstrip('/')

def is_google_native_api(api_base):
    base = normalize_api_base(api_base).lower()
    return 'generativelanguage.googleapis.com' in base or 'googleapis.com' in base

def pick_google_model(model_name, default_model='gemini-1.5-flash'):
    name = (model_name or '').strip()
    return name if 'gemini' in name.lower() else default_model

def get_effective_api_interval(api_base, ai_config=None, fallback=0):
    interval = max(0, int(fallback or 0))
    if isinstance(ai_config, dict):
        try:
            interval = max(interval, int(ai_config.get('api_interval', fallback) or 0))
        except Exception:
            pass
    return max(0, interval)

def _api_throttle_token(api_base, api_key):
    if is_google_native_api(api_base):
        raw = f'{normalize_api_base(api_base)}'
    else:
        raw = f"{normalize_api_base(api_base)}|{api_key or ''}"
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()

def wait_for_api_slot(api_base, api_key, min_interval=0, stop_check=None, log_fn=None, prefix=''):
    token = _api_throttle_token(api_base, api_key)
    while True:
        with _API_THROTTLE_LOCK:
            now = time.time()
            next_allowed = _API_NEXT_ALLOWED_TS.get(token, 0.0)
            wait_seconds = max(0.0, next_allowed - now)
            if wait_seconds <= 0:
                return
        if log_fn and wait_seconds >= 0.5:
            log_fn(f'{prefix}检测到限流冷却，等待 {wait_seconds:.1f}s 后重试...', 'gray')
        steps = max(1, int(wait_seconds * 10))
        for _ in range(steps):
            if stop_check and stop_check():
                return
            time.sleep(0.1)

def apply_api_cooldown(api_base, api_key, cooldown_seconds):
    cooldown_seconds = max(0.0, float(cooldown_seconds or 0))
    if cooldown_seconds <= 0:
        return
    token = _api_throttle_token(api_base, api_key)
    with _API_THROTTLE_LOCK:
        _API_NEXT_ALLOWED_TS[token] = max(_API_NEXT_ALLOWED_TS.get(token, 0.0), time.time() + cooldown_seconds)

def parse_retry_after_seconds(response, default_seconds):
    try:
        retry_after = response.headers.get('Retry-After', '')
        if retry_after:
            return max(float(retry_after), float(default_seconds or 0))
    except Exception:
        pass
    return float(default_seconds or 0)

def extract_api_error_message(response):
    try:
        data = response.json()
        if isinstance(data, dict):
            err = data.get('error')
            if isinstance(err, dict):
                msg = err.get('message') or err.get('status') or ''
                details = err.get('details')
                if isinstance(details, list) and details:
                    detail_text = []
                    for item in details[:2]:
                        if isinstance(item, dict):
                            part = item.get('reason') or item.get('detail') or item.get('@type') or ''
                            if part:
                                detail_text.append(str(part))
                    if detail_text:
                        msg = f"{msg} ({'; '.join(detail_text)})".strip()
                if msg:
                    return str(msg)
        text = response.text.strip()
        if text:
            return text[:200]
    except Exception:
        try:
            text = response.text.strip()
            if text:
                return text[:200]
        except Exception:
            pass
    return f"HTTP {getattr(response, 'status_code', 'ERROR')}"

class FormulaEngine:

    @staticmethod
    def col_to_index(col_str):
        """将 A, B, C... 转为 0, 1, 2..."""
        index = 0
        for char in col_str.upper():
            index = index * 26 + (ord(char) - ord('A') + 1)
        return index - 1

    @staticmethod
    def index_to_col(index):
        """将 0, 1, 2... 转为 A, B, C... (0->A, 1->B)"""
        res = ''
        temp = index + 1
        while temp > 0:
            temp, rem = divmod(temp - 1, 26)
            res = chr(ord('A') + rem) + res
        return res

    @staticmethod
    def get_cell_value(table, row, col):
        """获取单元格的数值，非数值返回 0"""
        item = table.item(row, col)
        if not item:
            return 0
        formula_val = item.data(_UserRole + 10)
        if formula_val is not None and isinstance(formula_val, (int, float)):
            return formula_val
        text = item.text().strip()
        if not text:
            return 0
        try:
            return float(text)
        except:
            match = re.match('^[-+]?[0-9]*\\.?[0-9]+', text)
            if match:
                return float(match.group())
            return 0

    @classmethod
    def evaluate(cls, formula, table):
        """解析并计算公式，支持 =A1+B1, SUM(A1:A5) 等"""
        if not formula or not formula.startswith('='):
            return formula
        expr = formula[1:].strip().upper()
        if not expr:
            return ''
        try:

            def replace_range(match):
                c1_str, r1_str, c2_str, r2_str = match.groups()
                v_col1, v_row1 = (cls.col_to_index(c1_str), int(r1_str) - 1)
                v_col2, v_row2 = (cls.col_to_index(c2_str), int(r2_str) - 1)
                vals = []
                for vr in range(min(v_row1, v_row2), max(v_row1, v_row2) + 1):
                    for vc in range(min(v_col1, v_col2), max(v_col1, v_col2) + 1):
                        lr = table.verticalHeader().logicalIndex(vr)
                        lc = table.horizontalHeader().logicalIndex(vc)
                        vals.append(cls.get_cell_value(table, lr, lc))
                return str(vals)
            expr = re.sub('([A-Z]+)(\\d+):([A-Z]+)(\\d+)', replace_range, expr)

            def replace_cell(match):
                c_str, r_str = match.groups()
                v_col, v_row = (cls.col_to_index(c_str), int(r_str) - 1)
                if 0 <= v_row < table.rowCount() and 0 <= v_col < table.columnCount():
                    logical_row = table.verticalHeader().logicalIndex(v_row)
                    logical_col = table.horizontalHeader().logicalIndex(v_col)
                    return str(cls.get_cell_value(table, logical_row, logical_col))
                return '0'
            expr = re.sub('(?<![A-Z])([A-Z]+)(\\d+)(?![A-Z])', replace_cell, expr)
            expr = re.sub('\\bSUM\\(', 'sum_func(', expr)
            expr = re.sub('\\bAVG\\(', 'avg_func(', expr)
            expr = re.sub('\\bMAX\\(', 'max_func(', expr)
            expr = re.sub('\\bMIN\\(', 'min_func(', expr)
            expr = re.sub('\\bABS\\(', 'abs(', expr)
            expr = re.sub('\\bROUND\\(', 'round(', expr)
            expr = re.sub('\\bLEN\\(', 'len(', expr)
            safe_env = {'sum_func': lambda x: sum(x) if isinstance(x, list) else x if isinstance(x, (int, float)) else 0, 'avg_func': lambda x: sum(x) / len(x) if isinstance(x, list) and len(x) > 0 else x if isinstance(x, (int, float)) else 0, 'max_func': lambda x: max(x) if isinstance(x, list) and len(x) > 0 else x if isinstance(x, (int, float)) else 0, 'min_func': lambda x: min(x) if isinstance(x, list) and len(x) > 0 else x if isinstance(x, (int, float)) else 0, 'abs': abs, 'round': round, 'len': len}
            clean_expr = re.sub('[^0-9+\\-*/().,\\[\\]_a-zA-Z]', '', expr)

            # Formulae come from editable table cells.  Never use ``eval`` here:
            # even a heavily filtered Python expression is not a security
            # boundary.  Parse the compact formula grammar and allow only the
            # arithmetic/list/function constructs that this spreadsheet exposes.
            parsed = ast.parse(clean_expr, mode='eval')

            def evaluate_node(node):
                if isinstance(node, ast.Expression):
                    return evaluate_node(node.body)
                if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                    return node.value
                if isinstance(node, (ast.List, ast.Tuple)):
                    return [evaluate_node(item) for item in node.elts]
                if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                    value = evaluate_node(node.operand)
                    return value if isinstance(node.op, ast.UAdd) else -value
                if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow)):
                    left, right = evaluate_node(node.left), evaluate_node(node.right)
                    operators = {
                        ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
                        ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b,
                        ast.Mod: lambda a, b: a % b, ast.Pow: lambda a, b: a ** b,
                    }
                    return operators[type(node.op)](left, right)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
                    function = safe_env.get(node.func.id)
                    if function is None:
                        raise ValueError('unsupported formula function')
                    return function(*(evaluate_node(argument) for argument in node.args))
                raise ValueError('unsupported formula syntax')

            result = evaluate_node(parsed)
            return round(result, 4) if isinstance(result, (int, float)) else result
        except Exception as e:
            return f'#ERR'

def clean_long_filename(filename, max_len=180):
    """前期素材整理专用：尽量保留长文案作为文件名，同时规避非法字符、保留名、尾部空格/点等命名问题。"""
    if not filename:
        filename = 'unnamed_item'
    cleaned = re.sub('[\\\\/:*?"<>|]', '_', str(filename))
    cleaned = re.sub('[\\x00-\\x1f]', ' ', cleaned)
    cleaned = re.sub('\\s+', ' ', cleaned).strip().strip('.')
    if not cleaned:
        cleaned = 'unnamed_item'
    reserved = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}
    if cleaned.upper() in reserved:
        cleaned = f'_{cleaned}'
    return cleaned[:max_len].rstrip(' .') or 'unnamed_item'

def smart_wrap_text(text, max_line_len=95, merge_single_linebreaks=False):
    """
    智能均衡断行逻辑：
    1. 优先在句末标点处切分，尽量保证每段都落在用户限制范围内。
    2. 不是简单贪婪拼接，而是做“均衡分桶”，让各段长度尽量接近。
    3. 若单句本身超长，优先降级到逗号/分号，再退到单词边界，尽量不硬切。
    """
    if not text or not text.strip():
        return text
    import re as _re
    import math as _math
    limit = max(10, int(max_line_len or 95))

    def _normalize_spaces(s):
        return _re.sub('\\s+', ' ', (s or '').strip())

    def _join_units(units):
        return ' '.join((u.strip() for u in units if u and u.strip()))

    def _prepare_paragraphs(raw_text):
        normalized_text = str(raw_text or '').replace('\r\n', '\n').replace('\r', '\n')
        if not merge_single_linebreaks:
            return [_normalize_spaces(p) for p in _re.split('\\n+', normalized_text) if _normalize_spaces(p)]
        paragraphs = []
        current_lines = []
        for raw_line in normalized_text.split('\n'):
            clean_line = _normalize_spaces(raw_line)
            if clean_line:
                current_lines.append(clean_line)
            elif current_lines:
                paragraphs.append(_join_units(current_lines))
                current_lines = []
        if current_lines:
            paragraphs.append(_join_units(current_lines))
        return paragraphs

    def _split_by_words(piece, inner_limit):
        words = [w for w in _re.split('\\s+', piece.strip()) if w]
        if not words:
            return []
        if len(words) == 1:
            return words
        lens = [len(w) for w in words]
        prefix = [0]
        for ln in lens:
            prefix.append(prefix[-1] + ln)

        def _word_seg_len(start_idx, end_idx):
            words_len = prefix[end_idx + 1] - prefix[start_idx]
            spaces = end_idx - start_idx
            return words_len + max(0, spaces)
        total_len = _word_seg_len(0, len(words) - 1)
        group_count = max(1, _math.ceil(total_len / inner_limit))
        inf = float('inf')
        dp = [[inf] * (len(words) + 1) for _ in range(group_count + 1)]
        prev = [[-1] * (len(words) + 1) for _ in range(group_count + 1)]
        dp[0][0] = 0.0
        target = max(max(lens), total_len / group_count)
        for g in range(1, group_count + 1):
            for end in range(g, len(words) + 1):
                for start in range(g - 1, end):
                    seg_len = _word_seg_len(start, end - 1)
                    if seg_len > inner_limit:
                        continue
                    score = dp[g - 1][start] + (seg_len - target) ** 2
                    if score < dp[g][end]:
                        dp[g][end] = score
                        prev[g][end] = start
        if dp[group_count][len(words)] >= inf:
            parts = []
            buf = words[0]
            for word in words[1:]:
                candidate = f'{buf} {word}'
                if len(candidate) <= inner_limit:
                    buf = candidate
                else:
                    parts.append(buf)
                    buf = word
            if buf:
                parts.append(buf)
            return parts
        result = []
        end = len(words)
        g = group_count
        while g > 0 and end > 0:
            start = prev[g][end]
            if start < 0:
                break
            result.append(' '.join(words[start:end]))
            end = start
            g -= 1
        return list(reversed(result)) if result else [' '.join(words)]

    def _split_long(sentence, inner_limit):
        sentence = _normalize_spaces(sentence)
        if len(sentence) <= inner_limit:
            return [sentence]
        sub_parts = [_normalize_spaces(s) for s in _re.findall('[^,;，；]*[,;，；]?', sentence) if _normalize_spaces(s)]
        if len(sub_parts) <= 1:
            return _split_by_words(sentence, inner_limit)
        total_sentence_len = len(_join_units(sub_parts))
        desired_groups = max(1, _math.ceil(total_sentence_len / inner_limit))
        soft_target = max(10, int(_math.ceil(total_sentence_len / desired_groups)))
        split_threshold = max(int(_math.ceil(soft_target * 1.15)), int(inner_limit * 0.85))
        atomic_sub_parts = []
        for sp in sub_parts:
            if len(sp) > split_threshold:
                atomic_sub_parts.extend(_split_by_words(sp, soft_target))
            else:
                atomic_sub_parts.append(sp)
        balanced = _balance_units(atomic_sub_parts, inner_limit)
        return [seg for seg in balanced if seg]

    def _segment_len(length_prefix, start_idx, end_idx):
        if start_idx > end_idx:
            return 0
        words_len = length_prefix[end_idx + 1] - length_prefix[start_idx]
        spaces = end_idx - start_idx
        return words_len + max(0, spaces)

    def _balance_units(units, inner_limit):
        if not units:
            return []
        if len(units) == 1:
            return units[:]
        lens = [len(u) for u in units]
        prefix = [0]
        for ln in lens:
            prefix.append(prefix[-1] + ln)
        total_len = _segment_len(prefix, 0, len(units) - 1)
        min_groups = max(1, _math.ceil(total_len / inner_limit))
        max_groups = min(len(units), min_groups + 2)
        inf = float('inf')
        best_choice = None
        for group_count in range(min_groups, max_groups + 1):
            target = max(max(lens), total_len / group_count)
            dp = [[inf] * (len(units) + 1) for _ in range(group_count + 1)]
            prev = [[-1] * (len(units) + 1) for _ in range(group_count + 1)]
            dp[0][0] = 0.0
            for g in range(1, group_count + 1):
                for end in range(g, len(units) + 1):
                    for start in range(g - 1, end):
                        seg_len = _segment_len(prefix, start, end - 1)
                        if seg_len > inner_limit:
                            continue
                        penalty = (seg_len - target) ** 2
                        lower_bound = max(1.0, target * 0.72)
                        if seg_len < lower_bound:
                            penalty += (lower_bound - seg_len) ** 2 * 0.5
                        score = dp[g - 1][start] + penalty
                        if score < dp[g][end]:
                            dp[g][end] = score
                            prev[g][end] = start
            if dp[group_count][len(units)] >= inf:
                continue
            score = dp[group_count][len(units)] + (group_count - min_groups) * (inner_limit * 0.35) ** 2
            if best_choice is None or score < best_choice[0]:
                best_choice = (score, group_count, prev)
        if best_choice is None:
            result = []
            buf = ''
            for unit in units:
                candidate = unit if not buf else f'{buf} {unit}'
                if len(candidate) <= inner_limit:
                    buf = candidate
                else:
                    if buf:
                        result.append(buf)
                    buf = unit
            if buf:
                result.append(buf)
            return result
        _, group_count, prev = best_choice
        result = []
        end = len(units)
        current_group = group_count
        while current_group > 0 and end > 0:
            start = prev[current_group][end]
            if start < 0:
                break
            result.append(_join_units(units[start:end]))
            end = start
            current_group -= 1
        return list(reversed(result)) if result else [_join_units(units)]
    paragraphs = _prepare_paragraphs(text)
    final_lines = []
    for paragraph in paragraphs:
        sentence_parts = [_normalize_spaces(p) for p in _re.findall('[^.!?。！？]*[.!?。！？]?', paragraph) if _normalize_spaces(p)]
        if not sentence_parts:
            sentence_parts = [paragraph]
        paragraph_total_len = len(_join_units(sentence_parts))
        paragraph_group_count = max(1, _math.ceil(paragraph_total_len / limit))
        paragraph_target = max(10, int(_math.ceil(paragraph_total_len / paragraph_group_count)))
        sentence_soft_limit = max(10, min(limit, paragraph_target))
        sentence_split_threshold = max(int(_math.ceil(paragraph_target * 1.18)), int(limit * 0.85))
        atomic_units = []
        for sentence in sentence_parts:
            if len(sentence) <= limit and (paragraph_group_count <= 1 or len(sentence) <= sentence_split_threshold):
                atomic_units.append(sentence)
            else:
                atomic_units.extend(_split_long(sentence, sentence_soft_limit if len(sentence) <= limit else limit))
        final_lines.extend(_balance_units(atomic_units, limit))
    return '\n'.join(final_lines) if final_lines else text


def segment_english_dialogue(text, target_words=135, minimum_words=None, overflow_ratio=0.20):
    """按完整台词句子分割英文文案，避免产生无法配音的极短尾段。

    ``target_words`` 是建议长度而非硬上限。分段只在句末进行；如果短尾段
    无法通过整句回搬解决，宁可小幅超出目标，也不会把一句台词从中间拆开。
    返回 ``list[str]``，每项对应一个待导出的数字 TXT 文件。
    """
    normalized = re.sub(r"\s+", " ", str(text or "").strip())
    if not normalized:
        return []
    try:
        target = max(1, int(target_words))
    except (TypeError, ValueError):
        target = 135
    # 小目标（例如 8 秒短片）也要避免只有两三个词；大目标则把最短段控制在
    # 约 12%~15% 的范围，最高不超过 18 词，避免过度强制合并。
    if minimum_words is None:
        minimum = max(12, min(18, int(round(target * 0.13))))
    else:
        try:
            minimum = max(1, int(minimum_words))
        except (TypeError, ValueError):
            minimum = 12
    maximum = max(target, int(math.ceil(target * (1.0 + max(0.0, float(overflow_ratio))))))
    emergency_maximum = max(maximum, int(math.ceil(target * 1.35)))

    def word_count(value):
        # 英文词、越南语音节与中文字符均是一个朗读单位。Unicode 词规则不能
        # 把 người / Chúa 等变音词拆开，否则按口播时长分段会严重偏离。
        return len(re.findall(r"[\u3400-\u9fff]|\d+(?:(?:[-/:]\d+)+|(?:[.,]\d+)?)(?:[%％])?|[^\W\d_]+(?:['’\-][^\W\d_]+)*", value or "", re.UNICODE))

    # 连续句末标点和尾随引号/括号保留在原句，保证对白语气与含义完整。
    sentence_pattern = r"[^.!?。！？]+(?:[.!?。！？]+[\"'”’）)]*|$)"
    sentences = [part.strip() for part in re.findall(sentence_pattern, normalized) if part.strip()]
    if not sentences:
        sentences = [normalized]

    groups = []
    current = []
    current_words = 0
    for sentence in sentences:
        count = word_count(sentence)
        if not current:
            current = [sentence]
            current_words = count
            continue
        candidate_words = current_words + count
        # 允许在完整句末稍微越过目标；但超过常规容忍度时才另起一段。
        if candidate_words <= maximum:
            current.append(sentence)
            current_words = candidate_words
        else:
            groups.append(current)
            current = [sentence]
            current_words = count
    if current:
        groups.append(current)

    def count_group(group):
        return sum(word_count(sentence) for sentence in group)

    # 从末尾向前修复极短段。优先合并；合并过长时从上一段末尾整句回搬。
    # 这样不会产生 2~3 词的尾段，也绝不在一句台词中间硬切。
    for index in range(len(groups) - 1, 0, -1):
        group_words = count_group(groups[index])
        if group_words >= minimum:
            continue
        previous = groups[index - 1]
        previous_words = count_group(previous)
        if previous_words + group_words <= emergency_maximum:
            groups[index - 1] = previous + groups[index]
            del groups[index]
            continue
        while len(previous) > 1 and group_words < minimum:
            moved = previous[-1]
            moved_words = word_count(moved)
            # 不用回搬导致上一段也变成短段的整句。
            if previous_words - moved_words < minimum:
                break
            previous.pop()
            groups[index].insert(0, moved)
            previous_words -= moved_words
            group_words += moved_words
        groups[index - 1] = previous
        # 上一段只有一条超长完整句时，不能再回搬；此时语义完整和可生成性
        # 比目标字数更重要，仍直接合并，绝不遗留 2~3 词的无效尾段。
        if group_words < minimum:
            groups[index - 1] = previous + groups[index]
            del groups[index]

    return [" ".join(group).strip() for group in groups if " ".join(group).strip()]

def make_unique_path(folder, stem, ext, max_component_len=180, max_full_path=240):
    """前期素材整理专用：生成不冲突且尽量长的安全路径。"""
    ext = ext or ''
    folder = os.path.abspath(folder)
    allowed_by_full = max_full_path - len(folder) - len(os.sep) - len(ext)
    allowed = max(12, min(max_component_len - len(ext), allowed_by_full))
    base = clean_long_filename(stem, allowed)
    candidate = os.path.join(folder, f'{base}{ext}')
    if not os.path.exists(candidate):
        return candidate
    n = 2
    while True:
        suffix = f'_{n}'
        cut_len = max(1, allowed - len(suffix))
        candidate = os.path.join(folder, f"{base[:cut_len].rstrip(' .')}{suffix}{ext}")
        if not os.path.exists(candidate):
            return candidate
        n += 1

class ExcelTable(QTableWidget):

    def __init__(self, rows, cols, parent=None):
        super().__init__(rows, cols, parent)
        self.setSelectionMode(_ExtendedSelection)
        self.setSelectionBehavior(_SelectItems)
        self.horizontalHeader().setSectionResizeMode(_Interactive)
        self.horizontalHeader().setStretchLastSection(True)
        self.setAlternatingRowColors(True)
        # 单击只用于定位/多选；编辑必须双击、F2 或直接输入，避免编辑器截获拖选和快捷键。
        self.setEditTriggers(_DoubleClicked | _EditKeyPressed | _AnyKeyPressed)
        self.setMouseTracking(True)
        self._is_filling = False
        self._fill_start_pos = None
        self._fill_rect = None

    def mousePressEvent(self, event):
        if event.button() == _LeftButton:
            pos = event.pos()
            selected_ranges = self.selectedRanges()
            if selected_ranges:
                last_range = selected_ranges[-1]
                last_row, last_col = (last_range.bottomRow(), last_range.rightColumn())
                rect = self.visualRect(self.model().index(last_row, last_col))
                handle_size = 14
                if rect.isValid() and self._can_fill_column(last_col) and QRect(rect.right() - handle_size, rect.bottom() - handle_size, handle_size, handle_size).contains(pos):
                    self._is_filling = True
                    # 保留完整源矩形，让多列/多行选择也能整体拖拽填充。
                    self._fill_source_info = (last_range.topRow(), last_range.bottomRow(), last_range.leftColumn(), last_range.rightColumn())
                    self._last_fill_row = last_row
                    self.setCursor(Qt.CursorShape.CrossCursor)
                    self.clearFocus()
                    event.accept()
                    return
            index = self.indexAt(pos)
            if index.isValid():
                row, col = (index.row(), index.column())
                rect = self.visualRect(index)
                handle_size = 14
                if self._can_fill_column(col) and QRect(rect.right() - handle_size, rect.bottom() - handle_size, handle_size, handle_size).contains(pos):
                    self._is_filling = True
                    self._fill_source_info = (row, row, col, col)
                    self._last_fill_row = row
                    self.setCursor(Qt.CursorShape.CrossCursor)
                    self.clearFocus()
                    event.accept()
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.pos()
        if self._is_filling:
            curr_row = self.rowAt(pos.y())
            curr_col = self.columnAt(pos.x())
            if curr_row >= 0 and curr_col >= 0:
                top, bottom, left, right = self._normalize_fill_source(self._fill_source_info)
                self._last_fill_row = curr_row
                self._last_fill_col = curr_col
                self.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
                self.clearSelection()
                if abs(curr_row - bottom) >= abs(curr_col - right):
                    self._fill_direction = 'V'
                    r_start, r_end = (min(top, curr_row), max(bottom, curr_row))
                    for r in range(r_start, r_end + 1):
                        for c in range(left, right + 1):
                            idx = self.model().index(r, c)
                            if idx.isValid():
                                self.selectionModel().select(idx, QItemSelectionModel.SelectionFlag.Select if PYQT_VERSION == 6 else QItemSelectionModel.Select)
                else:
                    self._fill_direction = 'H'
                    c_start, c_end = (min(left, curr_col), max(right, curr_col))
                    for c in range(c_start, c_end + 1):
                        for r in range(top, bottom + 1):
                            idx = self.model().index(r, c)
                            if idx.isValid():
                                self.selectionModel().select(idx, QItemSelectionModel.SelectionFlag.Select if PYQT_VERSION == 6 else QItemSelectionModel.Select)
            event.accept()
            return
        index = self.indexAt(pos)
        if index.isValid():
            rect = self.visualRect(index)
            handle_size = 14
            if self._can_fill_column(index.column()) and QRect(rect.right() - handle_size, rect.bottom() - handle_size, handle_size, handle_size).contains(pos):
                self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._is_filling:
            self._is_filling = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            top, bottom, left, right = self._normalize_fill_source(self._fill_source_info)
            direction = getattr(self, '_fill_direction', 'V')
            if direction == 'V' and self._last_fill_row != bottom:
                self.auto_fill_v(self._fill_source_info, self._last_fill_row)
            elif direction == 'H' and self._last_fill_col != right:
                self.auto_fill_h(self._fill_source_info, self._last_fill_col)
            # 填充完成后保留结果区域，便于继续复制、删除或再次填充。
            self.clearSelection()
            if direction == 'V':
                r_start, r_end, c_start, c_end = min(top, self._last_fill_row), max(bottom, self._last_fill_row), left, right
            else:
                r_start, r_end, c_start, c_end = top, bottom, min(left, self._last_fill_col), max(right, self._last_fill_col)
            self.setRangeSelected(QTableWidgetSelectionRange(r_start, c_start, r_end, c_end), True)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _can_fill_column(self, col):
        enabled = getattr(self, '_smart_fill_enabled_columns', None)
        if enabled is None:
            return 0 <= col < self.columnCount()
        try:
            return col in set(enabled)
        except Exception:
            return False

    @staticmethod
    def _normalize_fill_source(source_info):
        """兼容旧的三元组源信息，并统一为 top/bottom/left/right。"""
        if len(source_info) == 3:
            top, bottom, col = source_info
            return top, bottom, col, col
        return source_info

    def _get_fill_cell_payload(self, row, col):
        widget = self.cellWidget(row, col)
        if widget and isinstance(widget, QComboBox):
            txt = widget.currentText()
            return {'text': txt, 'norm_text': str(txt or '').strip(), 'formula': None, 'kind': 'combo'}
        if widget and isinstance(widget, QCheckBox):
            txt = 'YES' if widget.isChecked() else 'NO'
            return {'text': txt, 'norm_text': txt, 'formula': None, 'kind': 'check_widget'}
        item = self.item(row, col)
        if not item:
            return {'text': '', 'norm_text': '', 'formula': None, 'kind': 'empty'}
        meta = item.data(_UserRole)
        if isinstance(meta, dict) and 'base_code' in meta:
            txt = str(meta.get('base_code', '') or '')
        else:
            txt = item.text()
        return {'text': txt, 'norm_text': str(txt or '').strip(), 'formula': item.data(_UserRole + 11), 'kind': 'item'}

    def _set_fill_cell_payload(self, row, col, value, formula=None):
        if row >= self.rowCount():
            self.setRowCount(row + 1)
        if col >= self.columnCount():
            self.setColumnCount(col + 1)
        widget = self.cellWidget(row, col)
        if widget and isinstance(widget, QComboBox):
            widget.setCurrentText('' if value is None else str(value))
            return
        if widget and isinstance(widget, QCheckBox):
            raw = str(value or '').strip().lower()
            widget.setChecked(raw in ('1', 'true', 'yes', 'y', 'on', 'done'))
            return
        item = self.item(row, col)
        if not item:
            item = QTableWidgetItem()
            self.setItem(row, col, item)
        meta = item.data(_UserRole)
        if isinstance(meta, dict) and 'base_code' in meta:
            base_code = str(value or '').replace('(续)', '').strip()
            is_sub = bool(meta.get('is_sub'))
            current_text = item.text() or ''
            if is_sub:
                display_text = f"│    ↳ {base_code}{(' (续)' if base_code and (not base_code.endswith('(续)')) else '')}"
            else:
                is_expanded = current_text.lstrip().startswith('▾')
                display_text = f"{('▾ ★' if is_expanded else '▸ ★')} {base_code}".strip()
            meta['base_code'] = base_code
            item.setData(_UserRole, meta)
            item.setText(display_text)
            return
        item.setText('' if value is None else str(value))
        if formula is not None:
            item.setData(_UserRole + 11, formula)
        else:
            item.setData(_UserRole + 11, None)

    def _build_series_plan(self, source_data):
        if not source_data:
            return {'kind': 'empty'}
        texts = [d.get('text', '') for d in source_data]
        norm_texts = [d.get('norm_text', '') for d in source_data]
        formulas = [d.get('formula') for d in source_data]
        if len(source_data) == 1 and formulas[0]:
            return {'kind': 'formula', 'formula': formulas[0]}
        nums = []
        is_num = True
        for txt in norm_texts:
            try:
                nums.append(float(txt))
            except Exception:
                is_num = False
                break
        if is_num and nums:
            step = 1
            if len(nums) >= 2:
                step = nums[-1] - nums[-2]
                if step == 0:
                    return {'kind': 'copy_cycle', 'texts': texts}
            return {'kind': 'number', 'nums': nums, 'step': step}
        if all(norm_texts) and all((not f for f in formulas)):
            date_series = self._analyze_date_series(norm_texts)
            if date_series:
                return {'kind': 'date', 'series': date_series}
            text_series = self._analyze_text_series(norm_texts)
            if text_series:
                return {'kind': 'text_series', 'series': text_series}
        return {'kind': 'copy_cycle', 'texts': texts}

    def _materialize_series_value(self, plan, fill_forward, offset):
        kind = plan.get('kind')
        if kind == 'formula':
            return {'value': plan.get('formula'), 'formula': plan.get('formula')}
        if kind == 'number':
            nums = plan.get('nums', [])
            if not nums:
                return {'value': ''}
            step = float(plan.get('step', 1))
            base = nums[-1] if fill_forward else nums[0]
            new_val = base + step * offset
            return {'value': str(int(new_val)) if float(new_val).is_integer() else str(round(new_val, 4))}
        if kind == 'date':
            series = plan.get('series', {})
            dates = series.get('dates', [])
            if not dates:
                return {'value': ''}
            base_dt = dates[-1] if fill_forward else dates[0]
            new_dt = base_dt + series['step_delta'] * int(offset)
            return {'value': self._format_date_by_style(new_dt, series.get('style'))}
        if kind == 'text_series':
            series = plan.get('series', {})
            nums_list = series.get('nums_list', [])
            if not nums_list:
                return {'value': ''}
            base_nums = nums_list[-1] if fill_forward else nums_list[0]
            new_nums = []
            for i, base in enumerate(base_nums):
                step_i = int(series['steps'][i])
                new_nums.append(int(base + step_i * offset))
            out = []
            for i in range(len(series['steps'])):
                out.append(series['literals'][i])
                # zfill 会把负号计入总宽度（-1 -> -01），不符合编号列的固定数字位数。
                # 这里单独补零，保证 001 向上填充时得到 000、-001。
                number=int(new_nums[i]); digits=str(abs(number)).zfill(int(series['pads'][i]))
                out.append(('-' if number < 0 else '') + digits)
            out.append(series['literals'][-1])
            return {'value': ''.join(out)}
        if kind == 'copy_cycle':
            texts = plan.get('texts', [])
            if not texts:
                return {'value': ''}
            idx = offset - 1 if fill_forward else abs(offset) - 1
            return {'value': texts[idx % len(texts)]}
        return {'value': ''}

    def auto_fill_v(self, source_info, end_row):
        top, bottom, left, right = self._normalize_fill_source(source_info)
        if end_row >= top and end_row <= bottom:
            return
        before = self._history_snapshot()
        self.blockSignals(True)
        try:
            fill_down = end_row > bottom
            row_iter = range(bottom + 1, end_row + 1) if fill_down else range(top - 1, end_row - 1, -1)
            for col in range(left, right + 1):
                source_data = [self._get_fill_cell_payload(r, col) for r in range(top, bottom + 1)]
                if not source_data:
                    continue
                plan = self._build_series_plan(source_data)
                for r in row_iter:
                    offset = r - bottom if fill_down else r - top
                    value_pack = self._materialize_series_value(plan, fill_down, offset)
                    if plan.get('kind') == 'formula':
                        new_f = self._adjust_formula(value_pack.get('formula', ''), r - top, 0)
                        self._set_fill_cell_payload(r, col, new_f, formula=new_f)
                    else:
                        self._set_fill_cell_payload(r, col, value_pack.get('value', ''))
        finally:
            self.blockSignals(False)
        self.recalculate_all()
        self._commit_history_snapshot(before)

    def _analyze_date_series(self, texts):
        """
        识别常见日期格式，并按谷歌表格的感觉做“按天递增”填充：
        - 2 个种子：按两者日期差（天）作为步长
        - 1 个种子：默认步长为 1 天
        - 若多个种子但步长为 0（日期完全相同），认为不是序列，返回 None（交给循环填充）

        支持格式（以第一个种子的样式为准）：
        - YYYY-MM-DD / YYYY-M-D
        - YYYY/MM/DD
        - YYYY.MM.DD
        - YYYY年M月D日
        - YYYYMMDD
        """
        try:
            from datetime import date as _date
            from datetime import timedelta as _timedelta
            texts = [str(t or '').strip() for t in texts or []]
            if not texts or not texts[0]:
                return None
            style = self._detect_date_style(texts[0])
            if not style:
                return None
            dates = []
            for t in texts:
                dt = self._parse_date_by_style(t, style)
                if not dt:
                    return None
                dates.append(dt)
            if len(dates) >= 2:
                step_days = (dates[-1] - dates[-2]).days
                if step_days == 0:
                    return None
            else:
                step_days = 1
            return {'dates': dates, 'step_delta': _timedelta(days=int(step_days)), 'style': style}
        except Exception:
            return None

    def _detect_date_style(self, text):
        """从单个文本中识别日期样式并记录 0 填充宽度等信息。"""
        try:
            t = str(text or '').strip()
            m = re.match('^(\\d{4})([-/.])(\\d{1,2})\\2(\\d{1,2})$', t)
            if m:
                y, sep, mm, dd = m.groups()
                return {'kind': 'ymd_sep', 'sep': sep, 'y_pad': 4, 'm_pad': len(mm), 'd_pad': len(dd)}
            m = re.match('^(\\d{4})\\s*年\\s*(\\d{1,2})\\s*月\\s*(\\d{1,2})\\s*日$', t)
            if m:
                y, mm, dd = m.groups()
                return {'kind': 'ymd_cn', 'y_pad': 4, 'm_pad': len(mm), 'd_pad': len(dd)}
            m = re.match('^(\\d{4})(\\d{2})(\\d{2})$', t)
            if m:
                return {'kind': 'ymd_compact', 'y_pad': 4, 'm_pad': 2, 'd_pad': 2}
            return None
        except Exception:
            return None

    def _parse_date_by_style(self, text, style):
        """按指定 style 解析日期；失败返回 None。"""
        try:
            from datetime import date as _date
            t = str(text or '').strip()
            kind = (style or {}).get('kind')
            if kind == 'ymd_sep':
                sep = re.escape(style.get('sep', '-'))
                m = re.match(f'^(\\d{{4}}){sep}(\\d{{1,2}}){sep}(\\d{{1,2}})$', t)
                if not m:
                    return None
                y, mm, dd = m.groups()
                return _date(int(y), int(mm), int(dd))
            if kind == 'ymd_cn':
                m = re.match('^(\\d{4})\\s*年\\s*(\\d{1,2})\\s*月\\s*(\\d{1,2})\\s*日$', t)
                if not m:
                    return None
                y, mm, dd = m.groups()
                return _date(int(y), int(mm), int(dd))
            if kind == 'ymd_compact':
                m = re.match('^(\\d{4})(\\d{2})(\\d{2})$', t)
                if not m:
                    return None
                y, mm, dd = m.groups()
                return _date(int(y), int(mm), int(dd))
            return None
        except Exception:
            return None

    def _format_date_by_style(self, dt, style):
        """按 seed 的样式格式化日期字符串。"""
        try:
            if not dt or not style:
                return ''
            y = str(int(dt.year)).zfill(int(style.get('y_pad', 4)))
            m = str(int(dt.month)).zfill(int(style.get('m_pad', 2)))
            d = str(int(dt.day)).zfill(int(style.get('d_pad', 2)))
            kind = style.get('kind')
            if kind == 'ymd_sep':
                sep = style.get('sep', '-')
                return f'{y}{sep}{m}{sep}{d}'
            if kind == 'ymd_cn':
                return f'{y}年{m}月{d}日'
            if kind == 'ymd_compact':
                return f'{y}{m}{d}'
            return f'{y}-{m}-{d}'
        except Exception:
            try:
                return str(dt)
            except Exception:
                return ''

    def _analyze_text_series(self, texts):
        """
        尽量模拟「谷歌表格」的文本序列填充：
        - 若内容可被抽象为「固定文本片段 + 一个或多个数字片段」的模板，则对发生变化的数字片段做等差递增；
        - 仅 1 个种子时：默认递增最后一个数字片段（步长 1）；
        - 若多个种子但数字片段均不变化（步长全为 0），则认为不是序列，返回 None（继续走循环填充逻辑）。

        示例：
        - 表格1, 表格2 => 表格3（递增数字片段）
        - S01E01, S01E02 => S01E03（递增最后一个数字片段）
        - Table_009 => Table_010（保留 0 填充宽度）
        """
        try:
            texts = [str(t or '').strip() for t in texts or []]
            if not texts or not texts[0]:
                return None
            first = texts[0]
            split = re.split('(\\d+)', first)
            if len(split) < 3:
                return None
            literals = split[0::2]
            pads = [len(s) for s in split[1::2]]
            group_count = len(pads)
            if group_count <= 0:
                return None
            pattern_parts = [re.escape(literals[0])]
            for i in range(group_count):
                pattern_parts.append('(\\d+)')
                pattern_parts.append(re.escape(literals[i + 1]))
            pattern = '^' + ''.join(pattern_parts) + '$'
            rx = re.compile(pattern)
            nums_list = []
            for t in texts:
                m = rx.match(t)
                if not m:
                    return None
                nums_list.append([int(x) for x in m.groups()])
            if len(nums_list) >= 2:
                steps = [nums_list[-1][i] - nums_list[-2][i] for i in range(group_count)]
                if all((s == 0 for s in steps)):
                    return None
            else:
                steps = [0] * group_count
                steps[-1] = 1
            return {'literals': literals, 'pads': pads, 'nums_list': nums_list, 'steps': steps}
        except Exception:
            return None

    def auto_fill_h(self, source_info, end_col):
        top, bottom, left, right = self._normalize_fill_source(source_info)
        if left <= end_col <= right:
            return
        before = self._history_snapshot()
        self.blockSignals(True)
        try:
            fill_forward = end_col > right
            col_iter = range(right + 1, end_col + 1) if fill_forward else range(left - 1, end_col - 1, -1)
            for row in range(top, bottom + 1):
                source_data = [self._get_fill_cell_payload(row, col) for col in range(left, right + 1)]
                plan = self._build_series_plan(source_data)
                for col in col_iter:
                    offset = col - right if fill_forward else col - left
                    value_pack = self._materialize_series_value(plan, fill_forward, offset)
                    if plan.get('kind') == 'formula':
                        new_f = self._adjust_formula(value_pack.get('formula', ''), 0, col - left)
                        self._set_fill_cell_payload(row, col, new_f, formula=new_f)
                    else:
                        self._set_fill_cell_payload(row, col, value_pack.get('value', ''))
        finally:
            self.blockSignals(False)
        self.recalculate_all()
        self._commit_history_snapshot(before)

    def trigger_main_save(self):
        main_win = self.window()
        if hasattr(main_win, 'trigger_save'):
            main_win.trigger_save()

    def _history_snapshot(self):
        """子类可提供快照；基础表格仍可安全复用批处理逻辑。"""
        snapshot = getattr(self, '_snapshot', None)
        return snapshot() if callable(snapshot) else None

    def _commit_history_snapshot(self, before):
        commit = getattr(self, '_commit_bulk_history', None)
        if callable(commit):
            commit(before)
        else:
            self.trigger_main_save()

    def recalculate_all(self):
        """
        基类兜底：普通 ExcelTable 不一定支持公式系统。
        这里保持为安全空操作，避免拖拽填充后因调用不存在的方法而崩溃。
        真正支持公式重算的表格由子类 DraggableTableWidget 覆盖此方法。
        """
        return

    def _adjust_formula(self, formula, row_offset, col_offset):

        def replace_match(match):
            col_str, row_str = match.groups()
            new_row = int(row_str) + row_offset
            new_col_idx = FormulaEngine.col_to_index(col_str) + col_offset
            return f'{FormulaEngine.index_to_col(new_col_idx)}{new_row}'
        return re.sub('([A-Z]+)(\\d+)', replace_match, formula)

    def keyPressEvent(self, event):
        if event.key() == _Key_C and event.modifiers() == _ControlModifier:
            self.copy_selection()
            event.accept()
        elif event.key() == _Key_X and event.modifiers() == _ControlModifier:
            self.copy_selection(); self.delete_selection(); event.accept()
        elif event.key() == _Key_V and event.modifiers() == _ControlModifier:
            self.paste_selection(); event.accept()
        elif event.key() == _Key_Z and event.modifiers() == _ControlModifier and hasattr(self, 'undo_sheet'):
            self.undo_sheet(); event.accept()
        elif event.key() == _Key_Y and event.modifiers() == _ControlModifier and hasattr(self, 'redo_sheet'):
            self.redo_sheet(); event.accept()
        elif event.key() == _Key_Delete:
            self.delete_selection(); event.accept()
        elif event.key() == Qt.Key.Key_F2:
            item = self.currentItem()
            if item:
                formula = item.data(_UserRole + 11)
                if formula:
                    self.blockSignals(True)
                    item.setText(formula)
                    self.blockSignals(False)
                self.editItem(item)
        elif len(event.text()) > 0 and event.modifiers() in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier):
            main_win = self.window()
            if hasattr(main_win, 'save_timer'):
                main_win.save_timer.start(5000)
            super().keyPressEvent(event)
        elif event.key() in (_Key_Return, _Key_Enter):
            if self.state() == QAbstractItemView.State.EditingState:
                # Qt 的默认 Return 行为会因不同委托/平台而仅移动焦点、没有提交
                # 编辑器。这里明确提交并关闭编辑器，保证回车后数据立即写入表格。
                editor=QApplication.focusWidget()
                if editor is not None and editor is not self:
                    self.commitData(editor)
                    self.closeEditor(editor,QAbstractItemDelegate.EndEditHint.NoHint)
                    self.setFocus()
                    event.accept()
                    return
            if self.objectName() == 'todo_table':
                curr_row = self.currentRow()
                if curr_row == self.rowCount() - 1:
                    self.parent().parent().add_row()
                self.setCurrentCell(curr_row + 1, self.currentColumn())
            else:
                super().keyPressEvent(event)
        else:
            super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        """统一的中文表格菜单，所有使用 ExcelTable 的页面均可获得相同操作。"""
        index=self.indexAt(event.pos())
        if index.isValid() and not index in self.selectedIndexes():
            self.clearSelection(); self.setCurrentIndex(index); self.selectionModel().select(index, QItemSelectionModel.SelectionFlag.Select)
        menu=QMenu(self)
        # 表格引擎独立于主界面，但右键菜单仍必须是不透明、无阴影的实体菜单，
        # 避免背景皮肤和 Windows 阴影干扰文字阅读。
        menu.setAttribute(Qt.WA_TranslucentBackground,False)
        menu.setAttribute(Qt.WA_OpaquePaintEvent,True)
        try:
            menu.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint,True)
        except AttributeError:
            pass
        edit=menu.addAction('编辑当前单元格（Enter）')
        edit.setEnabled(self._can_edit_current_cell())
        edit.triggered.connect(self.edit_current_cell)
        if hasattr(self, 'open_expanded_cell_editor'):
            expand=menu.addAction('展开编辑长内容（F2）');expand.setEnabled(bool(self._can_open_expanded_cell_editor()));expand.triggered.connect(self.open_expanded_cell_editor)
            menu.addSeparator()
        if hasattr(self, 'undo_sheet'):
            undo=menu.addAction('撤销'); undo.setEnabled(bool(getattr(self, '_undo_stack', []))); undo.triggered.connect(self.undo_sheet)
            redo=menu.addAction('重做'); redo.setEnabled(bool(getattr(self, '_redo_stack', []))); redo.triggered.connect(self.redo_sheet)
            menu.addSeparator()
        menu.addAction('剪切（Ctrl+X）', lambda: (self.copy_selection(), self.delete_selection()))
        menu.addAction('复制（Ctrl+C）', self.copy_selection)
        menu.addAction('粘贴（Ctrl+V）', self.paste_selection)
        menu.addAction('删除单元格内容（Delete）', self.delete_selection)
        if hasattr(self, 'delete_selected_rows'):
            menu.addAction('删除选中行', self.delete_selected_rows)
        if hasattr(self, 'add_rows'):
            menu.addAction('新增一行', self.add_rows)
        menu.addSeparator(); menu.addAction('全选', self.selectAll)
        menu.exec(event.globalPos())

    def _can_edit_current_cell(self):
        """右键菜单中的就地编辑入口：空白格也允许先创建后编辑。"""
        try:
            row,column=self.currentRow(),self.currentColumn()
            if row<0 or column<0 or self.cellWidget(row,column) is not None:return False
            item=self.item(row,column)
            return item is None or bool(item.flags() & Qt.ItemFlag.ItemIsEditable)
        except Exception:
            return False

    def edit_current_cell(self):
        """以与双击一致的方式编辑当前格，避免右键后只能使用长文本弹窗。"""
        if not self._can_edit_current_cell():return False
        row,column=self.currentRow(),self.currentColumn();item=self.item(row,column)
        if item is None:
            item=QTableWidgetItem("");self.setItem(row,column,item)
        formula=item.data(_UserRole + 11)
        if formula:
            self.blockSignals(True);item.setText(str(formula));self.blockSignals(False)
        self.setCurrentItem(item);self.editItem(item);return True

    def _cell_text_for_clipboard(self, row, column):
        widget = self.cellWidget(row, column)
        if isinstance(widget, QComboBox):
            return widget.currentText()
        if isinstance(widget, QCheckBox):
            return 'YES' if widget.isChecked() else 'NO'
        item = self.item(row, column)
        return item.text() if item else ''

    def _write_pasted_value(self, row, column, value):
        if row >= self.rowCount():
            self.setRowCount(row + 1)
        if column >= self.columnCount():
            self.setColumnCount(column + 1)
        widget = self.cellWidget(row, column)
        if isinstance(widget, QComboBox):
            index = widget.findText(value)
            if index >= 0:
                widget.setCurrentIndex(index)
            return
        if isinstance(widget, QCheckBox):
            widget.setChecked(str(value).strip().upper() in ('1', 'TRUE', 'YES', 'Y', 'ON'))
            return
        item = self.item(row, column)
        if not item:
            item = QTableWidgetItem()
            self.setItem(row, column, item)
        item.setText(str(value))

    def _clipboard_grid(self):
        """优先解析浏览器/Google 表格提供的 HTML，再退回 TSV 纯文本。"""
        mime = QApplication.clipboard().mimeData()
        rows = []
        if mime.hasHtml():
            class _TableParser(HTMLParser):
                def __init__(self):
                    super().__init__(convert_charrefs=True); self.rows=[]; self.current=None; self.cell=None; self.colspan=1
                def handle_starttag(self, tag, attrs):
                    tag=tag.lower()
                    if tag == 'tr': self.current=[]
                    elif tag in ('td','th') and self.current is not None:
                        self.cell=[]; self.colspan=max(1, int(dict(attrs).get('colspan','1') or 1))
                    elif tag == 'br' and self.cell is not None: self.cell.append('\n')
                def handle_data(self, data):
                    if self.cell is not None: self.cell.append(data)
                def handle_endtag(self, tag):
                    tag=tag.lower()
                    if tag in ('td','th') and self.current is not None and self.cell is not None:
                        self.current.append(''.join(self.cell).strip()); self.current.extend(['']*(self.colspan-1)); self.cell=None
                    elif tag == 'tr' and self.current is not None:
                        self.rows.append(self.current); self.current=None
            try:
                parser=_TableParser(); parser.feed(mime.html()); rows=parser.rows
            except Exception as error:
                write_debug(f'HTML Paste Error: {error}')
        if rows:
            return rows
        text=mime.text().replace('\r\n','\n').replace('\r','\n')
        if not text:
            return []
        values=list(csv.reader(io.StringIO(text), delimiter='\t'))
        return values or [[text]]

    def copy_selection(self):
        """复制精确选中的格子；不连续多选区域以空格占位，绝不夹带未选内容。"""
        indexes={(index.row(), index.column()) for index in self.selectedIndexes()}
        if not indexes:
            return
        top,bottom=min(row for row,_ in indexes),max(row for row,_ in indexes)
        left,right=min(col for _,col in indexes),max(col for _,col in indexes)
        output=io.StringIO(); writer=csv.writer(output, delimiter='\t', quoting=csv.QUOTE_MINIMAL)
        for row in range(top,bottom+1):
            writer.writerow([self._cell_text_for_clipboard(row,column) if (row,column) in indexes else '' for column in range(left,right+1)])
        QApplication.clipboard().setText(output.getvalue())

    def paste_selection(self):
        try:
            rows_data=self._clipboard_grid()
            if not rows_data:
                return
            before=self._history_snapshot()
            selected=sorted({(index.row(), index.column()) for index in self.selectedIndexes()})
            self.blockSignals(True)
            try:
                # Excel 行为：已有多格选择时，用剪贴板矩阵平铺整个选区；单个值自然填满全部选择。
                if len(selected) > 1:
                    top,bottom=min(row for row,_ in selected),max(row for row,_ in selected)
                    left,right=min(col for _,col in selected),max(col for _,col in selected)
                    rectangular=len(selected)==(bottom-top+1)*(right-left+1)
                    if rectangular:
                        for row in range(top,bottom+1):
                            source_row=rows_data[(row-top)%len(rows_data)]
                            for column in range(left,right+1):
                                value=source_row[(column-left)%max(1,len(source_row))] if source_row else ''
                                self._write_pasted_value(row,column,value)
                    else:
                        values=[value for source_row in rows_data for value in source_row] or ['']
                        for index,(row,column) in enumerate(selected):
                            self._write_pasted_value(row,column,values[index%len(values)])
                else:
                    start_row,start_column=(selected[0] if selected else (max(0,self.currentRow()),max(0,self.currentColumn())))
                    for row_offset,source_row in enumerate(rows_data):
                        for column_offset,value in enumerate(source_row):
                            self._write_pasted_value(start_row+row_offset,start_column+column_offset,value)
            finally:
                self.blockSignals(False)
            self._commit_history_snapshot(before)
        except Exception as error:
            write_debug(f'Paste Error: {error}')

    def delete_selection(self):
        before=self._history_snapshot()
        self.blockSignals(True)
        try:
            for item in self.selectedItems():
                item.setText('')
            for r in range(self.rowCount()):
                for c in range(self.columnCount()):
                    if self.item(r, c) and self.item(r, c).isSelected():
                        w = self.cellWidget(r, c)
                        if isinstance(w, QCheckBox):
                            w.setChecked(False)
        finally:
            self.blockSignals(False)
        self._commit_history_snapshot(before)

    def add_mode_combo(self, row):
        combo = QComboBox()
        combo.addItems(['包含', '开头是', '结尾是', '后缀名', '完全匹配', '正则表达式'])
        combo.currentIndexChanged.connect(self.trigger_main_save)
        self.setCellWidget(row, 1, combo)

class DraggableTableWidget(ExcelTable):
    """不再支持拖拽（防止崩溃），仅作为带 ObjectName 的 ExcelTable 子类。支持公式计算。"""
    row_moved = pyqtSignal()

    def __init__(self, rows, cols, parent=None):
        super().__init__(rows, cols, parent)
        self.setSelectionBehavior(_SelectItems)
        self.verticalHeader().setVisible(True)
        self.horizontalHeader().setSectionsMovable(True)
        self.verticalHeader().setSectionsMovable(True)
        self.horizontalHeader().sectionMoved.connect(self.on_section_moved)
        self.verticalHeader().sectionMoved.connect(self.on_section_moved)
        self.itemChanged.connect(self.on_item_changed)
        self.itemDoubleClicked.connect(self.on_item_double_clicked)
        self._is_calculating = False
        self.update_headers()

    def on_section_moved(self, logicalIndex, oldVisualIndex, newVisualIndex):
        """行列移动后，重新刷新坐标和计算"""
        self.update_headers()
        self.recalculate_all()
        main_win = self.window()
        if hasattr(main_win, 'trigger_save'):
            main_win.trigger_save()

    def update_headers(self):
        """彻底固定视觉坐标：无论数据如何拖拽，位置上的 A,B,C 永远不动"""
        self.blockSignals(True)
        h_header = self.horizontalHeader()
        v_header = self.verticalHeader()
        for visual_idx in range(self.columnCount()):
            logical_idx = h_header.logicalIndex(visual_idx)
            col_name = FormulaEngine.index_to_col(visual_idx)
            self.setHorizontalHeaderItem(logical_idx, QTableWidgetItem(col_name))
        for visual_idx in range(self.rowCount()):
            logical_idx = v_header.logicalIndex(visual_idx)
            self.setVerticalHeaderItem(logical_idx, QTableWidgetItem(str(visual_idx + 1)))
        self.blockSignals(False)

    def on_item_double_clicked(self, item):
        formula = item.data(_UserRole + 11)
        if formula:
            self.blockSignals(True)
            item.setText(formula)
            self.blockSignals(False)
            self._is_editing_formula = True

    def closeEditor(self, editor, hint):
        super().closeEditor(editor, hint)
        if getattr(self, '_is_editing_formula', False):
            self._is_editing_formula = False
            self.recalculate_all()

    def on_item_changed(self, item):
        if self._is_calculating:
            return
        text = item.text().strip()
        if not text.startswith('='):
            item.setData(_UserRole + 11, None)
            item.setForeground(QColor('black'))
            item.setToolTip('')
        self.recalculate_all()

    def recalculate_all(self):
        """重新计算表格中所有的公式"""
        if self._is_calculating:
            return
        self._is_calculating = True
        self.blockSignals(True)
        try:
            for _ in range(3):
                changed = False
                for r in range(self.rowCount()):
                    for c in range(self.columnCount()):
                        item = self.item(r, c)
                        if not item:
                            continue
                        current_text = item.text().strip()
                        formula = item.data(_UserRole + 11)
                        if current_text.startswith('='):
                            formula = current_text
                            item.setData(_UserRole + 11, formula)
                        if formula and formula.startswith('='):
                            result = FormulaEngine.evaluate(formula, self)
                            item.setData(_UserRole + 10, result)
                            new_display = str(result)
                            if item.text() != new_display:
                                item.setText(new_display)
                                item.setForeground(QColor('#005fb8'))
                                item.setToolTip(f'公式: {formula}')
                                changed = True
                if not changed:
                    break
        finally:
            self.blockSignals(False)
            self._is_calculating = False

    def move_row_up(self, row):
        if row <= 0:
            return
        self._move_row_logic(row, row - 1)
        self.setCurrentCell(row - 1, self.currentColumn())
        self.row_moved.emit()

    def move_row_down(self, row):
        if row < 0 or row >= self.rowCount() - 1:
            return
        self._move_row_logic(row, row + 1)
        self.setCurrentCell(row + 1, self.currentColumn())
        self.row_moved.emit()

    def _move_row_logic(self, row_a, row_b):
        """将 row_a 和 row_b 的数据进行完美互换（原地互换，绝不丢失数据）"""
        if row_a < 0 or row_b < 0 or row_a >= self.rowCount() or (row_b >= self.rowCount()):
            return
        self.blockSignals(True)

        def get_row_data(row):
            data = []
            for col in range(self.columnCount()):
                widget = self.cellWidget(row, col)
                if isinstance(widget, QCheckBox):
                    data.append(('check', widget.isChecked()))
                elif isinstance(widget, QComboBox):
                    data.append(('combo', widget.currentText(), [widget.itemText(i) for i in range(widget.count())]))
                else:
                    item = self.item(row, col)
                    data.append(('item', item.text() if item else '', item.foreground() if item else None, item.font() if item else None))
            return data

        def set_row_data(row, data):
            note_w = self.parent()
            while note_w and (not hasattr(note_w, 'trigger_save')):
                note_w = note_w.parent()
            for col, d in enumerate(data):
                if d[0] == 'check':
                    cb = QCheckBox()
                    cb.setChecked(d[1])
                    if note_w:
                        cb.toggled.connect(note_w.trigger_save)
                    self.setCellWidget(row, col, cb)
                elif d[0] == 'combo':
                    combo = QComboBox()
                    combo.addItems(d[2])
                    combo.setCurrentText(d[1])
                    if note_w:
                        combo.currentTextChanged.connect(note_w.trigger_save)
                    self.setCellWidget(row, col, combo)
                else:
                    it = QTableWidgetItem(d[1])
                    if d[2]:
                        it.setForeground(d[2])
                    if d[3]:
                        it.setFont(d[3])
                    self.setItem(row, col, it)
        data_a = get_row_data(row_a)
        data_b = get_row_data(row_b)
        set_row_data(row_a, data_b)
        set_row_data(row_b, data_a)
        self.blockSignals(False)

class ClipFastMatchThread(QThread):
    """
    CLIP 极速图文匹配线程。
    不依赖大型视觉语言模型，直接利用 CLIP 模型计算图文余弦相似度。
    显存占用仅约 300MB，匹配速度比大模型快 10-50 倍。
    支持图片特征向量缓存，重复运行时无需重新编码图片。
    """
    progress = pyqtSignal(int)
    log = pyqtSignal(str, str)
    result = pyqtSignal(dict)
    error = pyqtSignal(str)
    _img_feature_cache = {}
    # 缓存向量只可由同一 CLIP 模型复用；不同模型的向量维度并不相同。
    _img_feature_cache_model_name = ''
    _clip_model = None
    _clip_model_name = ''

    def __init__(self, image_paths, scripts, clip_model_name='OFA-Sys/chinese-clip-vit-large-patch14', top_k=3, use_gpu=True):
        super().__init__()
        self.image_paths = image_paths
        self.scripts = scripts
        self.clip_model_name = clip_model_name
        self.top_k = top_k
        self.use_gpu = use_gpu
        self._stop = False

    def stop(self):
        self._stop = True

    @staticmethod
    def _normalize_match_text(text):
        text = str(text or '').strip().lower()
        return re.sub('[\\s_\\-\\\\/|,，、;；:：·]+', '', text)

    @classmethod
    def _build_remark_keywords(cls, remark):
        """从备注/特殊要求中提取用于路径匹配的关键词。"""
        remark = str(remark or '').strip()
        if not remark:
            return []
        parts = re.split('[\\n\\r,，、;；|/]+', remark)
        keywords = []
        for part in parts:
            part = str(part or '').strip()
            if not part:
                continue
            keywords.append(part.lower())
            compact = cls._normalize_match_text(part)
            if compact and compact not in keywords:
                keywords.append(compact)
        full_compact = cls._normalize_match_text(remark)
        if full_compact and full_compact not in keywords:
            keywords.append(full_compact)
        keywords = sorted(set([k for k in keywords if k]), key=len, reverse=True)
        return keywords

    @classmethod
    def _build_path_priority_bonus(cls, remark, image_paths):
        """
        根据备注中的关键词，对命中文件夹/路径名的图片给予强优先级加分。
        返回: bonus(np.ndarray), hit_count(int)
        """
        import numpy as np
        keywords = cls._build_remark_keywords(remark)
        if not keywords:
            return (np.zeros(len(image_paths), dtype=np.float32), 0)
        bonus = np.zeros(len(image_paths), dtype=np.float32)
        hit_count = 0
        for idx, p in enumerate(image_paths):
            path_str = str(p or '')
            path_lower = path_str.lower()
            norm_path = cls._normalize_match_text(path_lower)
            dir_parts = [x for x in re.split('[\\\\/]+', os.path.dirname(path_lower)) if x]
            base_name = os.path.splitext(os.path.basename(path_lower))[0]
            norm_base = cls._normalize_match_text(base_name)
            best = 0.0
            for kw in keywords:
                kw_lower = kw.lower()
                kw_norm = cls._normalize_match_text(kw_lower)
                if not kw_norm:
                    continue
                if any((d == kw_lower or cls._normalize_match_text(d) == kw_norm for d in dir_parts)):
                    best = max(best, 0.6)
                elif any((kw_lower in d or kw_norm in cls._normalize_match_text(d) for d in dir_parts)):
                    best = max(best, 0.42)
                elif kw_lower in base_name or kw_norm in norm_base:
                    best = max(best, 0.28)
                elif kw_lower in path_lower or kw_norm in norm_path:
                    best = max(best, 0.18)
            bonus[idx] = best
            if best > 0:
                hit_count += 1
        return (bonus, hit_count)

    @staticmethod
    def _build_requirement_prompt(content, remark):
        """把用户自由填写的备注与文案合成一个完整画面意图，不预设词表或规则。"""
        return f"请寻找一张能够同时表达以下完整画面意图的图片。\n文案场景：{str(content or '').strip()}\n补充要求：{str(remark or '').strip()}"

    @classmethod
    def _load_clip_model(cls, model_name, use_gpu, log_fn):
        """CLIP 模型延迟加载（类级单例，避免重复加载）。

        默认使用中文增强版 CLIP 模型，如果用户未指定或指定了不支持的名称。
        """
        default_chinese_clip = 'OFA-Sys/chinese-clip-vit-large-patch14'
        normalized_name = (model_name or default_chinese_clip).strip()
        if not normalized_name:
            normalized_name = default_chinese_clip
        previous_cache_model = str(getattr(cls, '_img_feature_cache_model_name', '') or '')
        if cls._img_feature_cache and previous_cache_model != normalized_name:
            old_label = previous_cache_model or '旧版未知模型'
            cls._img_feature_cache.clear()
            log_fn(f'🔄 检测到 CLIP 模型已从 {old_label} 切换为 {normalized_name}；已自动清除不兼容的图片特征缓存，并将重新编码图片。', 'orange')
        cls._img_feature_cache_model_name = normalized_name
        if cls._clip_model is not None and cls._clip_model_name == normalized_name:
            return cls._clip_model

        # 独立工作台同样使用兼容缓存和自身的进度统计，避免 Windows/U 盘环境只
        # 显示 Hugging Face 的技术警告、用户却看不到实际下载进度。
        os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING', '1')
        warnings.filterwarnings('ignore', message=r'You are sending unauthenticated requests to the HF Hub.*')
        cache_root = os.environ.get('HF_HOME', '')
        cache_dir = os.path.join(cache_root, 'hub', 'models--' + normalized_name.replace('/', '--'))
        try:
            snapshots = os.path.join(cache_dir, 'snapshots')
            has_cached_model = os.path.isdir(snapshots) and any(os.scandir(snapshots))
        except Exception:
            has_cached_model = False
        if has_cached_model:
            log_fn(f'📦 正在从本地缓存加载 CLIP 模型：{normalized_name}…', 'blue')
        else:
            log_fn(f'📥 首次模型下载提醒：CLIP 模型 {normalized_name} 尚未在本机缓存中找到，正在下载并加载。首次可能需要数分钟，请勿关闭软件；完成后将直接使用缓存。', 'orange')
            log_fn('💾 本机使用兼容缓存：不影响模型下载或匹配；首次缓存可能比支持开发者模式的 Windows 多占少量空间。', 'gray')

        download_monitor_stop = Event()
        if not has_cached_model:
            expected_sizes = {
                'OFA-Sys/chinese-clip-vit-large-patch14': 1.63 * 1024 ** 3,
                'OFA-Sys/chinese-clip-vit-base-patch16': 0.753 * 1024 ** 3,
                'clip-ViT-L-14': 1.71 * 1024 ** 3,
                'clip-ViT-B-16': 0.599 * 1024 ** 3,
                'clip-ViT-B-32': 0.605 * 1024 ** 3,
            }
            expected_bytes = expected_sizes.get(normalized_name, 1.0 * 1024 ** 3)
            def _watch_clip_download():
                last_bytes, last_time, last_notice = -1, time.monotonic(), 0.0
                while not download_monitor_stop.wait(1.0):
                    downloaded = 0
                    try:
                        for root, _, files in os.walk(cache_dir):
                            for filename in files:
                                if filename.endswith('.incomplete'):
                                    try: downloaded += os.path.getsize(os.path.join(root, filename))
                                    except OSError: pass
                    except OSError:
                        pass
                    now = time.monotonic()
                    if downloaded > 0 and downloaded != last_bytes:
                        speed = max(0, downloaded - max(0, last_bytes)) / max(.1, now - last_time) / 1024 ** 2
                        percent = min(99, int(downloaded * 100 / expected_bytes))
                        log_fn(f'📥 CLIP 下载进度：{downloaded / 1024 ** 2:.1f} MB / {expected_bytes / 1024 ** 3:.2f} GB（{percent}%，{speed:.1f} MB/s）', 'blue')
                        last_bytes, last_time, last_notice = downloaded, now, now
                    elif now - last_notice >= 12:
                        log_fn('🌐 CLIP 下载准备中：正在连接或校验文件，请保持网络连接…', 'gray')
                        last_notice = now
            threading.Thread(target=_watch_clip_download, name='clip-download-progress', daemon=True).start()
        device = 'cpu'
        if use_gpu:
            try:
                import torch
                if torch.cuda.is_available():
                    device = 'cuda'
                    log_fn('✅ 检测到 CUDA，CLIP 将使用 GPU 加速', 'green')
                else:
                    log_fn('⚠️ 未检测到 CUDA (Torch版本不匹配或无NVIDIA显卡)，将使用 CPU 运行。', 'orange')
                    log_fn('💡 提示：若您有NVIDIA显卡，请在终端运行：pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121', 'gray')
            except Exception:
                pass
        st_load_error = None
        tf_load_error = None
        try:
            from sentence_transformers import SentenceTransformer
            log_fn(f'⏳ 正在加载 CLIP 模型: {normalized_name}（首次需下载，后续将直接从缓存读取）', 'blue')
            cls._clip_model = SentenceTransformer(normalized_name, device=device)
            cls._clip_model_name = normalized_name
            download_monitor_stop.set()
            log_fn(f'✅ CLIP 模型加载完成 (device={device})', 'green')
            return cls._clip_model
        except Exception as e:
            st_load_error = e
            msg = str(e)
            if 'upgrade torch to at least v2.6' in msg or 'CVE-2025-32434' in msg:
                log_fn(f'⚠️ sentence-transformers 因 PyTorch 版本安全限制拒绝加载（{e}）', 'orange')
                log_fn('💡 解决思路：升级 torch>=2.6，或改用 Transformers(优先 safetensors) / cn_clip 加载。', 'gray')
            else:
                log_fn(f'⚠️ sentence-transformers 加载失败 ({e})', 'orange')
        try:
            import torch
            log_fn('🔄 尝试使用 Transformers 直接加载 CLIP（优先 safetensors）...', 'gray')
            import sys
            if getattr(sys, 'stdout', None) is None:
                sys.stdout = open(os.devnull, 'w', encoding='utf-8')
            if getattr(sys, 'stderr', None) is None:
                sys.stderr = open(os.devnull, 'w', encoding='utf-8')
            os.environ.setdefault('TOKENIZERS_PARALLELISM', 'false')
            from transformers import CLIPModel, CLIPProcessor
            torch_device = torch.device(device)
            try:
                clip_model = CLIPModel.from_pretrained(normalized_name, use_safetensors=True)
            except Exception:
                clip_model = CLIPModel.from_pretrained(normalized_name, use_safetensors=False)
            clip_processor = CLIPProcessor.from_pretrained(normalized_name)
            clip_model.eval().to(torch_device)

            class TransformersClipAdapter:

                def __init__(self, model, processor, device):
                    self.model = model
                    self.processor = processor
                    self.device = device

                def _batched(self, items, batch_size):
                    for i in range(0, len(items), max(1, int(batch_size))):
                        yield items[i:i + max(1, int(batch_size))]

                def encode(self, sentences, batch_size=32, show_progress_bar=False, convert_to_numpy=True):
                    from PIL import Image
                    import numpy as np
                    import torch
                    if not sentences:
                        return np.zeros((0, 512), dtype=np.float32)
                    is_image = isinstance(sentences[0], Image.Image)
                    feats_all = []

                    def _extract_2d_embedding(model_out, want: str):
                        """
                        将各种 Transformers 输出统一抽取成 (B, D) 的 embedding 张量。
                        want: "image" 或 "text"
                        """
                        if want == 'image' and hasattr(model_out, 'image_embeds') and (model_out.image_embeds is not None):
                            return model_out.image_embeds
                        if want == 'text' and hasattr(model_out, 'text_embeds') and (model_out.text_embeds is not None):
                            return model_out.text_embeds
                        if torch.is_tensor(model_out):
                            return model_out
                        if hasattr(model_out, 'pooler_output') and model_out.pooler_output is not None:
                            return model_out.pooler_output
                        if hasattr(model_out, 'last_hidden_state') and model_out.last_hidden_state is not None:
                            lhs = model_out.last_hidden_state
                            if torch.is_tensor(lhs):
                                if lhs.dim() == 3:
                                    return lhs[:, 0, :]
                                if lhs.dim() == 2:
                                    return lhs
                        if isinstance(model_out, (tuple, list)):
                            for x in model_out:
                                if torch.is_tensor(x) and x.dim() == 2:
                                    return x
                            if len(model_out) >= 2 and torch.is_tensor(model_out[1]):
                                return model_out[1]
                        raise TypeError(f'无法从 Transformers 输出中提取 embedding: {type(model_out)}')
                    with torch.no_grad():
                        if is_image:
                            for batch in self._batched(sentences, batch_size):
                                inputs = self.processor(images=batch, return_tensors='pt')
                                inputs = inputs.to(self.device)
                                if 'pixel_values' in inputs and hasattr(self.model, 'vision_model'):
                                    vout = self.model.vision_model(pixel_values=inputs['pixel_values'])
                                    feats = _extract_2d_embedding(vout, 'image')
                                    if hasattr(self.model, 'visual_projection'):
                                        feats = self.model.visual_projection(feats)
                                else:
                                    out = self.model(**inputs)
                                    feats = _extract_2d_embedding(out, 'image')
                                feats = feats / (feats.norm(dim=-1, keepdim=True) + 1e-08)
                                feats_all.append(feats.detach().cpu())
                        else:
                            for batch in self._batched(sentences, batch_size):
                                inputs = self.processor(text=batch, padding=True, truncation=True, return_tensors='pt')
                                inputs = inputs.to(self.device)
                                if 'input_ids' in inputs and hasattr(self.model, 'text_model'):
                                    tout = self.model.text_model(input_ids=inputs.get('input_ids'), attention_mask=inputs.get('attention_mask', None))
                                    feats = _extract_2d_embedding(tout, 'text')
                                    if hasattr(self.model, 'text_projection'):
                                        feats = self.model.text_projection(feats)
                                else:
                                    out = self.model(**inputs)
                                    feats = _extract_2d_embedding(out, 'text')
                                feats = feats / (feats.norm(dim=-1, keepdim=True) + 1e-08)
                                feats_all.append(feats.detach().cpu())
                    feats_all = torch.cat(feats_all, dim=0) if feats_all else torch.zeros((0, 512))
                    return feats_all.numpy() if convert_to_numpy else feats_all
            cls._clip_model = TransformersClipAdapter(clip_model, clip_processor, torch_device)
            cls._clip_model_name = normalized_name
            download_monitor_stop.set()
            log_fn(f'✅ Transformers CLIP 加载完成 (device={device})', 'green')
            return cls._clip_model
        except Exception as e:
            tf_load_error = e
            log_fn(f'⚠️ Transformers 加载失败 ({e})，尝试使用 cn_clip 官方库加载...', 'orange')
        try:
            import torch
            try:
                import cn_clip.clip as clip
                from cn_clip.clip import load_from_name
            except ImportError:
                log_fn('📦 检测到 cn_clip 缺失，正在自动安装 cn-clip...', 'blue')
                if not _silent_install_libs(['cn_clip'], timeout=1800, log_prefix='[CN-CLIP]'):
                    raise ImportError('缺失 cn_clip 库，且自动安装失败。')
                import importlib
                importlib.invalidate_caches()
                import cn_clip.clip as clip
                from cn_clip.clip import load_from_name
            model_short_name = normalized_name.split('/')[-1].replace('chinese-clip-', '').upper()
            if model_short_name == 'VIT-L-14':
                model_short_name = 'ViT-L-14'
            elif model_short_name == 'VIT-H-14':
                model_short_name = 'ViT-H-14'
            elif model_short_name == 'VIT-B-16':
                model_short_name = 'ViT-B-16'
            elif model_short_name == 'RN50':
                model_short_name = 'RN50'
            else:
                model_short_name = 'ViT-L-14'
            log_fn(f'⏳ 正在加载 CN-CLIP 模型: {model_short_name}（首次需下载，后续将直接从缓存读取）', 'blue')
            model, preprocess = load_from_name(model_short_name, device=device, download_root=os.environ['HF_HOME'], use_modelscope=True)

            class CnClipAdapter:

                def __init__(self, model, preprocess, device):
                    self.model = model.eval().to(device)
                    self.preprocess = preprocess
                    self.device = device

                def encode(self, sentences, batch_size=32, show_progress_bar=False, convert_to_numpy=True):
                    from PIL import Image
                    import numpy as np
                    import torch
                    if isinstance(sentences[0], Image.Image):
                        processed_images = torch.stack([self.preprocess(img) for img in sentences]).to(self.device)
                        with torch.no_grad():
                            features = self.model.encode_image(processed_images)
                    else:
                        tokenized_texts = clip.tokenize(sentences).to(self.device)
                        with torch.no_grad():
                            features = self.model.encode_text(tokenized_texts)
                    features /= features.norm(dim=-1, keepdim=True)
                    return features.cpu().numpy() if convert_to_numpy else features
            cls._clip_model = CnClipAdapter(model, preprocess, device)
            cls._clip_model_name = normalized_name
            download_monitor_stop.set()
            log_fn(f'✅ CN-CLIP 模型加载完成 (device={device})', 'green')
            return cls._clip_model
        except Exception as cn_e:
            download_monitor_stop.set()
            final_error_msg = f'CLIP 模型加载失败：\n  - sentence-transformers 尝试失败: {st_load_error}\n  - transformers 尝试失败: {tf_load_error}\n  - cn_clip 尝试失败: {cn_e}\n建议按优先级排查：\n  1) 安装/更新 safetensors + transformers（优先使用 safetensors 权重）\n  2) 或安装 cn_clip 作为兜底（pip install cn_clip）\n  3) 最后再考虑升级 torch>=2.6\n并确认模型名称正确。'
            raise RuntimeError(final_error_msg)

    @classmethod
    def clear_cache(cls):
        """  清除图片特征缓存。"""
        cls._img_feature_cache.clear()
        cls._img_feature_cache_model_name = ''

    def run(self):
        try:
            total_images = len(self.image_paths)
            total_scripts = len(self.scripts)
            if total_images == 0:
                self.error.emit('没有可处理的图片池')
                return
            if total_scripts == 0:
                self.error.emit('表格中没有文案内容')
                return
            self.log.emit(f'⚡ [CLIP 极速模式] 开始：{total_images} 张图片 × {total_scripts} 条文案', 'blue')
            self.progress.emit(2)
            model = self._load_clip_model(self.clip_model_name, self.use_gpu, self.log.emit)
            self.log.emit('🖼️ 正在提取图片特征向量（已缓存的图片直接跳过）...', 'blue')
            uncached = [p for p in self.image_paths if p not in self.__class__._img_feature_cache]
            if uncached:
                try:
                    from PIL import Image as _PILImage
                    pil_images = []
                    valid_paths = []
                    for p in uncached:
                        try:
                            img = _PILImage.open(p).convert('RGB')
                            img.thumbnail((336, 336))
                            pil_images.append(img)
                            valid_paths.append(p)
                        except Exception as img_e:
                            self.log.emit(f'⚠️ 图片读取失败，跳过: {os.path.basename(p)} ({img_e})', 'orange')
                    if pil_images:
                        feats = model.encode(pil_images, batch_size=16, show_progress_bar=False, convert_to_numpy=True)
                        for path, feat in zip(valid_paths, feats):
                            self.__class__._img_feature_cache[path] = feat
                except Exception as enc_e:
                    self.error.emit(f'CLIP 图片编码失败: {enc_e}')
                    return
            cached_count = total_images - len(uncached)
            self.log.emit(f'✅ 图片特征就绪（新编码 {len(uncached)} 张，命中缓存 {cached_count} 张）', 'green')
            self.progress.emit(30)
            import numpy as np
            img_feat_list = []
            valid_img_paths = []
            for p in self.image_paths:
                if p in self.__class__._img_feature_cache:
                    img_feat_list.append(self.__class__._img_feature_cache[p])
                    valid_img_paths.append(p)
            if not img_feat_list:
                self.error.emit('所有图片特征提取失败')
                return
            img_matrix = np.array(img_feat_list)
            norms = np.linalg.norm(img_matrix, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1e-08, norms)
            img_matrix_norm = img_matrix / norms
            match_result = {}
            valid_scripts = []
            sims_rows = []
            path_bonus_rows = []
            requirement_fused_rows = []
            score_component_rows = []
            for s_idx, script in enumerate(self.scripts):
                if self._stop:
                    self.log.emit('⚠️ 已手动停止', 'orange')
                    break
                row_idx = script['row']
                content = (script.get('cn', '') or script.get('en', '')).strip()
                remark = script.get('remark', '').strip()
                if not content and (not remark):
                    continue
                try:
                    content_feat = model.encode([content], convert_to_numpy=True)[0] if content else None
                    content_norm = content_feat / (np.linalg.norm(content_feat) + 1e-08) if content_feat is not None else None
                    remark_feat = None
                    requirement_feat = None
                    if remark:
                        raw_remark_feat = model.encode([remark], convert_to_numpy=True)[0]
                        requirement_feat = model.encode([self.__class__._build_requirement_prompt(content, remark)], convert_to_numpy=True)[0]
                        remark_feat = raw_remark_feat
                    remark_norm = remark_feat / (np.linalg.norm(remark_feat) + 1e-08) if remark_feat is not None else None
                    requirement_norm = requirement_feat / (np.linalg.norm(requirement_feat) + 1e-08) if requirement_feat is not None else None
                    content_sims = img_matrix_norm @ content_norm if content_norm is not None else np.zeros(len(valid_img_paths))
                    remark_sims = img_matrix_norm @ remark_norm if remark_norm is not None else np.zeros(len(valid_img_paths))
                    requirement_sims = img_matrix_norm @ requirement_norm if requirement_norm is not None else np.zeros(len(valid_img_paths))
                    if remark:
                        combined_sims = remark_sims * 0.85 + requirement_sims * 0.10 + content_sims * 0.05
                        self.log.emit(f'🧠 第 {row_idx + 1} 行按备注优先匹配（备注85% / 完整意图10% / 文案5%）：{remark[:64]}', 'blue')
                    else:
                        combined_sims = content_sims
                    path_bonus, hit_count = self.__class__._build_path_priority_bonus(remark, valid_img_paths)
                    if hit_count > 0:
                        self.log.emit(f'📁 第 {row_idx + 1} 行备注命中 {hit_count} 张路径/文件夹，优先从这些图片中选择', 'gray')
                        combined_sims = combined_sims + path_bonus
                    valid_scripts.append({'script': script, 'row': row_idx, 'cn': content, 'en': script.get('en', ''), 'remark': remark})
                    sims_rows.append(combined_sims.astype(np.float32))
                    path_bonus_rows.append(path_bonus.astype(np.float32))
                    requirement_fused_rows.append(bool(remark))
                    score_component_rows.append((remark_sims, requirement_sims, content_sims))
                except Exception as e:
                    self.log.emit(f'❌ 第 {row_idx + 1} 行特征提取失败，已跳过: {e}', 'red')
                self.progress.emit(30 + int((s_idx + 1) / max(1, total_scripts) * 35))
            if not valid_scripts:
                self.error.emit('没有可用于匹配的文案内容（全部为空或特征提取失败）')
                return
            sims_matrix = np.vstack(sims_rows)
            M, N = sims_matrix.shape
            assignment_sims = sims_matrix.astype(np.float64) - (np.arange(N, dtype=np.float64)[None, :] * 1e-12)

            def _hungarian_min_cost(cost_matrix):
                """
                匈牙利算法（最小化成本），支持行数<=列数的矩形矩阵。
                cost_matrix: List[List[float]]，shape=(rows, cols)
                return: assignment 列索引列表，长度=rows，每个元素为 0..cols-1
                """
                rows = len(cost_matrix)
                cols = len(cost_matrix[0]) if rows else 0
                u = [0.0] * (rows + 1)
                v = [0.0] * (cols + 1)
                p = [0] * (cols + 1)
                way = [0] * (cols + 1)
                INF = 1e+30
                for i in range(1, rows + 1):
                    p[0] = i
                    j0 = 0
                    minv = [INF] * (cols + 1)
                    used = [False] * (cols + 1)
                    while True:
                        used[j0] = True
                        i0 = p[j0]
                        delta = INF
                        j1 = 0
                        for j in range(1, cols + 1):
                            if not used[j]:
                                cur = cost_matrix[i0 - 1][j - 1] - u[i0] - v[j]
                                if cur < minv[j]:
                                    minv[j] = cur
                                    way[j] = j0
                                if minv[j] < delta:
                                    delta = minv[j]
                                    j1 = j
                        for j in range(0, cols + 1):
                            if used[j]:
                                u[p[j]] += delta
                                v[j] -= delta
                            else:
                                minv[j] -= delta
                        j0 = j1
                        if p[j0] == 0:
                            break
                    while True:
                        j1 = way[j0]
                        p[j0] = p[j1]
                        j0 = j1
                        if j0 == 0:
                            break
                assignment = [-1] * rows
                for j in range(1, cols + 1):
                    if p[j] != 0:
                        assignment[p[j] - 1] = j - 1
                return assignment
            cols = max(N, M)
            if cols != N:
                pad = np.full((M, cols - N), -1000000000.0, dtype=np.float64)
                sims_matrix_pad = np.hstack([assignment_sims, pad])
            else:
                sims_matrix_pad = assignment_sims
            cost_matrix = (-sims_matrix_pad).tolist()
            assign_cols = _hungarian_min_cost(cost_matrix)
            matched = 0
            for i, j in enumerate(assign_cols):
                meta = valid_scripts[i]
                row_idx = meta['row']
                if j is None or j < 0 or j >= N:
                    self.log.emit(f'❓ 第 {row_idx + 1} 行：图片不足或未分配到有效图片', 'orange')
                    continue
                sel_path = valid_img_paths[j]
                sim = float(sims_matrix[i, j])
                path_bonus_val = float(path_bonus_rows[i][j]) if i < len(path_bonus_rows) and j < len(path_bonus_rows[i]) else 0.0
                remark_part, intent_part, content_part = (float(x[j]) for x in score_component_rows[i])
                final_score = round(sim * 100, 1)
                match_result[sel_path] = {'row': row_idx, 'score': final_score, 'reason': (f"CLIP相似度:{sim:.3f} (全局最优{(' / 备注:' + format(remark_part, '.3f') + '、完整意图:' + format(intent_part, '.3f') + '、文案:' + format(content_part, '.3f') if requirement_fused_rows[i] else '')}{(' / 备注路径优先' if path_bonus_val > 0 else '')})"), 'cn': meta['cn'], 'en': meta['en']}
                matched += 1
                self.log.emit(f'✅ 第 {row_idx + 1} 行 → {os.path.basename(sel_path)} (得分: {final_score})', 'green')
                self.progress.emit(65 + int((i + 1) / max(1, M) * 35))
            self.log.emit(f'⚡ CLIP 匹配完成！共 {matched} 组结果（全局最优一对一）。', 'green')
            self.result.emit(match_result)
        except Exception as e:
            err_msg = traceback.format_exc()
            self.error.emit(f'CLIP 匹配线程异常: {e}\n{err_msg}')
            QTimer.singleShot(0, lambda: QMessageBox.critical(None, '后台线程崩溃', f'ClipFastMatchThread 发生严重错误:\n{err_msg}'))

class AiImageMatchThread(QThread):
    """
    后台线程：调用 AI（远程 API 或 本地引擎），分析一批图片与一批文案的最佳匹配关系。
    """
    progress = pyqtSignal(int)
    log = pyqtSignal(str, str)
    result = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, image_paths, scripts, api_key, api_base, model='gpt-4.1-mini', engine_mode='api', local_engine=None, api_interval=5, max_retries=3, api_keys=None):
        super().__init__()
        self.image_paths = image_paths
        self.scripts = scripts
        self.api_key = api_key
        self.api_base = api_base.rstrip('/') if api_base else ''
        self.model = model
        self.engine_mode = engine_mode
        self.local_engine = local_engine
        self.api_interval = api_interval
        self.max_retries = max_retries
        self._stop = False
        self.api_keys = api_keys or ([api_key] if api_key else [])

    def stop(self):
        self._stop = True

    def _suggest_local_candidate_limit(self):
        limit = 5
        model_name = str(self.model or '').lower()
        try:
            import torch
            if torch.cuda.is_available():
                total_gb = torch.cuda.get_device_properties(torch.cuda.current_device()).total_memory / 1024 ** 3
                if total_gb <= 12.5:
                    limit = 2
                elif total_gb <= 16.5:
                    limit = 3
        except Exception:
            pass
        if 'qwen2.5-vl-3b' in model_name or 'qwen2_5_vl' in model_name:
            limit = min(limit, 2)
        return max(1, int(limit))

    @staticmethod
    def _encode_image(path):
        """将图片压缩为轻量 JPEG data URL，避免一次传入大图造成卡顿和内存飙升。"""
        try:
            from PIL import Image
            with Image.open(path) as img:
                if img.mode in ('RGBA', 'P', 'LA'):
                    img = img.convert('RGB')
                img.thumbnail((384, 384), Image.Resampling.LANCZOS if hasattr(Image, 'Resampling') else Image.ANTIALIAS)
                buf = io.BytesIO()
                img.save(buf, format='JPEG', quality=60, optimize=True)
                data = base64.b64encode(buf.getvalue()).decode('utf-8')
                return f'data:image/jpeg;base64,{data}'
        except Exception:
            ext = os.path.splitext(path)[1].lower()
            mime_map = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp', '.bmp': 'image/bmp', '.gif': 'image/gif'}
            mime = mime_map.get(ext, 'image/jpeg')
            with open(path, 'rb') as f:
                data = base64.b64encode(f.read()).decode('utf-8')
            return f'data:{mime};base64,{data}'

    def run(self):
        try:
            total_scripts = len(self.scripts)
            total_images = len(self.image_paths)
            if total_images == 0:
                self.error.emit('没有可处理的图片池')
                return
            if total_scripts == 0:
                self.error.emit('表格中没有文案内容，请先填写中文或英文文案')
                return
            match_result = {}
            used_images = set()
            self.log.emit(f'🚀 启动智能池化筛选：从 {total_images} 张图片中为 {total_scripts} 条文案挑选最佳匹配', 'blue')
            for idx, script in enumerate(self.scripts):
                if self._stop:
                    self.log.emit('⚠️ 已手动停止', 'orange')
                    break
                row_idx = script['row']
                cn_content = script.get('cn', '').strip()
                en_content = script.get('en', '').strip()
                content = cn_content or en_content
                remark = script.get('remark', '').strip()
                log_msg = f'正在为第 {row_idx + 1} 行挑选图片: {content[:20]}...'
                if remark:
                    log_msg += f' (备注: {remark[:15]})'
                self.log.emit(log_msg, 'blue')
                try:
                    available_images = [p for p in self.image_paths if p not in used_images]
                    if not available_images:
                        self.log.emit(f'⚠️ 图片池已耗尽，第 {row_idx + 1} 行跳过', 'orange')
                        continue
                    if self.engine_mode == 'api':
                        if not self.api_key:
                            self.log.emit('❌ 错误: 未配置 API Key，无法使用远程模式', 'red')
                            break
                        self.log.emit(f'   🌐 正在通过 API 请求视觉模型 ({self.model}) 进行智能匹配...', 'black')
                        candidate_batch = available_images[:5]
                        import json as _json
                        import requests
                        messages = [{'role': 'system', 'content': '你是一个图片筛选专家。请从给出的多张图片中，选出最符合文案描述的一张。'}, {'role': 'user', 'content': [{'type': 'text', 'text': f'文案内容: {content}\n备注要求: {remark}\n\n请从以下候选图片中选出序号（0-4），仅返回序号数字。'}]}]
                        for i, img_p in enumerate(candidate_batch):
                            b64 = self._encode_image(img_p)
                            messages[1]['content'].append({'type': 'text', 'text': f'图片 {i}:'})
                            messages[1]['content'].append({'type': 'image_url', 'image_url': {'url': b64}})
                        headers = {'Authorization': f'Bearer {self.api_key}', 'Content-Type': 'application/json', 'HTTP-Referer': 'https://github.com/manus-ai/ai-assistant-pro', 'X-Title': '任务整理工具'}
                        payload = {'model': self.model, 'messages': messages, 'max_tokens': 10, 'temperature': 0, 'stream': False}
                        is_google = is_google_native_api(self.api_base)
                        if is_google:
                            google_model = pick_google_model(self.model, 'gemini-2.5-flash')
                            google_url = f'{self.api_base}/v1beta/models/{google_model}:generateContent?key={self.api_key}'
                            google_headers = {'Content-Type': 'application/json'}
                            prompt_text = f'System: 你是一个图片筛选专家。请从给出的多张图片中，选出最符合文案描述的一张。\nUser: 文案内容: {content}\n备注要求: {remark}\n\n请从以下候选图片中选出序号（0-4），仅返回序号数字。'
                            parts = [{'text': prompt_text}]
                            for i, img_p in enumerate(candidate_batch):
                                b64_raw = self._encode_image(img_p).split(',')[-1]
                                parts.append({'text': f'图片 {i}:'})
                                parts.append({'inline_data': {'mime_type': 'image/jpeg', 'data': b64_raw}})
                            google_payload = {'contents': [{'parts': parts}], 'generationConfig': {'temperature': 0, 'maxOutputTokens': 10}}
                        res_text = None
                        current_keys = self.api_keys if hasattr(self, 'api_keys') and self.api_keys else [self.api_key]
                        success_flag = False
                        for k_idx, active_key in enumerate(current_keys):
                            if self._stop or success_flag:
                                break
                            if len(current_keys) > 1:
                                self.log.emit(f'   🔑 正在尝试第 {k_idx + 1}/{len(current_keys)} 个 API Key...', 'gray')
                            if is_google:
                                google_url = f'{self.api_base}/v1beta/models/{google_model}:generateContent?key={active_key}'
                            for _attempt in range(self.max_retries):
                                if self._stop:
                                    break
                                try:
                                    wait_for_api_slot(self.api_base, active_key, get_effective_api_interval(self.api_base, {'api_interval': self.api_interval}, self.api_interval), stop_check=lambda: self._stop, log_fn=self.log.emit, prefix='   ⏳ ')
                                    if is_google:
                                        r = requests.post(google_url, json=google_payload, headers=google_headers, timeout=60, verify=HTTP_VERIFY)
                                    else:
                                        headers['Authorization'] = f'Bearer {active_key}'
                                        r = requests.post(f'{self.api_base}/chat/completions', json=payload, headers=headers, timeout=60, verify=HTTP_VERIFY)
                                    if r.status_code in [429, 401, 403]:
                                        err_msg = r.json().get('error', {}).get('message', r.text[:100])
                                        if r.status_code == 429:
                                            cooldown = parse_retry_after_seconds(r, 2 ** _attempt * (20 if is_google else 3))
                                            apply_api_cooldown(self.api_base, active_key, cooldown)
                                            self.log.emit(f'   ⚠️ Key-{k_idx + 1} 频率受限 (429): {extract_api_error_message(r)[:120]}', 'orange')
                                            self.log.emit(f'   ⚠️ Key-{k_idx + 1} 冷却 {cooldown:.0f}s 后重试/切换...', 'orange')
                                        else:
                                            self.log.emit(f'   ❌ Key-{k_idx + 1} 认证失败 (401/403)，准备切换下一个...', 'red')
                                            break
                                        continue
                                    r.raise_for_status()
                                    res_json = r.json()
                                    if is_google:
                                        try:
                                            candidates = res_json.get('candidates', [])
                                            if not candidates:
                                                prompt_feedback = res_json.get('promptFeedback', {})
                                                if prompt_feedback:
                                                    reason = prompt_feedback.get('blockReason', 'Unknown')
                                                    raise RuntimeError(f'Google 安全过滤拦截: {reason}')
                                                raise KeyError('candidates')
                                            content_obj = candidates[0].get('content', {})
                                            parts = content_obj.get('parts', [])
                                            if not parts:
                                                finish_reason = candidates[0].get('finishReason', 'Unknown')
                                                raise RuntimeError(f'Google 未返回内容, 原因: {finish_reason}')
                                            res_text = parts[0].get('text', '').strip()
                                        except (KeyError, IndexError) as parse_err:
                                            self.log.emit(f'   ⚠️ 解析 Google 返回出错: {parse_err}. 原始数据: {str(res_json)[:200]}...', 'gray')
                                            raise parse_err
                                    else:
                                        res_text = res_json['choices'][0]['message']['content'].strip()
                                    success_flag = True
                                    break
                                except Exception as _api_err:
                                    if _attempt < self.max_retries - 1:
                                        self.log.emit(f'   ⚠️ Key-{k_idx + 1} 发生异常，立即重试: {_api_err}', 'orange')
                                        continue
                                    else:
                                        self.log.emit(f'   ⚠️ Key-{k_idx + 1} 发生异常: {_api_err}', 'orange')
                                        break
                            if success_flag:
                                break
                        if not res_text:
                            raise RuntimeError(f'所有 {len(current_keys)} 个 API Key 均尝试失败，请检查配置。')
                        import re as _re_match
                        _m = _re_match.search('(\\d)', res_text)
                        best_batch_idx = int(_m.group(1)) if _m and int(_m.group(1)) < len(candidate_batch) else 0
                        selected_img_path = candidate_batch[best_batch_idx]
                        final_score = 95.0
                        reason = f'API({self.model}) 视觉识别匹配'
                        match_result[selected_img_path] = {'row': row_idx, 'score': final_score, 'reason': reason, 'cn': cn_content, 'en': en_content}
                        used_images.add(selected_img_path)
                        self.log.emit(f'✅ 匹配成功: 第 {row_idx + 1} 行 -> {os.path.basename(selected_img_path)} (得分: {final_score})', 'green')
                        self.progress.emit(int((idx + 1) / total_scripts * 100))
                        continue
                    elif self.engine_mode == 'local':
                        if not self.local_engine:
                            self.error.emit('本地模型未加载，无法执行图文匹配')
                            return
                        if not getattr(self.local_engine, 'supports_vision', False):
                            self.error.emit('当前本地模型是纯文字模型，不支持图文匹配。请切换到视觉模型，或改用远程 API / CLIP 极速模式。')
                            return
                        self.log.emit(f'   🖼️ 正在通过本地视觉模型 ({self.model}) 进行智能匹配...', 'black')
                        candidate_limit = self._suggest_local_candidate_limit()
                        candidate_batch = available_images[:candidate_limit]
                        self.log.emit(f'   🧠 本地显存保护已启用：本轮候选图 {len(candidate_batch)} 张，低显存推理模式 ON', 'gray')
                        choice_prompt = f'文案内容: {content}\n备注要求: {remark}\n\n请从这 {len(candidate_batch)} 张候选图片中选出最符合文案的一张。只返回一个序号数字（从 0 到 {len(candidate_batch) - 1}），不要输出解释。'
                        res_text = self.local_engine.chat(history=[{'role': 'user', 'content': choice_prompt}], system_prompt='你是一个图片筛选专家。请从给出的多张图片中，选出最符合文案描述的一张。', image_paths=candidate_batch, max_new_tokens=8, do_sample=False, temperature=0.0, prefer_low_memory=True, cleanup_cache=True)
                        import re as _re_match
                        _m = _re_match.search('(\\d+)', str(res_text or ''))
                        best_batch_idx = int(_m.group(1)) if _m and int(_m.group(1)) < len(candidate_batch) else 0
                        selected_img_path = candidate_batch[best_batch_idx]
                        final_score = 95.0
                        reason = f'本地视觉模型({self.model}) 图文匹配'
                        match_result[selected_img_path] = {'row': row_idx, 'score': final_score, 'reason': reason, 'cn': cn_content, 'en': en_content}
                        used_images.add(selected_img_path)
                        self.log.emit(f'✅ 匹配成功: 第 {row_idx + 1} 行 -> {os.path.basename(selected_img_path)} (得分: {final_score})', 'green')
                        self.progress.emit(int((idx + 1) / total_scripts * 100))
                        continue
                    else:
                        clip_model = ClipFastMatchThread._load_clip_model('OFA-Sys/chinese-clip-vit-large-patch14', True, lambda m, c='black': None)
                    sad_words = ['悲伤', '难过', '忧郁', '痛苦', '伤心', '哭泣', '哀悼', '失落', '沮丧', 'sad', 'unhappy', 'crying', 'sorrow']
                    happy_words = ['开心', '快乐', '兴奋', '喜悦', '高兴', '微笑', '大笑', 'happy', 'joy', 'excited', 'smile', 'laugh']
                    sad_scenes = ['灾难', '事故', '去世', '葬礼', '离别', '分手', '失败', '破产', '生病', '孤独', '寒冷', '废墟', '灾民', '乞讨']
                    happy_scenes = ['祝福', '婚礼', '庆典', '成功', '奖杯', '团聚', '过年', '生日', '礼物', '聚会', '阳光', '花朵', '旅游', '中奖']
                    sentiment_prompt = ''
                    lower_text = (content + ' ' + remark).lower()
                    if any((k in lower_text for k in sad_words)) or any((k in lower_text for k in sad_scenes)):
                        sentiment_prompt = '，表情悲伤，忧郁，哭泣，深沉，sad expression, sorrowful face, depressed atmosphere'
                    elif any((k in lower_text for k in happy_words)) or any((k in lower_text for k in happy_scenes)):
                        sentiment_prompt = '，表情开心，快乐，大笑，阳光，happy expression, smiling face, joyful atmosphere'
                    enhanced_content = content + sentiment_prompt
                    text_feat = clip_model.encode([enhanced_content], convert_to_numpy=True)[0]
                    if remark:
                        remark_feat = clip_model.encode([remark + sentiment_prompt], convert_to_numpy=True)[0]
                        text_feat = text_feat * 0.8 + remark_feat * 0.2
                    img_feats = []
                    valid_paths = []
                    for p in available_images:
                        if p in ClipFastMatchThread._img_feature_cache:
                            img_feats.append(ClipFastMatchThread._img_feature_cache[p])
                            valid_paths.append(p)
                    missing_paths = [p for p in available_images if p not in ClipFastMatchThread._img_feature_cache]
                    if missing_paths:
                        self.log.emit(f'   ⏳ 正在提取 {len(missing_paths)} 张新图片的特征...', 'black')
                        from PIL import Image as _PILImage
                        for p in missing_paths:
                            try:
                                img = _PILImage.open(p).convert('RGB')
                                img.thumbnail((336, 336))
                                feat = clip_model.encode([img], convert_to_numpy=True)[0]
                                ClipFastMatchThread._img_feature_cache[p] = feat
                                img_feats.append(feat)
                                valid_paths.append(p)
                            except:
                                continue
                    if not img_feats:
                        self.log.emit(f'❌ 第 {row_idx + 1} 行：无法获取图片特征', 'red')
                        continue
                    import numpy as np
                    img_matrix = np.array(img_feats)
                    img_matrix = img_matrix / (np.linalg.norm(img_matrix, axis=1, keepdims=True) + 1e-08)
                    text_feat = text_feat / (np.linalg.norm(text_feat) + 1e-08)
                    sims = img_matrix @ text_feat
                    path_bonus, hit_count = ClipFastMatchThread._build_path_priority_bonus(remark, valid_paths)
                    if hit_count > 0:
                        self.log.emit(f'   📁 第 {row_idx + 1} 行备注命中 {hit_count} 张路径/文件夹，优先从这些图片中选择', 'gray')
                        sims = sims + path_bonus
                    best_idx = np.argmax(sims)
                    best_sim = sims[best_idx]
                    selected_img_path = valid_paths[best_idx]
                    final_score = round(float(best_sim) * 100, 1)
                    match_result[selected_img_path] = {'row': row_idx, 'score': final_score, 'reason': f"CLIP全局最优(相似度:{best_sim:.3f}{(' / 备注路径优先' if hit_count > 0 and path_bonus[best_idx] > 0 else '')})", 'cn': cn_content, 'en': en_content}
                    used_images.add(selected_img_path)
                    self.log.emit(f'✅ 匹配成功: 第 {row_idx + 1} 行 -> {os.path.basename(selected_img_path)} (得分: {final_score})', 'green')
                except Exception as e:
                    self.log.emit(f'❌ 挑选出错 (第 {row_idx + 1} 行): {str(e)}', 'red')
                self.progress.emit(int((idx + 1) / total_scripts * 100))
            self.result.emit(match_result)
        except Exception as e:
            err_msg = traceback.format_exc()
            self.error.emit(f'AI 匹配线程异常: {e}\n{err_msg}')
            QTimer.singleShot(0, lambda: QMessageBox.critical(None, '后台线程崩溃', f'AiImageMatchThread 发生严重错误:\n{err_msg}'))

class ProjectAutoMatchThread(QThread):
    """
    专门为流水线设计的线程类：封装了图片扫描、引擎加载、AI匹配的全流程。
    """
    progress = pyqtSignal(int)
    log = pyqtSignal(str, str)
    result = pyqtSignal(str, dict)
    error = pyqtSignal(str, str)
    # 不覆盖 QThread.finished。覆盖 Qt 原生生命周期信号会导致某些机器上
    # finished 回调、线程清理与下一轮匹配的时序不稳定。
    task_finished = pyqtSignal()

    def __init__(self, name, src_dir, scripts, api_key, api_base, model, engine_mode='api', local_engine=None, max_scan=300, batch_size=5, local_model_path=None, mmproj_path=None, clip_model_name=None, clip_use_gpu=True, api_interval=5, max_retries=3, api_keys=None, ai_config=None, excluded_image_paths=None):
        super().__init__()
        self.project_name = name
        self.src_dir = src_dir
        self.scripts = scripts
        self.api_key = api_key
        self.api_base = api_base
        self.model = model
        self.engine_mode = engine_mode
        self.local_engine = local_engine
        self.max_scan = max_scan
        self.batch_size = batch_size
        self.local_model_path = local_model_path
        self.mmproj_path = mmproj_path
        self.clip_model_name = clip_model_name
        self.clip_use_gpu = clip_use_gpu
        self.api_interval = api_interval
        self.max_retries = max_retries
        self.api_keys = api_keys or ([api_key] if api_key else [])
        self.ai_config = ai_config or {}
        self.excluded_image_paths = {os.path.normcase(os.path.abspath(str(path))) for path in (excluded_image_paths or []) if str(path).strip() and not str(path).strip().lower().startswith('file://')}
        self.available_image_count = 0
        self._stop = False
        self.sub_thread = None

    def stop(self):
        self._stop = True
        if self.sub_thread:
            self.sub_thread.stop()

    def run(self):
        try:
            if self._stop:
                return
            self.log.emit(f'📂 正在扫描目录: {self.src_dir}', 'black')
            valid_exts = ('.jpg', '.jpeg', '.jfif', '.png', '.webp', '.bmp', '.gif', '.tif', '.tiff')
            image_paths = []
            for root, dirs, files in os.walk(self.src_dir):
                dirs.sort(key=str.casefold);files.sort(key=str.casefold)
                if self._stop:
                    self.log.emit('⏹️ 已停止目录扫描', 'orange')
                    return
                for f in files:
                    if self._stop:
                        self.log.emit('⏹️ 已停止目录扫描', 'orange')
                        return
                    if f.lower().endswith(valid_exts):
                        candidate_path=os.path.join(root, f)
                        if os.path.normcase(os.path.abspath(candidate_path)) not in self.excluded_image_paths:image_paths.append(candidate_path)
                    if len(image_paths) >= self.max_scan:
                        break
                if len(image_paths) >= self.max_scan:
                    break
            if not image_paths:
                self.error.emit(self.project_name, '目录下未找到可用于 AI 匹配的图片（已有图片路径会被保留并从候选池排除）')
                return
            self.available_image_count = len(image_paths)
            excluded_count=len(self.excluded_image_paths)
            self.log.emit(f'✅ 扫描完成，共找到 {len(image_paths)} 张可匹配图片' + (f'（已排除 {excluded_count} 张已有路径图片）' if excluded_count else ''), 'green')
            if self._stop:
                return
            if self.engine_mode == 'clip':
                self.sub_thread = ClipFastMatchThread(image_paths, self.scripts, clip_model_name=self.clip_model_name or 'OFA-Sys/chinese-clip-vit-large-patch14', use_gpu=self.clip_use_gpu)
            else:
                self.sub_thread = AiImageMatchThread(image_paths, self.scripts, self.api_key, self.api_base, model=self.model, engine_mode=self.engine_mode, local_engine=self.local_engine, api_interval=getattr(self, 'api_interval', 5), max_retries=getattr(self, 'max_retries', 3), api_keys=getattr(self, 'api_keys', [self.api_key]))
            self.sub_thread.progress.connect(self.progress.emit)
            self.sub_thread.log.connect(self.log.emit)
            loop = QEventLoop()
            self.sub_thread.finished.connect(loop.quit)
            match_res = None
            err_msg = None

            def on_res(res):
                nonlocal match_res
                match_res = res

            def on_err(err):
                nonlocal err_msg
                err_msg = err
            self.sub_thread.result.connect(on_res)
            self.sub_thread.error.connect(on_err)
            self.sub_thread.start()
            loop.exec()
            if self._stop:
                self.log.emit('⏹️ 已停止 AI 匹配任务', 'orange')
                return
            if err_msg:
                self.error.emit(self.project_name, err_msg)
            elif match_res:
                self.result.emit(self.project_name, match_res)
            else:
                self.error.emit(self.project_name, '匹配任务未返回任何结果')
        except Exception as e:
            err_msg = traceback.format_exc()
            self.error.emit(self.project_name, f'流水线执行异常: {e}\n{err_msg}')
            QTimer.singleShot(0, lambda: QMessageBox.critical(None, '后台线程崩溃', f'ProjectAutoMatchThread 发生严重错误:\n{err_msg}'))
        finally:
            self.task_finished.emit()

class ExpandedCellEditorDialog(QDialog):
    """所有 MaterialSpreadsheet 共用的多行单元格编辑器。"""
    def __init__(self, owner, title, value="", parent=None):
        super().__init__(parent or owner);self.setWindowTitle(title);self.setModal(True);self.setProperty("theme_dialog","true");self.setMinimumSize(640,440);self.resize(900,620)
        layout=QVBoxLayout(self);layout.setContentsMargins(22,18,22,18)
        hint=QLabel("可完整查看与编辑多行内容；Ctrl+Enter 保存，Esc 取消。");hint.setWordWrap(True);layout.addWidget(hint)
        self.editor=QTextEdit();self.editor.setAcceptRichText(False);self.editor.setPlainText(str(value or ""));layout.addWidget(self.editor,1)
        buttons=QHBoxLayout();buttons.addStretch();cancel=QPushButton("取消");save=QPushButton("保存单元格");cancel.clicked.connect(self.reject);save.clicked.connect(self.accept);buttons.addWidget(cancel);buttons.addWidget(save);layout.addLayout(buttons);QTimer.singleShot(0,self.editor.setFocus)
    def text_value(self):return self.editor.toPlainText()


class MaterialSpreadsheet(ExcelTable):
    """Qt 素材页的薄宿主：交互、填充、公式和剪贴板逻辑均来自原 ExcelTable。"""
    changed=Signal()
    EXTERNAL_SPREADSHEET_SUFFIXES=frozenset({'.xlsx','.csv','.tsv'})
    def __init__(self, rows=40, columns=6, parent=None):
        super().__init__(rows, columns, parent)
        self.setObjectName("materialSpreadsheet");self.setShowGrid(True);self.setGridStyle(Qt.PenStyle.SolidLine);self.external_file_drop_callback=None
        self.minimum_row_count=max(0,int(rows));self._smart_fill_enabled_columns=set(range(columns));self._undo_stack=[];self._redo_stack=[];self._history_blocked=False;self._last_snapshot=self._snapshot();self.itemChanged.connect(self._on_item_changed);self._apply_default_column_headers()

    def _external_spreadsheet_from_drop(self,event):
        """仅查看表格页设置回调；其它素材表保留自己的拖放语义。"""
        callback=getattr(self,'external_file_drop_callback',None)
        if not callable(callback) or not event.mimeData().hasUrls():return '',None
        for url in event.mimeData().urls():
            path=url.toLocalFile()
            if path and os.path.isfile(path) and os.path.splitext(path)[1].casefold() in self.EXTERNAL_SPREADSHEET_SUFFIXES:
                return path,callback
        return '',None

    def dragEnterEvent(self,event):
        path,_callback=self._external_spreadsheet_from_drop(event)
        if path:event.acceptProposedAction();return
        super().dragEnterEvent(event)

    def dragMoveEvent(self,event):
        path,_callback=self._external_spreadsheet_from_drop(event)
        if path:event.acceptProposedAction();return
        super().dragMoveEvent(event)

    def dropEvent(self,event):
        path,callback=self._external_spreadsheet_from_drop(event)
        if path:
            # 资源管理器拖入 XLSX/CSV/TSV 在“查看表格”中应等同点击“打开表格文件”，
            # 不能被通用单元格拖放当作一段文件路径写入单元格。
            callback(path);event.acceptProposedAction();return
        super().dropEvent(event)

    def viewportEvent(self,event):
        # QTableWidget 的文件拖放在部分 Windows/Qt 组合会先投递给 viewport，
        # 不一定经过表格自身的 dropEvent。两层都处理，保证拖到任意单元格都能打开。
        try:
            event_type=event.type()
            if event_type in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop):
                path,callback=self._external_spreadsheet_from_drop(event)
                if path:
                    if event_type == QEvent.Type.Drop:callback(path)
                    event.acceptProposedAction()
                    return True
        except Exception:
            pass
        return super().viewportEvent(event)
    @staticmethod
    def _column_letter(column):
        value=max(0,int(column))+1;result=""
        while value:value,remainder=divmod(value-1,26);result=chr(65+remainder)+result
        return result
    def _apply_default_column_headers(self):
        for column in range(self.columnCount()):
            item=self.horizontalHeaderItem(column)
            if item is None or not str(item.text() or "").strip():self.setHorizontalHeaderItem(column,QTableWidgetItem(self._column_letter(column)))
    def setColumnCount(self,columns):
        super().setColumnCount(columns)
        if hasattr(self,"_undo_stack"):self._apply_default_column_headers()
    def _snapshot(self):return [[self.item(row,column).text() if self.item(row,column) else "" for column in range(self.columnCount())] for row in range(self.rowCount())]
    def reset_history(self):self._undo_stack.clear();self._redo_stack.clear();self._last_snapshot=self._snapshot()
    def _on_item_changed(self,item=None,*_):
        # 记住用户输入的公式本体；显示区随后由 recalculate_all 写入计算结果。
        if item is not None and not self._history_blocked:
            raw=str(item.text() or '')
            if raw.startswith('='):
                item.setData(_UserRole + 11, raw)
            elif item.data(_UserRole + 11) and raw != str(item.data(_UserRole + 10) or ''):
                item.setData(_UserRole + 11, None)
        current=self._snapshot()
        if not self._history_blocked and current!=self._last_snapshot:
            self._undo_stack.append(self._last_snapshot)
            if len(self._undo_stack)>100:self._undo_stack.pop(0)
            self._redo_stack.clear()
        if not self._history_blocked:
            self.recalculate_all()
        # 公式重算会在信号屏蔽期间改写显示值，必须以重算后的画面作为下一次撤销基线。
        self._last_snapshot=self._snapshot()
        self.changed.emit()

    def _commit_bulk_history(self,before):
        """粘贴、删除与拖拽填充均在屏蔽 itemChanged 时调用，仍应成为一个可撤销动作。"""
        current=self._snapshot()
        if before is not None and before!=current:
            self._undo_stack.append(before)
            if len(self._undo_stack)>100:self._undo_stack.pop(0)
            self._redo_stack.clear()
        self._last_snapshot=current
        self.changed.emit()

    def recalculate_all(self):
        """启用核心模块已有的安全公式引擎，支持 A1 引用及 SUM/AVG/MAX/MIN。"""
        formulas=[]
        for row in range(self.rowCount()):
            for column in range(self.columnCount()):
                item=self.item(row,column)
                formula=item.data(_UserRole+11) if item else None
                if isinstance(formula,str) and formula.startswith('='):
                    formulas.append((item,formula))
        if not formulas:
            return
        self._history_blocked=True;self.blockSignals(True)
        try:
            # 两轮可覆盖常见的同向链式公式，复杂循环会安全显示 #ERR。
            for _ in range(2):
                for item,formula in formulas:
                    result=FormulaEngine.evaluate(formula,self)
                    item.setData(_UserRole+10,result)
                    item.setText(str(result))
        finally:
            self.blockSignals(False);self._history_blocked=False
    def _restore_snapshot(self,snapshot):
        self._history_blocked=True;self.blockSignals(True)
        try:
            self.setRowCount(max(self.minimum_row_count,len(snapshot)))
            for row in range(self.rowCount()):
                values=snapshot[row] if row<len(snapshot) else []
                for column in range(self.columnCount()):self.setItem(row,column,QTableWidgetItem(values[column] if column<len(values) else ""))
        finally:self.blockSignals(False);self._history_blocked=False
        self._last_snapshot=self._snapshot();self.changed.emit()
    def trigger_main_save(self): self.changed.emit()
    def _can_open_expanded_cell_editor(self):
        try:
            row,column=self.currentRow(),self.currentColumn()
            if row<0 or column<0 or self.cellWidget(row,column) is not None:return False
            item=self.item(row,column)
            return item is None or bool(item.flags() & Qt.ItemFlag.ItemIsEditable)
        except Exception:return False
    def open_expanded_cell_editor(self):
        """F2/右键统一进入长内容编辑，表格仍保持紧凑浏览行高。"""
        if not self._can_open_expanded_cell_editor():return False
        row,column=self.currentRow(),self.currentColumn();item=self.item(row,column)
        if item is None:item=QTableWidgetItem("");self.setItem(row,column,item)
        formula=item.data(_UserRole+11);value=formula if isinstance(formula,str) and formula.startswith("=") else item.text()
        header=self.horizontalHeaderItem(column);name=header.text() if header is not None else f"第 {column+1} 列"
        dialog=ExpandedCellEditorDialog(self.window(),f"编辑单元格｜第 {row+1} 行 · {name}",value,self)
        if dialog.exec()!=QDialog.Accepted:return False
        before=self._snapshot();new_value=dialog.text_value();self._history_blocked=True;self.blockSignals(True)
        try:item.setText(new_value);item.setData(_UserRole+11,new_value if new_value.startswith("=") else None)
        finally:self.blockSignals(False);self._history_blocked=False
        self.recalculate_all();self._commit_bulk_history(before);self.trigger_main_save();return True
    def clear_sheet(self, minimum_rows=40):
        before=self._snapshot()
        self.blockSignals(True)
        try:
            self.setRowCount(max(1, minimum_rows))
            for row in range(self.rowCount()):
                for column in range(self.columnCount()): self.setItem(row, column, QTableWidgetItem(""))
        finally: self.blockSignals(False)
        self._undo_stack.append(before);self._redo_stack.clear();self._last_snapshot=self._snapshot();self.changed.emit()
    def add_rows(self, count=1):
        before=self._snapshot();self.setRowCount(self.rowCount()+max(1,int(count)));self._undo_stack.append(before);self._redo_stack.clear();self._last_snapshot=self._snapshot();self.changed.emit()
    def delete_selected_rows(self):
        before=self._snapshot()
        for row in sorted({item.row() for item in self.selectedItems()}, reverse=True): self.removeRow(row)
        if self.rowCount()<self.minimum_row_count: self.setRowCount(self.minimum_row_count)
        self._undo_stack.append(before);self._redo_stack.clear();self._last_snapshot=self._snapshot();self.changed.emit()
    def undo_sheet(self):
        if not self._undo_stack:return
        current=self._snapshot();self._redo_stack.append(current);self._restore_snapshot(self._undo_stack.pop())
    def redo_sheet(self):
        if not self._redo_stack:return
        current=self._snapshot();self._undo_stack.append(current);self._restore_snapshot(self._redo_stack.pop())
    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_F2 and self.open_expanded_cell_editor():event.accept();return
        super().keyPressEvent(event)
