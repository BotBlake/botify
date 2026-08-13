from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Optional

from PyQt6 import QtGui, QtWidgets
from PyQt6.QtCore import Qt
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

from . import image_loader


def _image_candidates(value: Optional[str | Iterable[str]]) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value else ()
    return tuple(value or ())


class TrackPreview(QtWidgets.QWidget):
    """Reusable track metadata and cover preview."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cover_request = 0
        self.cover_label = QtWidgets.QLabel("No track selected")
        self.cover_label.setFixedSize(220, 220)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setStyleSheet(
            "background:#ddd;border:1px solid #bbb;border-radius:6px;"
        )
        self.title_label = QtWidgets.QLabel()
        self.title_label.setStyleSheet("font-weight:600;font-size:14px")
        self.meta_label = QtWidgets.QLabel()
        self.meta_label.setWordWrap(True)
        self.meta_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.cover_label)
        layout.addSpacing(8)
        layout.addWidget(self.title_label)
        layout.addWidget(self.meta_label)
        layout.addStretch(1)

    def set_track(
        self,
        track: Mapping[str, Any],
        image_urls: Optional[str | Iterable[str]] = None,
    ) -> None:
        ticks = track.get("RunTimeTicks") or 0
        minutes, seconds = divmod(int(ticks / 10_000_000), 60)
        artists = ", ".join(track.get("Artists") or [])
        self.title_label.setText(track.get("Name") or "(untitled)")
        self.meta_label.setText(
            f"Album: {track.get('Album') or ''}\n"
            f"Artists: {artists}\n"
            f"Duration: {minutes}:{seconds:02d}\n"
            f"Id: {track.get('Id') or ''}"
        )
        self._set_cover(_image_candidates(image_urls))

    def _set_cover(self, urls: tuple[str, ...]) -> None:
        self._cover_request += 1
        request = self._cover_request
        self.cover_label.clear()
        self.cover_label.setText("Loading…" if urls else "No Image")
        if not urls:
            return

        def loaded(pixmap: QtGui.QPixmap) -> None:
            if request != self._cover_request:
                return
            self.cover_label.setText("")
            self.cover_label.setPixmap(
                pixmap.scaled(
                    220,
                    220,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

        def failed(_error: Exception) -> None:
            if request == self._cover_request:
                self.cover_label.setText("No Image")

        image_loader.load_first(urls, loaded, failed)


class PlaybackBar(QtWidgets.QWidget):
    """Reusable playback controls and current-track presentation."""

    def __init__(self, player: QMediaPlayer, audio_output: QAudioOutput, parent=None):
        super().__init__(parent)
        self.player = player
        self.audio_output = audio_output
        self._cover_request = 0
        self._seeking = False
        self.setObjectName("PlaybackBar")
        self.setStyleSheet(
            "#PlaybackBar{border-top:1px solid #ddd;background:#fafafa;}"
        )

        self.cover = QtWidgets.QLabel("♪")
        self.cover.setFixedSize(80, 80)
        self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover.setStyleSheet(
            "background:#eee;border:1px solid #ddd;border-radius:6px;"
        )
        self.title = QtWidgets.QLabel()
        self.subtitle = QtWidgets.QLabel()
        self.subtitle.setStyleSheet("font-size:11px")

        self.play_button = QtWidgets.QPushButton(
            self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MediaPlay), ""
        )
        self.stop_button = QtWidgets.QPushButton(
            self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MediaStop), ""
        )
        self.seek = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 0)
        self.time_label = QtWidgets.QLabel("0:00 / 0:00")
        self.volume = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(50)
        self.audio_output.setVolume(0.5)

        self.play_button.clicked.connect(self._toggle_play)
        self.stop_button.clicked.connect(self.player.stop)
        self.seek.sliderPressed.connect(self._seek_pressed)
        self.seek.sliderReleased.connect(self._seek_released)
        self.seek.sliderMoved.connect(self._update_time)
        self.volume.valueChanged.connect(
            lambda value: self.audio_output.setVolume(value / 100.0)
        )
        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(
            lambda duration: self.seek.setRange(0, max(duration, 0))
        )
        self.player.playbackStateChanged.connect(self._playback_state_changed)

        metadata = QtWidgets.QVBoxLayout()
        metadata.addWidget(self.title)
        metadata.addWidget(self.subtitle)
        timeline = QtWidgets.QVBoxLayout()
        timeline.addWidget(self.seek)
        timeline.addWidget(self.time_label)
        volume_controls = QtWidgets.QHBoxLayout()
        volume_controls.addWidget(QtWidgets.QLabel("🔊"))
        volume_controls.addWidget(self.volume)
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(10)
        row.addWidget(self.cover)
        row.addLayout(metadata, 1)
        row.addWidget(self.play_button)
        row.addWidget(self.stop_button)
        row.addLayout(timeline, 3)
        row.addStretch(1)
        row.addLayout(volume_controls, 1)

    def set_now_playing_meta(self, title: str, subtitle: str = "") -> None:
        self.title.setText(title)
        self.subtitle.setText(subtitle)

    def set_cover_async(self, image_urls: Optional[str | Iterable[str]]) -> None:
        urls = _image_candidates(image_urls)
        self._cover_request += 1
        request = self._cover_request
        self.cover.clear()
        self.cover.setText("♪")
        if not urls:
            return

        def loaded(pixmap: QtGui.QPixmap) -> None:
            if request != self._cover_request:
                return
            self.cover.setText("")
            self.cover.setPixmap(
                pixmap.scaled(
                    80,
                    80,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

        image_loader.load_first(urls, loaded, lambda _error: None)

    def _toggle_play(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _seek_pressed(self) -> None:
        self._seeking = True

    def _seek_released(self) -> None:
        self._seeking = False
        self.player.setPosition(self.seek.value())

    def _update_time(self, position: int) -> None:
        duration = max(self.player.duration(), 1)
        current_minutes, current_seconds = divmod(int(position / 1000), 60)
        duration_minutes, duration_seconds = divmod(int(duration / 1000), 60)
        self.time_label.setText(
            f"{current_minutes}:{current_seconds:02d} / "
            f"{duration_minutes}:{duration_seconds:02d}"
        )

    def _position_changed(self, position: int) -> None:
        if not self._seeking:
            self.seek.setValue(position)
            self._update_time(position)

    def _playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        icon = (
            QtWidgets.QStyle.StandardPixmap.SP_MediaPause
            if state == QMediaPlayer.PlaybackState.PlayingState
            else QtWidgets.QStyle.StandardPixmap.SP_MediaPlay
        )
        self.play_button.setIcon(self.style().standardIcon(icon))
