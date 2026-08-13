from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Optional

from PyQt6 import QtCore
from PyQt6.QtCore import QUrl

from botify.model.music import MusicFilters, MusicLibraryModel, MusicSection
from botify.view.libraries.music import MusicLibraryView


class MusicLibraryController(QtCore.QObject):
    """Connect music-domain operations to a passive ``MusicLibraryView``."""

    def __init__(
        self,
        library_item: Mapping[str, Any],
        client: Any,
        player: Any,
        playback_bar: Any,
        run: Optional[Callable[..., None]] = None,
        parent=None,
    ):
        super().__init__(parent)
        library_id = library_item.get("Id")
        if not library_id:
            raise ValueError("Selected library has no Id")

        self.model = MusicLibraryModel(client, library_id)
        self.view = MusicLibraryView(library_item.get("Name") or "", parent)
        self.player = player
        self.playback_bar = playback_bar
        self._run = run
        self._requests: dict[str, int] = {}
        self._album_artist_id: Optional[str] = None
        self._album_cover_url: Optional[str] = None
        self._showing_album_detail = False

        self.view.refresh_requested.connect(self.refresh)
        self.view.section_changed.connect(self._section_changed)
        self.view.album_selected.connect(self._album_selected)
        self.view.artist_selected.connect(self._artist_selected)
        self.view.track_selected.connect(self._preview_track)
        self.view.track_activated.connect(self._play_track)
        self.view.album_back_requested.connect(self._show_album_grid)

        QtCore.QTimer.singleShot(0, self.initialize)

    def initialize(self) -> None:
        self._request(
            "genres",
            self.model.list_genres,
            self.view.set_genres,
            on_failure=lambda _error: None,
        )
        self.refresh()

    def refresh(self) -> None:
        filters = MusicFilters(**self.view.filter_values())
        section = MusicSection(self.view.current_section)
        if section is MusicSection.SONGS:
            self._showing_album_detail = False
            self._request(
                "songs", lambda: self.model.list_songs(filters), self._songs_loaded
            )
        elif section is MusicSection.ALBUMS:
            self._request(
                "albums",
                lambda: self.model.list_albums(filters, self._album_artist_id),
                self._albums_loaded,
            )
        else:
            self._request(
                "artists",
                lambda: self.model.list_artists(filters),
                self._artists_loaded,
            )

    def _section_changed(self, section: str) -> None:
        self._cancel_request("album_tracks")
        if section != MusicSection.ALBUMS.value:
            self._album_artist_id = None
            self._album_cover_url = None
            self._showing_album_detail = False
        self.refresh()

    def _songs_loaded(self, tracks: list[dict[str, Any]]) -> None:
        first_track = self.view.set_songs(tracks)
        if first_track:
            self._preview_track(first_track)

    def _albums_loaded(self, albums: list[dict[str, Any]]) -> None:
        self._showing_album_detail = False
        self._album_cover_url = None
        self.view.set_albums(albums, self._cover_map(albums))

    def _artists_loaded(self, artists: list[dict[str, Any]]) -> None:
        self.view.set_artists(artists, self._cover_map(artists))

    def _album_selected(self, album: Mapping[str, Any]) -> None:
        album_id = album.get("Id")
        if not album_id:
            return
        covers = self.model.item_cover_urls(album, 600)
        self._album_cover_url = covers[0] if covers else None
        self._request(
            "album_tracks",
            lambda: self.model.list_album_tracks(album_id),
            self._album_tracks_loaded,
        )

    def _album_tracks_loaded(self, tracks: list[dict[str, Any]]) -> None:
        self._showing_album_detail = True
        first_track = self.view.show_album_tracks(tracks)
        if first_track:
            self._preview_track(first_track)

    def _artist_selected(self, artist: Mapping[str, Any]) -> None:
        artist_id = artist.get("Id")
        if not artist_id:
            return
        self._album_artist_id = artist_id
        self.view.set_current_section(MusicSection.ALBUMS.value)

    def _show_album_grid(self) -> None:
        self._cancel_request("album_tracks")
        self._showing_album_detail = False
        self._album_cover_url = None
        self.view.show_album_grid()

    def _preview_track(self, track: Mapping[str, Any]) -> None:
        urls = self.model.track_cover_urls(
            track,
            600,
            album_fallback_url=self._album_cover_url,
            artist_fallback_id=self._album_artist_id,
        )
        self.view.preview_track(track, urls, self._showing_album_detail)

    def _play_track(self, track: Mapping[str, Any]) -> None:
        playback = self.model.playback_item(
            track,
            album_fallback_url=self._album_cover_url,
            artist_fallback_id=self._album_artist_id,
        )
        if not playback:
            return
        self.player.setSource(QUrl(playback.stream_url))
        self.playback_bar.set_now_playing_meta(playback.title, playback.subtitle)
        self.playback_bar.set_cover_async(playback.cover_urls)
        self.player.play()

    def _cover_map(self, items: list[dict[str, Any]]) -> dict[str, tuple[str, ...]]:
        return {
            item["Id"]: self.model.item_cover_urls(item, 300)
            for item in items
            if item.get("Id")
        }

    def _request(
        self,
        key: str,
        operation: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_failure: Optional[Callable[[Exception], None]] = None,
    ) -> None:
        request_id = self._requests.get(key, 0) + 1
        self._requests[key] = request_id

        def success(result: Any) -> None:
            if self._requests.get(key) == request_id:
                on_success(result)

        def failure(error: Exception) -> None:
            if self._requests.get(key) == request_id:
                (on_failure or self.view.show_error)(error)

        if self._run:
            try:
                self._run(operation, success, failure)
            except Exception as error:
                failure(error)
            return
        try:
            success(operation())
        except Exception as error:
            failure(error)

    def _cancel_request(self, key: str) -> None:
        self._requests[key] = self._requests.get(key, 0) + 1


__all__ = ["MusicLibraryController"]
