# -*- coding: utf-8 -*-
"""parse_folder_name_lenient 宽松解析 测试（2026-08-06 规则，本地验证，gitignored）"""
import pytest

from parsers.folder_parser import parse_folder_name_lenient, parse_folder_name


def _parse(name):
    result = parse_folder_name_lenient(name)
    assert result is not None, f"解析失败: {name}"
    return result


class TestUserFormat:
    """用户自用格式 [作者] 主名 [别名] (卷)"""

    def test_v04_recognized_as_volume(self):
        r = _parse("[河合孝典] 杀手餐厅 (V04)")
        assert r["author"] == "河合孝典"
        assert r["series"] == "杀手餐厅"
        assert r["vol_info"] == "V04"          # 关键：V 直接跟数字
        assert r["total_volumes"] == 4
        assert r["vol_type"] == "连载"
        assert r["complete"] is False

    def test_vol_dot_recognized_as_volume(self):
        r = _parse("[作者] 标题 (Vol.1)")
        assert r["vol_info"] == "Vol.1"
        assert r["total_volumes"] == 1

    def test_blue_lock_alias(self):
        r = _parse("[金城宗幸×野村优介] 蓝色监狱 [Blue Lock] (V23)")
        assert r["author"] == "金城宗幸×野村优介"
        assert r["series"] == "蓝色监狱"
        assert r["aliases"] == ["Blue Lock"]
        assert r["total_volumes"] == 23

    def test_multi_bracket_aliases(self):
        r = _parse("[黑乃奈奈绘] 和平捍卫队 铁 [新撰组异闻录 铁][Peace Maker II] (V05)")
        assert r["series"] == "和平捍卫队 铁"
        assert r["aliases"] == ["新撰组异闻录 铁", "Peace Maker II"]
        assert r["total_volumes"] == 5

    def test_kamui_series_kept_intact(self):
        # 关键：カムイ伝 第二部 主名完整（不截断成 伝）；缺V21 缺卷说明 → tag
        r = _parse("[白土三平] カムイ伝 第二部 [卡姆伊传 第二部] [日] (V22全 缺V21)")
        assert r["author"] == "白土三平"
        assert r["series"] == "カムイ伝 第二部"
        assert r["aliases"] == ["卡姆伊传 第二部"]
        assert r["tags"] == ["日", "缺V21"]   # [日] 归 tag；缺V21 缺卷说明 → tag
        assert r["vol_info"] == "V22全"        # V22全 仍是卷信息
        assert r["total_volumes"] == 22
        assert r["complete"] is True
        assert r["vol_type"] == "已完结"

    def test_missing_volume_goes_to_tag(self):
        # 缺卷说明（缺... 前缀）→ tag，不参与搜索（不进 aliases）
        r = _parse("[赤名修] 勇午 the Negotiator (缺东京种子岛篇)")
        assert r["series"] == "勇午 the Negotiator"
        assert r["aliases"] == []
        assert r["tags"] == ["缺东京种子岛篇"]
        assert r["vol_info"] is None

    def test_missing_volume_chinese_volume(self):
        # 缺第3卷 命中卷标正则但为缺卷说明 → tag，不进 vol_info
        r = _parse("[作者] 标题 (缺第3卷)")
        assert r["tags"] == ["缺第3卷"]
        assert r["vol_info"] is None
        assert r["total_volumes"] == 0

    def test_short_story(self):
        r = _parse("[比良贺みん也] 化身者 (短篇)")
        assert r["series"] == "化身者"
        assert r["vol_info"] == "短篇"         # 无卷号 → 短篇
        assert r["vol_type"] == "短篇"
        assert r["total_volumes"] == 1
        assert r["complete"] is False

    def test_volume_with_extras_complete(self):
        # 关键：(V02全+原画集) 卷=2 完结，+原画集 为附加内容
        r = _parse("[士郎正宗] 攻壳机动队 (V02全+原画集)")
        assert r["series"] == "攻壳机动队"
        assert r["total_volumes"] == 2
        assert r["complete"] is True
        assert r["vol_type"] == "已完结"
        assert r["extras"] == "原画集"
        assert r["has_extras"] is True
        assert "+原画集" in r["tags"]  # + 保留在 tag 里（2026-08-09 括号 tag 规则）

    def test_extras_selection(self):
        r = _parse("[田中政志] 小恐龙阿冈GON (V07全+精选集)")
        assert r["series"] == "小恐龙阿冈GON"
        assert r["total_volumes"] == 7
        assert r["extras"] == "精选集"
        assert r["complete"] is True

    def test_extras_shijiao(self):
        r = _parse("[赤人义一] 尸姬 (V23全+尸解教典)")
        assert r["series"] == "尸姬"
        assert r["total_volumes"] == 23
        assert r["extras"] == "尸解教典"
        assert r["complete"] is True

    def test_greek_letter_series(self):
        r = _parse("[贺东招二×上田宏] 惊爆危机 Σ [全金属狂潮 Σ] (V19全)")
        assert r["series"] == "惊爆危机 Σ"
        assert r["aliases"] == ["全金属狂潮 Σ"]
        assert r["total_volumes"] == 19
        assert r["complete"] is True

    def test_plain_complete_series(self):
        r = _parse("[井上雄彦] 灌篮高手 (V31全)")
        assert r["series"] == "灌篮高手"
        assert r["total_volumes"] == 31
        assert r["complete"] is True


class TestRoundBracketTags:
    """2026-08-09 括号 tag 规则：圆括号内 V 卷号后的全部内容 → 按空格拆成 tags，+ 保留"""

    def test_plus_extra_tag(self):
        r = _parse("[作者] 作品 (+原画集)")
        assert r["tags"] == ["+原画集"]
        assert r["aliases"] == []

    def test_no_volume_single_tag(self):
        # (单话版本) 之前进 aliases，现在进 tags
        r = _parse("[作者] 作品 (单话版本)")
        assert r["tags"] == ["单话版本"]
        assert r["aliases"] == []

    def test_volume_plus_extra(self):
        r = _parse("[作者] 作品 (V08 +原画集)")
        assert r["vol_info"] == "V08"
        assert r["tags"] == ["+原画集"]
        assert r["total_volumes"] == 8

    def test_volume_single_tag(self):
        r = _parse("[作者] 作品 (V08 单话版本)")
        assert r["vol_info"] == "V08"
        assert r["tags"] == ["单话版本"]

    def test_volume_multi_tags(self):
        r = _parse("[作者] 作品 (V08 原画集 外传)")
        assert r["vol_info"] == "V08"
        assert r["tags"] == ["原画集", "外传"]

    def test_no_volume_multi_tags_split(self):
        r = _parse("[作者] 作品 (原画集 外传)")
        assert r["tags"] == ["原画集", "外传"]
        assert r["aliases"] == []

    def test_missing_volume_plus_tag(self):
        r = _parse("[作者] 作品 (缺V21 原画集)")
        assert r["tags"] == ["缺V21", "原画集"]
        assert r["vol_info"] is None


class TestExternalFormats:
    """外部主流格式：至少能提取出主名/卷号"""

    def test_u2_all_bracket_format(self):
        # [标题][作者][卷]... 相邻方括号 → 作者取第二个
        r = _parse("[城市风云儿][青山刚昌][Vol.01-Vol.24][完结][日本小学馆授权台湾中文版][C.C扫图]")
        assert r["series"] == "城市风云儿"
        assert r["author"] == "青山刚昌"
        assert r["total_volumes"] == 24
        assert r["complete"] is True
        assert "完结" in r["tags"]
        assert "日本小学馆授权台湾中文版" in r["tags"]
        assert "C.C扫图" in r["tags"]

    def test_u2_saint_seiya(self):
        r = _parse("[聖鬥士星矢][車田正美][Vol.01-Vol.22][完结][天下][完全版][C.C]")
        assert r["series"] == "聖鬥士星矢"
        assert r["author"] == "車田正美"
        assert r["total_volumes"] == 22
        assert r["complete"] is True
        assert "完全版" in r["tags"]

    def test_nya_jp_volume_range(self):
        # 第01-12巻 卷范围（内联卷标剥离）
        r = _parse("エロマンガ先生 第01-12巻 [Ero Manga Sensei vol 01-12]")
        assert r["series"] == "エロマンガ先生"
        assert r["total_volumes"] == 12

    def test_spy_family_plain_volume(self):
        r = _parse("Spy x Family Vol.16 - Vol.17")
        assert r["series"] == "Spy x Family"
        assert r["total_volumes"] == 17

    def test_plain_v_volume(self):
        r = _parse("漫画名V01")
        assert r["series"] == "漫画名"
        assert r["vol_info"] == "V01"
        assert r["total_volumes"] == 1

    def test_english_scene_volume(self):
        r = _parse("[ENG] One Piece - Vol. 106 (FULL COLOR Digital Colored Comics)")
        assert r["series"] == "One Piece"
        assert r["total_volumes"] == 106
        assert r["tags"]  # FULL COLOR Digital Colored Comics → tag

    def test_scanlator_zip(self):
        r = _parse("Name of Manga - c006-010 (v02) [FooScans].zip")
        assert r["series"] == "Name of Manga - c006-010"
        assert r["total_volumes"] == 2

    def test_convention_code_and_nested_bracket(self):
        # (C97) 展会码 → tag；嵌套括号取最内层；主名取末尾残留
        r = _parse("(C97) [社团名 (作者名)] 标题")
        assert r["series"] == "标题"
        assert "C97" in r["tags"]
        assert "作者名" in r["aliases"]
        assert "社团名" in r["aliases"]
        assert r["total_volumes"] == 0          # C97 不是卷数

    def test_chinese_scanlation_zip(self):
        r = _parse("《作品名》第X话 [汉化组名].zip")
        assert r["series"] == "《作品名》第X话"
        assert "汉化组名" in r["tags"]

    def test_corner_bracket_keeps_full_name(self):
        r = _parse("【BLVEFO9】喂我吃吧 老師!")
        assert r["series"] == "【BLVEFO9】喂我吃吧 老師!"
        assert r["author"] == ""

    def test_jm_id_keeps_full_name(self):
        r = _parse("JM248965-喂我吃吧 老師!")
        assert r["series"] == "JM248965-喂我吃吧 老師!"


class TestEdgeCases:
    """边界与附加规则"""

    def test_empty_name_returns_none(self):
        assert parse_folder_name_lenient("") is None
        assert parse_folder_name_lenient("   ") is None

    def test_chinese_volume_numeral(self):
        r = _parse("[作者] 标题 (卷十全)")
        assert r["total_volumes"] == 10
        assert r["complete"] is True

    def test_chinese_volume_range(self):
        r = _parse("[作者] 标题 (第01-12巻)")
        assert r["total_volumes"] == 12

    def test_fullwidth_digits(self):
        r = _parse("[作者] 标题 (V０４)")
        assert r["total_volumes"] == 4

    def test_no_volume_default_ongoing(self):
        r = _parse("[作者] 标题 [别名]")
        assert r["series"] == "标题"
        assert r["vol_info"] is None
        assert r["vol_type"] == "连载"
        assert r["complete"] is False

    def test_ongoing_tag(self):
        r = _parse("[作者] 标题 (V01) [连载中]")
        assert r["vol_type"] == "连载"
        assert r["complete"] is False

    def test_liansaiban_is_version_tag_not_ongoing(self):
        # L209: 「连载版」是版本属性（收集自连载单话，非按刊本），不是连载状态；
        # V10全 已完结 → complete 必须为 True，不能被「连载版」误判 ongoing 覆盖
        r = _parse("[Boichi] Origin 源型机 (V10全 连载版+外传)")
        assert r["author"] == "Boichi"
        assert r["series"] == "Origin 源型机"
        assert r["total_volumes"] == 10
        assert r["complete"] is True
        assert r["vol_type"] == "已完结"
        assert any("连载版" in t for t in r["tags"])   # 连载版 留在 tag（版本属性）
        assert "连载版" in r["tags"]
        assert "+外传" in r["tags"]
        assert r["extras"] == "外传"                     # +外传 → extras
        assert r["has_extras"] is True

    def test_tags_field_present_and_deduped(self):
        r = _parse("[作者] 标题 [日] [日] (V01)")
        assert r["tags"] == ["日"]

    def test_compatible_with_old_parse_result_keys(self):
        r = _parse("[作者] 标题 [别名] (V02全)")
        for key in ("author", "series", "aliases", "vol_info", "total_volumes",
                    "vol_type", "complete", "has_extras", "extras"):
            assert key in r
        assert "tags" in r

    def test_old_function_still_works(self):
        # 旧函数不受影响
        r = parse_folder_name("[富坚义博] 全职猎人 HUNTER×HUNTER (V35全)")
        assert r is not None
        assert r["series"] == "全职猎人"

    def test_plus_multi_extras_split(self):
        # L138: + 连接的多个附加内容（无空格）按 + 拆成独立 tag，+ 保留为前缀
        r = _parse("[和月伸宏] 浪客剑心完全版 (V22全+剑心皆传+剧场版)")
        assert r["series"] == "浪客剑心完全版"
        assert r["total_volumes"] == 22
        assert r["complete"] is True
        assert "+剑心皆传" in r["tags"]
        assert "+剧场版" in r["tags"]
        assert "+剑心皆传+剧场版" not in r["tags"]
        assert r["extras"] == "剑心皆传+剧场版"


class TestWeekdaySeriesName:
    """星期X 系列名不能被「期+中文数字」卷标规则误剥（2026-08-19）"""

    def test_blood_monday_keeps_qiyi(self):
        # VOL_RE 曾把「星期一」的「期一」当内联卷标剥掉 → series 少「期一」
        r = _parse("[惠广史] 血色星期一 (V11全)")
        assert r["author"] == "惠广史"
        assert r["series"] == "血色星期一"
        assert r["vol_info"] == "V11全"
        assert r["total_volumes"] == 11
        assert r["complete"] is True
        assert r["vol_type"] == "已完结"

    def test_qi_no_longer_triggers_volume(self):
        # 彻底移除「期」作卷标标记：数字+期 不再被 VOL_RE 命中 → 进 tags，vol_info 为 None
        r = _parse("[作者] 作品 (3期)")
        assert r["series"] == "作品"
        assert r["vol_info"] is None
        assert r["total_volumes"] == 0
        assert "3期" in r["tags"]


class TestChapterCompleteTag:
    """章节型完结 (C07全)/(C12完结) 识别；不影响 (C97) 展会码与 V 型卷标（2026-10-28）"""

    def test_c07_complete_chapter(self):
        r = _parse("[高桥真] 最终兵器彼女 (C07全)")
        assert r["author"] == "高桥真"
        assert r["series"] == "最终兵器彼女"
        assert r["vol_info"] == "C07全"
        assert r["total_volumes"] == 7
        assert r["complete"] is True
        assert r["vol_type"] == "已完结"
        assert "C07全" not in r["tags"]

    def test_c97_convention_code_still_tag(self):
        # 展会码零影响：无「全/完结」→ 照旧进 tags，不算卷数
        r = _parse("[某社] 同人本 (C97)")
        assert r["series"] == "同人本"
        assert r["total_volumes"] == 0
        assert r["complete"] is False
        assert "C97" in r["tags"]

    def test_v10_complete_regression(self):
        r = _parse("[C.H.LINE×太田垣康男] 前线任务 (V10全)")
        assert r["series"] == "前线任务"
        assert r["total_volumes"] == 10
        assert r["complete"] is True
        assert r["vol_type"] == "已完结"

    def test_v02_complete_regression(self):
        r = _parse("[あき] 神的乐园 [奥林匹斯] (V02全)")
        assert r["series"] == "神的乐园"
        assert r["aliases"] == ["奥林匹斯"]
        assert r["total_volumes"] == 2
        assert r["complete"] is True
        assert r["vol_type"] == "已完结"

    def test_c12_complete_chapter(self):
        r = _parse("[作者] 某作品 (C12完结)")
        assert r["vol_info"] == "C12完结"
        assert r["total_volumes"] == 12
        assert r["complete"] is True
        assert r["vol_type"] == "已完结"
        assert "C12完结" not in r["tags"]

    def test_fullwidth_c07_complete(self):
        r = _parse("[高桥真] 最终兵器彼女 (Ｃ０７全)")
        assert r["vol_info"] == "Ｃ０７全"
        assert r["total_volumes"] == 7
        assert r["complete"] is True
        assert "Ｃ０７全" not in r["tags"]

    def test_c1_without_complete_word_unchanged(self):
        # 原有 C1-C9 单字卷标行为不变
        r = _parse("[作者] 标题 (C1)")
        assert r["vol_info"] == "C1"
        assert r["total_volumes"] == 1
        assert r["complete"] is False

    def test_c120_without_complete_word_is_tag(self):
        r = _parse("[作者] 标题 (C120)")
        assert r["total_volumes"] == 0
        assert r["complete"] is False
        assert "C120" in r["tags"]

    def test_c07_with_extra_content_stays_tag(self):
        # 只认「整段 = C+数字+全/完结」的精确形态，附带其它内容维持原 tag 行为
        r = _parse("[作者] 标题 (C07全 汉化)")
        assert r["total_volumes"] == 0
        assert r["complete"] is False
        assert "C07全" in r["tags"]
