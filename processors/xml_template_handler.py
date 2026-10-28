#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XML模板处理器模块 - 负责XML模板的创建和数据填充
"""

import re
from typing import Any, Dict

from config import COMICINFO_TEMPLATE, SHORT_STORY_TEMPLATE
from parsers.file_parser import is_short_story_folder


def _with_suffix(value: str, suffix: str) -> str:
    """幂等追加后缀：value 已带 suffix 时不重复追加（suffix 为空则原样返回）。"""
    if value and suffix and not str(value).endswith(suffix):
        return f"{value}{suffix}"
    return value


# 前导日期正则：从「开始」值（如 2000-05-30 或 1990-10-01 (1990年42号)）里
# 只取前导的 年-月-日，括号内的「1990年42号」等杂讯不参与匹配
_LEADING_DATE_RE = re.compile(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})")


def _infobox_value(detail: Dict[str, Any], key: str) -> str:
    """取 infobox 指定 key 的原始值串（value 为 list 时取首个非空 v）。"""
    for item in detail.get("infobox") or []:
        if item.get("key") != key:
            continue
        value = item.get("value", "")
        if isinstance(value, list):
            value = next((v.get("v", "") for v in value
                          if isinstance(v, dict) and v.get("v")), "")
        return str(value or "").strip()
    return ""


def resolve_release_date(detail: Dict[str, Any],
                         allow_ongoing_start: bool = False) -> str:
    """取日期原始串：顶层 date 优先，空则 infobox「发售日」兜底。

    章节型完结文件夹（is_chapter_version=True）且前两处都空时，才允许用
    infobox「开始」（连载起始日）再兜底——「开始」值形如 2000-05-30 或
    1990-10-01 (1990年42号)，用前导日期正则只取年月日（规整为 YYYY-MM-DD），
    括号内容不混入。单行本（V 标）等其它类型绝不用「开始」/「结束」——
    那是连载起止，不是单行本发售日。取不到返回空字符串。
    """
    if not detail:
        return ""
    date = str(detail.get("date") or "").strip()
    if date:
        return date
    sale_date = _infobox_value(detail, "发售日")
    if sale_date:
        return sale_date
    if not allow_ongoing_start:
        return ""
    start_raw = _infobox_value(detail, "开始")
    if not start_raw:
        return ""
    m = _LEADING_DATE_RE.search(start_raw)
    if not m:
        return ""
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


class XMLTemplateHandler:
    """XML模板处理器类"""
    
    def __init__(self):
        """初始化处理器"""
        pass
    
    def create_base_template(self, folder_info: Dict[str, Any], is_short_story: bool = False) -> Dict[str, Any]:
        """创建基础模板
        
        Args:
            folder_info: 文件夹信息字典
            is_short_story: 是否为短篇内容
            
        Returns:
            Dict[str, Any]: ComicInfo基础数据字典
        """
        # 根据 folder_info 自动判定短篇（宽松解析会写入 vol_type/vol_info/tags）
        is_short_story = is_short_story or is_short_story_folder(folder_info)

        if is_short_story:
            template = SHORT_STORY_TEMPLATE.copy()
        else:
            template = COMICINFO_TEMPLATE.copy()
        
        # 短篇完结：短篇的 Title 带「.短篇完结」后缀（幂等），Series 保持裸系列名
        title_display = _with_suffix(folder_info["series"], ".短篇完结") if is_short_story else folder_info["series"]
        
        # 填充基础信息（短篇保留 SHORT_STORY_TEMPLATE 的 Tags）
        template.update({
            "Title": title_display,
            "Series": folder_info["series"],
            "Writer": folder_info["author"],
            "Penciller": folder_info["author"],  # Writer/Penciller 单向补齐
            "Summary": "",
            "Tags": "短篇" if is_short_story else "",
        })
        
        # 设置卷数信息
        if is_short_story:
            template.update({
                "Count": "1",  # 短篇 = 一卷全
                "Volume": "",  # 短篇不显示Volume
                "Status": "Completed"  # 短篇默认已完成
            })
        else:
            # 已完结填写总卷数，连载中留空
            # 检查是否为已完结状态（complete标志为True或vol_info包含"全"）
            is_completed = folder_info["complete"] or ("全" in (folder_info.get("vol_info") or ""))
            volume_value = str(folder_info["total_volumes"]) if is_completed else ""
            template.update({
                "Count": volume_value,  # 系列总卷数
                "Status": "Completed" if is_completed else "Ongoing"
            })
        
        return template
    
    def create_bangumi_template(self, bangumi_data: Dict[str, Any], folder_info: Dict[str, Any],
                                volume_fetcher=None) -> Dict[str, Any]:
        """创建Bangumi数据模板
        
        Args:
            bangumi_data: Bangumi数据字典
            folder_info: 文件夹信息字典
            volume_fetcher: 可选 BangumiFetcher 实例；传入则额外挂逐卷发售日
                            base["_volume_dates"]（同一实例内缓存，扫描应复用同一个）
            
        Returns:
            Dict[str, Any]: 填充Bangumi数据的ComicInfo字典
        """
        template = self.create_base_template(folder_info)
        
        # 短篇完结：短篇的 Title 带后缀（覆盖 create_base_template 的结果），Series 保持裸系列名
        short_story_suffix = ".短篇完结" if is_short_story_folder(folder_info) else ""
        
        # 填充Bangumi数据
        bangumi_series = bangumi_data.get("name_cn") or bangumi_data.get("name") or folder_info["series"]
        template.update({
            "Title": _with_suffix(bangumi_series, short_story_suffix),
            "Series": bangumi_series,
            "Summary": bangumi_data.get("summary", ""),
            "Web": f"https://bgm.tv/subject/{bangumi_data['id']}" if bangumi_data.get("id") else ""
        })
        
        # 处理作者信息 - 使用BangumiFetcher的方法（infobox + persons 两端点合并）
        from models.bangumi_fetcher import BangumiFetcher, extract_bangumi_genre
        from models.author_utils import extract_bangumi_authors_merged
        from models.bangumi_genre import extract_bangumi_aliases
        fetcher = BangumiFetcher()

        # persons 端点每次都调（与 infobox 一起），失败静默返回 []
        subject_id = bangumi_data.get("id")
        persons = fetcher.get_manga_persons(int(subject_id)) if subject_id else []

        # 两端点合并分类：Writer=原作/脚本/监督/导演/原著，Penciller=作者/作画/插画，
        # Colorist=上色/色彩；同名跨端点去重（优先 infobox 映射）
        fields = extract_bangumi_authors_merged(bangumi_data, persons)
        story_authors = fields["Writer"]
        art_authors = fields["Penciller"]
        color_authors = fields["Colorist"]

        # 应用规则（Writer/Penciller 单向补齐：无画师时画师填原作，反之亦然）
        if not story_authors and not art_authors:
            # 没有任何作者信息，使用文件夹作者，同时填充Writer和Penciller
            template["Writer"] = folder_info["author"]
            template["Penciller"] = folder_info["author"]
        elif not story_authors and art_authors:
            # 只有绘画作者，同时填充Writer和Penciller
            template["Writer"] = ", ".join(art_authors)
            template["Penciller"] = ", ".join(art_authors)
        elif story_authors and not art_authors:
            # 只有故事作者，同时填充Writer和Penciller
            template["Writer"] = ", ".join(story_authors)
            template["Penciller"] = ", ".join(story_authors)
        else:
            # 同时有故事作者和绘画作者，分别放入对应字段
            template["Writer"] = ", ".join(story_authors)
            template["Penciller"] = ", ".join(art_authors)
        template["Colorist"] = ", ".join(color_authors)
        
        # 处理标签（复用 bangumi_fetcher 的 Genre 白名单 + Tags 截断逻辑）
        genre_str = extract_bangumi_genre(bangumi_data)
        template["Genre"] = genre_str

        if bangumi_data.get("tags"):
            genre_tags = set(genre_str.split(", "))
            # 截断 + 移除 Genre 命中词（与 bangumi_fetcher 的 Tags 逻辑一致）
            tags = [tag["name"] for tag in bangumi_data["tags"] if tag.get("count", 0) >= 2][:10]
            tags = [t for t in tags if t not in genre_tags]
            tags = [t for t in tags if not re.match(r"^\d+$", t)]  # 去掉纯数字（如 2024）
            remaining = list(tags)
            # 追加系列别名（infobox「别名」+ 日文原名）；与 Genre 词重复的别名同样剔除
            remaining.extend(a for a in extract_bangumi_aliases(bangumi_data) if a not in genre_tags)
            remaining.append(template.get("Status", ""))
            template["Tags"] = ", ".join(dict.fromkeys(remaining))
        
        # 处理年份信息（Year/Month/Day 单一入口；顶层 date 为空时 infobox「发售日」兜底；
        # 章节型完结（is_chapter_version）且前两处都空时才再用 infobox「开始」兜底）
        release_date = resolve_release_date(
            bangumi_data, allow_ongoing_start=bool(folder_info.get("is_chapter_version")))
        if release_date:
            template.update(self._extract_year_month(release_date))

        # 逐卷单行本发售日 {卷号: "YYYY-MM-DD"} 挂到 base；刷不到为 {}
        # （volume_fetcher 可选：不传则不加该键，行为与改动前完全一致；
        #   注意不能复用本函数内为取 persons 而新建的局部 fetcher —— 那是每次新建的
        #   persons 专用实例，没有跨调用缓存）
        if volume_fetcher is not None:
            from models.bangumi_volume_dates import attach_volume_dates
            attach_volume_dates(template, volume_fetcher, bangumi_data.get("id"))

        return template
    
    def create_local_template(self, folder_info: Dict[str, Any]) -> Dict[str, Any]:
        """创建本地数据模板（搜索失败时使用）
        
        Args:
            folder_info: 文件夹信息字典
            
        Returns:
            Dict[str, Any]: 使用本地数据的ComicInfo字典
        """
        template = self.create_base_template(folder_info)
        
        # 处理多作者情况（复用 author_utils._split_authors 统一拆分入口）
        from models.author_utils import _split_authors
        author = folder_info["author"]
        authors = _split_authors(author) or [author.strip()]

        # 当不确定作者角色时，将所有作者都放在Writer和Penciller字段中
        all_authors = ", ".join(authors)
        
        # 使用文件夹信息填充（Tags 沿用 create_base_template 的结果，短篇保留"短篇"）
        # 短篇完结：短篇的 Title 带后缀（覆盖 create_base_template 的结果），Series 保持裸系列名
        short_story_suffix = ".短篇完结" if is_short_story_folder(folder_info) else ""
        template.update({
            "Title": _with_suffix(folder_info["series"], short_story_suffix),
            "Series": folder_info["series"],
            "Writer": all_authors,  # Writer字段包含所有作者
            "Penciller": all_authors,  # Penciller字段也包含所有作者
            "Summary": "",
            "Web": "",
            "Rating": ""
        })
        
        return template
    
    def _extract_authors_from_infobox(self, infobox_data: list) -> Dict[str, str]:
        """从infobox数据中提取作者信息（与作者匹配逻辑保持一致）
        
        Args:
            infobox_data: infobox数据列表
            
        Returns:
            Dict[str, str]: 作者信息字典
        """
        authors = {
            "Writer": "",      # 编剧
            "Penciller": "",   # 画师
            "Inker": "",      # 墨线师
            "Colorist": "",   # 上色师
            "Letterer": "",   # 字母师
            "CoverArtist": "", # 封面画师
            "Editor": ""      # 编辑
        }
        
        # 收集所有作者信息
        all_authors = []
        
        # 定义作者类型映射（与作者匹配逻辑保持一致）
        author_type_mapping = {
            "原作": "Writer",      # 原作 → Writer
            "作者": "Penciller",   # 作者 → Penciller（Bangumi中的"作者"实际上是作画者）
            "作画": "Penciller",   # 作画 → Penciller
            "脚本": "Writer",      # 脚本 → Writer
            "监督": "Writer",      # 监督 → Writer
            "导演": "Writer",      # 导演 → Writer
            "原著": "Writer",      # 原著 → Writer
            "插画": "Penciller",   # 插画 → Penciller
            "墨线": "Inker",      # 墨线 → Inker
            "上色": "Colorist",   # 上色 → Colorist
            "字母": "Letterer",   # 字母 → Letterer
            "封面": "CoverArtist", # 封面 → CoverArtist
            "编辑": "Editor"      # 编辑 → Editor
        }
        
        for item in infobox_data:
            key = item.get("key", "")
            value = item.get("value", "")
            
            if key in author_type_mapping:
                target_field = author_type_mapping[key]
                
                # 处理不同类型的值格式
                if isinstance(value, list):
                    # 列表格式：提取所有作者名
                    for v in value:
                        if isinstance(v, dict) and v.get("v"):
                            author_name = v["v"].strip()
                            if author_name:
                                authors[target_field] = self._append_author(authors[target_field], author_name)
                                if author_name not in all_authors:
                                    all_authors.append(author_name)
                        elif isinstance(v, str):
                            author_name = v.strip()
                            if author_name:
                                authors[target_field] = self._append_author(authors[target_field], author_name)
                                if author_name not in all_authors:
                                    all_authors.append(author_name)
                elif isinstance(value, str):
                    # 字符串格式：直接添加
                    author_name = value.strip()
                    if author_name:
                        authors[target_field] = self._append_author(authors[target_field], author_name)
                        if author_name not in all_authors:
                            all_authors.append(author_name)
        
        # 应用作者分配规则
        # 规则1: 如果只有一个作者A，则Writer和Penciller都填A（ComicInfo XML 无 Author 字段）
        if len(all_authors) == 1:
            single_author = all_authors[0]
            authors["Writer"] = single_author
            authors["Penciller"] = single_author
        
        # 规则2: 如果只有Penciller没有Writer，则Writer也填Penciller（两个都填同一个人）
        elif authors["Penciller"] and not authors["Writer"]:
            authors["Writer"] = authors["Penciller"]

        # 兜底: Writer 和 Penciller 单向补齐（覆盖剩余分支，如只有 Writer 无 Penciller）
        if authors["Writer"] and not authors["Penciller"]:
            authors["Penciller"] = authors["Writer"]
        elif authors["Penciller"] and not authors["Writer"]:
            authors["Writer"] = authors["Penciller"]

        return authors
    
    def _extract_year_month(self, date_str: str) -> Dict[str, str]:
        """从日期字符串中提取年、月、日

        Args:
            date_str: 日期字符串（标准格式 YYYY-MM-DD；缺段时对应项为空串）

        Returns:
            Dict[str, str]: {"Year": 年, "Month": 月, "Day": 日}，取不到的项为空串
        """
        # 惰性导入：xml_generator 模块级 import 本模块，此处不能再反向模块级 import
        from processors.xml_generator import clean_day, clean_month, clean_year

        year_month = {"Year": "", "Month": "", "Day": ""}

        if date_str:
            # 尝试解析日期格式：YYYY-MM-DD（Year/Month/Day 再经清洗，防「年」等非数字字符）
            parts = date_str.split("-")
            if len(parts) >= 1:
                year_month["Year"] = clean_year(parts[0])
            if len(parts) >= 2:
                year_month["Month"] = clean_month(parts[1])
            if len(parts) >= 3:
                year_month["Day"] = clean_day(parts[2])

        return year_month
    
    def _append_author(self, current_authors: str, new_author: str) -> str:
        """追加作者到现有作者列表
        
        Args:
            current_authors: 当前作者列表
            new_author: 新作者
            
        Returns:
            str: 更新后的作者列表
        """
        if not current_authors:
            return new_author
        else:
            return f"{current_authors}, {new_author}"


def ensure_short_story_suffix(comic_info_base: Dict[str, Any],
                              folder_info: Dict[str, Any]) -> Dict[str, Any]:
    """短篇文件夹：确保 Title 带「.短篇完结」后缀（幂等，已带不重复），Series 保持裸系列名。

    manhuagui/comicvine 路径 create_base_template 后直接 update(detail)，
    detail 的裸 Series/Title 会覆盖 create_base_template 产出的带后缀 Title
    （create_bangumi_template 自带后缀逻辑，不走此函数）。此函数应在
    update(detail) 之后调用，把 Title 后缀统一补回。Series 不参与后缀，
    永远保持裸系列名（以 detail/folder 提供的裸名为准）。非短篇文件夹不做任何修改。

    Args:
        comic_info_base: ComicInfo 字典（原地修改）
        folder_info: 文件夹解析信息（is_short_story_folder 判定）

    Returns:
        传入的 comic_info_base（原地修改并返回，便于链式调用）
    """
    if comic_info_base and is_short_story_folder(folder_info):
        value = comic_info_base.get("Title")
        if value and not str(value).endswith(".短篇完结"):
            comic_info_base["Title"] = f"{value}.短篇完结"
    return comic_info_base


def create_xml_template_handler() -> XMLTemplateHandler:
    """创建XML模板处理器实例
    
    Returns:
        XMLTemplateHandler: XML模板处理器实例
    """
    return XMLTemplateHandler()