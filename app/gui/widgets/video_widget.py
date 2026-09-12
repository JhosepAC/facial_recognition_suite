from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QFont, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHeaderView, QHBoxLayout, QLabel, QMenu,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSlider,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.core.config import settings
from app.core.logger import logger
from app.database.session import get_session
from app.gui import icons
from app.i18n import bus as i18n_bus, tr
from app.services.export_service import build_export_name
from app.services.statistics_service import present_attribute_fields, primary_embedding_attrs
from app.services.video_service import VideoService
from app.vision.video_processor import VideoReader

ATTR_LABEL_KEYS = {
    "gafas": "attrs.glasses",
    "mascarilla": "attrs.mask",
    "barba": "attrs.beard",
    "bigote": "attrs.mustache",
    "sonrisa": "attrs.smile",
    "ojos_abiertos": "attrs.eyes_open",
}

ESTADO_GLYPHS = {
    "completado": ("check_circle", icons.COLOR_OK),
    "error": ("error", icons.COLOR_ERROR),
    "procesando": ("sync", "#6fa8ff"),
    "pendiente": ("circle", icons.COLOR_MUTED),
    "cancelado": ("close", icons.COLOR_MUTED),
}

# Periodo en ms del temporizador de reproducción continua.
PLAYBACK_MS = 50


# ====================================================================== #
# Hilo de trabajo: procesa el video sin bloquear la interfaz
# ====================================================================== #
class VideoProcessingWorker(QThread):
    progress = Signal(int, int)     # frames_procesados, total_frames
    finished_ok = Signal(int)       # job_id
    failed = Signal(str)

    def __init__(self, file_path: str, usuario: str | None = None,
                 sample_interval: int | None = None, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.usuario = usuario
        self.sample_interval = sample_interval

    def run(self) -> None:
        try:
            with get_session() as session:
                service = VideoService(session)
                job = service.analyze_video(
                    self.file_path,
                    progress_callback=lambda cur, total: self.progress.emit(cur, total),
                    usuario=self.usuario,
                    sample_interval=self.sample_interval,
                )
                job_id = job.id
                estado = job.estado
                mensaje_error = job.mensaje_error

            if estado == "completado":
                self.finished_ok.emit(job_id)
            else:
                self.failed.emit(mensaje_error or "Error desconocido al procesar el video.")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error en VideoProcessingWorker")
            self.failed.emit(str(exc))


# ====================================================================== #
# Zona de importación (arrastrar y soltar / selector de archivo)
# ====================================================================== #
class VideoDropArea(QFrame):
    file_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAcceptDrops(True)
        self.setMinimumHeight(96)

        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        self.icon_label = icons.icon_label("movie", 28, "#3f4250")
        self.icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.icon_label, alignment=Qt.AlignCenter)

        self.label = QLabel(tr("video.drop"))
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("color: #8f92a3;")
        self.label.setWordWrap(True)
        layout.addWidget(self.label)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        valid = [u for u in urls if Path(u).suffix.lower() in settings.video.allowed_extensions]
        if valid:
            self.file_selected.emit(valid[0])
        elif urls:
            QMessageBox.warning(self, tr("video.bad_format_title"),
                                tr("video.bad_format_msg") +
                                ", ".join(settings.video.allowed_extensions))

    def set_selected(self, path: str) -> None:
        self.icon_label.setPixmap(icons.pixmap("movie", 28, "#6fa8ff"))
        self.label.setText(icons.status_html("videocam", Path(path).name, "#e6e6e6"))
        self.label.setStyleSheet("color: #e6e6e6; font-weight: 600;")


# ====================================================================== #
# Chips: métrica del job y persona detectada
# ====================================================================== #
class MetricChip(QFrame):
    def __init__(self, icon_name: str, value: str, label: str, color: str = icons.COLOR_MUTED,
                 parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        layout.addWidget(icons.icon_label(icon_name, 20, color))

        col = QVBoxLayout()
        col.setSpacing(0)
        self.value_label = QLabel(value)
        self.value_label.setStyleSheet("font-size: 20px; font-weight: 700; color: #ffffff;")
        self._label_w = QLabel(label)
        self._label_w.setStyleSheet("color: #8f92a3; font-size: 11px;")
        col.addWidget(self.value_label)
        col.addWidget(self._label_w)
        layout.addLayout(col)
        layout.addStretch()

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)

    def set_label(self, label: str) -> None:
        self._label_w.setText(label)


class PersonChip(QFrame):
    def __init__(self, nombre: str, thumbnail: str | None, count: int,
                 conf_promedio: float | None, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFixedWidth(230)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        avatar = QLabel()
        avatar.setFixedSize(46, 46)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet("background-color: #1a1b21; border-radius: 8px;")
        pix = QPixmap(thumbnail) if thumbnail and Path(thumbnail).exists() else QPixmap()
        if pix.isNull():
            avatar.setPixmap(icons.pixmap("person", 26, "#8f92a3"))
        else:
            avatar.setPixmap(pix.scaled(46, 46, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        layout.addWidget(avatar)

        col = QVBoxLayout()
        col.setSpacing(0)
        name_label = QLabel(nombre)
        name_label.setStyleSheet("font-weight: 600; color: #ffffff;")
        name_label.setToolTip(nombre)
        sub = f"{count} aparición(es)"
        if conf_promedio is not None:
            sub += f" · {conf_promedio:.0f}%"
        self._sub_label = QLabel(sub)
        self._sub_label.setStyleSheet("color: #8f92a3; font-size: 11px;")
        col.addWidget(name_label)
        col.addWidget(self._sub_label)
        layout.addLayout(col, stretch=1)

    def update(self, count: int, conf_promedio: float | None) -> None:
        sub = f"{count} aparición(es)"
        if conf_promedio is not None:
            sub += f" · {conf_promedio:.0f}%"
        self._sub_label.setText(sub)


class PersonFilterChip(QPushButton):
    """Chip clicable con la miniatura y nombre de una persona detectada."""

    def __init__(self, nombre: str, thumbnail: str | None, count: int, parent=None):
        super().__init__(parent)
        self.setObjectName("ChipButton")
        self.setCursor(Qt.PointingHandCursor)
        pix = QPixmap(thumbnail) if thumbnail and Path(thumbnail).exists() else QPixmap()
        if not pix.isNull():
            self.setIcon(QIcon(pix.scaled(18, 18, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
        else:
            self.setIcon(icons.icon("person", 16, "#2ecc71"))
        self.setText(f"{nombre}  ·  {count}")
        self.setToolTip(f"Ir a la primera detección de {nombre}")


# ====================================================================== #
# Vista previa del video: redimensiona con el contenedor (mantiene proporción)
# ====================================================================== #
class VideoPreviewWidget(QWidget):
    """Muestra el frame actual escalado a todo el espacio disponible."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image: QImage | None = None
        self._placeholder = "Selecciona un video analizado para navegarlo."
        self.setMinimumHeight(260)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_image(self, image: QImage) -> None:
        self._image = image
        self.update()

    def set_placeholder(self, text: str) -> None:
        self._placeholder = text
        self._image = None
        self.update()

    def clear(self) -> None:
        self._image = None
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#14151c"))

        if self._image is None or self._image.isNull():
            painter.setPen(QColor("#8f92a3"))
            painter.setFont(QFont("Segoe UI", 13))
            painter.drawText(self.rect(), Qt.AlignCenter, self._placeholder)
            painter.end()
            return

        scaled = self._image.scaled(
            self.width(), self.height(),
            Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        painter.drawImage(x, y, scaled)
        painter.end()


# ====================================================================== #
# Widget principal del módulo de Video
# ====================================================================== #
class VideoAnalysisWidget(QWidget):
    def __init__(self, username: str | None = None, parent=None):
        super().__init__(parent)
        self.username = username
        self._selected_path: str | None = None
        self._worker: VideoProcessingWorker | None = None
        self._current_job_id: int | None = None
        self._preview_reader: VideoReader | None = None
        self._detections_by_frame: dict[int, list[dict]] = {}
        self._sorted_detection_frames: list[int] = []
        self._detail_rows: list[dict] = []
        self._person_frame_map: dict[str, int] = {}
        self._profile_attrs: dict[str, list[str]] = {}
        self._current_frame_number = 0
        self._current_fps = 25.0
        self._playing = False

        self._build_ui()
        self._load_latest_completed_job()
        i18n_bus().languageChanged.connect(self._retranslate)

    def _retranslate(self) -> None:
        self._title.setText(tr("video.title"))
        self._subtitle.setText(tr("video.subtitle"))
        self.drop_area.label.setText(tr("video.drop"))
        self._sample_label.setText(tr("video.sampling_label"))
        self.sample_combo.clear()
        for key, interval in (
            ("video.sampling_detailed", 5),
            ("video.sampling_standard", 10),
            ("video.sampling_fast", 15),
            ("video.sampling_ultra", 30),
        ):
            self.sample_combo.addItem(tr(key), interval)
        self.pick_btn.setText(tr("video.pick"))
        self.analyze_btn.setText(tr("video.analyze"))
        self._jobs_title.setText(tr("video.jobs_title"))
        self._refresh_btn.setToolTip(tr("video.refresh_list"))
        self.jobs_table.setHorizontalHeaderLabels(
            [tr("video.job_col_name"), tr("video.job_col_duration"),
             tr("video.job_col_status"), tr("video.job_col_detections"),
             tr("video.job_col_date")])
        self._jobs_hint.setText(tr("video.jobs_hint"))
        self._detail_title.setText(tr("video.detail_title"))
        self.export_btn.setText(tr("video.export"))
        self.delete_btn.setToolTip(tr("video.delete_tooltip"))
        self.chip_detecciones.set_label(tr("webcam.detections"))
        self.chip_personas.set_label(tr("video.chip_persons"))
        self.chip_reconocidas.set_label(tr("webcam.recognized"))
        self.chip_no_reconocidas.set_label(tr("webcam.unknowns"))
        self.chip_duracion.set_label(tr("video.chip_duration"))
        self._persons_label.setText(tr("video.persons_detected"))
        self.det_title_label.setText(tr("video.detections_title"))
        self._filter_label.setText(tr("video.min_confidence"))
        self.filter_combo.clear()
        for key, value in (("video.filter_all", 0), ("video.filter_gte_50", 50),
                           ("video.filter_gte_70", 70), ("video.filter_gte_90", 90)):
            self.filter_combo.addItem(tr(key), value)
        self.detections_table.setHorizontalHeaderLabels(
            ["#", tr("video.col_frame"), tr("video.col_time"), tr("webcam.event_name"),
             tr("webcam.event_confidence"), tr("video.col_status")])
        self.first_btn.setToolTip(tr("video.first_frame"))
        self.prev_btn.setToolTip(tr("video.prev_detection"))
        self.play_btn.setToolTip(tr("video.play_pause"))
        self.next_btn.setToolTip(tr("video.next_detection"))
        self.last_btn.setToolTip(tr("video.last_frame"))
        self.preview.set_placeholder(tr("video.preview_placeholder"))
        self._apply_detection_filter()

    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)

        # Cabecera
        header = QHBoxLayout()
        header.addWidget(icons.icon_label("movie", 22, "#6fa8ff"))
        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        self._title = QLabel(tr("video.title"))
        self._title.setStyleSheet("font-size: 22px; font-weight: 700;")
        self._subtitle = QLabel(tr("video.subtitle"))
        self._subtitle.setStyleSheet("color: #8f92a3; font-size: 12px;")
        title_col.addWidget(self._title)
        title_col.addWidget(self._subtitle)
        header.addLayout(title_col)
        header.addStretch()
        root.addLayout(header)

        # --- Importación ---
        import_card = QFrame()
        import_card.setObjectName("Card")
        import_layout = QVBoxLayout(import_card)
        import_layout.setContentsMargins(14, 14, 14, 14)
        import_layout.setSpacing(10)

        import_row = QHBoxLayout()
        self.drop_area = VideoDropArea()
        self.drop_area.file_selected.connect(self._on_file_selected)
        import_row.addWidget(self.drop_area, stretch=1)

        controls = QVBoxLayout()
        controls.setSpacing(8)

        sample_row = QHBoxLayout()
        self._sample_label = QLabel(tr("video.sampling_label"))
        self._sample_label.setStyleSheet("color: #8f92a3; font-size: 12px;")
        sample_row.addWidget(self._sample_label)
        self.sample_combo = QComboBox()
        for key, interval in (
            ("video.sampling_detailed", 5),
            ("video.sampling_standard", 10),
            ("video.sampling_fast", 15),
            ("video.sampling_ultra", 30),
        ):
            self.sample_combo.addItem(tr(key), interval)
        self.sample_combo.setCurrentIndex(2)  # c/15 = comportamiento por defecto
        self.sample_combo.setToolTip(tr("video.sampling_tooltip"))
        sample_row.addWidget(self.sample_combo, stretch=1)
        controls.addLayout(sample_row)

        self.pick_btn = QPushButton(tr("video.pick"))
        self.pick_btn.setObjectName("SecondaryButton")
        self.pick_btn.setIcon(icons.icon("folder_open", 16, "#b7b9c4"))
        self.pick_btn.clicked.connect(self._pick_file)
        controls.addWidget(self.pick_btn)

        self.analyze_btn = QPushButton(tr("video.analyze"))
        self.analyze_btn.setIcon(icons.icon("play", 16, "#ffffff"))
        self.analyze_btn.clicked.connect(self._start_analysis)
        self.analyze_btn.setEnabled(False)
        controls.addWidget(self.analyze_btn)

        import_row.addLayout(controls)
        import_layout.addLayout(import_row)

        self.file_info_label = QLabel("")
        self.file_info_label.setStyleSheet("color: #8f92a3; font-size: 12px;")
        self.file_info_label.setVisible(False)
        import_layout.addWidget(self.file_info_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        import_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #8f92a3;")
        self.status_label.setWordWrap(True)
        import_layout.addWidget(self.status_label)

        root.addWidget(import_card)

        # --- Splitter: trabajos | detalle ---
        splitter = QSplitter(Qt.Horizontal)

        # Panel izquierdo: lista de trabajos
        jobs_frame = QFrame()
        jobs_frame.setObjectName("Card")
        jobs_layout = QVBoxLayout(jobs_frame)
        jobs_layout.setContentsMargins(14, 14, 14, 14)
        jobs_layout.setSpacing(8)

        jobs_header = QHBoxLayout()
        self._jobs_title = QLabel(tr("video.jobs_title"))
        self._jobs_title.setStyleSheet("font-weight: 700; font-size: 15px;")
        jobs_header.addWidget(self._jobs_title)
        self.jobs_count_label = QLabel("0")
        self.jobs_count_label.setStyleSheet("color: #8f92a3;")
        jobs_header.addWidget(self.jobs_count_label)
        jobs_header.addStretch()
        self._refresh_btn = QPushButton()
        self._refresh_btn.setIcon(icons.icon("refresh", 16, "#b7b9c4"))
        self._refresh_btn.setObjectName("IconButton")
        self._refresh_btn.setFixedSize(28, 28)
        self._refresh_btn.setToolTip(tr("video.refresh_list"))
        self._refresh_btn.clicked.connect(lambda: self._refresh_jobs_table())
        jobs_header.addWidget(self._refresh_btn)
        jobs_layout.addLayout(jobs_header)

        self.jobs_table = QTableWidget(0, 5)
        self.jobs_table.setHorizontalHeaderLabels(
            [tr("video.job_col_name"), tr("video.job_col_duration"),
             tr("video.job_col_status"), tr("video.job_col_detections"),
             tr("video.job_col_date")])
        header = self.jobs_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in (1, 2, 3, 4):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.jobs_table.verticalHeader().setVisible(False)
        self.jobs_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.jobs_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.jobs_table.setIconSize(QSize(18, 18))
        self.jobs_table.cellClicked.connect(self._on_job_row_activated)
        jobs_layout.addWidget(self.jobs_table, stretch=1)

        self._jobs_hint = QLabel(tr("video.jobs_hint"))
        self._jobs_hint.setWordWrap(True)
        self._jobs_hint.setStyleSheet("color: #6b6e7d; font-size: 11px;")
        jobs_layout.addWidget(self._jobs_hint)
        splitter.addWidget(jobs_frame)

        # Panel derecho: detalle del trabajo seleccionado
        detail_frame = QFrame()
        detail_frame.setObjectName("Card")
        detail_layout = QVBoxLayout(detail_frame)
        detail_layout.setContentsMargins(14, 14, 14, 14)
        detail_layout.setSpacing(10)

        detail_header = QHBoxLayout()
        self._detail_title = QLabel(tr("video.detail_title"))
        self._detail_title.setStyleSheet("font-weight: 700; font-size: 15px;")
        detail_header.addWidget(self._detail_title)
        self.detail_file_label = QLabel("")
        self.detail_file_label.setStyleSheet("color: #8f92a3; font-size: 12px;")
        self.detail_file_label.setMinimumWidth(140)
        detail_header.addWidget(self.detail_file_label)
        detail_header.addStretch()

        self.export_btn = QPushButton(tr("video.export"))
        self.export_btn.setObjectName("SecondaryButton")
        self.export_btn.setIcon(icons.icon("download", 16, "#b7b9c4"))
        self.export_btn.setEnabled(False)
        self.export_btn.setMenu(self._build_export_menu())
        detail_header.addWidget(self.export_btn)

        self.delete_btn = QPushButton()
        self.delete_btn.setIcon(icons.icon("delete", 16, icons.COLOR_ERROR))
        self.delete_btn.setObjectName("IconButton")
        self.delete_btn.setFixedSize(30, 30)
        self.delete_btn.setToolTip(tr("video.delete_tooltip"))
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self._delete_current_job)
        detail_header.addWidget(self.delete_btn)
        detail_layout.addLayout(detail_header)

        # Métricas
        chips_row = QHBoxLayout()
        chips_row.setSpacing(10)
        self.chip_detecciones = MetricChip("visibility", "—", tr("webcam.detections"), "#6fa8ff")
        self.chip_personas = MetricChip("people", "—", tr("video.chip_persons"), "#2ecc71")
        self.chip_reconocidas = MetricChip("check_circle", "—", tr("webcam.recognized"), "#2ecc71")
        self.chip_no_reconocidas = MetricChip("person", "—", tr("webcam.unknowns"), "#e85d5d")
        self.chip_duracion = MetricChip("schedule", "—", tr("video.chip_duration"))
        for chip in (self.chip_detecciones, self.chip_personas, self.chip_reconocidas,
                     self.chip_no_reconocidas, self.chip_duracion):
            chips_row.addWidget(chip)
        chips_row.addStretch()
        detail_layout.addLayout(chips_row)

        # Fila de personas detectadas (chips clicables)
        self._persons_label = QLabel(tr("video.persons_detected"))
        self._persons_label.setStyleSheet("color: #8f92a3; font-size: 12px;")
        detail_layout.addWidget(self._persons_label)

        self.persons_scroll = QScrollArea()
        self.persons_scroll.setWidgetResizable(True)
        self.persons_scroll.setFrameShape(QFrame.NoFrame)
        self.persons_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.persons_scroll.setFixedHeight(40)
        self.persons_scroll.setStyleSheet(
            "QScrollArea { background-color: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background-color: transparent; }"
        )
        persons_host = QWidget()
        persons_host.setStyleSheet("background-color: transparent;")
        self.persons_layout = QHBoxLayout(persons_host)
        self.persons_layout.setContentsMargins(0, 0, 0, 0)
        self.persons_layout.setSpacing(8)
        self._persons_empty_label = QLabel(tr("video.persons_none"))
        self._persons_empty_label.setStyleSheet("color: #6b6e7d; font-size: 12px;")
        self.persons_layout.addWidget(self._persons_empty_label)
        self.persons_layout.addStretch()
        self.persons_scroll.setWidget(persons_host)
        detail_layout.addWidget(self.persons_scroll)

        # Splitter vertical: vista previa | detecciones
        self.detail_splitter = QSplitter(Qt.Vertical)
        self.detail_splitter.setChildrenCollapsible(False)
        self.detail_splitter.setStyleSheet("QSplitter::handle { background-color: transparent; }")

        # Panel superior: reproducción
        preview_pane = QWidget()
        preview_layout = QVBoxLayout(preview_pane)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(8)

        self.preview = VideoPreviewWidget()
        preview_layout.addWidget(self.preview, stretch=1)

        nav_row = QHBoxLayout()
        nav_row.setSpacing(8)
        self.frame_info_label = QLabel("")
        self.frame_info_label.setStyleSheet("color: #8f92a3; font-size: 12px; font-family: Consolas;")
        nav_row.addWidget(self.frame_info_label)

        self.first_btn = QPushButton()
        self.first_btn.setObjectName("IconButton")
        self.first_btn.setIcon(icons.icon("first_page", 18, "#b7b9c4"))
        self.first_btn.setFixedSize(30, 30)
        self.first_btn.setToolTip(tr("video.first_frame"))
        self.first_btn.clicked.connect(lambda: self._set_frame(0))
        nav_row.addWidget(self.first_btn)

        self.prev_btn = QPushButton()
        self.prev_btn.setObjectName("IconButton")
        self.prev_btn.setIcon(icons.icon("skip_previous", 18, "#b7b9c4"))
        self.prev_btn.setFixedSize(30, 30)
        self.prev_btn.setToolTip(tr("video.prev_detection"))
        self.prev_btn.clicked.connect(self._go_prev_detection)
        nav_row.addWidget(self.prev_btn)

        self.play_btn = QPushButton()
        self.play_btn.setObjectName("IconButton")
        self.play_btn.setIcon(icons.icon("play", 18, "#6fa8ff"))
        self.play_btn.setFixedSize(30, 30)
        self.play_btn.setToolTip(tr("video.play_pause"))
        self.play_btn.setEnabled(False)
        self.play_btn.clicked.connect(self._toggle_play)
        nav_row.addWidget(self.play_btn)

        self.next_btn = QPushButton()
        self.next_btn.setObjectName("IconButton")
        self.next_btn.setIcon(icons.icon("skip_next", 18, "#b7b9c4"))
        self.next_btn.setFixedSize(30, 30)
        self.next_btn.setToolTip(tr("video.next_detection"))
        self.next_btn.clicked.connect(self._go_next_detection)
        nav_row.addWidget(self.next_btn)

        self.last_btn = QPushButton()
        self.last_btn.setObjectName("IconButton")
        self.last_btn.setIcon(icons.icon("last_page", 18, "#b7b9c4"))
        self.last_btn.setFixedSize(30, 30)
        self.last_btn.setToolTip(tr("video.last_frame"))
        self.last_btn.clicked.connect(self._go_last_frame)
        nav_row.addWidget(self.last_btn)

        self.frame_slider = QSlider(Qt.Horizontal)
        self.frame_slider.setEnabled(False)
        self.frame_slider.sliderMoved.connect(self._on_slider_moved)
        self.frame_slider.sliderReleased.connect(self._on_slider_released)
        nav_row.addWidget(self.frame_slider, stretch=1)
        preview_layout.addLayout(nav_row)

        self.detail_splitter.addWidget(preview_pane)

        # Panel inferior: tabla de detecciones
        table_panel = QWidget()
        table_layout = QVBoxLayout(table_panel)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(6)

        det_header = QHBoxLayout()
        self.det_title_label = QLabel(tr("video.detections_title"))
        self.det_title_label.setStyleSheet("font-weight: 700; font-size: 15px;")
        det_header.addWidget(self.det_title_label)

        self._filter_label = QLabel(tr("video.min_confidence"))
        self._filter_label.setStyleSheet("color: #8f92a3; font-size: 12px;")
        det_header.addWidget(self._filter_label)
        self.filter_combo = QComboBox()
        for key, value in (("video.filter_all", 0), ("video.filter_gte_50", 50),
                           ("video.filter_gte_70", 70), ("video.filter_gte_90", 90)):
            self.filter_combo.addItem(tr(key), value)
        self.filter_combo.currentIndexChanged.connect(self._apply_detection_filter)
        self.filter_combo.setMinimumWidth(110)
        det_header.addWidget(self.filter_combo)
        det_header.addStretch()
        table_layout.addLayout(det_header)

        self.detections_table = QTableWidget(0, 6)
        self.detections_table.setHorizontalHeaderLabels(
            ["#", tr("video.col_frame"), tr("video.col_time"), tr("webcam.event_name"),
             tr("webcam.event_confidence"), tr("video.col_status")])
        det_header_view = self.detections_table.horizontalHeader()
        det_header_view.setSectionResizeMode(QHeaderView.Stretch)
        det_header_view.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        det_header_view.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        det_header_view.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.detections_table.verticalHeader().setVisible(False)
        self.detections_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.detections_table.setIconSize(QSize(34, 34))
        self.detections_table.setSortingEnabled(True)
        self.detections_table.cellDoubleClicked.connect(self._on_detection_row_activated)
        self.detections_table.setMinimumHeight(150)
        self.detections_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        table_layout.addWidget(self.detections_table, stretch=1)
        self.detail_splitter.addWidget(table_panel)

        self.detail_splitter.setStretchFactor(0, 3)
        self.detail_splitter.setStretchFactor(1, 2)
        detail_layout.addWidget(self.detail_splitter, stretch=1)

        splitter.addWidget(detail_frame)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 4)
        root.addWidget(splitter, stretch=1)

        # Temporizador de reproducción continua
        self._play_timer = QTimer(self)
        self._play_timer.setInterval(PLAYBACK_MS)
        self._play_timer.timeout.connect(self._play_tick)

    def _build_export_menu(self) -> QMenu:
        menu = QMenu(self)
        act_excel = menu.addAction(icons.icon("description", 16, "#6fa8ff"),
                                   tr("video.export_excel"))
        act_excel.triggered.connect(lambda: self._export_flow("excel"))
        act_csv = menu.addAction(icons.icon("download", 16, "#b7b9c4"),
                                 tr("video.export_csv"))
        act_csv.triggered.connect(lambda: self._export_flow("csv"))
        return menu

    # ------------------------------------------------------------------ #
    # Importación / lanzamiento del análisis
    # ------------------------------------------------------------------ #
    def _pick_file(self) -> None:
        exts = " ".join(f"*{e}" for e in settings.video.allowed_extensions)
        path, _ = QFileDialog.getOpenFileName(self, tr("video.pick"), "", f"{tr('video.videos_filter')} ({exts})")
        if path:
            self._on_file_selected(path)

    def _on_file_selected(self, path: str) -> None:
        self._selected_path = path
        self.drop_area.set_selected(path)
        self.analyze_btn.setEnabled(True)
        self.status_label.setText("")
        info = Path(path).name
        try:
            reader = VideoReader(path)
            meta = reader.open()
            reader.close()
            h, m, s = self._fmt_parts(meta.duration_seg)
            info += f"  ·  {m:02d}:{s:02d} min  ·  {meta.width}x{meta.height}  ·  {meta.fps:.0f} fps"
        except Exception:  # noqa: BLE001
            pass
        self.file_info_label.setText(info)
        self.file_info_label.setVisible(True)

    @staticmethod
    def _fmt_parts(seconds: float) -> tuple[int, int, int]:
        h, rem = divmod(int(seconds), 3600)
        m, s = divmod(rem, 60)
        return h, m, s

    def _start_analysis(self) -> None:
        if not self._selected_path:
            return
        self.analyze_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setText(tr("video.starting_analysis"))

        self._worker = VideoProcessingWorker(
            self._selected_path,
            usuario=self.username,
            sample_interval=self.sample_combo.currentData(),
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, current: int, total: int) -> None:
        pct = int(min(100, (current / total) * 100)) if total else 0
        self.progress_bar.setValue(pct)
        self.status_label.setText(tr("video.processing_frame").format(current, total, pct))

    def _on_finished(self, job_id: int) -> None:
        self.status_label.setText(icons.ok(tr("video.analysis_completed")))
        self.progress_bar.setVisible(False)
        self.analyze_btn.setEnabled(True)
        self._refresh_jobs_table()
        self._load_job(job_id)

    def _on_failed(self, message: str) -> None:
        self.status_label.setText(icons.err(tr("video.error_prefix").format(message)))
        self.progress_bar.setVisible(False)
        self.analyze_btn.setEnabled(True)
        self._refresh_jobs_table()

    # ------------------------------------------------------------------ #
    # Tabla de trabajos
    # ------------------------------------------------------------------ #
    def _load_latest_completed_job(self) -> None:
        latest_id: int | None = None
        with get_session() as session:
            service = VideoService(session)
            jobs = service.list_jobs()
            for job in jobs:
                if job.estado == "completado":
                    latest_id = job.id
                    break
        self._refresh_jobs_table()
        if latest_id is not None:
            self._load_job(latest_id)

    def _refresh_jobs_table(self) -> None:
        current = self._current_job_id
        with get_session() as session:
            service = VideoService(session)
            jobs = service.list_jobs()
            rows = []
            for job in jobs:
                duracion = f"{job.duracion_seg:.0f}s" if job.duracion_seg else "—"
                detecciones = service.repo.count_detections(job.id)
                fecha = job.fecha_creacion.strftime("%d/%m %H:%M") if job.fecha_creacion else "—"
                rows.append((job.id, job.nombre_archivo, duracion, job.estado, detecciones, fecha))

        self.jobs_table.setSortingEnabled(False)
        self.jobs_table.setRowCount(len(rows))
        for i, (job_id, nombre, duracion, estado, detecciones, fecha) in enumerate(rows):
            item_nombre = QTableWidgetItem(nombre)
            item_nombre.setData(Qt.UserRole, job_id)
            self.jobs_table.setItem(i, 0, item_nombre)
            self.jobs_table.setItem(i, 1, QTableWidgetItem(duracion))
            item_estado = QTableWidgetItem(estado)
            glyph, color = ESTADO_GLYPHS.get(estado, ("circle", icons.COLOR_MUTED))
            item_estado.setIcon(icons.icon(glyph, 16, color))
            self.jobs_table.setItem(i, 2, item_estado)
            self.jobs_table.setItem(i, 3, QTableWidgetItem(str(detecciones)))
            self.jobs_table.setItem(i, 4, QTableWidgetItem(fecha))
        self.jobs_table.setSortingEnabled(True)

        self.jobs_count_label.setText(str(len(rows)))

        if current is not None and any(r[0] == current for r in rows):
            self._load_job(current)

    def _on_job_row_activated(self, row: int, _col: int) -> None:
        item = self.jobs_table.item(row, 0)
        if item is None:
            return
        self._load_job(item.data(Qt.UserRole))

    # ------------------------------------------------------------------ #
    # Detalle del trabajo: métricas + detecciones + navegación
    # ------------------------------------------------------------------ #
    def _reset_detail(self) -> None:
        self._current_job_id = None
        self.detail_file_label.setText("")
        self.export_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)
        self.play_btn.setEnabled(False)
        self._stop_playback()
        for chip in (self.chip_detecciones, self.chip_personas, self.chip_reconocidas,
                     self.chip_no_reconocidas, self.chip_duracion):
            chip.set_value("—")
        self.preview.set_placeholder(tr("video.preview_placeholder"))
        self.frame_info_label.setText("")
        self._detections_by_frame = {}
        self._sorted_detection_frames = []
        self._detail_rows = []
        self._person_frame_map = {}
        self._profile_attrs = {}
        self.detections_table.setRowCount(0)
        self.det_title_label.setText(tr("video.detections_title"))
        self.frame_slider.setEnabled(False)
        self._clear_person_chips()
        if self._preview_reader is not None:
            self._preview_reader.close()
            self._preview_reader = None

    def _clear_person_chips(self) -> None:
        while self.persons_layout.count():
            item = self.persons_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _load_job(self, job_id: int) -> None:
        with get_session() as session:
            service = VideoService(session)
            job = service.get_job(job_id)
            if job is None or job.estado != "completado":
                self.status_label.setText(tr("video.no_results_yet"))
                return
            detections = service.list_detections(job_id)
            summary = service.job_summary(job_id)
            file_path = job.file_path
            total_frames = job.total_frames or 1
            fps = job.fps or 25.0
            duracion = job.duracion_seg or 0.0

            rows = [
                {
                    "frame": d.frame_number,
                    "tiempo": d.timestamp_fmt,
                    "persona": d.person.nombre_completo if d.person else tr("webcam.unknown"),
                    "person_uuid": d.person_uuid,
                    "confianza": d.confianza,
                    "evidencia": d.evidencia_path,
                    "bbox": d.bbox,
                    "recognized": d.person_uuid is not None,
                }
                for d in detections
            ]

            profile_attrs: dict[str, list[str]] = {}
            for d in detections:
                if d.person_uuid and d.person_uuid not in profile_attrs:
                    attrs = primary_embedding_attrs(d.person) if d.person else None
                    profile_attrs[d.person_uuid] = present_attribute_fields(attrs)

        self._profile_attrs = profile_attrs

        self._current_job_id = job_id
        self._current_fps = fps
        self.detail_file_label.setText(Path(file_path).name)
        self.export_btn.setEnabled(bool(rows))
        self.delete_btn.setEnabled(True)
        self.play_btn.setEnabled(True)

        self.chip_detecciones.set_value(str(summary["total"]))
        self.chip_personas.set_value(str(len(summary["personas"])))
        self.chip_reconocidas.set_value(str(summary["reconocidas"]))
        self.chip_no_reconocidas.set_value(str(summary["no_reconocidas"]))
        self.chip_duracion.set_value(self._fmt_time(duracion))

        self._detail_rows = rows
        self._apply_detection_filter()

        self._detections_by_frame = {}
        self._person_frame_map = {}
        for r in rows:
            entry = {
                "bbox": r["bbox"],
                "label": r["persona"],
                "conf": r["confianza"],
                "recognized": r["recognized"],
                "person_uuid": r["person_uuid"],
            }
            self._detections_by_frame.setdefault(r["frame"], []).append(entry)
            if r["person_uuid"] is not None and r["person_uuid"] not in self._person_frame_map:
                self._person_frame_map[r["person_uuid"]] = r["frame"]
        self._sorted_detection_frames = sorted(self._detections_by_frame.keys())

        self._rebuild_person_chips(summary["personas"])

        if self._preview_reader is not None:
            self._preview_reader.close()
        self._preview_reader = VideoReader(file_path)
        try:
            self._preview_reader.open()
        except Exception as exc:  # noqa: BLE001
            self.status_label.setText(icons.warn(tr("video.preview_failed").format(exc)))
            self._preview_reader = None
            self.play_btn.setEnabled(False)
            return

        self.frame_slider.setEnabled(True)
        self.frame_slider.setRange(0, max(0, total_frames - 1))
        first_frame = self._sorted_detection_frames[0] if self._sorted_detection_frames else 0
        self.frame_slider.setValue(first_frame)
        self._render_frame(first_frame)

    def _rebuild_person_chips(self, persons: list[dict]) -> None:
        self._clear_person_chips()
        # Se elimina el item de stretch que quedó: se reconstruye limpio.
        self.persons_layout.addStretch()
        if not persons:
            self._persons_empty_label = QLabel(tr("video.persons_none"))
            self._persons_empty_label.setStyleSheet("color: #6b6e7d; font-size: 12px;")
            self.persons_layout.insertWidget(0, self._persons_empty_label)
            return
        for entry in persons[:8]:
            chip = PersonFilterChip(entry["nombre"], entry.get("thumbnail"), entry["count"])
            chip.clicked.connect(lambda _=False, uuid_=entry["uuid"]: self._go_to_person(uuid_))
            self.persons_layout.insertWidget(self.persons_layout.count() - 1, chip)

    def _go_to_person(self, person_uuid: str) -> None:
        frame = self._person_frame_map.get(person_uuid)
        if frame is not None:
            self._set_frame(frame)

    def _fill_detections_table(self, rows: list[dict]) -> None:
        self.detections_table.setSortingEnabled(False)
        self.detections_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            num = QTableWidgetItem(str(i + 1))
            num.setTextAlignment(Qt.AlignCenter)
            self.detections_table.setItem(i, 0, num)

            item_frame = QTableWidgetItem(str(r["frame"]))
            item_frame.setData(Qt.UserRole, r["frame"])
            item_frame.setTextAlignment(Qt.AlignCenter)
            self.detections_table.setItem(i, 1, item_frame)
            self.detections_table.setItem(i, 2, QTableWidgetItem(r["tiempo"]))

            item_persona = QTableWidgetItem(r["persona"])
            pix = QPixmap(r["evidencia"]) if r["evidencia"] and Path(r["evidencia"]).exists() else QPixmap()
            if pix.isNull():
                item_persona.setIcon(icons.icon("person", 18, "#8f92a3"))
            else:
                item_persona.setIcon(QIcon(pix.scaled(34, 34, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            item_persona.setData(Qt.UserRole + 1, r["person_uuid"])
            if not r["recognized"]:
                item_persona.setForeground(Qt.gray)
            self.detections_table.setItem(i, 3, item_persona)

            conf = f"{r['confianza']:.1f}%" if r["confianza"] is not None else "—"
            item_conf = QTableWidgetItem(conf)
            item_conf.setTextAlignment(Qt.AlignCenter)
            self.detections_table.setItem(i, 4, item_conf)

            item_estado = QTableWidgetItem(tr("video.status_recognized") if r["recognized"] else tr("webcam.unknown"))
            item_estado.setTextAlignment(Qt.AlignCenter)
            item_estado.setForeground(QColor(icons.COLOR_OK) if r["recognized"] else QColor("#b7b9c4"))
            self.detections_table.setItem(i, 5, item_estado)
        self.detections_table.setSortingEnabled(True)

    def _apply_detection_filter(self) -> None:
        threshold = self.filter_combo.currentData() or 0
        filtered = [
            r for r in self._detail_rows
            if r["confianza"] is None or r["confianza"] >= threshold
        ]
        self._fill_detections_table(filtered)
        self.det_title_label.setText(tr("video.detections_count").format(len(filtered)))

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        h, m, s = VideoAnalysisWidget._fmt_parts(seconds)
        return f"{m:02d}:{s:02d}" if not h else f"{h:02d}:{m:02d}:{s:02d}"

    # ------------------------------------------------------------------ #
    # Navegación por frames
    # ------------------------------------------------------------------ #
    def _on_detection_row_activated(self, row: int, _col: int) -> None:
        item = self.detections_table.item(row, 1)
        if item is None:
            return
        self._set_frame(item.data(Qt.UserRole))

    def _on_slider_moved(self, value: int) -> None:
        self._render_frame(value)

    def _on_slider_released(self) -> None:
        self._render_frame(self.frame_slider.value())

    def _set_frame(self, frame_number: int) -> None:
        self.frame_slider.setValue(frame_number)
        self._render_frame(frame_number)

    def _go_last_frame(self) -> None:
        self._set_frame(self.frame_slider.maximum())

    def _go_prev_detection(self) -> None:
        self._step_detection(-1)

    def _go_next_detection(self) -> None:
        self._step_detection(1)

    def _step_detection(self, direction: int) -> None:
        if not self._sorted_detection_frames:
            return
        current = self.frame_slider.value()
        candidates = self._sorted_detection_frames
        if direction > 0:
            nxt = next((f for f in candidates if f > current), candidates[0])
        else:
            nxt = next((f for f in reversed(candidates) if f < current), candidates[-1])
        self._set_frame(nxt)

    def _toggle_play(self) -> None:
        if self._playing:
            self._stop_playback()
        else:
            self._start_playback()

    def _start_playback(self) -> None:
        if self._playing:
            return
        self._playing = True
        self.play_btn.setIcon(icons.icon("pause", 18, "#f2b134"))
        self.play_btn.setToolTip(tr("video.pause"))
        self.prev_btn.setEnabled(False)
        self.next_btn.setEnabled(False)
        self._play_timer.start()

    def _stop_playback(self) -> None:
        self._playing = False
        self._play_timer.stop()
        self.play_btn.setIcon(icons.icon("play", 18, "#6fa8ff"))
        self.play_btn.setToolTip(tr("video.play"))
        self.prev_btn.setEnabled(True)
        self.next_btn.setEnabled(True)

    def _play_tick(self) -> None:
        current = self.frame_slider.value()
        nxt = current + 1
        if nxt > self.frame_slider.maximum():
            self._stop_playback()
            return
        self.frame_slider.setValue(nxt)
        self._render_frame(nxt)

    # ------------------------------------------------------------------ #
    # Renderizado
    # ------------------------------------------------------------------ #
    def _draw_detections(self, frame: np.ndarray, detections: list[dict]) -> np.ndarray:
        display = frame.copy()
        for det in detections:
            x1, y1, x2, y2 = [int(v) for v in det["bbox"]]
            recognized = det["recognized"]
            color = (46, 204, 113) if recognized else (232, 93, 93)

            text = det["label"]
            if det["conf"] is not None:
                text += f"  {det['conf']:.0f}%"
            (tw, th), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)

            cv2.rectangle(display, (x1, y1), (x2, y2), color, 2)

            chips: list[str] = []
            if recognized and det.get("person_uuid"):
                present = self._profile_attrs.get(det["person_uuid"], [])
                chips = [tr(ATTR_LABEL_KEYS[f]) for f in present]

            bar_h = th + 6
            cursor = y1
            fill, fg, label = color, (255, 255, 255), text
            rows = [None]
            if chips:
                rows.append(((40, 45, 55), (120, 220, 255),
                             tr("video.attr_perfil").format(" · ".join(chips))))
            for i, ch in enumerate(rows):
                if ch is not None:
                    fill, fg, label = ch
                cursor -= bar_h + 2
                if cursor - bar_h <= 0:
                    continue
                (w, _), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX,
                                            0.5 if i else 0.55, 1)
                cv2.rectangle(display, (x1, cursor),
                              (min(display.shape[1], x1 + w + 10), cursor + bar_h),
                              fill, -1)
                cv2.putText(display, label, (x1 + 5, cursor + th + 2),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.5 if i else 0.55, fg, 1, cv2.LINE_AA)
        return display

    @staticmethod
    def _to_qimage(display: np.ndarray) -> QImage:
        rgb = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        return QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()

    def _render_frame(self, frame_number: int) -> None:
        self._current_frame_number = frame_number
        if self._preview_reader is None:
            return
        frame = self._preview_reader.read_frame_at(frame_number)
        if frame is None:
            self.preview.set_placeholder(tr("video.frame_unreadable"))
            return

        display = self._draw_detections(frame, self._detections_by_frame.get(frame_number, []))
        self.preview.set_image(self._to_qimage(display))

        tiempo = frame_number / self._current_fps if self._current_fps else 0.0
        n = len(self._detections_by_frame.get(frame_number, []))
        self.frame_info_label.setText(
            tr("video.frame_info").format(frame_number, self._fmt_time(tiempo), n)
        )

    # ------------------------------------------------------------------ #
    def _delete_current_job(self) -> None:
        if self._current_job_id is None:
            return
        resp = QMessageBox.question(
            self, tr("video.delete_title"),
            tr("video.delete_confirm"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return
        job_id = self._current_job_id
        self._stop_playback()
        with get_session() as session:
            service = VideoService(session)
            service.delete_job(job_id, usuario=self.username)
        self._reset_detail()
        self.status_label.setText(icons.ok(tr("video.analysis_deleted")))
        self._load_latest_completed_job()

    def _export_flow(self, fmt: str) -> None:
        if self._current_job_id is None:
            return
        exts_map = {"excel": (".xlsx", "Excel (*.xlsx)"), "csv": (".csv", "CSV (*.csv)")}
        ext, file_filter = exts_map.get(fmt, exts_map["csv"])
        with get_session() as session:
            job = VideoService(session).get_job(self._current_job_id)
        video_stem = Path(job.file_path).stem if job and job.file_path else "video"
        default_name = build_export_name(f"detecciones_{video_stem}", ext)
        path, _ = QFileDialog.getSaveFileName(
            self, tr("video.export_detections"), default_name, file_filter
        )
        if not path:
            return
        with get_session() as session:
            service = VideoService(session)
            count = service.export_detections(
                self._current_job_id, path, fmt=fmt, usuario=self.username
            )
        QMessageBox.information(
            self, tr("video.export_done"),
            tr("video.export_summary").format(count, path),
        )

    # ------------------------------------------------------------------ #
    def refresh_ui(self) -> None:
        self._refresh_jobs_table()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._stop_playback()
        if self._preview_reader is not None:
            self._preview_reader.close()
        if self._worker is not None:
            self._worker.wait(2000)
        super().closeEvent(event)