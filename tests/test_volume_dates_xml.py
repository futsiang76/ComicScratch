#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐卷发售日 → ComicInfo XML 落地测试（t_da6165cd）

从 test_volume_dates.py 拆出（原文件已到 400 行上限，单文件 ≤400 约束）：
- 第 2 卷 XML 输出本卷日期（非第 1 卷）
- 未命中卷号 → 系列级日期兜底
- 单卷日期只到 YYYY-MM → Month 用本卷、Day 留空，绝不借第 1 卷的日
- detail 三键全空（manhuagui/comicvine、xml_editor detail={}）→ 行为与旧版一致
"""

import pytest

from processors.result_builder import create_result_dict
from processors.xml_generator import XMLGenerator, build_file_comicinfo
from processors.xml_template_handler import XMLTemplateHandler
from tests.test_volume_dates import (_FakeFetcher, _base_with_volumes, _make_cbz,
                                     _vol)


@pytest.fixture(autouse=True)
def _no_live_network(monkeypatch):
    """create_bangumi_template 内部为取作者会新建 BangumiFetcher 打 persons 端点
    （既有行为，与本任务无关）→ 测试里一律拦掉，保证零真实网络请求。"""
    monkeypatch.setattr("models.bangumi_fetcher.BangumiFetcher.get_manga_persons",
                        lambda self, subject_id: [])


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

    def test_partial_date_does_not_borrow_series_day(self, tmp_path):
        """单卷日期只到 YYYY-MM → Month 用本卷、Day 留空（绝不借第 1 卷的日）

        回归：旧实现三块各自判空覆盖，Vol02 的 Day 会保留系列级 25。
        """
        _make_cbz(tmp_path, "Vol 01.cbz")
        _make_cbz(tmp_path, "Vol 02.cbz")
        base = _base_with_volumes({"1": "2008-09-25", "2": "2011-08"})
        result = create_result_dict(str(tmp_path), {"series": "神的乐园", "complete": True, "total_volumes": 2}, base,
                                    {"id": 30085}, False, "处理成功")
        details = result["file_details"]
        assert (details["Vol 02.cbz"]["year"], details["Vol 02.cbz"]["month"],
                details["Vol 02.cbz"]["day"]) == ("2011", "08", "")

        xml1 = self._xml_for(result, "Vol 01.cbz")
        xml2 = self._xml_for(result, "Vol 02.cbz")
        assert "<Year>2008</Year>" in xml1 and "<Day>25</Day>" in xml1
        assert "<Year>2011</Year>" in xml2 and "<Month>08</Month>" in xml2
        assert "<Day>" not in xml2            # 曾经错误地带出系列级 25
        assert "<Year>2008</Year>" not in xml2

    def test_detail_date_keys_all_empty_keeps_series_values(self):
        """detail 三键全空（manhuagui/comicvine、xml_editor detail={}）→ 行为与旧版一致"""
        info = build_file_comicinfo(
            {"series": "x", "year": "2008", "month": "09", "day": "25"}, "Vol 02.cbz",
            detail={"volume": "02", "year": "", "month": "", "day": "", "summary": ""},
            is_locked=False)
        assert (info["Year"], info["Month"], info["Day"]) == ("2008", "09", "25")
        info_empty = build_file_comicinfo(
            {"series": "x", "year": "2008", "month": "09", "day": "25"}, "Vol 02.cbz", detail={})
        assert (info_empty["Year"], info_empty["Month"], info_empty["Day"]) == ("2008", "09", "25")
