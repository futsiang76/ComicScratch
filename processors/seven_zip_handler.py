#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZIP处理器模块 - 高效处理ZIP/CBZ文件

使用7-Zip命令行工具提高性能，支持秒级处理大文件
"""

import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile
from contextlib import ExitStack
from typing import Any, Dict, List, Optional, Tuple

from parsers.file_parser import (generate_smart_title,
                                 parse_volume_from_filename)
from processors.utils import (file_tag, set_hidden_attr, thread_tag,
                              zip_lock, zip_lock_multi)
from processors.xml_generator import XMLGenerator

def _check_seven_zip_available() -> str:
    """检查7-Zip是否可用，并返回其路径
    
    Returns:
        str: 7-Zip可执行文件的路径，如果不可用返回空字符串
    """
    try:
        # 首先尝试直接运行7z.exe（如果在PATH中）
        result = subprocess.run(
            ['cmd', '/c', '7z.exe', '--help'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        if result.returncode == 0 or "7-Zip" in result.stdout:
            return "7z.exe"
        
        # 尝试7za.exe（命令行版本）
        result = subprocess.run(
            ['cmd', '/c', '7za.exe', '--help'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        if result.returncode == 0 or "7-Zip" in result.stdout:
            return "7za.exe"
        
        # 检查常见的安装路径
        common_paths = [
            r"C:\Program Files\7-Zip\7z.exe",
            r"C:\Program Files (x86)\7-Zip\7z.exe",
            r"D:\Program Files\7-Zip\7z.exe",
            r"D:\Program Files (x86)\7-Zip\7z.exe"
        ]
        
        for path in common_paths:
            if os.path.exists(path):
                return path
        
        return ""
    except (subprocess.SubprocessError, FileNotFoundError):
        return ""

def _add_with_zipfile(zip_path: str, file_content: str, file_name: str,
                      xml_exists: bool = False,
                      files_to_delete: Optional[List[str]] = None) -> bool:
    """使用 zipfile 流式重写添加/更新 XML（统一 ZIP_STORED 输出）

    逐条目流式复制（读一个条目即写一个条目，不全量载入内存），适合大卷。
    输出统一 ZIP_STORED（归档不压缩），替代 7z a -si 原地更新：
    7z -si 更新 DEFLATE 原卷需解压+重压整卷（154-269MB），慢 + 文件占用重试会把
    原卷替换成只含 XML 的空壳（丢图），故 zip/cbz 原地写统一走本方法。

    Args:
        zip_path: zip/cbz 文件路径
        file_content: 待写入的 XML 内容
        file_name: 文件名（默认 ComicInfo.xml）
        xml_exists: 目标 XML 是否已存在（仅影响成功提示文案）
        files_to_delete: 需删除的其它 XML 文件名列表（流式复制时跳过）

    Returns:
        bool: 是否成功
    """
    import zipfile

    files_to_delete = set(files_to_delete or [])

    # 文件级互斥锁（多实例安全）：写盘开始前对目标 zip 加锁，流式重写 + CRC
    # 校验 + os.replace 全部成功后 finally 才释放（任何一步失败也 finally 释放，
    # 绝不提前放锁让另一实例读到半成品）；同一 zip 另一实例正写时等待最多
    # 120s（大卷写盘 SSD 30s+/HDD 1-2 分钟，宁可多等不误跳过），超时才失败。
    # 不同 zip 锁文件不同，互不阻塞。
    lock_stack = ExitStack()
    try:
        if not lock_stack.enter_context(zip_lock(zip_path)):
            return False
        # 临时文件放「目标盘根下独立 .comicscratch_tmp 目录」（与目标 zip 同盘），
        # 避免用户在手同步目录(网盘/Syncthing)开着同步时把临时文件同步出去。
        # 与目标同盘保证 os.replace 同盘原子替换：系统临时目录在 C 盘、
        # 目标 zip 在其它盘会触发 MoveFileEx 跨盘 rename → WinError 17。
        safe_base = re.sub(r'[<>:"/\|?*]', '_', os.path.basename(zip_path))
        drive, _ = os.path.splitdrive(zip_path)
        temp_dir = os.path.join(drive + os.sep, ".comicscratch_tmp")
        try:
            os.makedirs(temp_dir, exist_ok=True)
            set_hidden_attr(temp_dir)
            temp_zip_path = os.path.join(temp_dir, f"{uuid.uuid4().hex[:8]}.tmp")
        except OSError:
            # 建盘根 temp 目录失败（只读盘根等）回退到目标 zip 同目录
            temp_zip_path = os.path.join(
                os.path.dirname(zip_path), f".{safe_base}.{uuid.uuid4().hex[:8]}.tmp")

        # 源文件可能被其它进程（如并行会话）短暂占用，打开失败时递增等待重试
        max_open_retries = 3
        zin = None
        for attempt in range(1, max_open_retries + 1):
            try:
                zin = zipfile.ZipFile(zip_path, 'r')
                break
            except (OSError, zipfile.BadZipFile):
                if attempt < max_open_retries:
                    time.sleep(0.5 * attempt)
                else:
                    raise

        try:
            with zipfile.ZipFile(temp_zip_path, 'w',
                                 zipfile.ZIP_STORED,
                                 allowZip64=True) as zout:
                # 逐条目流式复制：跳过目标 XML（由新内容覆盖）与需删除的其它 XML
                for name in zin.namelist():
                    if name == file_name or name in files_to_delete:
                        continue
                    try:
                        zout.writestr(name, zin.read(name))  # 读一个写一个，不整卷进内存
                    except Exception as e:
                        print(f"{thread_tag()} ⚠️  读取/写入文件失败 {file_tag(zip_path)} 条目 [{name}]: {str(e)[:200]}")
                # 写入新 XML
                zout.writestr(file_name, file_content.encode('utf-8'))
        finally:
            zin.close()

        # CRC校验：验证临时ZIP文件完整性
        with zipfile.ZipFile(temp_zip_path, 'r') as zf:
            bad_file = zf.testzip()
            if bad_file is None:
                print(f"{thread_tag()}   🔍 CRC校验通过 {file_tag(zip_path)}: 临时ZIP文件完整")
            else:
                print(f"{thread_tag()}   ⚠️  CRC校验失败 {file_tag(zip_path)}: 损坏的文件 {bad_file}")
                raise Exception(f"临时ZIP文件CRC校验失败 [{os.path.basename(zip_path)}]: {bad_file}")

        # 原子替换回原路径：目标 zip 可能被其它进程（Komga 扫描/资源管理器预览/杀软）
        # 瞬时占用，os.replace 抛 WinError 5(拒绝访问)/32(文件被占用) 时递增等待重试；
        # 非占用类错误（如 WinError 17 跨盘）不重试直接抛
        max_replace_retries = 3
        for attempt in range(1, max_replace_retries + 1):
            try:
                os.replace(temp_zip_path, zip_path)
                break
            except OSError as e:
                winerror = getattr(e, 'winerror', None)
                is_lock_error = (winerror in (5, 32) if winerror is not None
                                 else e.errno == 13)
                if is_lock_error and attempt < max_replace_retries:
                    print(f"{thread_tag()} ⚠️ os.replace 重试中（第 {attempt} 次） {file_tag(zip_path)}: {str(e)[:120]}")
                    time.sleep(0.5 * attempt)
                else:
                    raise

        if xml_exists:
            print(f"{thread_tag()} ✅ 使用zipfile成功更新文件 {file_tag(zip_path)}: {file_name}")
        else:
            print(f"{thread_tag()} ✅ 使用zipfile成功添加文件 {file_tag(zip_path)}: {file_name}")
        return True
    except Exception as e:
        print(f"{thread_tag()} 🔴 回退方法失败 {file_tag(zip_path)}: {str(e)}")
        # 失败清理与目标文件同目录的临时文件
        if 'temp_zip_path' in locals() and os.path.exists(temp_zip_path):
            try:
                os.unlink(temp_zip_path)
            except Exception:
                pass
        return False
    finally:
        # 成功/失败路径都释放文件锁（zip_lock 在 with 退出时删除锁文件）
        lock_stack.close()


def _convert_zip_container(zip_path: str, file_content: str, file_name: str,
                           target_ext: str, keep_original: bool = False) -> bool:
    """zip/cbz 容器 → 目标 zip 容器（.cbz/.zip）转换，用 zipfile 重写

    手动选择 CBZ/ZIP 格式时，对已是 zip 容器的源文件无需 7z：
    读出全部条目 → 按目标扩展名写出新文件（ZIP_STORED）→ 写入 XML。
    转换成功且 keep_original=False 时删除原文件。

    Args:
        zip_path: 源 zip/cbz 文件路径
        file_content: 待写入的 XML 内容
        file_name: 文件名（默认 ComicInfo.xml）
        target_ext: 目标扩展名（".cbz"/".zip"）
        keep_original: True 时保留原文件；False 时转换成功后删除原文件

    Returns:
        bool: 是否成功
    """
    import zipfile

    base_name = os.path.splitext(zip_path)[0]
    new_path = base_name + target_ext
    # 转换同时碰源文件（读+可能删）与目标文件（写）：对两者统一加文件级互斥锁，
    # 与 _add_with_zipfile 同一把锁，避免与另一实例的原地写并发
    lock_stack = zip_lock_multi([zip_path, new_path])
    if lock_stack is None:
        return False
    try:
        # 读出源文件全部条目（目标 XML 由新文件覆盖写入）
        with zipfile.ZipFile(zip_path, 'r') as zf:
            entries = {name: zf.read(name) for name in zf.namelist() if name != file_name}
        # 按目标扩展名写出新归档
        with zipfile.ZipFile(new_path, 'w', zipfile.ZIP_STORED, allowZip64=True) as zf:
            for name, content in entries.items():
                zf.writestr(name, content)
            zf.writestr(file_name, file_content.encode('utf-8'))
    except (zipfile.BadZipFile, OSError) as e:
        print(f"{thread_tag()} 🔴 ZIP 容器转换失败 {file_tag(zip_path)}: {str(e)[:100]}")
        lock_stack.close()
        return False

    if not keep_original and os.path.abspath(new_path) != os.path.abspath(zip_path):
        try:
            os.remove(zip_path)
            print(f"{thread_tag()} 🗑️   已删除原始文件 {file_tag(zip_path)}")
        except OSError as e:
            print(f"{thread_tag()} ⚠️   删除原始文件失败 {file_tag(zip_path)}: {str(e)[:100]}")
    print(f"{thread_tag()} ✅ 成功转换并添加文件 {file_tag(zip_path)}: {file_name}")
    lock_stack.close()
    return True


def _handle_archive_format(zip_path: str, file_content: str, file_name: str = 'ComicInfo.xml',
                           target_ext: str = '.zip', keep_original: bool = False) -> bool:
    """处理 RAR/CBR/CBZ 归档：提取 → 写入 XML → 以目标格式重新压缩

    Args:
        zip_path: 文件路径
        file_content: 文件内容
        file_name: 文件名
        target_ext: 目标扩展名（".zip"/".cbz"/".cb7"）；".cb7" 用 7z 容器，其余用 zip 容器
        keep_original: True 时保留原文件（仅转换出的新文件）；False 时转换成功删除原文件

    Returns:
        bool: 是否成功
    """
    import re
    import shutil

    # 归档转换同时碰源文件（读+可能删）与目标文件（写）：对两者统一加文件级
    # 互斥锁（同一把锁 helper），避免与另一实例对同一文件的并发写
    new_zip_path = os.path.splitext(zip_path)[0] + target_ext
    lock_stack = zip_lock_multi([zip_path, new_zip_path])
    if lock_stack is None:
        return False

    try:
        # 检查7-Zip是否可用
        seven_zip_path = _check_seven_zip_available()
        if not seven_zip_path:
            print(f"{thread_tag()} 🔴 7-Zip不可用，无法处理归档格式 {file_tag(zip_path)}")
            return False
        
        # 创建临时目录（为每个实例生成唯一路径）
        temp_dir = tempfile.gettempdir()
        # 使用安全的目录名，避免特殊字符，并添加唯一标识符
        safe_basename = re.sub(r'[<>"|?*]', '_', os.path.basename(zip_path))
        instance_id = str(uuid.uuid4())[:8]  # 生成8位唯一标识符
        extract_dir = os.path.join(temp_dir, f"extract_{instance_id}_{safe_basename}")
        os.makedirs(extract_dir, exist_ok=True)
        
        # 提取文件内容
        print(f"{thread_tag()} 🔄 提取文件内容 {file_tag(zip_path)}...")
        extract_success = False
        
        # 尝试不同的提取方法（只保留成功的方法）
        extraction_methods = [
            # 方法1: 自动识别格式（不带引号）
            lambda: _run_seven_zip(seven_zip_path, ['x', '-y', zip_path, f'-o{extract_dir}'])
        ]
        
        for i, method in enumerate(extraction_methods):
            try:
                print(f"{thread_tag()}   尝试提取方法 {i+1}...")
                result = method()
                if result.returncode == 0:
                    print(f"{thread_tag()}   ✅ 提取成功")
                    extract_success = True
                    break
                else:
                    # 不显示具体错误信息，直接显示下一步
                    print(f"{thread_tag()}   ⚠️  提取失败，尝试下一步处理")
            except Exception as e:
                print(f"{thread_tag()}   ⚠️  方法执行失败，尝试下一步处理")
        
        if not extract_success:
            print(f"{thread_tag()} 🔴 所有提取方法都失败 {file_tag(zip_path)}")
            return False
        
        # 写入新的XML文件
        xml_path = os.path.join(extract_dir, file_name)
        with open(xml_path, 'w', encoding='utf-8') as xml_file:
            xml_file.write(file_content)
        
        # 创建临时ZIP文件（为每个实例生成唯一路径）
        # 使用唯一标识符避免多实例冲突
        safe_temp_name = f"temp_{instance_id}_{re.sub(r'[\\s]', '_', safe_basename)}{target_ext}"
        temp_zip_path = os.path.join(temp_dir, safe_temp_name)
        
        # 将提取的内容重新压缩为ZIP
        print(f"{thread_tag()} 🔄 重新压缩为{target_ext}格式 {file_tag(zip_path)}...")
        zip_success = False

        # .cb7 用 7z 容器（-mx=0 禁用压缩，后续按图片格式压缩），其余用 zip 容器
        container_args = ["-t7z", "-mx=0"] if target_ext == ".cb7" else ["-tzip", "-mm=copy"]
        compression_methods = [
            lambda: _run_seven_zip(seven_zip_path, ["a", *container_args, "-y", temp_zip_path, f"{extract_dir}/*"])
        ]
        
        for i, method in enumerate(compression_methods):
            try:
                print(f"{thread_tag()}   尝试压缩方法 {i+1}...")
                result = method()
                if result.returncode == 0:
                    print(f"{thread_tag()}   ✅ 压缩成功")
                    zip_success = True
                    break
                else:
                    # 不显示具体错误信息，直接显示下一步
                    print(f"{thread_tag()}   ⚠️  压缩失败，尝试下一步处理")
            except Exception as e:
                print(f"{thread_tag()}   ⚠️  方法执行失败，尝试下一步处理")
        
        if not zip_success:
            print(f"{thread_tag()} 🔴 所有压缩方法都失败 {file_tag(zip_path)}")
            return False
        
        # 复制临时文件到新位置
        shutil.copy2(temp_zip_path, new_zip_path)

        # 转换成功且允许删除时，删除原文件（keep_original=True 时固定保留）
        if not keep_original and zip_path != new_zip_path:
            try:
                os.remove(zip_path)
                print(f"{thread_tag()} 🗑️   已删除原始文件 {file_tag(zip_path)}")
            except Exception as e:
                print(f"{thread_tag()} ⚠️   删除原始文件失败 {file_tag(zip_path)}: {str(e)}")

        print(f"{thread_tag()} ✅ 成功将文件转换为{target_ext}并添加文件 {file_tag(zip_path)}: {file_name}")
        print(f"{thread_tag()} 📁 新文件: {os.path.basename(new_zip_path)}")
        
        # 清理临时文件
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir)
        if os.path.exists(temp_zip_path):
            os.unlink(temp_zip_path)
        
        return True
    except Exception as e:
        print(f"{thread_tag()} 🔴 处理归档格式失败 {file_tag(zip_path)}: {str(e)[:50]}")
        # 清理临时文件
        if 'extract_dir' in locals() and os.path.exists(extract_dir):
            try:
                shutil.rmtree(extract_dir)
            except:
                pass
        if 'temp_zip_path' in locals() and os.path.exists(temp_zip_path):
            try:
                os.unlink(temp_zip_path)
            except:
                pass
        return False
    finally:
        # 成功/失败路径都释放文件锁
        lock_stack.close()


def _run_seven_zip(seven_zip_path: str, args: list) -> subprocess.CompletedProcess:
    """运行7-Zip命令

    Args:
        seven_zip_path: 7-Zip可执行文件路径
        args: 命令参数列表

    Returns:
        subprocess.CompletedProcess: 命令执行结果
    """
    if os.name == 'nt':  # Windows系统
        # 直接调用7-Zip，不使用cmd
        cmd_list = [seven_zip_path] + args
        # 7z.exe 在 Windows 输出系统 ANSI（GBK）编码，text=True 默认 utf-8 解码会
        # 在读取线程抛 UnicodeDecodeError；用容错解码避免线程崩溃、保证 stdout 完整
        return subprocess.run(
            cmd_list,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            shell=True  # 使用shell=True确保路径正确处理
        )
    else:  # Unix-like系统
        cmd_list = [seven_zip_path] + args
        return subprocess.run(
            cmd_list,
            capture_output=True,
            text=True
        )


def _extract_file_via_seven_zip(archive_path: str, file_name: str = 'ComicInfo.xml') -> Optional[str]:
    """用7-Zip从归档中提取单个文件内容（二进制安全读取，UTF-8解码）

    适用于 cbr/rar/7z 等 zipfile 无法直接打开的归档格式。
    使用 7z e -so 将文件内容输出到 stdout，避免解压整个归档。

    Args:
        archive_path: 归档文件路径
        file_name: 要提取的文件名

    Returns:
        Optional[str]: 文件文本内容，失败返回None
    """
    try:
        seven_zip_path = _check_seven_zip_available()
        if not seven_zip_path:
            return None

        result = subprocess.run(
            [seven_zip_path, 'e', '-so', '-y', archive_path, file_name],
            capture_output=True,
            shell=True
        )
        if result.returncode != 0:
            return None
        # 二进制模式读取，显式 UTF-8 解码，避免 Windows 默认编码（GBK）破坏中文内容
        return result.stdout.decode('utf-8', errors='replace')
    except Exception as e:
        print(f"{thread_tag()} ⚠️  使用7-Zip提取文件失败 [{archive_path}]: {str(e)[:50]}")
        return None


def _list_xml_files_via_seven_zip(archive_path: str) -> List[str]:
    """用7-Zip列出归档内的所有XML文件名

    使用 7z l -slt 技术模式输出，解析 Path = 行获取文件名。

    Args:
        archive_path: 归档文件路径

    Returns:
        List[str]: XML文件名列表（可能含目录前缀）
    """
    try:
        seven_zip_path = _check_seven_zip_available()
        if not seven_zip_path:
            return []

        result = subprocess.run(
            [seven_zip_path, 'l', '-slt', archive_path],
            capture_output=True,
            shell=True
        )
        if result.returncode != 0:
            return []

        output = result.stdout.decode('utf-8', errors='replace')
        xml_files = []
        for line in output.splitlines():
            line = line.strip()
            if line.startswith('Path = '):
                name = line[len('Path = '):].strip()
                if name.lower().endswith('.xml'):
                    xml_files.append(name)
        return xml_files
    except Exception as e:
        print(f"{thread_tag()} ⚠️  使用7-Zip列出XML失败 [{archive_path}]: {str(e)[:50]}")
        return []

