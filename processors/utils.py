#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
处理器共享工具函数 - 无循环依赖风险
"""

import hashlib
import os
import platform
import threading
import time
from contextlib import ExitStack, contextmanager
from typing import Dict, List, Optional, Tuple


def set_hidden_attr(dir_path: str) -> None:
    """给目录设置 Windows 隐藏属性（FILE_ATTRIBUTE_HIDDEN = 0x2）

    仅 Windows 生效（os.name == 'nt'）；非 Windows 直接返回——点号目录在
    Unix 已足够隐藏。目录不存在时先 makedirs 再设置。设置失败静默忽略：
    隐藏属性只是浏览体验优化，绝不影响写盘主流程、绝不抛异常。
    """
    if os.name != "nt":
        return
    try:
        os.makedirs(dir_path, exist_ok=True)
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(dir_path, 0x2)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# zip 写盘文件级互斥锁（多实例安全）
#
# 背景：批量处理时用户会新开第二个 ComicScratch 实例处理同一系列，两个实例
# 可能同时写同一个 zip → 互相锁（WinError 5/32）+ 可能写坏文件。不能加「禁止
# 第二实例」（用户需要多实例并行处理不同系列），正确方案是文件级互斥锁：
# 同一 zip 同一时刻只允许一个进程写，不同 zip 互不干扰。
#
# 等待策略：大 zip 完整写盘（流式重写 + CRC 校验 + os.replace）在 SSD 上要
# 30 秒+、HDD 可能 1-2 分钟 —— 锁等待窗口必须 ≥60s（2s×60 = 120s），
# 「宁可多等，不要误跳过」；等待期间每 10s 打一次进度提示，避免用户以为卡死。
#
# 实现：基于 O_CREAT|O_EXCL 的锁文件（原子创建，天然跨进程互斥），锁文件内容
# 记录持有者 PID；获取失败时检查 PID 是否存活，已死（崩溃残留）则删除重试。
# 不用 QLockFile：Qt 的 stale 检测在 Windows 上行为不可控且难以单测（等待为
# 真实阻塞、锁文件格式随 Qt 版本变化），自实现全部等待走 time.sleep、残留
# 清理路径完全确定，与项目现有测试风格（monkeypatch time.sleep）一致。
# ---------------------------------------------------------------------------

ZIP_LOCK_ATTEMPTS = 60   # 锁冲突最多尝试 60 轮（每轮 2 次原子获取）
ZIP_LOCK_WAIT_MS = 2000  # 每轮等待 2s → 总窗口 120s（覆盖 HDD 大卷 1-2 分钟写盘）
ZIP_LOCK_PROGRESS_EVERY_S = 10  # 等待期间每 10s 打印一次 ⏳ 进度提示

_lock_tls = threading.local()  # 线程级重入计数：同线程嵌套获取同一把锁不重复取


def _zip_lock_path(zip_path: str) -> str:
    """目标 zip 的唯一锁文件路径

    放「目标盘根 .comicscratch_tmp 目录」（与写盘临时文件同目录策略一致：
    本地盘根、不在手同步目录，避免锁文件被 Syncthing/网盘同步出去；跨盘时
    每把锁都落在目标 zip 所在盘）。文件名取 zip 绝对路径（normcase 归一化
    斜杠/大小写后）的 sha1 前 16 位 → 两个实例对同一 zip 必然算出同一把锁，
    不同 zip 锁文件不同互不阻塞。盘根不可写时回退目标 zip 同目录。
    """
    abs_path = os.path.normcase(os.path.abspath(zip_path))
    digest = hashlib.sha1(abs_path.encode("utf-8")).hexdigest()[:16]
    drive, _ = os.path.splitdrive(abs_path)
    lock_dir = os.path.join(drive + os.sep, ".comicscratch_tmp")
    try:
        os.makedirs(lock_dir, exist_ok=True)
        set_hidden_attr(lock_dir)
    except OSError:
        # 盘根只读等：回退到目标 zip 同目录（与 _add_with_zipfile 临时文件回退一致）
        lock_dir = os.path.dirname(abs_path)
    return os.path.join(lock_dir, f".comicscratch_lock_{digest}.lock")


def _tls_held() -> Dict[str, int]:
    """当前线程已持有的锁引用计数表（锁文件路径 → 重入次数）"""
    held = getattr(_lock_tls, "held", None)
    if held is None:
        held = _lock_tls.held = {}
    return held


def _pid_alive(pid: int) -> bool:
    """跨平台 PID 存活检查；无法确认时保守返回 True（避免误删活锁）

    Windows 用 OpenProcess（PROCESS_QUERY_LIMITED_INFORMATION）：
    - 打开失败且错误码是 ACCESS_DENIED(5) → 进程存在只是无权查询 → 视为存活
    - 其余失败（如 INVALID_PARAMETER(87) 进程不存在）→ 视为死亡
    POSIX 用 os.kill(pid, 0)。
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if not handle:
                return ctypes.get_last_error() == 5  # ACCESS_DENIED → 进程存在
            try:
                exit_code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return True  # 查询失败 → 保守视为存活
                return exit_code.value == 259  # STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except Exception:
        return True


def _try_acquire_lock(lock_path: str) -> bool:
    """O_CREAT|O_EXCL 原子创建锁文件并写入持有者 PID；已存在返回 False

    非 EEXIST 的 OSError（锁目录只读等环境问题）向上抛，由调用方按真实
    错误处理，不伪装成「另一实例锁定」。
    """
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    try:
        try:
            os.write(fd, f"{os.getpid()}\n{platform.node()}\n{time.time():.3f}\n"
                         .encode("utf-8"))
        except Exception:
            # 写入失败（磁盘满等）：清掉刚创建的锁文件再抛，避免留无 PID 残留
            try:
                os.unlink(lock_path)
            except OSError:
                pass
            raise
    finally:
        os.close(fd)
    return True


def _remove_stale_lock(lock_path: str) -> None:
    """崩溃残留锁（持有者 PID 已死）自动清除；活锁绝不碰

    读锁文件取 PID → 确认已死 → 删除前重读确认内容未被替换（新持有者会
    写入新 PID），把「误删另一进程刚建的新锁」的竞态窗口压到微秒级。
    解析失败（首行非数字等异常格式）时不动，交由超时失败提示用户。
    """
    try:
        with open(lock_path, "r", encoding="utf-8", errors="replace") as f:
            first_line = f.readline().strip()
        pid = int(first_line.split()[0]) if first_line else 0
    except (OSError, ValueError):
        return
    if pid <= 0 or _pid_alive(pid):
        return
    try:
        with open(lock_path, "r", encoding="utf-8", errors="replace") as f:
            if f.readline().strip() != first_line:
                return  # 已被替换成新锁（新 PID），不删
        os.unlink(lock_path)
    except OSError:
        pass


def _release_lock(lock_path: str) -> None:
    """释放锁：删除锁文件（崩溃/被杀时文件残留由下次获取方按 PID 清理）"""
    try:
        os.unlink(lock_path)
    except OSError:
        pass


@contextmanager
def zip_lock(zip_path: str, attempts: Optional[int] = None,
             wait_ms: Optional[int] = None):
    """zip 写盘文件级互斥锁（上下文管理器）

    同一 zip 同一时刻只允许一个进程写：写盘前加锁，写盘完成（含 os.replace
    原子替换）后释放；不同 zip 的锁文件不同，互不阻塞。

    Args:
        zip_path: 目标 zip/cbz 文件路径
        attempts: 锁冲突最多尝试轮数（默认 ZIP_LOCK_ATTEMPTS=60）
        wait_ms: 每轮等待毫秒（默认 ZIP_LOCK_WAIT_MS=2000，总窗口 120s）

    Yields:
        bool: True 已获锁；False 超时（已打印醒目提示，调用方应跳过并记失败）
    """
    lock_path = _zip_lock_path(zip_path)
    held = _tls_held()
    if lock_path in held:
        # 同线程嵌套获取同一把锁（如 7z 路径 → 回退 → _add_with_zipfile）：
        # O_EXCL 锁不可重入，用引用计数直接放行
        held[lock_path] += 1
        try:
            yield True
        finally:
            held[lock_path] -= 1
            if held[lock_path] <= 0:
                del held[lock_path]
        return

    attempts = ZIP_LOCK_ATTEMPTS if attempts is None else attempts
    wait_ms = ZIP_LOCK_WAIT_MS if wait_ms is None else wait_ms
    last_report = 0
    for attempt in range(attempts):
        if _try_acquire_lock(lock_path):
            break
        # 获取失败：先看是否是崩溃残留（PID 已死）→ 清掉立即重试
        _remove_stale_lock(lock_path)
        if _try_acquire_lock(lock_path):
            break
        if attempt + 1 < attempts:
            # 每 10s 打一次进度提示，让用户知道在等另一实例写盘而非卡死
            elapsed = int((attempt + 1) * wait_ms / 1000)
            if elapsed >= last_report + ZIP_LOCK_PROGRESS_EVERY_S:
                print(f"{thread_tag()} ⏳ 等待另一实例释放锁 {file_tag(zip_path)}... 已等待 {elapsed}s")
                last_report = elapsed
            time.sleep(wait_ms / 1000.0)
    else:
        # 120s 仍失败：对方大概率是异常卡死而非正常写盘（大卷写盘 2 分钟内必完成），
        # 跳过并记失败（调用方走 file_results 失败汇总），用户可稍后重试
        print(f"{thread_tag()} ⚠️ 文件被锁定超时，本次跳过，可稍后重试: {file_tag(zip_path)}")
        yield False
        return

    held[lock_path] = 1
    try:
        yield True
    finally:
        del held[lock_path]
        _release_lock(lock_path)


def zip_lock_multi(zip_paths: List[str]) -> Optional[ExitStack]:
    """对多个 zip 路径统一加锁（排序防死锁 + 去重）

    用于转换类写盘（如 _convert_zip_container 同时碰源文件与目标文件）：
    任一锁失败时释放已获取的全部锁并返回 None（提示已打印）。

    Returns:
        ExitStack: 调用方在 finally 中 close() 释放全部锁；失败返回 None
    """
    paths = sorted({os.path.normcase(os.path.abspath(p)) for p in zip_paths})
    stack = ExitStack()
    for p in paths:
        if not stack.enter_context(zip_lock(p)):
            stack.close()
            return None
    return stack


def thread_tag() -> str:
    """写盘日志线程标识前缀，如 [Dummy-2/1a2b3c4d]

    并发写盘（多个 SaveThread 同时写同一批 zip）时日志需能区分是哪个线程在
    读写哪个文件。线程名（QThread 场景下 Python 侧为 Dummy-N）+ 线程 id
    短 hex 唯一确定一个线程；同一写盘链路上各模块调用它得到的值一致，
    便于跨模块串起一个线程的完整读写过程。
    """
    return f"[{threading.current_thread().name}/{threading.get_ident():x}]"


def file_tag(zip_path: str) -> str:
    """写盘日志文件标识：系列文件夹名/文件名，如 [宫崎摩耶系列/Vol 08.zip]

    比纯 basename 更能定位「是哪套书」：同名 Vol 08.zip 在不同系列文件夹下
    无法区分，带上层文件夹名（通常是系列名）即可唯一辨识。zip_path 在盘根
    等无上层目录名时退化为显示盘符/目录路径。
    """
    folder = os.path.basename(os.path.dirname(zip_path)) or os.path.dirname(zip_path)
    return f"[{folder}/{os.path.basename(zip_path)}]"


def process_short_story_folder(folder_path: str, folder_info: Dict, depth: int = 0) -> Dict:
    """处理短篇文件夹
    
    Args:
        folder_path: 文件夹路径
        folder_info: 文件夹信息
        depth: 当前深度
        
    Returns:
        Dict: 处理结果
    """
    print(f"{'  ' * depth}📋 检测到短篇内容，跳过Bangumi查询")
    
    # 创建XML模板处理器
    template_handler = create_xml_template_handler()
    comic_info_base = template_handler.create_base_template(folder_info, is_short_story=True)
    
    # 设置模拟结果
    selected_result = {"id": 0, "name": folder_info["series"], "name_cn": folder_info["series"]}
    
    return {
        "comic_info_base": comic_info_base,
        "selected_result": selected_result,
        "skip_files": False
    }




def process_xml_modify_folder(folder_path: str, folder_info: Dict, depth: int = 0) -> Dict:
    """从XML文件中读取元数据（修正模式）
    
    Args:
        folder_path: 文件夹路径
        folder_info: 文件夹信息
        depth: 当前深度
        
    Returns:
        Dict: 处理结果
    """
    print(f"{'  ' * depth}📖 从XML文件读取元数据")
    
    from processors.zip_handler import read_xml_from_zip
    from processors.xml_template_handler import create_xml_template_handler
    
    # 尝试从文件夹中的第一个ZIP文件读取XML
    comic_info_base = None
    xml_source_file = None
    
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        if not os.path.isfile(file_path):
            continue
        if not filename.lower().endswith(('.zip', '.cbz', '.cbr', '.rar')):
            continue
        
        # 尝试读取XML
        xml_data = read_xml_from_zip(file_path)
        if xml_data:
            comic_info_base = xml_data
            xml_source_file = filename
            print(f"{'  ' * depth}  ✅ 从 {filename} 读取到XML数据")
            break
    
    if not comic_info_base:
        print(f"{'  ' * depth}❌ 未找到有效的XML文件，使用本地信息")
        # 如果没有找到XML，使用本地信息
        template_handler = create_xml_template_handler()
        comic_info_base = template_handler.create_local_template(folder_info)
    
    # 设置模拟结果
    selected_result = {
        "id": comic_info_base.get("Web", "").split("/")[-1] if comic_info_base.get("Web") else "",
        "name": comic_info_base.get("Series", folder_info["series"]),
        "name_cn": comic_info_base.get("Series", folder_info["series"])
    }
    
    return {
        "comic_info_base": comic_info_base,
        "selected_result": selected_result,
        "skip_files": False,
        "xml_source_file": xml_source_file
    }




def check_all_files_have_xml(folder_path: str) -> bool:
    """检查文件夹下所有ZIP文件是否都已包含XML文件
    
    Args:
        folder_path: 文件夹路径
        
    Returns:
        bool: 是否所有文件都已包含XML
    """
    import zipfile
    
    try:
        # 获取文件夹下所有ZIP文件
        zip_files = [f for f in os.listdir(folder_path) 
                    if f.endswith('.zip') or f.endswith('.cbz') or f.endswith('.cbr') or f.endswith('.rar')]
        
        if not zip_files:
            return False  # 没有ZIP文件，需要处理
        
        # 检查每个ZIP文件是否包含ComicInfo.xml
        for zip_file in zip_files:
            zip_path = os.path.join(folder_path, zip_file)
            
            try:
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    file_list = zf.namelist()
                    
                    # 检查是否有ComicInfo.xml文件
                    if 'ComicInfo.xml' not in file_list:
                        return False  # 至少有一个文件没有XML
            except Exception:
                # 如果无法打开ZIP文件，假设需要处理
                return False
        
        # 所有文件都包含XML
        return True
        
    except Exception as e:
        print(f"⚠️  检查文件夹XML状态失败: {str(e)[:50]}")
        return False  # 出错时假设需要处理


        # 统计结果
    print("\n" + "="*80)
    print("📊 批量处理完成 - 统计结果")
    print(f"📁 总文件夹数: {total_folders}")
    print(f"✅ 自动处理: {auto_processed} | 手动处理: {manual_processed} | 跳过: {skipped}")
    print(f"📄 文件统计: 总计{total_files}个 | 成功{success_files}个")
    print(f"💡 成功率: {success_files/total_files*100:.1f}%" if total_files > 0 else "💡 无文件处理")
    print("="*80)


