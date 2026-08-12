from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6 import QtCore
from PyQt6.QtCore import Qt


class TracksModel(QtCore.QAbstractTableModel):
    HEADERS = ["Title", "Artist(s)", "Album", "Duration", "Id"]

    def __init__(self, rows: List[Dict[str, Any]]):
        super().__init__()
        self.rows = rows

    def rowCount(self, parent=QtCore.QModelIndex()) -> int:
        return len(self.rows)

    def columnCount(self, parent=QtCore.QModelIndex()) -> int:
        return len(self.HEADERS)

    def data(self, index: QtCore.QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = self.rows[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return item.get("Name")
            if col == 1:
                artists = item.get("Artists") or []
                return ", ".join(artists)
            if col == 2:
                return item.get("Album") or ""
            if col == 3:
                ticks = item.get("RunTimeTicks") or 0
                seconds = int(ticks / 10_000_000)
                m, s = divmod(seconds, 60)
                return f"{m}:{s:02d}"
            if col == 4:
                return item.get("Id")
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if (
            role == Qt.ItemDataRole.DisplayRole
            and orientation == Qt.Orientation.Horizontal
        ):
            return self.HEADERS[section]
        return None

    def itemId(self, row: int) -> Optional[str]:
        if 0 <= row < len(self.rows):
            return self.rows[row].get("Id")
        return None
