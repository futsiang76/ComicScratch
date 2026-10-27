#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Title编辑对话框 - 编辑系列中各本书的Title和详细信息
"""

from typing import Dict, Union

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QHeaderView,
                             QLabel, QLineEdit, QPushButton, QTableWidget,
                             QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from gui.crop_queue import _open_single_crop_flow
from gui.results_table import THUMB_HEIGHT, _cover_with_badge
from models.edit_state import EditState


class TitleEditDialog(QDialog):
    """Title编辑对话框 - 编辑系列中各本书的Title（含封面缩略图列 + 裁剪入口）"""

    def __init__(self, data: Union[Dict, EditState], parent=None, selected_filename: str = None):
        super().__init__(parent)
        if isinstance(data, EditState):
            self.state = data
        else:
            self.state = EditState(data)
        self._selected_filename = selected_filename
        self._initial_locked_files = set(self.state.locked_files)
        self.crop_running = False  # 封面裁剪后台任务标志（供 crop_queue 复用）
        self.init_ui()

    def init_ui(self):
        """初始化UI"""
        series_name = self.state.series or "未知系列"
        if self._selected_filename:
            self.setWindowTitle(f"编辑卷信息 - {series_name} - {self._selected_filename}")
        else:
            self.setWindowTitle(f"编辑各卷信息 - {series_name}")
        self.setMinimumSize(1100, 600)

        layout = QVBoxLayout()

        # 系列信息标题
        info_label = QLabel(f"系列: {series_name}")
        info_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #333; padding: 5px;")
        layout.addWidget(info_label)

        # 锁定说明
        lock_help_label = QLabel("🔒 锁定单卷信息后，该卷的发行时间和简介将独立于系列设置，不会被系列级修改覆盖")
        lock_help_label.setStyleSheet("color: #666; font-style: italic; padding: 5px; background-color: #fff3cd; border-radius: 3px;")
        lock_help_label.setWordWrap(True)
        layout.addWidget(lock_help_label)

        # 表格
        self.title_table = QTableWidget()
        self.title_table.setColumnCount(8)
        self.title_table.setHorizontalHeaderLabels(["文件名", "Title", "Volume", "发行时间", "Summary", "标签", "🔒 锁定", "封面"])
        header = self.title_table.horizontalHeader()
        if header:
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
            header.setStyleSheet("""
                QHeaderView::section {
                    background-color: #4CAF50;
                    color: white;
                    padding: 5px;
                    border: 1px solid #ddd;
                    font-weight: bold;
                }
            """)

        # 表格样式
        self.title_table.setStyleSheet("""
            QTableWidget {
                gridline-color: #ddd;
                border: 1px solid #ddd;
                border-radius: 5px;
                background-color: white;
            }
            QTableWidget::item {
                padding: 5px;
            }
            QTableWidget::item:selected {
                background-color: #e3f2fd;
                color: black;
            }
        """)

        sorted_items = self.state.get_volumes_sorted()
        if self._selected_filename:
            sorted_items = [(f, t) for f, t in sorted_items if f == self._selected_filename]

        self.title_table.setRowCount(len(sorted_items))
        for row, (filename, title) in enumerate(sorted_items):
            detail = self.state.file_details.get(filename, {})
            is_locked = self.state.is_locked(filename)

            # 文件名列 - 不可编辑
            filename_item = QTableWidgetItem(filename)
            filename_item.setFlags(filename_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            filename_item.setBackground(Qt.GlobalColor.lightGray)
            self.title_table.setItem(row, 0, filename_item)

            # Title列
            title_item = QTableWidgetItem(title)
            self.title_table.setItem(row, 1, title_item)

            # Volume列
            volume_item = QTableWidgetItem(detail.get("volume", ""))
            self.title_table.setItem(row, 2, volume_item)

            # 发行时间列（有日显示 YYYY-MM-DD，无日保持 YYYY-MM）
            year = detail.get("year", "")
            month = detail.get("month", "")
            day = detail.get("day", "")
            if year and month and day:
                date_str = f"{year}-{month}-{day}"
            elif year and month:
                date_str = f"{year}-{month}"
            else:
                date_str = year
            date_item = QTableWidgetItem(date_str)
            # 如果锁定，用不同背景色
            if is_locked:
                date_item.setBackground(Qt.GlobalColor.yellow)
            self.title_table.setItem(row, 3, date_item)

            # Summary列
            summary_item = QTableWidgetItem(detail.get("summary", ""))
            # 如果锁定，用不同背景色
            if is_locked:
                summary_item.setBackground(Qt.GlobalColor.yellow)
            self.title_table.setItem(row, 4, summary_item)

            # 标签列
            tags_item = QTableWidgetItem(detail.get("tags", ""))
            self.title_table.setItem(row, 5, tags_item)

            # 锁定列 - 使用自定义控件
            lock_widget = QWidget()
            lock_layout = QHBoxLayout(lock_widget)
            lock_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
            lock_checkbox = QCheckBox()
            lock_checkbox.setChecked(is_locked)
            lock_checkbox.setStyleSheet("""
                QCheckBox {
                    spacing: 5px;
                }
                QCheckBox::indicator {
                    width: 20px;
                    height: 20px;
                    border-radius: 3px;
                    border: 2px solid #888;
                }
                QCheckBox::indicator:checked {
                    background-color: #4CAF50;
                    border-color: #4CAF50;
                    image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0id2hpdGUiPjxwYXRoIGQ9Ik05IDE2LjE3TDQuODMgMTJsLTEuNDIgMS40MUw5IDE5IDIxIDdsMS40MS0xLjQxeiIvPjwvc3ZnPg==);
                }
                QCheckBox::indicator:hover {
                    border-color: #4CAF50;
                }
            """)
            # 连接锁定状态变化信号，更新背景色
            lock_checkbox.stateChanged.connect(lambda state, r=row: self.on_lock_changed(r, state))
            
            lock_layout.addWidget(lock_checkbox)
            lock_layout.setContentsMargins(0, 0, 0, 0)
            self.title_table.setCellWidget(row, 6, lock_widget)

            # 封面列 - 缩略图 + 异常角标，点击弹裁剪界面
            cover_info = self.state.covers.get(filename) if self.state.covers else None
            self.title_table.setCellWidget(row, 7, self._make_cover_cell(filename, cover_info))
            self.title_table.setRowHeight(row, THUMB_HEIGHT + 8)

        layout.addWidget(self.title_table)

        # 按钮区域 - 使用更突出的样式
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        # 全选锁定按钮
        select_all_locks_btn = QPushButton("🔒 全选锁定")
        select_all_locks_btn.setMinimumHeight(35)
        select_all_locks_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                font-size: 13px;
                font-weight: bold;
                border-radius: 5px;
                padding: 8px;
            }
            QPushButton:hover {
                background-color: #e68900;
            }
        """)
        select_all_locks_btn.clicked.connect(self.select_all_locks)
        button_layout.addWidget(select_all_locks_btn)

        # 清除所有锁定按钮
        clear_all_locks_btn = QPushButton("🔓 清除锁定")
        clear_all_locks_btn.setMinimumHeight(35)
        clear_all_locks_btn.setStyleSheet("""
            QPushButton {
                background-color: #9E9E9E;
                color: white;
                font-size: 13px;
                font-weight: bold;
                border-radius: 5px;
                padding: 8px;
            }
            QPushButton:hover {
                background-color: #757575;
            }
        """)
        clear_all_locks_btn.clicked.connect(self.clear_all_locks)
        button_layout.addWidget(clear_all_locks_btn)

        # 确定按钮
        ok_btn = QPushButton("✅ 确定")
        ok_btn.setMinimumHeight(35)
        ok_btn.setMinimumWidth(100)
        ok_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-size: 14px;
                font-weight: bold;
                border-radius: 5px;
                padding: 8px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        ok_btn.clicked.connect(self.accept)
        button_layout.addWidget(ok_btn)

        # 取消按钮
        cancel_btn = QPushButton("❌ 取消")
        cancel_btn.setMinimumHeight(35)
        cancel_btn.setMinimumWidth(100)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                font-size: 14px;
                font-weight: bold;
                border-radius: 5px;
                padding: 8px;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        button_layout.addStretch()
        layout.addLayout(button_layout)

        self.setLayout(layout)

    def on_lock_changed(self, row: int, state: int):
        """锁定状态变化时的处理"""
        is_locked = (state == 2)  # 2 = checked
        # 更新发行时间和Summary列的背景色
        date_item = self.title_table.item(row, 3)
        summary_item = self.title_table.item(row, 4)
        
        if date_item:
            if is_locked:
                date_item.setBackground(Qt.GlobalColor.yellow)
            else:
                date_item.setBackground(Qt.GlobalColor.white)
        
        if summary_item:
            if is_locked:
                summary_item.setBackground(Qt.GlobalColor.yellow)
            else:
                summary_item.setBackground(Qt.GlobalColor.white)

    def select_all_locks(self):
        """全选所有锁定"""
        for row in range(self.title_table.rowCount()):
            lock_widget = self.title_table.cellWidget(row, 6)
            if lock_widget:
                checkbox = lock_widget.findChild(QCheckBox)
                if checkbox:
                    checkbox.setChecked(True)

    def clear_all_locks(self):
        """清除所有锁定"""
        for row in range(self.title_table.rowCount()):
            lock_widget = self.title_table.cellWidget(row, 6)
            if lock_widget:
                checkbox = lock_widget.findChild(QCheckBox)
                if checkbox:
                    checkbox.setChecked(False)

    def _get_cell_text(self, row: int, col: int) -> str:
        """获取单元格文本，优先从正在编辑的控件中读取"""
        editor = self.title_table.cellWidget(row, col)
        if editor:
            if isinstance(editor, QLineEdit):
                return editor.text()
            if isinstance(editor, QTextEdit):
                return editor.toPlainText()
        item = self.title_table.item(row, col)
        return item.text() if item else ""

    def _make_cover_cell(self, filename: str, info) -> QWidget:
        """封面缩略图单元格：缩略图 + 异常角标，点击弹裁剪界面"""
        return _cover_with_badge(
            info,
            bool(info) and info.get("ratio_ok") is False,
            lambda: self._open_crop_for(filename),
        )

    def _open_crop_for(self, filename: str):
        """点击封面缩略图 → 打开裁剪对话框；完成后刷新该卷缩略图"""
        if not self.state.covers or filename not in self.state.covers:
            return
        _open_single_crop_flow(
            self, self.state.covers, filename,
            on_done=lambda: self._refresh_cover_cell(filename),
        )

    def _refresh_cover_cell(self, filename: str):
        """裁剪完成后重渲染该卷封面单元格（缩略图/角标更新）"""
        for row in range(self.title_table.rowCount()):
            item = self.title_table.item(row, 0)
            if item and item.text() == filename:
                info = self.state.covers.get(filename) if self.state.covers else None
                self.title_table.setCellWidget(row, 7, self._make_cover_cell(filename, info))
                break

    def accept(self):
        """重写accept，将正在编辑的控件内容写回item"""
        if self.title_table.state() == QTableWidget.State.EditingState:
            row = self.title_table.currentRow()
            col = self.title_table.currentColumn()
            viewport = self.title_table.viewport()
            editor = viewport.focusWidget() if viewport else None
            if editor and isinstance(editor, QLineEdit):
                item = self.title_table.item(row, col)
                if item:
                    item.setText(editor.text())
        super().accept()

    def get_data(self) -> Dict:
        """获取编辑后的file_titles、file_details和locked_files"""
        file_titles = {}
        file_details = {}
        locked_files = set()
        for row in range(self.title_table.rowCount()):
            filename_item = self.title_table.item(row, 0)
            if not filename_item:
                continue
            filename = filename_item.text()
            file_titles[filename] = self._get_cell_text(row, 1)
            volume_text = self._get_cell_text(row, 2).strip()
            date_text = self._get_cell_text(row, 3).strip()
            summary_text = self._get_cell_text(row, 4).strip()
            tags_text = self._get_cell_text(row, 5).strip()
            year, month, day = "", "", ""
            if date_text:
                # 三段解析：YYYY-MM-DD 或 YYYY-MM（无日时 day 留空）
                parts = date_text.split("-", 2)
                year = parts[0].strip()
                if len(parts) > 1:
                    month = parts[1].strip()
                if len(parts) > 2:
                    day = parts[2].strip()
            file_details[filename] = {
                "volume": volume_text,
                "year": year,
                "month": month,
                "day": day,
                "summary": summary_text,
                "tags": tags_text
            }
            lock_widget = self.title_table.cellWidget(row, 6)
            if lock_widget:
                checkbox = lock_widget.findChild(QCheckBox)
                if checkbox and checkbox.isChecked():
                    locked_files.add(filename)
        return {"file_titles": file_titles, "file_details": file_details, "locked_files": locked_files}


