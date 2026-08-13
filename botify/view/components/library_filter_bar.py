from __future__ import annotations

from typing import Any

from PyQt6 import QtCore, QtWidgets

from .library_search_bar import LibrarySearchBar


class LibraryFilterBar(QtWidgets.QWidget):
    """Reusable search, genre, favorite, and sorting controls."""

    changed = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.search = LibrarySearchBar()
        self.genre = QtWidgets.QComboBox()
        self.genre.addItem("(Any)", None)
        self.favorites = QtWidgets.QCheckBox("Favorites only")
        self.sort = QtWidgets.QComboBox()
        self.sort.addItems(
            ["Name", "Artist", "Album", "DateCreated", "PlayCount", "Random"]
        )
        self.direction = QtWidgets.QPushButton("Asc")
        self.direction.setCheckable(True)
        refresh = QtWidgets.QPushButton("Refresh")

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.search)
        layout.addWidget(self.genre)
        layout.addWidget(self.favorites)
        layout.addWidget(self.sort)
        layout.addWidget(self.direction)
        layout.addWidget(refresh)

        self.search.searchRequested.connect(self.changed.emit)
        self.genre.currentIndexChanged.connect(self.changed.emit)
        self.favorites.stateChanged.connect(self.changed.emit)
        self.sort.currentIndexChanged.connect(self.changed.emit)
        self.direction.toggled.connect(self._direction_changed)
        refresh.clicked.connect(self.changed.emit)

    def values(self) -> dict[str, Any]:
        return {
            "search": self.search.text(),
            "genre": self.genre.currentData(),
            "favorites_only": self.favorites.isChecked(),
            "sort_by": self.sort.currentText(),
            "descending": self.direction.isChecked(),
        }

    def set_genres(self, genres: list[str]) -> None:
        self.genre.blockSignals(True)
        try:
            selected = self.genre.currentData()
            self.genre.clear()
            self.genre.addItem("(Any)", None)
            for genre in genres:
                self.genre.addItem(genre, genre)
            if selected:
                index = self.genre.findData(selected)
                if index >= 0:
                    self.genre.setCurrentIndex(index)
        finally:
            self.genre.blockSignals(False)

    def _direction_changed(self, descending: bool) -> None:
        self.direction.setText("Desc" if descending else "Asc")
        self.changed.emit()
