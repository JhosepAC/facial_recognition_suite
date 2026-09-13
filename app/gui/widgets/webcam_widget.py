"""
Live recognition with local webcam.

Design with decoupled threads to avoid flicker/slowness:

- CaptureThread: pure capture loop. Only does cap.read() and emits the frame
  to the GUI as fast as possible (no inference, no DB). Also publishes
  the latest frame to a queue for the recognition thread.
- RecognitionWorker: consumes the latest frame from the queue and runs the
  model. If the model is slower than the camera, it discards old frames
  (always processes the latest available). Opens its own DB session in its thread.
- ModelWarmupThread: preloads InsightFace models in background when
  opening the page, so turning on the camera does not freeze the UI.
"""
from __future__ import annotations

import queue
import time
import warnings
from collections import OrderedDict

import cv2
import numpy as np

# Silence noisy FutureWarnings from insightface/skimage that spam live logs
warnings.filterwarnings("ignore", category=FutureWarning, module="insightface.*")
warnings.filterwarnings("ignore", category=FutureWarning, module="skimage.*")

from PySide6.QtCore import QSize, QThread, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from app.core.config import settings
from app.core.logger import logger
from app.database.models import Person
from app.database.session import get_session
from app.gui import icons
from app.gui.widgets.video_widget import MetricChip, PersonChip
from app.i18n import bus as i18n_bus, tr
from app.recognition.recognition_service import RecognitionService
from app.services.person_service import PersonService
from app.services.statistics_service import diff_attribute_fields, primary_embedding_attrs
from app.vision.face_attributes import ATTR_FIELDS
from app.vision.face_engine import FaceEngine

ATTR_LABEL_KEYS = {
    "gafas": "attrs.glasses",
    "mascarilla": "attrs.mask",
    "barba": "attrs.beard",
    "bigote": "attrs.mustache",
    "sonrisa": "attrs.smile",
    "ojos_abiertos": "attrs.eyes_open",
}


# ====================================================================== #
# Model preload (does not block camera on start)
# ====================================================================== #
class ModelWarmupThread(QThread):
    finished_ok = Signal()
    failed = Signal(str)

    def run(self) -> None:
        try:
            FaceEngine.instance().warmup()
            self.finished_ok.emit()
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


# ====================================================================== #
# Pure capture thread (no inference)
# ====================================================================== #
class CaptureThread(QThread):
    frame_ready = Signal(int, np.ndarray)  # seq, frame BGR
    fps_updated = Signal(float)
    error = Signal(str)

    def __init__(self, camera_index: int, parent=None):
        super().__init__(parent)
        self.camera_index = camera_index
        self._running = False
        self.pending_frames: queue.Queue = queue.Queue(maxsize=1)

    def run(self) -> None:
        self._running = True
        cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(self.camera_index)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, settings.camera.frame_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, settings.camera.frame_height)
        # Try to set camera FPS to avoid CPU saturation
        try:
            cap.set(cv2.CAP_PROP_FPS, settings.camera.target_fps)
        except Exception:
            pass
        # Minimal buffer to reduce latency (avoid accumulating old frames in driver)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        if not cap.isOpened():
            self.error.emit(
                f"Could not open camera index {self.camera_index}. "
                "Check that it is not in use by another application."
            )
            self._running = False
            return

        seq = 0
        fps_window_start = time.perf_counter()
        fps_count = 0
        try:
            while self._running:
                ok, frame = cap.read()
                if not ok:
                    self.msleep(5)
                    continue

                seq += 1
                fps_count += 1

                # Fast path: show frame without any analysis.
                # Emit reference; receiver must copy if it needs to retain it.
                self.frame_ready.emit(seq, frame)

                # Slow path: leave the most recent frame for recognition.
                # Only copy when the worker can consume, discarding old ones.
                try:
                    self.pending_frames.put_nowait((seq, frame.copy()))
                except queue.Full:
                    try:
                        self.pending_frames.get_nowait()
                        self.pending_frames.put_nowait((seq, frame.copy()))
                    except queue.Empty:
                        pass

                if fps_count >= settings.camera.target_fps:
                    elapsed = time.perf_counter() - fps_window_start
                    if elapsed > 0:
                        self.fps_updated.emit(fps_count / elapsed)
                    fps_window_start = time.perf_counter()
                    fps_count = 0
                # Yield CPU briefly if UI is saturated
                # (avoid 100% busy-loop on a single core)
                if self.pending_frames.full():
                    self.msleep(1)
        finally:
            cap.release()
            self._running = False

    def stop(self) -> None:
        self._running = False
        self.wait(3000)


# ====================================================================== #
# Recognition thread decoupled from capture
# ====================================================================== #
class RecognitionWorker(QThread):
    faces_ready = Signal(int, list)  # seq del frame procesado, list[RecognizedFace]

    def __init__(self, pending_frames: queue.Queue, usuario: str | None = None,
                 parent=None):
        super().__init__(parent)
        self.pending_frames = pending_frames
        self.usuario = usuario
        self.interval = settings.camera.recognition_interval_frames
        self.lookup_refresh_s = 30.0
        self.max_width = getattr(settings.camera, "max_recognition_width", 640)
        self._running = False

    @staticmethod
    def _load_lookup(session) -> dict[str, str]:
        try:
            return {p.uuid: p.nombre_completo for p in session.query(Person).all()}
        except Exception:  # noqa: BLE001
            logger.exception("Error al cargar la lista de personas")
            return {}

    @staticmethod
    def _downscale_for_recognition(frame: np.ndarray, max_width: int) -> tuple[np.ndarray, float]:
        h, w = frame.shape[:2]
        if w <= max_width:
            return frame, 1.0
        scale = max_width / float(w)
        small = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        return small, scale

    @staticmethod
    def _scale_bboxes(faces: list, scale: float) -> list:
        if scale == 1.0:
            return faces
        inv = 1.0 / scale
        for f in faces:
            x1, y1, x2, y2 = f.bbox
            f.bbox = (x1 * inv, y1 * inv, x2 * inv, y2 * inv)
        return faces

    def run(self) -> None:
        self._running = True
        try:
            with get_session() as session:
                service = RecognitionService(session)
                lookup = self._load_lookup(session)
                last_seq = -1
                last_refresh = time.monotonic()
                processed = 0

                while self._running:
                    try:
                        seq, frame = self.pending_frames.get(timeout=0.2)
                    except queue.Empty:
                        continue

                    # If newer frames are queued, jump to the latest (do not process stale queue)
                    try:
                        while not self.pending_frames.empty():
                            seq2, frame2 = self.pending_frames.get_nowait()
                            seq, frame = seq2, frame2
                    except queue.Empty:
                        pass

                    if seq - last_seq < self.interval:
                        continue
                    last_seq = seq

                    if time.monotonic() - last_refresh > self.lookup_refresh_s:
                        lookup = self._load_lookup(session)
                        last_refresh = time.monotonic()

                    try:
                        small, scale = self._downscale_for_recognition(frame, self.max_width)
                        # Disable live attributes to save ~30ms per face (MediaPipe)
                        faces = service.recognize_frame(
                            small, person_lookup=lookup,
                            log_event=True, origen="webcam",
                            usuario=self.usuario, log_only_matches=True,
                            with_attributes=False,
                        )
                        # Rescale bboxes to original size for drawing
                        faces = self._scale_bboxes(faces, scale)
                        self.faces_ready.emit(seq, faces)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Error en reconocimiento de frame: {}", exc)

                    processed += 1
                    if processed % 40 == 0:
                        try:
                            session.commit()
                        except Exception:
                            session.rollback()
        finally:
            self._running = False

    def stop(self) -> None:
        self._running = False
        self.wait(3000)


# ====================================================================== #
# Video with fixed aspect ratio (no distortion or unbounded stretch)
# ====================================================================== #
class AspectFrameLabel(QLabel):
    """Label that keeps video aspect ratio and does not grow unbounded."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frame_ratio = 16.0 / 9.0
        self._set_ratio_from_camera()

    def _set_ratio_from_camera(self) -> None:
        try:
            w = int(settings.camera.frame_width or 1280)
            h = int(settings.camera.frame_height or 720)
            self._frame_ratio = (w / h) if h else (16.0 / 9.0)
        except Exception:  # noqa: BLE001
            self._frame_ratio = 16.0 / 9.0

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return max(1, int(width / self._frame_ratio))

    def sizeHint(self) -> QSize:  # noqa: D102
        return QSize(860, int(860 / self._frame_ratio))


# ====================================================================== #
# Main widget
# ====================================================================== #
class WebcamWidget(QWidget):
    def __init__(self, username: str | None = None, parent=None):
        super().__init__(parent)
        self.username = username
        self.capture: CaptureThread | None = None
        self.recognition: RecognitionWorker | None = None
        self.warmup: ModelWarmupThread | None = None
        self._model_ready = FaceEngine.instance().is_loaded

        self._last_faces: list = []
        self._attr_notes: dict[str, list[str]] = {}
        self._attr_notes_ts: dict[str, float] = {}
        self._session_faces = 0
        self._session_matches = 0
        self._session_unknown = 0
        self._session_persons: OrderedDict[str, dict] = OrderedDict()
        self._person_chips: dict[str, PersonChip] = {}
        self._last_log_ts: dict[str, float] = {}
        self._started_at = 0.0
        self._last_render_ts = 0.0
        self._cached_unknown_label: str | None = None
        self._cached_attr_labels: dict[str, str] = {}

        self._build_ui()
        self._start_warmup()
        i18n_bus().languageChanged.connect(self._retranslate)

    def _retranslate(self) -> None:
        self._title.setText(tr("webcam.title"))
        self._subtitle.setText(tr("webcam.subtitle"))
        self.start_btn.setText(tr("webcam.start"))
        self.stop_btn.setText(tr("webcam.stop"))
        self.camera_combo.clear()
        self.camera_combo.addItems([tr("webcam.camera_item").format(i) for i in range(4)])
        self.chip_rostros.set_label(tr("webcam.faces_screen"))
        self.chip_matches.set_label(tr("webcam.matches_label"))
        self.chip_time.set_label(tr("webcam.session_time"))
        self.chip_fps.set_label(tr("webcam.fps"))
        self._session_title.setText(tr("webcam.session_title"))
        self._events_title.setText(tr("webcam.recent"))
        self.events_table.setHorizontalHeaderLabels(
            [tr("webcam.event_time"), tr("webcam.event_name"), tr("webcam.event_confidence")])
        self._note.setText(tr("webcam.legal_note"))
        # Invalidate translation caches
        self._cached_unknown_label = None
        self._cached_attr_labels.clear()
        self._refresh_persons_chips()

    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        # Header
        header = QHBoxLayout()
        header.addWidget(icons.icon_label("videocam", 22, "#6fa8ff"))
        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        self._title = QLabel(tr("webcam.title"))
        self._title.setStyleSheet("font-size: 22px; font-weight: 700;")
        self._subtitle = QLabel(tr("webcam.subtitle"))
        self._subtitle.setStyleSheet("color: #8f92a3; font-size: 12px;")
        title_col.addWidget(self._title)
        title_col.addWidget(self._subtitle)
        header.addLayout(title_col)
        header.addStretch()
        root.addLayout(header)

        # Controls
        controls_card = QFrame()
        controls_card.setObjectName("Card")
        controls_layout = QVBoxLayout(controls_card)
        controls_layout.setContentsMargins(14, 14, 14, 14)
        controls_layout.setSpacing(10)

        controls_row = QHBoxLayout()
        self.camera_combo = QComboBox()
        self.camera_combo.addItems([tr("webcam.camera_item").format(i) for i in range(4)])
        self.camera_combo.setCurrentIndex(settings.camera.default_index)
        controls_row.addWidget(self.camera_combo)

        self.start_btn = QPushButton(tr("webcam.start"))
        self.start_btn.setIcon(icons.icon("play", 16, "#ffffff"))
        self.start_btn.clicked.connect(self._start)
        controls_row.addWidget(self.start_btn)

        self.stop_btn = QPushButton(tr("webcam.stop"))
        self.stop_btn.setObjectName("SecondaryButton")
        self.stop_btn.setIcon(icons.icon("stop", 16, "#b7b9c4"))
        self.stop_btn.clicked.connect(self._stop)
        self.stop_btn.setEnabled(False)
        controls_row.addWidget(self.stop_btn)

        controls_row.addStretch()
        controls_layout.addLayout(controls_row)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        controls_layout.addWidget(self.status_label)
        root.addWidget(controls_card)

        # Session metrics
        chips_row = QHBoxLayout()
        chips_row.setSpacing(10)
        self.chip_fps = MetricChip("videocam", "—", tr("webcam.fps"), "#6fa8ff")
        self.chip_rostros = MetricChip("people", "—", tr("webcam.faces_screen"), "#f2b134")
        self.chip_matches = MetricChip("check_circle", "0", tr("webcam.matches_label"), "#2ecc71")
        self.chip_time = MetricChip("schedule", "00:00", tr("webcam.session_time"))
        for chip in (self.chip_fps, self.chip_rostros, self.chip_matches, self.chip_time):
            chips_row.addWidget(chip)
        chips_row.addStretch()
        root.addLayout(chips_row)

        # Splitter: video | session panel
        splitter = QSplitter(Qt.Horizontal)

        video_frame = QFrame()
        video_frame.setObjectName("Card")
        video_layout = QVBoxLayout(video_frame)
        video_layout.setContentsMargins(10, 10, 10, 10)
        self.video_label = AspectFrameLabel(
            icons.status_html("videocam", tr("webcam.camera_stopped"), "#8f92a3", 18))
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(480, 270)
        self.video_label.setMaximumSize(1280, 720)
        self.video_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_label.setStyleSheet(
            "color: #8f92a3; background-color: #16171c;"
            "border: 1px solid #2a2b33; border-radius: 8px;"
        )
        video_layout.addWidget(self.video_label, 1)
        splitter.addWidget(video_frame)

        session_frame = QFrame()
        session_frame.setObjectName("Card")
        session_layout = QVBoxLayout(session_frame)
        session_layout.setContentsMargins(14, 14, 14, 14)
        session_layout.setSpacing(10)

        self._session_title = QLabel(tr("webcam.session_title"))
        self._session_title.setStyleSheet("font-weight: 700; font-size: 15px;")
        session_layout.addWidget(self._session_title)

        persons_header = QHBoxLayout()
        self.persons_label = QLabel(tr("webcam.persons_seen"))
        self.persons_label.setStyleSheet("font-weight: 600; font-size: 13px; color: #ffffff;")
        persons_header.addWidget(self.persons_label)
        persons_header.addStretch()
        session_layout.addLayout(persons_header)

        self.persons_scroll = QScrollArea()
        self.persons_scroll.setWidgetResizable(True)
        self.persons_scroll.setFrameShape(QFrame.NoFrame)
        self.persons_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.persons_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.persons_scroll.setStyleSheet(
            "QScrollArea { background-color: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background-color: transparent; }"
        )
        persons_host = QWidget()
        persons_host.setStyleSheet("background-color: transparent;")
        self.persons_layout = QVBoxLayout(persons_host)
        self.persons_layout.setContentsMargins(0, 0, 0, 0)
        self.persons_layout.setSpacing(8)
        self._persons_empty = QLabel(tr("webcam.no_persons_seen"))
        self._persons_empty.setStyleSheet("color: #8f92a3; padding: 6px;")
        self._persons_empty.setWordWrap(True)
        self.persons_layout.addWidget(self._persons_empty)
        self.persons_scroll.setWidget(persons_host)
        session_layout.addWidget(self.persons_scroll, stretch=1)

        self._events_title = QLabel(tr("webcam.recent"))
        self._events_title.setStyleSheet("color: #8f92a3; font-size: 12px;")
        session_layout.addWidget(self._events_title)

        self.events_table = QTableWidget(0, 3)
        self.events_table.setHorizontalHeaderLabels(
            [tr("webcam.event_time"), tr("webcam.event_name"), tr("webcam.event_confidence")])
        self.events_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.events_table.verticalHeader().setVisible(False)
        self.events_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.events_table.setMaximumHeight(220)
        session_layout.addWidget(self.events_table, stretch=1)

        splitter.addWidget(session_frame)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 3)
        splitter.setStyleSheet(
            "QSplitter::handle { background-color: transparent; border: none; }")
        root.addWidget(splitter, stretch=1)

        self._note = QLabel(tr("webcam.legal_note"))
        self._note.setWordWrap(True)
        self._note.setStyleSheet("color: #6b6e7d; font-size: 11px;")
        root.addWidget(self._note)

        self._session_timer = QTimer(self)
        self._session_timer.setInterval(1000)
        self._session_timer.timeout.connect(self._update_session_time)

        if self._model_ready:
            self.status_label.setText("Modelos de reconocimiento listos.")

    # ------------------------------------------------------------------ #
    # Model preload
    # ------------------------------------------------------------------ #
    def _start_warmup(self) -> None:
        if self._model_ready:
            self.status_label.setText(tr("webcam.models_ready"))
            return
        self.status_label.setText(tr("webcam.loading_models"))
        self.warmup = ModelWarmupThread()
        self.warmup.finished_ok.connect(lambda: self._on_model_ready(True))
        self.warmup.failed.connect(lambda msg: self._on_model_ready(False, msg))
        self.warmup.start()

    def _on_model_ready(self, ok: bool, message: str | None = None) -> None:
        self._model_ready = ok
        if ok:
            if self.capture is not None:
                self.status_label.setText(icons.ok(tr("webcam.camera_active")))
            else:
                self.status_label.setText(tr("webcam.models_ready"))
        else:
            self.status_label.setText(
                icons.err(tr("webcam.models_failed").format(message))
            )

    # ------------------------------------------------------------------ #
    # Stream control
    # ------------------------------------------------------------------ #
    def _start(self) -> None:
        if self.capture is not None:
            return
        camera_index = self.camera_combo.currentIndex()

        self.capture = CaptureThread(camera_index)
        self.capture.frame_ready.connect(self._on_frame)
        self.capture.fps_updated.connect(self._on_fps)
        self.capture.error.connect(self._on_error)

        self.recognition = RecognitionWorker(self.capture.pending_frames,
                                             usuario=self.username)
        self.recognition.faces_ready.connect(self._on_faces_ready)

        self.recognition.start()
        self.capture.start()

        self._started_at = time.monotonic()
        self._session_timer.start()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.camera_combo.setEnabled(False)
        self.chip_time.set_value("00:00")
        if self._model_ready:
            self.status_label.setText(icons.ok(tr("webcam.camera_active")))
        else:
            self.status_label.setText(
                icons.warn(tr("webcam.camera_preparing"))
            )

    def _stop(self) -> None:
        self._session_timer.stop()
        if self.recognition is not None:
            self.recognition.stop()
            self.recognition = None
        if self.capture is not None:
            self.capture.stop()
            self.capture = None
        self._last_faces = []

        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.camera_combo.setEnabled(True)
        self.status_label.setText(tr("webcam.camera_stopped"))
        self.video_label.setText(icons.status_html(
            "videocam", tr("webcam.camera_stopped"), "#8f92a3", 18))
        self.video_label.setPixmap(QPixmap())
        self._reset_session_metrics()

    def _on_error(self, message: str) -> None:
        self._stop()
        self.status_label.setText(icons.err(message))

    def closeEvent(self, event) -> None:  # noqa: N802
        self._session_timer.stop()
        if self.recognition is not None:
            self.recognition.stop()
        if self.capture is not None:
            self.capture.stop()
        if self.warmup is not None:
            self.warmup.wait(3000)
        super().closeEvent(event)

    # ------------------------------------------------------------------ #
    # Session metrics
    # ------------------------------------------------------------------ #
    def _reset_session_metrics(self) -> None:
        self._session_faces = 0
        self._session_matches = 0
        self._session_unknown = 0
        self._session_persons.clear()
        self._person_chips.clear()
        self._last_log_ts.clear()
        self._attr_notes.clear()
        self._attr_notes_ts.clear()
        self.chip_fps.set_value("—")
        self.chip_rostros.set_value("—")
        self.chip_matches.set_value("0")
        self.chip_time.set_value("00:00")
        self._refresh_persons_chips()
        self.events_table.setRowCount(0)

    def _update_session_time(self) -> None:
        elapsed = int(time.monotonic() - self._started_at)
        m, s = divmod(elapsed, 60)
        self.chip_time.set_value(f"{m:02d}:{s:02d}")

    def _on_fps(self, fps: float) -> None:
        self.chip_fps.set_value(f"{fps:.0f}")

    def _refresh_persons_chips(self) -> None:
        # Reuse existing cards: only create new ones, update
        # the rest in place (avoid flicker and per-frame rebuilds).
        seen: set[str] = set()
        for uuid, entry in self._session_persons.items():
            seen.add(uuid)
            chip = self._person_chips.get(uuid)
            if chip is None:
                chip = PersonChip(entry["nombre"], None, 0, None)
                self._person_chips[uuid] = chip
                self.persons_layout.addWidget(chip)
            chip.update(entry["count"], entry["sum"] / entry["count"])

        for uuid, chip in list(self._person_chips.items()):
            if uuid not in seen:
                self.persons_layout.removeWidget(chip)
                chip.deleteLater()
                del self._person_chips[uuid]

        show_empty = self._session_faces == 0 and not self._session_persons
        if show_empty:
            if not getattr(self, "_persons_empty", None):
                self._persons_empty = QLabel(
                    tr("webcam.no_persons_seen"))
                self._persons_empty.setStyleSheet("color: #8f92a3; padding: 6px;")
                self.persons_layout.addWidget(self._persons_empty)
        else:
            if getattr(self, "_persons_empty", None) is not None:
                self.persons_layout.removeWidget(self._persons_empty)
                self._persons_empty.deleteLater()
                self._persons_empty = None

        total = len(self._session_persons)
        self.persons_label.setText(
            tr("webcam.persons_seen") + (f"  ·  {total}" if total else ""))

    def _append_event(self, hora: str, nombre: str, confianza: float) -> None:
        self.events_table.insertRow(0)
        self.events_table.setItem(0, 0, QTableWidgetItem(hora))
        item_persona = QTableWidgetItem(nombre)
        item_persona.setIcon(icons.icon("person", 16, "#2ecc71"))
        self.events_table.setItem(0, 1, item_persona)
        item_conf = QTableWidgetItem(f"{confianza:.0f}%")
        item_conf.setForeground(QColor(icons.COLOR_OK))
        item_conf.setTextAlignment(Qt.AlignCenter)
        self.events_table.setItem(0, 2, item_conf)
        while self.events_table.rowCount() > 10:
            self.events_table.removeRow(self.events_table.rowCount() - 1)

    def _on_faces_ready(self, seq: int, faces: list) -> None:
        self._last_faces = faces
        self.chip_rostros.set_value(str(len(faces)))
        now = time.strftime("%H:%M:%S")
        now_ts = time.monotonic()
        for face in faces:
            self._session_faces += 1
            if face.person_uuid:
                entry = self._session_persons.get(face.person_uuid)
                if entry is None:
                    entry = {"nombre": face.person_nombre or tr("webcam.person"),
                             "count": 0, "sum": 0.0}
                    self._session_persons[face.person_uuid] = entry
                    self._session_matches += 1
                    self._append_event(now, entry["nombre"], face.confidence_pct)
                    self._last_log_ts[face.person_uuid] = now_ts
                    self._refresh_attr_notes(face.person_uuid, face.attributes)
                entry["count"] += 1
                entry["sum"] += face.confidence_pct
                # Refresh the log row every few seconds, not per frame.
                if now_ts - self._last_log_ts.get(face.person_uuid, 0) >= 5:
                    self._last_log_ts[face.person_uuid] = now_ts
                    self._append_event(now, entry["nombre"], face.confidence_pct)
                    self._refresh_attr_notes(face.person_uuid, face.attributes)
            else:
                self._session_unknown += 1
        self.chip_matches.set_value(str(self._session_matches))
        self._refresh_persons_chips()

    # ------------------------------------------------------------------ #
    # Frame rendering on screen
    # ------------------------------------------------------------------ #
    def _refresh_attr_notes(self, person_uuid: str, live_attrs) -> None:
        """Compare live-seen attributes with the stored profile and cache notices."""
        if not settings.recognition.live_attr_check or live_attrs is None:
            return
        # Cache 15s per person to avoid hitting DB every frame
        now = time.monotonic()
        if person_uuid in self._attr_notes_ts and now - self._attr_notes_ts[person_uuid] < 15:
            return
        stored = None
        try:
            with get_session() as session:
                person = PersonService(session).get(person_uuid)
                stored = primary_embedding_attrs(person) if person else None
        except Exception:  # noqa: BLE001
            return
        notes: list[str] = []
        for field in diff_attribute_fields(live_attrs, stored):
            live = bool(getattr(live_attrs, field))
            key = "webcam.attr_diff_on" if live else "webcam.attr_diff_off"
            # cache tr de labels
            label = self._cached_attr_labels.get(field)
            if label is None:
                label = tr(ATTR_LABEL_KEYS[field])
                self._cached_attr_labels[field] = label
            notes.append(tr(key).format(label))
        self._attr_notes[person_uuid] = notes
        self._attr_notes_ts[person_uuid] = now

    def _draw_faces(self, frame: np.ndarray, faces: list) -> np.ndarray:
        if not faces:
            return frame
        display = frame.copy()
        # Cache tr to avoid resolving i18n per face per frame
        cached_unknown = getattr(self, "_cached_unknown_label", None)
        if cached_unknown is None:
            cached_unknown = tr("webcam.unknown")
            self._cached_unknown_label = cached_unknown
        unknown_label = cached_unknown
        if not hasattr(self, "_cached_attr_labels"):
            self._cached_attr_labels = {}
        for face in faces:
            x1, y1, x2, y2 = [int(v) for v in face.bbox]
            # Clamp bbox to frame to avoid out-of-range rects (cv2 crash)
            h, w = display.shape[:2]
            x1 = max(0, min(x1, w - 1))
            y1 = max(0, min(y1, h - 1))
            x2 = max(x1 + 1, min(x2, w))
            y2 = max(y1 + 1, min(y2, h))
            recognized = face.person_uuid is not None
            color = (46, 204, 113) if recognized else (232, 93, 93)

            text = face.person_nombre if recognized else unknown_label
            if recognized:
                text += f"  {face.confidence_pct:.0f}%"
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)

            cv2.rectangle(display, (x1, y1), (x2, y2), color, 2)

            extra_lines: list[tuple[tuple, tuple, str]] = []
            if face.attributes is not None:
                # Reutilizar labels cacheados
                present = []
                for f in ATTR_FIELDS:
                    if getattr(face.attributes, f):
                        lbl = self._cached_attr_labels.get(f)
                        if lbl is None:
                            lbl = tr(ATTR_LABEL_KEYS[f])
                            self._cached_attr_labels[f] = lbl
                        present.append(lbl)
                if present:
                    chip_text = " · ".join(present)
                    extra_lines.append(((40, 45, 55), (120, 220, 255), chip_text))
            if recognized:
                notes = self._attr_notes.get(face.person_uuid)
                if notes:
                    warn_text = "! " + "; ".join(notes)
                    extra_lines.append(((0, 150, 230), (20, 42, 12), warn_text))

            bar_h = th + 6
            cursor = y1
            fill, fg, label = color, (255, 255, 255), text
            # [None] is the header (name/confidence); extra_lines are chips/attributes.
            # Avoid unpacking None that caused TypeError each frame.
            for i, entry in enumerate([None] + extra_lines):
                if entry is not None:
                    ch_fill, ch_fg, ch_label = entry
                    fill, fg, label = ch_fill, ch_fg, ch_label
                cursor -= bar_h + 2
                if cursor - bar_h <= 0:
                    continue
                (w2, _), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX,
                                            0.5 if i else 0.55, 1)
                cv2.rectangle(display, (x1, cursor),
                              (min(display.shape[1], x1 + w2 + 10), cursor + bar_h),
                              fill, -1)
                cv2.putText(display, label, (x1 + 5, cursor + th + 2),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.5 if i else 0.55, fg, 1, cv2.LINE_AA)
        return display

    def _on_frame(self, seq: int, frame: np.ndarray) -> None:
        # Rendering throttle: no more than display_max_fps (prevents saturating the UI thread).
        max_fps = getattr(settings.camera, "display_max_fps", 30)
        min_interval = 1.0 / max(1, max_fps)
        now = time.perf_counter()
        last_ts = getattr(self, "_last_render_ts", 0.0)
        if now - last_ts < min_interval:
            return
        self._last_render_ts = now

        # Draw only if there are faces; otherwise avoid expensive copy
        if self._last_faces:
            display = self._draw_faces(frame, self._last_faces)
        else:
            display = frame

        label_w = self.video_label.width()
        label_h = self.video_label.height()
        rgb = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimage = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(qimage).scaled(
            label_w, label_h,
            Qt.KeepAspectRatio, Qt.FastTransformation,
        )
        self.video_label.setPixmap(pixmap)
