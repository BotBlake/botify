from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Optional

from PyQt6 import QtCore, QtWidgets
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QPixmap

from . import image_loader


class GridItemWidget(QtWidgets.QWidget):
    """Reusable grid item used for albums and artists: icon + elided title + optional marquee."""

    def __init__(self, title: str, size: int = 150, parent=None):
        super().__init__(parent)
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)
        self.size = size
        self.icon_lbl = QtWidgets.QLabel()
        self.icon_lbl.setFixedSize(size, size)
        self.icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_lbl = QtWidgets.QLabel()
        self.title_lbl.setFixedWidth(size)
        self.title_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.title_lbl.setWordWrap(False)
        fm = self.title_lbl.fontMetrics()
        elided = fm.elidedText(title, Qt.TextElideMode.ElideRight, size)
        self.full_title = title
        self.title_lbl.setText(elided)
        v.addWidget(self.icon_lbl)
        v.addWidget(self.title_lbl)
        self._marquee_timer = QtCore.QTimer(self)
        self._marquee_timer.setInterval(250)
        self._marquee_index = 0
        self._marquee_enabled = False
        self._marquee_timer.timeout.connect(self._on_marquee)

    def set_pixmap(self, pix: QPixmap):
        if pix is None or pix.isNull():
            self.icon_lbl.setPixmap(QPixmap())
        else:
            self.icon_lbl.setPixmap(
                pix.scaled(
                    self.size,
                    self.size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def start_marquee(self):
        if len(self.full_title) <= 20:
            return
        self._marquee_enabled = True
        self._marquee_index = 0
        self._marquee_timer.start()

    def stop_marquee(self):
        self._marquee_timer.stop()
        self._marquee_enabled = False
        fm = self.title_lbl.fontMetrics()
        self.title_lbl.setText(
            fm.elidedText(self.full_title, Qt.TextElideMode.ElideRight, self.size)
        )

    def _on_marquee(self):
        if not self._marquee_enabled:
            return
        text = self.full_title + "   "
        n = len(text)
        i = self._marquee_index % n
        display = text[i : i + 30]
        self.title_lbl.setText(display)
        self._marquee_index += 1


class ItemGrid(QtWidgets.QListWidget):
    """Reusable, asynchronously populated grid for named media items."""

    item_selected = QtCore.pyqtSignal(object)

    def __init__(self, image_size: int = 150, parent=None):
        super().__init__(parent)
        self.image_size = image_size
        self._marquee_widget: Optional[GridItemWidget] = None
        self.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
        self.setIconSize(QSize(image_size, image_size))
        self.setGridSize(QSize(image_size + 20, image_size + 60))
        self.setResizeMode(QtWidgets.QListView.ResizeMode.Adjust)
        self.setSpacing(12)
        self.itemClicked.connect(self._item_clicked)

    def set_items(
        self,
        items: Sequence[Mapping[str, Any]],
        cover_urls: Mapping[str, Sequence[str]],
    ) -> None:
        self.stop_marquee()
        self.clear()
        placeholder = image_loader.placeholder(self.image_size)
        for item in items:
            self._add_item(item, cover_urls.get(item.get("Id") or "", ()), placeholder)

    def stop_marquee(self) -> None:
        if self._marquee_widget:
            self._marquee_widget.stop_marquee()
            self._marquee_widget = None

    def _add_item(
        self,
        item: Mapping[str, Any],
        urls: Sequence[str],
        placeholder: QPixmap,
    ) -> None:
        list_item = QtWidgets.QListWidgetItem()
        list_item.setData(Qt.ItemDataRole.UserRole, dict(item))
        widget = GridItemWidget(item.get("Name") or "(untitled)", self.image_size)
        widget.set_pixmap(placeholder)
        self.addItem(list_item)
        self.setItemWidget(list_item, widget)
        list_item.setSizeHint(widget.sizeHint())
        if not urls:
            return

        def loaded(pixmap: QPixmap) -> None:
            current_widget = self.itemWidget(list_item)
            if isinstance(current_widget, GridItemWidget):
                current_widget.set_pixmap(pixmap)

        image_loader.load_first(urls, loaded, lambda _error: None)

    def _item_clicked(self, item: QtWidgets.QListWidgetItem) -> None:
        self.stop_marquee()
        widget = self.itemWidget(item)
        if isinstance(widget, GridItemWidget):
            widget.start_marquee()
            self._marquee_widget = widget
        value = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(value, dict):
            self.item_selected.emit(value)
