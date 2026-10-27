#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐卷单行本发售日抓取 - Bangumi 关联条目「单行本」→ 各卷 date

流程：GET /v0/subjects/{series_id}/subjects 取关联条目（实测返回裸 list）
→ 过滤 relation == "单行本" → 逐条 GET /v0/subjects/{vol_id} 取该卷 date
（顶层 date 为空则 infobox「发售日」兜底，复用 resolve_release_date）
→ {"1": "2010-03-17", "2": "2010-07-16", ...}（键为卷号 int 归一化字符串）。

卷号提取不到、或该卷无日期 → 跳过该条：绝不按顺序给无编号的卷硬派日期。
失败一律静默返回 {}（与 fetch_web_authors / get_manga_persons 同一降级风格，
不抛异常、不刷错误），调用方据此沿用系列级日期。
"""

import re
from typing import Dict, Optional

import requests

# 卷号提取优先级：括号数字 → 第N卷 → Vol N；每个模式取首个命中
_VOLUME_PATTERNS = (
    re.compile(r"[（(]\s*(\d+)\s*[)）]"),
    re.compile(r"第\s*(\d+)\s*[巻卷集册]"),
    re.compile(r"[Vv]ol\.?\s*(\d+)", re.IGNORECASE),
)

VOLUME_RELATION = "单行本"


def extract_volume_number(name: str) -> Optional[str]:
    """从条目名提取卷号（int 归一化后的字符串，去前导零）；取不到返回 None

    「進撃の巨人 (1)」→ "1"；「SLAM DUNK (01)」→ "1"；
    「海賊王の求婚」（无编号）→ None（不做顺序推断）。
    """
    text = str(name or "")
    for pattern in _VOLUME_PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                return str(int(match.group(1)))
            except ValueError:  # 理论上不可达：\d+ 必可 int
                continue
    return None


def _volume_release_date(fetcher, vol_id: int) -> str:
    """取单卷发售日（顶层 date 优先，infobox「发售日」兜底）；实例级缓存

    单卷详情失败静默返回 ""（不重试、不打印错误），由调用方跳过该卷。
    """
    cache = fetcher.__dict__.setdefault("_volume_detail_cache", {})
    if vol_id in cache:
        return cache[vol_id]
    date = ""
    try:
        detail = fetcher._request_json("GET", f"/v0/subjects/{vol_id}")
    except (requests.exceptions.RequestException, ValueError):
        detail = None
    if isinstance(detail, dict):
        from processors.xml_template_handler import resolve_release_date
        date = resolve_release_date(detail)
    cache[vol_id] = date
    return date


def collect_volume_dates(fetcher, subject_id: int) -> Dict[str, str]:
    """取系列下各卷单行本发售日 {卷号: YYYY-MM-DD}；实例级缓存

    同一 series 只请求一次（关联列表 + 每卷详情各一次，详情按 id 去重）。
    失败静默降级：关联列表失败返回 {}，单卷详情失败跳过该卷。
    """
    cache = fetcher.__dict__.setdefault("_volume_dates_cache", {})
    if subject_id in cache:
        return cache[subject_id]

    dates: Dict[str, str] = {}
    try:
        payload = fetcher._request_json("GET", f"/v0/subjects/{subject_id}/subjects")
    except (requests.exceptions.RequestException, ValueError):
        payload = None
    items = payload if isinstance(payload, list) else (payload or {}).get("data") or []

    for item in items:
        if not isinstance(item, dict) or item.get("relation") != VOLUME_RELATION:
            continue
        volume = extract_volume_number(item.get("name") or item.get("name_cn") or "")
        vol_id = item.get("id")
        if not volume or volume in dates or not vol_id:
            continue
        try:
            date = _volume_release_date(fetcher, int(vol_id))
        except (TypeError, ValueError):
            continue
        if date:
            dates[volume] = date

    cache[subject_id] = dates
    return dates


def attach_volume_dates(comic_info_base: Optional[Dict], fetcher,
                        subject_id) -> None:
    """comic_info_base 构建后挂 _volume_dates（刷不到就是 {}）

    结果侧（result_builder）据此逐卷填 Year/Month/Day：命中用本卷日期，
    未命中沿用系列级日期（= 系列 date，通常即第 1 卷日期）。
    """
    if comic_info_base is None:
        return
    dates: Dict[str, str] = {}
    try:
        if fetcher is not None and subject_id is not None:
            dates = collect_volume_dates(fetcher, int(subject_id))
    except (TypeError, ValueError, AttributeError):
        dates = {}
    comic_info_base["_volume_dates"] = dates
