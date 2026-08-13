from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Optional

from PyQt6 import QtCore, QtWidgets

from botify.model.model import TracksModel

from .media import TrackPreview


class TrackTable(QtWidgets.QTableView):
    track_selected = QtCore.pyqtSignal(object)
    track_activated = QtCore.pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.verticalHeader().setVisible(False)
        self.setSortingEnabled(True)
        self.clicked.connect(self._selected)
        self.doubleClicked.connect(self._activated)

    def set_tracks(
        self, tracks: Sequence[Mapping[str, Any]]
    ) -> Optional[dict[str, Any]]:
        model = TracksModel([dict(track) for track in tracks])
        self.setModel(model)
        self.setColumnHidden(4, True)
        self.resizeColumnsToContents()
        if model.rowCount() == 0:
            return None
        index = model.index(0, 0)
        self.setCurrentIndex(index)
        return model.track_at(0)

    def _track_at(self, index: QtCore.QModelIndex) -> Optional[dict[str, Any]]:
        model = self.model()
        return model.track_at(index.row()) if isinstance(model, TracksModel) else None

    def _selected(self, index: QtCore.QModelIndex) -> None:
        track = self._track_at(index)
        if track:
            self.track_selected.emit(track)

    def _activated(self, index: QtCore.QModelIndex) -> None:
        track = self._track_at(index)
        if track:
            self.track_activated.emit(track)


class TrackBrowserPane(QtWidgets.QWidget):
    track_selected = QtCore.pyqtSignal(object)
    track_activated = QtCore.pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.table = TrackTable()
        self.preview = TrackPreview()
        self.table.track_selected.connect(self.track_selected.emit)
        self.table.track_activated.connect(self.track_activated.emit)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table, 3)
        layout.addWidget(self.preview, 2)

    def set_tracks(
        self, tracks: Sequence[Mapping[str, Any]]
    ) -> Optional[dict[str, Any]]:
        return self.table.set_tracks(tracks)

    def preview_track(
        self, track: Mapping[str, Any], image_urls: Sequence[str]
    ) -> None:
        self.preview.set_track(track, image_urls)
