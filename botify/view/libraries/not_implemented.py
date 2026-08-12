from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt


class NotImplementedView(QtWidgets.QWidget):
    """Extensible placeholder for not-yet-implemented library views.

    Provides a central area to add buttons, links, or actions later.
    """

    def __init__(self, name: str = "Not implemented", parent=None):
        super().__init__(parent)
        self.name = name
        v = QtWidgets.QVBoxLayout(self)

        title = QtWidgets.QLabel(f"{name}")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size:18px;font-weight:700;margin:8px;")

        message = QtWidgets.QLabel("This feature is not yet supported in Botify 😺")
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setStyleSheet("font-size:16px;margin:16px;")

        # Action area where additional buttons can be added later
        self.actions_container = QtWidgets.QWidget()
        actions_layout = QtWidgets.QHBoxLayout(self.actions_container)
        actions_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        v.addStretch(1)
        v.addWidget(title)
        v.addWidget(message)
        v.addStretch(2)
