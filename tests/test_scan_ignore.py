#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描忽略目录规则测试：通配符匹配 + 两个枚举入口剪枝 + 设置持久化"""

import json
import os

import pytest

from config import USER_CONFIG_PATH
from processors.ignore_rules import (
    filter_subdirs, find_rule_issues, get_ignore_patterns, is_dir_ignored,
    normalize_patterns)


class TestIgnoreMatcher:
    """通配符匹配语义"""

    def test_default_rules(self):
        assert get_ignore_patterns() == [".*", "_*"]
        for name in (".git", "_设定集", ".comicscratch_tmp"):
            assert is_dir_ignored(name)
        for name in ("海贼王", "[作者] 系列 (V01全)", "temp_backup"):
            assert not is_dir_ignored(name)

    def test_star_question_bracket_wildcards(self):
        assert is_dir_ignored("temp_backup", ["temp*"])
        assert not is_dir_ignored("temp_backup", ["temp?"])
        assert is_dir_ignored("temp1", ["temp?"])
        assert is_dir_ignored("abc", ["[abc]*"])
        assert not is_dir_ignored("xyz", ["[abc]*"])

    def test_case_insensitive(self):
        assert is_dir_ignored("CacheDir", ["cachedir"])
        assert is_dir_ignored("_EXTRAS", ["_*"])

    def test_empty_name_never_ignored(self):
        assert not is_dir_ignored("", [".*"])

    def test_normalize_patterns(self):
        assert normalize_patterns([" a ", "", "a", "b", "a"]) == ["a", "b"]
        assert normalize_patterns(None) == []

    def test_clear_rules_means_no_ignore(self, monkeypatch):
        import config
        monkeypatch.setattr(config, "SCAN_IGNORE_DIRS", [])
        assert get_ignore_patterns() == []
        assert not is_dir_ignored(".git")

    def test_filter_subdirs(self):
        names = ["series1", "_extra", ".git", "series2"]
        skipped = []
        kept = filter_subdirs(names, log_fn=skipped.append)
        assert kept == ["series1", "series2"]
        assert skipped == ["_extra", ".git"]


class TestEnumerationPruning:
    """两个枚举入口（GUI 全模式 + 批量递归）都剪枝忽略目录"""

    @pytest.fixture()
    def lib_tree(self, tmp_path):
        """分类目录 > {正常系列 x2, 忽略目录 x3, 临时目录}，忽略目录内含嵌套系列"""
        cat = tmp_path / "大师作品集"
        for d in ("[作者A] 正常系列一 (V01全)", "[作者B] 正常系列二 (V02全)",
                  ".git", "_设定集", ".comicscratch_tmp", "temp_backup"):
            p = cat / d
            p.mkdir(parents=True)
            (p / "01.zip").write_bytes(b"PK")
        nested = cat / "_设定集" / "[作者C] 藏在忽略里的系列 (V01全)"
        nested.mkdir(parents=True)
        (nested / "01.zip").write_bytes(b"PK")
        return tmp_path

    def _collected_names(self, folders):
        return sorted(os.path.basename(f) for f, _ in folders)

    def test_gui_collect_series_folders(self, lib_tree):
        from gui.scan_controller import _collect_series_folders
        names = self._collected_names(_collect_series_folders(str(lib_tree)))
        # 默认规则：.git/_设定集(含嵌套系列)被剪枝；temp_backup 合法收集
        assert names == ["[作者A] 正常系列一 (V01全)",
                         "[作者B] 正常系列二 (V02全)",
                         "temp_backup"]

    def test_recursive_handler(self, lib_tree):
        from processors.folder_recursive_handler import create_folder_recursive_handler
        h = create_folder_recursive_handler(max_depth=3)
        total, processed, _ = h.scan_directory(str(lib_tree),
                                               lambda *a: True, lambda *a: None)
        assert total == processed == 3
        stats = h.get_folder_statistics(str(lib_tree))
        assert stats["comic_folders"] == 3
        assert h.validate_folder_structure(str(lib_tree))["valid"]

    def test_runtime_config_change_applies(self, lib_tree, monkeypatch):
        import config
        from gui.scan_controller import _collect_series_folders
        monkeypatch.setattr(config, "SCAN_IGNORE_DIRS", [".*", "_*", "temp*"])
        names = self._collected_names(_collect_series_folders(str(lib_tree)))
        assert names == ["[作者A] 正常系列一 (V01全)",
                         "[作者B] 正常系列二 (V02全)"]


class TestRuleIssues:
    """保存前校验：致命问题 vs 提示问题"""

    def test_no_issues_for_default_and_sane_rules(self):
        assert find_rule_issues([".*", "_*"]) == ([], [])
        assert find_rule_issues(["temp*", "缓存?"]) == ([], [])

    def test_blocking_matches_everything(self):
        blocking, warnings = find_rule_issues(["*"])
        assert blocking and not warnings
        assert "匹配所有目录" in blocking[0]
        # ?* 也匹配一切（目录名至少 1 字符），同样拦截
        assert find_rule_issues(["?*"])[0]

    def test_path_separator_warning(self):
        blocking, warnings = find_rule_issues([".*/foo", "_*"])
        assert not blocking
        assert any("路径分隔符" in w for w in warnings)

    def test_empty_rules_warning(self):
        blocking, warnings = find_rule_issues([])
        assert not blocking
        assert any("不忽略任何目录" in w for w in warnings)

    def test_mixed_blocking_and_warning(self):
        blocking, warnings = find_rule_issues(["*", "foo/bar"])
        assert blocking and warnings


class TestSettingsPersistence:
    """设置对话框保存 → user_config.json 落盘 → 重载生效"""

    def test_save_settings_persists(self, tmp_path, monkeypatch):
        import config
        fake_path = str(tmp_path / "user_config.json")
        monkeypatch.setattr(config, "USER_CONFIG_PATH", fake_path)
        config.save_settings({"scan_ignore_dirs": [".*", "_*", "custom*"]})
        raw = json.load(open(fake_path, encoding="utf-8"))
        assert raw["scan_ignore_dirs"] == [".*", "_*", "custom*"]
