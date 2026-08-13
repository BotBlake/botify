from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Optional

from PyQt6 import QtCore, QtWidgets

from botify.view.components import ItemGrid, LibraryFilterBar, TrackBrowserPane


class MusicLibraryView(QtWidgets.QWidget):
    """Passive music-library view composed from reusable widgets."""

    refresh_requested = QtCore.pyqtSignal()
    section_changed = QtCore.pyqtSignal(str)
    album_selected = QtCore.pyqtSignal(object)
    artist_selected = QtCore.pyqtSignal(object)
    track_selected = QtCore.pyqtSignal(object)
    track_activated = QtCore.pyqtSignal(object)
    album_back_requested = QtCore.pyqtSignal()

    _SECTIONS = ("songs", "albums", "artists")

    def __init__(self, library_name: str = "", parent=None):
        super().__init__(parent)
        self.filter_bar = LibraryFilterBar()
        self.tabs = QtWidgets.QTabWidget()
        self.songs = TrackBrowserPane()
        self.albums = ItemGrid()
        self.artists = ItemGrid()
        self.album_tracks = TrackBrowserPane()
        self.album_stack = QtWidgets.QStackedWidget()

        if library_name:
            title = QtWidgets.QLabel(library_name)
            title.setStyleSheet("font-size:18px;font-weight:600")
        else:
            title = None

        self.tabs.addTab(self.songs, "Songs")
        self.tabs.addTab(self._build_albums_tab(), "Albums")
        self.tabs.addTab(self.artists, "Artists")

        layout = QtWidgets.QVBoxLayout(self)
        if title:
            layout.addWidget(title)
        layout.addWidget(self.filter_bar)
        layout.addWidget(self.tabs)

        self.filter_bar.changed.connect(self.refresh_requested.emit)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.albums.item_selected.connect(self.album_selected.emit)
        self.artists.item_selected.connect(self.artist_selected.emit)
        self.songs.track_selected.connect(self.track_selected.emit)
        self.songs.track_activated.connect(self.track_activated.emit)
        self.album_tracks.track_selected.connect(self.track_selected.emit)
        self.album_tracks.track_activated.connect(self.track_activated.emit)

    @property
    def current_section(self) -> str:
        return self._SECTIONS[self.tabs.currentIndex()]

    def filter_values(self) -> dict[str, Any]:
        return self.filter_bar.values()

    def set_current_section(self, section: str) -> None:
        if section in self._SECTIONS:
            self.tabs.setCurrentIndex(self._SECTIONS.index(section))

    def set_genres(self, genres: list[str]) -> None:
        self.filter_bar.set_genres(genres)

    def set_songs(
        self, tracks: Sequence[Mapping[str, Any]]
    ) -> Optional[dict[str, Any]]:
        return self.songs.set_tracks(tracks)

    def set_albums(
        self,
        albums: Sequence[Mapping[str, Any]],
        cover_urls: Mapping[str, Sequence[str]],
    ) -> None:
        self.albums.set_items(albums, cover_urls)
        self.show_album_grid()

    def set_artists(
        self,
        artists: Sequence[Mapping[str, Any]],
        cover_urls: Mapping[str, Sequence[str]],
    ) -> None:
        self.artists.set_items(artists, cover_urls)

    def show_album_tracks(
        self, tracks: Sequence[Mapping[str, Any]]
    ) -> Optional[dict[str, Any]]:
        first_track = self.album_tracks.set_tracks(tracks)
        self.album_stack.setCurrentIndex(1)
        return first_track

    def show_album_grid(self) -> None:
        self.albums.stop_marquee()
        self.album_stack.setCurrentIndex(0)

    def preview_track(
        self,
        track: Mapping[str, Any],
        image_urls: Sequence[str],
        album_detail: bool,
    ) -> None:
        pane = self.album_tracks if album_detail else self.songs
        pane.preview_track(track, image_urls)

    def show_error(self, error: Exception) -> None:
        QtWidgets.QMessageBox.critical(self, "Error", str(error))

    def _build_albums_tab(self) -> QtWidgets.QWidget:
        grid_page = QtWidgets.QWidget()
        grid_layout = QtWidgets.QVBoxLayout(grid_page)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.addWidget(self.albums)

        detail_page = QtWidgets.QWidget()
        detail_layout = QtWidgets.QVBoxLayout(detail_page)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        back_row = QtWidgets.QHBoxLayout()
        back_button = QtWidgets.QPushButton("← Back to Albums")
        back_button.clicked.connect(self.album_back_requested.emit)
        back_row.addWidget(back_button)
        back_row.addStretch(1)
        detail_layout.addLayout(back_row)
        detail_layout.addWidget(self.album_tracks)

        self.album_stack.addWidget(grid_page)
        self.album_stack.addWidget(detail_page)
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.album_stack)
        return page

    def _tab_changed(self, index: int) -> None:
        if 0 <= index < len(self._SECTIONS):
            self.section_changed.emit(self._SECTIONS[index])


__all__ = ["MusicLibraryView"]
