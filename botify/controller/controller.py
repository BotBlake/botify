from __future__ import annotations

import sys
import uuid
import platform

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

from botify.model.constants import APP_NAME, APP_VERSION, ORG_NAME, ORG_DOMAIN
from botify.model.threads import Worker
from botify.model.jellyfin_apiclient import JellyfinClient
from botify.view.components import PlaybackBar
from botify.view.view import (
    OnboardingWidget,
    SettingsDialog,
    LibraryBrowser,
)


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
        act_refresh.triggered.connect(self.load_library_browser)
        tb.addAction(act_refresh)

        # --- Central layout (onboarding or library content with playback controls)
        self.stack = QtWidgets.QStackedWidget()
        self.setCentralWidget(self.stack)

        # Onboarding view
        self.onboarding = OnboardingWidget(
            self._client_factory, self.settings, parent=self
        )
        self.onboarding.authenticated.connect(self._on_authenticated)
        self.stack.addWidget(self.onboarding)  # idx 0

        # App view
        self.app_container = QtWidgets.QWidget()
        app_v = QtWidgets.QVBoxLayout(self.app_container)
        app_v.setContentsMargins(6, 6, 6, 6)
        app_v.setSpacing(6)

        # Top area: library landing page or selected library content
        self.top_stack = QtWidgets.QStackedWidget()

        self.top_stack.addWidget(QtWidgets.QLabel("Loading…"))
        self.top_stack.addWidget(QtWidgets.QLabel("Select a library"))

        # Bottom playback bar
        self.playback_bar = PlaybackBar(self.player, self.audio_output)

        app_v.addWidget(self.top_stack, 1)
        app_v.addWidget(self.playback_bar, 0)
        self.stack.addWidget(self.app_container)  # idx 1

        # Restore session if possible
        if (
            self.settings.value("token")
            and self.settings.value("user_id")
            and self.settings.value("server")
        ):
            self.client = self._client_factory(self.settings.value("server"))
            self.client.state.token = self.settings.value("token")
            self.client.state.user_id = self.settings.value("user_id")
            self.stack.setCurrentIndex(1)
            QtCore.QTimer.singleShot(0, self.load_library_browser)
        else:
            self.stack.setCurrentIndex(0)

    # ---- Client factory
    def _client_factory(self, server: str) -> JellyfinClient:
        return JellyfinClient(
            server, device_id=self.device_id, device_name=self.device_name
        )

    def _run(self, fn, on_ok, on_err=None):
        worker = Worker(fn)
        worker.signals.finished.connect(on_ok)
        if on_err:
            worker.signals.error.connect(on_err)
        else:
            worker.signals.error.connect(
                lambda e: QtWidgets.QMessageBox.critical(self, "Error", str(e))
            )
        self.pool.start(worker)

    def load_login_screen_async(self, on_ok, on_err=None):
        """Call _load_login_screen in a background worker and invoke on_ok with the result.

        on_ok will be called with a single argument: (splash_pixmap, user_list)
        """
        self._run(self._load_login_screen, on_ok, on_err)

    # ---- Load Login Screen
    def _load_login_screen(self):
        self.client = self._client_factory(server=self.settings.value("server"))
        public_users = self.client._call_endpoint("/Users/Public")
        user_list = []
        for user in public_users:
            image_pm = None
            if "PrimaryImageTag" in user:
                image_pm = self.client._get_image_pm(
                    "/UserImage", params={"userId": user["Id"]}, crop_ratio=(1, 1)
                )
            user_list.append(
                {
                    "username": user.get("Name"),
                    "uid": user.get("Id"),
                    "profilepicture": image_pm,
                }
            )
        splash_screen_pm = self.client._get_image_pm("/Branding/SplashScreen")
        return splash_screen_pm, user_list

    # ---- After login
    def _on_authenticated(self, auth: object):
        # auth is an AuthState
        self.client = self._client_factory(auth.server)
        self.client.state = auth
        self.stack.setCurrentIndex(1)
        self.load_library_browser()

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
                    self.load_library_browser()
                else:
                    self.stack.setCurrentIndex(0)

    def load_library_browser(self):
        """Load the landing page showing available libraries (/UserViews)."""
        if not hasattr(self, "client") or not self.client.state.token:
            QtWidgets.QMessageBox.information(
                self, "Login required", "Please log in via Quick Connect."
            )
            self.stack.setCurrentIndex(0)
            return

        def ok(views):
            # views is a list of BaseItemDto-like dicts
            browser = LibraryBrowser(views, self.client, parent=self)
            browser.library_selected.connect(self.open_library)

            self._replace_top_page(0, browser)

        self._run(self.client.list_user_views, ok)

    def open_library(self, library_item: dict):
        """Open the view appropriate for a selected library."""
        coll_type = (library_item.get("CollectionType") or "").lower()

        if coll_type == "music":
            self.open_music_library(library_item)
            return

        # Unsupported — show friendly placeholder in the content area
        # Use a more extensible not-implemented view from the libraries package
        from botify.view.libraries.not_implemented import NotImplementedView

        page = NotImplementedView(library_item.get("Name", ""), parent=self)
        self._set_music_controller(None)
        self._replace_top_page(1, page)

    def open_music_library(self, library_item: dict):
        """Create the music controller and display its view."""
        if not hasattr(self, "client") or not self.client.state.token:
            QtWidgets.QMessageBox.information(
                self, "Login required", "Please log in via Quick Connect."
            )
            self.stack.setCurrentIndex(0)
            return

        lib_id = library_item.get("Id")
        if not lib_id:
            QtWidgets.QMessageBox.warning(
                self, "Library", "Selected library has no Id."
            )
            return

        from botify.controller.music import MusicLibraryController

        music_controller = MusicLibraryController(
            library_item=library_item,
            client=self.client,
            player=self.player,
            playback_bar=self.playback_bar,
            run=self._run,
            parent=self,
        )
        self._replace_top_page(1, music_controller.view)
        self._set_music_controller(music_controller)

    def _set_music_controller(self, controller) -> None:
        previous = getattr(self, "music_controller", None)
        if previous is not None and previous is not controller:
            previous.deleteLater()
        self.music_controller = controller

    def _replace_top_page(self, index: int, page: QtWidgets.QWidget) -> None:
        old = self.top_stack.widget(index)
        self.top_stack.removeWidget(old)
        old.deleteLater()
        self.top_stack.insertWidget(index, page)
        self.top_stack.setCurrentIndex(index)


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
