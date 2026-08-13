from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6 import QtCore, QtWidgets
from PyQt6.QtCore import Qt, QUrl, QSize
from PyQt6.QtGui import QPixmap, QColor

from botify.model.model import TracksModel
from botify.view.libraries.music import music_query_params


class SimpleTableModel(QtCore.QAbstractTableModel):
    def __init__(self, headers: List[str], rows: List[Dict[str, Any]]):
        super().__init__()
        self.headers = headers
        self.rows = rows

    def rowCount(self, parent=QtCore.QModelIndex()) -> int:
        return len(self.rows)

    def columnCount(self, parent=QtCore.QModelIndex()) -> int:
        return len(self.headers)

    def data(self, index: QtCore.QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = self.rows[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            key = self.headers[col]
            return item.get(key, "")
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.headers[section]
        return None


class GridItemWidget(QtWidgets.QWidget):
    """Reusable grid item used for albums and artists: icon + elided title + optional marquee."""
    def __init__(self, title: str, size: int = 150, parent=None):
        super().__init__(parent)
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)
        self.size = size
        self.icon_lbl = QtWidgets.QLabel()
        self.icon_lbl.setFixedSize(size, size)
        self.icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_lbl = QtWidgets.QLabel()
        self.title_lbl.setFixedWidth(size)
        self.title_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.title_lbl.setWordWrap(False)
        fm = self.title_lbl.fontMetrics()
        elided = fm.elidedText(title, Qt.TextElideMode.ElideRight, size)
        self.full_title = title
        self.title_lbl.setText(elided)
        v.addWidget(self.icon_lbl)
        v.addWidget(self.title_lbl)
        self._marquee_timer = QtCore.QTimer(self)
        self._marquee_timer.setInterval(250)
        self._marquee_index = 0
        self._marquee_enabled = False
        self._marquee_timer.timeout.connect(self._on_marquee)

    def set_pixmap(self, pix: QPixmap):
        if pix is None or pix.isNull():
            self.icon_lbl.setPixmap(QPixmap())
        else:
            self.icon_lbl.setPixmap(pix.scaled(self.size, self.size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def start_marquee(self):
        if len(self.full_title) <= 20:
            return
        self._marquee_enabled = True
        self._marquee_index = 0
        self._marquee_timer.start()

    def stop_marquee(self):
        self._marquee_timer.stop()
        fm = self.title_lbl.fontMetrics()
        self.title_lbl.setText(fm.elidedText(self.full_title, Qt.TextElideMode.ElideRight, self.size))

    def _on_marquee(self):
        if not self._marquee_enabled:
            return
        text = self.full_title + "   "
        n = len(text)
        i = self._marquee_index % n
        display = text[i: i + 30]
        self.title_lbl.setText(display)
        self._marquee_index += 1


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
        # Enable temporary debug logging for music view requests to aid diagnostics
        # Set to False to disable verbose logs
        self._debug_music_logs = True

        self.layout = QtWidgets.QVBoxLayout(self)

        # Controls row
        self.controls_row = QtWidgets.QHBoxLayout()
        self.search_box = QtWidgets.QLineEdit()
        self.search_box.setPlaceholderText("Search…")
        self.search_box.returnPressed.connect(self.reload_current)
        self.controls_row.addWidget(self.search_box)

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
        s = self.search_box.text().strip()
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
            # Directly call the existing Jellyfin client to keep changes minimal
            if getattr(self, "_debug_music_logs", False):
                print(f"[Music DEBUG] fetch songs params: {params}")
            return self.client.list_items_in_parent(self.lib_id, params=params)

        def on_ok(items):
            try:
                if getattr(self, "_debug_music_logs", False):
                    ids = [f"{i.get('Id')}: {i.get('Name')!r}" for i in (items or [])[:10]]
                    print(f"[Music DEBUG] fetched songs count={len(items)} sample={ids}")
                model = TracksModel(items)
                self.songs_table.setModel(model)
                self.songs_table.setColumnHidden(4, True)
                self.songs_table.resizeColumnsToContents()
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error", str(e))

        def on_err(e):
            QtWidgets.QMessageBox.critical(self, "Error", str(e))

        self._bg_run(fetch, on_ok, on_err)

    def _load_albums(self, artist_id: Optional[str] = None):
        params = self._make_base_params()
        # ensure we request albums
        params["IncludeItemTypes"] = "MusicAlbum"
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
            if getattr(self, "_debug_music_logs", False):
                print(f"[Music DEBUG] fetch albums params: {p}")
            return self.client.list_items_in_parent(self.lib_id, params=p)

        def on_ok(items):
            try:
                if getattr(self, "_debug_music_logs", False):
                    ids = [f"{i.get('Id')}: {i.get('Name')!r}" for i in (items or [])[:10]]
                    print(f"[Music DEBUG] fetched albums count={len(items)} sample={ids}")
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
        image_url = None
        # Prefer track's own image; fallback to current album image if present
        if hasattr(self.client, "image_url_for_item") and track.get("Id"):
            try:
                image_url = self.client.image_url_for_item(track["Id"], "Primary", 600)
            except Exception:
                image_url = None
        if not image_url and hasattr(self, "current_album_image") and self.current_album_image:
            image_url = self.current_album_image
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
        image_url = None
        # Prefer the track's image first
        if hasattr(self.client, "image_url_for_item") and track.get("Id"):
            try:
                image_url = self.client.image_url_for_item(track["Id"], "Primary", 600)
            except Exception:
                image_url = None
        # Fallback to album image if track image isn't available
        if not image_url and hasattr(self, "current_album_image") and self.current_album_image:
            image_url = self.current_album_image
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
        # Prefer the song's own cover; fallback to album image if not available
        try:
            track_img = self.client.image_url_for_item(item_id, "Primary", 400)
        except Exception:
            track_img = None
        if track_img:
            self.playback_bar.set_cover_async(track_img)
        elif hasattr(self, "current_album_image") and self.current_album_image:
            self.playback_bar.set_cover_async(self.current_album_image)
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
            # Historically the album's items are fetched by using the album id
            # as the parentId. That reliably returns the album's tracks.
            if getattr(self, "_debug_music_logs", False):
                print(f"[Music DEBUG] fetch album_tracks parent_id={parent_id} params={params}")
            return self.client.list_items_in_parent(parent_id, params=params)

        def on_ok(items):
            try:
                if getattr(self, "_debug_music_logs", False):
                    ids = [f"{i.get('Id')}: {i.get('Name')!r}" for i in (items or [])[:10]]
                    print(f"[Music DEBUG] fetched album_tracks count={len(items)} sample={ids}")
                model = TracksModel(items)
                self.songs_table.setModel(model)
                self.songs_table.setColumnHidden(4, True)
                self.songs_table.resizeColumnsToContents()
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
            if getattr(self, "_debug_music_logs", False):
                print(f"[Music DEBUG] load_album_detail album_id={album_id} params={params}")
            return self.client.list_items_in_parent(album_id, params=params)

        def on_ok(items):
            try:
                if getattr(self, "_debug_music_logs", False):
                    ids = [f"{i.get('Id')}: {i.get('Name')!r}" for i in (items or [])[:10]]
                    print(f"[Music DEBUG] album_detail fetched count={len(items)} sample={ids}")
                model = TracksModel(items)
                self.album_tracks_table.setModel(model)
                self.album_tracks_table.setColumnHidden(4, True)
                self.album_tracks_table.resizeColumnsToContents()
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

    def _open_album(self, index: QtCore.QModelIndex):
        # This method left for compatibility with old table-based album view.
        model: SimpleTableModel = self.albums_table.model()  # type: ignore
        if not model:
            return
        row = index.row()
        album_id = model.rows[row].get("Id")
        if not album_id:
            return
        # attempt to fetch album image
        album_image = None
        try:
            album_image = self.client.image_url_for_item(album_id, "Primary", 400)
        except Exception:
            album_image = None
        self._show_album_tracks(album_id, album_image)

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
        # Prefer the song's own cover; fallback to album image if not available
        try:
            track_img = self.client.image_url_for_item(item_id, "Primary", 400)
        except Exception:
            track_img = None
        if track_img:
            self.playback_bar.set_cover_async(track_img)
        elif hasattr(self, "current_album_image") and self.current_album_image:
            self.playback_bar.set_cover_async(self.current_album_image)
        self.player.play()

    def _open_artist(self, index: QtCore.QModelIndex):
        model: SimpleTableModel = self.artists_table.model()  # type: ignore
        if not model:
            return
        row = index.row()
        artist_id = model.rows[row].get("Id")
        if not artist_id:
            return
        # Query albums by this artist within the library
        params = {"IncludeItemTypes": "MusicAlbum", "Recursive": True, "artistIds": artist_id}
        try:
            items = self.client.list_items_in_parent(self.lib_id, params=params)
            rows = []
            for it in items:
                rows.append({"Name": it.get("Name"), "AlbumArtist": ", ".join(it.get("Artists") or []), "ProductionYear": it.get("ProductionYear") or "", "Id": it.get("Id")})
            dlg = QtWidgets.QDialog(self)
            dlg.setWindowTitle("Artist Albums")
            v = QtWidgets.QVBoxLayout(dlg)
            tbl = QtWidgets.QTableView()
            model2 = SimpleTableModel(["Name", "AlbumArtist", "ProductionYear", "Id"], rows)
            tbl.setModel(model2)
            tbl.setColumnHidden(3, True)
            def on_double(idx):
                row = idx.row()
                album_id = model2.rows[row].get("Id")
                if not album_id:
                    return
                # fetch album image if possible
                album_image = None
                try:
                    album_image = self.client.image_url_for_item(album_id, "Primary", 400)
                except Exception:
                    album_image = None
                dlg.accept()
                # Open album in the main Albums view (detail page)
                self._show_album_tracks(album_id, album_image)
            tbl.doubleClicked.connect(on_double)
            v.addWidget(tbl)
            btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close)
            btns.rejected.connect(dlg.reject)
            v.addWidget(btns)
            dlg.resize(800, 500)
            dlg.exec()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))

    def _open_album_from_dialog(self, model: SimpleTableModel, table: QtWidgets.QTableView, index: QtCore.QModelIndex, parent_dialog: QtWidgets.QDialog):
        row = index.row()
        album_id = model.rows[row].get("Id")
        if not album_id:
            return
        parent_dialog.accept()
        # Open the selected album's tracks
        self._show_album_tracks(album_id)

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
