#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
编辑辅助 - 单行编辑/双击编辑/选中编辑入口
"""

import copy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFormLayout, QHBoxLayout, QInputDialog,
                             QLabel, QLineEdit, QMessageBox, QPushButton,
                             QTextEdit, QVBoxLayout, QWidget)

from .edit_dialog import EditDialog
from .title_edit_dialog import TitleEditDialog
from .utils import _trim_compare_dicts


def edit_row(mw, row: int):
    """编辑指定行（系列级编辑）—— 确认且有实际改动后立即落盘（save_single_result）"""
    results = getattr(mw, "scan_results", None)
    if not results or row < 0 or row >= len(results):
        return
    result = mw.scan_results[row]
    original_data = copy.deepcopy(result)
    dialog = EditDialog(result, mw)

    if dialog.exec() == QDialog.DialogCode.Accepted:
        updated_data = dialog.get_data()
        locked_files = updated_data.get("locked_files", set())

        has_changes = False
        for key, new_value in updated_data.items():
            old_value = original_data.get(key, "")
            if isinstance(old_value, dict) and isinstance(new_value, dict):
                if _trim_compare_dicts(old_value, new_value):
                    has_changes = True
                    break
            elif isinstance(old_value, set) or isinstance(new_value, set):
                old_set = old_value if isinstance(old_value, set) else set()
                new_set = new_value if isinstance(new_value, set) else set()
                if old_set != new_set:
                    has_changes = True
                    break
            else:
                if str(old_value).strip() != str(new_value).strip():
                    has_changes = True
                    break

        if has_changes:
            mw.scan_results[row].update(updated_data)
            mw.scan_results[row]["process_status"] = "已修改"
            mw.update_results_table()
            # 结果页编辑即时落盘：只写当前这一个 result。save_single_result 自带
            # FIFO 等待队列（任意时刻保存线程 ≤1），不能用 save_changes（它会收集
            # scan_results 里所有「已修改」结果重复写盘，且可能与扫描线程并发）
            from .save_handler import save_single_result
            save_single_result(mw, mw.scan_results[row])
        else:
            print(f"ℹ️  无实际修改，跳过: {result.get('series', '')}")



def on_results_double_clicked(mw, row: int, column: int):
    """双击结果表格行 - 弹出各卷信息编辑对话框（确认且有改动后立即落盘）"""
    results = getattr(mw, "scan_results", None)
    if not results or row < 0 or row >= len(results):
        return
    result = mw.scan_results[row]
    original_titles = copy.deepcopy(result.get("file_titles", {}))
    original_details = copy.deepcopy(result.get("file_details", {}))
    original_locked = copy.deepcopy(result.get("locked_files", set()))
    dialog = TitleEditDialog(result, mw)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        title_data = dialog.get_data()
        new_titles = title_data["file_titles"]
        new_details = title_data["file_details"]
        locked_files = title_data["locked_files"]

        trimmed_old_titles = {k: v.strip() for k, v in original_titles.items()}
        trimmed_new_titles = {k: v.strip() for k, v in new_titles.items()}
        if _trim_compare_dicts(original_details, new_details) or trimmed_old_titles != trimmed_new_titles or original_locked != locked_files:
            mw.scan_results[row]["file_titles"] = new_titles
            mw.scan_results[row]["file_details"] = new_details
            mw.scan_results[row]["locked_files"] = locked_files
            mw.scan_results[row]["process_status"] = "已修改"
            mw.update_results_table()
            # 逐卷编辑同样即时落盘：只写当前这一个 result（save_single_result 自带
            # FIFO 等待队列，任意时刻保存线程 ≤1；不用 save_changes，避免重复写盘）
            from .save_handler import save_single_result
            save_single_result(mw, mw.scan_results[row])
        else:
            print(f"ℹ️  各卷信息无实际修改，跳过: {result.get('series', '')}")



def edit_selected(mw):
    """编辑选中行 - 弹出对话框让用户选择要编辑的条目"""
    if not mw.scan_results:
        QMessageBox.warning(mw, "警告", "没有可编辑的结果")
        return

    items = [f"{i+1}. {r['series']} - {r.get('folder_name', '')}" for i, r in enumerate(mw.scan_results)]
    item, ok = QInputDialog.getItem(mw, "选择条目", "请选择要编辑的条目:", items, 0, False)
    if ok and item:
        row = items.index(item)
        mw.edit_row(row)


