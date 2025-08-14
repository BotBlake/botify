# view.py
from __future__ import annotations

import platform
import requests
from typing import Any, Dict, Optional

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

# import app constants and Worker from model
from model import APP_NAME, Worker


# -------------------------
# UI Components
# -------------------------
class OnboardingWidget(QtWidgets.QWidget):
    """Stacked onboarding: server entry -> quick connect code + polling."""
    authenticated = QtCore.pyqtSignal(object)

    def __init__(self, client_factory, settings: QtCore.QSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.client_factory = client_factory
        self.client = None
        self.pool = QtCore.QThreadPool.globalInstance()
        self.secret = None

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
