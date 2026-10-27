"""
Shared data state for edit dialogs.

Manages series fields, volume-level data, and lock states
decoupled from UI code.
"""


class EditState:
    """Shared data state for edit dialogs. Manages series fields, volumes, and lock states."""

    def __init__(self, data: dict):
        # Series fields
        self.series = data.get("series", "")
        self.count = data.get("count", "")
        self.writer = data.get("writer", "")
        self.penciller = data.get("penciller", "")
        self.colorist = data.get("colorist", "")
        self.bangumi_id = data.get("bangumi_id", "")
        self.source = data.get("source", "")
        self.source_id = data.get("source_id", "")
        self.web = data.get("web", "")
        self.year = data.get("year", "")
        self.month = data.get("month", "")
        self.day = data.get("day", "")
        self.status = data.get("status", "")
        self.summary = data.get("summary", "")
        self.tags = data.get("tags", "")
        self.genre = data.get("genre", "")
        self.manga = data.get("manga", "")

        # Volume-level data
        self.file_titles = data.get("file_titles", {})  # {filename: title}
        self.file_details = data.get("file_details", {})  # {filename: {volume, year, month, day, summary}}
        self.covers = data.get("covers", {})  # {filename: {path, width, height, ratio_ok}}

        # Lock states
        self.locked_files = data.get("locked_files", set())  # set of locked filenames

    def is_locked(self, filename: str) -> bool:
        """Check if a file is locked."""
        return filename in self.locked_files

    def sync_series_values(self, series_year: str, series_month: str, series_day: str,
                           series_summary: str = "") -> None:
        """把系列级值下发到未锁定卷（原 EditDialog.get_data 内联逻辑）

        日期只覆盖「仍沿用系列值」的卷——日期全空，或三格仍等于构造时的系列日期；
        已带本卷单行本发售日的卷保持原值，避免系列级编辑把逐卷日期抹平。
        summary 保持原行为：未锁定卷一律同步。
        """
        original = (str(self.year or ""), str(self.month or ""), str(self.day or ""))
        for filename in self.file_titles:
            if self.is_locked(filename):
                continue
            detail = self.file_details.setdefault(filename, {})
            current = (str(detail.get("year", "") or ""), str(detail.get("month", "") or ""),
                       str(detail.get("day", "") or ""))
            if current == ("", "", "") or current == original:
                if series_year:
                    detail["year"] = series_year
                if series_month:
                    detail["month"] = series_month
                if series_day:
                    detail["day"] = series_day
            if series_summary:
                detail["summary"] = series_summary

    def set_locked(self, filename: str, locked: bool):
        """Set lock state for a file."""
        if locked:
            self.locked_files.add(filename)
        else:
            self.locked_files.discard(filename)

    def select_all_locks(self, filenames: list):
        """Lock all given filenames."""
        for fn in filenames:
            self.locked_files.add(fn)

    def clear_all_locks(self):
        """Clear all locks."""
        self.locked_files.clear()

    def get_volumes_sorted(self) -> list:
        """Return volumes sorted by volume number then filename."""
        def sort_key(item):
            filename, title = item
            detail = self.file_details.get(filename, {})
            vol = detail.get("volume", "")
            try:
                return (int(vol), filename)
            except (ValueError, TypeError):
                return (999999, filename)

        return sorted(self.file_titles.items(), key=sort_key)

    def update_from_title_data(self, title_data: dict):
        """Update volume data from TitleEditDialog.get_data() result."""
        self.file_titles = title_data.get("file_titles", {})
        self.file_details = title_data.get("file_details", {})
        self.locked_files = title_data.get("locked_files", set())

    def to_dict(self) -> dict:
        """Export all data as a dict (backward compatible with old self.data)."""
        return {
            "series": self.series,
            "count": self.count,
            "writer": self.writer,
            "penciller": self.penciller,
            "colorist": self.colorist,
            "bangumi_id": self.bangumi_id,
            "source": self.source,
            "source_id": self.source_id,
            "web": self.web,
            "year": self.year,
            "month": self.month,
            "day": self.day,
            "status": self.status,
            "summary": self.summary,
            "tags": self.tags,
            "genre": self.genre,
            "manga": self.manga,
            "file_titles": self.file_titles,
            "file_details": self.file_details,
            "locked_files": self.locked_files,
        }

    def to_series_dict(self) -> dict:
        """Export only series-level fields."""
        return {
            "series": self.series,
            "count": self.count,
            "writer": self.writer,
            "penciller": self.penciller,
            "colorist": self.colorist,
            "bangumi_id": self.bangumi_id,
            "source": self.source,
            "source_id": self.source_id,
            "web": self.web,
            "year": self.year,
            "month": self.month,
            "day": self.day,
            "status": self.status,
            "summary": self.summary,
            "tags": self.tags,
            "genre": self.genre,
            "manga": self.manga,
        }
