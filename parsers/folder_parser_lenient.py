#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
宽松文件夹名解析（parse_folder_name_lenient，2026-08-06 用户规则，2026-08-09 括号 tag 规则）
从 folder_parser 拆出：仅 lenient 解析器及其私有常量/辅助函数。
"""

import re

# =====================================================================
# 卷标正则：V/Vol/volume/卷/册/期/C/chapter + 数字/中文数字/全角数字。
# V04（V 直接跟数字）与 Vol.1 分开写；C97 是展会码（tag），C1-C9 才是卷标；支持 第01-12巻。
# =====================================================================
VOL_RE = re.compile(
    r"(?:"
    r"[Vv][Oo][Ll][Uu][Mm][Ee]\.?\s*[0-9０-９一二三四五六七八九十百]+|"
    r"[Vv][Oo][Ll]\.?\s*[0-9０-９一二三四五六七八九十百]+|"
    r"(?<![A-Za-z0-9])[Vv][0-9０-９]+|"
    r"[Cc][Hh][Aa][Pp][Tt][Ee][Rr]\.?\s*[0-9０-９]+|"
    r"[Cc][Hh]\.?\s*[0-9０-９]+|"
    r"(?<![A-Za-z0-9])[Cc][0-9０-９](?![0-9０-９])|"
    r"第\s*[0-9０-９一二三四五六七八九十百]+(?:\s*[-~—至]\s*[0-9０-９一二三四五六七八九十百]+)?\s*[巻卷话話]|"
    r"[0-9０-９一二三四五六七八九十百]+\s*[巻卷]|"
    r"[0-9０-９]+\s*[册冊]|[0-9０-９]+\s*[话話]|"
    r"[巻卷册冊话話]\s*[0-9０-９一二三四五六七八九十百]+"
    r")",
    re.IGNORECASE,
)
# 黑名单词表：命中 → tag（语言/版本/来源/类型），不参与搜索
TAG_BLACKLIST = {
    "日", "中", "英", "汉", "繁", "简",
    "双语", "日文", "中文", "英文", "简中", "繁中", "日文原版", "日文版", "中文版", "英文版",
    "日版", "台版", "港版", "大陆版", "国漫", "日漫",
    "完全版", "爱藏版", "电子版", "文库版", "新装版", "纪念版", "收藏版", "典藏版",
    "全彩", "彩色版", "黑白", "扫描版", "修复版", "高清", "dx", "digital", "colored",
    "color", "full color", "remastered", "raw", "scan", "scans", "scanlation", "scanlator",
    "汉化", "汉化组", "生肉", "自购", "扫图", "自扫", "转载", "精排", "修复", "民间汉化",
    "完结", "连载中", "连载", "短篇", "短篇集", "单行本", "画集", "原画集", "设定集", "公式书",
    "番外", "外传", "特别篇", "总集篇", "同人", "合集", "精选集", "别册", "complete", "completed", "ongoing",
    "授权版", "官方", "台版授权",
}
COMPLETE_WORDS = ("全", "完结", "完", "end", "completed", "fin", "complete")
# 章节型完结：整个圆括号内容仅为 C+数字+全/完结（如 C07全 / C12完结）。
# VOL_RE 的 C 分支只认 C1-C9 一位数（防 C97 展会码误判），故 C07 以上单独判定。
_CHAPTER_DONE_RE = re.compile(r"^[Cc]\s*([0-9]{1,4})\s*(?:全|完结)$")
_HINTS_COMPLETE = ("完结", "end", "completed", "fin", "complete")   # tag 分支只认多字词
_HINTS_ONGOING = ("未完结", "连载中", "ongoing", "未完")   # 「连载」是版本属性（连载版）非连载状态，不列入
_CN_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "零": 0}
_BRACKET_OPEN = set("[（(")
_BRACKET_CLOSE = set("]）)")


def _to_halfwidth(text):
    """全角字母/数字转半角"""
    out = []
    for ch in text:
        code = ord(ch)
        if code == 0x3000:
            out.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


def _extract_numbers(text):
    """提取卷标文本中的数字（含中文/全角数字）"""
    half = _to_halfwidth(text)
    nums = [int(d) for d in re.findall(r"\d+", half)]
    if not nums:
        m = re.search(r"[一二三四五六七八九十百零]+", half)
        if m:
            total = current = 0
            for ch in m.group(0):
                if ch in "十拾":
                    current = current * 10 if current else 10
                    total += current
                    current = 0
                elif ch in "百佰":
                    current = current * 100 if current else 100
                    total += current
                    current = 0
                else:
                    current += _CN_DIGITS.get(ch, 0)
            nums = [total + current]
    return nums


def _is_tag_content(text):
    """判断括号内容是否为 tag（黑名单命中、展会码 C97/C99/C100、或缺卷说明 缺...）"""
    t = text.strip()
    if not t:
        return False
    if t in TAG_BLACKLIST or t.startswith("缺") or re.match(r"^C\d{2,3}$", t, re.IGNORECASE):
        return True
    low = t.lower()
    return any(len(w) > 1 and w in low for w in TAG_BLACKLIST)


def _scan_brackets(text):
    """返回最外层括号组 (start, end, open_char)，支持嵌套"""
    spans = []
    i, n = 0, len(text)
    while i < n:
        if text[i] in _BRACKET_OPEN:
            open_char = text[i]
            depth = 1
            j = i + 1
            while j < n and depth > 0:
                if text[j] in _BRACKET_OPEN:
                    depth += 1
                elif text[j] in _BRACKET_CLOSE:
                    depth -= 1
                j += 1
            spans.append((i, j, open_char))
            i = j
        else:
            i += 1
    return spans


def _split_nested(content, open_char=None):
    """拆分可能嵌套的括号内容 → [(piece, bracket_char)]；bracket_char 继承最外层括号类型"""
    spans = _scan_brackets(content)
    if not spans:
        return [(content, open_char)]
    innermost, leftovers, last = [], [], 0
    for start, end, _ in spans:
        piece = content[last:start].strip()
        if piece:
            leftovers.append((piece, open_char))
        innermost.extend(_split_nested(content[start + 1:end - 1], open_char))
        last = end
    tail = content[last:].strip()
    if tail:
        leftovers.append((tail, open_char))
    return innermost + leftovers


def _split_round_tags(c):
    """圆括号无卷号内容按空格拆分成 tags（+ 保留），返回 (tags, extras, complete_hint, ongoing_hint)"""
    tags, extras = [], []
    complete_hint = ongoing_hint = False
    for seg in c.split():
        if not seg:
            continue
        if "+" in seg:
            pieces = seg.split("+")
            for i, piece in enumerate(pieces):
                piece = piece.strip()
                if not piece:
                    continue
                tag = piece if i == 0 else "+" + piece
                if tag not in tags:
                    tags.append(tag)
                if i >= 1 and piece not in extras:
                    extras.append(piece)
        else:
            tags.append(seg)
        low = seg.lower()
        if any(w in low for w in _HINTS_COMPLETE):
            complete_hint = True
        if any(w in low for w in _HINTS_ONGOING):
            ongoing_hint = True
    return tags, extras, complete_hint, ongoing_hint


def _apply_vol_info(c, vol_text, total_volumes):
    """卷标文本 → (total_volumes, complete, vol_type)：提取数字、按内容判断完结"""
    nums = _extract_numbers(vol_text)
    if nums:
        total_volumes = max(total_volumes, max(nums))
    if any(w in c.lower() for w in COMPLETE_WORDS):
        return total_volumes, True, "已完结"
    return total_volumes, False, "连载"


def _extract_inline_volume(text):
    """剥离正文内联卷标 → (剥离后文本, 卷标文本, 数字列表)"""
    matches = list(VOL_RE.finditer(text))
    if not matches:
        return text, None, []
    numbers = []
    for m in matches:
        numbers.extend(_extract_numbers(m.group(0)))
    stripped = re.sub(r"\s+", " ", (text[:matches[0].start()] + text[matches[-1].end():]).strip())
    return stripped.strip(" -–—·|"), text[matches[0].start():matches[-1].end()].strip(), numbers


def parse_folder_name_lenient(folder_name, folder_path=None):
    """宽松解析文件夹名（2026-08-06 规则），兼容多种主流格式。

    返回与 parse_folder_name 兼容的 dict，并新增 tags 字段。
    括号规则（2026-08-09）：圆括号内 V 卷号之后的全部内容 → 按空格拆分成 tags，`+` 保留；
    方括号仍按既有逻辑（别名 / tag 黑名单识别）。
    """
    name = (folder_name or "").strip()
    if not name:
        return None
    # 作者 = 第一个 [..]（无作者容忍）；[标题][作者][卷]… 相邻两括号 → U2 格式
    leading, rest, author = [], name, ""
    for _ in range(2):
        m = re.match(r"^\[([^\[\]]*)\]", rest)
        if not m:
            break
        leading.append(m.group(1).strip())
        rest = rest[m.end():].strip()
    series_prefix = leading[0] if len(leading) == 2 else ""
    if leading:
        author = leading[1] if len(leading) == 2 else leading[0]
    # 括号分组（嵌套取最内层，带最外层括号类型）+ 非括号片段
    spans = _scan_brackets(rest)
    candidates = []
    for start, end, open_char in spans:
        candidates += _split_nested(rest[start + 1:end - 1], open_char)
    plain_parts, last = [], 0
    for start, end, _open_char in spans:
        plain_parts.append(rest[last:start])
        last = end
    plain_parts.append(rest[last:])
    # 主名：作者后、下一个括号前的内容原样保留；为空时取末尾残留
    if series_prefix:
        series_name = series_prefix
    else:
        series_raw = (plain_parts[0] if plain_parts else rest).strip()
        if not series_raw:
            series_raw = next((p.strip() for p in reversed(plain_parts) if p.strip()), "")
        series_name = _extract_inline_volume(series_raw)[0].strip()
    # 分类括号内容：方括号 → 别名/tag 既有逻辑；圆括号 → 卷号后内容全部进 tag（+ 保留）
    aliases, tags, extras = [], [], []
    vol_info = None
    total_volumes = 0
    complete = False
    vol_type = "连载"
    complete_hint = ongoing_hint = False
    for content, open_char in candidates:
        c = content.strip()
        if not c:
            continue
        is_square = open_char == "["
        tags += [p for p in c.split() if p.startswith("缺")]  # 缺卷说明 → tag（如 缺V21）
        c = " ".join(p for p in c.split() if not p.startswith("缺")).strip()
        if not c:
            continue
        if c == "短篇":
            vol_info, total_volumes, vol_type, complete = c, 1, "短篇", False
            continue
        if not is_square:                          # 章节型完结：(C07全)/(C12完结) → 卷数=数字且完结，不进 tag
            mc = _CHAPTER_DONE_RE.match(_to_halfwidth(c))
            if mc:
                vol_info = c
                total_volumes = max(total_volumes, int(mc.group(1)))
                complete, vol_type = True, "已完结"
                continue
        m = VOL_RE.search(c)
        if m and is_square:                       # 方括号卷标：整段作 vol_info
            vol_info = c
            if "+" in c:                          # V02全+原画集 → 附加内容（可作 tag）
                for ep in (p.strip() for p in c.split("+")[1:]):
                    if ep:
                        extras.append(ep)
                        if ep not in tags:
                            tags.append(ep)
            total_volumes, complete, vol_type = _apply_vol_info(c, c, total_volumes)
        elif m:                                   # 圆括号卷标：只取卷号，其余进 tag
            vol_text = m.group(0)
            after = c[m.end():]
            for w in sorted(COMPLETE_WORDS, key=len, reverse=True):  # V08全 并入卷号
                if after.lower().startswith(w):
                    vol_text += after[:len(w)]
                    after = after[len(w):]
                    break
            vol_info = vol_text
            total_volumes, complete, vol_type = _apply_vol_info(c, vol_text, total_volumes)
            rest = (c[:m.start()] + " " + after).strip()
            if rest:
                seg_tags, seg_extras, ch, oh = _split_round_tags(rest)
                tags += seg_tags
                extras += seg_extras
                complete_hint |= ch
                ongoing_hint |= oh
        elif not is_square:                       # 无卷号圆括号 → 全部进 tag（+ 保留）
            seg_tags, seg_extras, ch, oh = _split_round_tags(c)
            tags += seg_tags
            extras += seg_extras
            complete_hint |= ch
            ongoing_hint |= oh
        elif _is_tag_content(c):
            tags.append(c)
            low = c.lower()
            if any(w in low for w in _HINTS_COMPLETE):
                complete_hint = True
            if any(w in low for w in _HINTS_ONGOING):
                ongoing_hint = True
        else:
            aliases.append(c)
    # 非括号片段中的内联卷标（第01-12巻 / V01 / Vol.16 - Vol.17）
    inline_vol = None
    for part in plain_parts:
        _, vt, nums = _extract_inline_volume(part)
        if vt:
            inline_vol = inline_vol or vt
            for n in nums:
                total_volumes = max(total_volumes, n)
    if vol_info is None and inline_vol:
        vol_info = inline_vol
    # 完结判定：无「全/完结」字样 → 默认未完结（连载）
    if vol_info is None:
        if complete_hint and not ongoing_hint:
            complete, vol_type = True, "已完结"
        else:
            complete, vol_type = False, "连载"
    elif vol_type != "短篇" and complete_hint and not ongoing_hint:
        complete, vol_type = True, "已完结"
    elif vol_type != "短篇" and ongoing_hint:
        complete, vol_type = False, "连载"
    extras = list(dict.fromkeys(extras))
    aliases = list(dict.fromkeys(a for a in aliases if a))
    tags = list(dict.fromkeys(tags))
    return {
        "author": author,
        "series": series_name,
        "aliases": aliases,
        "tags": tags,
        "vol_info": vol_info,
        "total_volumes": total_volumes,
        "vol_type": vol_type,
        "complete": complete,
        "has_extras": bool(extras),
        "extras": "+".join(extras),
    }
