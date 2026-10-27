#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
结果表格填充 - 在结果标签页中展示扫描结果的卡片列表

P2 封面展示：
- 系列卡片左侧显示首卷封面缩略图 + 「共 N 卷」徽章
- 「展开」显示该系列全部卷封面的缩略图网格（网格换行）
- 封面比例异常（非 870x1230±10% 竖版）→ 红色「需裁剪」角标

P3 裁剪交互：
- 所有封面缩略图可点击（ClickableLabel）→ 弹裁剪对话框；仅比例异常叠加红色角标
- 确定后后台裁剪并重打包（__new 排第一位），完成后角标消失、缩略图换新
"""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
                             QLabel, QPushButton, QSizePolicy, QVBoxLayout,
                             QWidget)

from gui.crop_queue import _open_crop_flow
from gui.utils import save_threads_running, set_results_saving
from processors.cover_utils import read_cover_bytes, sort_volume_files

# 封面缩略图尺寸（870x1230 竖版比例）
THUMB_WIDTH = 100
THUMB_HEIGHT = 141
# 卷封面网格间距与列数下限（B5：列数按窗口宽度自适应）
GRID_SPACING = 10
MIN_GRID_COLUMNS = 4


def grid_columns(available_width: int) -> int:
    """按可用宽度计算卷封面网格列数：单格(缩略图+间距)，窄屏保底 4 列，宽屏自动加列（8+）"""
    cell_width = THUMB_WIDTH + GRID_SPACING
    return max(MIN_GRID_COLUMNS, int(available_width) // cell_width)

GROUP_BOX_STYLE = """
    QGroupBox {
        font-weight: bold;
        font-size: 14px;
        color: #333;
        border: 2px solid #4CAF50;
        border-radius: 7px;
        margin-top: 10px;
        padding-top: 10px;
        background-color: white;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 5px 0 5px;
        background-color: #4CAF50;
        color: white;
        border-radius: 3px;
    }
"""

EDIT_BTN_STYLE = """
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
    QPushButton:pressed {
        background-color: #cc7a00;
    }
"""

EXPAND_BTN_STYLE = """
    QPushButton {
        background-color: #4CAF50;
        color: white;
        font-size: 12px;
        border-radius: 3px;
        padding: 4px 12px;
    }
    QPushButton:hover {
        background-color: #45a049;
    }
"""


class ClickableLabel(QLabel):
    """鼠标左键可点击的 QLabel（「需裁剪」封面缩略图用，P3 触发裁剪对话框）"""

    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.unsetCursor()
        super().leaveEvent(event)


def _placeholder_label() -> QLabel:
    """灰色占位框 + 📕（封面缺失/加载失败时兜底）"""
    label = QLabel("📕")
    label.setFixedSize(THUMB_WIDTH, THUMB_HEIGHT)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet(
        "background-color: #e0e0e0; color: #aaa;"
        "border: 1px solid #ccc; font-size: 30px;"
    )
    return label


def _load_cover_pixmap(info: dict) -> "QPixmap | None":
    """从 zip 读取封面字节并缩放为缩略图；无图/失败返回 None"""
    if not info:
        return None
    data = read_cover_bytes(info.get("path", ""))
    if not data:
        return None
    pixmap = QPixmap()
    if not pixmap.loadFromData(data):
        return None
    return pixmap.scaled(
        THUMB_WIDTH, THUMB_HEIGHT,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _cover_thumbnail(info: dict, on_click=None) -> QLabel:
    """封面缩略图 QLabel；无图/加载失败 → 占位图，传入 on_click 时转为可点击"""
    if on_click is None:
        label = _placeholder_label()
    else:
        label = ClickableLabel()
        label.setFixedSize(THUMB_WIDTH, THUMB_HEIGHT)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(
            "background-color: #e0e0e0; color: #aaa;"
            "border: 1px solid #ccc; font-size: 30px;"
        )
        label.clicked.connect(on_click)
    pixmap = _load_cover_pixmap(info)
    if pixmap is not None:
        label.setPixmap(pixmap)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("border: 1px solid #ccc; background-color: #f5f5f5;")
    return label


def _crop_badge() -> QLabel:
    """红色「需裁剪」角标（P2 只做展示标记，裁剪交互在 P3）"""
    badge = QLabel("需裁剪")
    badge.setStyleSheet(
        "background-color: #e53935; color: white; font-size: 10px;"
        "font-weight: bold; border-radius: 3px; padding: 1px 5px;"
    )
    return badge


def _cover_with_badge(info: dict, show_badge: bool, on_click=None) -> QWidget:
    """封面缩略图 + 右上角异常角标（同网格单元格叠加，角标浮于图右上角）

    所有封面均可点击裁剪（合格封面无角标但可点，异常封面带红色角标）。
    """
    container = QWidget()
    layout = QGridLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    layout.addWidget(_cover_thumbnail(info, on_click), 0, 0)
    if show_badge:
        layout.addWidget(
            _crop_badge(), 0, 0,
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
        )
    return container


def _volume_card(filename: str, info: dict, on_click=None) -> QWidget:
    """单卷封面卡片：缩略图 + 文件名 + 异常角标（供卷网格使用）"""
    card = QWidget()
    layout = QVBoxLayout(card)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    inner = QVBoxLayout()  # 封面+标题的居中容器
    inner.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    inner.addWidget(
        _cover_with_badge(info, info.get("ratio_ok") is False, on_click),
        0, Qt.AlignmentFlag.AlignHCenter,
    )
    name_label = QLabel(os.path.basename(filename))
    name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    name_label.setWordWrap(True)
    name_label.setMinimumWidth(THUMB_WIDTH)
    name_label.setStyleSheet("color: #555; font-size: 11px;")
    inner.addWidget(name_label, 0, Qt.AlignmentFlag.AlignHCenter)
    layout.addLayout(inner)
    return card


class _VolumeGrid(QWidget):
    """卷封面网格：列数随宽度自适应，resize 时重排（复用已建缩略图，避免重复读 zip）"""

    def __init__(self, cards: list, parent=None):
        super().__init__(parent)
        self._cards = cards
        self._grid_layout = QGridLayout(self)
        self._grid_layout.setContentsMargins(0, 8, 0, 0)
        self._grid_layout.setSpacing(GRID_SPACING)
        self._relayout(grid_columns(self.width()))

    def _relayout(self, cols: int) -> None:
        """按列数重新摆放卡片"""
        for card in self._cards:
            self._grid_layout.removeWidget(card)
        for idx, card in enumerate(self._cards):
            row, col = divmod(idx, cols)
            self._grid_layout.addWidget(card, row, col)

    def resizeEvent(self, event) -> None:
        """窗口宽度变化导致可用宽度跨过列数阈值时重排"""
        if grid_columns(event.size().width()) != grid_columns(event.oldSize().width()):
            self._relayout(grid_columns(event.size().width()))
        super().resizeEvent(event)


def _build_volume_grid(result: dict, make_handler) -> QWidget:
    """该系列全部卷封面的缩略图网格（列数按宽度自适应，宽屏 8+ 列，窄屏 4 列）"""
    covers = result.get("covers", {}) or {}
    cards = [
        _volume_card(filename, covers[filename], make_handler(filename))
        for filename in sort_volume_files(list(covers.keys()))
    ]
    return _VolumeGrid(cards)


def _toggle_volume_grid(result: dict, holder: QWidget, btn: QPushButton,
                        make_handler) -> None:
    """展开/收起卷封面网格（首次展开才构建，避免隐藏时批量读 zip）"""
    if holder.layout().count() == 0:
        holder.layout().addWidget(_build_volume_grid(result, make_handler))
    visible = not holder.isVisible()
    holder.setVisible(visible)
    btn.setText("收起 ▲" if visible else "展开 ▼")


def update_results_table(mw):
    mw._interactive_widgets = []  # 本次重建的可交互元素（写盘期间禁用，重建后按当前状态恢复/禁用）
    # 清空现有结果（results_layout 中的所有子部件）
    while mw.results_layout.count():
        child = mw.results_layout.takeAt(0)
        if child is not None:
            w = child.widget()
            if w:
                w.deleteLater()

    def _make_crop_handler(result: dict, filename: str):
        """生成点击「需裁剪」封面 → 裁剪对话框的处理器（闭包绑定 result/filename）"""
        return lambda: _open_crop_flow(mw, result, filename)

    # 为每个结果创建一个卡片
    for row, result in enumerate(mw.scan_results):
        group_box = QGroupBox(f"{result['series']} - {result['folder_name']}")
        group_box.setStyleSheet(GROUP_BOX_STYLE)

        outer_layout = QVBoxLayout()
        outer_layout.setSpacing(0)  # 收起/展开网格时紧贴表头，不留默认 6px
        header_layout = QHBoxLayout()
        header_layout.setSpacing(0)  # 左侧封面列与右侧信息列贴紧

        # 左侧列：首卷封面缩略图（异常则叠加红色角标，可点击裁剪）+ 正下方的「展开」按钮
        covers = result.get("covers", {}) or {}
        sorted_names = sort_volume_files(list(covers.keys()))
        first_name = sorted_names[0] if sorted_names else None
        first_info = covers.get(first_name) if first_name else None

        grid_holder = QWidget()
        grid_layout = QVBoxLayout(grid_holder)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_holder.setVisible(False)

        expand_btn = QPushButton("展开 ▼")
        expand_btn.setStyleSheet(EXPAND_BTN_STYLE)
        expand_btn.clicked.connect(
            lambda _, r=result, g=grid_holder, b=expand_btn:
            _toggle_volume_grid(r, g, b, lambda f: _make_crop_handler(r, f))
        )
        mw._interactive_widgets.append(expand_btn)  # 展开卷封面网格，写盘期间禁用
        cover_block = QVBoxLayout()
        cover_block.setSpacing(0)  # 「裁剪封面」紧贴展开/收起按钮上方
        cover_block.setContentsMargins(0, 8, 12, 0)  # 缩略图与卡片顶部留间距（不顶头），右边距 12px 分隔右侧信息列
        cover_container = _cover_with_badge(
            first_info,
            bool(first_info) and first_info.get("ratio_ok") is False,
            _make_crop_handler(result, first_name) if first_name else None,
        )
        mw._interactive_widgets.append(cover_container)  # 封面缩略图（点击裁剪），写盘期间禁用
        cover_block.addWidget(cover_container, 0, Qt.AlignmentFlag.AlignHCenter)
        crop_label = QLabel("裁剪封面")
        crop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        crop_label.setContentsMargins(0, 0, 0, 0)  # 无内边距，紧贴按钮
        crop_label.setStyleSheet("color: #666; font-size: 12px;")
        # 禁止纵向拉伸：否则标签会吃掉卡片剩余高度，文字与展开按钮拉开视觉间距
        crop_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        cover_block.addWidget(crop_label, 0, Qt.AlignmentFlag.AlignHCenter)
        cover_block.addWidget(expand_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        header_layout.addLayout(cover_block)

        # 右侧：卷数徽章 + 信息表单 + 操作
        info_layout = QVBoxLayout()

        top_row = QHBoxLayout()
        vol_count = len(result.get("file_details", {}) or {}) or result.get("count", "")
        count_badge = QLabel(f"📚 共 {vol_count} 卷")
        count_badge.setStyleSheet(
            "background-color: #4CAF50; color: white; font-size: 11px;"
            "font-weight: bold; border-radius: 9px; padding: 2px 10px;"
        )
        top_row.addWidget(count_badge)
        top_row.addStretch()
        info_layout.addLayout(top_row)

        card_layout = QFormLayout()
        card_layout.addRow("文件夹:", QLabel(result["folder_name"]))
        card_layout.addRow("系列名:", QLabel(result["series"]))
        card_layout.addRow("作者:", QLabel(result.get("writer", "")))
        card_layout.addRow("作画:", QLabel(result.get("penciller", "")))
        card_layout.addRow("上色:", QLabel(result.get("colorist", "")))
        card_layout.addRow("Web:", QLabel(result.get("web", "")))
        year_str = result.get("year", "")
        month_str = result.get("month", "")
        day_str = result.get("day", "")
        if year_str and month_str and day_str:
            date_display = f"{year_str}-{month_str}-{day_str}"
        elif year_str and month_str:
            date_display = f"{year_str}-{month_str}"
        else:
            date_display = year_str or ""
        card_layout.addRow("发行时间:", QLabel(date_display))
        card_layout.addRow("状态:", QLabel(result["status"]))

        # 简介和标签（有值才显示）
        summary_text = result.get("summary", "")
        if summary_text:
            summary_label = QLabel(summary_text)
            summary_label.setWordWrap(True)
            summary_label.setMaximumHeight(60)
            card_layout.addRow("简介:", summary_label)

        genre_text = result.get("genre", "")
        if genre_text:
            genre_label = QLabel(genre_text)
            genre_label.setWordWrap(True)
            card_layout.addRow("分类:", genre_label)

        tags_text = result.get("tags", "")
        if tags_text:
            tags_label = QLabel(tags_text)
            tags_label.setWordWrap(True)
            card_layout.addRow("标签:", tags_label)

        card_layout.addRow("是否Manga:", QLabel(result.get("manga", "")))

        # 操作按钮 - 独立于表单行的整宽布局，addStretch 保证水平居中
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        edit_btn = QPushButton("✏️ 编辑")
        edit_btn.setMinimumHeight(35)
        edit_btn.setMinimumWidth(100)
        edit_btn.setStyleSheet(EDIT_BTN_STYLE)
        edit_btn.clicked.connect(lambda _, r=row: mw.edit_row(r))
        mw._interactive_widgets.append(edit_btn)  # 编辑元数据，写盘期间禁用
        button_layout.addWidget(edit_btn)
        button_layout.addStretch()

        info_layout.addLayout(card_layout)
        info_layout.addLayout(button_layout)
        header_layout.addLayout(info_layout, 1)
        outer_layout.addLayout(header_layout)
        outer_layout.addWidget(grid_holder)

        group_box.setLayout(outer_layout)
        mw.results_layout.addWidget(group_box)

    # 写盘进行中：禁用本次构建的可交互元素 + 显示工作小猫；写盘完成自动恢复
    set_results_saving(mw, save_threads_running(mw))
