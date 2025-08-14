from __future__ import annotations

import sys
import uuid
import platform

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

from botify.model.model import TracksModel, APP_NAME, APP_VERSION, ORG_NAME, ORG_DOMAIN, Worker
from botify.model.jellyfin_apiclient import JellyfinClient 
from botify.view.view import OnboardingWidget, SettingsDialog, TrackPreview, PlaybackBar


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
    def _on_authenticated(self, auth: object):
        # auth is an AuthState
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
            model_ = TracksModel(items)
            self.tracks_table.setModel(model_)
            self.tracks_table.setColumnHidden(4, True)  # hide id column
            self.tracks_table.resizeColumnsToContents()

        self._run(self.client.list_all_tracks, ok)

    # ---- Preview click
    def _preview_selected(self, index: QtCore.QModelIndex):
        model_: TracksModel = self.tracks_table.model()  # type: ignore
        if not model_:
            return
        row = index.row()
        track = model_.rows[row]
        image_url = None
        if hasattr(self, "client") and track.get("Id"):
            image_url = self.client.image_url_for_item(track["Id"], "Primary", 600)
        self.preview_panel.set_track(track, image_url)

    # ---- Playback (double click)
    def _play_selected(self, index: QtCore.QModelIndex):
        model_: TracksModel = self.tracks_table.model()  # type: ignore
        if not model_:
            return
        row = index.row()
        track = model_.rows[row]
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
