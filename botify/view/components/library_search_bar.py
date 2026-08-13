from __future__ import annotations

from PyQt6 import QtCore, QtWidgets


class LibrarySearchBar(QtWidgets.QWidget):
    """Reusable search input with explicit trigger for library views."""

    searchRequested = QtCore.pyqtSignal()

    def __init__(self, placeholder: str = "Search…", parent=None):
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._line_edit = QtWidgets.QLineEdit()
        self._line_edit.setPlaceholderText(placeholder)
        self._line_edit.returnPressed.connect(self.searchRequested.emit)
        layout.addWidget(self._line_edit)

    def text(self) -> str:
        return self._line_edit.text()
