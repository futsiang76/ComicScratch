#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置文件 - 所有常量、配置和正则表达式模式

用户可配置设置（API Key/阈值/超时/保存格式等）持久化在 user_config.json
（项目根，gitignore 不入库）。启动时从该文件读取，缺失字段用默认值；
secrets.py 仅作为 API Key 的 legacy fallback（user_config 未配置时才读取）。
"""

import json
import os

# ===================== 用户设置持久化 =====================
USER_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "user_config.json")

# 用户可配置项默认值（user_config.json 缺失字段时使用）
DEFAULT_SETTINGS = {
    "bangumi_access_token": "",
    "comicvine_api_key": "",
    "fuzz_threshold": 85,          # 作品名模糊匹配阈值
    "author_match_threshold": 70,  # 作者名匹配阈值（任一作者≥70即匹配）
    "timeout": 15,                 # 请求超时时间
    "max_retries": 3,              # 请求重试次数
    "crop_memory_enabled": True,   # 封面裁剪定位记忆开关（默认开启）
    "save_format": "keep",         # 保存格式：keep/cbz/zip/cb7
    "delete_after_convert": True,  # 手动格式转换成功后是否删除原文件
    "default_manga_dir": "",       # 默认漫画目录（留空则启动时提示选择）
    "remember_last_path": True,    # 记住上次路径开关（开启则启动优先用上次目录）
    # 多系列扫描忽略规则：命中通配符的目录不作为系列处理且不再递归
    # （fnmatch 通配：* 任意字符 ? 单字符 [abc] 字符集；匹配目录名本身，不分大小写）
    "scan_ignore_dirs": [".*", "_*"],
    "first_run_done": False,       # 首次启动轻引导是否已完成（完成后不再弹出）
    # 赞助通道（发布者配置；留空=不显示赞助入口）
    "sponsor_enabled": False,      # 是否启用赞助入口（齿轮菜单显示「赞助支持」）
    "sponsor_qr_path": "",         # 收款码图片路径（单码，兼容旧配置；如 assets/sponsor_qr.png）
    "sponsor_qr_codes": [],        # 收款码列表（多码并排）：[{"name": "支付宝", "path": "assets/xx.jpg"}, ...]
    "sponsor_text": "",            # 赞助文案（留空用默认文案）
    "sponsor_url": "",             # 可选外部赞助链接（爱发电/Ko-fi/GitHub Sponsor 等）
    "sponsor_close_confirm": True, # 关闭时确认框带赞助提示（可关）
    "sponsor_close_count": 0,      # 关闭计数（每 N 次弹感谢窗，勿手改）
    # Bangumi API 镜像列表（官方优先；官方被墙时自动降级到社区镜像）
    "bangumi_mirrors": [
        "https://api.bgm.tv",          # 官方（海外/可直连用户）
        "https://api.bangumi.lol",     # 社区镜像1（大陆可用）
        "https://bgmapi.anibt.net",    # 社区镜像2（备胎，随时可能下线）
    ],
}


def _read_user_config() -> dict:
    """读取 user_config.json；文件缺失或内容损坏时返回空 dict"""
    try:
        with open(USER_CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_settings() -> dict:
    """读取 user_config.json 并返回完整设置字典（缺失字段补默认值）

    Returns:
        dict: 全部用户设置（键见 DEFAULT_SETTINGS）
    """
    settings = dict(DEFAULT_SETTINGS)
    settings.update(_read_user_config())
    return settings


def save_settings(settings: dict) -> None:
    """将用户设置合并写入 user_config.json（保留文件里已有字段）

    同时把新值同步到 config 模块属性，保存后立即生效（无需重启）。

    Args:
        settings: 部分或全部用户设置；未知键会被忽略
    """
    data = load_settings()
    data.update({key: value for key, value in settings.items()
                 if key in DEFAULT_SETTINGS})
    try:
        with open(USER_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"🔴 保存用户设置失败: {str(e)[:100]}")
    apply_settings(data)


# 设置键 → config 模块属性名
SETTINGS_ATTR_MAP = {
    "bangumi_access_token": "BANGUMI_ACCESS_TOKEN",
    "comicvine_api_key": "COMICVINE_API_KEY",
    "fuzz_threshold": "FUZZ_THRESHOLD",
    "author_match_threshold": "AUTHOR_MATCH_THRESHOLD",
    "timeout": "TIMEOUT",
    "max_retries": "MAX_RETRIES",
    "crop_memory_enabled": "CROP_MEMORY_ENABLED",
    "save_format": "SAVE_FORMAT",
    "delete_after_convert": "DELETE_AFTER_CONVERT",
    "default_manga_dir": "DEFAULT_MANGA_DIR",
    "remember_last_path": "REMEMBER_LAST_PATH",
    "scan_ignore_dirs": "SCAN_IGNORE_DIRS",
    "first_run_done": "FIRST_RUN_DONE",
    "sponsor_enabled": "SPONSOR_ENABLED",
    "sponsor_qr_path": "SPONSOR_QR_PATH",
    "sponsor_qr_codes": "SPONSOR_QR_CODES",
    "sponsor_text": "SPONSOR_TEXT",
    "sponsor_url": "SPONSOR_URL",
    "sponsor_close_confirm": "SPONSOR_CLOSE_CONFIRM",
    "sponsor_close_count": "SPONSOR_CLOSE_COUNT",
    "bangumi_mirrors": "BANGUMI_MIRRORS",
}


def apply_settings(settings: dict) -> None:
    """把设置同步到 config 模块属性（写入文件后调用，立即生效）

    Args:
        settings: 设置字典（键必须是 DEFAULT_SETTINGS 中的键）
    """
    for key, attr in SETTINGS_ATTR_MAP.items():
        if key in settings:
            globals()[attr] = settings[key]


def _legacy_api_key(name: str) -> str:
    """从 secrets.py 读取 legacy API Key（user_config 为空时的降级源）"""
    try:
        import secrets
        return str(getattr(secrets, name, "") or "").strip()
    except (ImportError, AttributeError):
        return ""


def _api_key_from_config(key: str, legacy_name: str) -> str:
    """解析 API Key：user_config.json 优先，其次 secrets.py legacy 降级"""
    value = str(_user_config.get(key, "") or "").strip()
    if value:
        return value
    return _legacy_api_key(legacy_name)


# ===================== 应用信息 =====================
APP_NAME = "ComicScratch"
APP_VERSION = "1.0.0"

# ===================== 核心配置 =====================
# 启动时从 user_config.json 加载（设置对话框保存时直接改写这些模块属性）
_user_config = _read_user_config()

BANGUMI_ACCESS_TOKEN = _api_key_from_config("bangumi_access_token",
                                            "BANGUMI_ACCESS_TOKEN")
COMICVINE_API_KEY = _api_key_from_config("comicvine_api_key",
                                         "COMICVINE_API_KEY")
FUZZ_THRESHOLD = _user_config.get("fuzz_threshold",
                                  DEFAULT_SETTINGS["fuzz_threshold"])
AUTHOR_MATCH_THRESHOLD = _user_config.get("author_match_threshold",
                                          DEFAULT_SETTINGS["author_match_threshold"])
TIMEOUT = _user_config.get("timeout", DEFAULT_SETTINGS["timeout"])
MAX_RETRIES = _user_config.get("max_retries", DEFAULT_SETTINGS["max_retries"])
CROP_MEMORY_ENABLED = _user_config.get("crop_memory_enabled",
                                       DEFAULT_SETTINGS["crop_memory_enabled"])
SAVE_FORMAT = _user_config.get("save_format", DEFAULT_SETTINGS["save_format"])
DELETE_AFTER_CONVERT = _user_config.get("delete_after_convert",
                                        DEFAULT_SETTINGS["delete_after_convert"])
DEFAULT_MANGA_DIR = _user_config.get("default_manga_dir",
                                     DEFAULT_SETTINGS["default_manga_dir"])
REMEMBER_LAST_PATH = _user_config.get("remember_last_path",
                                      DEFAULT_SETTINGS["remember_last_path"])
# 多系列扫描忽略规则（fnmatch 通配符列表，命中目录不作为系列且不递归）
_scan_ignore_cfg = _user_config.get("scan_ignore_dirs",
                                    DEFAULT_SETTINGS["scan_ignore_dirs"])
SCAN_IGNORE_DIRS = _scan_ignore_cfg if isinstance(_scan_ignore_cfg, list) \
    else list(DEFAULT_SETTINGS["scan_ignore_dirs"])
FIRST_RUN_DONE = _user_config.get("first_run_done",
                                  DEFAULT_SETTINGS["first_run_done"])

# 赞助通道（发布者配置：收款码/文案/外链；sponsor_enabled=True 时齿轮菜单显示入口）
SPONSOR_ENABLED = _user_config.get("sponsor_enabled",
                                   DEFAULT_SETTINGS["sponsor_enabled"])
SPONSOR_QR_PATH = _user_config.get("sponsor_qr_path",
                                   DEFAULT_SETTINGS["sponsor_qr_path"])
SPONSOR_QR_CODES = _user_config.get("sponsor_qr_codes",
                                    DEFAULT_SETTINGS["sponsor_qr_codes"])
SPONSOR_TEXT = _user_config.get("sponsor_text",
                                DEFAULT_SETTINGS["sponsor_text"])
SPONSOR_URL = _user_config.get("sponsor_url",
                               DEFAULT_SETTINGS["sponsor_url"])
SPONSOR_CLOSE_CONFIRM = _user_config.get("sponsor_close_confirm",
                                         DEFAULT_SETTINGS["sponsor_close_confirm"])
SPONSOR_CLOSE_COUNT = _user_config.get("sponsor_close_count",
                                       DEFAULT_SETTINGS["sponsor_close_count"])

# Bangumi API 镜像列表：user_config.json 可覆盖；非法值（非列表/空）回退默认
_mirrors_cfg = _user_config.get("bangumi_mirrors",
                                DEFAULT_SETTINGS["bangumi_mirrors"])
BANGUMI_MIRRORS = _mirrors_cfg if (isinstance(_mirrors_cfg, list) and _mirrors_cfg) \
    else list(DEFAULT_SETTINGS["bangumi_mirrors"])

# Bangumi 数据源标识：gui 数据源下拉值 ↔ fetcher 直连域名映射
# （官方 api.bgm.tv；镜像 api.bangumi.lol，大陆可用）
BANGUMI_SOURCE_OFFICIAL = "bangumi"
BANGUMI_SOURCE_MIRROR = "bangumi_mirror"

# 数据源下拉显示名（gui 下拉项 ↔ scan_controller 路由；manhuagui 排最后）
SOURCE_BANGUMI_TEXT = "Bangumi（官方）"
SOURCE_BANGUMI_MIRROR_TEXT = "Bangumi（大陆镜像）"
SOURCE_COMICVINE_TEXT = "ComicVine（欧美漫）"
SOURCE_MANHUAGUI_TEXT = "manhuagui"

# 保存格式 → 目标扩展名（None 表示保持原格式）
SAVE_FORMAT_EXT = {
    "keep": None,   # zip/cbz 原地写；rar/cbr/7z 自动转 .cbz 并保留原文件
    "cbz": ".cbz",  # 统一转 .cbz（zip 容器，zipfile 写）
    "zip": ".zip",  # 统一转 .zip（zip 容器，zipfile 写）
    "cb7": ".cb7",  # 统一转 .cb7（7z 容器，7z.exe 写）
}

# ===================== 运行模式常量 =====================
SHOW_TOP_N = 10               # 手动选择时显示前N个结果
WAITING_TIME = 0             # 等待用户输入的时间（秒），0表示无限等待
MODE_SKIP_XMLEXIST = 0        # 跳过已有XML文件的模式：0=按现有全匹配策略修改，1=有XML就跳过，2=只处理已有XML的文件（修正模式）
AUTO_TURBO_MATCH = 0          # 无人值守快速模式：0=关闭，1=开启（仅当唯一匹配结果时自动处理）

# ===================== XML模板配置 =====================
COMICINFO_TEMPLATE = {
    "Title": "",           # 标题
    "Series": "",          # 系列名
    "Volume": "",          # 单本书卷数
    "Number": "",          # 单话编号（用于单话文件）
    "Count": "",           # 系列总卷数（已完结填写，连载中留空）
    "Summary": "",         # 简介
    "Notes": "",           # 备注
    "Year": "",            # 年份
    "Month": "",           # 月份
    "Day": "",             # 日（单行本发售日；取不到留空，XML 中整行不写）
    "Writer": "",          # 编剧
    "Penciller": "",       # 画师
    "Inker": "",           # 墨线师
    "Colorist": "",        # 上色师
    "Letterer": "",        # 字母师
    "CoverArtist": "",     # 封面画师
    "Editor": "",          # 编辑
    "Publisher": "",       # 出版社
    "Genre": "",            # 类型
    "Web": "",             # 网址
    "PageCount": "",       # 页数
    "LanguageISO": "zh-CN", # 语言代码
    "Format": "Zip",       # 格式
    "BlackAndWhite": "",   # 是否黑白
    "Manga": "Yes",        # 是否漫画
    "AgeRating": "",       # 年龄分级
    "Tags": "",            # 标签
    "Status": "",          # 状态（Completed/Ongoing）
    "Rating": ""           # 评分
}

# 短篇特殊模板
SHORT_STORY_TEMPLATE = {
    **COMICINFO_TEMPLATE,
    "Count": "1",            # 短篇 = 一卷全
    "Volume": "",           # 短篇不显示单本书卷数
    "Summary": "短篇漫画",    # 短篇简介
    "Tags": "短篇",         # 短篇标签
    "Status": "Completed"    # 短篇默认已完成
}

# ===================== 正则表达式模式 =====================
# 匹配格式：[作者] 漫画名 (V05全) 或 [作者] 漫画名 (短篇全) 或 [作者] 漫画名 (V03全+设定集+番外) 或 [作者] 漫画名 第1部 (V03 C13)
# 兼容作者[]后没有空格的情况
FOLDER_PATTERN = r'^\[(?P<author>.+?)\]\s*(?P<series>.+?)(?:\s+第.+?)?\s*\((?P<vol_info>V\d+(?:\s+\w+)?|短篇)(?P<complete>全)?(?:[\s\+](?P<extras>.+?))?\)$'


# 文件名解析模式
VOL_PATTERN = r'(?:Vol\.?\s*(\d+)|V(\d+)|第\s*(\d+)\s*卷)'
CHAPTER_PATTERN = r'^(C(\d+)|第(\d+)话)'

# ===================== 额外内容关键词 =====================
EXTRA_KEYWORDS = ['设定集', '番外', '外传', '特典', '附录', '画集', '原画集']