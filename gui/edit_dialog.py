#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
编辑对话框 - 编辑单个条目的元数据（支持多系列导航与修正模式自动逐个跳转）
"""

from typing import Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout,
                             QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
                             QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from models.edit_state import EditState
from .title_edit_dialog import TitleEditDialog

# 输入框统一样式
_FIELD_STYLE = "padding: 5px; border: 1px solid #ddd; border-radius: 3px;"


def _make_btn(text: str, color: str, hover_color: str, pressed_color: str,
              min_width: int = 120, min_height: int = 40, font_size: int = 14) -> QPushButton:
    """创建统一样式的按钮"""
    btn = QPushButton(text)
    btn.setMinimumHeight(min_height)
    btn.setMinimumWidth(min_width)
    btn.setStyleSheet(f"""
        QPushButton {{
            background-color: {color};
            color: white;
            font-size: {font_size}px;
            font-weight: bold;
            border-radius: 5px;
            padding: 10px;
        }}
        QPushButton:hover {{ background-color: {hover_color}; }}
        QPushButton:pressed {{ background-color: {pressed_color}; }}
        QPushButton:disabled {{ background-color: #ccc; color: #999; }}
    """)
    return btn


class EditDialog(QDialog):
    """编辑对话框 - 用于编辑单个条目的元数据"""

    def __init__(self, data: Dict, parent=None, filename: str = "", locked_files: set = None,
                 results_list: list = None, current_index: int = 0, auto_advance: bool = False):
        super().__init__(parent)
        self.state = EditState(data)
        self.filename = filename
        # 向后兼容：合并外部传入的 locked_files
        if locked_files:
            for fn in locked_files:
                self.state.locked_files.add(fn)
        self.results_list = results_list
        self.current_index = current_index
        # 修正模式多系列：点「确定」自动保存并跳到下一个系列，最后一项才关闭
        self.auto_advance = auto_advance
        self.init_ui()

    def _add_line_field(self, form: QFormLayout, label: str, attr: str, value: str) -> QLineEdit:
        """创建带统一样式的 QLineEdit，挂到 self.<attr> 并加入表单"""
        edit = QLineEdit(value)
        edit.setStyleSheet(_FIELD_STYLE)
        setattr(self, attr, edit)
        form.addRow(label, edit)
        return edit

    def _add_combo_field(self, form: QFormLayout, label: str, attr: str,
                         items: list, current: str) -> QComboBox:
        """创建 QComboBox，挂到 self.<attr> 并加入表单"""
        combo = QComboBox()
        combo.addItems(items)
        if current:
            combo.setCurrentText(current)
        combo.setStyleSheet(_FIELD_STYLE)
        setattr(self, attr, combo)
        form.addRow(label, combo)
        return combo

    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle("编辑元数据")
        self.setMinimumSize(600, 700)

        layout = QVBoxLayout()

        # ── 系列导航（多系列时显示，标签含当前系列名） ──
        if self.results_list and len(self.results_list) > 1:
            series_label = QLabel(self._format_series_label())
            series_label.setObjectName("series_label")
            series_label.setStyleSheet("font-size: 13px; color: #666; font-weight: bold;")
            layout.addWidget(series_label)

        form_layout = QFormLayout()

        self._add_line_field(form_layout, "系列名:", "series_edit", self.state.series)
        self._add_line_field(form_layout, "总卷数:", "count_edit", str(self.state.count))
        self._add_line_field(form_layout, "作者:", "writer_edit", self.state.writer)
        self._add_line_field(form_layout, "作画:", "penciller_edit", self.state.penciller)
        self._add_line_field(form_layout, "上色:", "colorist_edit", self.state.colorist)
        # Web 完整链接（固定标签，不区分数据源）
        self._add_line_field(form_layout, "Web:", "web_edit", self.state.web)

        # 发行日期（年月日同行）
        year_month_layout = QHBoxLayout()
        self.year_edit = QLineEdit(self.state.year)
        self.year_edit.setPlaceholderText("年")
        self.year_edit.setMaximumWidth(80)
        self.year_edit.setStyleSheet(_FIELD_STYLE)
        year_month_layout.addWidget(self.year_edit)
        year_month_layout.addWidget(QLabel("-"))
        self.month_edit = QLineEdit(self.state.month)
        self.month_edit.setPlaceholderText("月")
        self.month_edit.setMaximumWidth(60)
        self.month_edit.setStyleSheet(_FIELD_STYLE)
        year_month_layout.addWidget(self.month_edit)
        year_month_layout.addWidget(QLabel("-"))
        self.day_edit = QLineEdit(self.state.day)
        self.day_edit.setPlaceholderText("日")
        self.day_edit.setMaximumWidth(60)  # 宽度同月框
        self.day_edit.setStyleSheet(_FIELD_STYLE)
        year_month_layout.addWidget(self.day_edit)
        year_month_layout.addStretch()
        form_layout.addRow("发行日期:", year_month_layout)

        self._add_combo_field(form_layout, "状态:", "status_combo",
                              ["", "Completed", "Ongoing"], self.state.status)

        # 简介
        self.summary_edit = QTextEdit(self.state.summary)
        self.summary_edit.setMaximumHeight(80)
        self.summary_edit.setStyleSheet(_FIELD_STYLE)
        form_layout.addRow("简介:", self.summary_edit)

        self._add_line_field(form_layout, "分类:", "genre_edit", self.state.genre)
        self._add_line_field(form_layout, "标签:", "tags_edit", self.state.tags)
        self._add_combo_field(form_layout, "是否Manga:", "manga_combo",
                              ["Yes", "No"], self.state.manga)

        layout.addLayout(form_layout)

        # ── 卷列表表格 ──
        if self.state.file_titles:
            vol_label = QLabel("📚 系列包含的卷")
            vol_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #333; padding: 10px 5px 5px 5px;")
            layout.addWidget(vol_label)

            self.volume_table = QTableWidget()
            self.volume_table.setColumnCount(4)
            self.volume_table.setHorizontalHeaderLabels(["文件名", "Title", "Volume", "🔒 锁定"])

            header = self.volume_table.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
            header.setStyleSheet("""
                QHeaderView::section {
                    background-color: #4CAF50;
                    color: white;
                    padding: 5px;
                    border: 1px solid #ddd;
                    font-weight: bold;
                }
            """)

            self.volume_table.setStyleSheet("""
                QTableWidget {
                    gridline-color: #ddd;
                    border: 1px solid #ddd;
                    border-radius: 5px;
                    background-color: white;
                }
                QTableWidget::item {
                    padding: 5px;
                }
            """)

            self._refresh_volume_table()

            lock_hint = QLabel("锁定后，该卷的元数据在系列级修改中不会被覆盖")
            lock_hint.setStyleSheet("color: #999; font-size: 11px; padding: 2px 5px;")
            layout.addWidget(lock_hint)

            # 逐卷编辑按钮
            self.edit_titles_btn = _make_btn("📝 逐卷编辑各卷详细信息...", "#2196F3",
                                             "#0b7dda", "#0a5f8f", min_width=200)
            self.edit_titles_btn.clicked.connect(self.open_title_edit)
            layout.addWidget(self.edit_titles_btn)
        else:
            self.volume_table = None
            self.edit_titles_btn = None

        # ── 前后系列导航按钮 ──
        if self.results_list and len(self.results_list) > 1:
            nav_layout = QHBoxLayout()
            nav_layout.addStretch()

            self.prev_btn = _make_btn("◀", "#2196F3", "#0b7dda", "#0a5f8f",
                                      min_width=50, font_size=18)
            self.prev_btn.setEnabled(self.current_index > 0)
            self.prev_btn.clicked.connect(lambda: self._navigate(-1))
            nav_layout.addWidget(self.prev_btn)

            self.next_btn = _make_btn("▶", "#2196F3", "#0b7dda", "#0a5f8f",
                                      min_width=50, font_size=18)
            self.next_btn.setEnabled(self.current_index < len(self.results_list) - 1)
            self.next_btn.clicked.connect(lambda: self._navigate(1))
            nav_layout.addWidget(self.next_btn)

            layout.addLayout(nav_layout)

        # 按钮区域
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        ok_btn = _make_btn("✅ 确定", "#4CAF50", "#45a049", "#3d8b40")
        ok_btn.clicked.connect(self.accept)
        button_layout.addWidget(ok_btn)

        cancel_btn = _make_btn("❌ 取消", "#f44336", "#da190b", "#b7140a")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        button_layout.addStretch()
        layout.addLayout(button_layout)

        self.setLayout(layout)

    def _refresh_volume_table(self):
        """从 self.state 重建卷列表表格"""
        if self.volume_table is None:
            return

        sorted_items = self.state.get_volumes_sorted()
        self.volume_table.setRowCount(len(sorted_items))

        for row, (filename, title) in enumerate(sorted_items):
            detail = self.state.file_details.get(filename, {})
            is_locked = self.state.is_locked(filename)

            # 文件名（只读，灰底）
            filename_item = QTableWidgetItem(filename)
            filename_item.setFlags(filename_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            filename_item.setBackground(Qt.GlobalColor.lightGray)
            self.volume_table.setItem(row, 0, filename_item)

            # Title（只读）
            title_item = QTableWidgetItem(title)
            title_item.setFlags(title_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.volume_table.setItem(row, 1, title_item)

            # Volume（只读）
            vol = detail.get("volume", "")
            vol_item = QTableWidgetItem(str(vol) if vol else "")
            vol_item.setFlags(vol_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.volume_table.setItem(row, 2, vol_item)

            # 🔒 锁定 checkbox
            lock_widget = QWidget()
            lock_layout = QHBoxLayout(lock_widget)
            lock_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lock_layout.setContentsMargins(0, 0, 0, 0)

            lock_cb = QCheckBox()
            lock_cb.setChecked(is_locked)
            lock_cb.stateChanged.connect(
                lambda state, fn=filename: self.state.set_locked(fn, state == 2)
            )
            lock_layout.addWidget(lock_cb)
            self.volume_table.setCellWidget(row, 3, lock_widget)

        self.volume_table.cellDoubleClicked.connect(self._on_volume_double_click)

    def _on_volume_double_click(self, row, col):
        """双击卷列表行打开单卷编辑"""
        fn_item = self.volume_table.item(row, 0)
        if fn_item:
            dialog = TitleEditDialog(self.state, self, selected_filename=fn_item.text())
            if dialog.exec() == QDialog.DialogCode.Accepted:
                title_data = dialog.get_data()
                self.state.update_from_title_data(title_data)
                self._refresh_volume_table()

    def open_title_edit(self):
        """打开逐卷编辑对话框"""
        selected_filename = None
        if self.volume_table is not None:
            selected_rows = set()
            for item in self.volume_table.selectedItems():
                selected_rows.add(item.row())
            if len(selected_rows) == 1:
                row = list(selected_rows)[0]
                fn_item = self.volume_table.item(row, 0)
                if fn_item:
                    selected_filename = fn_item.text()
        dialog = TitleEditDialog(self.state, self, selected_filename=selected_filename)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            title_data = dialog.get_data()
            self.state.update_from_title_data(title_data)
            self._refresh_volume_table()

    def _save_current_to_list(self):
        """将当前编辑状态保存到 results_list[current_index]"""
        if self.results_list is None or self.current_index >= len(self.results_list):
            return
        current = self.get_data()
        self.results_list[self.current_index].update(current)
        self.results_list[self.current_index]["process_status"] = "已修改"

    def _load_result_into_ui(self, data: Dict):
        """将 data 加载到 UI 控件"""
        self.state = EditState(data)
        self.series_edit.setText(self.state.series)
        self.count_edit.setText(str(self.state.count))
        self.writer_edit.setText(self.state.writer)
        self.penciller_edit.setText(self.state.penciller)
        self.colorist_edit.setText(self.state.colorist)
        self.web_edit.setText(self.state.web)
        self.year_edit.setText(self.state.year)
        self.month_edit.setText(self.state.month)
        self.day_edit.setText(self.state.day)
        self.status_combo.setCurrentText(self.state.status)
        self.summary_edit.setPlainText(self.state.summary)
        self.genre_edit.setText(self.state.genre)
        self.tags_edit.setText(self.state.tags)
        self.manga_combo.setCurrentText(self.state.manga if self.state.manga else "Yes")
        # 刷新卷列表
        if self.volume_table is not None:
            self._refresh_volume_table()

    def _format_series_label(self) -> str:
        """构造系列导航标签：序号 + 当前系列名"""
        if not self.results_list:
            return ""
        name = self.state.series
        if not name and self.current_index < len(self.results_list):
            name = self.results_list[self.current_index].get("series", "")
        return f"系列 {self.current_index + 1} / {len(self.results_list)} — {name}"

    def _navigate(self, delta: int):
        """前后切换系列"""
        new_index = self.current_index + delta
        if new_index < 0 or new_index >= len(self.results_list):
            return

        # 保存当前
        self._save_current_to_list()

        # 加载新系列
        self.current_index = new_index
        self._load_result_into_ui(self.results_list[self.current_index])

        # 更新系列标签（序号 + 系列名）
        series_label = self.findChild(QLabel, "series_label")
        if series_label:
            series_label.setText(self._format_series_label())

        # 更新箭头状态
        self.prev_btn.setEnabled(self.current_index > 0)
        self.next_btn.setEnabled(self.current_index < len(self.results_list) - 1)

    def accept(self):
        """确定时保存当前编辑到列表；auto_advance 且未到末项时跳到下一系列继续编辑"""
        self._save_current_to_list()
        if self.auto_advance and self.results_list and self.current_index < len(self.results_list) - 1:
            self._navigate(1)
            return
        super().accept()

    def get_data(self) -> Dict:
        """获取编辑后的数据，未锁定卷自动同步系列级 year/month/day/summary（见 EditState.sync_series_values）"""
        series_year = self.year_edit.text().strip()
        series_month = self.month_edit.text().strip()
        series_day = self.day_edit.text().strip()
        series_summary = self.summary_edit.toPlainText().strip()
        self.state.sync_series_values(series_year, series_month, series_day, series_summary)

        result = {
            "series": self.series_edit.text(),
            "count": self.count_edit.text(),
            "writer": self.writer_edit.text(),
            "penciller": self.penciller_edit.text(),
            "colorist": self.colorist_edit.text(),
            "web": self.web_edit.text(),
            "year": series_year,
            "month": series_month,
            "day": series_day,
            "status": self.status_combo.currentText(),
            "summary": series_summary,
            "genre": self.genre_edit.text(),
            "tags": self.tags_edit.text(),
            "manga": self.manga_combo.currentText(),
            "file_titles": self.state.file_titles,
            "file_details": self.state.file_details,
            "locked_files": self.state.locked_files,
            "is_locked": self.filename in self.state.locked_files if self.filename else False,
        }
        return result
