from __future__ import annotations

from typing import Optional, Callable
import requests
from PyQt6 import QtCore
from PyQt6.QtGui import QPixmap

from .threads import Worker


def _fetch_pixmap(url: str) -> QPixmap:
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    pix = QPixmap()
    if not pix.loadFromData(r.content):
        # return an empty pixmap to indicate failure
        return QPixmap()
    return pix


def load(url: str, on_ok: Callable[[QPixmap], None], on_err: Optional[Callable[[Exception], None]] = None):
    """Load an image from URL in a background thread and call on_ok(pixmap) on the main thread.

    on_err(exception) will be called if the fetch fails.
    """
    worker = Worker(_fetch_pixmap, url)
    worker.signals.finished.connect(on_ok)
    if on_err:
        worker.signals.error.connect(on_err)
    else:
        # default error handler: print to stderr
        worker.signals.error.connect(lambda e: print("Image load error:", e))
    QtCore.QThreadPool.globalInstance().start(worker)
