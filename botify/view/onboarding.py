from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, QTimer, QSize, QPropertyAnimation, QEasingCurve, pyqtProperty, QThreadPool
from PyQt6.QtGui import QPixmap, QPainter, QColor, QPainterPath, QPen, QBrush, QIcon, QFont, QPalette, QLinearGradient
from PyQt6.QtWidgets import QWidget, QLineEdit, QHBoxLayout, QVBoxLayout, QPushButton, QSizePolicy, QGraphicsDropShadowEffect, QLabel, QFrame
import math
from botify.model.model import Worker

class RotatingCarousel(QWidget):
    def __init__(self, accounts, username_callback=None, parent=None):
        """
        accounts: list of dicts -> {username, userid, profilepicture}
        username_callback: function(username) to call when center profile changes
        """
        super().__init__(parent)
        self.accounts = accounts
        self.username_callback = username_callback

        # Load images
        self.pixmaps = []
        for acc in accounts:
            pm = acc["profilepicture"]
            if pm is None:
                pm = QPixmap(100, 100)
                pm.fill(QColor("gray"))
            
            self.pixmaps.append(pm)

        # Rotation & animation
        self.angle_offset = 0.0
        self.target_offset = 0.0
        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self.animate_step)
        self.animation_timer.setInterval(16)  # ~60 FPS

        self.setMinimumHeight(240)   # was 200
        self.setMinimumWidth(400)    # was 200
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Dynamic spacing
        self.spacing_angle = 2 * math.pi / len(self.accounts)

        # Track center shrink state
        self.shrink_center = False

    def wheelEvent(self, event):
        if event.angleDelta().y() > 0:
            self.rotate(-1)
        else:
            self.rotate(1)

    def mousePressEvent(self, event):
        clicked_idx = self.get_clicked_index(event.pos().x(), event.pos().y())
        if clicked_idx is None:
            return
        center_idx = self.get_center_index()

        if clicked_idx == (center_idx - 1) % len(self.accounts):
            # Left profile clicked → rotate left
            self.rotate(-1)
        elif clicked_idx == (center_idx + 1) % len(self.accounts):
            # Right profile clicked → rotate right
            self.rotate(1)
        elif clicked_idx != center_idx:
            # Other profile → rotate shortest path
            diff = (clicked_idx - center_idx) % len(self.accounts)
            if diff > len(self.accounts) / 2:
                diff -= len(self.accounts)
            self.rotate(diff)

    def get_center_index(self):
        return int(round(-self.angle_offset / self.spacing_angle)) % len(self.accounts)

    def get_clicked_index(self, mx, my):
        order = self.get_positions()
        for idx, (x, y, size) in enumerate(order):
            if (mx - x) ** 2 + (my - y) ** 2 <= (size / 2) ** 2:
                return idx
        return None

    def rotate(self, steps):
        self.target_offset += -steps * self.spacing_angle
        if not self.animation_timer.isActive():
            self.animation_timer.start()

    def animate_step(self):
        speed = 0.15
        diff = self.target_offset - self.angle_offset
        if abs(diff) < 0.001:
            self.angle_offset = self.target_offset
            self.animation_timer.stop()
            if self.username_callback:
                self.username_callback(self.accounts[self.get_center_index()]["username"])
        else:
            self.angle_offset += diff * speed
        self.update()

    def get_positions(self):
        """Calculate positions and sizes for all accounts"""
        w = self.width()
        h = self.height()
        cx = w / 2
        cy = h / 2
        radius_x = min(250, w / 2.5)
        radius_y = min(60, h / 6)  # vertical oval lift for back profiles
        base_size = 60

        order = []
        for i, _ in enumerate(self.accounts):
            angle = i * self.spacing_angle + self.angle_offset
            x = cx + math.sin(angle) * radius_x
            y = cy + math.cos(angle) * radius_y  # higher in back
            depth_scale = 1.0 - 0.3 * (1 - math.cos(angle))  # bigger in front
            size = base_size * depth_scale + 40 * depth_scale

            if i == self.get_center_index() and self.shrink_center:
                size *= 0.85  # shrink if editing username

            order.append((x, y, size))
        return order

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        positions = self.get_positions()

        # Sort by Y for depth effect
        order_with_idx = sorted(enumerate(positions), key=lambda e: e[1][1])

        for idx, (x, y, size) in order_with_idx:
            # Border color
            if idx == self.get_center_index():
                border_color = QColor("darkgrey")
                border_width = 5
            else:
                border_color = QColor("black")
                border_width = 3

            painter.setPen(border_color)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(int(x - size / 2), int(y - size / 2), int(size), int(size))

            # Masked image
            pixmap = self.pixmaps[idx].scaled(int(size), int(size),
                                              Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                              Qt.TransformationMode.SmoothTransformation)

            mask = QPixmap(pixmap.size())
            mask.fill(Qt.GlobalColor.transparent)
            mask_painter = QPainter(mask)
            mask_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            path = QPainterPath()
            path.addEllipse(0, 0, pixmap.width(), pixmap.height())
            mask_painter.setClipPath(path)
            mask_painter.drawPixmap(0, 0, pixmap)
            mask_painter.end()

            painter.drawPixmap(int(x - size / 2), int(y - size / 2), mask)

    def set_shrink_center(self, shrink: bool):
        """Call this from LoginScreen when username is edited manually."""
        self.shrink_center = shrink
        self.update()

class LoginFields(QWidget):
    def __init__(self, parent=None, continue_callback=None):
        super().__init__(parent)
        self.username_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.continue_btn = ContinueButton(continue_callback)
        self.continue_btn.setVisible(False)

        self.username_edit.setPlaceholderText("Username")
        self.password_edit.setPlaceholderText("Password")
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)

        # Rounded style
        for edit in (self.username_edit, self.password_edit):
            edit.setStyleSheet("""
                QLineEdit {
                    border: 2px solid #bbb;
                    border-radius: 18px;
                    padding: 8px 16px;
                    font-size: 16px;
                    background: rgba(180, 180, 180, 0.25);
                    color: #fff;
                    font-weight: 500;
                }
                QLineEdit:focus {
                    border: 2px solid #448aff;
                    background: rgba(220, 220, 220, 0.35);
                    color: #fff;
                }
                QLineEdit::placeholder {
                    color: #bbb;
                }
            """)
            edit.setMinimumHeight(36)
            edit.setMaximumHeight(36)

        self.username_edit.textChanged.connect(self._check_fields)
        self.password_edit.textChanged.connect(self._check_fields)

        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(8)
        self.fields_lay = QVBoxLayout()
        self.fields_lay.setContentsMargins(0, 0, 0, 0)
        self.fields_lay.setSpacing(8)
        self.fields_lay.addWidget(self.username_edit)
        self.fields_lay.addWidget(self.password_edit)
        self.lay.addLayout(self.fields_lay)
        self.lay.addWidget(self.continue_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.lay.addStretch()

        # Animation for sliding fields right
        self._fields_offset = 0
        self.fields_anim = QPropertyAnimation(self, b"fieldsOffset", self)
        self.fields_anim.setDuration(400)
        self.fields_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Continue button fade/slide in from left
        self.continue_btn.set_opacity(0)
        self.continue_btn.set_slide(-24)
        self.arrow_anim = QPropertyAnimation(self.continue_btn, b"opacity", self)
        self.arrow_anim.setDuration(400)
        self.arrow_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.slide_anim = QPropertyAnimation(self.continue_btn, b"slide", self)
        self.slide_anim.setDuration(400)
        self.slide_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def set_username(self, username: str):
        self.username_edit.setText(username)

    def _check_fields(self):
        show = bool(self.username_edit.text().strip()) and bool(self.password_edit.text().strip())
        if show and not self.continue_btn.isVisible():
            # Reset slide and opacity before showing for smooth first animation
            self.continue_btn.set_slide(-24)
            self.continue_btn.set_opacity(0)
            self.continue_btn.setVisible(True)
            self.arrow_anim.stop()
            self.arrow_anim.setStartValue(0)
            self.arrow_anim.setEndValue(1)
            self.arrow_anim.start()
            self.slide_anim.stop()
            self.slide_anim.setStartValue(-24)
            self.slide_anim.setEndValue(0)
            self.slide_anim.start()
            self.fields_anim.stop()
            self.fields_anim.setStartValue(0)
            self.fields_anim.setEndValue(32)
            self.fields_anim.start()
        elif not show and self.continue_btn.isVisible():
            self.arrow_anim.stop()
            self.arrow_anim.setStartValue(self.continue_btn.opacity)
            self.arrow_anim.setEndValue(0)
            self.arrow_anim.start()
            self.slide_anim.stop()
            self.slide_anim.setStartValue(self.continue_btn.slide)
            self.slide_anim.setEndValue(-24)
            self.slide_anim.start()
            self.fields_anim.stop()
            self.fields_anim.setStartValue(self._fields_offset)
            self.fields_anim.setEndValue(0)
            self.fields_anim.start()
            # Hide button after fade out and reset slide/opacity for next show
            def hide_btn():
                if self.continue_btn.opacity == 0:
                    self.continue_btn.setVisible(False)
                    self.continue_btn.set_slide(-24)
                    self.continue_btn.set_opacity(0)
            self.arrow_anim.finished.connect(hide_btn)

    def get_fieldsOffset(self):
        return self._fields_offset

    def set_fieldsOffset(self, value):
        self._fields_offset = value
        self.fields_lay.setContentsMargins(int(value), 0, 0, 0)

    fieldsOffset = pyqtProperty(int, fget=get_fieldsOffset, fset=set_fieldsOffset)

class ContinueButton(QPushButton):
    def __init__(self, continue_callback=None, parent=None):
        super().__init__(parent)
        self.setFixedSize(44, 44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("background: transparent; border: none;")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._opacity = 0.0
        self._slide = -24  # start off-screen left
        self.clicked.connect(self._on_click)
        self._callback = continue_callback

    def set_opacity(self, value):
        self._opacity = value
        self.update()

    def get_opacity(self):
        return self._opacity

    opacity = pyqtProperty(float, fget=get_opacity, fset=set_opacity)

    def set_slide(self, value):
        self._slide = value
        self.update()

    def get_slide(self):
        return self._slide

    slide = pyqtProperty(int, fget=get_slide, fset=set_slide)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self._opacity)
        painter.translate(self._slide, 0)
        painter.setBrush(QColor("#1976d2"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, self.width(), self.height())
        painter.setBrush(QColor("white"))
        painter.setPen(Qt.PenStyle.NoPen)
        w, h = self.width(), self.height()
        arrow = [
            (w * 0.38, h * 0.28),
            (w * 0.38, h * 0.72),
            (w * 0.68, h * 0.5)
        ]
        path = QPainterPath()
        path.moveTo(*arrow[0])
        path.lineTo(*arrow[1])
        path.lineTo(*arrow[2])
        path.closeSubpath()
        painter.drawPath(path)

    def _on_click(self):
        if self._callback:
            self._callback()

class GlassBox(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        self.setMinimumWidth(440)
        self.setMinimumHeight(380)
        # Drop shadow for effect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 120))
        self.setGraphicsEffect(shadow)
        # Layout for stacking widgets inside glass box
        self.glass_layout = QVBoxLayout(self)
        self.glass_layout.setContentsMargins(32, 32, 32, 32)

        # Add servername label at the top - playful headline
        self.server_label = QLabel("LOGIN")
        self.server_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # Use a playful font if available, fallback to Comic Sans MS or Segoe Script, else default
        font = QFont()
        # Try Comic Sans MS, then Segoe Script, then fallback
        for family in ["Comic Sans MS", "Segoe Script", "Arial Rounded MT Bold", "Verdana"]:
            font.setFamily(family)
            if QFont(family).exactMatch():
                break
        font.setPointSize(48)
        font.setWeight(QFont.Weight.Bold)
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 110)
        self.server_label.setFont(font)

        # Glow effect on text
        glow = QGraphicsDropShadowEffect()
        glow.setBlurRadius(24)
        glow.setColor(QColor("#a0e0ff"))
        glow.setOffset(0, 0)
        self.server_label.setGraphicsEffect(glow)

        # Transparent background
        self.server_label.setStyleSheet("""
            color: #fff;
            margin-bottom: 12px;
            background: transparent;
        """)

        self.glass_layout.addWidget(self.server_label, alignment=Qt.AlignmentFlag.AlignHCenter)

    def set_servername(self, name: str):
        self.servername = name
        self.server_label.setText(f"Log into {self.servername}")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        color = QColor(0, 0, 0, 180)  # transparent black
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, 28, 28)

class QuickConnectWidget(QWidget):
    def __init__(self, parent):
        super().__init__(parent)

        self.parent = parent
        self.client = parent.client
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(5000)
        self.poll_timer.timeout.connect(self.poll_quickconnect_state)

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(0, 12, 0, 0)
        vbox.setSpacing(2)

        # Separator with "or"
        sep_row = QHBoxLayout()
        sep_row.setContentsMargins(0, 0, 0, 0)
        sep_row.setSpacing(8)
        line1 = QFrame()
        line1.setFrameShape(QFrame.Shape.HLine)
        line1.setFrameShadow(QFrame.Shadow.Sunken)
        line1.setStyleSheet("color: #aaa; background: #aaa; min-height:1px; border: none;")
        sep_row.addWidget(line1, 1)
        or_label = QLabel("or")
        or_label.setStyleSheet("color: #aaa; font-size: 13px; font-weight: 500; background: transparent;")
        sep_row.addWidget(or_label)
        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        line2.setFrameShadow(QFrame.Shadow.Sunken)
        line2.setStyleSheet("color: #aaa; background: #aaa; min-height:1px; border: none;")
        sep_row.addWidget(line2, 1)
        vbox.addLayout(sep_row)

        # "QuickConnect" (no background, no border, just white text)
        quick_label = QLabel("QuickConnect")
        quick_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        quick_label.setStyleSheet("""
            color: #fff;
            font-size: 15px;
            font-weight: 500;
            margin-top: 2px;
            background: transparent;
            border: none;
            border-radius: 0;
            padding: 2px 0 2px 0;
        """)
        vbox.addWidget(quick_label)

        # Code display (selectable, visually focused, fully transparent background)
        self.code_label = QLabel("000000")
        self.code_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.code_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.code_label.setStyleSheet("""
            color: #fff;
            font-size: 32px;
            font-weight: bold;
            letter-spacing: 4px;
            padding: 6px 0 2px 0;
            background: transparent;
            border-radius: 12px;
            border: none;
        """)
        vbox.addWidget(self.code_label)
        vbox.addStretch(1)

        self.initiate_quickconnect()

    def set_code(self, code: str):
        self.code_label.setText(code)
    
    def _run(self, fn, on_ok, on_err=None):
        worker = Worker(fn)
        worker.signals.finished.connect(on_ok)
        if on_err:
            worker.signals.error.connect(on_err)
        else:
            worker.signals.error.connect(lambda e: QtWidgets.QMessageBox.critical(self, "Error", str(e)))
        QtCore.QThreadPool.globalInstance().start(worker)

    def initiate_quickconnect(self):
        def ok(data):
            self.secret = data.get("Secret")
            if"Code" not in data:
                self.setVisible(False)
            code = data.get("Code", "??????")
            self.code_label.setText(code)
            self.poll_timer.start()

        self._run(lambda: self.client.quickconnect_initiate(), ok)

    def poll_quickconnect_state(self):
        if not self.client or not self.secret:
            return

        def ok(data):
            auth = bool(data.get("Authenticated"))
            if auth:
                self.poll_timer.stop()
                self._run(lambda: self.client.authenticate_with_quickconnect(self.secret), self._after_auth)
            else:
                error = data.get("Error")
                if error:
                    self.poll_timer.stop()
                    self.initiate_quickconnect()

        self._run(lambda: self.client.quickconnect_state(self.secret), ok)

    def _after_auth(self, data):
        assert self.client is not None
        self.parent.settings.setValue("token", self.client.state.token)
        self.parent.settings.setValue("user_id", self.client.state.user_id)
        self.parent.settings.setValue("device_id", self.client.state.device_id)
        self.parent.authenticated.emit(self.client.state)

    def setVisible(self, visible: bool):
        super().setVisible(visible)

class LoginScreen(QWidget):
    def __init__(self, users, show_quickconnect: bool, parent=None,
                 background_pixmap: QPixmap = None, continue_callback=None):
        super().__init__(parent)
        self.users = users
        self.background_pixmap = background_pixmap
        self.zoom = 1.0
        self._callback = continue_callback

        self.parent = parent

        # Layout for GlassBox (stays centered automatically)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.glass_box = GlassBox()
        self.carousel = RotatingCarousel(users, username_callback=self.on_carousel_username)
        self.login_fields = LoginFields(continue_callback=self.on_continue)
        self.quickconnect = QuickConnectWidget(parent=self.parent)

        self.glass_box.glass_layout.addWidget(self.carousel, alignment=Qt.AlignmentFlag.AlignCenter)
        self.glass_box.glass_layout.addWidget(self.login_fields, alignment=Qt.AlignmentFlag.AlignCenter)
        self.glass_box.glass_layout.addWidget(self.quickconnect, alignment=Qt.AlignmentFlag.AlignCenter)
        self.quickconnect.setVisible(show_quickconnect)

        layout.addStretch()
        layout.addWidget(self.glass_box, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.background_pixmap:
            painter = QPainter(self)
            scaled = self.background_pixmap.scaled(
                int(self.width() * self.zoom),
                int(self.height() * self.zoom),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            # Always center the image within the widget
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)

    def on_carousel_username(self, username):
        self.login_fields.set_username(username)

    def on_continue(self):
        if self._callback:
            self._callback(
                username=self.login_fields.username_edit.text(),
                password=self.login_fields.password_edit.text()
            )


# --- Small entrypoint ---
def manual():
    import sys
    from PyQt6.QtWidgets import QApplication, QMainWindow
    from PyQt6.QtGui import QPixmap, QPainter, QColor
    from PyQt6.QtCore import Qt

    app = QApplication(sys.argv)

    # Generate users and assign rainbow profile pictures
    user_count = 5
    users = [{"username": f"User {i+1}", "uid": f"{i+1}"} for i in range(user_count)]
    for i in range(user_count):
        pm = QPixmap(100, 100)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        hue = int((i / 20) * 360)
        color = QColor.fromHsv(hue, 255, 220)
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, 100, 100)
        painter.end()
        users[i]["profilepicture"] = pm

    # Generate some background gradient (Thanks Interwebs)
    bg_pixmap = QPixmap(300, 200); bg_pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(bg_pixmap); g = QLinearGradient(0,0,300,200)
    g.setColorAt(0, QColor(30,30,30)); g.setColorAt(1, QColor(60,60,90))
    p.fillRect(bg_pixmap.rect(), g); p.end()

    def on_continue(username: str, password: str):
        print("Continue clicked! Username:", username, "Password:", password)

    class MainWindow(QMainWindow):
        def __init__(self, users):
            super().__init__()
            self.setWindowTitle("Botify - Log into Server.")
            self.setCentralWidget(
                LoginScreen(
                    parent=self,
                    users=users,
                    show_quickconnect=True,
                    background_pixmap=bg_pixmap,
                    continue_callback=on_continue
                )
            )

    win = MainWindow(users)
    win.show()
    sys.exit(app.exec())
