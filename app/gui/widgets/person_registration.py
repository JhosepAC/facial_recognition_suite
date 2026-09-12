"""
Registro de personas.

Este módulo es exclusivamente para dar de alta personas: la ficha de datos
y su dataset de fotografías (que se procesan localmente para extraer el
vector biométrico). No hay lista de personas aquí — la búsqueda/gestión de
registros existentes vive en el módulo de Búsqueda.

Flujo:
1. El usuario llena la ficha y agrega fotografías (arrastrar-soltar,
   selector de archivos o captura desde webcam). Las fotos quedan *en
   espera* (staging) hasta el guardado.
2. Al pulsar «Guardar», un hilo en segundo plano crea la persona, procesa
   cada foto (detección + embedding) y reporta el progreso.
3. Al terminar, el formulario se limpia por completo (campos y dataset)
   para registrar a la siguiente persona.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import cv2

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QComboBox,
    QSpinBox, QTextEdit, QPushButton, QLabel, QScrollArea, QFrame,
    QFileDialog, QMessageBox, QGridLayout, QDialog, QSplitter, QProgressBar,
)

from app.database.session import get_session
from app.gui import icons
from app.i18n import bus as i18n_bus, tr
from app.services.person_service import PersonService
from app.core.logger import logger

PHOTO_CARD_WIDTH = 150
PHOTO_CARD_HEIGHT = 186

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


# --------------------------------------------------------------------------- #
# Vista previa de una foto a tamaño completo
# --------------------------------------------------------------------------- #
class PhotoPreviewDialog(QDialog):
    """Ventana modal para ver una foto del dataset a tamaño completo."""

    def __init__(self, photo_path: str, title: str, parent=None,
                 attributes_text: str | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        pix = QPixmap(photo_path)
        if not pix.isNull():
            if pix.width() > 900 or pix.height() > 640:
                pix = pix.scaled(900, 640, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        label = QLabel()
        if pix.isNull():
            label.setText(tr("persons.load_image_error"))
            label.setAlignment(Qt.AlignCenter)
        else:
            label.setPixmap(pix)
        label.setMinimumSize(400, 300)
        layout.addWidget(label)

        if attributes_text:
            attrs_label = QLabel(attributes_text)
            attrs_label.setWordWrap(True)
            attrs_label.setStyleSheet(
                "color: #c9cbd6; font-size: 12px; padding: 6px 10px;"
                "background-color: #1c1d24; border: 1px solid #2a2b33; border-radius: 6px;"
            )
            layout.addWidget(attrs_label)

        close_btn = QPushButton(tr("common.close"))
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignRight)


# --------------------------------------------------------------------------- #
# Tarjeta de foto
# --------------------------------------------------------------------------- #
class PhotoCard(QFrame):
    """Tarjeta de una foto del dataset: miniatura, calidad, principal y acciones."""

    preview_requested = Signal(int)
    primary_requested = Signal(int)
    delete_requested = Signal(int)

    def __init__(self, photo_id: int, thumb_path: str | None,
                 calidad_score: float | None, es_principal: bool, parent=None,
                 show_primary_btn: bool = True, show_delete_btn: bool = True):
        super().__init__(parent)
        self.photo_id = photo_id
        self.setObjectName("Card")
        self.setFixedSize(PHOTO_CARD_WIDTH, PHOTO_CARD_HEIGHT)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        thumb = QLabel()
        thumb.setFixedSize(PHOTO_CARD_WIDTH - 16, 120)
        thumb.setAlignment(Qt.AlignCenter)
        thumb.setCursor(Qt.PointingHandCursor)
        thumb.setStyleSheet("background-color: #1a1b21; border-radius: 6px;")
        thumb.setToolTip(tr("persons.view_large"))
        thumb.mousePressEvent = lambda _event: self.preview_requested.emit(self.photo_id)
        self._load_thumb(thumb, thumb_path)
        layout.addWidget(thumb)

        badges = QHBoxLayout()
        badges.setSpacing(4)
        if es_principal:
            star = QLabel()
            star.setPixmap(icons.pixmap("star", 14, icons.COLOR_WARN))
            star.setToolTip(tr("persons.primary"))
            badges.addWidget(star)
        if calidad_score is not None:
            quality = QLabel(f"{calidad_score:.0f}/100")
            quality.setStyleSheet("color: #8f92a3; font-size: 11px;")
            quality.setToolTip(tr("persons.quality_score"))
            badges.addWidget(quality)
        badges.addStretch()
        layout.addLayout(badges)

        actions = QHBoxLayout()
        actions.setSpacing(6)

        if show_primary_btn:
            primary_btn = QPushButton()
            primary_btn.setIcon(icons.icon(
                "star", 16, icons.COLOR_WARN if es_principal else icons.COLOR_MUTED
            ))
            primary_btn.setObjectName("IconButton")
            primary_btn.setFixedSize(28, 28)
            primary_btn.setToolTip(tr("persons.mark_primary") if not es_principal else tr("persons.primary"))
            primary_btn.setCursor(Qt.PointingHandCursor)
            primary_btn.clicked.connect(lambda: self.primary_requested.emit(self.photo_id))
            actions.addWidget(primary_btn)

        preview_btn = QPushButton()
        preview_btn.setIcon(icons.icon("visibility", 16, icons.COLOR_MUTED))
        preview_btn.setObjectName("IconButton")
        preview_btn.setFixedSize(28, 28)
        preview_btn.setToolTip(tr("persons.view_photo"))
        preview_btn.setCursor(Qt.PointingHandCursor)
        preview_btn.clicked.connect(lambda: self.preview_requested.emit(self.photo_id))
        actions.addWidget(preview_btn)

        actions.addStretch()

        if show_delete_btn:
            del_btn = QPushButton()
            del_btn.setIcon(icons.icon("delete", 16, icons.COLOR_ERROR))
            del_btn.setObjectName("IconButton")
            del_btn.setFixedSize(28, 28)
            del_btn.setToolTip(tr("persons.delete_photo"))
            del_btn.setCursor(Qt.PointingHandCursor)
            del_btn.clicked.connect(lambda: self.delete_requested.emit(self.photo_id))
            actions.addWidget(del_btn)
        layout.addLayout(actions)

    def _load_thumb(self, label: QLabel, thumb_path: str | None) -> None:
        pix = QPixmap(thumb_path) if thumb_path and Path(thumb_path).exists() else QPixmap()
        if pix.isNull():
            pix = icons.pixmap("image", 40, "#5a5d6e")
        else:
            pix = pix.scaled(PHOTO_CARD_WIDTH - 16, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        label.setPixmap(pix)


# --------------------------------------------------------------------------- #
# Rejilla de fotos con drag & drop
# --------------------------------------------------------------------------- #
class PhotoGridWidget(QWidget):
    """Rejilla de tarjetas de fotos dentro de un QScrollArea; acepta drag & drop."""

    files_dropped = Signal(list)
    resized = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("Card")
        self.empty_label: QLabel | None = None
        self.grid = QGridLayout(self)
        self.grid.setSpacing(10)
        self.grid.setContentsMargins(12, 12, 12, 12)
        self.show_empty()
        i18n_bus().languageChanged.connect(self._on_language_changed)

    def _on_language_changed(self) -> None:
        if self.empty_label is not None:
            self.empty_label.setText(tr("persons.drop_hint"))

    def clear_cards(self) -> None:
        self.grid.setRowStretch(0, 0)
        self.grid.setColumnStretch(0, 0)
        self.grid.setContentsMargins(12, 12, 12, 12)
        self.grid.setSpacing(10)
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def show_empty(self) -> None:
        self.clear_cards()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(0)
        self.empty_label = QLabel(tr("persons.drop_hint"))
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(
            "color: #8f92a3; background-color: #16171c; padding: 48px 16px;"
        )
        self.empty_label.setWordWrap(True)
        self.grid.addWidget(self.empty_label, 0, 0)
        self.grid.setRowStretch(0, 1)
        self.grid.setColumnStretch(0, 1)
        self.empty_label.setVisible(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        image_paths = [p for p in paths if Path(p).suffix.lower() in IMAGE_EXTENSIONS]
        if image_paths:
            self.files_dropped.emit(image_paths)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.resized.emit()


# --------------------------------------------------------------------------- #
# Captura de foto desde webcam (diálogo modal)
# --------------------------------------------------------------------------- #
class _CameraThread(QThread):
    frame_ready = Signal(object)  # np.ndarray BGR
    error = Signal(str)

    def __init__(self, camera_index: int = 0, parent=None):
        super().__init__(parent)
        self.camera_index = camera_index
        self._running = False

    def run(self) -> None:
        cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            self.error.emit(tr("persons.camera_error"))
            self._running = False
            return
        self._running = True
        try:
            while self._running:
                ok, frame = cap.read()
                if not ok:
                    self.msleep(10)
                    continue
                self.frame_ready.emit(frame)
                self.msleep(30)
        finally:
            cap.release()
            self._running = False

    def stop(self) -> None:
        self._running = False
        self.wait(3000)


class CapturePhotoDialog(QDialog):
    """Permite tomar una fotografía desde la webcam para el dataset."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.photo_path: str | None = None
        self.setWindowTitle(tr("persons.capture_title"))
        self.resize(700, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.video_label = QLabel(icons.status_html(
            "videocam", tr("persons.camera_preparing"), "#8f92a3", 18))
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(640, 400)
        self.video_label.setStyleSheet(
            "color: #8f92a3; background-color: #14151c;"
            "border: 1px solid #2a2b33; border-radius: 8px;"
        )
        layout.addWidget(self.video_label, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.capture_btn = QPushButton(tr("persons.capture_btn"))
        self.capture_btn.setIcon(icons.icon("camera", 16, "#ffffff"))
        self.capture_btn.setCursor(Qt.PointingHandCursor)
        self.capture_btn.clicked.connect(self._capture)
        btn_row.addWidget(self.capture_btn)

        self.accept_btn = QPushButton(tr("persons.use_photo"))
        self.accept_btn.setIcon(icons.icon("check_circle", 16, "#ffffff"))
        self.accept_btn.setCursor(Qt.PointingHandCursor)
        self.accept_btn.setVisible(False)
        self.accept_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.accept_btn)

        self.retry_btn = QPushButton(tr("persons.retry"))
        self.retry_btn.setObjectName("SecondaryButton")
        self.retry_btn.setCursor(Qt.PointingHandCursor)
        self.retry_btn.setVisible(False)
        self.retry_btn.clicked.connect(self._start_camera)
        btn_row.addWidget(self.retry_btn)

        btn_row.addStretch()

        cancel_btn = QPushButton(tr("common.cancel"))
        cancel_btn.setObjectName("SecondaryButton")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        self._frame: object | None = None
        self._frame_ref: object | None = None
        self._camera: _CameraThread | None = None
        self._start_camera()

    # ------------------------------------------------------------------ #
    def _start_camera(self) -> None:
        if self._camera is not None:
            self._camera.stop()
            self._camera = None
        self._frame = None
        self.video_label.setText(icons.status_html(
            "videocam", tr("persons.camera_preparing"), "#8f92a3", 18))
        self.video_label.setPixmap(QPixmap())
        self.capture_btn.setVisible(True)
        self.accept_btn.setVisible(False)
        self.retry_btn.setVisible(False)
        self.status_label.setText("")
        self._camera = _CameraThread(parent=self)
        self._camera.frame_ready.connect(self._on_frame)
        self._camera.error.connect(self._on_camera_error)
        self._camera.start()

    def _on_frame(self, frame) -> None:
        self._frame = frame
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        self._frame_ref = rgb
        img = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()
        pix = QPixmap.fromImage(img).scaled(
            self.video_label.width(), self.video_label.height(),
            Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        self.video_label.setPixmap(pix)

    def _on_camera_error(self, message: str) -> None:
        if self._camera is not None:
            self._camera.stop()
            self._camera = None
        self.capture_btn.setEnabled(False)
        self.video_label.setText(icons.status_html("error", message, icons.COLOR_ERROR, 18))
        self.status_label.setText(icons.err(message))

    def _capture(self) -> None:
        if self._frame is None:
            return
        if self._camera is not None:
            self._camera.stop()
            self._camera = None
        fd, path = tempfile.mkstemp(suffix=".png", prefix="biovision_capture_")
        os.close(fd)
        ok, encoded = cv2.imencode(".png", self._frame)
        if not ok:
            self.status_label.setText(icons.err(tr("persons.encode_error")))
            return
        encoded.tofile(path)
        self.photo_path = path

        pix = QPixmap(path).scaled(
            self.video_label.width(), self.video_label.height(),
            Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        self.video_label.setPixmap(pix)
        self.capture_btn.setVisible(False)
        self.accept_btn.setVisible(True)
        self.retry_btn.setVisible(True)
        self.status_label.setText(icons.ok(tr("persons.captured_ok")))

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._camera is not None:
            self._camera.stop()
            self._camera = None
        super().closeEvent(event)


# --------------------------------------------------------------------------- #
# Guardado en segundo plano (crea la persona + procesa las fotos)
# --------------------------------------------------------------------------- #
class SavePersonWorker(QThread):
    progress = Signal(int, int)  # foto actual, total
    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, datos: dict, photo_paths: list[str], primary_path: str | None,
                 usuario: str | None, parent=None):
        super().__init__(parent)
        self.datos = datos
        self.photo_paths = photo_paths
        self.primary_path = primary_path
        self.usuario = usuario

    def run(self) -> None:  # noqa: D102
        try:
            with get_session() as session:
                service = PersonService(session)
                person = service.create_person(**self.datos, usuario=self.usuario)
                nombre_completo = person.nombre_completo
                added = 0
                errors: list[str] = []
                total = len(self.photo_paths)
                for i, path in enumerate(self.photo_paths, start=1):
                    self.progress.emit(i, total)
                    try:
                        service.add_photo_from_path(
                            person.uuid, path,
                            set_as_primary=(Path(path).resolve() == Path(self.primary_path).resolve()
                                            if self.primary_path else False),
                            usuario=self.usuario)
                        added += 1
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("No se pudo procesar {}: {}", path, exc)
                        errors.append(f"{Path(path).name}: {exc}")
            self.finished_ok.emit({
                "nombre": nombre_completo,
                "added": added,
                "total": total,
                "errors": errors,
            })
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error al registrar persona")
            self.failed.emit(str(exc))


# --------------------------------------------------------------------------- #
# Widget principal: registro de personas
# --------------------------------------------------------------------------- #
class PersonManagementWidget(QWidget):
    """Alta de personas: ficha de datos + dataset de fotografías (staging)."""

    def __init__(self, username: str | None = None, parent=None):
        super().__init__(parent)
        self.username = username
        self._staged: list[dict] = []  # [{"id": int, "path": str}]
        self._photo_cards: list[PhotoCard] = []
        self._photo_columns = 0
        self._seq = 0
        self.worker: SavePersonWorker | None = None
        self._build_ui()
        i18n_bus().languageChanged.connect(self._retranslate)

    def _retranslate(self) -> None:
        self._header_title.setText(tr("persons.title"))
        self._header_subtitle.setText(tr("persons.subtitle"))
        self._form_title.setText(tr("persons.data_title"))
        self._required_hint.setText(tr("persons.required_tip"))
        self.save_button.setText(tr("persons.save"))
        self.clear_button.setText(tr("persons.clear"))
        self._photos_title.setText(tr("persons.dataset_title"))
        self._capture_btn.setText(tr("persons.webcam"))
        self._add_btn.setText(tr("persons.add_photos_btn"))
        self._photos_hint.setText(tr("persons.photos_hint"))
        self._update_photo_count()
        self.sexo_combo.setItemText(1, tr("persons.male"))
        self.sexo_combo.setItemText(2, tr("persons.female"))
        self.sexo_combo.setItemText(3, tr("persons.other"))

    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)
        root.addLayout(self._build_header())

        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background-color: #1e1f26; }")
        splitter.addWidget(self._build_form_panel())
        splitter.addWidget(self._build_photos_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([440, 900])
        root.addWidget(splitter, stretch=1)

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(12)
        header.addWidget(icons.icon_label("person_add", 26, "#6fa8ff"))
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel(tr("persons.title"))
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        subtitle = QLabel(tr("persons.subtitle"))
        subtitle.setStyleSheet("color: #8f92a3; font-size: 12px;")
        self._header_title = title
        self._header_subtitle = subtitle
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header.addLayout(title_col)
        header.addStretch()
        return header

    # ------------------------------------------------------------------ #
    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text.upper())
        label.setStyleSheet(
            "color: #6fa8ff; font-size: 11px; font-weight: 700;"
            "letter-spacing: 1px; margin-top: 6px;"
        )
        return label

    def _build_form_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Card")
        frame.setMinimumWidth(360)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(8)

        form_title = QLabel(tr("persons.data_title"))
        form_title.setStyleSheet("font-size: 16px; font-weight: 700;")
        self._form_title = form_title
        layout.addWidget(form_title)

        required_hint = QLabel(tr("persons.required_tip"))
        required_hint.setStyleSheet("color: #8f92a3; font-size: 12px;")
        self._required_hint = required_hint
        layout.addWidget(required_hint)

        self.nombre_edit = QLineEdit()
        self.apellidos_edit = QLineEdit()
        self.alias_edit = QLineEdit()
        self.sexo_combo = QComboBox()
        self.sexo_combo.addItems(["", tr("persons.male"), tr("persons.female"), tr("persons.other")])
        self.edad_spin = QSpinBox()
        self.edad_spin.setRange(0, 120)

        layout.addWidget(self._section_label(tr("persons.identity")))
        id_form = QFormLayout()
        id_form.setSpacing(8)
        id_form.addRow(tr("persons.nombre") + " *", self.nombre_edit)
        id_form.addRow(tr("persons.apellidos") + " *", self.apellidos_edit)
        id_form.addRow(tr("persons.alias"), self.alias_edit)
        id_form.addRow(tr("persons.sexo"), self.sexo_combo)
        id_form.addRow(tr("persons.edad_aproximada"), self.edad_spin)
        layout.addLayout(id_form)

        self.empresa_edit = QLineEdit()
        self.departamento_edit = QLineEdit()
        self.cargo_edit = QLineEdit()

        layout.addWidget(self._section_label(tr("persons.work")))
        work_form = QFormLayout()
        work_form.setSpacing(8)
        work_form.addRow(tr("persons.empresa"), self.empresa_edit)
        work_form.addRow(tr("persons.departamento"), self.departamento_edit)
        work_form.addRow(tr("persons.cargo"), self.cargo_edit)
        layout.addLayout(work_form)

        self.telefono_edit = QLineEdit()
        self.correo_edit = QLineEdit()

        layout.addWidget(self._section_label(tr("persons.contact")))
        contact_form = QFormLayout()
        contact_form.setSpacing(8)
        contact_form.addRow(tr("persons.telefono"), self.telefono_edit)
        contact_form.addRow(tr("persons.correo"), self.correo_edit)
        layout.addLayout(contact_form)

        self.observaciones_edit = QTextEdit()
        self.observaciones_edit.setMaximumHeight(90)

        layout.addWidget(self._section_label(tr("persons.notes")))
        layout.addWidget(self.observaciones_edit)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.save_button = QPushButton(tr("persons.save"))
        self.save_button.setIcon(icons.icon("check_circle", 16, "#ffffff"))
        self.save_button.setCursor(Qt.PointingHandCursor)
        self.save_button.clicked.connect(self._on_save_person)
        buttons.addWidget(self.save_button, stretch=1)

        self.clear_button = QPushButton(tr("persons.clear"))
        self.clear_button.setObjectName("SecondaryButton")
        self.clear_button.setCursor(Qt.PointingHandCursor)
        self.clear_button.clicked.connect(self._confirm_clear)
        buttons.addWidget(self.clear_button)
        layout.addLayout(buttons)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        layout.addStretch()
        return frame

    def _build_photos_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel(tr("persons.dataset_title"))
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        self._photos_title = title
        header.addWidget(title)

        self.photo_count_label = QLabel(tr("persons.photos_none"))
        self.photo_count_label.setStyleSheet("color: #8f92a3;")
        header.addWidget(self.photo_count_label)
        header.addStretch()

        self._capture_btn = QPushButton(tr("persons.webcam"))
        self._capture_btn.setObjectName("SecondaryButton")
        self._capture_btn.setIcon(icons.icon("camera", 16, "#b7b9c4"))
        self._capture_btn.setCursor(Qt.PointingHandCursor)
        self._capture_btn.clicked.connect(self._capture_webcam)
        header.addWidget(self._capture_btn)

        self._add_btn = QPushButton(tr("persons.add_photos_btn"))
        self._add_btn.setObjectName("SecondaryButton")
        self._add_btn.setCursor(Qt.PointingHandCursor)
        self._add_btn.clicked.connect(self._pick_photos)
        header.addWidget(self._add_btn)
        layout.addLayout(header)

        self.photo_grid = PhotoGridWidget()
        self.photo_grid.files_dropped.connect(self._stage_photos)
        self.photo_grid.resized.connect(self._relayout_photos)

        self.photos_scroll = QScrollArea()
        self.photos_scroll.setWidgetResizable(True)
        self.photos_scroll.setFrameShape(QFrame.NoFrame)
        self.photos_scroll.setStyleSheet("QScrollArea { background-color: #16171c; }")
        self.photos_scroll.setWidget(self.photo_grid)
        layout.addWidget(self.photos_scroll, stretch=1)

        hint = QLabel(tr("persons.photos_hint"))
        hint.setStyleSheet("color: #8f92a3;")
        hint.setWordWrap(True)
        self._photos_hint = hint
        layout.addWidget(hint)

        return frame

    # ------------------------------------------------------------------ #
    # Staging de fotografías
    # ------------------------------------------------------------------ #
    def _pick_photos(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr("persons.pick_photos"), "",
            tr("persons.images_filter")
        )
        if paths:
            self._stage_photos(paths)

    def _capture_webcam(self) -> None:
        dialog = CapturePhotoDialog(self)
        if dialog.exec() == QDialog.Accepted and dialog.photo_path:
            self._stage_photos([dialog.photo_path])

    def _stage_photos(self, paths: list[str]) -> None:
        staged_paths = {Path(d["path"]).resolve() for d in self._staged}
        added = 0
        for p in paths:
            path = Path(p)
            if path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            resolved = path.resolve()
            if resolved in staged_paths:
                continue
            hay_principal = any(d.get("primary") for d in self._staged)
            self._staged.append({
                "id": self._seq, "path": str(path),
                "primary": not hay_principal,
            })
            self._seq += 1
            staged_paths.add(resolved)
            added += 1
        if added:
            self._render_photo_cards()
            self.status_label.setText(icons.ok(tr("persons.photos_added").format(added)))

    def _set_staged_primary(self, photo_id: int) -> None:
        for data in self._staged:
            data["primary"] = (data["id"] == photo_id)
        self._render_photo_cards()
        self.status_label.setText(icons.ok(tr("persons.primary_updated")))

    def _staged_by_id(self, photo_id: int) -> dict | None:
        return next((d for d in self._staged if d["id"] == photo_id), None)

    def _preview_photo(self, photo_id: int) -> None:
        data = self._staged_by_id(photo_id)
        if not data or not Path(data["path"]).exists():
            QMessageBox.warning(self, tr("persons.photo_unavailable"),
                                tr("persons.photo_unavailable_msg"))
            return
        PhotoPreviewDialog(data["path"], tr("persons.photo_dataset_title"), self).exec()

    def _delete_photo(self, photo_id: int) -> None:
        data = self._staged_by_id(photo_id)
        if not data:
            return
        nombre = Path(data["path"]).name
        resp = QMessageBox.question(
            self, tr("persons.remove_photo"),
            tr("persons.remove_photo_msg").format(nombre),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return
        self._staged = [d for d in self._staged if d["id"] != photo_id]
        if self._staged and not any(d.get("primary") for d in self._staged):
            self._staged[0]["primary"] = True
        self._cleanup_temp_file(data["path"])
        self._render_photo_cards()
        self.status_label.setText(icons.ok(tr("persons.photo_removed")))

    def _clear_staged(self) -> None:
        for data in self._staged:
            self._cleanup_temp_file(data["path"])
        self._staged.clear()
        self._render_photo_cards()

    @staticmethod
    def _cleanup_temp_file(path: str) -> None:
        """Elimina archivos temporales (captura webcam); nunca los originales."""
        try:
            temp_dir = Path(tempfile.gettempdir()).resolve()
            p = Path(path).resolve()
            if temp_dir in p.parents and p.exists():
                p.unlink(missing_ok=True)
        except OSError:
            pass

    # ------------------------------------------------------------------ #
    # Render de la rejilla de fotos en espera
    # ------------------------------------------------------------------ #
    def _update_photo_count(self) -> None:
        self.photo_count_label.setText(
            tr("persons.photos_none")
            if not self._staged
            else tr("persons.photos_count").format(len(self._staged))
        )

    def _render_photo_cards(self) -> None:
        self.photo_grid.clear_cards()
        self._photo_cards.clear()
        if not self._staged:
            self.photo_grid.show_empty()
            self._update_photo_count()
            return
        cols = self._photo_columns or 1
        for i, data in enumerate(self._staged):
            card = PhotoCard(
                photo_id=data["id"],
                thumb_path=data["path"],
                calidad_score=None,
                es_principal=bool(data.get("primary", i == 0)),
                show_primary_btn=True,
            )
            card.preview_requested.connect(self._preview_photo)
            card.primary_requested.connect(self._set_staged_primary)
            card.delete_requested.connect(self._delete_photo)
            self.photo_grid.grid.addWidget(card, i // cols, i % cols)
            self._photo_cards.append(card)
        self._update_photo_count()

    def _relayout_photos(self) -> None:
        available = self.photo_grid.width() - 24 - 12
        cols = max(1, available // (PHOTO_CARD_WIDTH + 10))
        if cols == self._photo_columns and self._photo_cards:
            return
        self._photo_columns = cols
        self._render_photo_cards()

    # ------------------------------------------------------------------ #
    # Limpieza del formulario
    # ------------------------------------------------------------------ #
    def _clear_form(self) -> None:
        self.nombre_edit.clear()
        self.apellidos_edit.clear()
        self.alias_edit.clear()
        self.sexo_combo.setCurrentIndex(0)
        self.edad_spin.setValue(0)
        self.empresa_edit.clear()
        self.departamento_edit.clear()
        self.cargo_edit.clear()
        self.telefono_edit.clear()
        self.correo_edit.clear()
        self.observaciones_edit.clear()
        self.nombre_edit.setStyleSheet("")
        self.apellidos_edit.setStyleSheet("")

    def _confirm_clear(self) -> None:
        has_content = bool(self._staged)
        if not has_content:
            for widget in (self.nombre_edit, self.apellidos_edit, self.alias_edit,
                           self.empresa_edit, self.departamento_edit,
                           self.cargo_edit, self.telefono_edit, self.correo_edit):
                if widget.text().strip():
                    has_content = True
                    break
            if not has_content and not self.observaciones_edit.toPlainText().strip():
                self.status_label.setText(tr("persons.form_empty"))
                return
        resp = QMessageBox.question(
            self, tr("persons.clear_confirm"),
            tr("persons.clear_confirm_msg"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return
        self._clear_form()
        self._clear_staged()
        self.progress_bar.setVisible(False)
        self.status_label.setText(tr("persons.form_cleared"))

    # ------------------------------------------------------------------ #
    # Guardado
    # ------------------------------------------------------------------ #
    @staticmethod
    def _mark_invalid(widget: QWidget, invalid: bool) -> None:
        widget.setStyleSheet("border: 1px solid #e85d5d;" if invalid else "")

    def _on_save_person(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        if self.save_button.isEnabled() is False:
            return

        nombre = self.nombre_edit.text().strip()
        apellidos = self.apellidos_edit.text().strip()

        nombre_ok = bool(nombre)
        apellidos_ok = bool(apellidos)
        self._mark_invalid(self.nombre_edit, not nombre_ok)
        self._mark_invalid(self.apellidos_edit, not apellidos_ok)
        if not nombre_ok or not apellidos_ok:
            (self.nombre_edit if not nombre_ok else self.apellidos_edit).setFocus()
            self.status_label.setText(icons.warn(tr("persons.name_required")))
            return

        correo = self.correo_edit.text().strip()
        if correo and not EMAIL_RE.match(correo):
            self._mark_invalid(self.correo_edit, True)
            self.status_label.setText(icons.warn(tr("persons.email_invalid")))
            return
        self._mark_invalid(self.correo_edit, False)

        if not self._staged:
            resp = QMessageBox.question(
                self, tr("persons.no_photos_title"),
                tr("persons.no_photos_msg"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
            )
            if resp != QMessageBox.Yes:
                return

        full = f"{nombre} {apellidos}".strip().lower()
        duplicados = []
        with get_session() as session:
            service = PersonService(session)
            duplicados = [
                p for p in service.search(f"{nombre} {apellidos}")
                if p.nombre_completo.strip().lower() == full
            ]
        if duplicados:
            resp = QMessageBox.question(
                self, tr("persons.duplicate_title"),
                tr("persons.duplicate_msg").format(duplicados[0].nombre_completo),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if resp != QMessageBox.Yes:
                return

        datos = dict(
            nombre=nombre,
            apellidos=apellidos,
            alias=self.alias_edit.text().strip() or None,
            sexo=self.sexo_combo.currentText() or None,
            edad_aproximada=self.edad_spin.value() or None,
            empresa=self.empresa_edit.text().strip() or None,
            departamento=self.departamento_edit.text().strip() or None,
            cargo=self.cargo_edit.text().strip() or None,
            telefono=self.telefono_edit.text().strip() or None,
            correo=correo or None,
            observaciones=self.observaciones_edit.toPlainText().strip() or None,
        )
        paths = [d["path"] for d in self._staged]
        primary = next(
            (d["path"] for d in self._staged if d.get("primary")),
            paths[0] if paths else None,
        )

        self.save_button.setEnabled(False)
        self.clear_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, max(1, len(paths)))
        self.progress_bar.setValue(0)
        self.status_label.setText(icons.warn(tr("persons.saving")))

        self.worker = SavePersonWorker(datos, paths, primary, self.username, self)
        self.worker.progress.connect(self._on_save_progress)
        self.worker.finished_ok.connect(self._on_save_finished)
        self.worker.failed.connect(self._on_save_failed)
        self.worker.start()

    def _on_save_progress(self, current: int, total: int) -> None:
        if total > 0:
            self.progress_bar.setValue(current)
            self.status_label.setText(
                icons.warn(tr("persons.processing_photo").format(current, total)))

    def _on_save_finished(self, result: dict) -> None:
        self.save_button.setEnabled(True)
        self.clear_button.setEnabled(True)
        self.progress_bar.setVisible(False)

        resumen = tr("persons.saved_resumen").format(
            result['nombre'], result['added'], result['total']
        )
        if result["errors"]:
            detalles = "\n".join(result["errors"][:8])
            mas = f"\n(+{len(result['errors']) - 8} más)" if len(result["errors"]) > 8 else ""
            self.status_label.setText(
                icons.ok(resumen) + "<br><br>" + icons.warn(
                    tr("persons.rejected")) +
                f"<br>{detalles}{mas}"
            )
        else:
            self.status_label.setText(icons.ok(resumen))

        self._clear_form()
        self._clear_staged()

    def _on_save_failed(self, message: str) -> None:
        self.save_button.setEnabled(True)
        self.clear_button.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setText(icons.err(tr("persons.save_failed").format(message)))

    # ------------------------------------------------------------------ #
    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout_photos()
