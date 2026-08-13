"""Reusable carousel components.

Provides RotatingCarousel and LibraryCarousel UI widgets.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional
import math

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap, QPainter, QColor, QPainterPath, QPalette
from PyQt6.QtWidgets import QWidget


class RotatingCarousel(QWidget):
    """Circular rotating carousel of pixmaps.

    accounts: list of dicts with keys 'profilepicture' (QPixmap) and optional 'username'.
    username_callback: optional callback called when the center item changes.
    """

    def __init__(
        self,
        accounts: List[Dict[str, Any]],
        username_callback: Optional[Callable[[str], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.accounts = accounts
        self.username_callback = username_callback

        self.pixmaps: List[QPixmap] = []
        for acc in accounts:
            pm = acc.get("profilepicture")
            if pm is None:
                pm = QPixmap(100, 100)
                pm.fill(QColor("gray"))
            self.pixmaps.append(pm)

        self.angle_offset = 0.0
        self.target_offset = 0.0
        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self.animate_step)
        self.animation_timer.setInterval(16)

        self.setMinimumHeight(200)
        self.setMinimumWidth(300)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._spacing_angle = 2 * math.pi / max(len(self.accounts), 1)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if event.angleDelta().y() > 0:
            self.rotate(-1)
        else:
            self.rotate(1)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        clicked = self.get_clicked_index(event.pos().x(), event.pos().y())
        if clicked is None:
            return
        center = self.get_center_index()
        if clicked == (center - 1) % len(self.accounts):
            self.rotate(-1)
        elif clicked == (center + 1) % len(self.accounts):
            self.rotate(1)
        elif clicked != center:
            diff = (clicked - center) % len(self.accounts)
            if diff > len(self.accounts) / 2:
                diff -= len(self.accounts)
            self.rotate(diff)

    def get_center_index(self) -> int:
        return int(round(-self.angle_offset / self._spacing_angle)) % max(
            len(self.accounts), 1
        )

    def get_clicked_index(self, mx: float, my: float) -> Optional[int]:
        for idx, (x, y, size) in enumerate(self.get_positions()):
            if (mx - x) ** 2 + (my - y) ** 2 <= (size / 2) ** 2:
                return idx
        return None

    def rotate(self, steps: int) -> None:
        self.target_offset += -steps * self._spacing_angle
        if not self.animation_timer.isActive():
            self.animation_timer.start()

    def animate_step(self) -> None:
        speed = 0.15
        diff = self.target_offset - self.angle_offset
        if abs(diff) < 0.001:
            self.angle_offset = self.target_offset
            self.animation_timer.stop()
            if self.username_callback:
                idx = self.get_center_index()
                name = (
                    self.accounts[idx].get("username")
                    if idx < len(self.accounts)
                    else ""
                )
                self.username_callback(name)
        else:
            self.angle_offset += diff * speed
        self.update()

    def get_positions(self) -> List[tuple[float, float, float]]:
        w = self.width()
        h = self.height()
        cx = w / 2
        cy = h / 2
        radius_x = min(250, w / 2.5)
        radius_y = min(60, h / 6)
        base_size = 60

        order: List[tuple[float, float, float]] = []
        for i, _ in enumerate(self.accounts):
            angle = i * self._spacing_angle + self.angle_offset
            x = cx + math.sin(angle) * radius_x
            y = cy + math.cos(angle) * radius_y
            depth_scale = 1.0 - 0.3 * (1 - math.cos(angle))
            size = base_size * depth_scale + 40 * depth_scale
            order.append((x, y, size))
        return order

    def _masked_pixmap(
        self, pixmap: QPixmap, shape: str = "ellipse", radius: int = 8
    ) -> QPixmap:
        """Return a masked pixmap according to the requested shape.

        shape: 'ellipse' or 'rounded'
        radius: corner radius for rounded rect
        """
        mask = QPixmap(pixmap.size())
        mask.fill(Qt.GlobalColor.transparent)
        mask_painter = QPainter(mask)
        mask_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        if shape == "ellipse":
            path.addEllipse(0, 0, pixmap.width(), pixmap.height())
        else:
            path.addRoundedRect(0, 0, pixmap.width(), pixmap.height(), radius, radius)
        mask_painter.setClipPath(path)
        mask_painter.drawPixmap(0, 0, pixmap)
        mask_painter.end()
        return mask

    def _draw_item(
        self, painter: QPainter, idx: int, x: float, y: float, size: float
    ) -> None:
        """Default item drawing: circular masked pixmap centered at x,y."""
        pix = self.pixmaps[idx].scaled(
            int(size),
            int(size),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        masked = self._masked_pixmap(pix, shape="ellipse")
        painter.drawPixmap(int(x - size / 2), int(y - size / 2), masked)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        """Paint carousel items from back to front according to their depth."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        positions = self.get_positions()
        order_with_idx = sorted(enumerate(positions), key=lambda item: item[1][1])
        for idx, (x, y, size) in order_with_idx:
            self._draw_item(painter, idx, x, y, size)


class LibraryCarousel(RotatingCarousel):
    """Carousel that renders rounded-rectangle library tiles.

    The center item is emphasized and clicking it triggers select_callback with
    the original item dict.
    """

    def __init__(
        self,
        items: List[Dict[str, Any]],
        center_changed_callback: Optional[Callable[[str], None]] = None,
        select_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        accounts = [
            {
                "username": it.get("Name"),
                "profilepicture": it.get("pixmap")
                if it.get("pixmap") is not None
                else QPixmap(100, 100),
            }
            for it in items
        ]
        super().__init__(
            accounts, username_callback=center_changed_callback, parent=parent
        )
        self.items = items
        self.select_callback = select_callback

    def set_pixmap_at(self, index: int, pixmap: QPixmap) -> None:
        if 0 <= index < len(self.pixmaps):
            self.pixmaps[index] = pixmap
            self.update()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        clicked = self.get_clicked_index(event.pos().x(), event.pos().y())
        if clicked is None:
            return
        center = self.get_center_index()
        if clicked == center:
            if self.select_callback:
                self.select_callback(self.items[center])
            return
        super().mousePressEvent(event)

    def _draw_item(
        self, painter: QPainter, idx: int, x: float, y: float, size: float
    ) -> None:
        """Draw a rounded-rect tile for the library at position x,y with width ~1.6*size."""
        w = int(size * 1.6)
        h = int(size)
        rect_x = int(x - w / 2)
        rect_y = int(y - h / 2)
        radius = 12 if idx == self.get_center_index() else 8
        pixmap = self.pixmaps[idx].scaled(
            w,
            h,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        masked = self._masked_pixmap(pixmap, shape="rounded", radius=radius)
        painter.drawPixmap(rect_x, rect_y, masked)
        if idx == self.get_center_index():
            title = self.items[idx].get("Name", "")
            text_color = self.palette().color(QPalette.ColorRole.WindowText)
            painter.setPen(text_color)
            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(title)
            painter.drawText(int(x - tw / 2), rect_y + h + 20, title)
