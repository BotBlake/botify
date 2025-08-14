from __future__ import annotations

import uuid
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
from requests import Response

from PyQt6 import QtCore
from PyQt6.QtCore import Qt

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
# Tracks (QAbstractTableModel)
# -------------------------
from PyQt6 import QtCore


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