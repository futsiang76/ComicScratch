#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XML编辑器 - 打开/编辑/对比 XML 文件
"""

import copy
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                             QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                             QMessageBox, QPushButton, QTextEdit, QVBoxLayout,
                             QWidget)

from .edit_dialog import EditDialog
from .utils import _trim_compare_dicts


def _xml_data_to_edit_fields(xml_data: dict) -> dict:
    """将 ComicInfo.xml 字段字典转换为编辑对话框字段字典

    xml_data 是 {XML标签: 值}（如 Series/Writer/Genre），
    返回 EditDialog 使用的 data 字典（series/writer/genre...）。
    两处编辑流程（文件/压缩包内 XML）共用，字段增改只改这里。
    """
    return {
        "series": xml_data.get("Series", ""),
        "count": xml_data.get("Count", ""),
        "writer": xml_data.get("Writer", ""),
        "penciller": xml_data.get("Penciller", ""),
        "colorist": xml_data.get("Colorist", ""),
        "year": xml_data.get("Year", ""),
        "month": xml_data.get("Month", ""),
        "status": xml_data.get("Status", ""),
        "summary": xml_data.get("Summary", ""),
        "genre": xml_data.get("Genre", ""),
        "tags": xml_data.get("Tags", ""),
        "manga": xml_data.get("Manga", ""),
    }


def _has_edit_changes(original: dict, updated: dict) -> bool:
    """对比原始/更新后字段，判断是否有实际修改（任一字段变化即 True）"""
    return any(
        str(original.get(key, "")).strip() != str(updated.get(key, "")).strip()
        for key in original
    )


def open_xml_editor(mw, xml_path: str):
    """打开XML编辑对话框 - 解析ComicInfo.xml并打开编辑对话框
    
    扫描页"编辑XML"按钮和结果页均可调用此方法。
    """
    import xml.etree.ElementTree as ET

    if not os.path.isfile(xml_path):
        QMessageBox.warning(mw, "错误", f"文件不存在:\n{xml_path}")
        return

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        xml_data = {child.tag: (child.text or "").strip() for child in root}
    except Exception as e:
        QMessageBox.warning(mw, "错误", f"读取XML文件失败:\n{str(e)[:200]}")
        return

    data = _xml_data_to_edit_fields(xml_data)

    original_data = copy.deepcopy(data)
    dialog = EditDialog(data, mw)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        updated_data = dialog.get_data()

        # 检查是否有实际修改
        if not _has_edit_changes(original_data, updated_data):
            print("ℹ️  无实际修改，跳过保存")
            return

        from processors.xml_generator import XMLGenerator, build_file_comicinfo

        xml_filename = os.path.basename(xml_path)
        comic_info = build_file_comicinfo(
            updated_data, xml_filename,
            file_titles={xml_filename: xml_data.get("Title", "")},
            detail={})

        try:
            xml_content = XMLGenerator().generate_comicinfo_xml(comic_info)
            with open(xml_path, 'w', encoding='utf-8') as f:
                f.write(xml_content)
            QMessageBox.information(mw, "成功", f"ComicInfo.xml 已保存")
        except Exception as e:
            QMessageBox.warning(mw, "错误", f"保存XML文件失败:\n{str(e)[:200]}")



def on_edit_xml_clicked(mw):
    """扫描页"编辑XML"按钮点击处理"""
    from processors.utils import process_xml_modify_folder
    from processors.result_builder import create_result_dict_from_xml
    from parsers.folder_parser import parse_folder_name_lenient
    from processors.xml_generator import XMLGenerator, build_file_comicinfo
    from processors.zip_handler import add_file_to_zip

    current_dir = mw.path_edit.text().strip()
    # 剥离首尾引号（从文件管理器复制的路径可能带 " 或 '）
    if len(current_dir) >= 2 and current_dir[0] in ('"', "'") and current_dir[-1] == current_dir[0]:
        current_dir = current_dir[1:-1]
    current_dir = current_dir.strip()
    if not current_dir:
        QMessageBox.warning(mw, "错误", "请先选择漫画目录")
        return

    # 判断：父目录（含子目录）vs 单系列目录（直接含zip）
    from processors.ignore_rules import filter_subdirs
    subdirs = [d for d in os.listdir(current_dir)
               if os.path.isdir(os.path.join(current_dir, d))]
    # 忽略规则（设置里可配）：命中通配符的目录（如 .开头/_开头）不作为系列
    subdirs = filter_subdirs(subdirs)
    has_zip = any(f.lower().endswith(('.zip', '.cbz'))
                  for f in os.listdir(current_dir)
                  if os.path.isfile(os.path.join(current_dir, f)))

    if subdirs and not has_zip:
        # ── 父目录模式：每个子目录是一个系列 ──
        results_list = []
        for sub in sorted(subdirs):
            sub_path = os.path.join(current_dir, sub)
            folder_info = parse_folder_name_lenient(sub, sub_path)
            if not folder_info:
                folder_info = {"series": sub, "author": "", "volume": "",
                               "total_volumes": 0, "complete": False}
            xml_result = process_xml_modify_folder(sub_path, folder_info, 0)
            if xml_result and xml_result.get("comic_info_base"):
                result = create_result_dict_from_xml(sub_path, folder_info, xml_result)
                result["_from_modify"] = True
                result["folder_path"] = sub_path
                results_list.append(result)

        if not results_list:
            QMessageBox.warning(mw, "错误", "所有子目录中均未找到 ComicInfo.xml")
            return

        # 全部从 modify 路径来
        mw.scan_results = results_list
        dialog = EditDialog(results_list[0], mw, results_list=mw.scan_results, current_index=0)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            mw.scan_results = []
            return

        # 保存：每个系列的结果写入各自目录（per-file 推导 Volume/Number）
        for i, r in enumerate(mw.scan_results):

            folder_path = r.get("folder_path", current_dir)
            for f in os.listdir(folder_path):
                if not f.lower().endswith(('.zip', '.cbz')):
                    continue
                try:
                    file_info = build_file_comicinfo(
                        r, f,
                        file_titles=r.get("file_titles", {}),
                        detail=r.get("file_details", {}).get(f, {}),
                        is_locked=f in r.get("locked_files", set()))
                    xml_content = XMLGenerator().generate_comicinfo_xml(file_info)
                    add_file_to_zip(os.path.join(folder_path, f), xml_content)
                except Exception:
                    pass

        QMessageBox.information(mw, "成功", f"已保存 {len(mw.scan_results)} 个系列")
        mw.scan_results = []
        return

    # ── 单系列目录模式（直接含zip文件） ──
    folder_name = os.path.basename(current_dir)
    folder_info = parse_folder_name_lenient(folder_name, current_dir)
    if not folder_info:
        folder_info = {"series": folder_name, "author": "", "volume": "",
                       "total_volumes": 0, "complete": False}

    xml_result = process_xml_modify_folder(current_dir, folder_info, 0)
    if not xml_result or not xml_result.get("comic_info_base"):
        QMessageBox.warning(mw, "错误", "当前目录的 zip/cbz 文件中未找到 ComicInfo.xml")
        return

    result = create_result_dict_from_xml(current_dir, folder_info, xml_result)
    result["_from_modify"] = True

    original_data = copy.deepcopy(result)
    dialog = EditDialog(result, mw)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return

    updated_data = dialog.get_data()

    has_changes = any(
        str(original_data.get(k, "")).strip() != str(updated_data.get(k, "")).strip()
        for k in ["series", "count", "writer", "penciller", "colorist",
                  "year", "month", "status", "summary", "genre", "tags", "manga"]
    )
    if not has_changes:
        print("ℹ️   无实际修改，跳过保存")
        return

    success_count = 0
    fail_count = 0
    for f in os.listdir(current_dir):
        if not f.lower().endswith(('.zip', '.cbz')):
            continue
        try:
            file_info = build_file_comicinfo(
                updated_data, f,
                file_titles=result.get("file_titles", {}),
                detail=result.get("file_details", {}).get(f, {}),
                is_locked=f in result.get("locked_files", set()))
            xml_content = XMLGenerator().generate_comicinfo_xml(file_info)
            if add_file_to_zip(os.path.join(current_dir, f), xml_content):
                success_count += 1
            else:
                fail_count += 1
        except Exception:
            fail_count += 1

    if fail_count == 0:
        QMessageBox.information(mw, "成功",
                                f"ComicInfo.xml 已保存到 {success_count} 个文件")
    else:
        QMessageBox.warning(mw, "完成",
                            f"成功: {success_count} 个, 失败: {fail_count} 个")


def edit_zip_xml(parent: QWidget, zip_path: str) -> bool:
    """编辑zip/cbz文件中的ComicInfo.xml - 用于批量处理中的XML编辑

    Args:
        parent: 父窗口
        zip_path: 包含ComicInfo.xml的zip/cbz文件路径

    Returns:
        True if changes were saved, False otherwise
    """
    from processors.zip_handler import read_xml_from_zip, add_file_to_zip
    from processors.xml_generator import XMLGenerator, build_file_comicinfo

    if not os.path.isfile(zip_path):
        QMessageBox.warning(parent, "错误", f"文件不存在:\n{zip_path}")
        return False

    xml_data = read_xml_from_zip(zip_path)
    if xml_data is None:
        QMessageBox.warning(parent, "错误",
                            f"读取 ComicInfo.xml 失败:\n{os.path.basename(zip_path)}")
        return False

    data = _xml_data_to_edit_fields(xml_data)

    original_data = copy.deepcopy(data)
    filename = os.path.basename(zip_path)
    dialog = EditDialog(data, parent, filename=filename)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False

    updated_data = dialog.get_data()

    if not _has_edit_changes(original_data, updated_data):
        return False

    comic_info = build_file_comicinfo(
        updated_data, filename,
        file_titles={filename: xml_data.get("Title", "")},
        detail={"volume": xml_data.get("Volume", ""),
                "number": xml_data.get("Number", "")})

    try:
        xml_content = XMLGenerator().generate_comicinfo_xml(comic_info)
        if add_file_to_zip(zip_path, xml_content):
            QMessageBox.information(parent, "成功",
                                    f"ComicInfo.xml 已保存到:\n{filename}")
            return True
        else:
            QMessageBox.warning(parent, "错误",
                                f"写入 ComicInfo.xml 失败:\n{filename}")
            return False
    except Exception as e:
        QMessageBox.warning(parent, "错误", f"保存XML文件失败:\n{str(e)[:200]}")
        return False


