# view.py
from __future__ import annotations

from typing import Any, Dict, List

from PyQt6 import QtCore, QtWidgets
from PyQt6.QtCore import Qt

# import app constants and Worker from model
from botify.model.constants import APP_NAME
from botify.view.components import PlaybackBar as PlaybackBar
from botify.view.components import TrackPreview as TrackPreview
from botify.view.onboarding import LoginScreen


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
        self.parent = parent

        self.stack = QtWidgets.QStackedWidget()
        self._build_server_page()
        # self._build_quickconnect_page()

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
        self.next_btn.clicked.connect(self.open_login)

        v.addWidget(title)
        v.addLayout(form)
        v.addStretch(1)
        v.addWidget(self.next_btn)

        self.stack.addWidget(page)

    def open_login(self):
        def user_login(username: str, password: str):
            if not self.client:
                QtWidgets.QMessageBox.warning(
                    self, "Client Error", "No client initialized."
                )
                return
            try:
                data = self.client.authenticate_with_credentials(username, password)
                self._after_auth(data)
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Authentication Error", str(e))
                return

        self.client = self.client_factory(self.server_edit.text().strip())
        self.settings.setValue("server", self.client.state.server)

        # Show a lightweight loading placeholder while assets are fetched
        loading_page = QtWidgets.QWidget()
        lv = QtWidgets.QVBoxLayout(loading_page)
        loading_lbl = QtWidgets.QLabel("Loading login screen…")
        loading_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lv.addStretch(1)
        lv.addWidget(loading_lbl)
        lv.addStretch(1)
        self.stack.addWidget(loading_page)
        self.stack.setCurrentWidget(loading_page)

        # When the main window has loaded splash/users it will call back with the data
        def on_loaded(result):
            try:
                background_pixmap, user_list = result
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Load Error", str(e))
                self.stack.setCurrentIndex(0)
                return

            page = QtWidgets.QWidget()
            v = QtWidgets.QVBoxLayout(page)
            login_screen = LoginScreen(
                background_pixmap=background_pixmap,
                users=user_list,
                show_quickconnect=True,
                continue_callback=user_login,
                parent=self,
            )
            v.addWidget(login_screen)

            # Replace loading page with real page in the same stack position
            idx = self.stack.indexOf(loading_page)
            if idx != -1:
                self.stack.removeWidget(loading_page)
                self.stack.insertWidget(idx, page)
                self.stack.setCurrentIndex(idx)
            else:
                self.stack.addWidget(page)
                self.stack.setCurrentWidget(page)

        # ask the main window to load the login screen assets asynchronously
        self.parent.load_login_screen_async(on_loaded)

    def start_quickconnect(self):
        server = self.server_edit.text().strip()
        if not server:
            QtWidgets.QMessageBox.warning(
                self, "Server", "Please enter your Jellyfin server URL."
            )
            return
        self.client = self.client_factory(server)
        self.settings.setValue("server", self.client.state.server)
        self.stack.setCurrentIndex(1)
        self.initiate_quickconnect()

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
                self._run(
                    lambda: self.client.authenticate_with_quickconnect(self.secret),
                    self._after_auth,
                )
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
            QtWidgets.QDialogButtonBox.StandardButton.Save
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        self.logout_btn = QtWidgets.QPushButton("Log out")
        self.logout_btn.setStyleSheet(
            "QPushButton{background:#e74c3c;color:white;padding:6px;border-radius:6px}"
        )
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
        QtWidgets.QMessageBox.information(
            self, "Logged out", "Session cleared. You will need to log in again."
        )
        self.accept()


# -------------------------
# Library Browser
# -------------------------
class LibraryBrowser(QtWidgets.QWidget):
    """Landing page showing available libraries (UserViews) in a horizontal row.

    Emits library_selected with the BaseItemDto (dict) when a library is clicked.
    Layout includes left/right arrows and a large clear space below as in the mock.
    """

    library_selected = QtCore.pyqtSignal(object)

    def __init__(self, views: List[Dict[str, Any]], client, parent=None):
        super().__init__(parent)
        self.views = views
        self.client = client

        layout = QtWidgets.QVBoxLayout(self)
        title = QtWidgets.QLabel("Your Libraries")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size:20px;font-weight:600;margin:8px 0;")
        layout.addWidget(title)

        # Row with arrows and carousel in the middle
        row = QtWidgets.QHBoxLayout()
        left_btn = QtWidgets.QPushButton("←")
        left_btn.setFixedWidth(48)
        left_btn.setFlat(True)
        right_btn = QtWidgets.QPushButton("→")
        right_btn.setFixedWidth(48)
        right_btn.setFlat(True)

        # Use the LibraryCarousel implemented in onboarding.py
        from botify.view.components.carousel import LibraryCarousel
        from botify.view.components import image_loader

        # Prepare items list for carousel; carousel will draw center title itself
        # Pass the full BaseItemDto dicts to the carousel so selection keeps all fields
        items = [it for it in self.views]

        carousel = LibraryCarousel(
            items,
            center_changed_callback=None,
            select_callback=lambda itm: self.library_selected.emit(itm),
            parent=self,
        )
        carousel.setMinimumHeight(220)

        # Asynchronously load images into the carousel pixmaps
        for idx, it in enumerate(self.views):
            vid = it.get("Id")
            if not vid:
                continue
            try:
                url = self.client.image_url_for_item(vid, "Primary", 300)
            except Exception:
                url = None
            if not url:
                continue

            def make_ok(i):
                def _ok(pix):
                    carousel.set_pixmap_at(i, pix)

                return _ok

            def make_err(i):
                def _err(e):
                    # ignore errors — carousel will show placeholder
                    pass

                return _err

            image_loader.load(url, make_ok(idx), make_err(idx))

        # Arrow behaviour: rotate carousel left/right
        left_btn.clicked.connect(lambda: carousel.rotate(-1))
        right_btn.clicked.connect(lambda: carousel.rotate(1))

        row.addWidget(left_btn)
        row.addWidget(carousel, 1)
        row.addWidget(right_btn)

        layout.addLayout(row)

        # Make sure the carousel and tiles are transparent and don't show borders
        carousel.setStyleSheet("background:transparent;border:none;")
        left_btn.setStyleSheet("background:transparent;border:none;font-size:18px;")
        right_btn.setStyleSheet("background:transparent;border:none;font-size:18px;")

        # Below: large clear area with placeholder text (as per mock)
        spacer = QtWidgets.QWidget()
        vsp = QtWidgets.QVBoxLayout(spacer)
        lbl_main = QtWidgets.QLabel("This space stays\nclear for now")
        lbl_main.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_main.setStyleSheet("font-size:18px;font-weight:600;margin:20px;")
        lbl_sub = QtWidgets.QLabel("Lorem\nIpsum")
        lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_sub.setStyleSheet("font-size:14px;margin-top:20px;")
        vsp.addStretch(1)
        vsp.addWidget(lbl_main)
        vsp.addWidget(lbl_sub)
        vsp.addStretch(2)
        layout.addWidget(spacer, 1)


class UnsupportedLibraryView(QtWidgets.QWidget):
    """Simple placeholder for unsupported library types."""

    def __init__(self, collection_name: str = "This feature", parent=None):
        super().__init__(parent)
        v = QtWidgets.QVBoxLayout(self)
        lbl = QtWidgets.QLabel("This feature is not yet supported in Botify 😺")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("font-size:18px;font-weight:600;margin:20px;")
        v.addStretch(1)
        v.addWidget(lbl)
        v.addStretch(2)
