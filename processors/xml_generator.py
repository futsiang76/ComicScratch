#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XML生成器模块 - 负责生成ComicInfo.xml内容
"""

import re
from typing import Any, Dict, Optional

from processors.xml_template_handler import XMLTemplateHandler


def clean_year(year_value: Any) -> str:
    """清洗 ComicInfo 的 Year 字段：只保留 4 位数字年份（如 1999），否则返回空字符串。

    Komga 读取 ComicInfo.xml 时 Year 是数字类型，带「年」等非数字字符会导致整份
    XML 反序列化失败（Jackson 报 ComicInfo["Year"]），Title/Summary/作者/Tags 全部丢失。
    manhuagui 源抓到的年代形如「1999年」，必须在此清成纯数字：优先匹配 4 位年份
    （正则 \\d{4}），退而求其次取连续数字段；提取不到返回空字符串（不硬塞 0000）。
    """
    if year_value is None:
        return ""
    text = str(year_value).strip()
    if not text:
        return ""
    match = re.search(r"\d{4}", text)
    if match:
        return match.group(0)
    match = re.search(r"\d+", text)
    return match.group(0) if match else ""


def clean_month(month_value: Any) -> str:
    """清洗 ComicInfo 的 Month 字段：只保留 1-2 位数字月份（如 1 或 01），否则返回空字符串。

    与 clean_year 同理：Month 在 Komga 中同为数字类型，带非数字字符会导致解析失败。
    """
    if month_value is None:
        return ""
    text = str(month_value).strip()
    if not text:
        return ""
    match = re.search(r"\d+", text)
    return match.group(0) if match else ""


def clean_day(day_value: Any) -> str:
    """清洗 ComicInfo 的 Day 字段：只保留 1-31 的日（如 5 或 25），否则返回空字符串。

    与 clean_year/clean_month 同理：Day 在 Komga 中同为数字类型，带非数字字符会导致
    解析失败。除数字校验外还做范围校验——"0"、"32" 这类非法日一律清空（空串不写标签）。
    传入完整日期串（如 "2008-09-25"）时抽到 2008，超出范围同样清空。
    """
    if day_value is None:
        return ""
    text = str(day_value).strip()
    if not text:
        return ""
    match = re.search(r"\d+", text)
    if not match:
        return ""
    digits = match.group(0)
    return digits if 1 <= int(digits) <= 31 else ""


class XMLGenerator:
    """XML生成器类"""
    
    def __init__(self):
        """初始化生成器"""
        self.template_handler = XMLTemplateHandler()
    
    def generate_comicinfo_xml(self, comic_info: Dict[str, Any]) -> str:
        """生成ComicInfo.xml内容
        
        Args:
            comic_info: ComicInfo字典
            
        Returns:
            str: XML格式的字符串
        """
        xml_content = '''<?xml version="1.0"?>\n<ComicInfo xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">\n'''
        
                # 按特定顺序添加字段
        fields_order = [
            "Title", "Series", "Volume", "Number", "Count", "Summary", "Notes",
            "Year", "Month", "Day", "Writer", "Penciller", "Inker", "Colorist", "Letterer",
            "CoverArtist", "Editor", "Publisher", "Genre", "Web", "PageCount",
            "LanguageISO", "Format", "BlackAndWhite", "Manga", "AgeRating",
            "Tags", "Status", "Rating"
        ]
        
        for field in fields_order:
            value = comic_info.get(field, "")
            if value:
                xml_content += f'    <{field}>{self._escape_xml(value)}</{field}>\n'
        
        xml_content += '</ComicInfo>'
        return xml_content
    
    def generate_for_short_story(self, folder_info: Dict[str, Any]) -> str:
        """为短篇内容生成XML
        
        Args:
            folder_info: 文件夹信息字典
            
        Returns:
            str: XML内容字符串
        """
        template = self.template_handler.create_base_template(folder_info, is_short_story=True)
        return self.generate_comicinfo_xml(template)
    
    def generate_with_bangumi_data(self, bangumi_data: Dict[str, Any], folder_info: Dict[str, Any]) -> str:
        """使用Bangumi数据生成XML
        
        Args:
            bangumi_data: Bangumi数据字典
            folder_info: 文件夹信息字典
            
        Returns:
            str: XML内容字符串
        """
        template = self.template_handler.create_bangumi_template(bangumi_data, folder_info)
        return self.generate_comicinfo_xml(template)
    
    def generate_with_local_data(self, folder_info: Dict[str, Any]) -> str:
        """使用本地数据生成XML（搜索失败时使用）
        
        Args:
            folder_info: 文件夹信息字典
            
        Returns:
            str: XML内容字符串
        """
        template = self.template_handler.create_local_template(folder_info)
        return self.generate_comicinfo_xml(template)
    
    def generate_for_file(self, base_comic_info: Dict[str, Any], file_name: str, 
                         folder_info: Dict[str, Any]) -> str:
        """为单个文件生成XML
        
        Args:
            base_comic_info: 基础ComicInfo数据
            file_name: 文件名
            folder_info: 文件夹信息
            
        Returns:
            str: XML内容字符串
        """
        import re

        from parsers.file_parser import (generate_smart_title,
                                         parse_volume_from_filename)

        # 复制基础数据
        file_comic_info = base_comic_info.copy()
        
        # 生成智能标题
        smart_title_result = generate_smart_title(file_name, folder_info.get("series", ""), folder_info)
        smart_title = smart_title_result[0]  # 提取标题字符串
        
        # 判断文件类型：先尝试从文件名提取卷数信息
        file_vol_info = parse_volume_from_filename(file_name)
        
        # 如果能成功提取卷数信息，说明是单行本文件
        if file_vol_info['number'] and file_vol_info['number'].strip():
            # 普通卷数文件
            file_comic_info.update({
                "Title": smart_title,  # 使用智能生成的标题
                "Count": base_comic_info.get("Count", ""),  # 已完结填写总卷数，连载中留空
                "Volume": file_vol_info['number'],  # 单本书的卷数
                "Number": file_vol_info['number'],  # 新增：Number 与 Volume 同值
            })
        else:
            # 检查是否为单话文件（C01、C 01、第01话等）
            chapter_match = re.search(r'(C\s*\d+|第\s*\d+\s*话)', file_name, re.IGNORECASE)
            if chapter_match:
                # 单话文件，将序号写入Number字段
                chapter_text = chapter_match.group(1)
                # 提取数字部分
                number_match = re.search(r'\d+', chapter_text)
                if number_match:
                    file_comic_info.update({
                        "Title": smart_title,  # 使用智能生成的标题
                        "Number": number_match.group(),  # 单话编号
                        "Volume": "",  # 单话文件不显示Volume
                        "Status": "Ongoing"  # 单话文件视为已完结
                    })
                else:
                    # 无法提取数字，使用默认逻辑
                    file_comic_info.update({
                        "Title": smart_title,  # 使用智能生成的标题
                        "Volume": "",  # 非单行本内容不显示Volume
                        "Status": "Completed"  # 非单行本内容视为已完结
                    })
            else:
                # 无法识别为单行本或单话的文件（包括画集、设定集、番外等）
                file_comic_info.update({
                    "Title": smart_title,  # 使用智能生成的标题
                    "Volume": "",  # 非单行本内容不显示Volume
                    "Status": "Completed"  # 非单行本内容视为已完结
                })
            # 保留Count字段，如果整个系列已完结，应该显示总卷数
            # 只有当整个系列连载中时，Count字段才会为空
        
        return self.generate_comicinfo_xml(file_comic_info)
    
    def _escape_xml(self, text: str) -> str:
        """转义XML特殊字符
        
        Args:
            text: 需要转义的文本
            
        Returns:
            str: 转义后的文本
        """
        if not text:
            return text
        
        # 替换XML特殊字符
        replacements = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&apos;'
        }
        
        for char, replacement in replacements.items():
            text = text.replace(char, replacement)
        
        return text


def apply_volume_number(file_comic_info: Dict[str, Any], filename: str,
                        detail: Optional[Dict] = None) -> None:
    """为单个漫画文件推导并原地写入 Volume/Number。

    规则：detail 有 volume → 单行本（Number 取 detail 的 number，缺省同 volume）；
    detail 无 volume 但有 number → 单话（Number=话号，Volume 空）；否则按文件名解析
    （单行本 Number=Volume 同值；C01/第01话 → Number=话号 Volume 空；其它 → 都空）。
    """
    import re
    from parsers.file_parser import parse_volume_from_filename

    detail = detail or {}
    if detail.get("volume"):
        file_comic_info["Volume"] = detail["volume"]
        file_comic_info["Number"] = detail.get("number") or detail["volume"]
    elif detail.get("number"):
        file_comic_info["Number"] = detail["number"]
        file_comic_info["Volume"] = ""
    else:
        vol_info = parse_volume_from_filename(filename)
        if vol_info.get("number") and vol_info["number"].strip():
            file_comic_info["Volume"] = vol_info["number"]
            file_comic_info["Number"] = vol_info["number"]
        else:
            chapter_match = re.search(r'(C\s*\d+|第\s*\d+\s*话)', filename, re.IGNORECASE)
            if chapter_match:
                number_match = re.search(r'\d+', chapter_match.group(1))
                if number_match:
                    file_comic_info["Number"] = number_match.group()
                    file_comic_info["Volume"] = ""
            else:
                file_comic_info["Volume"] = ""
                file_comic_info["Number"] = ""


def build_file_comicinfo(result: Optional[Dict], filename: str, *,
                         file_titles: Optional[Dict] = None,
                         detail: Optional[Dict] = None,
                         is_locked: bool = False) -> Dict[str, Any]:
    """为单个漫画文件生成完整 ComicInfo 字典（系列字段 + per-file 字段）。

    所有保存路径（save_thread 扫描保存 / xml_editor 编辑XML保存）共用此唯一入口，
    per-file 字段写入逻辑集中一处，以后加 per-file 字段只改这里。
    result 为系列字段来源（扫描结果 dict 或 EditDialog 的 get_data 返回），
    file_titles/detail/is_locked 为 per-file 数据。
    """
    # 系列字段 + 默认值（Series/Writer/Count/Genre/Web 等由 build_full_comicinfo_dict 映射）
    file_comic_info = build_full_comicinfo_dict(result)
    result = result or {}
    file_titles = file_titles or {}
    detail = detail or {}
    # Title：file_titles 优先（编辑XML 保留原 Title），否则按文件名生成 smart title
    if file_titles.get(filename):
        file_comic_info["Title"] = file_titles[filename]
    else:
        from parsers.file_parser import generate_smart_title
        folder_info = {"series": result.get("series", ""),
                       "complete": result.get("status") == "Completed",
                       "short_story": result.get("short_story", False)}
        file_comic_info["Title"] = generate_smart_title(
            filename, result.get("series", ""), folder_info)[0]
    # Volume/Number：detail 或文件名解析
    apply_volume_number(file_comic_info, filename, detail)
    # 锁住的文件：detail 覆盖 year/month/day/summary（Year/Month/Day 经清洗，防非数字字符）
    if is_locked:
        if detail.get("year"):
            file_comic_info["Year"] = clean_year(detail["year"])
        if detail.get("month"):
            file_comic_info["Month"] = clean_month(detail["month"])
        if detail.get("day"):
            file_comic_info["Day"] = clean_day(detail["day"])
        if detail.get("summary"):
            file_comic_info["Summary"] = detail["summary"]
    # Notes 锁定标记
    file_comic_info["Notes"] = "ComicScratcherLocked" if is_locked else ""
    return file_comic_info


def build_full_comicinfo_dict(result=None, **overrides) -> Dict[str, Any]:
    """构建完整的 ComicInfo 字典——所有写入路径共用此入口。

    基于 COMICINFO_TEMPLATE 确保所有字段都有默认值（Genre/Format/LanguageISO 等），
    然后通过 result 字典和关键字参数覆盖。

    Args:
        result: 扫描结果字典（可选），包含 series/count/writer/penciller/colorist/
                year/month/status/summary/tags/manga/publisher/bangumi_id 等字段
        **overrides: 单独覆盖的 ComicInfo 字段名（如 Title, Volume, Notes 等）

    Returns:
        Dict[str, Any]: 完整的 ComicInfo 字典（包含 COMICINFO_TEMPLATE 全部字段）
    """
    from config import COMICINFO_TEMPLATE

    info = COMICINFO_TEMPLATE.copy()

    if result:
        _apply_result_fields(info, result)

    if overrides:
        for k, v in overrides.items():
            if k in info:
                info[k] = v

    return info


def _apply_result_fields(info: Dict[str, Any], result: Dict[str, Any]) -> None:
    """将扫描结果字典的通用字段映射到 ComicInfo 字典（原地修改）。"""
    series = str(result.get("series", ""))
    # Series 永远保持裸系列名：清除历史遗留后缀（旧版本曾把后缀写在 Series 上）
    for legacy in (".短篇完结", ".单卷完结"):
        if series.endswith(legacy):
            series = series[: -len(legacy)]
            break
    info["Series"] = series
    info["Title"] = series
    # 短篇完结：短篇文件夹（result 携带 short_story 信号）→ Title 带「.短篇完结」后缀
    # （save_thread 的 Title 实际由 generate_smart_title 生成，此处兜底直接 result→XML 路径）
    # 幂等：已带后缀不重复追加；Series 保持裸名
    if result.get("short_story") and not series.endswith(".短篇完结"):
        info["Title"] = f"{series}.短篇完结"
    info["Count"] = str(result.get("count", "")) if result.get("count") else ""
    info["Writer"] = str(result.get("writer", ""))
    info["Penciller"] = str(result.get("penciller", ""))
    info["Colorist"] = str(result.get("colorist", ""))
    info["Year"] = clean_year(result.get("year", ""))
    info["Month"] = clean_month(result.get("month", ""))
    info["Day"] = clean_day(result.get("day", ""))
    info["Status"] = str(result.get("status", ""))
    info["Summary"] = str(result.get("summary", ""))
    info["Tags"] = str(result.get("tags", ""))
    info["Manga"] = str(result.get("manga", "Yes"))
    info["Publisher"] = str(result.get("publisher", ""))
    if result.get("genre"):
        info["Genre"] = str(result.get("genre"))
    # Web 直接用结果 dict 的 web 字段（编辑/回读后可能被用户修改，不再按 source 拼 URL）
    if result.get("web"):
        info["Web"] = str(result.get("web"))


def create_xml_generator() -> XMLGenerator:
    """创建XML生成器实例
    
    Returns:
        XMLGenerator: XML生成器实例
    """
    return XMLGenerator()