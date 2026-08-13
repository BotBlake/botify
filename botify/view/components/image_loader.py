from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Optional

import requests
from PyQt6 import QtCore
from PyQt6.QtGui import QColor, QPixmap

from botify.model.threads import Worker


def _fetch_first_pixmap(urls: tuple[str, ...]) -> QPixmap:
    last_error: Optional[Exception] = None
    for url in urls:
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            pixmap = QPixmap()
            if pixmap.loadFromData(response.content) and not pixmap.isNull():
                return pixmap
            last_error = ValueError(f"Unable to decode image from {url}")
        except Exception as error:
            last_error = error
    if last_error:
        raise last_error
    raise ValueError("No image URLs supplied")


def load_first(
    urls: Iterable[str],
    on_ok: Callable[[QPixmap], None],
    on_err: Optional[Callable[[Exception], None]] = None,
) -> None:
    candidates = tuple(dict.fromkeys(url for url in urls if url))
    if not candidates:
        if on_err:
            on_err(ValueError("No image URLs supplied"))
        return
    worker = Worker(_fetch_first_pixmap, candidates)
    worker.signals.finished.connect(on_ok)
    worker.signals.error.connect(
        on_err or (lambda error: print("Image load error:", error))
    )
    QtCore.QThreadPool.globalInstance().start(worker)


def load(
    url: str,
    on_ok: Callable[[QPixmap], None],
    on_err: Optional[Callable[[Exception], None]] = None,
) -> None:
    load_first((url,), on_ok, on_err)


def placeholder(
    size: int = 150, color: Optional[tuple[int, int, int]] = None
) -> QPixmap:
    background = QColor(*(color or (60, 60, 60)))
    pixmap = QPixmap(size, size)
    pixmap.fill(background)
    return pixmap
