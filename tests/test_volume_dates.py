#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐卷单行本发售日（t_da6165cd）测试

规则（用户拍板，不许启发式硬猜）：
- 每卷用自己那卷的 Bangumi 发售日；卷号匹配不上或该卷无日期 → 沿用系列级日期
- 卷号提取优先级：(N) / （N） → 第N巻卷集册 → Vol N；提取不到 = 不做顺序推断
- 发售日只用顶层 date / infobox「发售日」，绝不用「开始」/「结束」

真实样本（api.bgm.tv 实测）：進撃の巨人(8491) 1 卷 2010-03-17 / 2 卷 2010-07-16；
神的乐园(30085) 1 卷 2008-09-25 / 2 卷 2009-09-25；海賊王の求婚(211220) 3 卷全无编号。
"""

import zipfile

import pytest
import requests

from models.bangumi_volume_dates import (attach_volume_dates, collect_volume_dates,
                                         extract_volume_number)
from processors.result_builder import _volume_date_parts, create_result_dict
from processors.xml_generator import XMLGenerator, build_file_comicinfo
from processors.xml_template_handler import XMLTemplateHandler


@pytest.fixture(autouse=True)
def _no_live_network(monkeypatch):
    """create_bangumi_template 内部为取作者会新建 BangumiFetcher 打 persons 端点
    （既有行为，与本任务无关）→ 测试里一律拦掉，保证零真实网络请求。"""
    monkeypatch.setattr("models.bangumi_fetcher.BangumiFetcher.get_manga_persons",
                        lambda self, subject_id: [])


# ---------- 卷号提取 ----------

class TestExtractVolumeNumber:
    @pytest.mark.parametrize("name,expected", [
        ("進撃の巨人 (1)", "1"),          # 实测系列 8491
        ("SLAM DUNK (01)", "1"),          # 零填充 → int 归一化（实测 36752）
        ("SLAM DUNK 完全版 (01)", "1"),    # 实测 18462
        ("海賊王の求婚", None),            # 反例：无编号，绝不按顺序硬派
        ("海賊王と約束の花嫁", None),
        ("オリンポス (2)", "2"),
        ("オリンポス（2）", "2"),          # 全角括号
        ("テスト ( 3 )", "3"),            # 括号内空格
        ("作品 第3巻", "3"),               # 日文「巻」
        ("作品 第12卷", "12"),
        ("作品 第5册", "5"),
        ("作品 第7集", "7"),
        ("作品 Vol.07", "7"),
        ("作品 vol 8", "8"),
        ("作品 VOL9", "9"),
        ("測試 (2) 第3巻", "2"),           # 括号优先级高于「第N巻」
        ("", None),
        (None, None),
    ])
    def test_extract(self, name, expected):
        assert extract_volume_number(name) == expected


# ---------- get_volume_dates（mock 关联响应） ----------

class _FakeFetcher:
    """替身：记录请求路径，返回预置关联列表 / 卷详情"""

    def __init__(self, subjects=None, details=None, fail_subjects=False):
        self.calls = []
        self._subjects = subjects if subjects is not None else []
        self._details = details or {}
        self._fail_subjects = fail_subjects

    def _request_json(self, method, path, params=None, json_payload=None):
        self.calls.append(path)
        if path.endswith("/subjects"):
            if self._fail_subjects:
                raise requests.exceptions.ConnectionError("boom")
            return self._subjects
        vol_id = int(path.rsplit("/", 1)[1])
        detail = self._details[vol_id]
        if isinstance(detail, Exception):
            raise detail
        return detail

    def get_volume_dates(self, subject_id):
        return collect_volume_dates(self, subject_id)


def _vol(vol_id, name, relation="单行本"):
    return {"id": vol_id, "name": name, "relation": relation}


class TestCollectVolumeDates:
    def test_maps_volumes_and_filters_relation(self):
        """只认 relation=="单行本"，番外篇等一概不入；键为 int 归一化字符串"""
        f = _FakeFetcher(
            subjects=[_vol(11, "進撃の巨人 (1)"), _vol(12, "進撃の巨人 (2)"),
                      _vol(13, "進撃の巨人 (3)", relation="番外篇"),
                      _vol(14, "進撃の巨人 (4)"),  # 无详情 → 跳过
                      ],
            details={11: {"date": "2010-03-17"}, 12: {"date": "2010-07-16"},
                     13: {"date": "2012-01-01"}, 14: {"date": ""}},
        )
        assert f.get_volume_dates(8491) == {"1": "2010-03-17", "2": "2010-07-16"}

    def test_zero_padded_name_normalized(self):
        """「(01)」与「(1)」同为键 "1"（结果侧 vol="01" 才能命中）"""
        f = _FakeFetcher(subjects=[_vol(21, "SLAM DUNK (01)"), _vol(22, "SLAM DUNK (02)")],
                         details={21: {"date": "1991-02-08"}, 22: {"date": "1991-06-10"}})
        assert f.get_volume_dates(36752) == {"1": "1991-02-08", "2": "1991-06-10"}

    def test_unnumbered_names_skipped_without_detail_request(self):
        """反例：3 卷 name 全无编号 → 返回 {} 且不为它们发详情请求（不猜）"""
        f = _FakeFetcher(
            subjects=[_vol(31, "海賊王の求婚"), _vol(32, "海賊王と約束の花嫁"),
                      _vol(33, "海賊王の結婚")],
            details={31: {"date": "2011-03-01"}, 32: {"date": "2012-04-28"},
                     33: {"date": "2014-08-30"}},
        )
        assert f.get_volume_dates(211220) == {}
        assert f.calls == ["/v0/subjects/211220/subjects"]

    def test_empty_date_falls_back_to_infobox_release(self):
        """顶层 date 空 → infobox「发售日」兜底"""
        f = _FakeFetcher(subjects=[_vol(41, "某作 (1)")],
                         details={41: {"date": "",
                                       "infobox": [{"key": "发售日", "value": "2010-03-17"}]}})
        assert f.get_volume_dates(1) == {"1": "2010-03-17"}

    def test_start_end_never_used_as_release_date(self):
        """只有「开始」/「结束」（连载起止）→ 该卷无发售日，跳过"""
        f = _FakeFetcher(subjects=[_vol(51, "某作 (1)"), _vol(52, "某作 (2)")],
                         details={51: {"date": "", "infobox": [
                             {"key": "开始", "value": "2009-01-01"},
                             {"key": "结束", "value": "2010-01-01"}]},
                                  52: {"date": "2010-07-16"}})
        assert f.get_volume_dates(1) == {"2": "2010-07-16"}

    def test_instance_cache_hit_no_extra_requests(self):
        """同一 series 只请求一次：第二次直接命中缓存"""
        f = _FakeFetcher(subjects=[_vol(61, "某作 (1)"), _vol(62, "某作 (2)")],
                         details={61: {"date": "2010-03-17"}, 62: {"date": "2010-07-16"}})
        first = f.get_volume_dates(1)
        calls_after_first = len(f.calls)
        second = f.get_volume_dates(1)
        assert second == first
        assert len(f.calls) == calls_after_first
        assert calls_after_first == 3  # 1 关联列表 + 2 卷详情

    def test_series_request_failure_returns_empty_silently(self):
        """关联列表请求失败 → 静默返回 {}（不抛异常）"""
        f = _FakeFetcher(fail_subjects=True)
        assert f.get_volume_dates(1) == {}

    def test_single_volume_failure_skips_only_that_volume(self):
        """单卷详情失败 → 只跳过该卷，其它卷照旧"""
        f = _FakeFetcher(subjects=[_vol(71, "某作 (1)"), _vol(72, "某作 (2)")],
                         details={71: requests.exceptions.Timeout("t/o"),
                                  72: {"date": "2010-07-16"}})
        assert f.get_volume_dates(1) == {"2": "2010-07-16"}

    def test_dict_payload_compat(self):
        """兼容 {"data": [...]} 形态（官方/镜像个别端点如此）"""
        f = _FakeFetcher(subjects={"data": [_vol(81, "某作 (1)")]},
                         details={81: {"date": "2010-03-17"}})
        assert f.get_volume_dates(1) == {"1": "2010-03-17"}


# ---------- attach_volume_dates / 模板接线 ----------

_FOLDER = {"series": "神的乐园", "author": "某作者",
           "complete": True, "total_volumes": 2}


class TestAttachVolumeDates:
    def test_attaches_mapping(self):
        f = _FakeFetcher(subjects=[_vol(11, "進撃の巨人 (1)")],
                         details={11: {"date": "2010-03-17"}})
        base = {}
        attach_volume_dates(base, f, 8491)
        assert base["_volume_dates"] == {"1": "2010-03-17"}

    def test_none_base_and_none_id_safe(self):
        attach_volume_dates(None, _FakeFetcher(), 1)  # 不崩
        base = {}
        attach_volume_dates(base, _FakeFetcher(), None)
        assert base["_volume_dates"] == {}

    def test_template_without_fetcher_has_no_key(self):
        """不传 fetcher（旧调用方式/测试直接调用）→ 不加 _volume_dates，行为不变"""
        template = XMLTemplateHandler().create_bangumi_template(
            {"id": 30085, "name": "オリンポス", "date": "2008-09-25"}, dict(_FOLDER))
        assert "_volume_dates" not in template
        assert template["Year"] == "2008"

    def test_template_with_fetcher_attaches(self):
        f = _FakeFetcher(subjects=[_vol(26562, "オリンポス (1)"),
                                   _vol(30084, "オリンポス (2)")],
                         details={26562: {"date": "2008-09-25"},
                                  30084: {"date": "2009-09-25"}})
        template = XMLTemplateHandler().create_bangumi_template(
            {"id": 30085, "name": "オリンポス", "date": "2008-09-25"},
            dict(_FOLDER), f)
        assert template["_volume_dates"] == {"1": "2008-09-25", "2": "2009-09-25"}


# ---------- _volume_date_parts ----------

class TestVolumeDateParts:
    def test_hit(self):
        assert _volume_date_parts({"2": "2009-09-25"}, "02") == ("2009", "09", "25")

    def test_miss(self):
        assert _volume_date_parts({"1": "2008-09-25"}, "02") == ("", "", "")

    @pytest.mark.parametrize("dates,vol", [
        ({}, "01"), (None, "01"), ({"1": "2008-09-25"}, ""), ({"1": "x"}, "A"),
    ])
    def test_unusable_inputs(self, dates, vol):
        assert _volume_date_parts(dates, vol) == ("", "", "")

    def test_year_month_only(self):
        """只有 YYYY-MM 的卷日期 → 日留空（不借用其它卷的日）"""
        assert _volume_date_parts({"3": "2011-08"}, "03") == ("2011", "08", "")


# ---------- result_builder：命中 / 未命中 ----------

def _png(w=100, h=150):
    import struct
    import zlib

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\xff\xff\xff" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _make_cbz(folder, name):
    with zipfile.ZipFile(folder / name, "w") as zf:
        zf.writestr("000.png", _png())


def _base_with_volumes(volumes):
    base = XMLTemplateHandler().create_base_template({"series": "神的乐园", "author": "某作者", "complete": True, "total_volumes": 2})
    base.update({"Series": "神的乐园", "Year": "2008", "Month": "09", "Day": "25"})
    base["_volume_dates"] = volumes
    return base


class TestResultBuilderVolumeDates:
    def test_hit_uses_own_volume_date(self, tmp_path):
        """第 2 卷命中 → file_details 用第 2 卷日期；系列级 result 仍是系列 date"""
        _make_cbz(tmp_path, "Vol 01.cbz")
        _make_cbz(tmp_path, "Vol 02.cbz")
        base = _base_with_volumes({"1": "2008-09-25", "2": "2009-09-25"})
        result = create_result_dict(str(tmp_path), {"series": "神的乐园", "complete": True, "total_volumes": 2}, base,
                                    {"id": 30085}, False, "处理成功")
        assert result["file_details"]["Vol 01.cbz"]["year"] == "2008"
        assert result["file_details"]["Vol 02.cbz"]["year"] == "2009"
        assert result["file_details"]["Vol 02.cbz"]["month"] == "09"
        assert result["file_details"]["Vol 02.cbz"]["day"] == "25"
        # 系列级语义不变
        assert (result["year"], result["month"], result["day"]) == ("2008", "09", "25")

    def test_miss_falls_back_to_series_date(self, tmp_path):
        """卷号不在映射里（如 Vol 05）→ 沿用系列级日期"""
        _make_cbz(tmp_path, "Vol 05.cbz")
        base = _base_with_volumes({"1": "2008-09-25", "2": "2009-09-25"})
        result = create_result_dict(str(tmp_path), {"series": "神的乐园", "complete": True, "total_volumes": 2}, base,
                                    {"id": 30085}, False, "处理成功")
        details = result["file_details"]["Vol 05.cbz"]
        assert (details["year"], details["month"], details["day"]) == ("2008", "09", "25")

    def test_no_mapping_key_behaviour_unchanged(self, tmp_path):
        """无 _volume_dates（manhuagui/comicvine 源）→ 全部沿用系列级，行为不变"""
        _make_cbz(tmp_path, "Vol 02.cbz")
        base = _base_with_volumes({})
        del base["_volume_dates"]
        result = create_result_dict(str(tmp_path), {"series": "神的乐园", "complete": True, "total_volumes": 2}, base,
                                    {"id": 1}, False, "处理成功", source="manhuagui")
        details = result["file_details"]["Vol 02.cbz"]
        assert (details["year"], details["month"], details["day"]) == ("2008", "09", "25")

    def test_unnumbered_volume_falls_back(self, tmp_path):
        """文件解析不出卷号 → 系列级（不按顺序推断）"""
        _make_cbz(tmp_path, "神的乐园 短篇集.cbz")
        base = _base_with_volumes({"1": "2008-09-25", "2": "2009-09-25"})
        result = create_result_dict(str(tmp_path), {"series": "神的乐园", "complete": True, "total_volumes": 2}, base,
                                    {"id": 30085}, False, "处理成功")
        details = list(result["file_details"].values())[0]
        assert (details["year"], details["month"], details["day"]) == ("2008", "09", "25")


# ---------- XML 落地：第 2 卷输出自己那卷的 Day ----------

class TestXmlPerVolumeDay:
    def _xml_for(self, result, filename):
        info = build_file_comicinfo(result, filename,
                                   file_titles=result["file_titles"],
                                   detail=result["file_details"][filename],
                                   is_locked=False)
        return XMLGenerator().generate_comicinfo_xml(info)

    def test_vol2_xml_uses_own_date(self, tmp_path):
        """端到端：create_bangumi_template(fetcher) → create_result_dict → XML"""
        _make_cbz(tmp_path, "Vol 01.cbz")
        _make_cbz(tmp_path, "Vol 02.cbz")
        f = _FakeFetcher(subjects=[_vol(26562, "オリンポス (1)"),
                                   _vol(30084, "オリンポス (2)")],
                         details={26562: {"date": "2008-09-25"},
                                  30084: {"date": "2009-09-25"}})
        base = XMLTemplateHandler().create_bangumi_template(
            {"id": 30085, "name": "オリンポス", "date": "2008-09-25"},
            {"series": "神的乐园", "author": "某作者", "complete": True, "total_volumes": 2}, f)
        result = create_result_dict(str(tmp_path), {"series": "神的乐园", "complete": True, "total_volumes": 2}, base,
                                    {"id": 30085}, False, "处理成功")

        xml1 = self._xml_for(result, "Vol 01.cbz")
        xml2 = self._xml_for(result, "Vol 02.cbz")
        assert "<Year>2008</Year>" in xml1 and "<Day>25</Day>" in xml1
        assert "<Year>2009</Year>" in xml2
        assert "<Month>09</Month>" in xml2
        assert "<Day>25</Day>" in xml2
        assert "<Year>2008</Year>" not in xml2
        # Day 紧跟 Month
        assert xml2.index("<Month>") < xml2.index("<Day>")

    def test_fallback_xml_uses_series_date(self, tmp_path):
        """未命中 → XML 仍是系列日期（第 1 卷值），不猜"""
        _make_cbz(tmp_path, "Vol 07.cbz")
        base = _base_with_volumes({"1": "2008-09-25", "2": "2009-09-25"})
        result = create_result_dict(str(tmp_path), {"series": "神的乐园", "complete": True, "total_volumes": 2}, base,
                                    {"id": 30085}, False, "处理成功")
        xml = self._xml_for(result, "Vol 07.cbz")
        assert "<Year>2008</Year>" in xml and "<Day>25</Day>" in xml

    def test_locked_flag_no_longer_required(self):
        """改动点：detail 日期不再要求 is_locked 才生效"""
        info = build_file_comicinfo(
            {"series": "x", "year": "2008", "month": "09", "day": "25"}, "Vol 02.cbz",
            detail={"year": "2009", "month": "09", "day": "25", "summary": "单卷摘要"},
            is_locked=False)
        assert (info["Year"], info["Month"], info["Day"]) == ("2009", "09", "25")
        assert info["Summary"] == ""          # summary 仍需 is_locked
        info_locked = build_file_comicinfo(
            {"series": "x", "year": "2008", "month": "09", "day": "25"}, "Vol 02.cbz",
            detail={"year": "2009", "month": "09", "day": "25", "summary": "单卷摘要"},
            is_locked=True)
        assert info_locked["Summary"] == "单卷摘要"
