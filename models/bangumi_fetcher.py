#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bangumi API封装模块 - 处理所有Bangumi相关功能

数据源直连（官方 api.bgm.tv / 镜像 api.bangumi.lol，无自动 failover）；
网页兜底跟随所选数据源。辅助逻辑拆分到 bangumi_* 子模块，本文件仅保留
BangumiFetcher 类并统一导出。
"""

import re
from typing import Dict, List, Optional
from urllib.parse import quote

import requests
from thefuzz import fuzz
from zhconv import convert
import urllib3

import config
from config import FUZZ_THRESHOLD, SHOW_TOP_N, TIMEOUT

# 禁用SSL警告（仅用于开发环境）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---- 子模块统一导出（旧 import 路径兼容，各模块见自身 docstring）----
from .bangumi_comicinfo import build_comicinfo
from .bangumi_genre import BANGUMI_GENRE_WHITELIST, extract_bangumi_genre
from .bangumi_source import (_ACTIVE_SOURCE, _WEB_BROWSER_UA, _api_base_for_source,
                             _web_mirror_from_api, get_active_bangumi_source,
                             set_active_bangumi_source)
from .bangumi_volume_filter import (_VOLUME_MARKER_RE, _filter_series_volumes,
                                    _has_volume_marker)
from .bangumi_web_parse import (_PERSON_LINK_RE, _WEB_AUTHOR_FIELD_RE,
                                _WEB_AUTHOR_TIPS, _parse_web_authors)

# author_utils 原模块级导出（包装方法委托对象，兼容外部引用）
from .author_utils import (extract_bangumi_authors,
                           extract_bangumi_authors_by_type, match_author)


class BangumiFetcher:
    def __init__(self, source: Optional[str] = None):
        """按数据源直连对应域名（默认跟随模块级当前源，官方 api.bgm.tv / 镜像 api.bangumi.lol）

        Args:
            source: 数据源标识（config.BANGUMI_SOURCE_OFFICIAL / _MIRROR）；
                    缺省用模块级当前源（由 gui 按用户选择设置）
        """
        # 动态读取模块级当前源（from import 会绑定旧值，见 set_active_bangumi_source）
        self._source = source or get_active_bangumi_source()
        self._base_url = _api_base_for_source(self._source)
        # 网页兜底域名由 API 域名派生，跟随同一数据源（官方 bgm.tv / 镜像 bangumi.lol）
        self._web_base = _web_mirror_from_api(self._base_url)

        self.session = requests.Session()
        self.session.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        # 从 config 模块读取 token（user_config.json 主源），设置保存后新建
        # fetcher 即可生效（from config import 会绑定旧值，故此处引用模块属性）
        if config.BANGUMI_ACCESS_TOKEN:
            self.session.headers["Authorization"] = f"Bearer {config.BANGUMI_ACCESS_TOKEN}"

        # 禁用SSL证书验证（解决HTTPS连接问题）
        self.session.verify = False

        # 网页作者兜底缓存：同一 subject_id 只抓取一次（实例内生效）
        self._web_authors_cache: Dict[int, List[str]] = {}
        # persons 端点缓存：同一 subject_id 只请求一次（实例内生效）
        self._persons_cache: Dict[int, List[Dict]] = {}

    def _request_json(self, method: str, path: str,
                      params: Optional[Dict] = None,
                      json_payload: Optional[Dict] = None) -> Dict:
        """按当前数据源直连对应 base_url 的 JSON 请求（无自动 failover）

        失败打印「Bangumi 镜像不可用」级别提示后立即抛出，不自动切换数据源；
        网络类错误不重试。

        Args:
            method: HTTP 方法（"GET"/"POST"）
            path: 以 / 开头的 API 路径（不含域名）
            params: 查询参数（可选）
            json_payload: JSON 请求体（可选）

        Returns:
            Dict: 响应 JSON

        Raises:
            requests.exceptions.RequestException: 网络/HTTP 错误（原样抛出）
        """
        try:
            response = self.session.request(
                method, self._base_url + path, params=params, json=json_payload,
                timeout=TIMEOUT, verify=False,
            )
            response.raise_for_status()
            return response.json()
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.HTTPError) as e:
            print(f"⚠️    Bangumi 镜像不可用 [{self._base_url}{path}]: {str(e)[:50]}")
            raise

    def search_manga(self, keyword: str, folder_info: Optional[Dict] = None) -> List[Dict]:
        """搜索漫画，返回所有匹配结果（前10个）

        统一走 v0 POST {base}/v0/search/subjects?limit=10（官方与镜像均支持），
        payload {"keyword": ..., "filter": {"type": [1]}}；直连所选数据源域名，
        不做自动 failover。series/platform/images 字段由 v0 POST 直接提供。
        """
        try:
            keyword_cn = convert(keyword, "zh-cn")
            path = "/v0/search/subjects"
            params = {"limit": SHOW_TOP_N}  # 1=书籍/漫画 type 过滤放 payload
            payload = {"keyword": keyword_cn, "filter": {"type": [1]}}
            data = self._request_json("POST", path, params=params, json_payload=payload)
            # v0 POST response: {"data": [...]} - real items in data
            results = [item for item in data.get("data", [])
                       if isinstance(item, dict)]

            # 逐条过滤：series=False 且名称带「卷号标记」的条目（系列的单卷）剔除；
            # 保留系列(series=True)、外传/原画集/设定集/一卷全(series=False 但无卷号标记)。
            # series 字段在搜索列表直接可用，无额外 API 请求，也不依赖结果数阈值。
            results = _filter_series_volumes(results)

            details_cache: Dict[int, Optional[Dict]] = {}  # 详情缓存：复用别名检查的详情，避免重复请求

            # 按作品名匹配度排序（忽略英文大小写）
            scored_results = []
            for item in results:
                title_cn = convert(item.get("name_cn", ""), "zh-cn")
                title_ori = convert(item.get("name", ""), "zh-cn")

                # 首先尝试主标题匹配
                main_score = max(
                    fuzz.ratio(title_cn.lower(), keyword_cn.lower()),
                    fuzz.partial_ratio(title_cn.lower(), keyword_cn.lower()),
                    fuzz.ratio(title_ori.lower(), keyword_cn.lower())
                )

                # 如果主标题匹配度不够，尝试匹配别名
                final_score = main_score
                if main_score < FUZZ_THRESHOLD:
                    # 获取作品详情以检查别名
                    try:
                        detail = self.get_manga_detail(item["id"])
                        details_cache[item["id"]] = detail
                        if detail:
                            # 从infobox中提取别名信息
                            infobox = detail.get("infobox", [])
                            for info_item in infobox:
                                if info_item.get("key") == "别名":
                                    aliases = info_item.get("value", [])
                                    if isinstance(aliases, list):
                                        for alias in aliases:
                                            if isinstance(alias, dict) and alias.get("v"):
                                                alias_text = convert(alias["v"], "zh-cn")
                                                alias_score = max(
                                                    fuzz.ratio(alias_text.lower(), keyword_cn.lower()),
                                                    fuzz.partial_ratio(alias_text.lower(), keyword_cn.lower())
                                                )
                                                if alias_score > final_score:
                                                    final_score = alias_score
                                                    print(f"💡 通过别名匹配: {alias_text} (匹配度: {final_score}%)")
                                    elif isinstance(aliases, str) and aliases.strip():
                                        alias_text = convert(aliases, "zh-cn")
                                        alias_score = max(
                                            fuzz.ratio(alias_text.lower(), keyword_cn.lower()),
                                            fuzz.partial_ratio(alias_text.lower(), keyword_cn.lower())
                                        )
                                        if alias_score > final_score:
                                            final_score = alias_score
                                            print(f"💡 通过别名匹配: {alias_text} (匹配度: {final_score}%)")
                                    break
                    except Exception as e:
                        print(f"⚠️   获取详情失败 [{item['id']}]: {str(e)[:30]}")

                if final_score >= FUZZ_THRESHOLD:
                    scored_results.append((final_score, item))

            # 按匹配度降序排列
            scored_results.sort(key=lambda x: x[0], reverse=True)

            api_results = [r[1] for r in scored_results[:SHOW_TOP_N]]

            # API 无结果时尝试网页搜索兜底
            if not api_results and folder_info:
                author = folder_info.get("author", "")
                aliases = folder_info.get("aliases", [])
                web_results = self._web_search_fallback(keyword, author, aliases)
                if web_results:
                    return web_results

            return api_results
        except Exception as e:
            print(f"🔴 搜索失败 [{keyword}]: {str(e)[:50]}")

            # API 异常时也尝试网页搜索兜底
            if folder_info:
                author = folder_info.get("author", "")
                aliases = folder_info.get("aliases", [])
                web_results = self._web_search_fallback(keyword, author, aliases)
                if web_results:
                    return web_results

            return []

    def _web_search_subject_ids(self, keyword: str, timeout: int = 10) -> list:
        """网页搜索 Bangumi，从搜索结果页提取 subject ID 列表

        跟随当前数据源：官方源→bgm.tv，镜像源→bangumi.lol（浏览器 UA 过
        Cloudflare）。失败静默降级返回空列表（API 搜索为主源，网页仅补充），
        不打印错误。
        """
        url = f"{self._web_base}/subject_search/{quote(keyword)}?cat=1"
        try:
            resp = self.session.get(url, timeout=timeout, verify=False,
                                    headers={"User-Agent": _WEB_BROWSER_UA})
            resp.raise_for_status()
            subject_ids = re.findall(r'href="/subject/(\d+)"', resp.text)
        except (requests.exceptions.RequestException, ValueError):
            return []
        seen = set()
        unique = []
        for sid in subject_ids:
            if sid not in seen:
                seen.add(sid)
                unique.append(sid)
        return unique

    def _web_search_fallback(self, keyword: str, author: str = "",
                              alt_keywords: list = None) -> List[Dict]:
        """网页搜索兜底策略：按优先级尝试多种搜索方式"""
        strategies = []

        # a. 书名直接搜索
        strategies.append(("书名", keyword))

        # b. 书名 + 作者名联合搜索
        if author and author != keyword:
            strategies.append(("书名+作者", f"{keyword} {author}"))

        # c. 别名搜索
        if alt_keywords:
            for alt in alt_keywords:
                if alt != keyword:
                    strategies.append(("别名", alt))

        # d. 去特殊符号再搜
        cleaned = re.sub(r'[★♪◆☆●◎◇□■△▲▽▼※〒→←↑↓♡♥]', '', keyword).strip()
        if cleaned and cleaned != keyword:
            strategies.append(("去除特殊符号", cleaned))

        for strategy_name, query in strategies:
            print(f"🔍 网页搜索 ({strategy_name}): {query}")
            ids = self._web_search_subject_ids(query)
            if not ids:
                continue
            results = []
            for sid in ids[:SHOW_TOP_N]:
                detail = self.get_manga_detail(int(sid))
                if detail:
                    results.append({
                        "id": int(sid),
                        "name": detail.get("name", ""),
                        "name_cn": detail.get("name_cn", ""),
                        "series": detail.get("series", False),  # 详情接口同样带 series，供统一过滤
                        "platform": detail.get("platform", ""),  # 详情接口同样带 platform，供弹窗「（漫画系列）」后缀渲染
                        "rating": detail.get("rating", {})
                    })
            # 与 API 搜索统一：逐条过滤 series=False 且名称带卷号标记的条目
            results = _filter_series_volumes(results)
            if results:
                print(f"✅ 网页搜索 ({strategy_name}) 找到 {len(results)} 个结果")
                return results
            else:
                print(f"⚠️  网页搜索 ({strategy_name}) 找到 ID 但获取详情失败")

        return []

    def get_manga_detail(self, subject_id: int) -> Optional[Dict]:
        """获取漫画详细信息（含作者、出版社等）

        走 v0 GET {base}/v0/subjects/{id}（官方/镜像均支持）；直连所选
        数据源域名，不做自动 failover。
        """
        try:
            path = f"/v0/subjects/{subject_id}"
            return self._request_json("GET", path)
        except requests.exceptions.RequestException as e:
            print(f"🔴 获取详情失败 [{subject_id}]: {str(e)[:50]}")
            return None

    def fetch_web_authors(self, subject_id: int) -> List[str]:
        """从 Bangumi 网页信息栏兜底提取作者（API infobox 无作者字段时使用）

        老条目（如 37953）API infobox 无「作者」字段，但网页版信息栏有
        `作者: <a href="/person/39">CLAMP</a>`。跟随当前数据源：官方源→
        bgm.tv，镜像源→bangumi.lol（浏览器 UA 过 Cloudflare）。带实例级
        缓存：同一 subject_id 只抓取一次；失败静默降级返回空列表（API
        infobox 作者为主源，网页仅补充），不打印错误。

        Args:
            subject_id: Bangumi 条目 ID

        Returns:
            List[str]: 作者名列表；无作者或失败返回空列表
        """
        if subject_id in self._web_authors_cache:
            return self._web_authors_cache[subject_id]
        url = f"{self._web_base}/subject/{subject_id}"
        try:
            resp = self.session.get(url, timeout=TIMEOUT, verify=False,
                                    headers={"User-Agent": _WEB_BROWSER_UA})
            resp.raise_for_status()
            # 响应头无 charset 时 requests 默认按 ISO-8859-1 解码导致中文乱码；
            # 页面实际为 UTF-8，显式指定编码后再解析作者字段
            resp.encoding = "utf-8"
            authors = _parse_web_authors(resp.text)
        except (requests.exceptions.RequestException, UnicodeError, ValueError):
            authors = []
        self._web_authors_cache[subject_id] = authors
        return authors

    def get_manga_persons(self, subject_id: int) -> List[Dict]:
        """获取条目人物列表（含 relation 职务字段），走 v0 GET {base}/v0/subjects/{id}/persons

        官方与镜像同路径；直连所选数据源域名，不做自动 failover。带实例级
        缓存：同一 subject_id 只请求一次；失败静默降级返回空列表（与
        fetch_web_authors 同一降级模式），不抛异常、不打印错误。

        Args:
            subject_id: Bangumi 条目 ID

        Returns:
            List[Dict]: 人物列表（每项含 name/relation/career/type 等）；
                        无人物或失败返回空列表
        """
        if subject_id in self._persons_cache:
            return self._persons_cache[subject_id]
        persons: List[Dict] = []
        path = f"/v0/subjects/{subject_id}/persons"
        limit, offset = 100, 0
        try:
            while True:
                resp = self.session.get(self._base_url + path,
                                        params={"limit": limit, "offset": offset},
                                        timeout=TIMEOUT, verify=False)
                resp.raise_for_status()
                payload = resp.json()
                # persons 端点返回裸 list（官方与镜像实测）；兼容 dict{"data": [...]} 形态
                if isinstance(payload, list):
                    items = [i for i in payload if isinstance(i, dict)]
                else:
                    items = [i for i in (payload.get("data") or []) if isinstance(i, dict)]
                persons.extend(items)
                if len(items) < limit or offset >= 400:  # 上限保护，防异常分页
                    break
                offset += limit
        except (requests.exceptions.RequestException, ValueError):
            persons = []  # 失败静默降级：与 fetch_web_authors 一致，不重试
        self._persons_cache[subject_id] = persons
        return persons

    def get_volume_dates(self, subject_id: int) -> Dict[str, str]:
        """逐卷单行本发售日 {卷号: "YYYY-MM-DD"}（委托 bangumi_volume_dates，实例级缓存）"""
        from .bangumi_volume_dates import collect_volume_dates
        return collect_volume_dates(self, subject_id)

    def extract_bangumi_authors(self, detail: Dict,
                                persons: Optional[List[Dict]] = None) -> List[str]:
        """包装方法：委托到 author_utils（persons 可选并入，跨端点合并）"""
        from .author_utils import extract_bangumi_authors as _extract
        return _extract(detail, persons)

    def extract_bangumi_authors_by_type(self, detail: Dict) -> Dict[str, List[str]]:
        """包装方法：委托到 author_utils"""
        from .author_utils import extract_bangumi_authors_by_type as _extract_by_type
        return _extract_by_type(detail)

    def match_author(self, folder_author: str, bangumi_authors: List[str]) -> bool:
        """包装方法：委托到 author_utils"""
        from .author_utils import match_author as _match
        return _match(folder_author, bangumi_authors)

    def extract_comicinfo(self, detail: Dict, folder_info: Dict) -> Dict:
        """提取 ComicInfo.xml 所需字段（委托到 bangumi_comicinfo.build_comicinfo）"""
        persons = []
        subject_id = detail.get("id") if detail else None
        if subject_id:
            try:
                persons = self.get_manga_persons(int(subject_id))
            except (TypeError, ValueError):
                persons = []
        return build_comicinfo(detail, folder_info, persons)
