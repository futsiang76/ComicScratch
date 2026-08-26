#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
扫描控制逻辑 - 扫描启动/停止/进度/完成回调
"""

import os
from functools import partial
from typing import Dict, List, Optional, Tuple

from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import Qt

from config import (SOURCE_BANGUMI_TEXT, SOURCE_COMICVINE_TEXT,
                    SOURCE_MANHUAGUI_TEXT)

from .edit_dialog import EditDialog
from .save_handler import save_single_result
from .scan_tab import apply_source_mode_constraint
from .scan_thread import ScanThread
from .utils import start_loading_cat, stop_loading_cat


def _lock_controls(mw) -> None:
    """扫描期间锁定扫描模式与数据源选择，防止中途切换"""
    mode_group = getattr(mw, "mode_group", None)
    if mode_group is not None:
        for btn in mode_group.buttons():
            btn.setEnabled(False)
    source_combo = getattr(mw, "source_combo", None)
    if source_combo is not None:
        source_combo.setEnabled(False)
    # 锁定目录输入/浏览/编辑XML/无人值守（控件可能不存在，getattr 防御）
    for attr in ("path_edit", "browse_btn", "edit_xml_btn", "auto_turbo_check"):
        widget = getattr(mw, attr, None)
        if widget is not None:
            widget.setEnabled(False)
    # 扫描期间显示进度条（所有 start 分支统一在此 show）
    progress_bar = getattr(mw, "progress_bar", None)
    if progress_bar is not None:
        progress_bar.show()


def _unlock_controls(mw) -> None:
    """扫描结束/出错后恢复模式与数据源选择（受限源下仍保持其模式约束）"""
    apply_source_mode_constraint(mw, getattr(mw, "selected_source", SOURCE_BANGUMI_TEXT))
    source_combo = getattr(mw, "source_combo", None)
    if source_combo is not None:
        source_combo.setEnabled(True)
    # 恢复目录输入/浏览/编辑XML/无人值守（控件可能不存在，getattr 防御）
    for attr in ("path_edit", "browse_btn", "edit_xml_btn", "auto_turbo_check"):
        widget = getattr(mw, attr, None)
        if widget is not None:
            widget.setEnabled(True)


def start_scan(mw):
    """开始扫描"""
    manga_root = mw.path_edit.text().strip().strip('"\'')
    if not manga_root:
        QMessageBox.warning(mw, "警告", "请先选择漫画根目录")
        return

    if not os.path.isdir(manga_root):
        QMessageBox.warning(mw, "警告", "指定的目录不存在")
        return

    # 数据源路由：manhuagui / ComicVine 走「多系列拦截 → 单系列扫描」
    source = getattr(mw, "selected_source", SOURCE_BANGUMI_TEXT)
    if source == SOURCE_MANHUAGUI_TEXT:
        _start_manhuagui_scan(mw, manga_root)
        return
    if source == SOURCE_COMICVINE_TEXT:
        _start_comicvine_scan(mw, manga_root)
        return

    # 弹出对话框询问是否为Manga
    manga_value = _ask_manga_setting(mw)
    if manga_value is None:
        # 用户点击取消
        return

    # 获取配置
    mode = mw.mode_group.checkedId()
    auto_turbo = 1 if mw.auto_turbo_check.isChecked() else 0

    # 手动匹配模式：Bangumi ID 在扫描过程中逐文件夹输入，此处无需提前获取
    bangumi_id = None

    # 清空日志
    mw.log_text.clear()
    mw.log_text.append(f"开始扫描: {manga_root}")
    mw.log_text.append(f"模式: {mw.mode_group.checkedButton().text()}")
    mw.log_text.append(f"无人值守: {'开启' if auto_turbo else '关闭'}")
    mw.log_text.append(f"Manga设置: {manga_value}")

    # 清空结果
    mw.scan_results = []
    mw.update_results_table()

    # 手动匹配模式：逐个系列文件夹「输入→查询→确认」，后台线程执行
    # （弹窗经 DialogBridge 桥接主线程，主线程不阻塞，小猫动画持续刷新）
    if mode == 3:
        _start_manual_match_scan(mw, manga_root, manga_value)
        return

    # 全匹配模式（非无人值守）：逐个系列「扫描→确认→保存」，后台线程执行
    # （弹窗经 DialogBridge 桥接主线程，进度/日志/结果经信号更新，主线程不阻塞）
    if mode == 0 and auto_turbo != 1:
        from .full_match_scan import FullMatchThread

        thread = FullMatchThread(manga_root, manga_value, parent=mw)
        mw.scan_thread = thread
        thread.progress_updated.connect(partial(_on_full_match_progress, mw))
        thread.progress_range.connect(partial(_on_full_match_progress_range, mw))
        thread.log_message.connect(partial(_on_full_match_log, mw))
        thread.scan_completed.connect(partial(_on_full_match_completed, mw))
        thread.series_saved.connect(partial(_on_full_match_series_saved, mw), Qt.ConnectionType.QueuedConnection)
        thread.series_finished.connect(partial(_on_full_match_series_finished, mw))
        thread.error_occurred.connect(partial(on_error_occurred, mw))

        mw.scan_btn.setEnabled(False)
        mw.stop_btn.setEnabled(True)
        mw.progress_bar.setRange(0, 0)  # 不确定进度（后台线程开始时由信号校正）

        _lock_controls(mw)
        start_loading_cat(mw)  # 全匹配扫描等待期显示工作小猫动画（进度条已 show，定位准确）
        thread.start()
        return

    # 创建并启动扫描线程
    mw.scan_thread = ScanThread(manga_root, mode, auto_turbo, manga_value, bangumi_id, parent=mw)
    mw.scan_thread.progress_updated.connect(mw.on_progress_updated)
    mw.scan_thread.scan_completed.connect(mw.on_scan_completed)
    mw.scan_thread.error_occurred.connect(mw.on_error_occurred)

    mw.scan_btn.setEnabled(False)
    mw.stop_btn.setEnabled(True)
    mw.progress_bar.setRange(0, 0)  # 不确定进度

    _lock_controls(mw)
    start_loading_cat(mw)  # 批量扫描等待期显示工作小猫动画（进度条已 show，定位准确）
    mw.scan_thread.start()


def _ask_manga_setting(mw) -> Optional[str]:
    """弹出 Manga 设置对话框，返回 'Yes'/'No'/None（取消）"""
    manga_dialog = QMessageBox(mw)
    manga_dialog.setWindowTitle("Manga设置")
    manga_dialog.setText("请选择是否为Manga（漫画）")
    manga_dialog.setInformativeText("此设置将应用于所有扫描到的文件")
    yes_btn = manga_dialog.addButton("是 (Yes)", QMessageBox.ButtonRole.YesRole)
    no_btn = manga_dialog.addButton("否 (No)", QMessageBox.ButtonRole.NoRole)
    manga_dialog.addButton("取消", QMessageBox.ButtonRole.RejectRole)
    manga_dialog.exec()

    if manga_dialog.clickedButton() == yes_btn:
        return "Yes"
    if manga_dialog.clickedButton() == no_btn:
        return "No"
    return None


def _start_manhuagui_scan(mw, manga_root: str) -> None:
    """manhuagui 源扫描入口：依赖检查 → 多系列拦截 → 单系列扫描

    manhuagui 源只支持单系列目录：多系列在扫描前拦截弹窗，不开始扫。
    依赖未装成功（用户取消/安装失败）直接返回，不影响 Bangumi 源。
    """
    from models.manhuagui_deps import ensure_manhuagui_deps

    # 1. 依赖检查
    if not ensure_manhuagui_deps(mw):
        return

    # 2. 多系列拦截
    folders = _collect_series_folders(manga_root)
    if len(folders) > 1:
        QMessageBox.warning(
            mw, "数据源限制",
            "manhuagui 源只支持单系列扫描，请拆分成单系列目录或用 Bangumi 源",
        )
        return

    # 3. Manga 设置（与 Bangumi 流程一致）
    manga_value = _ask_manga_setting(mw)
    if manga_value is None:
        return

    # 3.5 清空日志/结果（主线程操作，对应原 _run_manhuagui_single_scan 的初始化）
    mw.log_text.clear()
    mw.log_text.append(f"开始扫描: {manga_root}")
    mw.log_text.append(f"数据源: {SOURCE_MANHUAGUI_TEXT}")
    mw.log_text.append(f"Manga设置: {manga_value}")
    mw.scan_results = []
    mw.update_results_table()

    # 4. 单系列扫描流程（搜索走 manhuagui，后台线程执行，对齐全匹配 FullMatchThread）
    from .manhuagui_scan import ManhuaguiScanThread

    thread = ManhuaguiScanThread(manga_root, manga_value, folders, parent=mw)
    mw.scan_thread = thread
    thread.progress_updated.connect(partial(_on_full_match_progress, mw))
    thread.progress_range.connect(partial(_on_full_match_progress_range, mw))
    thread.log_message.connect(partial(_on_full_match_log, mw))
    thread.scan_completed.connect(partial(_on_full_match_completed, mw))
    thread.series_saved.connect(partial(_on_full_match_series_saved, mw), Qt.ConnectionType.QueuedConnection)
    thread.series_finished.connect(partial(_on_manhuagui_series_finished, mw))
    thread.error_occurred.connect(partial(on_error_occurred, mw))

    mw.scan_btn.setEnabled(False)
    mw.stop_btn.setEnabled(True)
    mw.progress_bar.setRange(0, 0)  # 不确定进度（后台线程开始时由信号校正）

    _lock_controls(mw)
    start_loading_cat(mw)  # manhuagui 扫描等待期显示工作小猫动画（进度条已 show，定位准确）
    thread.start()


def _start_comicvine_scan(mw, manga_root: str) -> None:
    """ComicVine 源扫描入口：多系列拦截 → Manga 设置 → 单系列扫描（后台线程）

    ComicVine 源只支持单系列目录：多系列在扫描前拦截弹窗，不开始扫。
    requests 直连无额外依赖，无需依赖检查（与 manhuagui 分支不同）。
    """
    # 1. 多系列拦截
    folders = _collect_series_folders(manga_root)
    if len(folders) > 1:
        QMessageBox.warning(
            mw, "数据源限制",
            "ComicVine 源只支持单系列扫描，请拆分成单系列目录或用 Bangumi 源",
        )
        return

    # 2. Manga 设置（与 Bangumi 流程一致）
    manga_value = _ask_manga_setting(mw)
    if manga_value is None:
        return

    # 2.5 清空日志/结果（主线程操作，对应原 _run_comicvine_single_scan 的初始化）
    mw.log_text.clear()
    mw.log_text.append(f"开始扫描: {manga_root}")
    mw.log_text.append("数据源: ComicVine")
    mw.log_text.append(f"Manga设置: {manga_value}")
    mw.scan_results = []
    mw.update_results_table()

    # 3. 单系列扫描流程（搜索走 ComicVine，后台线程执行）
    from .comicvine_scan import ComicVineScanThread

    thread = ComicVineScanThread(manga_root, manga_value, folders, parent=mw)
    mw.scan_thread = thread
    thread.progress_updated.connect(partial(_on_full_match_progress, mw))
    thread.progress_range.connect(partial(_on_full_match_progress_range, mw))
    thread.log_message.connect(partial(_on_full_match_log, mw))
    thread.scan_completed.connect(partial(_on_full_match_completed, mw, mode=0))
    thread.series_saved.connect(partial(_on_full_match_series_saved, mw), Qt.ConnectionType.QueuedConnection)
    thread.series_finished.connect(partial(_on_comicvine_series_finished, mw))
    thread.error_occurred.connect(partial(on_error_occurred, mw))

    mw.scan_btn.setEnabled(False)
    mw.stop_btn.setEnabled(True)
    mw.progress_bar.setRange(0, 0)  # 不确定进度（后台线程开始时由信号校正）

    _lock_controls(mw)
    start_loading_cat(mw)  # ComicVine 扫描等待期显示工作小猫动画（进度条已 show，定位准确）
    thread.start()


def _collect_series_folders(manga_root: str) -> List[Tuple[str, Dict]]:
    """收集目标目录下的系列文件夹列表（直接包含漫画文件的目录）

    高一层目录已收集为系列时，其子目录不再重复收集（与递归扫描语义一致）。

    Args:
        manga_root: 漫画根目录

    Returns:
        List[Tuple[str, Dict]]: [(folder_path, folder_info), ...]
    """
    from parsers.file_parser import parse_folder_from_filename
    from parsers.folder_parser import parse_folder_name_lenient

    from processors.ignore_rules import get_ignore_patterns, filter_subdirs, is_dir_ignored

    comic_ext = ('.zip', '.cbz', '.cbr', '.rar')
    folders = []
    collected = []
    ignore_patterns = get_ignore_patterns()
    for root, dirs, files in os.walk(manga_root):
        # 父级已是系列文件夹时跳过其后代，避免重复处理
        if any(root.startswith(parent + os.sep) for parent in collected):
            continue
        # 忽略规则剪枝：命中规则的目录（如 .开头/_开头）不作为系列且不再递归
        dirs[:] = filter_subdirs(dirs, ignore_patterns)
        if root != manga_root and is_dir_ignored(os.path.basename(root), ignore_patterns):
            continue
        if not any(f.lower().endswith(comic_ext) for f in files):
            continue
        folder_info = parse_folder_name_lenient(os.path.basename(root), root)
        if not folder_info:
            folder_info = parse_folder_from_filename(root)
        if folder_info:
            collected.append(root)
            folders.append((root, folder_info))
    return folders


def _start_manual_match_scan(mw, manga_root: str, manga_value: Optional[str]) -> None:
    """手动匹配模式（mode 3）扫描入口：后台线程逐个系列「输入→查询→确认」

    每个文件夹：
      1. 弹窗输入 Bangumi ID（0=使用本地文件夹信息）
      2. 查询 Bangumi 详情并构建 comic_info_base（本地则直接构建）
      3. 构建结果并立即弹 EditDialog 确认
      4. 确认后写入 XML，进入下一个文件夹

    弹窗经 DialogBridge 桥接主线程，进度/日志/结果经信号更新，主线程不阻塞。
    """
    from .manual_match_scan import ManualMatchThread

    folders = _collect_series_folders(manga_root)

    thread = ManualMatchThread(manga_root, manga_value, folders, parent=mw)
    mw.scan_thread = thread
    thread.progress_updated.connect(partial(_on_full_match_progress, mw))
    thread.progress_range.connect(partial(_on_full_match_progress_range, mw))
    thread.log_message.connect(partial(_on_full_match_log, mw))
    thread.scan_completed.connect(partial(_on_full_match_completed, mw, mode=3))
    thread.series_saved.connect(partial(_on_full_match_series_saved, mw), Qt.ConnectionType.QueuedConnection)
    thread.series_finished.connect(partial(_on_manual_series_finished, mw))
    thread.error_occurred.connect(partial(on_error_occurred, mw))

    mw.scan_btn.setEnabled(False)
    mw.stop_btn.setEnabled(True)
    mw.progress_bar.setRange(0, 0)  # 不确定进度（后台线程开始时由信号校正）

    _lock_controls(mw)
    start_loading_cat(mw)  # 手动匹配扫描等待期显示工作小猫动画（进度条已 show，定位准确）
    thread.start()


def check_xml_before_scan(mw, manga_root: str) -> tuple:
    """扫描前检查目录中是否已有XML文件，返回 (是否有XML, 统计信息)"""
    try:
        from processors.zip_handler import check_zip_xml_files
        
        stats = {
            "total_files": 0,
            "files_with_xml": 0,
            "files_without_xml": 0,
            "sample_files": [],  # 前10个有XML的文件示例
            "no_xml_files": []   # 前10个无XML的文件示例
        }
        
        for root, dirs, files in os.walk(manga_root):
            for file in files:
                if file.lower().endswith(('.zip', '.cbz', '.cbr', '.rar')):
                    stats["total_files"] += 1
                    file_path = os.path.join(root, file)
                    try:
                        # 检查ZIP文件中是否包含ComicInfo.xml
                        has_xml, _, _ = check_zip_xml_files(file_path, "")
                    except Exception:
                        # 无法读取的归档视为无XML
                        has_xml = False
                    relative_path = os.path.relpath(file_path, manga_root)
                    if has_xml:
                        stats["files_with_xml"] += 1
                        # 保存前10个有XML的文件作为示例
                        if len(stats["sample_files"]) < 10:
                            stats["sample_files"].append(relative_path)
                    else:
                        stats["files_without_xml"] += 1
                        # 保存前10个无XML的文件作为示例
                        if len(stats["no_xml_files"]) < 10:
                            stats["no_xml_files"].append(relative_path)
        
        has_xml = stats["files_with_xml"] > 0
        return has_xml, stats
    except Exception as e:
        print(f"检查XML文件时出错: {e}")
        return False, {}


def stop_scan(mw):
    """停止扫描"""
    if mw.scan_thread and mw.scan_thread.isRunning():
        mw.scan_thread.stop()
        mw.log_text.append("\n正在停止扫描...")
        mw.stop_btn.setEnabled(False)


def on_progress_updated(mw, progress: int, message: str):
    """进度更新"""
    mw.log_text.append(message)
    # 自动滚动到底部（确保滚动条非 None）
    vbar = mw.log_text.verticalScrollBar()
    if vbar is not None:
        vbar.setValue(vbar.maximum())


def _finish_scan(mw, results: List[Dict], mode: int) -> None:
    """扫描/编辑收尾：路由到结果页或扫描页（未来 008 封面流程的挂载点）

    有结果 → 直接切到结果页；无结果 → 留在扫描页。
    扩展点：未来 008 合并封面改图后，在此调用 _maybe_start_cover_flow(mw, results, mode)
    判断是否进入封面处理流程（结果页封面缩略图 → 用户选择是否改图）。
    """
    if not results:
        mw.tab_widget.setCurrentIndex(0)  # 无结果 → 扫描页
        return
    mw.tab_widget.setCurrentIndex(1)      # 有结果 → 结果页
    # 未来扩展点：_maybe_start_cover_flow(mw, results, mode)


def _on_full_match_progress(mw, progress: int, message: str) -> None:
    """全匹配模式进度信号：更新进度条值 + 日志滚动（主线程槽）"""
    mw.progress_bar.setValue(progress)
    if message:
        mw.log_text.append(message)
        vbar = mw.log_text.verticalScrollBar()
        if vbar is not None:
            vbar.setValue(vbar.maximum())


def _on_full_match_progress_range(mw, minimum: int, maximum: int) -> None:
    """全匹配模式进度条范围信号：setRange 语义（主线程槽）"""
    mw.progress_bar.setRange(minimum, maximum)


def _on_full_match_log(mw, message: str) -> None:
    """全匹配模式日志信号：追加日志并滚动到底部（主线程槽）"""
    mw.log_text.append(message)
    vbar = mw.log_text.verticalScrollBar()
    if vbar is not None:
        vbar.setValue(vbar.maximum())


def _on_full_match_series_finished(mw, processed: int, skipped: int) -> None:
    """全匹配模式收尾信号：追加统计消息（主线程槽）"""
    mw.log_text.append(f"\n全匹配完成: 共处理 {processed} 个系列，跳过 {skipped} 个")
    vbar = mw.log_text.verticalScrollBar()
    if vbar is not None:
        vbar.setValue(vbar.maximum())


def _on_manhuagui_series_finished(mw, processed: int, skipped: int) -> None:
    """manhuagui 单系列扫描收尾信号：追加统计消息（主线程槽）"""
    mw.log_text.append(f"\nmanhuagui 扫描完成: 共处理 {processed} 个系列，跳过 {skipped} 个")
    vbar = mw.log_text.verticalScrollBar()
    if vbar is not None:
        vbar.setValue(vbar.maximum())


def _on_comicvine_series_finished(mw, processed: int, skipped: int) -> None:
    """ComicVine 单系列扫描收尾信号：追加统计消息（主线程槽）"""
    mw.log_text.append(f"\nComicVine 扫描完成: 共处理 {processed} 个系列，跳过 {skipped} 个")
    vbar = mw.log_text.verticalScrollBar()
    if vbar is not None:
        vbar.setValue(vbar.maximum())


def _on_manual_series_finished(mw, processed: int, skipped: int) -> None:
    """手动匹配模式收尾信号：追加统计消息（主线程槽）"""
    mw.log_text.append(f"\n手动匹配完成: 共处理 {processed} 个系列，跳过 {skipped} 个")
    vbar = mw.log_text.verticalScrollBar()
    if vbar is not None:
        vbar.setValue(vbar.maximum())


def _on_full_match_series_saved(mw, result: Dict) -> None:
    """全匹配模式逐系列保存信号：结果入库 → 立即静默写盘（主线程槽，QueuedConnection）

    每个系列确认后即时保存，保证扫描中途崩溃/强制停止时已确认结果不丢失。
    只保存当前这一个 result（save_single_result），绝不调 save_changes——
    后者会收集 scan_results 里【所有】"已修改"结果，导致后确认的系列把前面
    已写的系列重复写盘，且多个 SaveThread 并发写同一批 zip（WinError 5 +
    G:/.comicscratch_tmp 多份相同 tmp）。save_single_result 自带等待队列：
    已有保存线程在跑时入队，前一个完成后立即续写，任意时刻保存线程数 ≤1。
    结果表刷新延后到写盘完成槽 _on_save_finished 里的
    update_results_table，避免写盘期间并发读 zip。
    """
    mw.scan_results.append(result)
    save_single_result(mw, result)


def _on_full_match_completed(mw, results: List[Dict], mode: int = 0) -> None:
    """全匹配/manhuagui/ComicVine/手动匹配模式完成信号：统一收尾（主线程槽）

    结果已由 series_saved 逐系列保存并写盘，此处仅兜底刷新结果表，
    不重复 save_changes。results 参数保留以兼容既有调用方。
    mode 标识来源模式，用于 _finish_scan 路由（008 封面流程挂载点）。
    """
    stop_loading_cat(mw)
    _unlock_controls(mw)
    mw.update_results_table()
    mw.scan_btn.setEnabled(True)
    mw.stop_btn.setEnabled(False)
    mw.progress_bar.setRange(0, 1)
    mw.progress_bar.setValue(1)
    _finish_scan(mw, mw.scan_results, mode)


def on_scan_completed(mw, results: List[Dict]):
    """扫描完成"""
    from PySide6.QtWidgets import QDialog

    stop_loading_cat(mw)
    _unlock_controls(mw)
    mw.scan_results = results
    mw.progress_bar.setRange(0, 1)
    mw.progress_bar.setValue(1)

    mw.log_text.append(f"\n扫描完成! 共找到 {len(results)} 个文件夹")
    mw.log_text.append("=" * 80)

    mw.scan_btn.setEnabled(True)
    mw.stop_btn.setEnabled(False)
    mw.update_results_table()

    # ── 有扫描结果 → 打开编辑元数据（多系列导航） ──
    from config import AUTO_TURBO_MATCH, MODE_SKIP_XMLEXIST
    # 修正模式结果（_from_modify）必须进入编辑流程，即使无人值守也不自动保存
    is_modify_results = any(r.get("_from_modify") for r in results)
    if AUTO_TURBO_MATCH == 1 and not is_modify_results:
        # 无人值守模式：不弹编辑窗，直接保存
        mw.log_text.append(f"🚀 无人值守模式：自动保存 {len(results)} 个结果")
        if results:
            for r in results:
                r["process_status"] = "已修改"
            mw.save_changes()
    elif len(results) == 1:
        # 单个结果 → 弹编辑元数据（无导航；修正模式标记结果逐项编辑）
        result = results[0]
        dialog = EditDialog(result, mw, auto_advance=is_modify_results)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            updated_data = dialog.get_data()
            mw.scan_results[0].update(updated_data)
            mw.scan_results[0]["process_status"] = "已修改"
            mw.update_results_table()
            mw.save_changes()
        else:
            mw.scan_results = []
            mw.update_results_table()

    elif len(results) > 1:
        # 多个结果 → 弹编辑元数据（带 ◀▶ 导航；修正模式自动逐个跳转）
        first_result = results[0]
        dialog = EditDialog(first_result, mw, results_list=mw.scan_results,
                            current_index=0, auto_advance=is_modify_results)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # 对话框关闭时把其余结果也标记为已修改，确保多系列全部写入
            for r in mw.scan_results:
                r["process_status"] = "已修改"
            mw.update_results_table()
            mw.save_changes()
        else:
            mw.scan_results = []
            mw.update_results_table()

    # 统一收尾：有结果 → 结果页；无结果/取消编辑 → 留在扫描页
    _finish_scan(mw, mw.scan_results, MODE_SKIP_XMLEXIST)


def on_error_occurred(mw, error: str):
    """发生错误"""
    stop_loading_cat(mw)
    _unlock_controls(mw)
    mw.log_text.append(f"\n❌ {error}")
    mw.progress_bar.setRange(0, 1)
    mw.progress_bar.setValue(0)

    mw.scan_btn.setEnabled(True)
    mw.stop_btn.setEnabled(False)

    QMessageBox.critical(mw, "错误", error)
