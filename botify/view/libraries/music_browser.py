from __future__ import annotations

from typing import Any, Dict, Optional

from PyQt6 import QtCore, QtWidgets
from PyQt6.QtCore import Qt, QUrl, QSize
from PyQt6.QtGui import QPixmap

from botify.model.model import TracksModel
from botify.view.libraries.music import music_query_params
from botify.view.components import LibrarySearchBar, GridItemWidget

class MusicLibraryView(QtWidgets.QWidget):
    """A small music browser with Songs, Albums and Artists views.

    Uses JellyfinClient.list_items_in_parent to query scoped results and reuses
    the existing TracksModel and playback player passed in.
    """

    def __init__(
        self,
        library_item: Dict[str, Any],
        client,
        player,
        playback_bar,
        run=None,
        parent=None,
    ):
        super().__init__(parent)
        self.client = client
        self.player = player
        self.playback_bar = playback_bar
        self.library = library_item
        self.lib_id = library_item.get("Id")
        # optional runner for background tasks (controller._run)
        self.run = run

        self.layout = QtWidgets.QVBoxLayout(self)

        # Controls row
        self.controls_row = QtWidgets.QHBoxLayout()
        self.search_bar = LibrarySearchBar()
        self.search_bar.searchRequested.connect(self.reload_current)
        self.controls_row.addWidget(self.search_bar)

        self.genre_combo = QtWidgets.QComboBox()
        self.genre_combo.setEditable(False)
        self.genre_combo.addItem("(Any)")
        self.genre_combo.currentIndexChanged.connect(self.reload_current)
        self.controls_row.addWidget(self.genre_combo)

        self.favorite_chk = QtWidgets.QCheckBox("Favorites only")
        self.favorite_chk.stateChanged.connect(self.reload_current)
        self.controls_row.addWidget(self.favorite_chk)

        self.sort_combo = QtWidgets.QComboBox()
        self.sort_combo.addItems(["Name", "Artist", "Album", "DateCreated", "PlayCount", "Random"])
        self.controls_row.addWidget(self.sort_combo)

        self.sort_dir_btn = QtWidgets.QPushButton("Asc")
        self.sort_dir_btn.setCheckable(True)
        self.sort_dir_btn.toggled.connect(lambda v: self.sort_dir_btn.setText("Desc" if v else "Asc"))
        self.controls_row.addWidget(self.sort_dir_btn)

        self.refresh_btn = QtWidgets.QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.reload_current)
        self.controls_row.addWidget(self.refresh_btn)

        self.layout.addLayout(self.controls_row)

        # Tabs for Songs / Albums / Artists
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._build_songs_tab(), "Songs")
        self.tabs.addTab(self._build_albums_tab(), "Albums")
        self.tabs.addTab(self._build_artists_tab(), "Artists")
        self.tabs.currentChanged.connect(lambda _: self.reload_current())
        self.layout.addWidget(self.tabs)

        # Internal small state to coordinate pending navigation and avoid reload races
        self._pending_artist_filter: Optional[str] = None
        self._active_artist_id: Optional[str] = None
        self._suppress_next_reload: bool = False

        # Helper to execute background tasks using controller._run if provided
        def _bg_run(fn, on_ok, on_err=None):
            if self.run:
                try:
                    self.run(fn, on_ok, on_err)
                except Exception as e:
                    if on_err:
                        on_err(e)
                    else:
                        QtWidgets.QMessageBox.critical(self, "Error", str(e))
            else:
                # fallback: run synchronously (keeps compatibility)
                try:
                    res = fn()
                    on_ok(res)
                except Exception as e:
                    if on_err:
                        on_err(e)
                    else:
                        QtWidgets.QMessageBox.critical(self, "Error", str(e))

        self._bg_run = _bg_run

        # Initially populate genres (best effort)
        QtCore.QTimer.singleShot(0, lambda: self._bg_run(self._populate_genres_fn, self._on_genres_loaded))
        # Initial load
        QtCore.QTimer.singleShot(0, self.reload_current)

    # --- UI builders
    def _build_songs_tab(self):
        w = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(w)
        # Table on left
        self.songs_table = QtWidgets.QTableView()
        self.songs_table.doubleClicked.connect(self._play_song)
        self.songs_table.clicked.connect(self._preview_song)
        self.songs_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.songs_table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.songs_table.verticalHeader().setVisible(False)
        self.songs_table.setSortingEnabled(True)

        # Preview on right
        from botify.view.view import TrackPreview

        self.songs_preview = TrackPreview()

        h.addWidget(self.songs_table, 3)
        h.addWidget(self.songs_preview, 2)
        return w

    def _build_albums_tab(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        # Use a stacked widget: index 0 = grid of albums, index 1 = album detail (tracks)
        self.albums_stack = QtWidgets.QStackedWidget()

        # Grid page
        grid_page = QtWidgets.QWidget()
        grid_layout = QtWidgets.QVBoxLayout(grid_page)
        self.albums_grid = QtWidgets.QListWidget()
        self.albums_grid.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
        self.albums_grid.setIconSize(QSize(150, 150))
        # force fixed grid cell size so icons and titles align
        self.albums_grid.setGridSize(QSize(170, 210))
        self.albums_grid.setResizeMode(QtWidgets.QListView.ResizeMode.Adjust)
        self.albums_grid.setSpacing(12)
        # single click opens album (per request) and starts marquee
        self.albums_grid.itemClicked.connect(self._album_item_activated)
        grid_layout.addWidget(self.albums_grid)

        # Detail page (reuses TrackPreview like Songs tab)
        detail_page = QtWidgets.QWidget()
        detail_layout = QtWidgets.QVBoxLayout(detail_page)
        back_row = QtWidgets.QHBoxLayout()
        self.album_back_btn = QtWidgets.QPushButton("← Back to Albums")
        def _back_to_grid():
            try:
                if hasattr(self, "_current_marquee_widget") and self._current_marquee_widget:
                    self._current_marquee_widget.stop_marquee()
            except Exception:
                pass
            self.albums_stack.setCurrentIndex(0)
        self.album_back_btn.clicked.connect(_back_to_grid)
        back_row.addWidget(self.album_back_btn)
        back_row.addStretch(1)
        detail_layout.addLayout(back_row)

        # Tracks (left) + preview (right)
        tracks_preview_h = QtWidgets.QHBoxLayout()
        self.album_tracks_table = QtWidgets.QTableView()
        self.album_tracks_table.doubleClicked.connect(lambda idx: self._play_from_table(self.album_tracks_table, idx))
        self.album_tracks_table.clicked.connect(self._preview_album_track)
        self.album_tracks_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.album_tracks_table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.album_tracks_table.verticalHeader().setVisible(False)
        self.album_tracks_table.setSortingEnabled(True)

        from botify.view.view import TrackPreview
        self.album_preview = TrackPreview()

        tracks_preview_h.addWidget(self.album_tracks_table, 3)
        tracks_preview_h.addWidget(self.album_preview, 2)
        detail_layout.addLayout(tracks_preview_h)

        self.albums_stack.addWidget(grid_page)
        self.albums_stack.addWidget(detail_page)

        v.addWidget(self.albums_stack)
        return w

    def _build_artists_tab(self):
        # Use icon-grid artists view for parity with albums
        return self._build_artists_grid()

    # --- Data loading
    def _make_base_params(self) -> Dict[str, Any]:
        # Start with music defaults
        params = music_query_params(self.lib_id).copy()
        # apply search
        s = self.search_bar.text().strip()
        if s:
            params["SearchTerm"] = s
        # favorites
        if self.favorite_chk.isChecked():
            params["IsFavorite"] = True
        # genre
        genre = self.genre_combo.currentText()
        if genre and genre != "(Any)":
            params["Genres"] = genre
        # paging sensible default
        params.setdefault("StartIndex", 0)
        params.setdefault("Limit", 200)
        return params

    def reload_current(self):
        # Suppress one automatic reload if another navigation just set the content
        if getattr(self, "_suppress_next_reload", False):
            self._suppress_next_reload = False
            return

        idx = self.tabs.currentIndex()
        if idx == 0:
            # if there's a pending parent (album) load requested via grid click, use it
            if getattr(self, "_pending_song_parent", None):
                parent_id, parent_img = self._pending_song_parent
                self._pending_song_parent = None
                self._load_songs_for_parent(parent_id, parent_img)
            else:
                self._load_songs()
        elif idx == 1:
            # if an artist filter was requested just before switching here, apply it
            if getattr(self, "_pending_artist_filter", None):
                artist_id = self._pending_artist_filter
                self._pending_artist_filter = None
                self._load_albums(artist_id=artist_id)
            else:
                self._load_albums()
        else:
            self._load_artists()

    def _load_songs(self):
        params = self._make_base_params()
        # sorting mapping
        sort_map = {
            "Name": "Name",
            "Artist": "Artist",
            "Album": "Album",
            "DateCreated": "DateCreated",
            "PlayCount": "PlayCount",
            "Random": "Random",
        }
        params["SortBy"] = sort_map.get(self.sort_combo.currentText(), "SortName")
        params["SortOrder"] = "Descending" if self.sort_dir_btn.isChecked() else "Ascending"

        def fetch():
            return self.client.list_items_in_parent(self.lib_id, params=params)

        def on_ok(items):
            try:
                self._set_tracks_model(self.songs_table, items)
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error", str(e))

        def on_err(e):
            QtWidgets.QMessageBox.critical(self, "Error", str(e))

        self._bg_run(fetch, on_ok, on_err)

    def _load_albums(self, artist_id: Optional[str] = None):
        params = self._make_base_params()
        # ensure we request albums
        params["IncludeItemTypes"] = "MusicAlbum"
        self._active_artist_id = artist_id
        # sorting
        sort_map = {
            "Name": "SortName",
            "AlbumArtist": "AlbumArtist",
            "ProductionYear": "ProductionYear",
            "DateCreated": "DateCreated",
        }
        sel = self.sort_combo.currentText()
        params["SortBy"] = sort_map.get(sel, "SortName")
        params["SortOrder"] = "Descending" if self.sort_dir_btn.isChecked() else "Ascending"

        def fetch():
            # Direct call into client; scope by parentId (lib) and optionally artistIds
            p = params.copy()
            if artist_id:
                p["artistIds"] = artist_id
                p["ArtistIds"] = artist_id
            return self.client.list_items_in_parent(self.lib_id, params=p)

        def on_ok(items):
            try:
                # Populate grid
                self.albums_grid.clear()
                from botify.model import image_loader

                # prepare a placeholder pixmap (frame) to show while images load
                placeholder_pm = image_loader.placeholder(150)

                # manage marquee widget reference
                self._current_marquee_widget = None

                for it in items:
                    self._add_grid_item(self.albums_grid, it, placeholder_pm, size=150)

                # show grid page
                self.albums_stack.setCurrentIndex(0)
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error", str(e))

        def on_err(e):
            QtWidgets.QMessageBox.critical(self, "Error", str(e))

        self._bg_run(fetch, on_ok, on_err)

    def _load_artists(self):
        params = self._make_base_params()
        params["IncludeItemTypes"] = "MusicArtist"
        params["SortBy"] = "SortName"
        params["SortOrder"] = "Ascending"

        def fetch():
            return self.client.list_items_in_parent(self.lib_id, params=params)

        def on_ok(items):
            try:
                self.artists_grid.clear()
                from botify.model import image_loader
                placeholder_pm = image_loader.placeholder(150)
                for it in items:
                    self._add_grid_item(self.artists_grid, it, placeholder_pm, size=150)
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error", str(e))

        def on_err(e):
            QtWidgets.QMessageBox.critical(self, "Error", str(e))

        self._bg_run(fetch, on_ok, on_err)

    # --- album grid interactions
    def _album_item_activated(self, item: QtWidgets.QListWidgetItem):
        """Handle click of an album item in the grid.

        Behavior:
        - Stop any previous marquee.
        - Start marquee on clicked item.
        - Load the album's songs and switch to the Songs tab so the main Songs
          UI is reused (preview/playback behavior remains consistent).
        """
        try:
            it = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(it, dict):
                return
            album_id = it.get("Id")
            album_image = None
            try:
                if album_id:
                    album_image = self.client.image_url_for_item(album_id, "Primary", 400)
            except Exception:
                album_image = None
            # Stop previous marquee widget if any
            try:
                if hasattr(self, "_current_marquee_widget") and self._current_marquee_widget:
                    self._current_marquee_widget.stop_marquee()
            except Exception:
                pass
            # start marquee on the clicked item's widget
            try:
                w = self.albums_grid.itemWidget(item)
                if w and hasattr(w, "start_marquee"):
                    w.start_marquee()
                    self._current_marquee_widget = w
            except Exception:
                pass
            # Open album detail inside the Albums tab (show tracks in the detail pane)
            # Load tracks for album into album_tracks_table and show the detail page
            self._load_album_detail(album_id, album_image)
        except Exception:
            return

    # Artists grid (icon-mode) for parity with albums
    def _build_artists_grid(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        self.artists_grid = QtWidgets.QListWidget()
        self.artists_grid.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
        self.artists_grid.setIconSize(QSize(150, 150))
        self.artists_grid.setGridSize(QSize(170, 210))
        self.artists_grid.setResizeMode(QtWidgets.QListView.ResizeMode.Adjust)
        self.artists_grid.setSpacing(12)
        self.artists_grid.itemClicked.connect(self._artist_item_clicked)
        v.addWidget(self.artists_grid)
        return w

    def _add_grid_item(self, grid: QtWidgets.QListWidget, item_dict: Dict[str, Any], placeholder_pm: QPixmap, size: int = 150):
        """Add an item to a grid (albums or artists) and asynchronously load its cover."""
        name = item_dict.get("Name") or "(untitled)"
        aid = item_dict.get("Id")
        list_item = QtWidgets.QListWidgetItem()
        list_item.setData(Qt.ItemDataRole.UserRole, item_dict)
        widget = GridItemWidget(name, size=size)
        widget.set_pixmap(placeholder_pm)
        grid.addItem(list_item)
        grid.setItemWidget(list_item, widget)
        list_item.setSizeHint(widget.sizeHint())
        if not aid:
            return
        try:
            url = self.client.image_url_for_item(aid, "Primary", 300)
        except Exception:
            url = None
        if not url:
            return
        from botify.model import image_loader
        def make_ok(li=list_item, g=grid):
            def _ok(pix):
                if pix is None or pix.isNull():
                    return
                try:
                    w = g.itemWidget(li)
                    if w:
                        w.set_pixmap(pix)
                except Exception:
                    pass
            return _ok
        def make_err(aid_id):
            def _err(e):
                pass
            return _err
        image_loader.load(url, make_ok(), make_err(aid))

    def _item_image_url(self, item_id: Optional[str], max_side: int) -> Optional[str]:
        if not item_id:
            return None
        try:
            return self.client.image_url_for_item(item_id, "Primary", max_side)
        except Exception:
            return None

    def _first_artist_id(self, track: Dict[str, Any]) -> Optional[str]:
        artist_items = track.get("ArtistItems") or []
        if isinstance(artist_items, list):
            for entry in artist_items:
                if isinstance(entry, dict) and entry.get("Id"):
                    return entry.get("Id")
        artist_ids = track.get("ArtistIds") or []
        if isinstance(artist_ids, list) and artist_ids:
            return artist_ids[0]
        return self._active_artist_id

    def _resolve_track_image_url(
        self,
        track: Dict[str, Any],
        max_side: int,
        album_fallback_url: Optional[str] = None,
    ) -> Optional[str]:
        # 1) track image
        track_id = track.get("Id")
        image_url = self._item_image_url(track_id, max_side)
        if image_url:
            return image_url
        # 2) album image
        album_id = track.get("AlbumId")
        image_url = self._item_image_url(album_id, max_side)
        if image_url:
            return image_url
        if album_fallback_url:
            return album_fallback_url
        # 3) artist image
        artist_id = self._first_artist_id(track)
        return self._item_image_url(artist_id, max_side)

    def _set_tracks_model(self, table: QtWidgets.QTableView, items: list):
        model = TracksModel(items)
        table.setModel(model)
        table.setColumnHidden(4, True)
        table.resizeColumnsToContents()
        return model

    def _artist_item_clicked(self, item: QtWidgets.QListWidgetItem):
        # open albums view filtered by this artist
        try:
            it = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(it, dict):
                return
            artist_id = it.get("Id")
            # request albums view filtered by this artist
            # Use pending state so the tab-change handler applies the filter (avoids races)
            self._pending_artist_filter = artist_id
            # Switch to Albums tab; reload_current will pick up _pending_artist_filter
            self.tabs.setCurrentIndex(1)
        except Exception:
            return
    # --- interactions
    def _preview_song(self, index: QtCore.QModelIndex):
        model: TracksModel = self.songs_table.model()  # type: ignore
        if not model:
            return
        row = index.row()
        track = model.rows[row]
        image_url = self._resolve_track_image_url(
            track, 600, getattr(self, "current_album_image", None)
        )
        self.songs_preview.set_track(track, image_url)

    def _preview_album_track(self, index: QtCore.QModelIndex):
        """Preview a track selected in the album detail page, reusing TrackPreview.

        Prefer the track's own image when available, else fallback to the album cover.
        """
        model: TracksModel = self.album_tracks_table.model()  # type: ignore
        if not model:
            return
        row = index.row()
        track = model.rows[row]
        image_url = self._resolve_track_image_url(
            track, 600, getattr(self, "current_album_image", None)
        )
        self.album_preview.set_track(track, image_url)

    def _play_song(self, index: QtCore.QModelIndex):
        model: TracksModel = self.songs_table.model()  # type: ignore
        if not model:
            return
        row = index.row()
        track = model.rows[row]
        item_id = track.get("Id")
        if not item_id:
            return
        url = QUrl(self.client.stream_url_for_track(item_id))
        self.player.setSource(url)
        title = track.get("Name", "")
        subtitle = ", ".join(track.get("Artists") or [])
        self.playback_bar.set_now_playing_meta(title, subtitle)
        track_img = self._resolve_track_image_url(
            track, 400, getattr(self, "current_album_image", None)
        )
        if track_img:
            self.playback_bar.set_cover_async(track_img)
        self.player.play()

    def _load_songs_for_parent(self, parent_id: str, parent_image_url: Optional[str] = None):
        """Load songs scoped to a parent (library or album) and show them in the Songs tab.

        This reuses the existing TracksModel and the Songs tab UI so previews and
        playback behave consistently.
        """
        if not parent_id:
            return
        params = {"IncludeItemTypes": "Audio", "Recursive": True, "SortBy": "ParentIndexNumber,IndexNumber,SortName", "SortOrder": "Ascending"}

        def fetch():
            return self.client.list_items_in_parent(parent_id, params=params)

        def on_ok(items):
            try:
                model = self._set_tracks_model(self.songs_table, items)
                # remember current album image for playback/preview
                self.current_album_image = parent_image_url
                # show Songs tab (suppress the automatic reload which would otherwise re-query the whole library)
                self._suppress_next_reload = True
                self.tabs.setCurrentIndex(0)
                # select first row + preview
                if model.rowCount() > 0:
                    idx = model.index(0, 0)
                    self.songs_table.setCurrentIndex(idx)
                    self._preview_song(idx)
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error", str(e))

        def on_err(e):
            QtWidgets.QMessageBox.critical(self, "Error", str(e))

        self._bg_run(fetch, on_ok, on_err)

    def _show_album_tracks(self, album_id: str, album_image_url: Optional[str] = None):
        # backward compat: keep API
        self._load_songs_for_parent(album_id, album_image_url)

    def _load_album_detail(self, album_id: str, album_image_url: Optional[str] = None):
        """Load tracks for the given album into the album detail pane and switch to it.

        This keeps the Albums tab active and shows the album's tracks in-place,
        preserving the 'Back to Albums' button and album preview.
        """
        if not album_id:
            return
        params = {"IncludeItemTypes": "Audio", "Recursive": True, "SortBy": "ParentIndexNumber,IndexNumber,SortName", "SortOrder": "Ascending"}

        def fetch():
            return self.client.list_items_in_parent(album_id, params=params)

        def on_ok(items):
            try:
                model = self._set_tracks_model(self.album_tracks_table, items)
                self.current_album_image = album_image_url
                # show album detail page and select first track
                self.albums_stack.setCurrentIndex(1)
                if model.rowCount() > 0:
                    idx = model.index(0, 0)
                    self.album_tracks_table.setCurrentIndex(idx)
                    self._preview_album_track(idx)
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error", str(e))

        def on_err(e):
            QtWidgets.QMessageBox.critical(self, "Error", str(e))

        self._bg_run(fetch, on_ok, on_err)

    def _play_from_table(self, table: QtWidgets.QTableView, index: QtCore.QModelIndex):
        model: TracksModel = table.model()  # type: ignore
        if not model:
            return
        row = index.row()
        track = model.rows[row]
        item_id = track.get("Id")
        if not item_id:
            return
        from PyQt6.QtCore import QUrl

        url = QUrl(self.client.stream_url_for_track(item_id))
        self.player.setSource(url)
        title = track.get("Name", "")
        subtitle = ", ".join(track.get("Artists") or [])
        self.playback_bar.set_now_playing_meta(title, subtitle)
        track_img = self._resolve_track_image_url(
            track, 400, getattr(self, "current_album_image", None)
        )
        if track_img:
            self.playback_bar.set_cover_async(track_img)
        self.player.play()

    # --- helpers
    def _populate_genres_fn(self):
        # Best-effort attempt to fetch available genres for the library using Items/Filters
        genres: list = []
        try:
            user_id = self.client.state.user_id
            if not user_id:
                return genres
            path = f"/Users/{user_id}/Items/Filters"
            params = {"parentId": self.lib_id, "IncludeItemTypes": "Audio"}
            data = self.client._call_endpoint(path, params=params)
            # data may be a dict with 'Filters' or list; search for group with 'Name' == 'Genres'
            groups = data.get("Filters") if isinstance(data, dict) else None
            if not groups:
                return genres
            for g in groups:
                if g.get("Name") and "genre" in g.get("Name").lower():
                    for val in g.get("Values", [])[:50]:
                        name = val.get("Name")
                        if name:
                            genres.append(name)
                    break
        except Exception:
            # ignore errors — genre filter remains optional
            pass
        return genres

    def _on_genres_loaded(self, genres: list):
        if not genres:
            return
        try:
            self.genre_combo.blockSignals(True)
            for g in genres:
                self.genre_combo.addItem(g)
        finally:
            self.genre_combo.blockSignals(False)


__all__ = ["MusicLibraryView"]
