"""结果页编辑落盘测试 — edit_row / on_results_double_clicked 确认且「有实际改动」后
必须调 save_single_result 写盘（系列级「✏️ 编辑」与逐卷编辑，双击行）。

回归点：两处原来只改内存（scan_results[row].update + 置「已修改」+ 刷新表格），
从不调保存函数 → 用户点「确定」后 ComicInfo.xml 不写回 CBZ。
"""
import copy
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QDialog

from gui import edit_controller
from gui.edit_dialog import EditDialog

Accepted = QDialog.DialogCode.Accepted
Rejected = QDialog.DialogCode.Rejected


def _make_result(series="某系列"):
    return {
        "folder_path": f"C:/fake/{series}",
        "folder_name": f"{series} 文件夹",
        "series": series,
        "count": "",
        "writer": "作者A",
        "penciller": "",
        "colorist": "",
        "web": "",
        "year": "2020",
        "month": "5",
        "day": "1",
        "status": "Ongoing",
        "summary": "",
        "genre": "",
        "tags": "",
        "manga": "No",
        "process_status": "新扫描",
        "file_titles": {"Vol 01.zip": "某卷01"},
        "file_details": {"Vol 01.zip": {"volume": "1"}},
        "locked_files": set(),
    }


def _spy_save(monkeypatch):
    """替换 save_single_result，记录每次调用的 (mw, result)"""
    calls = []
    monkeypatch.setattr(
        "gui.save_handler.save_single_result",
        lambda mw, result, show_result=False: calls.append((mw, result)),
    )
    return calls


def _patch_dialog(monkeypatch, attr_name, code, mutate=None):
    """把 edit_controller.<attr_name> 换成假对话框

    code: exec() 返回值；mutate(result_dict) -> get_data() 返回值
    （mutate 缺省 → 原样深拷贝回传 = 无任何改动）
    """
    class _FakeDialog:
        def __init__(self, data, parent=None):
            self._data = data

        def exec(self):
            return code

        def get_data(self):
            if mutate is None:
                return copy.deepcopy(self._data)
            return mutate(self._data)

    monkeypatch.setattr(edit_controller, attr_name, _FakeDialog)


def _patch_window(app, monkeypatch, results):
    app.scan_results = list(results)
    app.update_results_table = lambda: None
    return app


# ---------------- 系列级编辑 edit_row ----------------

def test_edit_row_accepted_with_changes_saves(app, monkeypatch):
    """Accepted + 有改动 → save_single_result 调 1 次，第二个参数就是该 result"""
    result = _make_result()
    window = _patch_window(app, monkeypatch, [result])
    calls = _spy_save(monkeypatch)
    _patch_dialog(monkeypatch, "EditDialog", Accepted,
                  mutate=lambda d: dict(d, series="改后系列"))

    edit_controller.edit_row(window, 0)

    assert len(calls) == 1
    assert calls[0][0] is window
    assert calls[0][1] is window.scan_results[0]
    assert window.scan_results[0]["series"] == "改后系列"
    assert window.scan_results[0]["process_status"] == "已修改"


def test_edit_row_accepted_without_changes_does_not_save(app, monkeypatch):
    """Accepted 但数据无变化 → 不写盘"""
    window = _patch_window(app, monkeypatch, [_make_result()])
    calls = _spy_save(monkeypatch)
    _patch_dialog(monkeypatch, "EditDialog", Accepted)

    edit_controller.edit_row(window, 0)

    assert calls == []
    assert window.scan_results[0]["process_status"] == "新扫描"


def test_edit_row_rejected_does_not_save(app, monkeypatch):
    """Rejected → 不写盘"""
    window = _patch_window(app, monkeypatch, [_make_result()])
    calls = _spy_save(monkeypatch)
    _patch_dialog(monkeypatch, "EditDialog", Rejected,
                  mutate=lambda d: dict(d, series="改后系列"))

    edit_controller.edit_row(window, 0)

    assert calls == []
    assert window.scan_results[0]["series"] == "某系列"


def test_edit_row_out_of_range_is_silent(app, monkeypatch):
    """row 越界 / 无 scan_results → 静默返回，不抛异常也不写盘"""
    window = _patch_window(app, monkeypatch, [_make_result()])
    calls = _spy_save(monkeypatch)
    _patch_dialog(monkeypatch, "EditDialog", Accepted,
                  mutate=lambda d: dict(d, series="改后系列"))

    edit_controller.edit_row(window, 5)          # 越界
    edit_controller.edit_row(window, -1)         # 负数
    edit_controller.edit_row(SimpleNamespace(update_results_table=lambda: None), 0)  # 无 scan_results

    assert calls == []


# ---------------- 逐卷编辑 on_results_double_clicked ----------------

def test_double_click_with_changes_saves(app, monkeypatch):
    """逐卷编辑有改动（file_titles 变）→ 写盘 1 次"""
    result = _make_result()
    window = _patch_window(app, monkeypatch, [result])
    calls = _spy_save(monkeypatch)
    _patch_dialog(
        monkeypatch, "TitleEditDialog", Accepted,
        mutate=lambda d: {"file_titles": {"Vol 01.zip": "改后卷名"},
                          "file_details": d["file_details"],
                          "locked_files": d["locked_files"]},
    )

    edit_controller.on_results_double_clicked(window, 0, 0)

    assert len(calls) == 1
    assert calls[0][1] is window.scan_results[0]
    assert window.scan_results[0]["file_titles"] == {"Vol 01.zip": "改后卷名"}
    assert window.scan_results[0]["process_status"] == "已修改"


def test_double_click_without_changes_does_not_save(app, monkeypatch):
    """逐卷编辑无改动 → 不写盘"""
    window = _patch_window(app, monkeypatch, [_make_result()])
    calls = _spy_save(monkeypatch)
    _patch_dialog(monkeypatch, "TitleEditDialog", Accepted)

    edit_controller.on_results_double_clicked(window, 0, 0)

    assert calls == []
    assert window.scan_results[0]["process_status"] == "新扫描"


def test_double_click_out_of_range_is_silent(app, monkeypatch):
    """逐卷编辑 row 越界 / 无 scan_results → 静默返回"""
    window = _patch_window(app, monkeypatch, [_make_result()])
    calls = _spy_save(monkeypatch)
    _patch_dialog(monkeypatch, "TitleEditDialog", Accepted)

    edit_controller.on_results_double_clicked(window, 9, 0)
    edit_controller.on_results_double_clicked(
        SimpleNamespace(update_results_table=lambda: None), 0, 0)

    assert calls == []


# ---------------- 真实对话框（不 mock get_data）防假实现漂移 ----------------

def test_edit_row_real_dialog_with_changes_saves(app, monkeypatch):
    """真实 EditDialog：改 series 后确定 → 真走 has_changes 判定并写盘"""
    result = _make_result()
    window = _patch_window(app, monkeypatch, [result])
    calls = _spy_save(monkeypatch)

    def _accept_and_change(self):
        self.series_edit.setText("真实对话框改后")
        return Accepted

    monkeypatch.setattr(EditDialog, "exec", _accept_and_change)

    edit_controller.edit_row(window, 0)

    assert len(calls) == 1
    assert calls[0][1] is window.scan_results[0]
    assert window.scan_results[0]["series"] == "真实对话框改后"


def test_edit_row_real_dialog_without_changes_does_not_save(app, monkeypatch):
    """真实 EditDialog：原样确定（往返无差异）→ 不写盘"""
    canonical = EditDialog(_make_result()).get_data()   # 经对话框取一次规范形态
    canonical["process_status"] = "新扫描"              # 运行态字段，get_data 不含
    window = _patch_window(app, monkeypatch, [copy.deepcopy(canonical)])
    calls = _spy_save(monkeypatch)
    monkeypatch.setattr(EditDialog, "exec", lambda self: Accepted)

    edit_controller.edit_row(window, 0)

    assert calls == []
    assert window.scan_results[0]["process_status"] == "新扫描"


# ---------------- 并发安全：已有保存线程在跑时入队，不开第二个线程 ----------------

def test_edit_row_enqueues_when_save_thread_running(app, monkeypatch):
    """已有保存线程运行中 → 编辑落盘进入 FIFO 队列，不并发启动第二个写盘线程"""
    window = _patch_window(app, monkeypatch, [_make_result()])

    class _FakeRunningThread:
        def isRunning(self):
            return True

    running = _FakeRunningThread()
    window._save_threads = [running]
    window._save_pending = []
    _patch_dialog(monkeypatch, "EditDialog", Accepted,
                  mutate=lambda d: dict(d, series="改后系列"))

    edit_controller.edit_row(window, 0)   # 走真实 save_single_result

    assert window._save_threads == [running]          # 未新增线程
    assert len(window._save_pending) == 1             # 入队等待
    assert window._save_pending[0][0] is window.scan_results[0]
