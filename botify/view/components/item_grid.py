
from PyQt6 import QtCore, QtWidgets
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap

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
            self.icon_lbl.setPixmap(pix.scaled(self.size, self.size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def start_marquee(self):
        if len(self.full_title) <= 20:
            return
        self._marquee_enabled = True
        self._marquee_index = 0
        self._marquee_timer.start()

    def stop_marquee(self):
        self._marquee_timer.stop()
        fm = self.title_lbl.fontMetrics()
        self.title_lbl.setText(fm.elidedText(self.full_title, Qt.TextElideMode.ElideRight, self.size))

    def _on_marquee(self):
        if not self._marquee_enabled:
            return
        text = self.full_title + "   "
        n = len(text)
        i = self._marquee_index % n
        display = text[i: i + 30]
        self.title_lbl.setText(display)
        self._marquee_index += 1
