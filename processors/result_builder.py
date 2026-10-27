#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""结果构建器 - 构建扫描结果字典"""
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from processors.xml_generator import XMLGenerator
from .cover_utils import get_zip_cover_info
from .utils import check_all_files_have_xml
from parsers.file_parser import is_short_story_folder


def _collect_covers(folder_path: str, comic_files: List) -> Dict:
    """为每个漫画文件提取封面信息 {filename: {path, width, height, ratio_ok}}

    仅处理 zip/cbz（cbr/rar 走 7z 工具链，P2 暂不解析封面）。
    """
    covers = {}
    for f, _ in comic_files:
        if f.lower().endswith(('.zip', '.cbz')):
            info = get_zip_cover_info(os.path.join(folder_path, f))
            if info:
                covers[f] = info
    return covers


def _merge_folder_tags(existing_tags: str, folder_name: str) -> str:
    """合并文件夹名中的标签到已有标签中，去重保持顺序

    × 分隔的多作者标签：若拆开后任一部分已存在于 Tags 则跳过
    （避免 [宇佐崎白×西修] 与已有的 西修/宇佐崎しろ 重复）
    """
    from parsers.folder_parser import parse_folder_name_lenient
    parsed = parse_folder_name_lenient(folder_name)
    # 宽松解析的 tags + aliases 均写入 Tags（ComicInfo XML 无别名字段，别名并入 Tags 才能在 XML 体现）
    folder_tags = (list(parsed.get("tags", []) or []) + list(parsed.get("aliases", []) or [])) if parsed else []
    if not folder_tags:
        return existing_tags
    existing = [t.strip() for t in existing_tags.split(',') if t.strip()] if existing_tags else []
    for tag in folder_tags:
        parts = [p.strip() for p in re.split(r'[×xX]', tag) if p.strip()]
        if any(p in existing for p in parts):
            continue  # 作者已存在于 Tags（拆分后），跳过合并版
        if tag not in existing:
            existing.append(tag)
    return ', '.join(existing)


def _apply_author_fill(writer: str, penciller: str) -> tuple:
    """单向补齐：Writer/Penciller 只有一个时，另一个也填同一人"""
    if writer and not penciller:
        return writer, writer
    if penciller and not writer:
        return penciller, penciller
    return writer, penciller

def create_result_dict(folder_path: str, folder_info: Dict, 
                       comic_info_base: Optional[Dict], selected_result: Optional[Dict],
                       skipped: bool, process_status: str, source: str = "bangumi") -> Dict:
    """创建结果字典
    
    Args:
        folder_path: 文件夹路径
        folder_info: 文件夹信息
        comic_info_base: ComicInfo基础数据
        selected_result: 选中的搜索结果
        skipped: 是否跳过
        process_status: 处理状态（如"处理成功"、"已跳过"）
        source: 数据源（"bangumi"、"manhuagui" 或 "comicvine"）
        
    Returns:
        Dict: 结果字典
    """
    if comic_info_base and comic_info_base.get("Status"):
        comic_status = comic_info_base["Status"]
    elif folder_info.get("complete"):
        comic_status = "Completed"
    else:
        comic_status = "Ongoing"

    file_titles = {}
    file_details = {}
    locked_files = set()
    covers = {}
    try:
        from parsers.file_parser import (generate_smart_title,
                                         parse_volume_from_filename)
        # 收集漫画文件及大小
        comic_files = []
        for f in os.listdir(folder_path):
            file_path = os.path.join(folder_path, f)
            if not os.path.isfile(file_path):
                continue
            if not f.lower().endswith(('.zip', '.cbz', '.cbr', '.rar')):
                continue
            comic_files.append((f, os.path.getsize(file_path)))
            smart_title_result = generate_smart_title(f, folder_info.get("series", ""), folder_info)
            file_titles[f] = smart_title_result[0]
            vol_info = parse_volume_from_filename(f)
            file_details[f] = {
                "volume": vol_info.get("number", ""),
                "year": comic_info_base.get("Year", "") if comic_info_base else "",
                "month": comic_info_base.get("Month", "") if comic_info_base else "",
                "day": comic_info_base.get("Day", "") if comic_info_base else "",
                "summary": comic_info_base.get("Summary", "") if comic_info_base else ""
            }
        # 提取每卷封面信息（尺寸 + 比例异常标记），供 P2 结果页展示
        covers = _collect_covers(folder_path, comic_files)
        # 恢复锁定状态：先查 SQLite 缓存
        from models.database import LockDatabase
        from processors.zip_handler import read_xml_from_zip
        db = LockDatabase()
        db_states = db.batch_get_lock_states(comic_files)
        for f, fsize in comic_files:
            key = (f, fsize)
            if key in db_states:
                if db_states[key]:
                    locked_files.add(f)
            else:
                # SQLite 未命中，解压 ZIP 读 XML Notes
                file_path = os.path.join(folder_path, f)
                xml_data = read_xml_from_zip(file_path)
                if xml_data and xml_data.get("Notes") == "ComicScratcherLocked":
                    locked_files.add(f)
    except Exception:
        pass

    writer, penciller = _apply_author_fill(
        comic_info_base.get("Writer", "") if comic_info_base else folder_info.get("author", ""),
        comic_info_base.get("Penciller", "") if comic_info_base else "",
    )
    result = {
        "folder_path": folder_path,
        "folder_name": os.path.basename(folder_path),
        "series": comic_info_base.get("Series", "") if comic_info_base else folder_info.get("series", ""),
        "short_story": is_short_story_folder(folder_info),
        "file_titles": file_titles,
        "file_details": file_details,
        "covers": covers,
        "locked_files": locked_files,
        "count": comic_info_base.get("Count", "") if comic_info_base else "",
        "writer": writer,
        "penciller": penciller,
        "colorist": comic_info_base.get("Colorist", "") if comic_info_base else "",
        "year": comic_info_base.get("Year", "") if comic_info_base else "",
        "month": comic_info_base.get("Month", "") if comic_info_base else "",
        "day": comic_info_base.get("Day", "") if comic_info_base else "",
        "bangumi_id": str(selected_result.get("id", "")) if (selected_result and source == "bangumi") else "",
        "source_id": str(selected_result.get("id", "")) if (selected_result and source in ("manhuagui", "comicvine")) else "",
        "source_url": selected_result.get("url", "") if selected_result else "",
        "source": source,
        "genre": comic_info_base.get("Genre", "") if comic_info_base else "",
        "publisher": comic_info_base.get("Publisher", "") if comic_info_base else "",
        "status": comic_status,
        "summary": comic_info_base.get("Summary", "") if comic_info_base else "",
        "tags": _merge_folder_tags(
            comic_info_base.get("Tags", "") if comic_info_base else "",
            os.path.basename(folder_path)
        ),
        "rating": comic_info_base.get("Rating", "") if comic_info_base else "",
        "manga": comic_info_base.get("Manga", "Yes") if comic_info_base else "Yes",
        "process_status": process_status,
        "xml_exists": check_all_files_have_xml(folder_path),
        "skipped": skipped
    }

    # Web 链接统一走 web 字段：manhuagui/ComicVine 用详情页 URL，bangumi 拼 bgm.tv 地址
    if result.get("source") in ("manhuagui", "comicvine") and result.get("source_url"):
        result["web"] = result["source_url"]
    elif result.get("bangumi_id"):
        result["web"] = f"https://bgm.tv/subject/{result['bangumi_id']}"
    else:
        result["web"] = ""

    return result


def create_result_dict_from_xml(folder_path: str, folder_info: Dict,
                                 xml_result: Dict) -> Dict:
    """从XML读取结果创建结果字典（修正模式专用）
    
    Args:
        folder_path: 文件夹路径
        folder_info: 文件夹信息
        xml_result: XML读取结果
        
    Returns:
        Dict: 结果字典
    """
    comic_info_base = xml_result.get("comic_info_base", {})
    selected_result = xml_result.get("selected_result", {})
    
    # 确定状态
    if comic_info_base and comic_info_base.get("Status"):
        comic_status = comic_info_base["Status"]
    elif folder_info.get("complete"):
        comic_status = "Completed"
    else:
        comic_status = "Ongoing"

    # 生成文件标题和详情（每个文件读取各自的XML）+ 恢复锁定状态
    file_titles = {}
    file_details = {}
    locked_files = set()
    covers = {}
    try:
        from parsers.file_parser import generate_smart_title, parse_volume_from_filename
        from processors.zip_handler import read_xml_from_zip
        from models.database import LockDatabase
        # 收集漫画文件及大小
        comic_files = []
        for f in os.listdir(folder_path):
            file_path = os.path.join(folder_path, f)
            if not os.path.isfile(file_path):
                continue
            if not f.lower().endswith(('.zip', '.cbz', '.cbr', '.rar')):
                continue
            comic_files.append((f, os.path.getsize(file_path)))

        # 提取每卷封面信息（尺寸 + 比例异常标记），供 P2 结果页展示
        covers = _collect_covers(folder_path, comic_files)
        # 先查 SQLite 缓存恢复锁定状态
        db = LockDatabase()
        db_states = db.batch_get_lock_states(comic_files)

        for f, fsize in comic_files:
            file_path = os.path.join(folder_path, f)
            smart_title_result = generate_smart_title(f, folder_info.get("series", ""), folder_info)
            vol_info = parse_volume_from_filename(f)
            file_xml = read_xml_from_zip(file_path)
            # Title 优先用原 XML 的 Title，回退 smart title（编辑XML 保留原 Title）
            file_titles[f] = (file_xml.get("Title", "") if file_xml else "") or smart_title_result[0]
            if file_xml:
                file_details[f] = {
                    "volume": file_xml.get("Volume", vol_info.get("number", "")),
                    "number": file_xml.get("Number", ""),
                    "year": file_xml.get("Year", ""),
                    "month": file_xml.get("Month", ""),
                    "day": file_xml.get("Day", ""),
                    "summary": file_xml.get("Summary", "")
                }
                # SQLite 未命中时，从 XML Notes 恢复锁定状态
                key = (f, fsize)
                if key in db_states:
                    if db_states[key]:
                        locked_files.add(f)
                elif file_xml.get("Notes") == "ComicScratcherLocked":
                    locked_files.add(f)
            else:
                # 回退：使用文件夹级基础数据
                file_details[f] = {
                    "volume": vol_info.get("number", ""),
                    "year": comic_info_base.get("Year", "") if comic_info_base else "",
                    "month": comic_info_base.get("Month", "") if comic_info_base else "",
                    "day": comic_info_base.get("Day", "") if comic_info_base else "",
                    "summary": comic_info_base.get("Summary", "") if comic_info_base else ""
                }
                # 无 XML 也检查 SQLite 缓存
                key = (f, fsize)
                if key in db_states and db_states[key]:
                    locked_files.add(f)
    except Exception:
        pass

    writer, penciller = _apply_author_fill(
        comic_info_base.get("Writer", "") if comic_info_base else folder_info.get("author", ""),
        comic_info_base.get("Penciller", "") if comic_info_base else "",
    )
    result = {
        "folder_path": folder_path,
        "folder_name": os.path.basename(folder_path),
        "series": comic_info_base.get("Series", "") if comic_info_base else folder_info.get("series", ""),
        "short_story": is_short_story_folder(folder_info),
        "file_titles": file_titles,
        "file_details": file_details,
        "covers": covers,
        "locked_files": locked_files,
        "count": comic_info_base.get("Count", "") if comic_info_base else "",
        "writer": writer,
        "penciller": penciller,
        "colorist": comic_info_base.get("Colorist", "") if comic_info_base else "",
        "year": comic_info_base.get("Year", "") if comic_info_base else "",
        "month": comic_info_base.get("Month", "") if comic_info_base else "",
        "day": comic_info_base.get("Day", "") if comic_info_base else "",
        "bangumi_id": str(selected_result.get("id", "")) if selected_result else "",
        "web": comic_info_base.get("Web", "") if comic_info_base else "",
        "publisher": comic_info_base.get("Publisher", "") if comic_info_base else "",
        "status": comic_status,
        "summary": comic_info_base.get("Summary", "") if comic_info_base else "",
        "genre": comic_info_base.get("Genre", "") if comic_info_base else "",  # 编辑XML路径：分类字段
        "tags": comic_info_base.get("Tags", "") if comic_info_base else "",  # 编辑XML路径：直接从XML读取，不合并文件夹标签
        "rating": comic_info_base.get("Rating", "") if comic_info_base else "",
        "manga": comic_info_base.get("Manga", "") if comic_info_base else "",  # 使用XML中的Manga值
        "process_status": "已读取XML",  # 特殊状态，表示已从XML读取
        "xml_exists": True,
        "xml_readonly": True,  # 标记为只读模式
        "skipped": False  # 不跳过，只是不更新文件
    }
    
    return result
    
