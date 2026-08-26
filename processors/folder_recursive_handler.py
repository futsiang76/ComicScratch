#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件夹递归处理器模块 - 负责递归扫描和处理漫画文件夹
"""

import os
from typing import Any, Callable, Dict, List, Tuple

from parsers.file_parser import parse_folder_from_filename
from parsers.folder_parser import parse_folder_name_lenient
from processors.ignore_rules import filter_subdirs, is_dir_ignored


class FolderRecursiveHandler:
    """文件夹递归处理器类"""
    
    def __init__(self, max_depth: int = 3):
        """初始化文件夹递归处理器
        
        Args:
            max_depth: 最大递归深度
        """
        self.max_depth = max_depth
    
    def scan_directory(self, root_path: str, 
                      folder_callback: Callable[[str, Dict, int], Any],
                      recursive_callback: Callable[[str, int], Any]) -> Tuple[int, int, int]:
        """扫描目录并处理漫画文件夹
        
        Args:
            root_path: 根目录路径
            folder_callback: 文件夹处理回调函数
            recursive_callback: 递归处理回调函数
            
        Returns:
            Tuple[int, int, int]: (总文件夹数, 处理文件夹数, 跳过文件夹数)
        """
        total_folders = 0
        processed_folders = 0
        skipped_folders = 0
        
        def _has_comic_files(path: str) -> bool:
            """目录直接包含漫画压缩文件时返回 True（与 _collect_series_folders 一致）"""
            try:
                return any(f.lower().endswith(('.zip', '.cbz', '.cbr', '.rar'))
                           for f in os.listdir(path)
                           if os.path.isfile(os.path.join(path, f)))
            except OSError:
                return False

        def _process_directory(current_path: str, depth: int = 0):
            """递归处理目录
            
            Args:
                current_path: 当前目录路径
                depth: 当前深度
            """
            nonlocal total_folders, processed_folders, skipped_folders
            
            if depth > self.max_depth:
                return
            
            try:
                # 首先检查当前目录本身是否是合法的漫画文件夹
                # （宽松解析器对任意非空名都返回真，需叠加"含漫画文件"判定，
                #   否则根目录永远被误判为系列、递归永不发生）
                current_dir_name = os.path.basename(current_path)
                folder_info = parse_folder_name_lenient(current_dir_name, current_path)
                if not folder_info:
                    # 尝试从文件名提取信息
                    folder_info = parse_folder_from_filename(current_path)
                
                if folder_info and _has_comic_files(current_path):
                    # 检查是否是不规则文件夹
                    is_irregular = folder_info.get('from_filename', False)
                    
                    # 根目录本身就是合法的漫画文件夹，直接处理它
                    total_folders += 1
                    
                    # 只在规则文件夹时显示根目录提示
                    if not is_irregular:
                        print(f"\n{'  ' * depth}{'='*60}")
                        print(f"{'  ' * depth}📚 根目录为系列: {folder_info['series']}")
                        print(f"{'  ' * depth}✍️  文件夹作者: {folder_info['author']}")
                        print(f"{'  ' * depth}📖 总卷数: {folder_info['total_volumes']} | 类型: {folder_info['vol_info']} | 状态: {'已完结' if folder_info['complete'] else '连载中'}")
                        if folder_info['has_extras']:
                            print(f"{'  ' * depth}📦 额外内容: {folder_info['extras']}")
                        print(f"{'  ' * depth}{'='*60}")
                    
                    # 调用文件夹处理回调
                    result = folder_callback(current_path, folder_info, depth)
                    if result:
                        processed_folders += 1
                    else:
                        skipped_folders += 1
                    return  # 根目录已处理，不再递归子目录
                
                # 如果不是根目录系列，则正常处理子目录
                for item in os.listdir(current_path):
                    item_path = os.path.join(current_path, item)

                    if not os.path.isdir(item_path):
                        continue

                    # 忽略规则：命中通配符的目录不作为系列且不递归
                    if is_dir_ignored(item):
                        print(f"\n{'  ' * depth}⚠️  跳过忽略目录: {item}")
                        skipped_folders += 1
                        continue

                    if item.startswith("."):
                        print(f"\n{'  ' * depth}⚠️  跳过隐藏文件夹: {item}")
                        skipped_folders += 1
                        continue
                    
                    # 检查是否是合法的漫画文件夹
                    folder_info = parse_folder_name_lenient(item, item_path)
                    if not folder_info:
                        # 尝试从文件名提取信息
                        folder_info = parse_folder_from_filename(item_path)
                    
                    if folder_info and _has_comic_files(item_path):
                        # 是合法的漫画文件夹（直接含漫画文件），处理它
                        total_folders += 1
                        print(f"\n{'  ' * depth}{'='*60}")
                        print(f"{'  ' * depth}📚 处理系列: {folder_info['series']}")
                        print(f"{'  ' * depth}✍️  文件夹作者: {folder_info['author']}")
                        print(f"{'  ' * depth}📖 总卷数: {folder_info['total_volumes']} | 类型: {folder_info['vol_info']} | 状态: {'已完结' if folder_info['complete'] else '连载中'}")
                        if folder_info['has_extras']:
                            print(f"{'  ' * depth}📦 额外内容: {folder_info['extras']}")
                        print(f"{'  ' * depth}{'='*60}")
                        
                        # 调用文件夹处理回调
                        result = folder_callback(item_path, folder_info, depth)
                        if result:
                            processed_folders += 1
                        else:
                            skipped_folders += 1
                    else:
                        # 不是合法的漫画文件夹，递归检查子目录
                        print(f"\n{'  ' * depth}🔍 递归检查子目录: {item}")
                        recursive_callback(item_path, depth + 1)
                        _process_directory(item_path, depth + 1)
            
            except Exception as e:
                print(f"\n{'  ' * depth}🔴 处理目录失败: {str(e)[:50]}")
        
        # 开始递归处理
        _process_directory(root_path)
        
        return total_folders, processed_folders, skipped_folders
    
    def get_folder_statistics(self, root_path: str) -> Dict[str, Any]:
        """获取文件夹统计信息
        
        Args:
            root_path: 根目录路径
            
        Returns:
            Dict[str, Any]: 统计信息
        """
        stats = {
            'total_folders': 0,
            'comic_folders': 0,
            'non_comic_folders': 0,
            'hidden_folders': 0,
            'max_depth': 0,
            'folder_types': {},
            'authors': {},
            'status': {'completed': 0, 'ongoing': 0}
        }
        
        def _collect_statistics(current_path: str, depth: int = 0):
            """递归收集统计信息
            
            Args:
                current_path: 当前目录路径
                depth: 当前深度
            """
            nonlocal stats
            
            if depth > self.max_depth:
                return
            
            stats['max_depth'] = max(stats['max_depth'], depth)
            
            try:
                for item in os.listdir(current_path):
                    item_path = os.path.join(current_path, item)

                    if not os.path.isdir(item_path):
                        continue

                    stats['total_folders'] += 1

                    # 忽略规则：命中通配符的目录不计入且不递归
                    if is_dir_ignored(item):
                        continue

                    if item.startswith("."):
                        stats['hidden_folders'] += 1
                        continue
                    
                    # 检查是否是合法的漫画文件夹
                    folder_info = parse_folder_name_lenient(item, item_path)
                    if not folder_info:
                        # 尝试从文件名提取信息
                        folder_info = parse_folder_from_filename(item_path)
                    
                    if folder_info and any(
                            f.lower().endswith(('.zip', '.cbz', '.cbr', '.rar'))
                            for f in os.listdir(item_path)
                            if os.path.isfile(os.path.join(item_path, f))):
                        stats['comic_folders'] += 1
                        
                        # 统计文件夹类型
                        vol_type = folder_info.get('vol_type', 'unknown')
                        if vol_type not in stats['folder_types']:
                            stats['folder_types'][vol_type] = 0
                        stats['folder_types'][vol_type] += 1
                        
                        # 统计作者
                        author = folder_info['author']
                        if author not in stats['authors']:
                            stats['authors'][author] = 0
                        stats['authors'][author] += 1
                        
                        # 统计状态
                        if folder_info['complete']:
                            stats['status']['completed'] += 1
                        else:
                            stats['status']['ongoing'] += 1
                    else:
                        stats['non_comic_folders'] += 1
                        # 递归统计子目录
                        _collect_statistics(item_path, depth + 1)
            
            except Exception as e:
                print(f"🔴 收集统计信息失败: {str(e)[:50]}")
        
        # 开始收集统计信息
        _collect_statistics(root_path)
        
        return stats
    
    def validate_folder_structure(self, root_path: str) -> Dict[str, Any]:
        """验证文件夹结构
        
        Args:
            root_path: 根目录路径
            
        Returns:
            Dict[str, Any]: 验证结果
        """
        validation = {
            'valid': True,
            'errors': [],
            'warnings': [],
            'suggestions': []
        }
        
        def _validate_structure(current_path: str, depth: int = 0):
            """递归验证文件夹结构
            
            Args:
                current_path: 当前目录路径
                depth: 当前深度
            """
            nonlocal validation
            
            if depth > self.max_depth:
                validation['warnings'].append(f"目录深度超过限制: {current_path}")
                return
            
            try:
                items = os.listdir(current_path)
                
                if not items:
                    validation['warnings'].append(f"空目录: {current_path}")
                    return
                
                comic_folders = 0
                non_comic_folders = 0
                
                for item in items:
                    item_path = os.path.join(current_path, item)

                    if not os.path.isdir(item_path):
                        continue

                    # 忽略规则：命中通配符的目录不参与结构验证且不递归
                    if is_dir_ignored(item):
                        continue

                    if item.startswith("."):
                        continue
                    
                    # 检查是否是合法的漫画文件夹
                    folder_info = parse_folder_name_lenient(item, item_path)
                    if not folder_info:
                        folder_info = parse_folder_from_filename(item_path)
                    
                    has_comic = any(
                        f.lower().endswith(('.zip', '.cbz', '.cbr', '.rar'))
                        for f in os.listdir(item_path)
                        if os.path.isfile(os.path.join(item_path, f)))
                    if folder_info and has_comic:
                        comic_folders += 1
                        
                        # 验证文件夹命名
                        if not self._validate_folder_name(item, folder_info):
                            validation['suggestions'].append(f"建议优化文件夹命名: {item}")
                    else:
                        non_comic_folders += 1
                        # 递归验证子目录
                        _validate_structure(item_path, depth + 1)
                
                # 检查混合目录结构
                if comic_folders > 0 and non_comic_folders > 0:
                    validation['warnings'].append(f"混合目录结构: {current_path} (包含{comic_folders}个漫画文件夹和{non_comic_folders}个非漫画文件夹)")
            
            except Exception as e:
                validation['errors'].append(f"验证失败: {current_path} - {str(e)[:50]}")
                validation['valid'] = False
        
        # 开始验证
        _validate_structure(root_path)
        
        return validation
    
    def _validate_folder_name(self, folder_name: str, folder_info: Dict) -> bool:
        """验证文件夹命名
        
        Args:
            folder_name: 文件夹名
            folder_info: 文件夹信息
            
        Returns:
            bool: 是否有效
        """
        # 基本验证规则
        if not folder_name.strip():
            return False
        
        if len(folder_name) > 100:
            return False
        
        # 检查是否包含必要信息
        required_fields = ['author', 'series']
        for field in required_fields:
            if field not in folder_info or not folder_info[field]:
                return False
        
        return True


def create_folder_recursive_handler(max_depth: int = 3) -> FolderRecursiveHandler:
    """创建文件夹递归处理器实例
    
    Args:
        max_depth: 最大递归深度
        
    Returns:
        FolderRecursiveHandler: 文件夹递归处理器实例
    """
    return FolderRecursiveHandler(max_depth)