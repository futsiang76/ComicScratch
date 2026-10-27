#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
匹配失败处理器模块 - 负责处理搜索失败和匹配失败的流程

使用timeout_handler模块统一管理超时逻辑。
支持 GUI 模式（通过 gui_bridge）和控制台模式。
"""

from typing import Any, Dict, List, Optional

from config import AUTHOR_MATCH_THRESHOLD
from models.bangumi_fetcher import BangumiFetcher
from processors.search_handler import SearchHandler
from processors.interaction_handler import InteractionHandler
from processors.xml_template_handler import XMLTemplateHandler
from processors.timeout_handler import TimeoutHandler
from processors.choice_handlers import create_choice_handlers


class MatchFailureHandler:
    """匹配失败处理器类"""

    def __init__(self, fetcher: BangumiFetcher, timeout_handler: Optional[TimeoutHandler] = None,
                 gui_bridge: Optional[Any] = None):
        """初始化匹配失败处理器

        Args:
            fetcher: Bangumi获取器实例
            timeout_handler: 超时处理器实例，None则创建新的
            gui_bridge: GUI 对话框桥接器（DialogBridge实例），为None时使用 console input()
        """
        self.fetcher = fetcher
        self.timeout_handler = timeout_handler or TimeoutHandler()
        self.search_handler = SearchHandler(fetcher)
        self.interaction_handler = InteractionHandler(self.timeout_handler, gui_bridge)
        self.template_handler = XMLTemplateHandler()
        self.choice_handlers = create_choice_handlers(self.fetcher)
        self.gui_bridge = gui_bridge

    def handle_search_failure(self, folder_info: Dict, alt_keywords: List[str],
                            depth: int = 0) -> Dict:
        """处理搜索失败流程

        Args:
            folder_info: 文件夹信息
            alt_keywords: 别名关键词列表
            depth: 当前深度

        Returns:
            Dict: 处理结果
        """
        print(f"{'  ' * depth}⚠️  进入搜索失败处理流程")

        # 处理用户选择
        result = self.interaction_handler.handle_search_failure(folder_info, alt_keywords, depth)

        choice = result.get("choice")

        if choice == "timeout":
            comic_info_base = self.template_handler.create_local_template(folder_info)
            return {
                "comic_info_base": comic_info_base,
                "selected_result": None,
                "skip_files": False
            }
        elif choice == "1":
            # GUI 模式下，ID 已在对话框中收集
            if self.gui_bridge and result.get("_gui_value"):
                return self._handle_id_search_with_value(folder_info, result["_gui_value"], depth)
            return self._handle_id_search(folder_info, depth)
        elif choice == "2":
            # GUI 模式下，关键词已在对话框中收集
            if self.gui_bridge and result.get("_gui_value"):
                return self._handle_manual_search_with_value(folder_info, result["_gui_value"], depth)
            return self._handle_manual_search(folder_info, depth)
        elif choice == "local_write":
            return self._handle_local_write(folder_info, depth)
        else:
            return {
                "comic_info_base": None,
                "selected_result": None,
                "skip_files": True
            }
    
    def handle_no_author_match(self, folder_info: Dict, alt_keywords: List[str], 
                              depth: int = 0) -> Dict:
        """处理无作者匹配结果的情况
        
        Args:
            folder_info: 文件夹信息
            alt_keywords: 别名关键词列表
            depth: 当前深度
            
        Returns:
            Dict: 处理结果
        """
        print(f"{'  ' * depth}⚠️  未找到作者匹配的结果，进入搜索失败流程")
        return self.handle_search_failure(folder_info, alt_keywords, depth)
    
    def _handle_id_search(self, folder_info: Dict, depth: int = 0) -> Dict:
        """处理按ID查找

        Args:
            folder_info: 文件夹信息
            depth: 当前深度

        Returns:
            Dict: 处理结果
        """
        # 使用choice_handlers处理ID搜索
        id_input = self.interaction_handler.get_id_input(depth)
        if id_input:
            return self._handle_id_search_with_value(folder_info, id_input, depth)

        # ID查找失败，使用本地数据
        comic_info_base = self.template_handler.create_local_template(folder_info)
        return {
            "comic_info_base": comic_info_base,
            "selected_result": None,
            "skip_files": True
        }

    def _handle_id_search_with_value(self, folder_info: Dict, id_value: str,
                                     depth: int = 0) -> Dict:
        """使用已获取的 ID 值进行查找（GUI 模式复用）

        Args:
            folder_info: 文件夹信息
            id_value: Bangumi ID 字符串
            depth: 当前深度

        Returns:
            Dict: 处理结果
        """
        selected_result, success = self.choice_handlers.handle_id_search(id_value, depth)
        if success and selected_result:
            detail = self.fetcher.get_manga_detail(selected_result["id"])
            if detail:
                comic_info_base = self.template_handler.create_bangumi_template(detail, folder_info, self.fetcher)
                return {
                    "comic_info_base": comic_info_base,
                    "selected_result": selected_result,
                    "skip_files": False
                }

        comic_info_base = self.template_handler.create_local_template(folder_info)
        return {
            "comic_info_base": comic_info_base,
            "selected_result": None,
            "skip_files": True
        }

    def _handle_manual_search(self, folder_info: Dict, depth: int = 0) -> Dict:
        """处理手动关键词搜索

        Args:
            folder_info: 文件夹信息
            depth: 当前深度

        Returns:
            Dict: 处理结果
        """
        search_results = self.interaction_handler.handle_manual_search(self.fetcher, depth)
        if search_results:
            return self._handle_manual_search_results(search_results, folder_info, depth)

        comic_info_base = self.template_handler.create_local_template(folder_info)
        return {
            "comic_info_base": comic_info_base,
            "selected_result": None,
            "skip_files": False
        }

    def _handle_manual_search_with_value(self, folder_info: Dict, keyword: str,
                                         depth: int = 0) -> Dict:
        """使用已获取的关键词进行搜索（GUI 模式复用）

        Args:
            folder_info: 文件夹信息
            keyword: 搜索关键词
            depth: 当前深度

        Returns:
            Dict: 处理结果
        """
        print(f"{'  ' * depth}🔍 使用关键词搜索: {keyword}")
        search_results = self.fetcher.search_manga(keyword, folder_info)
        if search_results:
            print(f"{'  ' * depth}✅ 使用关键词 '{keyword}' 找到 {len(search_results)} 个结果")
            return self._handle_manual_search_results(search_results, folder_info, depth)

        print(f"{'  ' * depth}❌ 关键词 '{keyword}' 未找到结果")
        comic_info_base = self.template_handler.create_local_template(folder_info)
        return {
            "comic_info_base": comic_info_base,
            "selected_result": None,
            "skip_files": False
        }

    def _handle_manual_search_results(self, search_results: List[Dict],
                                      folder_info: Dict, depth: int = 0) -> Dict:
        """处理手动搜索的结果

        Args:
            search_results: 搜索结果列表
            folder_info: 文件夹信息
            depth: 当前深度

        Returns:
            Dict: 处理结果
        """
        matching_results = self.search_handler.filter_matching_results(
            search_results, folder_info, AUTHOR_MATCH_THRESHOLD
        )

        if len(matching_results) == 0:
            comic_info_base = self.template_handler.create_local_template(folder_info)
            return {"comic_info_base": comic_info_base, "selected_result": None, "skip_files": False}
        elif len(matching_results) == 1:
            selected_result = matching_results[0]
            print(f"{'  ' * depth}✅ 手动搜索匹配成功: {selected_result.get('name_cn') or selected_result.get('name')}")
            detail = self.fetcher.get_manga_detail(selected_result["id"])
            if detail:
                comic_info_base = self.template_handler.create_bangumi_template(detail, folder_info, self.fetcher)
                return {"comic_info_base": comic_info_base, "selected_result": selected_result, "skip_files": False}
            else:
                comic_info_base = self.template_handler.create_local_template(folder_info)
                return {"comic_info_base": comic_info_base, "selected_result": None, "skip_files": False}
        else:
            print(f"{'  ' * depth}⚠️  找到 {len(matching_results)} 个作者匹配的结果，需要手动选择")
            from processors.selector_handler import create_selector_handler
            selector_handler = create_selector_handler(gui_bridge=self.gui_bridge)
            selected_result = selector_handler.manual_select(matching_results, folder_info, [])

            if selected_result is None:
                comic_info_base = self.template_handler.create_local_template(folder_info)
                return {"comic_info_base": comic_info_base, "selected_result": None, "skip_files": False}
            elif isinstance(selected_result, str) and selected_result == 'use_local_info':
                comic_info_base = self.template_handler.create_local_template(folder_info)
                return {"comic_info_base": comic_info_base, "selected_result": None, "skip_files": False}
            elif isinstance(selected_result, dict) and "id" in selected_result:
                detail = self.fetcher.get_manga_detail(selected_result["id"])
                if detail:
                    comic_info_base = self.template_handler.create_bangumi_template(detail, folder_info, self.fetcher)
                    return {"comic_info_base": comic_info_base, "selected_result": selected_result, "skip_files": False}
                else:
                    comic_info_base = self.template_handler.create_local_template(folder_info)
                    return {"comic_info_base": comic_info_base, "selected_result": None, "skip_files": False}
            else:
                comic_info_base = self.template_handler.create_local_template(folder_info)
                return {"comic_info_base": comic_info_base, "selected_result": None, "skip_files": False}
    
    def _handle_local_write(self, folder_info: Dict, depth: int = 0) -> Dict:
        """处理按本地解析信息写入
        
        Args:
            folder_info: 文件夹信息
            depth: 当前深度
            
        Returns:
            Dict: 处理结果
        """
        # 使用choice_handlers处理本地写入
        local_data, success = self.choice_handlers.handle_local_write(folder_info, depth)
        
        if success:
            # 创建本地模板
            comic_info_base = self.template_handler.create_local_template(folder_info)
            return {
                "comic_info_base": comic_info_base,
                "selected_result": None,
                "skip_files": False
            }
        else:
            # 本地写入失败，使用默认的本地模板
            comic_info_base = self.template_handler.create_local_template(folder_info)
            return {
                "comic_info_base": comic_info_base,
                "selected_result": None,
                "skip_files": False
            }
    
    def handle_timeout_fallback(self, folder_info: Dict, depth: int = 0) -> Dict:
        """处理超时回退到本地数据的情况
        
        Args:
            folder_info: 文件夹信息
            depth: 当前深度
            
        Returns:
            Dict: 处理结果
        """
        print(f"{'  ' * depth}⏰ 等待超时，自动使用本地文件夹解析结果")
        comic_info_base = self.template_handler.create_local_template(folder_info)
        return {
            "comic_info_base": comic_info_base,
            "selected_result": None,
            "skip_files": False  # 这里应该是False，因为生成了本地数据需要处理文件
        }
    
    def handle_manual_timeout(self, folder_info: Dict, depth: int = 0) -> Dict:
        """处理手动选择超时的情况
        
        Args:
            folder_info: 文件夹信息
            depth: 当前深度
            
        Returns:
            Dict: 处理结果
        """
        print(f"{'  ' * depth}⏰ 手动选择超时或跳过，使用本地文件夹解析结果")
        comic_info_base = self.template_handler.create_local_template(folder_info)
        print(f"{'  ' * depth}✅ 自动使用文件夹解析信息")
        
        return {
            "comic_info_base": comic_info_base,
            "selected_result": None,
            "skip_files": False
        }


def create_match_failure_handler(fetcher: BangumiFetcher,
                                  timeout_handler: Optional[TimeoutHandler] = None,
                                  gui_bridge: Optional[Any] = None) -> MatchFailureHandler:
    """创建匹配失败处理器实例

    Args:
        fetcher: Bangumi获取器实例
        timeout_handler: 超时处理器实例，None则创建新的
        gui_bridge: GUI 对话框桥接器实例

    Returns:
        MatchFailureHandler: 匹配失败处理器实例
    """
    return MatchFailureHandler(fetcher, timeout_handler, gui_bridge)