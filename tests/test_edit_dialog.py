"""编辑对话框测试"""
from PySide6.QtWidgets import QLineEdit, QPushButton, QComboBox, QTextEdit

from gui.edit_dialog import EditDialog


def test_edit_dialog_fields_exist(qtbot):
    """各字段存在"""
    dialog = EditDialog({})
    qtbot.addWidget(dialog)
    dialog.show()

    assert isinstance(dialog.series_edit, QLineEdit)
    assert isinstance(dialog.count_edit, QLineEdit)
    assert isinstance(dialog.writer_edit, QLineEdit)
    assert isinstance(dialog.penciller_edit, QLineEdit)
    assert isinstance(dialog.colorist_edit, QLineEdit)
    assert isinstance(dialog.web_edit, QLineEdit)
    assert isinstance(dialog.year_edit, QLineEdit)
    assert isinstance(dialog.month_edit, QLineEdit)
    assert isinstance(dialog.day_edit, QLineEdit)
    assert isinstance(dialog.status_combo, QComboBox)
    assert isinstance(dialog.summary_edit, QTextEdit)
    assert isinstance(dialog.tags_edit, QLineEdit)
    assert isinstance(dialog.manga_combo, QComboBox)


def test_edit_dialog_empty_data(qtbot):
    """无数据时正常显示空字段"""
    dialog = EditDialog({})
    qtbot.addWidget(dialog)
    dialog.show()

    assert dialog.series_edit.text() == ""
    assert dialog.writer_edit.text() == ""
    assert dialog.year_edit.text() == ""


def test_edit_dialog_with_data(qtbot):
    """含数据时正确填充"""
    data = {
        "series": "测试漫画",
        "writer": "测试作者",
        "year": "2024",
        "month": "6",
        "status": "Completed",
        "tags": "少年, 热血",
    }
    dialog = EditDialog(data)
    qtbot.addWidget(dialog)
    dialog.show()

    assert dialog.series_edit.text() == "测试漫画"
    assert dialog.writer_edit.text() == "测试作者"
    assert dialog.year_edit.text() == "2024"
    assert dialog.status_combo.currentText() == "Completed"


def test_edit_dialog_get_data(qtbot):
    """get_data 返回编辑后的数据"""
    dialog = EditDialog({"series": "原系列"})
    qtbot.addWidget(dialog)

    dialog.series_edit.setText("新系列")
    dialog.writer_edit.setText("新作者")

    result = dialog.get_data()
    assert result["series"] == "新系列"
    assert result["writer"] == "新作者"


def test_edit_dialog_day_field_roundtrip(qtbot):
    """发行日期三格：加载 day、保存回写 result['day']，并同步未锁定卷的 file_details"""
    data = {"series": "某系列", "year": "2008", "month": "9", "day": "25",
            "file_titles": {"Vol 01.zip": "某卷"},
            "file_details": {"Vol 01.zip": {"volume": "1"}},
            "locked_files": set()}
    dialog = EditDialog(data)
    qtbot.addWidget(dialog)

    assert dialog.day_edit.text() == "25"
    result = dialog.get_data()
    assert result["day"] == "25"
    assert result["file_details"]["Vol 01.zip"]["day"] == "25"
    assert result["file_details"]["Vol 01.zip"]["month"] == "9"
