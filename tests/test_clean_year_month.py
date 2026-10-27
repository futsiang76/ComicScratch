"""clean_year / clean_month / clean_day 公共清洗函数测试 — Year/Month/Day 字段只保留纯数字

背景：Komga 读取 ComicInfo.xml 时 Year/Month/Day 是数字类型，「1999年」等带非数字字符的
值会导致整份 XML 反序列化失败（Jackson 报 ComicInfo["Year"]）、元数据全部丢弃。
manhuagui 源抓到的年代正是「1999年」，必须清成纯数字再写入 XML。
"""
import pytest

from processors.xml_generator import clean_day, clean_month, clean_year


class TestCleanYear:
    @pytest.mark.parametrize("raw,expected", [
        ("1999年", "1999"),        # manhuagui 源：带「年」字
        ("1999年1月", "1999"),     # 带年月
        ("2024-07-15", "2024"),   # 完整日期
        ("2024", "2024"),         # 已是纯数字
        (2016, "2016"),           # 数字类型（ComicVine start_year 为 int）
        (1966, "1966"),
        ("19世纪末", "19"),       # 无 4 位年份时退而取连续数字段
    ])
    def test_extracts_digits(self, raw, expected):
        assert clean_year(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "未知", "   "])
    def test_empty_when_no_digits(self, raw):
        assert clean_year(raw) == ""


class TestCleanMonth:
    @pytest.mark.parametrize("raw,expected", [
        ("7", "7"),
        ("07", "07"),
        ("12", "12"),
        ("7月", "7"),
    ])
    def test_extracts_digits(self, raw, expected):
        assert clean_month(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "未知"])
    def test_empty_when_no_digits(self, raw):
        assert clean_month(raw) == ""


class TestCleanDay:
    @pytest.mark.parametrize("raw,expected", [
        ("25", "25"),
        ("05", "05"),
        ("1", "1"),
        ("31", "31"),
        (25, "25"),          # 数字类型
        ("25日", "25"),      # 带「日」字
    ])
    def test_valid_days(self, raw, expected):
        assert clean_day(raw) == expected

    @pytest.mark.parametrize("raw", [
        "0",                 # 下越界
        "32",                # 上越界
        "x",                 # 无数字
        "",                  # 空
        None,
        "2008-09-25",        # 完整日期串抽到 2008，超范围 → 空
    ])
    def test_invalid_days_empty(self, raw):
        assert clean_day(raw) == ""


class TestWritePathsCleanYearMonth:
    """三条 Year/Month/Day 写入路径都经过清洗"""

    def test_apply_result_fields_cleans_manhuagui_year(self):
        """_apply_result_fields（统一入口）：1999年 → 1999，1月 → 1，25日 → 25"""
        from processors.xml_generator import _apply_result_fields

        info = {"Year": "x", "Month": "x", "Day": "x"}
        _apply_result_fields(info, {"year": "1999年", "month": "1月", "day": "25日",
                                    "series": "某系列"})
        assert info["Year"] == "1999"
        assert info["Month"] == "1"
        assert info["Day"] == "25"

    def test_apply_result_fields_invalid_day_empty(self):
        """_apply_result_fields：非法日（0/32/空）清成空串，不写标签"""
        from processors.xml_generator import _apply_result_fields

        for bad in ("0", "32", "", None):
            info = {"Day": "x"}
            _apply_result_fields(info, {"series": "某系列", "day": bad})
            assert info["Day"] == ""

    def test_locked_detail_year_cleaned(self):
        """build_file_comicinfo 锁住文件路径：detail 的 year/day 带非数字字符也被清成纯数字"""
        from processors.xml_generator import build_file_comicinfo

        info = build_file_comicinfo(
            {"series": "x", "year": "2020"},
            "Vol 01.zip",
            detail={"year": "1999年", "month": "7月", "day": "25日",
                    "summary": "单卷独立摘要"},
            is_locked=True,
        )
        assert info["Year"] == "1999"
        assert info["Month"] == "7"
        assert info["Day"] == "25"
        assert info["Summary"] == "单卷独立摘要"

    def test_extract_year_month_cleaned(self):
        """xml_template_handler._extract_year_month：日期串带「年」时 Year 只留数字"""
        from processors.xml_template_handler import XMLTemplateHandler

        ym = XMLTemplateHandler()._extract_year_month("1999年1月")
        assert ym["Year"] == "1999"
        assert ym["Month"] == ""
        assert ym["Day"] == ""
        ym2 = XMLTemplateHandler()._extract_year_month("2024-07-15")
        assert (ym2["Year"], ym2["Month"], ym2["Day"]) == ("2024", "07", "15")

    def test_extract_full_date_gives_day(self):
        """YYYY-MM-DD → 三段齐全；Day 取第 3 段"""
        from processors.xml_template_handler import XMLTemplateHandler

        ym = XMLTemplateHandler()._extract_year_month("2008-09-25")
        assert ym["Year"] == "2008"
        assert ym["Month"] in ("09", "9")
        assert ym["Day"] == "25"

    def test_extract_year_month_only_no_day(self):
        """YYYY-MM（无日）→ Day 为空串"""
        from processors.xml_template_handler import XMLTemplateHandler

        ym = XMLTemplateHandler()._extract_year_month("2008-09")
        assert (ym["Year"], ym["Month"], ym["Day"]) == ("2008", "09", "")

    def test_pure_digits_unchanged(self):
        """纯数字 Year/Month 输出不受影响（Bangumi/ComicVine 正常路径）"""
        from processors.xml_generator import build_file_comicinfo

        info = build_file_comicinfo(
            {"series": "x", "year": "2016", "month": "5"},
            "Vol 01.zip",
            detail={"year": "1966", "month": "12"},
            is_locked=True,
        )
        assert info["Year"] == "1966"
        assert info["Month"] == "12"


class TestXMLDayOutput:
    """XML 输出层：Day 有值时在 <Month> 之后输出，无值时整行不写"""

    @staticmethod
    def _xml(date_str):
        """走 create_bangumi_template + generate_comicinfo_xml 生成 XML"""
        from parsers.folder_parser_lenient import parse_folder_name_lenient
        from processors.xml_generator import XMLGenerator
        from processors.xml_template_handler import XMLTemplateHandler

        folder_info = parse_folder_name_lenient("[作者甲] 某系列 (V01全)")
        # 不带 id 避免走 persons 端点（测试不联网）
        bangumi_data = {"name": "某系列", "name_cn": "某系列", "summary": "",
                        "date": date_str}
        template = XMLTemplateHandler().create_bangumi_template(bangumi_data, folder_info)
        return XMLGenerator().generate_comicinfo_xml(template)

    def test_day_written_after_month(self):
        xml = self._xml("2008-09-25")
        assert "<Year>2008</Year>" in xml
        assert "<Day>25</Day>" in xml
        assert xml.index("<Month>") < xml.index("<Day>")

    def test_no_day_tag_when_day_missing(self):
        xml = self._xml("2008-09")
        assert "<Day" not in xml
        assert "<Month>09</Month>" in xml

    def test_no_day_tag_when_date_empty(self):
        xml = self._xml("")
        assert "<Day" not in xml
        assert "<Year>" not in xml

    def test_locked_volume_day_override_rendered(self):
        """锁定卷 detail 的 day 覆盖系列级值并写入 XML"""
        from processors.xml_generator import XMLGenerator, build_file_comicinfo

        info = build_file_comicinfo(
            {"series": "x", "year": "2008", "month": "09"},
            "Vol 01.zip",
            detail={"year": "2009", "month": "10", "day": "31"},
            is_locked=True)
        xml = XMLGenerator().generate_comicinfo_xml(info)
        assert "<Day>31</Day>" in xml
        assert "<Month>10</Month>" in xml
