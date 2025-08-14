#!/usr/bin/env python3
"""
Botify (single-file)

Features
- Onboarding flow to enter server URL and login via Quick Connect
- Multithreaded network I/O via QThreadPool so UI stays responsive
- Lists all Audio tracks and plays on click using QMediaPlayer
- Settings dialog to change server and logout (clears token)
- Persists settings via QSettings (server, token, userId, deviceId)
- Bottom playback bar (cover art, seek, play/pause, stop, volume)
- Right-side preview panel with cover + details on selected track

Dependencies
- PyQt6
- requests

Tested with PyQt6 >= 6.4. If QtMultimedia isn't installed on your platform, install
`PyQt6-Qt6` / `PyQt6` wheels that include it. On Linux, you may need system codecs.

"""
from __future__ import annotations

import sys
import platform
import uuid
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
from requests import Response

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

APP_NAME = "Botify"
APP_VERSION = "0.1.0"
ORG_NAME = "Botify"
ORG_DOMAIN = "botify.local"

# -------------------------------
# Helper: Worker for threaded I/O
# -------------------------------
class WorkerSignals(QtCore.QObject):
    finished = QtCore.pyqtSignal(object)
    error = QtCore.pyqtSignal(Exception)


class Worker(QtCore.QRunnable):
    """Run a function in a background thread and emit result via signals."""

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @QtCore.pyqtSlot()
    def run(self):
        try:
            res = self.fn(*self.args, **self.kwargs)
        except Exception as e:
            self.signals.error.emit(e)
            return
        self.signals.finished.emit(res)


# -------------------------
# Jellyfin API simple client
# -------------------------
@dataclass
class AuthState:
    server: str
    device_id: str
    device_name: str
    token: Optional[str] = None
    user_id: Optional[str] = None


class JellyfinClient:
    def __init__(self, server: str, device_id: str, device_name: str):
        self.session = requests.Session()
        self.state = AuthState(server=self._clean_server(server), device_id=device_id, device_name=device_name)
        self.timeout = 15

    # ---- basic helpers ----
    def _clean_server(self, server: str) -> str:
        s = server.strip()
        if not s.startswith("http://") and not s.startswith("https://"):
            s = "http://" + s
        return s.rstrip("/")

    def _auth_header(self) -> str:
        parts = [
            f'Client="{APP_NAME}"',
            f'Device="{self.state.device_name}"',
            f'DeviceId="{self.state.device_id}"',
            f'Version="{APP_VERSION}"',
        ]
        if self.state.token:
            parts.append(f'Token="{self.state.token}"')
        return "MediaBrowser " + ", ".join(parts)

    def _headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": self._auth_header(),
        }

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Response:
        url = f"{self.state.server}{path}"
        return self.session.get(url, headers=self._headers(), params=params, timeout=self.timeout)

    def _post(self, path: str, data: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None) -> Response:
        url = f"{self.state.server}{path}"
        payload = json.dumps(data) if data is not None else None
        return self.session.post(url, headers=self._headers(), data=payload, params=params, timeout=self.timeout)

    # ---- Quick Connect flow ----
    def quickconnect_enabled(self) -> bool:
        r = self._get("/QuickConnect/Enabled")
        r.raise_for_status()
        return bool(r.json())

    def quickconnect_initiate(self) -> Dict[str, Any]:
        r = self._post("/QuickConnect/Initiate")
        r.raise_for_status()
        return r.json()  # { Code, Secret, Authenticated, ... }

    def quickconnect_state(self, secret: str) -> Dict[str, Any]:
        r = self._get("/QuickConnect/Connect", params={"secret": secret})
        if r.status_code == 404:
            return {"Authenticated": False, "Error": "Unknown quick connect secret"}
        r.raise_for_status()
        return r.json()

    def authenticate_with_quickconnect(self, secret: str) -> Dict[str, Any]:
        url = "/Users/AuthenticateWithQuickConnect"
        payload = {"Secret": secret}
        r = self._post(url, data=payload)
        r.raise_for_status()
        data = r.json()
        token = data.get("AccessToken") or data.get("AccessTokenString")
        user = data.get("User") or {}
        user_id = user.get("Id")
        if not token or not user_id:
            raise RuntimeError("Quick Connect authentication did not return token/user id")
        self.state.token = token
        self.state.user_id = user_id
        return data

    # ---- Library ----
    def list_all_tracks(self) -> List[Dict[str, Any]]:
        if not self.state.user_id:
            raise RuntimeError("Not authenticated")
        params = {
            "IncludeItemTypes": "Audio",
            "Recursive": True,
            "Fields": "Album,Artists,RunTimeTicks,ParentId",
            "SortBy": "SortName",
            "SortOrder": "Ascending"
        }
        r = self._get(f"/Users/{self.state.user_id}/Items", params=params)
        r.raise_for_status()
        return r.json().get("Items", [])

    def stream_url_for_track(self, item_id: str) -> str:
        token = self.state.token or ""
        return f"{self.state.server}/Audio/{item_id}/stream?static=true&api_key={token}"

    def image_url_for_item(self, item_id: str, kind: str = "Primary", max_side: int = 400) -> str:
        """Return a Jellyfin image URL for the item (Primary/Thumb/Backdrop)."""
        token = self.state.token or ""
        return f"{self.state.server}/Items/{item_id}/Images/{kind}?maxSide={max_side}&quality=90&api_key={token}"


# -------------------------
# UI Components
# -------------------------
class OnboardingWidget(QtWidgets.QWidget):
    """Stacked onboarding: server entry -> quick connect code + polling."""
    authenticated = QtCore.pyqtSignal(AuthState)

    def __init__(self, client_factory, settings: QtCore.QSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.client_factory = client_factory
        self.client: Optional[JellyfinClient] = None
        self.pool = QtCore.QThreadPool.globalInstance()
        self.secret: Optional[str] = None

        self.stack = QtWidgets.QStackedWidget()
        self._build_server_page()
        self._build_quickconnect_page()

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.stack)

        saved_server = self.settings.value("server", "")
        if saved_server:
            self.server_edit.setText(saved_server)

    def _build_server_page(self):
        page = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(page)

        title = QtWidgets.QLabel(f"Welcome to {APP_NAME}")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        title.setStyleSheet("font-size: 20px; font-weight: 600; margin: 8px 0;")

        form = QtWidgets.QFormLayout()
        self.server_edit = QtWidgets.QLineEdit()
        self.server_edit.setPlaceholderText("http(s)://your-jellyfin-server:8096")
        form.addRow("Server URL", self.server_edit)

        self.next_btn = QtWidgets.QPushButton("Continue →")
        self.next_btn.clicked.connect(self.start_quickconnect)

        v.addWidget(title)
        v.addLayout(form)
        v.addStretch(1)
        v.addWidget(self.next_btn)

        self.stack.addWidget(page)

    def _build_quickconnect_page(self):
        page = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(page)

        self.qc_title = QtWidgets.QLabel("Quick Connect")
        self.qc_title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.qc_title.setStyleSheet("font-size: 18px; font-weight: 600; margin: 8px 0;")

        self.code_label = QtWidgets.QLabel("...")
        self.code_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.code_label.setStyleSheet("font-size: 28px; font-weight: 700; letter-spacing: 2px; margin: 8px 0;")

        self.info_label = QtWidgets.QLabel(
            "Open a logged-in Jellyfin app → Settings → Quick Connect and enter the code above.\n"
            "We will automatically detect authorization."
        )
        self.info_label.setWordWrap(True)
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.back_btn = QtWidgets.QPushButton("← Back")
        self.back_btn.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        self.refresh_btn = QtWidgets.QPushButton("Get New Code")
        self.refresh_btn.clicked.connect(self.initiate_quickconnect)

        btnrow = QtWidgets.QHBoxLayout()
        btnrow.addWidget(self.back_btn)
        btnrow.addStretch(1)
        btnrow.addWidget(self.refresh_btn)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        v.addWidget(self.qc_title)
        v.addWidget(self.code_label)
        v.addWidget(self.info_label)
        v.addLayout(btnrow)
        v.addWidget(self.status_label)
        v.addStretch(1)

        self.stack.addWidget(page)

        self.poll_timer = QtCore.QTimer(self)
        self.poll_timer.setInterval(5000)
        self.poll_timer.timeout.connect(self.poll_quickconnect_state)

    def start_quickconnect(self):
        server = self.server_edit.text().strip()
        if not server:
            QtWidgets.QMessageBox.warning(self, "Server", "Please enter your Jellyfin server URL.")
            return
        self.client = self.client_factory(server)
        self.settings.setValue("server", self.client.state.server)
        self.stack.setCurrentIndex(1)
        self.initiate_quickconnect()

    def _run(self, fn, on_ok, on_err=None):
        worker = Worker(fn)
        worker.signals.finished.connect(on_ok)
        if on_err:
            worker.signals.error.connect(on_err)
        else:
            worker.signals.error.connect(lambda e: QtWidgets.QMessageBox.critical(self, "Error", str(e)))
        QtCore.QThreadPool.globalInstance().start(worker)

    def initiate_quickconnect(self):
        if not self.client:
            return
        self.status_label.setText("Requesting code…")

        def ok(data):
            self.secret = data.get("Secret")
            code = data.get("Code", "??????")
            self.code_label.setText(code)
            self.status_label.setText("Waiting for authorization… (polling)")
            self.poll_timer.start()

        self._run(lambda: self.client.quickconnect_initiate(), ok)

    def poll_quickconnect_state(self):
        if not self.client or not self.secret:
            return

        def ok(data):
            auth = bool(data.get("Authenticated"))
            if auth:
                self.poll_timer.stop()
                self._run(lambda: self.client.authenticate_with_quickconnect(self.secret), self._after_auth)
            else:
                self.status_label.setText("Still waiting for authorization…")

        self._run(lambda: self.client.quickconnect_state(self.secret), ok)

    def _after_auth(self, data):
        assert self.client is not None
        self.settings.setValue("token", self.client.state.token)
        self.settings.setValue("user_id", self.client.state.user_id)
        self.settings.setValue("device_id", self.client.state.device_id)
        self.authenticated.emit(self.client.state)


class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent, settings: QtCore.QSettings):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.settings = settings

        layout = QtWidgets.QVBoxLayout(self)

        form = QtWidgets.QFormLayout()
        self.server_edit = QtWidgets.QLineEdit(self.settings.value("server", ""))
        form.addRow("Server URL", self.server_edit)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        self.logout_btn = QtWidgets.QPushButton("Log out")
        self.logout_btn.setStyleSheet("QPushButton{background:#e74c3c;color:white;padding:6px;border-radius:6px}")
        self.logout_btn.clicked.connect(self.logout)

        layout.addLayout(form)
        layout.addWidget(self.logout_btn)
        layout.addStretch(1)
        layout.addWidget(btns)

    def accept(self):
        self.settings.setValue("server", self.server_edit.text().strip())
        super().accept()

    def logout(self):
        for key in ("token", "user_id"):
            self.settings.remove(key)
        QtWidgets.QMessageBox.information(self, "Logged out", "Session cleared. You will need to log in again.")
        self.accept()


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

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def itemId(self, row: int) -> Optional[str]:
        if 0 <= row < len(self.rows):
            return self.rows[row].get("Id")
        return None


# -------------------------
# Preview & Playback widgets
# -------------------------
class TrackPreview(QtWidgets.QWidget):
    """Right-side preview panel for the selected track."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QtCore.QThreadPool.globalInstance()
        self.cover_label = QtWidgets.QLabel("No track selected")
        self.cover_label.setFixedSize(220, 220)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setStyleSheet("background:#ddd;border:1px solid #bbb;border-radius:6px;")

        self.title_lbl = QtWidgets.QLabel("")
        self.title_lbl.setStyleSheet("font-weight:600;font-size:14px")
        self.meta_lbl = QtWidgets.QLabel("")
        self.meta_lbl.setWordWrap(True)
        self.meta_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        v = QtWidgets.QVBoxLayout(self)
        v.addWidget(self.cover_label)
        v.addSpacing(8)
        v.addWidget(self.title_lbl)
        v.addWidget(self.meta_lbl)
        v.addStretch(1)

    def _fetch_image_bytes(self, url: str) -> bytes:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.content

    def set_track(self, track: Dict[str, Any], image_url: Optional[str]):
        name = track.get("Name", "")
        album = track.get("Album", "")
        artists = ", ".join(track.get("Artists") or [])
        ticks = track.get("RunTimeTicks") or 0
        seconds = int(ticks / 10_000_000)
        m, s = divmod(seconds, 60)
        dur = f"{m}:{s:02d}"
        self.title_lbl.setText(name or "(untitled)")
        self.meta_lbl.setText(f"Album: {album}\nArtists: {artists}\nDuration: {dur}\nId: {track.get('Id','')}")

        # async image load
        if image_url:
            worker = Worker(self._fetch_image_bytes, image_url)

            def ok(data: bytes):
                pix = QtGui.QPixmap()
                if pix.loadFromData(data):
                    self.cover_label.setPixmap(
                        pix.scaled(220, 220, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    )
                else:
                    self.cover_label.setText("No Image")

            def err(e: Exception):
                self.cover_label.setText("No Image")

            worker.signals.finished.connect(ok)
            worker.signals.error.connect(err)
            self.pool.start(worker)
        else:
            self.cover_label.setText("No Image")


class PlaybackBar(QtWidgets.QWidget):
    """Bottom playback bar with cover, seek, controls, volume."""
    def __init__(self, player: QMediaPlayer, audio_output: QAudioOutput, parent=None):
        super().__init__(parent)
        self.pool = QtCore.QThreadPool.globalInstance()
        self.player = player
        self.audio_output = audio_output
        self.setObjectName("PlaybackBar")
        self.setStyleSheet("#PlaybackBar{border-top:1px solid #ddd;background:#fafafa;}")

        self.cover = QtWidgets.QLabel("♪")
        self.cover.setFixedSize(80, 80)
        self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover.setStyleSheet("background:#eee;border:1px solid #ddd;border-radius:6px;")

        self.title = QtWidgets.QLabel("")
        self.sub = QtWidgets.QLabel("")
        self.sub.setStyleSheet("color:#666;font-size:11px")

        self.play_btn = QtWidgets.QPushButton(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MediaPlay), "")
        self.play_btn.clicked.connect(self._toggle_play)

        self.stop_btn = QtWidgets.QPushButton(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MediaStop), "")
        self.stop_btn.clicked.connect(self.player.stop)

        self.seek = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.sliderPressed.connect(self._seek_pressed)
        self.seek.sliderReleased.connect(self._seek_released)
        self.seek.sliderMoved.connect(self._seek_moved)
        self._seeking = False

        self.time_lbl = QtWidgets.QLabel("0:00 / 0:00")

        self.vol_icon = QtWidgets.QLabel("🔊")
        self.vol = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(50)
        self.audio_output.setVolume(0.5)
        self.vol.valueChanged.connect(lambda v: self.audio_output.setVolume(v / 100.0))

        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.playbackStateChanged.connect(self._on_state)

        left = QtWidgets.QVBoxLayout()
        left.addWidget(self.title)
        left.addWidget(self.sub)

        mid = QtWidgets.QVBoxLayout()
        mid.addWidget(self.seek)
        mid.addWidget(self.time_lbl)

        right = QtWidgets.QHBoxLayout()
        right.addWidget(self.vol_icon)
        right.addWidget(self.vol)

        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(10)
        row.addWidget(self.cover)
        row.addLayout(left, 1)
        row.addWidget(self.play_btn)
        row.addWidget(self.stop_btn)
        row.addLayout(mid, 3)
        row.addStretch(1)
        row.addLayout(right, 1)

    # ----- public helpers
    def set_now_playing_meta(self, title: str, subtitle: str = ""):
        self.title.setText(title)
        self.sub.setText(subtitle)

    def set_cover_async(self, url: Optional[str]):
        if not url:
            self.cover.setText("♪")
            self.cover.setPixmap(QtGui.QPixmap())  # clear
            return

        def fetch(url_: str) -> bytes:
            r = requests.get(url_, timeout=10)
            r.raise_for_status()
            return r.content

        worker = Worker(fetch, url)

        def ok(data: bytes):
            pix = QtGui.QPixmap()
            if pix.loadFromData(data):
                self.cover.setPixmap(
                    pix.scaled(80, 80, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                )
            else:
                self.cover.setText("♪")

        def err(e: Exception):
            self.cover.setText("♪")

        worker.signals.finished.connect(ok)
        worker.signals.error.connect(err)
        self.pool.start(worker)

    # ----- internal slots
    def _toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _seek_pressed(self):
        self._seeking = True

    def _seek_released(self):
        self._seeking = False
        self.player.setPosition(self.seek.value())

    def _seek_moved(self, pos: int):
        # Update live time label while moving
        dur = max(self.player.duration(), 1)
        cur_m, cur_s = divmod(int(pos / 1000), 60)
        dur_m, dur_s = divmod(int(dur / 1000), 60)
        self.time_lbl.setText(f"{cur_m}:{cur_s:02d} / {dur_m}:{dur_s:02d}")

    def _on_position(self, position: int):
        if not self._seeking:
            self.seek.setValue(position)
            dur = max(self.player.duration(), 1)
            cur_m, cur_s = divmod(int(position / 1000), 60)
            dur_m, dur_s = divmod(int(dur / 1000), 60)
            self.time_lbl.setText(f"{cur_m}:{cur_s:02d} / {dur_m}:{dur_s:02d}")

    def _on_duration(self, duration: int):
        self.seek.setRange(0, max(duration, 0))

    def _on_state(self, state: QMediaPlayer.PlaybackState):
        icon = (
            QtWidgets.QStyle.StandardPixmap.SP_MediaPause
            if state == QMediaPlayer.PlaybackState.PlayingState
            else QtWidgets.QStyle.StandardPixmap.SP_MediaPlay
        )
        self.play_btn.setIcon(self.style().standardIcon(icon))


# -------------------------
# Main Window
# -------------------------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1100, 700)
        QtWidgets.QApplication.setOrganizationName(ORG_NAME)
        QtWidgets.QApplication.setOrganizationDomain(ORG_DOMAIN)
        QtWidgets.QApplication.setApplicationName(APP_NAME)
        QtWidgets.QApplication.setApplicationVersion(APP_VERSION)

        self.settings = QtCore.QSettings()
        self.pool = QtCore.QThreadPool.globalInstance()

        # Device identity
        self.device_id = self.settings.value("device_id") or str(uuid.uuid4())
        self.settings.setValue("device_id", self.device_id)
        self.device_name = platform.node() or "PyQt Device"

        # Player setup
        self.audio_output = QAudioOutput()
        self.player = QMediaPlayer()
        self.player.setAudioOutput(self.audio_output)

        # --- Toolbar
        tb = self.addToolBar("Main")
        act_settings = QtGui.QAction("Settings", self)
        act_settings.triggered.connect(self.open_settings)
        tb.addAction(act_settings)
        act_refresh = QtGui.QAction("Refresh", self)
        act_refresh.triggered.connect(self.load_tracks)
        tb.addAction(act_refresh)

        # --- Central Layout (Stack: Onboarding vs App; App = table + preview + playback bar)
        self.stack = QtWidgets.QStackedWidget()
        self.setCentralWidget(self.stack)

        # Onboarding view
        self.onboarding = OnboardingWidget(self._client_factory, self.settings)
        self.onboarding.authenticated.connect(self._on_authenticated)
        self.stack.addWidget(self.onboarding)  # idx 0

        # App view (table + preview + playback)
        self.app_container = QtWidgets.QWidget()
        app_v = QtWidgets.QVBoxLayout(self.app_container)
        app_v.setContentsMargins(6, 6, 6, 6)
        app_v.setSpacing(6)

        # Top split: table (left) + preview (right)
        top = QtWidgets.QWidget()
        top_h = QtWidgets.QHBoxLayout(top)
        top_h.setContentsMargins(0, 0, 0, 0)
        top_h.setSpacing(8)

        self.tracks_table = QtWidgets.QTableView()
        self.tracks_table.doubleClicked.connect(self._play_selected)
        self.tracks_table.clicked.connect(self._preview_selected)
        self.tracks_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.tracks_table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.tracks_table.verticalHeader().setVisible(False)
        self.tracks_table.setSortingEnabled(True)

        self.preview_panel = TrackPreview()

        top_h.addWidget(self.tracks_table, 3)
        top_h.addWidget(self.preview_panel, 2)

        # Bottom playback bar
        self.playback_bar = PlaybackBar(self.player, self.audio_output)

        app_v.addWidget(top, 1)
        app_v.addWidget(self.playback_bar, 0)
        self.stack.addWidget(self.app_container)  # idx 1

        # Restore session if possible
        if self.settings.value("token") and self.settings.value("user_id") and self.settings.value("server"):
            self.client = self._client_factory(self.settings.value("server"))
            self.client.state.token = self.settings.value("token")
            self.client.state.user_id = self.settings.value("user_id")
            self.stack.setCurrentIndex(1)
            QtCore.QTimer.singleShot(0, self.load_tracks)
        else:
            self.stack.setCurrentIndex(0)

    # ---- Client factory
    def _client_factory(self, server: str) -> JellyfinClient:
        return JellyfinClient(server, device_id=self.device_id, device_name=self.device_name)

    def _run(self, fn, on_ok, on_err=None):
        worker = Worker(fn)
        worker.signals.finished.connect(on_ok)
        if on_err:
            worker.signals.error.connect(on_err)
        else:
            worker.signals.error.connect(lambda e: QtWidgets.QMessageBox.critical(self, "Error", str(e)))
        self.pool.start(worker)

    # ---- After login
    def _on_authenticated(self, auth: AuthState):
        self.client = self._client_factory(auth.server)
        self.client.state = auth
        self.stack.setCurrentIndex(1)
        self.load_tracks()

    # ---- Settings
    def open_settings(self):
        dlg = SettingsDialog(self, self.settings)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            new_server = self.settings.value("server")
            if new_server:
                self.client = self._client_factory(new_server)
                token = self.settings.value("token")
                user_id = self.settings.value("user_id")
                if token and user_id:
                    self.client.state.token = token
                    self.client.state.user_id = user_id
                    self.load_tracks()
                else:
                    self.stack.setCurrentIndex(0)

    # ---- Load tracks
    def load_tracks(self):
        if not hasattr(self, 'client') or not self.client.state.token:
            QtWidgets.QMessageBox.information(self, "Login required", "Please log in via Quick Connect.")
            self.stack.setCurrentIndex(0)
            return

        def ok(items):
            print(f"Loaded {len(items)} tracks")
            model = TracksModel(items)
            self.tracks_table.setModel(model)
            self.tracks_table.setColumnHidden(4, True)  # hide id column
            self.tracks_table.resizeColumnsToContents()

        self._run(self.client.list_all_tracks, ok)

    # ---- Preview click
    def _preview_selected(self, index: QtCore.QModelIndex):
        model: TracksModel = self.tracks_table.model()  # type: ignore
        if not model:
            return
        row = index.row()
        track = model.rows[row]
        image_url = None
        if hasattr(self, "client") and track.get("Id"):
            image_url = self.client.image_url_for_item(track["Id"], "Primary", 600)
        self.preview_panel.set_track(track, image_url)

    # ---- Playback (double click)
    def _play_selected(self, index: QtCore.QModelIndex):
        model: TracksModel = self.tracks_table.model()  # type: ignore
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
        self.playback_bar.set_cover_async(self.client.image_url_for_item(item_id, "Primary", 400))
        self.player.play()


# -------------------------
# Entrypoint
# -------------------------
def main():
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
