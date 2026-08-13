from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt


class NotImplementedView(QtWidgets.QWidget):
    """Placeholder for not-yet-implemented library views."""

    def __init__(self, name: str = "Not implemented", parent=None):
        super().__init__(parent)
        v = QtWidgets.QVBoxLayout(self)

        title = QtWidgets.QLabel(f"{name}")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size:18px;font-weight:700;margin:8px;")

        message = QtWidgets.QLabel("This feature is not yet supported in Botify 😺")
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setStyleSheet("font-size:16px;margin:16px;")

        v.addStretch(1)
        v.addWidget(title)
        v.addWidget(message)
        v.addStretch(2)
