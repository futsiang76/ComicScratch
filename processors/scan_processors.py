#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量处理器模块 - 主流程控制器

使用新的模块化组件：
- search_handler: 搜索处理器
- interaction_handler: 交互处理器  
- xml_template_handler: XML模板处理器
- file_handler: 文件处理器
- match_failure_handler: 匹配失败处理器
- folder_recursive_handler: 文件夹递归处理器
- timeout_handler: 超时处理器
"""

import os
import platform
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

from config import AUTHOR_MATCH_THRESHOLD, FUZZ_THRESHOLD, WAITING_TIME
from models.bangumi_fetcher import BangumiFetcher
from processors.folder_recursive_handler import create_folder_recursive_handler
from processors.interaction_handler import create_interaction_handler
from processors.irregular_folder_handler import (
    is_irregular_folder, process_irregular_folder,
    process_irregular_folder_files)
from processors.match_failure_handler import create_match_failure_handler
from processors.search_handler import create_search_handler
from processors.selector_handler import create_selector_handler
from processors.timeout_handler import create_timeout_handler
from processors.xml_template_handler import create_xml_template_handler
from processors.zip_handler import create_file_handler
from .utils import check_all_files_have_xml, process_short_story_folder, process_xml_modify_folder

def process_normal_folder(folder_path: str, folder_info: Dict, fetcher, depth: int = 0,
                         gui_callback: Optional[Callable] = None) -> Dict:
    """处理普通漫画文件夹
    
    Args:
        folder_path: 文件夹路径
        folder_info: 文件夹信息
        fetcher: Bangumi获取器
        depth: 当前深度
        gui_callback: GUI 交互回调函数，签名为 gui_callback(action, **params) -> Any
                      为 None 时使用 console input() 交互
        
    Returns:
        Dict: 处理结果
    """
    # 创建处理器实例
    search_handler = create_search_handler(fetcher)
    match_failure_handler = create_match_failure_handler(fetcher)
    template_handler = create_xml_template_handler()
    
    # 1. 提取搜索关键词（仅系列名）
    search_keywords, alt_keywords = search_handler.extract_search_keywords(folder_path, folder_info)
    
    # 2. 执行搜索（先使用系列名，如果失败则自动尝试别名）
    search_results = search_handler.search_with_keywords(search_keywords, folder_info)
    
    if not search_results and alt_keywords:
        # 系列名搜索失败，自动尝试别名搜索
        print(f"{'  ' * depth}🔄 系列名搜索失败，自动尝试别名搜索...")
        for alt_keyword in alt_keywords:
            print(f"{'  ' * depth}🔍 使用别名搜索: {alt_keyword}")
            alt_results = search_handler.search_with_keywords([alt_keyword], folder_info)
            if alt_results:
                search_results = alt_results
                print(f"{'  ' * depth}✅ 使用别名 '{alt_keyword}' 找到 {len(search_results)} 个结果")
                break
            else:
                print(f"{'  ' * depth}❌ 别名 '{alt_keyword}' 未找到结果")
    
    if not search_results:
        # 所有搜索都失败处理
        
        # 无人值守模式：搜索失败时直接跳过
        from config import AUTO_TURBO_MATCH
        if AUTO_TURBO_MATCH == 1:
            print(f"{'  ' * depth}🚀 无人值守模式：未找到搜索结果，跳过此系列")
            return {
                "comic_info_base": None,
                "selected_result": None,
                "skip_files": True
            }
        
        print(f"{'  ' * depth}❌ 未找到系列名 '{folder_info['series']}' 和别名的搜索结果")
        
        # GUI 模式：使用回调获取用户选择
        if gui_callback:
            return _handle_search_failure_gui(folder_info, alt_keywords, fetcher,
                                              template_handler, search_handler,
                                              gui_callback, depth)
        
        return match_failure_handler.handle_search_failure(folder_info, alt_keywords, depth)
    
    # 3. 检查搜索结果中是否有作者匹配
    has_author_match = search_handler.has_author_match(search_results, folder_info)
    
    if not has_author_match and alt_keywords:
        # 作者匹配失败，自动尝试别名搜索
        print(f"{'  ' * depth}🔄 作者匹配失败，自动尝试别名搜索...")
        for alt_keyword in alt_keywords:
            print(f"{'  ' * depth}🔍 使用别名搜索: {alt_keyword}")
            alt_results = search_handler.search_with_keywords([alt_keyword], folder_info)
            if alt_results:
                # 检查别名搜索结果中是否有作者匹配
                alt_has_author_match = search_handler.has_author_match(alt_results, folder_info)
                if alt_has_author_match:
                    search_results = alt_results
                    print(f"{'  ' * depth}✅ 使用别名 '{alt_keyword}' 找到作者匹配的结果")
                    has_author_match = True
                    break
                else:
                    print(f"{'  ' * depth}❌ 别名 '{alt_keyword}' 搜索结果中未找到作者匹配")
            else:
                print(f"{'  ' * depth}❌ 别名 '{alt_keyword}' 未找到结果")
    
    # 4. 过滤匹配结果（作者匹配才做作者过滤，否则直接走放宽）
    if has_author_match:
        matching_results = search_handler.filter_matching_results(search_results, folder_info, AUTHOR_MATCH_THRESHOLD)
    else:
        # 作者不匹配：不走作者过滤，交给下方放宽逻辑
        matching_results = []
    
    # 作者过滤 0 结果但搜索有结果：放宽为系列名匹配前5个（漫画系列优先）
    if not matching_results and search_results:
        from models.author_utils import relax_author_filter
        matching_results = relax_author_filter(search_results)
        print(f"{'  ' * depth}💡 作者匹配失败，放宽为系列名匹配结果 {len(matching_results)} 个（漫画系列优先）")

    # 5. 根据匹配结果数量决定处理方式
    if len(matching_results) == 0:
        # 没有作者匹配结果，进入搜索失败流程
        
        # 无人值守模式：无匹配结果时直接跳过
        from config import AUTO_TURBO_MATCH
        if AUTO_TURBO_MATCH == 1:
            print(f"{'  ' * depth}🚀 无人值守模式：无匹配结果，跳过此系列")
            return {
                "comic_info_base": None,
                "selected_result": None,
                "skip_files": True
            }
        
        # GUI 模式：使用回调获取用户选择
        if gui_callback:
            return _handle_search_failure_gui(folder_info, alt_keywords, fetcher,
                                              template_handler, search_handler,
                                              gui_callback, depth)
        
        return match_failure_handler.handle_no_author_match(folder_info, alt_keywords, depth)
    elif len(matching_results) == 1:
        # 只有一个匹配结果
        if gui_callback:
            from config import AUTO_TURBO_MATCH
            if AUTO_TURBO_MATCH == 1:
                # 无人值守模式：唯一匹配直接自动确认，不弹窗
                selected_result = matching_results[0]
            else:
                # GUI模式：让用户确认搜索结果，或按ID搜索
                selected_result = gui_callback('select_result',
                                               search_results=matching_results,
                                               folder_info=folder_info,
                                               alt_keywords=alt_keywords)
                if selected_result is None:
                    return {"comic_info_base": None, "selected_result": None, "skip_files": True}
                elif selected_result == 'use_local_info':
                    comic_info_base = template_handler.create_local_template(folder_info)
                    return {"comic_info_base": comic_info_base, "selected_result": None, "skip_files": False}
        else:
            # CLI模式：自动选择
            selected_result = matching_results[0]
        print(f"{'  ' * depth}  ✅ 自动匹配成功: {selected_result.get('name_cn') or selected_result.get('name')} (ID: {selected_result['id']})")
        
        # 获取详细信息
        detail = fetcher.get_manga_detail(selected_result["id"])
        comic_info_base = template_handler.create_bangumi_template(detail, folder_info, fetcher)
        
        return {
            "comic_info_base": comic_info_base,
            "selected_result": selected_result,
            "skip_files": False
        }
    else:
        # 多个匹配结果，需要用户手动选择
        
        # 无人值守模式：多个匹配结果时直接跳过
        from config import AUTO_TURBO_MATCH
        if AUTO_TURBO_MATCH == 1:
            print(f"{'  ' * depth}🚀 无人值守模式：找到 {len(matching_results)} 个匹配结果，跳过此系列")
            return {
                "comic_info_base": None,
                "selected_result": None,
                "skip_files": True
            }
        print(f"{'  ' * depth}⚠️  找到 {len(matching_results)} 个作者匹配的结果，需要手动选择")
        print(f"{'  ' * depth}💡 文件夹作者: {folder_info['author']}")
        
        # GUI 模式：使用回调获取用户选择
        if gui_callback:
            selected_result = gui_callback('select_result',
                                           search_results=matching_results,
                                           folder_info=folder_info,
                                           alt_keywords=alt_keywords)
        else:
            # 创建选择器处理器（控制台模式）
            selector_handler = create_selector_handler()
            selected_result = selector_handler.manual_select(matching_results, folder_info, alt_keywords)
        
        if selected_result is None:
            # 用户选择'q'跳过，直接返回跳过
            return {
                "comic_info_base": None,
                "selected_result": None,
                "skip_files": True
            }
        elif selected_result == 'use_local_info':
            # 用户选择'l'使用本地信息
            comic_info_base = template_handler.create_local_template(folder_info)
            return {
                "comic_info_base": comic_info_base,
                "selected_result": None,
                "skip_files": False
            }
        else:
            # 正常选择，使用Bangumi信息
            # 获取详细信息
            detail = fetcher.get_manga_detail(selected_result["id"])
            comic_info_base = template_handler.create_bangumi_template(detail, folder_info, fetcher)
            
            return {
                "comic_info_base": comic_info_base,
                "selected_result": selected_result,
                "skip_files": False
            }


def _handle_search_failure_gui(folder_info: Dict, alt_keywords: List[str], fetcher,
                               template_handler, search_handler,
                               gui_callback: Callable, depth: int = 0) -> Dict:
    """GUI 模式下处理搜索失败/无匹配的交互流程

    通过 gui_callback 弹出对话框让用户选择：
    - 按 Bangumi ID 查找
    - 自定义关键词搜索
    - 仅使用本地信息
    - 跳过此系列

    Returns:
        Dict: 处理结果，与 process_normal_folder 返回格式一致
    """
    indent = '  ' * depth

    # 弹出选项对话框
    choice = gui_callback('search_failure',
                          folder_info=folder_info,
                          alt_keywords=alt_keywords)

    action = choice.get('action', 'skip')
    value = choice.get('value')

    if action == 'id_search':
        # 按 Bangumi ID 查找
        try:
            subject_id = int(value)
        except (ValueError, TypeError):
            print(f"{indent}❌ ID 格式错误")
            comic_info_base = template_handler.create_local_template(folder_info)
            return {"comic_info_base": comic_info_base, "selected_result": None, "skip_files": True}

        detail = fetcher.get_manga_detail(subject_id)
        if detail:
            result = {"id": subject_id, "name": detail.get("name", ""),
                      "name_cn": detail.get("name_cn", ""),
                      "rating": detail.get("rating", {})}
            print(f"{indent}✅ ID 查找成功: {result.get('name_cn') or result.get('name')}")
            comic_info_base = template_handler.create_bangumi_template(detail, folder_info, fetcher)
            return {"comic_info_base": comic_info_base, "selected_result": result, "skip_files": False}
        else:
            print(f"{indent}❌ 未找到 ID 为 {subject_id} 的作品，使用本地信息")
            comic_info_base = template_handler.create_local_template(folder_info)
            return {"comic_info_base": comic_info_base, "selected_result": None, "skip_files": True}

    elif action == 'keyword_search':
        # 自定义关键词搜索
        print(f"{indent}🔍 使用关键词搜索: {value}")
        search_results = fetcher.search_manga(value)
        if not search_results:
            print(f"{indent}❌ 关键词 '{value}' 未找到结果，使用本地信息")
            comic_info_base = template_handler.create_local_template(folder_info)
            return {"comic_info_base": comic_info_base, "selected_result": None, "skip_files": False}

        print(f"{indent}✅ 关键词 '{value}' 找到 {len(search_results)} 个结果")

        # 过滤匹配结果
        matching_results = search_handler.filter_matching_results(
            search_results, folder_info, AUTHOR_MATCH_THRESHOLD)

        if len(matching_results) == 0:
            print(f"{indent}⚠️ 无作者匹配结果，使用本地信息")
            comic_info_base = template_handler.create_local_template(folder_info)
            return {"comic_info_base": comic_info_base, "selected_result": None, "skip_files": False}
        elif len(matching_results) == 1:
            selected_result = matching_results[0]
            if gui_callback:
                # GUI模式：让用户确认搜索结果
                confirmed = gui_callback('select_result',
                                         search_results=matching_results,
                                         folder_info=folder_info)
                if confirmed is None:
                    return {"comic_info_base": None, "selected_result": None, "skip_files": True}
                elif confirmed == 'use_local_info':
                    comic_info_base = template_handler.create_local_template(folder_info)
                    return {"comic_info_base": comic_info_base, "selected_result": None, "skip_files": False}
                selected_result = confirmed
            print(f"{indent}✅ 手动搜索匹配成功: {selected_result.get('name_cn') or selected_result.get('name')}")
            detail = fetcher.get_manga_detail(selected_result["id"])
            if detail:
                comic_info_base = template_handler.create_bangumi_template(detail, folder_info, fetcher)
                return {"comic_info_base": comic_info_base, "selected_result": selected_result, "skip_files": False}
            else:
                comic_info_base = template_handler.create_local_template(folder_info)
                return {"comic_info_base": comic_info_base, "selected_result": None, "skip_files": False}
        else:
            # 多个结果，再次使用选择对话框
            selected_result = gui_callback('select_result',
                                           search_results=matching_results,
                                           folder_info=folder_info,
                                           alt_keywords=[])
            if selected_result is None:
                comic_info_base = template_handler.create_local_template(folder_info)
                return {"comic_info_base": comic_info_base, "selected_result": None, "skip_files": False}
            elif selected_result == 'use_local_info':
                comic_info_base = template_handler.create_local_template(folder_info)
                return {"comic_info_base": comic_info_base, "selected_result": None, "skip_files": False}
            elif isinstance(selected_result, dict) and "id" in selected_result:
                detail = fetcher.get_manga_detail(selected_result["id"])
                if detail:
                    comic_info_base = template_handler.create_bangumi_template(detail, folder_info, fetcher)
                    return {"comic_info_base": comic_info_base, "selected_result": selected_result, "skip_files": False}
                else:
                    comic_info_base = template_handler.create_local_template(folder_info)
                    return {"comic_info_base": comic_info_base, "selected_result": None, "skip_files": False}
            else:
                comic_info_base = template_handler.create_local_template(folder_info)
                return {"comic_info_base": comic_info_base, "selected_result": None, "skip_files": False}

    elif action == 'use_local_info':
        # 仅使用本地信息
        print(f"{indent}📋 使用本地文件夹解析信息")
        comic_info_base = template_handler.create_local_template(folder_info)
        return {"comic_info_base": comic_info_base, "selected_result": None, "skip_files": False}

    else:  # action == 'skip'
        print(f"{indent}⏭️ 用户跳过此系列")
        return {"comic_info_base": None, "selected_result": None, "skip_files": True}


def process_comic_folder(folder_path: str, folder_info: Dict, fetcher, file_handler, 
                        auto_processed, manual_processed, skipped, depth: int = 0, manga_value: Optional[str] = None) -> Tuple[int, int, int, int, int]:
    """处理单个漫画文件夹
    
    Args:
        folder_path: 文件夹路径
        folder_info: 文件夹信息
        fetcher: Bangumi获取器
        file_handler: 文件处理器
        auto_processed: 自动处理计数
        manual_processed: 手动处理计数
        skipped: 跳过计数
        depth: 当前深度
        manga_value: Manga字段值（"Yes"或"No"），为None时使用input询问
        
    Returns:
        Tuple[int, int, int, int, int]: (auto_processed, manual_processed, skipped, total_files, success_files)
    """
    total_files = 0
    success_files = 0
    
    # 导入配置
    from config import MODE_SKIP_XMLEXIST

    # 高速模式：在解析文件夹前先检查所有文件是否都已包含XML
    if MODE_SKIP_XMLEXIST == 1:
        all_files_have_xml = check_all_files_have_xml(folder_path)
        if all_files_have_xml:
            print(f"{'  ' * depth}⏭️  高速模式：文件夹下所有文件已包含XML，跳过整个文件夹")
            skipped += 1
            return auto_processed, manual_processed, skipped, total_files, success_files
    
    # 修正模式：只处理有XML的文件夹，并从XML读取元数据（只读不写）
    if MODE_SKIP_XMLEXIST == 2:
        all_files_have_xml = check_all_files_have_xml(folder_path)
        if not all_files_have_xml:
            print(f"{'  ' * depth}⏭️  修正模式：文件夹下没有文件包含XML，跳过整个文件夹")
            skipped += 1
            return auto_processed, manual_processed, skipped, total_files, success_files
        
        # 修正模式：从XML读取元数据，不更新文件（与GUI行为一致）
        print(f"{'  ' * depth}📖 修正模式：从XML文件读取元数据（只读不写）")
        process_xml_modify_folder(folder_path, folder_info, depth)
        auto_processed += 1
        
        return auto_processed, manual_processed, skipped, total_files, success_files
    
    # 检测是否是不规范文件夹（从文件名提取的信息）
    is_irregular = is_irregular_folder(folder_info)
    
    if is_irregular:
        # 不规范文件夹，每个文件独立处理
        result = process_irregular_folder(folder_path, fetcher, depth)
        auto_processed += 1
    # 短篇文件夹特殊处理
    elif folder_info.get('vol_type') == '短篇':
        result = process_short_story_folder(folder_path, folder_info, depth)
        auto_processed += 1
    else:
        # 正常流程
        result = process_normal_folder(folder_path, folder_info, fetcher, depth)
        
        # 更新统计
        if result.get("selected_result"):
            if result["selected_result"] == "manual":
                manual_processed += 1
            else:
                auto_processed += 1
    
    # 处理文件
    if result.get("skip_files"):
        skipped += 1
        print(f"{'  ' * depth}⏭️  跳过此系列")
    else:
        # 检查是否是不规范文件夹特殊处理
        if result.get("selected_result") == "irregular":
            # 不规范文件夹，每个文件独立处理
            total_files, success_files = process_irregular_folder_files(
                folder_path, fetcher, depth
            )
        else:
            # 正常处理
            comic_info_base = result["comic_info_base"]
            skip_files = result.get("skip_files", False)
            
            total_files, success_files = file_handler.process_comic_files(
                folder_path, comic_info_base, folder_info, skip_files
            )
    
    return auto_processed, manual_processed, skipped, total_files, success_files


