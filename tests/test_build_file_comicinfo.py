#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_file_comicinfo 公共函数测试 — 统一完整字段入口

覆盖范围：
- 系列字段映射正确（Series/Writer/Count 等由 build_full_comicinfo_dict 提供）
- Title 优先：file_titles 命中 → 用原 Title（编辑XML保留原 Title）
- Title 回退：file_titles 未命中 → 按文件名生成 smart title
- Volume/Number：由 detail 或文件名解析得出
- 锁住文件：year/month/summary 被 detail 覆盖，Notes 写 ComicScratcherLocked
- 非锁文件：Notes 为空
- create_result_dict_from_xml 的 file_titles 反映原 XML Title（编辑XML保留原 Title）
"""
import struct
import zipfile
import zlib

from processors.xml_generator import build_file_comicinfo


def _make_png(width: int, height: int) -> bytes:
    """生成指定尺寸的纯色 PNG 占位图（不依赖 PIL）"""
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row = b"\x00" + b"\x99\x99\x99" * width
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(row * height)) + chunk(b"IEND", b""))


def _make_cbz_with_xml(tmp_path, name: str, title: str, series: str) -> str:
    """生成含 ComicInfo.xml（带 Title/Series）的 cbz 文件"""
    cbz_path = tmp_path / name
    xml_content = (f'<?xml version="1.0"?>\n<ComicInfo>\n'
                   f'    <Title>{title}</Title>\n'
                   f'    <Series>{series}</Series>\n'
                   f'    <Volume>03</Volume>\n'
                   f'</ComicInfo>\n')
    with zipfile.ZipFile(cbz_path, "w") as zf:
        zf.writestr("000.png", _make_png(100, 150))
        zf.writestr("ComicInfo.xml", xml_content)
    return str(cbz_path)


# ---------- 系列字段映射 ----------

def test_series_fields_mapped():
    """系列字段由 build_full_comicinfo_dict 映射（Series/Writer/Count/Genre/Web）"""
    result = {
        "series": "某系列", "count": 5, "writer": "作者甲",
        "genre": "科幻", "web": "https://example.com/x",
    }
    info = build_file_comicinfo(result, "Vol 01.zip")
    assert info["Series"] == "某系列"
    assert info["Writer"] == "作者甲"
    assert info["Count"] == "5"
    assert info["Genre"] == "科幻"
    assert info["Web"] == "https://example.com/x"


def test_result_none_uses_defaults():
    """result 为 None 也能构造（全默认值 + smart title）"""
    info = build_file_comicinfo(None, "Vol 03.zip")
    assert info["Title"] == "Vol 03"
    assert info["Series"] == ""


# ---------- Title 优先级 ----------

def test_title_uses_file_titles_when_hit():
    """file_titles 命中 → 使用原 Title（编辑XML保留原 Title）"""
    info = build_file_comicinfo(
        {"series": "某系列"}, "Vol 01.zip",
        file_titles={"Vol 01.zip": "某卷标题"})
    assert info["Title"] == "某卷标题"
    assert info["Series"] == "某系列"


def test_title_falls_back_to_smart_title():
    """file_titles 未命中 → 按文件名生成 smart title"""
    info = build_file_comicinfo({"series": "某系列"}, "Vol 03.zip")
    assert info["Title"] == "Vol 03"


def test_title_empty_file_title_falls_back():
    """file_titles 命中但为空 → 回退 smart title"""
    info = build_file_comicinfo(
        {"series": "某系列"}, "Vol 03.zip",
        file_titles={"Vol 03.zip": ""})
    assert info["Title"] == "Vol 03"


# ---------- Volume/Number ----------

def test_volume_number_from_detail():
    """detail 有 volume → Volume/Number 同值（文件名用 Vol 格式避免触发
    无 vol_type 的 smart-title 既有边界，与 save_thread 旧行为一致）"""
    info = build_file_comicinfo({"series": "x"}, "Vol 03.zip",
                                detail={"volume": "035"})
    assert info["Volume"] == "035"
    assert info["Number"] == "035"


def test_volume_number_from_filename():
    """detail 空 → 文件名解析单行本"""
    info = build_file_comicinfo({"series": "x"}, "Vol 03.zip")
    assert info["Volume"] == "03"
    assert info["Number"] == "03"


# ---------- 锁定字段 ----------

def test_locked_overrides_year_month_summary():
    """is_locked=True → year/month/day/summary 被 detail 覆盖，Notes 写锁定标记"""
    detail = {"year": "2024", "month": "7", "day": "15", "summary": "单卷独立摘要"}
    info = build_file_comicinfo(
        {"series": "x", "year": "2020", "month": "1", "summary": "系列级摘要"},
        "Vol 01.zip", detail=detail, is_locked=True)
    assert info["Year"] == "2024"
    assert info["Month"] == "7"
    assert info["Day"] == "15"
    assert info["Summary"] == "单卷独立摘要"
    assert info["Notes"] == "ComicScratcherLocked"


def test_unlocked_keeps_series_summary():
    """is_locked=False → year/month/summary 保持系列级，Notes 为空"""
    info = build_file_comicinfo(
        {"series": "x", "year": "2020", "month": "1", "summary": "系列级摘要"},
        "Vol 01.zip",
        detail={"year": "2024", "month": "7", "summary": "单卷独立摘要"},
        is_locked=False)
    assert info["Year"] == "2020"
    assert info["Month"] == "1"
    assert info["Summary"] == "系列级摘要"
    assert info["Notes"] == ""


def test_series_day_applied_to_unlocked_file():
    """result 的 day 经统一入口写入 Day（未锁定卷继承系列级值）"""
    info = build_file_comicinfo({"series": "x", "year": "2008", "month": "9",
                                 "day": "25"}, "Vol 01.zip")
    assert info["Day"] == "25"


def test_notes_unlocked_empty():
    """非锁定文件 Notes 为空"""
    info = build_file_comicinfo({"series": "x"}, "Vol 01.zip")
    assert info["Notes"] == ""


# ---------- create_result_dict_from_xml 集成测试 ----------

def _build_xml_result(comic_info_base):
    return {
        "comic_info_base": comic_info_base,
        "selected_result": {},
    }


def test_create_result_dict_from_xml_file_titles_uses_xml_title(tmp_path):
    """create_result_dict_from_xml 的 file_titles 优先原 XML Title"""
    from processors.result_builder import create_result_dict_from_xml

    _make_cbz_with_xml(tmp_path, "Vol 01.cbz", "某卷标题", "Smoke 系列")
    folder_info = {"series": "Smoke 系列", "complete": True, "total_volumes": 1}
    result = create_result_dict_from_xml(
        str(tmp_path), folder_info,
        _build_xml_result({"Series": "Smoke 系列", "Status": "Completed"}))
    assert result["file_titles"]["Vol 01.cbz"] == "某卷标题"


def test_create_result_dict_from_xml_file_titles_fallback_smart(tmp_path):
    """无 XML 时 file_titles 回退 smart title"""
    from processors.result_builder import create_result_dict_from_xml

    with zipfile.ZipFile(tmp_path / "Vol 02.cbz", "w") as zf:
        zf.writestr("000.png", _make_png(100, 150))
    folder_info = {"series": "Smoke", "complete": True}
    result = create_result_dict_from_xml(
        str(tmp_path), folder_info,
        _build_xml_result({"Series": "Smoke", "Status": "Completed"}))
    assert result["file_titles"]["Vol 02.cbz"] == "Vol 02"


# ---------- 短篇/单卷完结（Title 带后缀、Series 裸名，2026-08-23 反转） ----------

def test_short_story_title_suffixed_series_bare():
    """短篇文件夹（short_story=True）→ Title 带「.短篇完结」，Series 保持裸系列名"""
    result = {"series": "化身者", "short_story": True, "status": "Completed", "tags": "短篇"}
    info = build_file_comicinfo(result, "化身者 (短篇).zip")
    assert info["Title"] == "化身者.短篇完结"
    assert info["Series"] == "化身者"


def test_short_story_series_strips_legacy_suffix():
    """series 带历史遗留后缀（旧版本写在 Series）→ Series 清回裸名，Title 不重复追加"""
    result = {"series": "化身者.短篇完结", "short_story": True}
    info = build_file_comicinfo(result, "Vol 01.zip")
    assert info["Series"] == "化身者"
    assert info["Title"] == "化身者.短篇完结"


def test_non_short_story_series_unchanged():
    """非短篇文件夹 → Series 不带后缀（回归）"""
    result = {"series": "某系列", "short_story": False, "status": "Completed"}
    info = build_file_comicinfo(result, "Vol 01.zip")
    assert info["Series"] == "某系列"
    assert info["Title"] == "Vol 01"


def test_single_volume_complete_title_suffixed_series_bare():
    """(V01全) 单卷完结 → Title 带「.单卷完结」（generate_smart_title 规则1），Series 保持裸名"""
    result = {"series": "Parrot", "status": "Completed"}
    info = build_file_comicinfo(result, "Parrot (V01全).zip")
    assert info["Title"] == "Parrot.单卷完结"
    assert info["Series"] == "Parrot"


def test_short_story_scan_result_flow(tmp_path):
    """端到端：真实解析 (短篇) 文件夹 → create_result_dict → build_file_comicinfo"""
    from parsers.folder_parser_lenient import parse_folder_name_lenient
    from processors.result_builder import create_result_dict

    folder_info = parse_folder_name_lenient("[比良贺みん也] 化身者 (短篇)")
    assert folder_info is not None
    result = create_result_dict(str(tmp_path), folder_info, None, None, False, "已处理")
    assert result["short_story"] is True
    assert result["series"] == "化身者"  # series 信号保持裸名
    info = build_file_comicinfo(result, "化身者 (短篇).zip", file_titles=result["file_titles"])
    assert info["Title"] == "化身者.短篇完结"
    assert info["Series"] == "化身者"