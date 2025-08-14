from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
from requests import Response

APP_NAME = "Botify"
APP_VERSION = "0.1.0"

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

    def quickconnect_enabled(self) -> bool:
        r = self._get("/QuickConnect/Enabled")
        r.raise_for_status()
        return bool(r.json())

    def quickconnect_initiate(self) -> Dict[str, Any]:
        r = self._post("/QuickConnect/Initiate")
        r.raise_for_status()
        return r.json()

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
        token = self.state.token or ""
        return f"{self.state.server}/Items/{item_id}/Images/{kind}?maxSide={max_side}&quality=90&api_key={token}"
