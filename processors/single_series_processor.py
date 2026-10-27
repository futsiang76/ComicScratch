#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单系列处理器模块 - 处理指定Bangumi ID的单个文件夹

用于用户已知Bangumi ID的情况，跳过搜索和匹配流程
"""

import os
from typing import Dict, Optional, Tuple

from config import BANGUMI_ACCESS_TOKEN
from models.bangumi_fetcher import BangumiFetcher
from parsers.folder_parser import parse_folder_name_lenient
from processors.interaction_handler import create_interaction_handler
from processors.xml_template_handler import create_xml_template_handler
from processors.zip_handler import create_file_handler


def build_comic_info_from_id(fetcher: BangumiFetcher, bangumi_id: int,
                             folder_info: Dict) -> Optional[Tuple[Dict, Dict]]:
    """按 Bangumi ID 查询详情并构建 comic_info_base（GUI/控制台共享）

    Args:
        fetcher: BangumiFetcher 实例
        bangumi_id: Bangumi 作品 ID
        folder_info: 文件夹解析信息

    Returns:
        (comic_info_base, selected_result) 查询成功；None 表示未找到作品
    """
    detail = fetcher.get_manga_detail(bangumi_id)
    if not detail:
        return None
    template_handler = create_xml_template_handler()
    comic_info_base = template_handler.create_bangumi_template(detail, folder_info, fetcher)
    selected_result = {
        "id": bangumi_id,
        "name": detail.get("name", ""),
        "name_cn": detail.get("name_cn", detail.get("name", "")),
    }
    return comic_info_base, selected_result


class SingleSeriesProcessor:
    """单系列处理器"""
    
    def __init__(self, fetcher: Optional[BangumiFetcher] = None):
        """初始化单系列处理器
        
        Args:
            fetcher: Bangumi获取器实例，如果为None则创建新的
        """
        self.fetcher = fetcher or BangumiFetcher()
    
    def process_folder_with_id(self, folder_path: str, bangumi_id: int) -> bool:
        """处理指定Bangumi ID的文件夹
        
        Args:
            folder_path: 文件夹路径
            bangumi_id: Bangumi作品ID
            
        Returns:
            bool: 是否成功处理
        """
        print(f"\n🚀 开始处理单一系列: {os.path.basename(folder_path)}")
        print(f"   Bangumi ID: {bangumi_id}")
        
        try:
            # 解析文件夹信息
            folder_name = os.path.basename(folder_path)
            folder_info = parse_folder_name_lenient(folder_name, folder_path)
            
            if not folder_info:
                print(f"❌ 无法解析文件夹信息: {folder_name}")
                return False
            
            # 添加路径信息
            folder_info['path'] = folder_path
            folder_info['series_original'] = folder_info.get('series', '')
            
            # 按 Bangumi ID 查询并构建 comic_info_base（复用共享函数）
            built = build_comic_info_from_id(self.fetcher, bangumi_id, folder_info)
            if not built:
                print(f"❌ 无法获取Bangumi详情，ID: {bangumi_id}")
                return False
            comic_info_base, _ = built
            
            # 使用现有的FileHandler处理ZIP文件
            file_handler = create_file_handler()
            total_files, success_files = file_handler.process_comic_files(
                folder_path, comic_info_base, folder_info, skip_files=False
            )
            
            if success_files > 0:
                print(f"✅ 单系列处理完成: {success_files}/{total_files} 个文件成功")
                return True
            else:
                print(f"❌ 单系列处理失败: {success_files}/{total_files} 个文件成功")
                return False
            
        except Exception as e:
            print(f"❌ 单系列处理失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def process_folder_with_local_info(self, folder_path: str) -> bool:
        """使用本地文件夹信息处理文件夹
        
        Args:
            folder_path: 文件夹路径
            
        Returns:
            bool: 是否成功处理
        """
        print(f"\n🚀 开始处理单一系列（本地信息）: {os.path.basename(folder_path)}")
        
        try:
            # 解析文件夹信息
            folder_name = os.path.basename(folder_path)
            folder_info = parse_folder_name_lenient(folder_name)
            
            # 如果无法从文件夹名称解析，说明是不规则文件夹
            # 每个zip文件都是一个独立的单卷系列，需要分开解析
            if not folder_info:
                print(f"⚠️  检测到不规则文件夹，每个ZIP文件将作为独立系列处理")
                print(f"💡 提示：这是模式3的分支 - 不规则文件夹独立处理")
                return self._process_irregular_folder(folder_path)
            
            # 添加路径信息
            folder_info['path'] = folder_path
            folder_info['series_original'] = folder_info.get('series', '')
            
            # 创建本地XML模板（复用现有函数）
            template_handler = create_xml_template_handler()
            comic_info_base = template_handler.create_local_template(folder_info)
            
            # 使用现有的FileHandler处理ZIP文件
            file_handler = create_file_handler()
            total_files, success_files = file_handler.process_comic_files(
                folder_path, comic_info_base, folder_info, skip_files=False
            )
            
            if success_files > 0:
                print(f"✅ 本地信息处理完成: {success_files}/{total_files} 个文件成功")
                return True
            else:
                print(f"❌ 本地信息处理失败: {success_files}/{total_files} 个文件成功")
                return False
                
        except Exception as e:
            print(f"❌ 本地信息处理失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _process_irregular_folder(self, folder_path: str) -> bool:
        """处理不规则文件夹，每个ZIP文件作为独立系列处理
        
        Args:
            folder_path: 文件夹路径
            
        Returns:
            bool: 是否成功处理
        """
        print(f"\n🔄 开始处理不规则文件夹: {os.path.basename(folder_path)}")
        
        try:
            # 查找文件夹中的zip文件
            zip_files = []
            for file in os.listdir(folder_path):
                if file.lower().endswith(('.zip', '.cbz', '.cbr', '.rar')):
                    zip_files.append(file)
            
            if not zip_files:
                print(f"❌ 文件夹中没有找到ZIP文件: {os.path.basename(folder_path)}")
                return False
            
            # 手动判断是否为Manga
            manga_input = input("是否为Manga？(Y/n): ").strip().lower()
            manga_value = "No" if manga_input == "n" else "Yes"
            print(f"📖 Manga字段设置为: {manga_value}")
            
            print(f"📁 找到 {len(zip_files)} 个ZIP文件")
            print(f"💡 提示：每个文件都会单独询问处理方式")
            
            # 导入单个文件名解析函数
            from parsers.file_parser import parse_filename_info
            from processors.xml_template_handler import \
                create_xml_template_handler
            from processors.zip_handler import add_file_to_zip
            
            total_files = len(zip_files)
            success_files = 0
            
            # 对每个zip文件单独处理
            for zip_file in zip_files:
                print(f"\n{'='*60}")
                print(f"📄 处理文件: {zip_file}")
                print(f"{'='*60}")
                
                try:
                    # 解析单个zip文件的信息
                    file_info = parse_filename_info(zip_file)
                    
                    if not file_info:
                        print(f"⚠️  无法从文件名解析信息，跳过: {zip_file}")
                        continue
                    
                    print(f"📚 系列名: {file_info.get('series', '未知')}")
                    print(f"✍️  作者: {file_info.get('author', '未知')}")
                    print(f"🏷️  标签: {', '.join(file_info.get('tags', []))}")
                    
                    # 询问用户处理方式
                    print(f"\n请选择处理方式:")
                    print(f"  0. 使用本地信息（从文件名解析）")
                    print(f"  其他数字. 输入Bangumi ID")
                    
                    bangumi_id_input = input(f"请输入Bangumi ID (输入0使用本地信息，输入s跳过): ").strip()
                    
                    # 检查是否跳过
                    if bangumi_id_input.lower() == 's':
                        print(f"⏭️  跳过文件: {zip_file}")
                        continue
                    
                    if not bangumi_id_input:
                        print(f"⚠️  未输入Bangumi ID，跳过: {zip_file}")
                        continue
                    
                    # 创建文件夹信息结构
                    folder_info = {
                        'series': file_info.get('series', ''),
                        'author': file_info.get('author', ''),
                        'tags': file_info.get('tags', []),
                        'vol_type': '未知',
                        'total_vols': '',
                        'total_volumes': '',  # 添加total_volumes键
                        'complete': True,     # 添加complete键，默认为True（已完结）
                        'has_extras': False,
                        'extras': '',
                        'path': folder_path,
                        'series_original': file_info.get('series', '')
                    }
                    
                    # 处理单个zip文件
                    file_handler = create_file_handler()
                    zip_path = os.path.join(folder_path, zip_file)
                    
                    # 根据用户选择处理
                    if bangumi_id_input == '0':
                        print(f"\n📋 使用本地信息写入")
                        # 创建XML模板
                        template_handler = create_xml_template_handler()
                        comic_info_base = template_handler.create_local_template(folder_info)
                        comic_info_base["Manga"] = manga_value
                    else:
                        try:
                            bangumi_id = int(bangumi_id_input)
                            print(f"\n🔍 正在按Bangumi ID查找: {bangumi_id}")
                            built = build_comic_info_from_id(self.fetcher, bangumi_id, folder_info)
                            if not built:
                                print(f"❌ 无法获取Bangumi详情，ID: {bangumi_id}")
                                continue
                            comic_info_base, _ = built
                            comic_info_base["Manga"] = manga_value
                        except ValueError:
                            print(f"❌ Bangumi ID必须是数字，跳过: {zip_file}")
                            continue
                    
                    # 为单个文件生成特定的XML
                    xml_content = file_handler.xml_generator.generate_for_file(
                        comic_info_base, zip_file, folder_info
                    )
                    
                    # 写入XML到ZIP文件
                    result = add_file_to_zip(zip_path, xml_content)
                    
                    if result is True:
                        print(f"✅ 处理成功: {zip_file}")
                        success_files += 1
                    elif result is False:
                        print(f"❌ 处理失败: {zip_file}")
                    else:
                        print(f"⏭️  跳过文件（内容一致）: {zip_file}")
                        success_files += 1
                        
                except Exception as e:
                    print(f"❌ 处理异常: {zip_file} - {str(e)}")
                    continue
            
            print(f"\n{'='*60}")
            print(f"📊 不规则文件夹处理完成: {success_files}/{total_files} 个文件成功")
            print(f"{'='*60}")
            
            return success_files > 0
            
        except Exception as e:
            print(f"❌ 不规则文件夹处理失败: {e}")
            import traceback
            traceback.print_exc()
            return False


def create_single_series_processor(fetcher: Optional[BangumiFetcher] = None) -> SingleSeriesProcessor:
    """创建单系列处理器实例
    
    Args:
        fetcher: Bangumi获取器实例
        
    Returns:
        SingleSeriesProcessor: 单系列处理器实例
    """
    return SingleSeriesProcessor(fetcher)