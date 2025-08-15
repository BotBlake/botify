from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import QRect

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

    def _call_endpoint(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Fetches an image from the server and returns it as a QPixmap.
        Automatically detects image format from Content-Type header.
    
        :param crop_ratio: Optional tuple (width_ratio, height_ratio) for cropping.
            Example: (1, 1) for square, (16, 9) for widescreen.
            If None, returns the full image.
        """
        
        r = self._get(path, params=params)
        if not r.ok:
            return {"error": "Server not found"}
        r.raise_for_status()
        return r.json()

    def _get_image_pm(self, path: str, params: Optional[Dict[str, Any]] = None, crop_ratio: Optional[Tuple[int, int]] = None) -> QPixmap:
        """
        Fetches an image from the server and returns it as a QPixmap.
        Automatically detects image format from the Content-Type header.
        """
        url = f"{self.state.server}{path}"
        response = self.session.get(
            url,
            headers=self._headers(),
            params=params,
            timeout=self.timeout
        )
        response.raise_for_status()
        img_bytes = response.content

        # Detect image format
        content_type = response.headers.get("Content-Type", "").lower()
        if "png" in content_type:
            fmt = "PNG"
        elif "jpeg" in content_type or "jpg" in content_type:
            fmt = "JPG"
        elif "gif" in content_type:
            fmt = "GIF"
        elif "bmp" in content_type:
            fmt = "BMP"
        else:
            fmt = None  # Let QPixmap guess

        # Load into QPixmap
        pixmap = QPixmap()
        if not pixmap.loadFromData(img_bytes, fmt):
            raise ValueError(f"Failed to load image from {url}")

         # Crop to ratio if specified
        if crop_ratio:
            w_ratio, h_ratio = crop_ratio
            img = pixmap.toImage()

            orig_w, orig_h = img.width(), img.height()
            target_ratio = w_ratio / h_ratio
            current_ratio = orig_w / orig_h

            if current_ratio > target_ratio:
                # Image too wide → crop horizontally
                new_w = int(orig_h * target_ratio)
                x_offset = (orig_w - new_w) // 2
                crop_rect = QRect(x_offset, 0, new_w, orig_h)
            else:
                # Image too tall → crop vertically
                new_h = int(orig_w / target_ratio)
                y_offset = (orig_h - new_h) // 2
                crop_rect = QRect(0, y_offset, orig_w, new_h)

            cropped_img = img.copy(crop_rect)
            pixmap = QPixmap.fromImage(cropped_img)

        return pixmap

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
        token = data.get("AccessToken")
        user = data.get("User") or {}
        user_id = user.get("Id")
        if not token or not user_id:
            raise RuntimeError("Quick Connect authentication did not return token/user id")
        self.state.token = token
        self.state.user_id = user_id
        return data

    def authenticate_with_credentials(self, username: str, password: str) -> Dict[str, Any]:
        url = "/Users/AuthenticateByName"
        payload = {"Username": username, "Pw": password}
        r = self._post(url, data=payload)
        r.raise_for_status()
        data = r.json()
        token = data.get("AccessToken")
        user = data.get("User") or {}
        user_id = user.get("Id")
        if not token or not user_id:
            raise RuntimeError("Authentication did not return token/user id")
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
