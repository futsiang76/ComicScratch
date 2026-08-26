#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""应用设置对话框"""

import config
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                             QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                             QLabel, QLineEdit, QMessageBox, QPushButton,
                             QSpinBox, QVBoxLayout, QWidget)

# 各分组表单标签文本（单一来源：统一标签列宽按此集合中最长者计算）
_LABELS = {
    "source_token": "Bangumi Access Token:",
    "source_comicvine": "ComicVine API Key:",
    "scan_fuzz": "作品名模糊匹配阈值 (%):",
    "scan_author": "作者名匹配阈值 (%):",
    "scan_timeout": "请求超时时间 (秒):",
    "scan_retries": "请求重试次数:",
    "scan_ignore": "忽略目录规则:",
    "result_format": "保存格式:",
    "result_delete": "写入后删除旧文件:",
    "dir_default": "默认漫画目录:",
    "dir_remember": "记住上次路径:",
    "crop_memory": "封面裁剪定位记忆:",
}


class SwitchButton(QCheckBox):
    """左右开关（QCheckBox 自绘滑动圆钮，选中靠右，绿色）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(48, 20)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        # 轨道
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#4cd964") if self.isChecked() else QColor("#cccccc"))
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        # 滑动圆钮
        d = rect.height() - 4
        x = rect.width() - d - 2 if self.isChecked() else 2
        painter.setBrush(QColor("white"))
        painter.drawEllipse(x, 2, d, d)


class SettingsDialog(QDialog):
    """应用设置对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("应用设置")
        self.setMinimumWidth(460)
        self._label_width = None
        self._setup_ui()

    def _make_label(self, text: str) -> QLabel:
        """创建统一宽度的表单标签，保证各分组输入控件左边缘对齐同一竖线"""
        label = QLabel(text)
        label.setFixedWidth(self._label_column_width())
        return label

    def _label_column_width(self) -> int:
        """统一标签列宽：取全部表单标签中最长文本的渲染宽度（仅计算一次）"""
        if self._label_width is None:
            fm = QFontMetrics(self.font())
            self._label_width = max(
                fm.boundingRect(text).width() for text in _LABELS.values())
        return self._label_width

    def _setup_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)

        # ===== 1. 源配置 =====
        source_group = QGroupBox("源配置")
        source_form = QFormLayout()
        source_group.setLayout(source_form)

        # API Key 配置（密码模式，写入 user_config.json）
        self.bangumi_edit = QLineEdit()
        self.bangumi_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.bangumi_edit.setText(config.BANGUMI_ACCESS_TOKEN)
        source_form.addRow(self._make_label(_LABELS["source_token"]), self.bangumi_edit)

        self.comicvine_edit = QLineEdit()
        self.comicvine_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.comicvine_edit.setText(config.COMICVINE_API_KEY)
        source_form.addRow(self._make_label(_LABELS["source_comicvine"]), self.comicvine_edit)

        layout.addWidget(source_group)

        # ===== 2. 扫描配置 =====
        scan_group = QGroupBox("扫描配置")
        scan_form = QFormLayout()
        scan_group.setLayout(scan_form)

        self.fuzz_spin = QSpinBox()
        self.fuzz_spin.setRange(0, 100)
        self.fuzz_spin.setValue(config.FUZZ_THRESHOLD)
        scan_form.addRow(self._make_label(_LABELS["scan_fuzz"]), self.fuzz_spin)

        self.author_spin = QSpinBox()
        self.author_spin.setRange(0, 100)
        self.author_spin.setValue(config.AUTHOR_MATCH_THRESHOLD)
        scan_form.addRow(self._make_label(_LABELS["scan_author"]), self.author_spin)

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1, 60)
        self.timeout_spin.setValue(config.TIMEOUT)
        scan_form.addRow(self._make_label(_LABELS["scan_timeout"]), self.timeout_spin)

        self.retries_spin = QSpinBox()
        self.retries_spin.setRange(0, 10)
        self.retries_spin.setValue(config.MAX_RETRIES)
        scan_form.addRow(self._make_label(_LABELS["scan_retries"]), self.retries_spin)

        # 忽略目录规则：逗号分隔通配符（fnmatch），命中目录不作为系列且不递归
        self.ignore_dirs_edit = QLineEdit()
        self.ignore_dirs_edit.setText(", ".join(config.SCAN_IGNORE_DIRS))
        self.ignore_dirs_edit.setPlaceholderText("如: .*, _*, temp*")
        # 输入框下方小字说明（默认规则 + 通配符/分隔符用法）
        ignore_hint = QLabel(
            '默认忽略以“.”或“_”开头的文件夹，自定义简单规则时，'
            '以“*”为通配符，并以“,”加空格分隔开来')
        ignore_hint.setWordWrap(True)
        ignore_hint.setStyleSheet("color: gray; font-size: 11px;")
        ignore_widget = QWidget()
        ignore_layout = QVBoxLayout()
        ignore_layout.setContentsMargins(0, 0, 0, 0)
        ignore_layout.setSpacing(2)
        ignore_layout.addWidget(self.ignore_dirs_edit)
        ignore_layout.addWidget(ignore_hint)
        ignore_widget.setLayout(ignore_layout)
        scan_form.addRow(self._make_label(_LABELS["scan_ignore"]), ignore_widget)

        layout.addWidget(scan_group)

        # ===== 3. 扫描结果处理 =====
        result_group = QGroupBox("扫描结果处理")
        result_form = QFormLayout()
        result_group.setLayout(result_form)

        # 保存格式：keep/cbz/zip/cb7（默认保持原格式）
        self.save_format_combo = QComboBox()
        self.save_format_combo.addItem("保持原格式", "keep")
        self.save_format_combo.addItem("CBZ (.cbz)", "cbz")
        self.save_format_combo.addItem("ZIP (.zip)", "zip")
        self.save_format_combo.addItem("CB7 (.cb7)", "cb7")
        index = self.save_format_combo.findData(config.SAVE_FORMAT)
        self.save_format_combo.setCurrentIndex(index if index >= 0 else 0)
        result_form.addRow(self._make_label(_LABELS["result_format"]), self.save_format_combo)

        self.delete_after_convert_switch = SwitchButton()
        self.delete_after_convert_switch.setChecked(config.DELETE_AFTER_CONVERT)
        result_form.addRow(self._make_label(_LABELS["result_delete"]), self.delete_after_convert_switch)

        layout.addWidget(result_group)

        # ===== 4. 应用目录 =====
        dir_group = QGroupBox("应用目录")
        dir_form = QFormLayout()
        dir_group.setLayout(dir_form)

        # 默认漫画目录：QLineEdit + 浏览按钮（留空则启动时提示选择）
        self.default_dir_edit = QLineEdit()
        self.default_dir_edit.setText(config.DEFAULT_MANGA_DIR)
        self.default_dir_edit.setPlaceholderText("留空则启动时提示选择")
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self._browse_default_dir)
        dir_widget = QWidget()
        dir_layout = QHBoxLayout()
        dir_layout.setContentsMargins(0, 0, 0, 0)
        dir_layout.addWidget(self.default_dir_edit)
        dir_layout.addWidget(browse_btn)
        dir_widget.setLayout(dir_layout)
        dir_form.addRow(self._make_label(_LABELS["dir_default"]), dir_widget)

        self.remember_last_path_switch = SwitchButton()
        self.remember_last_path_switch.setChecked(config.REMEMBER_LAST_PATH)
        dir_form.addRow(self._make_label(_LABELS["dir_remember"]), self.remember_last_path_switch)

        layout.addWidget(dir_group)

        # ===== 5. 封面裁剪（放最后） =====
        crop_group = QGroupBox("封面裁剪")
        crop_form = QFormLayout()
        crop_group.setLayout(crop_form)

        self.crop_memory_switch = SwitchButton()
        self.crop_memory_switch.setChecked(config.CROP_MEMORY_ENABLED)
        crop_form.addRow(self._make_label(_LABELS["crop_memory"]), self.crop_memory_switch)

        layout.addWidget(crop_group)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _browse_default_dir(self):
        """浏览选择默认漫画目录（对话框起始目录优先取当前输入值）"""
        start = self.default_dir_edit.text().strip() or config.DEFAULT_MANGA_DIR or ""
        path = QFileDialog.getExistingDirectory(self, "选择默认漫画目录", start)
        if path:
            self.default_dir_edit.setText(path)

    def _on_accept(self):
        config.BANGUMI_ACCESS_TOKEN = self.bangumi_edit.text().strip()
        config.COMICVINE_API_KEY = self.comicvine_edit.text().strip()
        config.FUZZ_THRESHOLD = self.fuzz_spin.value()
        config.AUTHOR_MATCH_THRESHOLD = self.author_spin.value()
        config.TIMEOUT = self.timeout_spin.value()
        config.MAX_RETRIES = self.retries_spin.value()
        # 忽略目录规则：逗号分隔 → 列表（剥引号/全角逗号/去空，保持顺序）
        ignore_raw = self.ignore_dirs_edit.text().replace("，", ",")
        ignore_parsed = []
        for p in ignore_raw.split(","):
            p = p.strip().strip("'\"“”")
            if p:
                ignore_parsed.append(p)
        # 保存前校验：致命问题（如匹配一切目录）默认返回修改；提示问题可仍然保存
        from processors.ignore_rules import find_rule_issues
        blocking, warnings = find_rule_issues(ignore_parsed)
        if blocking or warnings:
            lines = blocking + warnings
            msg = QMessageBox(self)
            msg.setWindowTitle("忽略目录规则提示")
            msg.setText("\n".join(f"• {line}" for line in lines))
            if blocking:
                msg.setInformativeText("是否仍然保存这些规则？")
                msg.setIcon(QMessageBox.Icon.Warning)
                save_btn = msg.addButton("仍然保存", QMessageBox.ButtonRole.AcceptRole)
                msg.addButton("返回修改", QMessageBox.ButtonRole.RejectRole)
                msg.setDefaultButton(msg.buttons()[1])  # 默认返回修改
            else:
                msg.setInformativeText("是否仍然保存？")
                msg.setIcon(QMessageBox.Icon.Information)
                save_btn = msg.addButton("仍然保存", QMessageBox.ButtonRole.AcceptRole)
                msg.addButton("返回修改", QMessageBox.ButtonRole.RejectRole)
            msg.exec()
            if msg.clickedButton() is not save_btn:
                return  # 用户选择返回修改，不关闭对话框
        config.SCAN_IGNORE_DIRS = ignore_parsed
        config.CROP_MEMORY_ENABLED = self.crop_memory_switch.isChecked()
        config.SAVE_FORMAT = self.save_format_combo.currentData()
        config.DELETE_AFTER_CONVERT = self.delete_after_convert_switch.isChecked()
        config.DEFAULT_MANGA_DIR = self.default_dir_edit.text().strip()
        config.REMEMBER_LAST_PATH = self.remember_last_path_switch.isChecked()
        config.save_settings({
            "bangumi_access_token": config.BANGUMI_ACCESS_TOKEN,
            "comicvine_api_key": config.COMICVINE_API_KEY,
            "fuzz_threshold": config.FUZZ_THRESHOLD,
            "author_match_threshold": config.AUTHOR_MATCH_THRESHOLD,
            "timeout": config.TIMEOUT,
            "max_retries": config.MAX_RETRIES,
            "scan_ignore_dirs": config.SCAN_IGNORE_DIRS,
            "crop_memory_enabled": config.CROP_MEMORY_ENABLED,
            "save_format": config.SAVE_FORMAT,
            "delete_after_convert": config.DELETE_AFTER_CONVERT,
            "default_manga_dir": config.DEFAULT_MANGA_DIR,
            "remember_last_path": config.REMEMBER_LAST_PATH,
        })
        self.accept()
