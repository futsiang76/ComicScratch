#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
扫描目录忽略规则 - 所有扫描模式共用的目录过滤

多系列扫描时，部分目录不应被当作漫画系列处理（如 .git、_设定集、临时目录）。
本模块提供统一的通配符匹配判定，供 GUI 枚举（scan_controller）与
批量递归（folder_recursive_handler）共用。

通配符语法（fnmatch 风格）：
    *      匹配任意长度任意字符（含空）
    ?      匹配单个任意字符
    [abc]  匹配方括号内任一字符；[!abc] 取反；支持区间 [a-z]

规则只匹配【目录名本身】（不含路径层级），Windows 下不区分大小写。
默认规则 [" .*", "_*"]：以点开头或以下划线开头的目录一律跳过，
且不再递归进入其子目录（剪枝）。
"""

import fnmatch
from typing import Iterable, List, Tuple


def normalize_patterns(patterns: Iterable[str]) -> List[str]:
    """清洗规则列表：去空白、去空项、去重（保持顺序）"""
    seen = set()
    result: List[str] = []
    for p in patterns or []:
        p = str(p).strip()
        if p and p not in seen:
            seen.add(p)
            result.append(p)
    return result


def get_ignore_patterns() -> List[str]:
    """读取当前生效的忽略规则（config.SCAN_IGNORE_DIRS → 清洗）

    每次调用实时读 config 模块属性（不做模块级 from-import 绑定），
    设置对话框保存后立即生效，无需重启。
    显式清空规则 = 不忽略任何目录；仅属性缺失时回退默认值。
    """
    import config
    patterns = getattr(config, "SCAN_IGNORE_DIRS", None)
    if patterns is None:
        patterns = [".*", "_*"]
    return normalize_patterns(patterns)


def is_dir_ignored(dir_name: str, patterns: Iterable[str] = None) -> bool:
    """判断目录名是否命中忽略规则

    Args:
        dir_name: 目录名（仅名字，不带路径）
        patterns: 忽略规则列表；None 时读当前配置

    Returns:
        bool: True=应忽略该目录（含其整个子树）
    """
    if not dir_name:
        return False
    pats = get_ignore_patterns() if patterns is None else normalize_patterns(patterns)
    name_lower = dir_name.lower()
    for pat in pats:
        if fnmatch.fnmatch(name_lower, pat.lower()):
            return True
    return False


def filter_subdirs(dir_names: List[str], patterns: Iterable[str] = None,
                   log_fn=None) -> List[str]:
    """原地过滤 os.walk 的 dirs 列表（剪枝：命中的目录不再递归）

    用法：
        for root, dirs, files in os.walk(root):
            dirs[:] = filter_subdirs(dirs)

    Args:
        dir_names: 当前层目录名列表
        patterns: 忽略规则列表；None 时读当前配置
        log_fn: 可选日志回调，签名为 log_fn(dir_name)，记录被忽略的目录

    Returns:
        List[str]: 未命中规则的目录名（新列表，赋回 dirs 即完成剪枝）
    """
    kept: List[str] = []
    for d in dir_names:
        if is_dir_ignored(d, patterns):
            if log_fn:
                log_fn(d)
        else:
            kept.append(d)
    return kept


# 探测名集合：同时命中全部 → 判定规则"匹配一切目录"（用户常见误输入）
_PROBES = ("test", ".git", "_a", "Z9")


def _matches_everything(pattern: str) -> bool:
    """判断规则是否命中所有探测名（≈ 忽略一切目录的误输入，如单独的 *）"""
    low = pattern.lower()
    return all(fnmatch.fnmatch(p, low) for p in _PROBES)


def find_rule_issues(patterns: Iterable[str]) -> Tuple[List[str], List[str]]:
    """检查规则列表的问题，返回 (致命问题, 提示问题)

    致命（blocking）：会忽略一切目录的规则，保存后可能导致扫描结果为空；
    提示（warnings）：不影响运行但多半是用户误解，如路径分隔符/空规则。
    均在保存前由设置对话框展示，无问题返回 ([], [])。

    Args:
        patterns: 用户输入的原始规则列表（未清洗也可）

    Returns:
        Tuple[List[str], List[str]]: (致命问题列表, 提示问题列表)
    """
    pats = normalize_patterns(patterns)
    blocking: List[str] = []
    warnings: List[str] = []
    if not pats:
        warnings.append("未设置任何忽略规则（等价于不忽略任何目录）")
    for p in pats:
        if _matches_everything(p):
            blocking.append(f"规则“{p}”会匹配所有目录，可能导致扫描结果为空")
        if "/" in p or "\\" in p:
            warnings.append(
                f"规则“{p}”包含路径分隔符，但规则只匹配目录名本身，该规则不会生效")
    return blocking, warnings
