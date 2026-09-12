from __future__ import annotations

import time
from datetime import datetime
from math import ceil
from pathlib import Path

import cv2
import numpy as np

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import (
    QBrush, QColor, QDragEnterEvent, QDropEvent, QFont, QIcon, QImage,
    QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QLabel, QFrame, QFileDialog, QHeaderView, QMessageBox,
    QTabWidget, QSplitter, QScrollArea, QGridLayout, QComboBox, QSizePolicy,
    QProgressBar, QTextEdit, QSpinBox, QAbstractSpinBox,
)

from app.core.config import settings
from app.core.exceptions import NoFaceDetectedError
from app.core.logger import logger, audit_logger
from app.core.permissions import PERM_ADMIN, PERM_PERSONAS
from app.database.session import get_session
from app.gui import icons
from app.gui.widgets.person_registration import (
    EMAIL_RE, PHOTO_CARD_WIDTH, PHOTO_CARD_HEIGHT, PhotoCard, PhotoGridWidget,
    PhotoPreviewDialog,
)
from app.i18n import bus as i18n_bus, tr
from app.recognition.matcher import compare_pair
from app.recognition.recognition_service import RecognitionService
from app.services.export_service import build_export_name
from app.services.person_service import PersonService
from app.services.statistics_service import attrs_from_json, primary_embedding_attrs
from app.vision.face_attributes import (
    ATTR_FIELDS, EYE_COLOR_LABELS, HAIR_COLOR_LABELS, FaceAttributes,
)
from app.vision.face_engine import FaceEngine

ATTR_LABEL_KEYS = {
    "gafas": "attrs.glasses",
    "mascarilla": "attrs.mask",
    "barba": "attrs.beard",
    "bigote": "attrs.mustache",
    "sonrisa": "attrs.smile",
    "ojos_abiertos": "attrs.eyes_open",
}

ATTR_AGEN_KEYS = {
    "edad": "attrs.age",
    "genero": "attrs.gender",
}

ATTR_COLOR_KEYS = {
    "color_ojos": "attrs.eye_color",
    "color_pelo": "attrs.hair_color",
}


def _attrs_present_text(attrs: FaceAttributes | None) -> str:
    """Línea resumen: atributos presentes en un rostro (para vista previa/ficha)."""
    if attrs is None:
        return ""
    present = [tr(ATTR_LABEL_KEYS[f]) for f in ATTR_FIELDS if getattr(attrs, f)]
    return tr("attrs.summary").format(", ".join(present)) if present else tr("attrs.none_hint")

# --------------------------------------------------------------------------- #
# Módulo: Búsqueda inteligente (por texto o por foto)
# --------------------------------------------------------------------------- #


def _primary_thumbnail(person) -> str | None:
    """Ruta de la miniatura de la foto principal de una persona (o de la primera)."""
    if person.photos:
        primary = next((p for p in person.photos if p.es_principal), person.photos[0])
        return primary.thumbnail_path or primary.file_path
    return None


# Etiqueta visible de cada campo informativo (lectura) -> clave del dict `datos` en _load_user.
DETAIL_FIELD_KEYS = {
    "Fotos": "fotos",
    "Embeddings": "embeddings",
    "Registrado": "registrado",
    "Última modificación": "modificacion",
}


class PhotoSearchWorker(QThread):
    """Busca la persona más parecida a una imagen, en segundo plano."""

    step = Signal(str)
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, image_path: str, usuario: str | None = None, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.usuario = usuario

    def run(self) -> None:  # noqa: D102
        try:
            self.step.emit("Leyendo imagen de búsqueda...")
            image = cv2.imread(self.image_path)
            if image is None:
                raise ValueError("No se pudo leer la imagen seleccionada.")

            self.step.emit("Detectando el rostro más relevante...")
            face = FaceEngine.instance().largest_face(image)
            if face is None:
                raise NoFaceDetectedError(
                    "No se detectó ningún rostro en la imagen. Usa una foto frontal y nítida."
                )

            self.step.emit("Comparando contra la base biométrica (1:N)...")
            with get_session() as session:
                rec_service = RecognitionService(session)
                person_service = PersonService(session)
                candidates = rec_service.search_similar(
                    image, top_k=settings.recognition.top_k_results,
                    log_event=True, usuario=self.usuario,
                )

                best_by_person: dict[str, dict] = {}
                for cand in candidates:
                    persona = person_service.get(cand.person_uuid)
                    if persona is None:
                        continue
                    prev = best_by_person.get(cand.person_uuid)
                    if prev is None or cand.confidence_pct > prev["similitud"]:
                        best_by_person[cand.person_uuid] = {
                            "persona": persona,
                            "similitud": cand.confidence_pct,
                            "distancia": cand.distance,
                            "match": cand.is_match,
                        }

                rows = []
                for entry in sorted(best_by_person.values(),
                                    key=lambda e: e["similitud"], reverse=True):
                    p = entry["persona"]
                    rows.append({
                        "uuid": p.uuid,
                        "nombre": p.nombre_completo,
                        "alias": p.alias or "",
                        "empresa": p.empresa or "",
                        "cargo": p.cargo or "",
                        "correo": p.correo or "",
                        "thumb": _primary_thumbnail(p),
                        "similitud": entry["similitud"],
                        "distancia": entry["distancia"],
                        "match": entry["match"],
                    })

            self.finished_ok.emit({"image": image, "face": face, "rows": rows})
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class PhotoPickerCard(QFrame):
    """Tarjeta para seleccionar (clic o arrastre) la fotografía de búsqueda."""

    image_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setStyleSheet("PhotoPickerCard { background-color: #16171c; }")
        self.setAcceptDrops(True)
        self.setMinimumHeight(230)
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        self.icon_label = icons.icon_label("crop_free", 36, "#3f4250")
        self.icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.icon_label, alignment=Qt.AlignCenter)

        self.label = QLabel("Haz clic o arrastra aquí la fotografía de búsqueda")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("color: #8f92a3;")
        self.label.setWordWrap(True)
        layout.addWidget(self.label)

    def set_image(self, pix: QPixmap) -> None:
        self.icon_label.hide()
        max_w = max(240, self.width() - 28)
        scaled = pix.scaled(max_w, 320, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.label.setPixmap(scaled)
        self.label.setAlignment(Qt.AlignCenter)

    def clear(self) -> None:
        self.icon_label.show()
        self.label.setPixmap(QPixmap())
        self.label.setText("Haz clic o arrastra aquí la fotografía de búsqueda")
        self.label.setAlignment(Qt.AlignCenter)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.image_selected.emit("__pick__")
        super().mousePressEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        image_paths = [p for p in paths if Path(p).suffix.lower() in
                       (".jpg", ".jpeg", ".png", ".bmp", ".webp")]
        if image_paths:
            self.image_selected.emit(image_paths[0])


class PersonSearchWidget(QWidget):
    """Módulo 'Búsqueda de personas' — por texto o por fotografía, con ficha dedicada."""

    def __init__(self, username: str | None = None, permisos: set[str] | None = None, parent=None):
        super().__init__(parent)
        self.username = username
        self.permisos = set(permisos or [])
        self._can_edit = "*" in self.permisos or PERM_PERSONAS in self.permisos
        self._can_delete = self._can_edit and ("*" in self.permisos or PERM_ADMIN in self.permisos)
        self._results = None
        self._detail_uuid: str | None = None
        self._query_path: str | None = None
        self._photo_worker: PhotoSearchWorker | None = None
        self._detail_photo_data: list[dict] = []
        self._detail_photo_cards: list[PhotoCard] = []
        self._detail_photo_columns = 0
        self._detail_photo_rev = 0
        self._detail_photo_rendered_rev = -1
        self._detail_info: dict[str, QLabel] = {}
        self._detail_editing = False

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._search_text)

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(600)
        self._autosave_timer.timeout.connect(self._save_person_details)

        self._build_ui()
        self._reset_detail()
        self._load_empresas()
        self._search_text()
        i18n_bus().languageChanged.connect(self._retranslate)

    def _retranslate(self) -> None:
        self._title.setText(tr("search.title"))
        self._subtitle.setText(tr("search.subtitle"))
        self.tabs.setTabText(0, tr("search.tab_text"))
        self.tabs.setTabText(1, tr("search.tab_photo"))
        self._results_title.setText(tr("search.results"))
        self.search_edit.setPlaceholderText(tr("search.placeholder"))
        self._search_btn.setText(tr("common.search"))
        self._clear_btn.setText(tr("common.clear"))
        self._all_btn.setText(tr("search.show_all"))
        self.photo_search_btn.setText(tr("search.search_photo"))
        self.photo_clear_btn.setText(tr("search.clear_photo"))
        self.results_table.setHorizontalHeaderLabels(
            [tr("search.img"), tr("search.result_name"), tr("persons.alias"),
             tr("persons.empresa"), tr("search.result_match"), tr("search.result_state")])
        if hasattr(self, "_attr_name_items"):
            for field, name in self._attr_name_items.items():
                name.setText(tr(ATTR_LABEL_KEYS[field]))
        self._retranslate_attrs_placeholder()
        for combo in (getattr(self, "attrs_present_combo", None),
                      getattr(self, "attrs_absent_combo", None)):
            if combo is not None:
                idx = combo.currentIndex()
                self._fill_attr_combo(combo)
                combo.setCurrentIndex(min(idx, combo.count() - 1))

    # ------------------------------------------------------------------ #
    def _retranslate_attrs_placeholder(self) -> None:
        if hasattr(self, "_attr_placeholder"):
            self._attr_placeholder.setText(tr("attrs.placeholder"))

    # ------------------------------------------------------------------ #
    def _set_attribute_ui(self, attrs: FaceAttributes | None) -> None:
        """Refresca el panel de análisis facial extendido de la ficha."""
        if not hasattr(self, "_attr_items"):
            return
        if attrs is None:
            self._attr_placeholder.setText(tr("attrs.placeholder"))
            self._attr_placeholder.setVisible(True)
            for field in list(ATTR_FIELDS) + ["edad", "genero", "color_ojos", "color_pelo"]:
                label = self._attr_items[field]
                label.setText("—")
                label.setStyleSheet("color: #6b6e7d; font-size: 12px;")
            return
        self._attr_placeholder.setVisible(False)
        for field in ATTR_FIELDS:
            label = self._attr_items[field]
            present = bool(getattr(attrs, field))
            label.setText(tr("attrs.yes") if present else tr("attrs.no"))
            label.setStyleSheet(
                "color: #2ecc71; font-size: 12px;" if present
                else "color: #6b6e7d; font-size: 12px;")
        edad = attrs.edad
        self._attr_items["edad"].setText(str(edad) if edad else "—")
        genero = attrs.genero
        genero_text = ("attrs.gender_male" if genero == "M"
                       else "attrs.gender_female") if genero in ("M", "F") else None
        self._attr_items["genero"].setText(tr(genero_text) if genero_text else "—")
        for key in ATTR_COLOR_KEYS:
            color = getattr(attrs, key)
            self._attr_items[key].setText(color if color else "—")
        for key in ("edad", "genero", "color_ojos", "color_pelo"):
            self._attr_items[key].setStyleSheet("color: #e6e6e6; font-size: 12px;")
        for key in ATTR_COLOR_KEYS:
            color = getattr(attrs, key)
            if color is None:
                self._attr_items[key].setStyleSheet("color: #6b6e7d; font-size: 12px;")
            else:
                self._attr_items[key].setStyleSheet("color: #e6e6e6; font-size: 12px;")

    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        header = QHBoxLayout()
        header.addWidget(icons.icon_label("search", 22, "#6fa8ff"))
        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        self._title = QLabel(tr("search.title"))
        self._title.setStyleSheet("font-size: 22px; font-weight: 700;")
        self._subtitle = QLabel(tr("search.subtitle"))
        self._subtitle.setStyleSheet("color: #8f92a3; font-size: 12px;")
        title_col.addWidget(self._title)
        title_col.addWidget(self._subtitle)
        header.addLayout(title_col)
        header.addStretch()
        root.addLayout(header)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background-color: #1e1f26; }")
        splitter.addWidget(self._build_search_panel())
        splitter.addWidget(self._build_detail_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)
        root.addWidget(splitter, stretch=1)

    # ------------------------------------------------------------------ #
    # Panel de búsqueda
    # ------------------------------------------------------------------ #
    def _build_search_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Card")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_text_tab(), tr("search.tab_text"))
        self.tabs.addTab(self._build_photo_tab(), tr("search.tab_photo"))
        lay.addWidget(self.tabs)

        results_header = QHBoxLayout()
        self._results_title = QLabel(tr("search.results"))
        self._results_title.setStyleSheet("font-weight: 700; font-size: 15px;")
        results_header.addWidget(self._results_title)
        self.results_count_label = QLabel("0")
        self.results_count_label.setStyleSheet("color: #8f92a3;")
        results_header.addWidget(self.results_count_label)
        results_header.addStretch()
        lay.addLayout(results_header)

        self.results_table = QTableWidget(0, 6)
        self.results_table.setHorizontalHeaderLabels(
            [tr("search.img"), tr("search.result_name"), tr("persons.alias"),
             tr("persons.empresa"), tr("search.result_match"), tr("search.result_state")])
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.verticalHeader().setDefaultSectionSize(40)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setIconSize(QSize(34, 34))
        self.results_table.cellClicked.connect(self._on_result_clicked)
        self.results_table.setMinimumHeight(300)
        lay.addWidget(self.results_table, stretch=1)
        return frame

    def _build_text_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 10, 8, 8)
        lay.setSpacing(10)

        row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(tr("search.placeholder"))
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._schedule_search)
        self.search_edit.returnPressed.connect(self._search_text)
        row.addWidget(self.search_edit, stretch=1)

        self._search_btn = QPushButton(tr("common.search"))
        self._search_btn.setIcon(icons.icon("search", 16, "#ffffff"))
        self._search_btn.clicked.connect(self._search_text)
        row.addWidget(self._search_btn)

        self._clear_btn = QPushButton(tr("common.clear"))
        self._clear_btn.setObjectName("SecondaryButton")
        self._clear_btn.setIcon(icons.icon("close", 14, "#b7b9c4"))
        self._clear_btn.clicked.connect(self._clear_search)
        row.addWidget(self._clear_btn)
        lay.addLayout(row)

        filter_row = QHBoxLayout()
        self.empresa_combo = QComboBox()
        self.empresa_combo.currentIndexChanged.connect(self._schedule_search)
        filter_row.addWidget(self.empresa_combo, stretch=1)

        self._all_btn = QPushButton(tr("search.show_all"))
        self._all_btn.setObjectName("SecondaryButton")
        self._all_btn.clicked.connect(self._show_all)
        filter_row.addWidget(self._all_btn)
        lay.addLayout(filter_row)

        attr_filter_row = QHBoxLayout()
        present_label = QLabel(tr("search.filter_present"))
        present_label.setStyleSheet("color: #8f92a3; font-size: 12px;")
        attr_filter_row.addWidget(present_label)
        self.attrs_present_combo = QComboBox()
        self._fill_attr_combo(self.attrs_present_combo)
        self.attrs_present_combo.currentIndexChanged.connect(self._schedule_search)
        attr_filter_row.addWidget(self.attrs_present_combo)

        absent_label = QLabel(tr("search.filter_absent"))
        absent_label.setStyleSheet("color: #8f92a3; font-size: 12px;")
        attr_filter_row.addWidget(absent_label)
        self.attrs_absent_combo = QComboBox()
        self._fill_attr_combo(self.attrs_absent_combo)
        self.attrs_absent_combo.currentIndexChanged.connect(self._schedule_search)
        attr_filter_row.addWidget(self.attrs_absent_combo)
        attr_filter_row.addStretch()
        lay.addLayout(attr_filter_row)

        color_filter_row = QHBoxLayout()
        self._color_combos: dict[str, QComboBox] = {}
        for field in ATTR_COLOR_KEYS:
            label = QLabel(tr(ATTR_COLOR_KEYS[field]))
            label.setStyleSheet("color: #8f92a3; font-size: 12px;")
            color_filter_row.addWidget(label)
            combo = QComboBox()
            self._fill_color_combo(combo, field)
            combo.currentIndexChanged.connect(self._schedule_search)
            color_filter_row.addWidget(combo)
            self._color_combos[field] = combo
        color_filter_row.addStretch()
        lay.addLayout(color_filter_row)
        lay.addStretch()
        return w

    def _fill_attr_combo(self, combo: QComboBox) -> None:
        combo.addItem(tr("search.attr_any"), "")
        for field in ATTR_FIELDS:
            combo.addItem(tr(ATTR_LABEL_KEYS[field]), field)

    def _fill_color_combo(self, combo: QComboBox, field: str) -> None:
        combo.addItem(tr("search.color_any"), "")
        labels = (EYE_COLOR_LABELS if field == "color_ojos" else HAIR_COLOR_LABELS)
        for label in labels:
            combo.addItem(label, label)

    def _build_photo_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 10, 8, 8)
        lay.setSpacing(10)

        self.photo_picker = PhotoPickerCard()
        self.photo_picker.image_selected.connect(self._on_query_image)
        lay.addWidget(self.photo_picker, stretch=1)

        self.photo_file_label = QLabel("")
        self.photo_file_label.setStyleSheet("color: #6b6e7d; font-size: 12px;")
        self.photo_file_label.setWordWrap(True)
        lay.addWidget(self.photo_file_label)

        self.photo_search_btn = QPushButton(tr("search.search_photo"))
        self.photo_search_btn.setIcon(icons.icon("scan", 16, "#ffffff"))
        self.photo_search_btn.setEnabled(False)
        self.photo_search_btn.clicked.connect(self._start_photo_search)
        lay.addWidget(self.photo_search_btn)

        self.photo_status_label = QLabel("")
        self.photo_status_label.setStyleSheet("color: #8f92a3;")
        self.photo_status_label.setWordWrap(True)
        lay.addWidget(self.photo_status_label)

        self.photo_clear_btn = QPushButton(tr("search.clear_photo"))
        self.photo_clear_btn.setObjectName("SecondaryButton")
        self.photo_clear_btn.setIcon(icons.icon("close", 14, "#b7b9c4"))
        self.photo_clear_btn.setEnabled(False)
        self.photo_clear_btn.clicked.connect(self._clear_photo)
        lay.addWidget(self.photo_clear_btn)
        lay.addStretch()
        return w

    # ------------------------------------------------------------------ #
    # Panel de detalle (ficha dedicada de la persona)
    # ------------------------------------------------------------------ #
    def _build_detail_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Card")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        top = QHBoxLayout()
        self.avatar_label = QLabel()
        self.avatar_label.setFixedSize(96, 96)
        self.avatar_label.setAlignment(Qt.AlignCenter)
        self.avatar_label.setStyleSheet("background-color: #1a1b21; border-radius: 12px;")
        self.avatar_label.setPixmap(icons.pixmap("person", 44, "#8f92a3"))
        top.addWidget(self.avatar_label)

        name_col = QVBoxLayout()
        name_col.setSpacing(4)
        self.detail_name_label = QLabel("Selecciona una persona")
        self.detail_name_label.setStyleSheet("font-size: 18px; font-weight: 700;")
        self.detail_name_label.setWordWrap(True)
        name_col.addWidget(self.detail_name_label)
        self.detail_subtitle_label = QLabel(
            "Usa los resultados de la búsqueda para ver la ficha completa.")
        self.detail_subtitle_label.setStyleSheet("color: #8f92a3; font-size: 12px;")
        self.detail_subtitle_label.setWordWrap(True)
        name_col.addWidget(self.detail_subtitle_label)
        top.addLayout(name_col, stretch=1)

        self.detail_edit_btn = QPushButton()
        self.detail_edit_btn.setObjectName("SecondaryButton")
        self.detail_edit_btn.setText("Editar")
        self.detail_edit_btn.setIcon(icons.icon("edit", 15, "#b7b9c4"))
        self.detail_edit_btn.setEnabled(False)
        self.detail_edit_btn.clicked.connect(self._enable_edition)
        top.addWidget(self.detail_edit_btn)
        lay.addLayout(top)

        self.detail_editor_card = QFrame()
        self.detail_editor_card.setObjectName("Card")
        editor_lay = QVBoxLayout(self.detail_editor_card)
        editor_lay.setContentsMargins(12, 12, 12, 12)
        editor_lay.setSpacing(10)

        self.detail_status = QLabel("Edición en tiempo real activada.")
        self.detail_status.setWordWrap(True)
        self.detail_status.setStyleSheet("color: #8f92a3; font-size: 12px;")
        editor_lay.addWidget(self.detail_status)

        form_lay = QGridLayout()
        form_lay.setHorizontalSpacing(18)
        form_lay.setVerticalSpacing(8)

        def put(form, row: int, col: int, label: str, widget: QWidget) -> None:
            lab = QLabel(label)
            lab.setStyleSheet("color: #8f92a3; font-size: 12px;")
            lab.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            form.addWidget(lab, row * 2, col, alignment=Qt.AlignTop)
            form.addWidget(widget, row * 2 + 1, col)

        self.det_nombre = QLineEdit()
        self.det_apellidos = QLineEdit()
        put(form_lay, 0, 0, "Nombre *", self.det_nombre)
        put(form_lay, 0, 1, "Apellidos *", self.det_apellidos)

        self.det_alias = QLineEdit()
        self.det_sexo = QComboBox()
        self.det_sexo.setEditable(True)
        self.det_sexo.addItems(["", "Masculino", "Femenino", "Otro"])
        self.det_edad = QSpinBox()
        self.det_edad.setRange(0, 120)
        put(form_lay, 1, 0, "Alias", self.det_alias)
        put(form_lay, 1, 1, "Sexo", self.det_sexo)

        self.det_edad_lab = QLabel("Edad aprox.")
        self.det_edad_lab.setStyleSheet("color: #8f92a3; font-size: 12px;")
        form_lay.addWidget(self.det_edad_lab, 4, 0, alignment=Qt.AlignTop)
        form_lay.addWidget(self.det_edad, 5, 0)

        self.det_empresa = QLineEdit()
        put(form_lay, 2, 1, "Empresa", self.det_empresa)
        self.det_departamento = QLineEdit()
        put(form_lay, 3, 0, "Departamento", self.det_departamento)
        self.det_cargo = QLineEdit()
        put(form_lay, 3, 1, "Cargo", self.det_cargo)
        self.det_telefono = QLineEdit()
        put(form_lay, 4, 0, "Teléfono", self.det_telefono)
        self.det_correo = QLineEdit()
        put(form_lay, 4, 1, "Correo", self.det_correo)
        editor_lay.addLayout(form_lay)

        self.det_observaciones = QTextEdit()
        self.det_observaciones.setMaximumHeight(80)
        self.det_observaciones.setPlaceholderText("Observaciones...")
        editor_lay.addWidget(self.det_observaciones)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.save_detail_btn = QPushButton("Guardar cambios")
        self.save_detail_btn.setIcon(icons.icon("check_circle", 16, "#ffffff"))
        self.save_detail_btn.clicked.connect(self._save_person_details)
        btn_row.addWidget(self.save_detail_btn, stretch=1)
        self.cancel_detail_btn = QPushButton("Descartar")
        self.cancel_detail_btn.setObjectName("SecondaryButton")
        self.cancel_detail_btn.clicked.connect(self._disable_edition)
        btn_row.addWidget(self.cancel_detail_btn)
        editor_lay.addLayout(btn_row)
        lay.addWidget(self.detail_editor_card)

        fields_card = QFrame()
        fields_card.setObjectName("Card")
        fields_lay = QGridLayout(fields_card)
        fields_lay.setContentsMargins(14, 12, 14, 12)
        fields_lay.setHorizontalSpacing(20)
        fields_lay.setVerticalSpacing(8)

        def add_field(row: int, col: int, key: str) -> None:
            k = QLabel(key)
            k.setStyleSheet("color: #8f92a3; font-size: 12px;")
            v = QLabel("—")
            v.setStyleSheet("color: #e6e6e6; font-size: 13px;")
            v.setWordWrap(True)
            fields_lay.addWidget(k, row * 2, col, alignment=Qt.AlignTop)
            fields_lay.addWidget(v, row * 2 + 1, col, alignment=Qt.AlignTop)
            self._detail_info[key] = v

        add_field(0, 0, "Fotos")
        add_field(0, 1, "Embeddings")
        add_field(1, 0, "Registrado")
        add_field(1, 1, "Última modificación")
        lay.addWidget(fields_card)

        attrs_card = QFrame()
        attrs_card.setObjectName("Card")
        attrs_lay = QVBoxLayout(attrs_card)
        attrs_lay.setContentsMargins(14, 12, 14, 12)
        attrs_lay.setSpacing(6)
        attrs_title = QLabel(tr("attrs.title"))
        attrs_title.setStyleSheet("font-size: 13px; font-weight: 700;")
        attrs_lay.addWidget(attrs_title)
        self._attr_placeholder = QLabel(tr("attrs.placeholder"))
        self._attr_placeholder.setWordWrap(True)
        self._attr_placeholder.setStyleSheet("color: #6b6e7d; font-size: 12px;")
        attrs_lay.addWidget(self._attr_placeholder)
        self._attr_items: dict[str, QLabel] = {}
        self._attr_name_items: dict[str, QLabel] = {}
        attr_grid = QGridLayout()
        attr_grid.setHorizontalSpacing(12)
        attr_grid.setVerticalSpacing(4)
        for i, field in enumerate(ATTR_FIELDS):
            name = QLabel(tr(ATTR_LABEL_KEYS[field]))
            name.setStyleSheet("color: #8f92a3; font-size: 12px;")
            value = QLabel("—")
            value.setStyleSheet("color: #e6e6e6; font-size: 12px;")
            attr_grid.addWidget(name, i // 2, (i % 2) * 2, alignment=Qt.AlignRight)
            attr_grid.addWidget(value, i // 2, (i % 2) * 2 + 1)
            self._attr_name_items[field] = name
            self._attr_items[field] = value
        for i, key in enumerate(("edad", "genero"), start=len(ATTR_FIELDS)):
            name = QLabel(tr(ATTR_AGEN_KEYS[key]))
            name.setStyleSheet("color: #8f92a3; font-size: 12px;")
            value = QLabel("—")
            value.setStyleSheet("color: #e6e6e6; font-size: 12px;")
            attr_grid.addWidget(name, i // 2, (i % 2) * 2, alignment=Qt.AlignRight)
            attr_grid.addWidget(value, i // 2, (i % 2) * 2 + 1)
            self._attr_name_items[key] = name
            self._attr_items[key] = value
        for i, key in enumerate(ATTR_COLOR_KEYS, start=len(ATTR_FIELDS) + 2):
            name = QLabel(tr(ATTR_COLOR_KEYS[key]))
            name.setStyleSheet("color: #8f92a3; font-size: 12px;")
            value = QLabel("—")
            value.setStyleSheet("color: #e6e6e6; font-size: 12px;")
            attr_grid.addWidget(name, i // 2, (i % 2) * 2, alignment=Qt.AlignRight)
            attr_grid.addWidget(value, i // 2, (i % 2) * 2 + 1)
            self._attr_name_items[key] = name
            self._attr_items[key] = value
        attrs_lay.addLayout(attr_grid)
        lay.addWidget(attrs_card)

        photos_header = QHBoxLayout()
        photos_title = QLabel("Fotografías (dataset)")
        photos_title.setStyleSheet("font-size: 15px; font-weight: 700;")
        photos_header.addWidget(photos_title)
        self.detail_photo_count = QLabel("0 fotos")
        self.detail_photo_count.setStyleSheet("color: #8f92a3;")
        photos_header.addWidget(self.detail_photo_count)
        photos_header.addStretch()
        self.add_photos_btn = QPushButton("+ Añadir fotos")
        self.add_photos_btn.setObjectName("SecondaryButton")
        self.add_photos_btn.setEnabled(False)
        self.add_photos_btn.clicked.connect(self._pick_photos)
        photos_header.addWidget(self.add_photos_btn)

        self.clear_photos_btn = QPushButton("Limpiar dataset")
        self.clear_photos_btn.setObjectName("SecondaryButton")
        self.clear_photos_btn.setEnabled(False)
        self.clear_photos_btn.clicked.connect(self._clear_photo_dataset)
        photos_header.addWidget(self.clear_photos_btn)
        lay.addLayout(photos_header)

        self.photo_grid = PhotoGridWidget()
        self.photo_grid.files_dropped.connect(self._add_photos)
        self.photo_grid.resized.connect(self._relayout_detail_photos)
        self.photos_scroll = QScrollArea()
        self.photos_scroll.setWidgetResizable(True)
        self.photos_scroll.setFrameShape(QFrame.NoFrame)
        self.photos_scroll.setStyleSheet("QScrollArea { background-color: #16171c; }")
        self.photos_scroll.setWidget(self.photo_grid)
        self.photos_scroll.setMinimumHeight(PHOTO_CARD_HEIGHT + 24)
        lay.addWidget(self.photos_scroll, stretch=0)

        hint = QLabel(
            "Clic en una miniatura para verla en grande. La estrella marca la foto principal. "
            "El dataset se muestra en rejilla de 3 columnas; si hay más de 3 filas, "
            "se desplaza dentro del propio contenedor.")
        hint.setStyleSheet("color: #6b6e7d; font-size: 11px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        lay.addSpacing(6)
        self.delete_person_btn = QPushButton("Eliminar persona")
        self.delete_person_btn.setObjectName("DangerButton")
        self.delete_person_btn.setIcon(icons.icon("delete", 16, "#ffffff"))
        self.delete_person_btn.setEnabled(False)
        self.delete_person_btn.setToolTip(
            "Elimina definitivamente a la persona y su dataset de fotografías.")
        self.delete_person_btn.clicked.connect(self._delete_person)
        lay.addWidget(self.delete_person_btn)
        lay.addStretch()

        # C1: ocultar acciones de escritura a quienes no tienen el permiso.
        if not self._can_edit:
            self.detail_edit_btn.hide()
            self.add_photos_btn.hide()
            self.clear_photos_btn.hide()
        if not self._can_delete:
            self.delete_person_btn.hide()

        self._connect_detail_signals()

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet("QScrollArea { background-color: transparent; }")
        scroll_area.setWidget(frame)
        return scroll_area

    def _connect_detail_signals(self) -> None:
        """Empata cada campo editable a un guardado automático en tiempo real (600 ms)."""
        self.det_nombre.textChanged.connect(self._on_detail_edited)
        self.det_apellidos.textChanged.connect(self._on_detail_edited)
        self.det_alias.textChanged.connect(self._on_detail_edited)
        self.det_sexo.currentTextChanged.connect(self._on_detail_edited)
        self.det_edad.valueChanged.connect(self._on_detail_edited)
        self.det_empresa.textChanged.connect(self._on_detail_edited)
        self.det_departamento.textChanged.connect(self._on_detail_edited)
        self.det_cargo.textChanged.connect(self._on_detail_edited)
        self.det_telefono.textChanged.connect(self._on_detail_edited)
        self.det_correo.textChanged.connect(self._on_detail_edited)
        self.det_observaciones.textChanged.connect(self._on_detail_edited)

    def _on_detail_edited(self, _value=None) -> None:
        if not self._detail_uuid or not self.detail_editor_card.isVisible():
            return
        if getattr(self, "_populating", False):
            return
        self.detail_status.setText("Guardando…")
        self._autosave_timer.start()

    def _flush_autosave(self) -> None:
        if self._autosave_timer.isActive():
            self._autosave_timer.stop()
            self._save_person_details()

    # ------------------------------------------------------------------ #
    # Búsqueda por texto
    # ------------------------------------------------------------------ #
    def _load_empresas(self) -> None:
        selected = self.empresa_combo.currentData() if hasattr(self, "empresa_combo") else None
        with get_session() as session:
            service = PersonService(session)
            empresas = service.list_empresas()
        self.empresa_combo.blockSignals(True)
        self.empresa_combo.clear()
        self.empresa_combo.addItem("Todas las empresas", None)
        for e in empresas:
            self.empresa_combo.addItem(e, e)
        if selected is not None:
            idx = self.empresa_combo.findData(selected)
            if idx >= 0:
                self.empresa_combo.setCurrentIndex(idx)
        self.empresa_combo.blockSignals(False)

    def _schedule_search(self) -> None:
        self._search_timer.start()

    def _show_all(self) -> None:
        self.search_edit.clear()
        for combo in (self.attrs_present_combo, self.attrs_absent_combo,
                      *self._color_combos.values()):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self._search_text()

    def _clear_search(self) -> None:
        """Limpia el buscador de texto, el filtro, la foto y los resultados."""
        self._search_timer.stop()
        self.search_edit.blockSignals(True)
        self.search_edit.clear()
        self.search_edit.blockSignals(False)
        self.empresa_combo.blockSignals(True)
        self.empresa_combo.setCurrentIndex(0)
        self.empresa_combo.blockSignals(False)
        for combo_name in ("attrs_present_combo", "attrs_absent_combo"):
            combo = getattr(self, combo_name, None)
            if combo is not None:
                combo.blockSignals(True)
                combo.setCurrentIndex(0)
                combo.blockSignals(False)
        for combo in getattr(self, "_color_combos", {}).values():
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self._fill_results([])
        self._reset_detail()

    def _reset_detail(self) -> None:
        """Restaura la ficha de detalle a su estado vacío inicial."""
        self._detail_uuid = None
        if self._autosave_timer.isActive():
            self._autosave_timer.stop()
        self.detail_name_label.setText("Selecciona una persona")
        self.detail_subtitle_label.setText(
            "Usa los resultados de la búsqueda para ver la ficha completa.")
        self.detail_edit_btn.setEnabled(False)
        self.detail_edit_btn.setVisible(False)
        self._set_editing(False)
        self._set_avatar(None)
        for key, label in self._detail_info.items():
            label.setText("—")
        self._set_detail_photos([])
        self._set_attribute_ui(None)
        self.add_photos_btn.setEnabled(False)
        self.clear_photos_btn.setEnabled(False)
        self.delete_person_btn.setEnabled(False)

    def _search_text(self) -> None:
        self._search_timer.stop()
        query = self.search_edit.text().strip()
        empresa = self.empresa_combo.currentData()
        present = self.attrs_present_combo.currentData() if hasattr(self, "attrs_present_combo") else None
        absent = self.attrs_absent_combo.currentData() if hasattr(self, "attrs_absent_combo") else None
        color_ojos = self._color_combos["color_ojos"].currentData()
        color_pelo = self._color_combos["color_pelo"].currentData()
        with get_session() as session:
            service = PersonService(session)
            if query or empresa or present or absent or color_ojos or color_pelo:
                personas = service.search(
                    query, empresa=empresa,
                    attrs=[present] if present else None,
                    excl_attrs=[absent] if absent else None,
                    color_ojos=color_ojos or None,
                    color_pelo=color_pelo or None,
                )
            else:
                personas = service.list_all()
            rows = []
            for p in personas:
                rows.append({
                    "uuid": p.uuid,
                    "nombre": p.nombre_completo,
                    "alias": p.alias or "",
                    "empresa": p.empresa or "",
                    "cargo": p.cargo or "",
                    "correo": p.correo or "",
                    "thumb": _primary_thumbnail(p),
                    "similitud": None,
                    "match": False,
                    "estado": "",
                    "estado_icon": "",
                    "estado_color": "",
                })
        self._fill_results(rows)

    def _fill_results(self, rows: list[dict]) -> None:
        self.results_table.setRowCount(len(rows))
        self.results_count_label.setText(str(len(rows)))
        for i, r in enumerate(rows):
            item_foto = QTableWidgetItem()
            thumb = r.get("thumb")
            pix = QPixmap(thumb) if thumb and Path(thumb).exists() else QPixmap()
            if pix.isNull():
                item_foto.setIcon(icons.icon("person", 18, "#8f92a3"))
            else:
                item_foto.setIcon(QIcon(
                    pix.scaled(34, 34, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)))
            item_foto.setData(Qt.UserRole, r["uuid"])
            item_foto.setToolTip("Clic para ver la ficha")
            self.results_table.setItem(i, 0, item_foto)

            item_nombre = QTableWidgetItem(r["nombre"])
            item_nombre.setData(Qt.UserRole, r["uuid"])
            item_nombre.setForeground(QColor("#ffffff"))
            self.results_table.setItem(i, 1, item_nombre)
            self.results_table.setItem(i, 2, QTableWidgetItem(r["alias"]))
            self.results_table.setItem(i, 3, QTableWidgetItem(r["empresa"]))

            sim = r.get("similitud")
            self.results_table.setItem(
                i, 4, QTableWidgetItem(f"{sim:.1f}%" if sim is not None else "—"))

            if r.get("estado"):
                item_estado = QTableWidgetItem(r["estado"])
                item_estado.setIcon(icons.icon(r["estado_icon"], 16, r["estado_color"]))
                item_estado.setForeground(QColor(r["estado_color"]))
                self.results_table.setItem(i, 5, item_estado)
            else:
                self.results_table.setItem(i, 5, QTableWidgetItem(""))

    def _on_result_clicked(self, row: int, _col: int) -> None:
        item = self.results_table.item(row, 0)
        if item is None:
            return
        uuid = item.data(Qt.UserRole)
        if uuid:
            self._load_person(uuid)

    # ------------------------------------------------------------------ #
    # Búsqueda por fotografía
    # ------------------------------------------------------------------ #
    def _on_query_image(self, path: str) -> None:
        if path == "__pick__":
            self._pick_query_image()
            return
        self._query_path = path
        self.photo_picker.set_image(QPixmap(path))
        self.photo_file_label.setText(icons.status_html("image", Path(path).name, "#b7b9c4"))
        self.photo_search_btn.setEnabled(True)
        self.photo_clear_btn.setEnabled(True)
        self.photo_status_label.setText("")

    def _clear_photo(self) -> None:
        """Limpia la fotografía de búsqueda y los resultados asociados."""
        self._query_path = None
        self.photo_picker.clear()
        self.photo_file_label.clear()
        self.photo_search_btn.setEnabled(False)
        self.photo_clear_btn.setEnabled(False)
        self.photo_status_label.setText("")

    def _pick_query_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Fotografía de búsqueda", "",
            "Imágenes (*.jpg *.jpeg *.png *.bmp *.webp)")
        if path:
            self._on_query_image(path)

    def _start_photo_search(self) -> None:
        if not self._query_path or self._photo_worker and self._photo_worker.isRunning():
            return
        self.photo_search_btn.setEnabled(False)
        self.photo_status_label.setText(
            icons.status_html("sync", "Iniciando búsqueda...", "#6fa8ff"))

        self._photo_worker = PhotoSearchWorker(self._query_path, usuario=self.username)
        self._photo_worker.step.connect(self._on_photo_step)
        self._photo_worker.finished_ok.connect(self._on_photo_search_done)
        self._photo_worker.failed.connect(self._on_photo_search_failed)
        self._photo_worker.finished.connect(self._on_photo_worker_finished)
        self._photo_worker.start()

    def _on_photo_step(self, step: str) -> None:
        self.photo_status_label.setText(icons.status_html("sync", step, "#6fa8ff"))

    def _on_photo_search_done(self, data: dict) -> None:
        image = data["image"]
        face = data["face"]
        if face is not None:
            x1, y1, x2, y2 = [int(v) for v in face.bbox]
            cv2.rectangle(image, (x1, y1), (x2, y2), (46, 204, 113), 3)

        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
        self.photo_picker.set_image(QPixmap.fromImage(qimg.copy()))

        rows = [r for r in data["rows"] if r["match"]]
        for r in rows:
            r["estado"] = "Coincide"
            r["estado_icon"] = "check_circle"
            r["estado_color"] = icons.COLOR_OK
        self._fill_results(rows)

        if rows:
            self.photo_status_label.setText(icons.ok(
                f"{len(rows)} persona(s) coincidente(s). Clic en un resultado para ver su ficha."))
        else:
            self.photo_status_label.setText(icons.warn(
                "No se encontró ninguna coincidencia con esa fotografía."))

    def _on_photo_search_failed(self, message: str) -> None:
        self.photo_status_label.setText(icons.err(message))

    def _on_photo_worker_finished(self) -> None:
        self.photo_search_btn.setEnabled(self._query_path is not None)
        if self._photo_worker:
            self._photo_worker.deleteLater()
            self._photo_worker = None

    # ------------------------------------------------------------------ #
    # Ficha dedicada de la persona
    # ------------------------------------------------------------------ #
    def _load_person(self, uuid: str) -> None:
        self._populating = True
        try:
            self._load_person_impl(uuid)
        finally:
            self._populating = False

    def _load_person_impl(self, uuid: str) -> None:
        if uuid != self._detail_uuid:
            self._detail_editing = False
        with get_session() as session:
            service = PersonService(session)
            person = service.get(uuid)
            if person is None:
                return
            photos = service.list_photos(uuid)
            primary_photo = next((p for p in photos if p.es_principal),
                                 photos[0] if photos else None)
            avatar_path = primary_photo.file_path if primary_photo else None
            info = {
                "fotos": str(len(photos)),
                "embeddings": str(len(person.embeddings)),
                "registrado": person.fecha_creacion.strftime("%d/%m/%Y %H:%M")
                if person.fecha_creacion else "—",
                "modificacion": person.fecha_modificacion.strftime("%d/%m/%Y %H:%M")
                if person.fecha_modificacion else "—",
            }
            attrs_by_photo = {
                emb.photo_id: attrs_from_json(emb.facial_attributes)
                for emb in person.embeddings if emb.photo_id is not None
            }
            photo_data = [
                {"id": p.id, "file_path": p.file_path,
                 "thumbnail_path": p.thumbnail_path,
                 "calidad_score": p.calidad_score,
                 "es_principal": p.es_principal,
                 "attributes": attrs_by_photo.get(p.id)}
                for p in photos
            ]
            datos_campos = {
                "nombre": person.nombre,
                "apellidos": person.apellidos,
                "alias": person.alias or "",
                "sexo": person.sexo or "",
                "edad": person.edad_aproximada or 0,
                "empresa": person.empresa or "",
                "departamento": person.departamento or "",
                "cargo": person.cargo or "",
                "telefono": person.telefono or "",
                "correo": person.correo or "",
                "observaciones": person.observaciones or "",
            }
            nombre_completo = person.nombre_completo
            empresa, cargo = person.empresa or "", person.cargo or ""
            attrs_primarios = primary_embedding_attrs(person)

        self._detail_uuid = uuid
        self.detail_name_label.setText(nombre_completo)
        self.det_nombre.setText(datos_campos["nombre"])
        self.det_apellidos.setText(datos_campos["apellidos"])
        self.det_alias.setText(datos_campos["alias"])
        self.det_sexo.setCurrentText(datos_campos["sexo"])
        self.det_edad.setValue(datos_campos["edad"])
        self.det_empresa.setText(datos_campos["empresa"])
        self.det_departamento.setText(datos_campos["departamento"])
        self.det_cargo.setText(datos_campos["cargo"])
        self.det_telefono.setText(datos_campos["telefono"])
        self.det_correo.setText(datos_campos["correo"])
        self.det_observaciones.setPlainText(datos_campos["observaciones"])
        self.detail_edit_btn.setEnabled(self._can_edit)
        self.detail_edit_btn.setVisible(self._can_edit)
        self._set_avatar(avatar_path)
        parts = [x for x in (empresa, cargo) if x]
        self.detail_subtitle_label.setText(" · ".join(parts) if parts else
                                           "Persona registrada en el sistema")
        for key, label in self._detail_info.items():
            label.setText(info[DETAIL_FIELD_KEYS[key]])
        self._set_detail_photos(photo_data)
        self._set_attribute_ui(attrs_primarios)
        self.add_photos_btn.setEnabled(self._can_edit)
        self.clear_photos_btn.setEnabled(self._can_edit and len(photo_data) > 0)
        self.delete_person_btn.setEnabled(self._can_delete)
        self._set_editing(self._detail_editing)

    def _set_editing(self, editing: bool) -> None:
        self._detail_editing = editing
        if not hasattr(self, "detail_editor_card"):
            return
        self.detail_editor_card.setVisible(self._detail_uuid is not None)
        deadline = not editing
        for w in (self.det_nombre, self.det_apellidos, self.det_alias,
                  self.det_empresa, self.det_departamento, self.det_cargo,
                  self.det_telefono, self.det_correo):
            w.setReadOnly(deadline)
        self.det_sexo.setEditable(not deadline)
        self.det_sexo.setEnabled(not deadline)
        self.det_edad.setButtonSymbols(QAbstractSpinBox.PlusMinus
                                       if not deadline else QAbstractSpinBox.NoButtons)
        self.det_edad.setReadOnly(deadline)
        self.det_observaciones.setReadOnly(deadline)
        self.save_detail_btn.setVisible(editing)
        self.cancel_detail_btn.setVisible(editing)

    def _enable_edition(self) -> None:
        if not self._detail_uuid or not self._can_edit:
            return
        self._set_editing(True)
        self.detail_status.setText("Editando en tiempo real — cada cambio quedará guardado.")
        self.detail_status.setStyleSheet("color: #6fa8ff; font-size: 12px;")

    def _disable_edition(self) -> None:
        self._set_editing(False)
        self.detail_status.setText("Datos en modo lectura. Pulsa «Editar» para modificarlos.")
        self.detail_status.setStyleSheet("color: #8f92a3; font-size: 12px;")
        if self._detail_uuid:
            self._load_person(self._detail_uuid)

    def _save_person_details(self) -> None:
        if not self._detail_uuid:
            return
        nombre = self.det_nombre.text().strip()
        apellidos = self.det_apellidos.text().strip()
        if not nombre or not apellidos:
            self.detail_status.setText(icons.err("El nombre y los apellidos son obligatorios."))
            return
        nombre = nombre.capitalize()
        apellidos = apellidos.capitalize() if " " not in apellidos else apellidos
        correo = self.det_correo.text().strip()
        if correo and not EMAIL_RE.match(correo):
            self.detail_status.setText(icons.err("El correo electrónico no es válido."))
            return
        datos = {
            "nombre": nombre,
            "apellidos": apellidos,
            "alias": self.det_alias.text().strip() or None,
            "sexo": self.det_sexo.currentText().strip() or None,
            "edad_aproximada": self.det_edad.value() or None,
            "empresa": self.det_empresa.text().strip() or None,
            "departamento": self.det_departamento.text().strip() or None,
            "cargo": self.det_cargo.text().strip() or None,
            "telefono": self.det_telefono.text().strip() or None,
            "correo": correo or None,
            "observaciones": self.det_observaciones.toPlainText().strip() or None,
        }
        try:
            with get_session() as session:
                service = PersonService(session)
                service.update_person(self._detail_uuid, **datos, usuario=self.username)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error al actualizar la persona")
            self.detail_status.setText(icons.err(f"Error al guardar: {exc}"))
            return
        self.detail_status.setText(icons.ok("Cambios guardados correctamente."))
        self.detail_subtitle_label.setText(" · ".join(
            [x for x in (datos.get("empresa") or "", datos.get("cargo") or "") if x])
            or "Persona registrada en el sistema")
        self._load_empresas()
        self._load_person(self._detail_uuid)
        self._sync_results_row(self._detail_uuid)

    def _sync_results_row(self, uuid: str) -> None:
        """Actualiza la fila de la persona en la tabla de resultados en tiempo real."""
        for row in range(self.results_table.rowCount()):
            item = self.results_table.item(row, 0)
            if item is None or item.data(Qt.UserRole) != uuid:
                continue
            with get_session() as session:
                person = PersonService(session).get(uuid)
                if person is None:
                    return
                nombre = person.nombre_completo
                alias = person.alias or ""
                empresa = person.empresa or ""
                thumb = _primary_thumbnail(person)
            self.results_table.item(row, 1).setText(nombre)
            self.results_table.item(row, 2).setText(alias)
            self.results_table.item(row, 3).setText(empresa)
            pix = QPixmap(thumb) if thumb and Path(thumb).exists() else QPixmap()
            if pix.isNull():
                self.results_table.item(row, 0).setIcon(icons.icon("person", 18, "#8f92a3"))
            else:
                self.results_table.item(row, 0).setIcon(QIcon(
                    pix.scaled(34, 34, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)))
            break

    def _clear_photo_dataset(self) -> None:
        """Pide confirmación y elimina todas las fotos del dataset de la persona actual."""
        if not self._detail_uuid or not self._detail_photo_data or not self._can_edit:
            return
        resp = QMessageBox.question(
            self, "Limpiar dataset",
            "Se eliminarán todas las fotografías y sus vectores biométricos "
            f"({len(self._detail_photo_data)}). ¿Continuar?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return
        for data in list(self._detail_photo_data):
            with get_session() as session:
                PersonService(session).delete_photo(
                    self._detail_uuid, data["id"], usuario=self.username)
        self._load_person(self._detail_uuid)
        self.detail_status.setText(icons.ok("Dataset de fotografías limpiado."))

    def _delete_person(self) -> None:
        """Pide confirmación y elimina a la persona junto con su dataset."""
        if not self._detail_uuid or not self._can_delete:
            return
        nombre = self.detail_name_label.text().strip() or "esta persona"
        resp = QMessageBox.question(
            self, "Eliminar persona",
            f"Se eliminará permanentemente a «{nombre}» junto con todas sus "
            "fotografías y vectores biométricos. Esto no se puede deshacer.\n\n¿Continuar?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return
        uuid = self._detail_uuid
        if self._autosave_timer.isActive():
            self._autosave_timer.stop()
        with get_session() as session:
            deleted = PersonService(session).delete(uuid, usuario=self.username)
        if not deleted:
            QMessageBox.warning(self, "No se pudo eliminar",
                                "La persona ya no existe o hubo un error.")
            return
        self._reset_detail()
        self.detail_status.setText("")
        self._load_empresas()
        self._search_text()

    def _set_avatar(self, avatar_path: str | None) -> None:
        pix = QPixmap(avatar_path) if avatar_path and Path(avatar_path).exists() else QPixmap()
        if pix.isNull():
            self.avatar_label.setPixmap(icons.pixmap("person", 44, "#8f92a3"))
        else:
            self.avatar_label.setPixmap(pix.scaled(
                96, 96, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))

    # ------------------------------------------------------------------ #
    # Dataset de fotos en la ficha
    # ------------------------------------------------------------------ #
    def _set_detail_photos(self, photo_data: list[dict]) -> None:
        self._detail_photo_data = list(photo_data)
        self._detail_photo_rev += 1
        self._relayout_detail_photos()

    def _relayout_detail_photos(self) -> None:
        available = self.photo_grid.width() - 24 - 12
        cols = min(3, max(1, available // (PHOTO_CARD_WIDTH + 10)))
        if (cols == self._detail_photo_columns
                and self._detail_photo_cards
                and self._detail_photo_rev == self._detail_photo_rendered_rev):
            return
        self._detail_photo_columns = cols
        self._detail_photo_rendered_rev = self._detail_photo_rev
        self._render_detail_photo_cards()

    def _update_photo_grid_height(self) -> None:
        """Limita la altura visible de la rejilla a 3 filas; el resto se scrollea."""
        if not self._detail_photo_data:
            self.photo_grid.setMaximumHeight(PHOTO_CARD_HEIGHT + 24)
            self.photos_scroll.setFixedHeight(PHOTO_CARD_HEIGHT + 24)
            return
        visible_rows = min(3, ceil(len(self._detail_photo_data) / self._detail_photo_columns))
        height = visible_rows * PHOTO_CARD_HEIGHT \
            + (visible_rows - 1) * 10 + 24
        self.photo_grid.setMaximumHeight(height)
        self.photos_scroll.setFixedHeight(height)

    def _render_detail_photo_cards(self) -> None:
        self.photo_grid.clear_cards()
        self._detail_photo_cards.clear()
        if not self._detail_photo_data:
            self.photo_grid.show_empty()
            self.detail_photo_count.setText("0 fotos")
            self._update_photo_grid_height()
            return
        cols = self._detail_photo_columns or 1
        for i, data in enumerate(self._detail_photo_data):
            card = PhotoCard(
                photo_id=data["id"],
                thumb_path=data["thumbnail_path"],
                calidad_score=data["calidad_score"],
                es_principal=data["es_principal"],
                show_primary_btn=self._can_edit,
                show_delete_btn=self._can_edit,
            )
            card.preview_requested.connect(self._preview_photo)
            card.primary_requested.connect(self._set_primary_photo)
            card.delete_requested.connect(self._delete_photo)
            self.photo_grid.grid.addWidget(card, i // cols, i % cols)
            self._detail_photo_cards.append(card)
        self.detail_photo_count.setText(f"{len(self._detail_photo_data)} fotos")
        self._update_photo_grid_height()

    def _reload_detail_photos(self) -> None:
        if not self._detail_uuid:
            self._set_detail_photos([])
            return
        with get_session() as session:
            service = PersonService(session)
            photos = service.list_photos(self._detail_uuid)
            photo_data = [
                {"id": p.id, "file_path": p.file_path,
                 "thumbnail_path": p.thumbnail_path,
                 "calidad_score": p.calidad_score,
                 "es_principal": p.es_principal}
                for p in photos
            ]
        self._set_detail_photos(photo_data)

    def _pick_photos(self) -> None:
        if not self._detail_uuid:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Añadir fotografías", "",
            "Imágenes (*.jpg *.jpeg *.png *.bmp *.webp)")
        if paths:
            self._add_photos(paths)

    def _add_photos(self, paths: list[str]) -> None:
        if not self._detail_uuid:
            return
        added = 0
        errores: list[str] = []
        with get_session() as session:
            service = PersonService(session)
            for path in paths:
                try:
                    service.add_photo_from_path(self._detail_uuid, path,
                                                usuario=self.username)
                    added += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning("No se pudo procesar {}: {}", path, exc)
                    errores.append(f"{Path(path).name}: {exc}")
        if added:
            self._reload_detail_photos()
            self.detail_photo_count.setText(f"{len(self._detail_photo_data)} fotos")
        if errores:
            QMessageBox.warning(self, "Algunas fotos fueron rechazadas",
                                "\n".join(errores[:8]))

    def _preview_photo(self, photo_id: int) -> None:
        data = next((d for d in self._detail_photo_data if d["id"] == photo_id), None)
        if not data:
            return
        path = data.get("file_path")
        if not path or not Path(path).exists():
            QMessageBox.warning(self, "Foto no disponible",
                                "No se encontró el archivo de la foto.")
            return
        PhotoPreviewDialog(path, "Foto de la persona", self,
                           attributes_text=_attrs_present_text(
                               data.get("attributes"))).exec()

    def _set_primary_photo(self, photo_id: int) -> None:
        if not self._detail_uuid:
            return
        with get_session() as session:
            service = PersonService(session)
            service.set_primary_photo(self._detail_uuid, photo_id,
                                      usuario=self.username)
        self._load_person(self._detail_uuid)
        self._sync_results_row(self._detail_uuid)

    def _delete_photo(self, photo_id: int) -> None:
        data = next((d for d in self._detail_photo_data if d["id"] == photo_id), None)
        nombre = Path(data["file_path"]).name if data and data.get("file_path") else f"foto #{photo_id}"
        resp = QMessageBox.question(
            self, "Eliminar foto",
            f"¿Eliminar {nombre} y su vector biométrico?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return
        with get_session() as session:
            service = PersonService(session)
            service.delete_photo(self._detail_uuid, photo_id, usuario=self.username)
        self._load_person(self._detail_uuid)
        self._sync_results_row(self._detail_uuid)

    # ------------------------------------------------------------------ #
    def refresh_ui(self) -> None:
        if getattr(self, "_populating", False):
            return
        self._flush_autosave()
        self._load_empresas()
        self._search_text()
        if self._detail_uuid:
            self._load_person(self._detail_uuid)

    def set_username(self, username: str | None) -> None:
        """Actualiza el usuario activo; el audit y el dataset responden en tiempo real."""
        self.username = username
        self._flush_autosave()
        if self._detail_uuid:
            self._load_person(self._detail_uuid)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout_detail_photos()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._photo_worker is not None:
            self._photo_worker.wait(2000)
        super().closeEvent(event)


# --------------------------------------------------------------------------- #
# Módulo: Comparador biométrico (escáner 1:1)
# --------------------------------------------------------------------------- #

STEP_NAMES = [
    "Cargando imagen A",
    "Analizando imagen B",
    "Detectando rostro en imagen A",
    "Detectando rostro en imagen B",
    "Extrayendo vectores biométricos",
    "Calculando similitud coseno",
    "Generando veredicto",
]


def _bgr_to_pixmap(bgr: np.ndarray) -> QPixmap:
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    img = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(img.copy())


class ScanCanvas(QWidget):
    """Lienzo de escaneo: imagen + retícula de puntería + línea de barrido + overlay del rostro."""

    def __init__(self, accent: str, parent=None):
        super().__init__(parent)
        self._accent = accent
        self._pix: QPixmap | None = None
        self._scan = 0.0
        self._scanning = False
        self._face_rect: tuple[float, float, float, float] | None = None
        self._landmarks: np.ndarray | None = None
        self._face_score: float | None = None
        self._image_info: str | None = None
        self.setMinimumSize(300, 280)

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    # ---------------------------------------------------------------- #
    def set_image(self, pix: QPixmap) -> None:
        self._pix = pix
        self._face_rect = None
        self._landmarks = None
        self._face_score = None
        self.update()

    def set_image_info(self, info: str) -> None:
        self._image_info = info
        self.update()

    def set_face(self, bbox: tuple, landmarks, score: float | None = None) -> None:
        self._face_rect = tuple(bbox)
        self._landmarks = landmarks
        self._face_score = score
        self.update()

    def set_scanning(self, on: bool) -> None:
        self._scanning = on
        self._scan = 0.0
        if on:
            self._timer.start()
        else:
            self._timer.stop()
            self.update()

    def _tick(self) -> None:
        self._scan = (self._scan + 0.025) % 1.0
        self.update()

    # ---------------------------------------------------------------- #
    def _image_rect(self) -> QRectF:
        if self._pix is None or self._pix.isNull():
            return QRectF(self.rect()).adjusted(14, 14, -14, -14)
        pix = self._pix.size()
        avail_w = self.width() - 28
        avail_h = self.height() - 28
        scale = min(avail_w / pix.width(), avail_h / pix.height())
        dw = pix.width() * scale
        dh = pix.height() * scale
        return QRectF((self.width() - dw) / 2, (self.height() - dh) / 2, dw, dh)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#16171c"))

        if self._pix is None or self._pix.isNull():
            self._draw_placeholder(p)
            return

        ir = self._image_rect()
        p.drawPixmap(ir.toRect(), self._pix)

        if self._face_rect is not None:
            self._draw_face_overlay(p, ir)
        if self._scanning:
            self._draw_scan_line(p, ir)
        self._draw_reticle(p, ir, self._accent)

        self._draw_image_info(p, ir)

    def _draw_image_info(self, p: QPainter, ir: QRectF) -> None:
        if self._image_info:
            p.setFont(QFont("Consolas", 9))
            p.setPen(QColor("#9aa0b3"))
            p.drawText(
                QRectF(ir.left() + 10, ir.bottom() - 24, ir.width() - 20, 18),
                Qt.AlignmentFlag.AlignLeft, self._image_info,
            )
        if self._face_score is not None:
            badge = f"CONFIANZA {self._face_score * 100:.1f}%"
            p.setFont(QFont("Consolas", 9))
            p.setPen(QColor(self._accent))
            p.drawText(
                QRectF(ir.left() + 10, ir.top() + 8, ir.width() - 20, 18),
                Qt.AlignmentFlag.AlignLeft, badge,
            )

    def _draw_placeholder(self, p: QPainter) -> None:
        rect = QRectF(self.rect()).adjusted(14, 14, -14, -14)
        pen = QPen(QColor("#34353f"), 1, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawRect(rect)

        p.setFont(icons._font(42))
        p.setPen(QColor("#3f4250"))
        p.drawText(QRectF(0, self.height() / 2 - 56, self.width(), 60),
                   Qt.AlignmentFlag.AlignCenter, icons._glyph("crop_free"))

        p.setFont(QFont("Consolas", 10))
        p.setPen(QColor("#5a5d6e"))
        p.drawText(QRectF(0, self.height() / 2 + 8, self.width(), 20),
                   Qt.AlignmentFlag.AlignCenter, "SIN IMAGEN")

    def _draw_reticle(self, p: QPainter, rect: QRectF, color: str) -> None:
        pen = QPen(QColor(color), 2)
        p.setPen(pen)
        length = 24
        x0, y0 = rect.left(), rect.top()
        x1, y1 = rect.right(), rect.bottom()
        for cx, cy, dx, dy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
            p.drawLine(int(cx), int(cy), int(cx + dx * length), int(cy))
            p.drawLine(int(cx), int(cy), int(cx), int(cy + dy * length))

    def _draw_scan_line(self, p: QPainter, ir: QRectF) -> None:
        y = ir.top() + self._scan * ir.height()
        grad = QLinearGradient(0, y - 22, 0, y + 22)
        r, g, b, _ = QColor(self._accent).getRgb()
        grad.setColorAt(0.0, QColor(r, g, b, 0))
        grad.setColorAt(0.5, QColor(r, g, b, 90))
        grad.setColorAt(1.0, QColor(r, g, b, 0))
        p.fillRect(QRectF(ir.left(), y - 22, ir.width(), 44), QBrush(grad))

        p.setPen(QPen(QColor(self._accent), 1.5))
        p.drawLine(int(ir.left()), int(y), int(ir.right()), int(y))

        p.setFont(QFont("Consolas", 9))
        p.setPen(QColor(self._accent))
        p.drawText(QRectF(ir.left() + 10, ir.top() + 10, ir.width() - 20, 18),
                   Qt.AlignmentFlag.AlignLeft, "■ ANALIZANDO...")

    def _draw_face_overlay(self, p: QPainter, ir: QRectF) -> None:
        x1, y1, x2, y2 = self._face_rect
        sx = ir.width() / self._pix.width()
        sy = ir.height() / self._pix.height()
        rx = ir.left() + x1 * sx
        ry = ir.top() + y1 * sy
        rw = (x2 - x1) * sx
        rh = (y2 - y1) * sy

        p.setPen(QPen(QColor(self._accent), 2))
        p.drawRect(QRectF(rx, ry, rw, rh))

        if self._landmarks is not None:
            p.setPen(QPen(QColor(icons.COLOR_OK), 1.5))
            for lx, ly in self._landmarks:
                wx = ir.left() + float(lx) * sx
                wy = ir.top() + float(ly) * sy
                p.drawLine(int(wx) - 5, int(wy), int(wx) + 5, int(wy))
                p.drawLine(int(wx), int(wy) - 5, int(wx), int(wy) + 5)

        p.setFont(QFont("Consolas", 8))
        p.setPen(QColor(icons.COLOR_OK))
        top = max(ir.top(), ry - 20)
        p.drawText(QRectF(rx, top, rw, 16), Qt.AlignmentFlag.AlignCenter, "ROSTRO DETECTADO")


class ScanFrame(QFrame):
    """Panel con lienzo de escaneo, nombre de archivo y botón de selección."""

    image_dropped = Signal(str)

    def __init__(self, title_key: str, accent: str, on_select, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAcceptDrops(True)
        self.title_key = title_key
        self._has_source = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        self.title_label = QLabel(tr(title_key))
        self.title_label.setStyleSheet("font-size: 15px; font-weight: 700;")
        header.addWidget(self.title_label)
        header.addStretch()
        layout.addLayout(header)

        self.canvas = ScanCanvas(accent)
        layout.addWidget(self.canvas, stretch=1)

        self.file_label = QLabel(tr("compare.no_image_selected"))
        self.file_label.setStyleSheet("color: #6b6e7d; font-size: 12px;")
        self.file_label.setWordWrap(True)
        layout.addWidget(self.file_label)

        self.select_button = QPushButton(tr("compare.select_image"))
        self.select_button.setObjectName("SecondaryButton")
        self.select_button.clicked.connect(on_select)
        layout.addWidget(self.select_button)

    def retranslate(self) -> None:
        self.title_label.setText(tr(self.title_key))
        self.select_button.setText(tr("compare.select_image"))
        if not self._has_source:
            self.file_label.setText(tr("compare.no_image_selected"))

    def set_source(self, name: str, pix: QPixmap) -> None:
        self._has_source = True
        self.file_label.setText(name)
        self.canvas.set_image(pix)

    def clear_source(self) -> None:
        self._has_source = False
        self.file_label.setText(tr("compare.no_image_selected"))
        self.canvas.set_image(QPixmap())

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        image_paths = [p for p in paths if Path(p).suffix.lower() in
                       (".jpg", ".jpeg", ".png", ".bmp", ".webp")]
        if image_paths:
            self.image_dropped.emit(image_paths[0])


class SimilarityGauge(QWidget):
    """Indicador circular animado del porcentaje de coincidencia."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(240, 240)
        self._target = 0.0
        self._display = 0.0
        self._color = QColor("#8f92a3")
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._step)

    def set_value(self, pct: float, color: str) -> None:
        self._target = pct
        self._color = QColor(color)
        if not self._timer.isActive():
            self._timer.start()

    def reset(self) -> None:
        self._target = 0.0
        self._display = 0.0
        self._color = QColor("#8f92a3")
        self._timer.stop()
        self.update()

    def _step(self) -> None:
        diff = self._target - self._display
        if abs(diff) < 0.4:
            self._display = self._target
            self._timer.stop()
        else:
            self._display += diff * 0.12
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        size = 192
        rect = QRectF((w - size) / 2, (h - size) / 2, size, size)
        pen_w = 16
        start = 225 * 16
        span = 270 * 16

        p.setPen(QPen(QColor("#2a2b33"), pen_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, start, span)

        p.setPen(QPen(self._color, pen_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, start, int(-span * self._display / 100.0))

        p.setPen(QColor("#ffffff"))
        p.setFont(QFont("Segoe UI", 38, QFont.Weight.Bold))
        p.drawText(QRectF(0, h / 2 - 54, w, 62), Qt.AlignmentFlag.AlignCenter,
                   f"{self._display:.1f}%")

        p.setPen(QColor("#8f92a3"))
        p.setFont(QFont("Consolas", 9))
        p.drawText(QRectF(0, h / 2 + 14, w, 20), Qt.AlignmentFlag.AlignCenter, "SIMILITUD")


class StepRow(QWidget):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(10)
        self.dot = QLabel()
        self.dot.setFixedSize(18, 18)
        self.label = QLabel(text)
        lay.addWidget(self.dot)
        lay.addWidget(self.label)
        lay.addStretch()
        self.set_state("pending")

    def set_state(self, state: str) -> None:
        if state == "done":
            self.dot.setPixmap(icons.pixmap("check_circle", 14, icons.COLOR_OK))
            self.label.setStyleSheet("color: #e6e6e6;")
        elif state == "error":
            self.dot.setPixmap(icons.pixmap("error", 14, icons.COLOR_ERROR))
            self.label.setStyleSheet(f"color: {icons.COLOR_ERROR};")
        else:
            self.dot.setPixmap(icons.pixmap("circle", 14, "#3a3c47"))
            self.label.setStyleSheet("color: #6b6e7d;")

    def _set_dot_color(self, color: str) -> None:
        self.dot.setPixmap(icons.pixmap("circle", 14, color))
        self.label.setStyleSheet("color: #ffffff;")


class StepList(QWidget):
    """Lista de pasos del proceso con estados pending / active / done / error."""

    def __init__(self, steps: list[str], parent=None):
        super().__init__(parent)
        self._rows: list[StepRow] = []
        lay = QVBoxLayout(self)
        lay.setSpacing(2)
        lay.setContentsMargins(0, 0, 0, 0)
        for text in steps:
            row = StepRow(text)
            lay.addWidget(row)
            self._rows.append(row)
        lay.addStretch()

        self._active_index = -1
        self._pulse_on = False
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(380)
        self._pulse_timer.timeout.connect(self._pulse)

    def reset_all(self) -> None:
        for row in self._rows:
            row.set_state("pending")
        self._active_index = -1
        self._pulse_timer.stop()

    def set_active(self, index: int) -> None:
        for row in self._rows:
            row.set_state("pending")
        if index < 0 or index >= len(self._rows):
            return
        self._active_index = index
        self._pulse_on = True
        self._rows[index]._set_dot_color("#6fa8ff")
        self._pulse_timer.start()

    def mark_done(self, index: int) -> None:
        if self._active_index == index:
            self._pulse_timer.stop()
        if 0 <= index < len(self._rows):
            self._rows[index].set_state("done")

    def mark_error(self, index: int) -> None:
        if self._active_index == index:
            self._pulse_timer.stop()
        if 0 <= index < len(self._rows):
            self._rows[index].set_state("error")

    def _pulse(self) -> None:
        self._pulse_on = not self._pulse_on
        if self._active_index >= 0:
            color = "#6fa8ff" if self._pulse_on else "#2f6fed"
            self._rows[self._active_index]._set_dot_color(color)


class CompareWorker(QThread):
    """Ejecuta el análisis 1:1 en segundo plano y reporta cada paso."""

    step_started = Signal(str)
    step_succeeded = Signal(str, object)
    progress = Signal(int)
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, path_a: str, path_b: str, parent=None):
        super().__init__(parent)
        self.path_a = path_a
        self.path_b = path_b

    def run(self) -> None:  # noqa: D102
        steps = [
            "Cargando imagen A",
            "Analizando imagen B",
            "Detectando rostro en imagen A",
            "Detectando rostro en imagen B",
            "Extrayendo vectores biométricos",
            "Calculando similitud coseno",
            "Generando veredicto",
        ]
        total = len(steps)
        img_a, img_b = None, None
        face_a, face_b = None, None
        result = None

        try:
            for i, name in enumerate(steps):
                self.step_started.emit(name)
                self.progress.emit(int((i / total) * 100))

                if name == "Cargando imagen A":
                    # Corregido: self.path_a
                    img_a = FaceEngine.load_image_bgr(self.path_a)
                    if img_a is None:
                        raise ValueError("No se pudo leer la imagen A. Verifica el archivo.")
                    self.step_succeeded.emit(name, img_a)

                elif name == "Analizando imagen B":
                    # Corregido: self.path_b
                    img_b = FaceEngine.load_image_bgr(self.path_b)
                    if img_b is None:
                        raise ValueError("No se pudo leer la imagen B. Verifica el archivo.")
                    self.step_succeeded.emit(name, img_b)

                elif name == "Detectando rostro en imagen A":
                    face_a = FaceEngine.instance().largest_face(img_a)
                    if face_a is None:
                        raise NoFaceDetectedError("No se detectó ningún rostro en la imagen A.")
                    self.step_succeeded.emit(name, face_a)

                elif name == "Detectando rostro en imagen B":
                    face_b = FaceEngine.instance().largest_face(img_b)
                    if face_b is None:
                        raise NoFaceDetectedError("No se detectó ningún rostro en la imagen B.")
                    self.step_succeeded.emit(name, face_b)

                elif name == "Extrayendo vectores biométricos":
                    self.step_succeeded.emit(name, None)

                elif name == "Calculando similitud coseno":
                    result = compare_pair(face_a.embedding, face_b.embedding)
                    self.step_succeeded.emit(name, result)

                elif name == "Generando veredicto":
                    self.progress.emit(100)
                    self.finished_ok.emit({
                        "result": result,
                        "face_a": face_a,
                        "face_b": face_b,
                        "image_a": img_a,
                        "image_b": img_b,
                    })
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class FaceCompareWidget(QWidget):
    """Módulo 'Comparador biométrico' — escáner 1:1 con proceso visible."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path_a: str | None = None
        self._path_b: str | None = None
        self._worker: CompareWorker | None = None
        self._face_a = None
        self._face_b = None
        self._image_a: np.ndarray | None = None
        self._image_b: np.ndarray | None = None
        self._active_step_idx = -1
        self._start_time = 0.0
        self._elapsed = 0.0
        self._elapsed_timer: QTimer | None = None
        self._last_result: dict | None = None
        self._build_ui()
        self._reset_results()
        self._refresh_compare_ready()
        i18n_bus().languageChanged.connect(self._retranslate)

    def _retranslate(self) -> None:
        self._title.setText(tr("compare.title"))
        self._subtitle.setText(tr("compare.subtitle"))
        self.compare_btn.setText(tr("compare.compare"))
        self.swap_btn.setText(tr("compare.swap"))
        self.clear_btn.setText(tr("common.clear"))
        self.export_btn.setText(tr("compare.export"))
        self.status_label.setText(tr("compare.ready"))
        if hasattr(self, "_steps_title"):
            self._steps_title.setText(tr("compare.steps_title"))
            self._metrics_title.setText(tr("compare.metrics_title"))
            self.frame_a.retranslate()
            self.frame_b.retranslate()
            for value_label, key in self._metric_label_keys.items():
                if value_label in self._metric_name_labels:
                    self._metric_name_labels[value_label].setText(tr(key))

    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        header = QHBoxLayout()
        self._title = QLabel(tr("compare.title"))
        self._title.setStyleSheet("font-size: 22px; font-weight: 700;")
        header.addWidget(self._title)
        header.addStretch()
        layout.addLayout(header)

        self._subtitle = QLabel(tr("compare.subtitle"))
        self._subtitle.setStyleSheet("color: #8f92a3;")
        self._subtitle.setWordWrap(True)
        layout.addWidget(self._subtitle)

        # --- Panel central: A | gauge | B ---
        top = QHBoxLayout()
        top.setSpacing(14)
        self.frame_a = ScanFrame("compare.image_a", "#6fa8ff", self._pick_a)
        self.frame_b = ScanFrame("compare.image_b", "#e8895c", self._pick_b)
        self.frame_a.image_dropped.connect(self._on_drop_a)
        self.frame_b.image_dropped.connect(self._on_drop_b)
        top.addWidget(self.frame_a, stretch=1)
        top.addWidget(self._build_center(), stretch=0)
        top.addWidget(self.frame_b, stretch=1)
        layout.addLayout(top, stretch=1)

        # --- Panel inferior: pasos + métricas ---
        bottom = QHBoxLayout()
        bottom.setSpacing(14)
        bottom.addWidget(self._build_steps_panel(), stretch=1)
        bottom.addWidget(self._build_metrics_panel(), stretch=0)
        layout.addLayout(bottom)

        # --- Barra de acciones ---
        actions = QHBoxLayout()
        self.compare_btn = QPushButton(tr("compare.compare"))
        self.compare_btn.setIcon(icons.icon("compare", 16, "#ffffff"))
        self.compare_btn.clicked.connect(self._compare)
        actions.addWidget(self.compare_btn)

        self.swap_btn = QPushButton(tr("compare.swap"))
        self.swap_btn.setObjectName("SecondaryButton")
        self.swap_btn.setIcon(icons.icon("swap_horiz", 16, "#b7b9c4"))
        self.swap_btn.clicked.connect(self._swap_ab)
        actions.addWidget(self.swap_btn)

        self.clear_btn = QPushButton(tr("common.clear"))
        self.clear_btn.setObjectName("SecondaryButton")
        self.clear_btn.setIcon(icons.icon("refresh", 16, "#b7b9c4"))
        self.clear_btn.clicked.connect(self._clear_all)
        actions.addWidget(self.clear_btn)

        self.export_btn = QPushButton(tr("compare.export"))
        self.export_btn.setObjectName("SecondaryButton")
        self.export_btn.setIcon(icons.icon("download", 16, "#b7b9c4"))
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._export_report)
        actions.addWidget(self.export_btn)

        self.status_label = QLabel(tr("compare.ready"))
        self.status_label.setStyleSheet("color: #8f92a3;")
        actions.addWidget(self.status_label, stretch=1)
        layout.addLayout(actions)

    def _build_center(self) -> QWidget:
        center = QWidget()
        lay = QVBoxLayout(center)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(8)

        self.gauge = SimilarityGauge()
        lay.addWidget(self.gauge)

        self.verdict_label = QLabel("")
        self.verdict_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.verdict_label.setStyleSheet("font-size: 17px; font-weight: 700;")
        lay.addWidget(self.verdict_label)

        self.gauge_hint = QLabel("")
        self.gauge_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.gauge_hint.setWordWrap(True)
        self.gauge_hint.setStyleSheet("color: #8f92a3; font-size: 12px;")
        lay.addWidget(self.gauge_hint)

        self.attr_a_label = QLabel("")
        self.attr_a_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.attr_a_label.setStyleSheet("color: #6fa8ff; font-size: 12px;")
        lay.addWidget(self.attr_a_label)

        self.attr_b_label = QLabel("")
        self.attr_b_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.attr_b_label.setStyleSheet("color: #e8895c; font-size: 12px;")
        lay.addWidget(self.attr_b_label)

        self.elapsed_label = QLabel("")
        self.elapsed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.elapsed_label.setStyleSheet(
            "font-family: 'Consolas'; color: #8f92a3; font-size: 12px;")
        lay.addWidget(self.elapsed_label)

        lay.addStretch()
        return center

    def _build_steps_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Card")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        self._steps_title = QLabel(tr("compare.steps_title"))
        self._steps_title.setStyleSheet("font-size: 14px; font-weight: 700;")
        lay.addWidget(self._steps_title)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        lay.addWidget(self.progress_bar)

        self.steps = StepList(STEP_NAMES)
        lay.addWidget(self.steps, stretch=1)
        return frame

    def _build_metrics_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Card")
        frame.setMinimumWidth(300)
        frame.setMaximumWidth(360)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        self._metrics_title = QLabel(tr("compare.metrics_title"))
        self._metrics_title.setStyleSheet("font-size: 14px; font-weight: 700;")
        lay.addWidget(self._metrics_title)

        self.metric_dist = self._metric_value()
        self.metric_sim = self._metric_value()
        self.metric_pct = self._metric_value()
        self.metric_umbral = self._metric_value()
        self.metric_estado = self._metric_value()

        self._metric_name_labels: dict[QLabel, QLabel] = {}
        self._metric_label_keys: dict[QLabel, str] = {}
        lay.addWidget(self._metric_row("compare.distance", self.metric_dist))
        lay.addWidget(self._metric_row("compare.similarity", self.metric_sim))
        lay.addWidget(self._metric_row("compare.percentage", self.metric_pct))
        lay.addWidget(self._metric_row("compare.threshold", self.metric_umbral))
        lay.addWidget(self._metric_row("compare.verdict", self.metric_estado))
        lay.addStretch()
        return frame

    def _metric_value(self) -> QLabel:
        label = QLabel("—")
        label.setStyleSheet(
            "color: #e6e6e6; font-family: 'Consolas','Cascadia Mono','Courier New',monospace;"
            "font-size: 13px;"
        )
        return label

    def _metric_row(self, key: str, value: QLabel) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        name_label = QLabel(tr(key))
        name_label.setStyleSheet("color: #8f92a3; font-size: 12px;")
        lay.addWidget(name_label)
        lay.addStretch()
        lay.addWidget(value)
        self._metric_name_labels[value] = name_label
        self._metric_label_keys[value] = key
        return row

    # ------------------------------------------------------------------ #
    def _load_side(self, side: str, path: str) -> None:
        if side == "a":
            self._path_a = path
            self.frame_a.set_source(f"{tr('compare.image_a')} · {Path(path).name}", QPixmap(path))
            self.frame_a.canvas.set_image_info(None)
        else:
            self._path_b = path
            self.frame_b.set_source(f"{tr('compare.image_b')} · {Path(path).name}", QPixmap(path))
            self.frame_b.canvas.set_image_info(None)
        self._reset_results()
        self._refresh_compare_ready()

    def _on_drop_a(self, path: str) -> None:
        self._load_side("a", path)

    def _on_drop_b(self, path: str) -> None:
        self._load_side("b", path)

    def _pick_a(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("compare.image_a"), "", tr("compare.images_filter")
        )
        if path:
            self._load_side("a", path)

    def _pick_b(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("compare.image_b"), "", tr("compare.images_filter")
        )
        if path:
            self._load_side("b", path)

    def _swap_ab(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        self._path_a, self._path_b = self._path_b, self._path_a
        self._face_a, self._face_b = self._face_b, self._face_a
        self._image_a, self._image_b = self._image_b, self._image_a
        pix_a = QPixmap(self._path_a) if self._path_a else QPixmap()
        pix_b = QPixmap(self._path_b) if self._path_b else QPixmap()
        self.frame_a.set_source(
            f"{tr('compare.image_a')} · {Path(self._path_a).name}" if self._path_a
            else tr("compare.no_image_selected"),
            pix_a)
        self.frame_b.set_source(
            f"{tr('compare.image_b')} · {Path(self._path_b).name}" if self._path_b
            else tr("compare.no_image_selected"),
            pix_b)
        self._reset_results()
        self._refresh_compare_ready()

    def _refresh_compare_ready(self) -> None:
        ready = bool(self._path_a and self._path_b)
        self.compare_btn.setEnabled(ready)
        if not ready:
            self.export_btn.setEnabled(False)

    def _clear_all(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        self._path_a = None
        self._path_b = None
        self._face_a = None
        self._face_b = None
        self._image_a = None
        self._image_b = None
        self._last_result = None
        self.frame_a.canvas.set_image(QPixmap())
        self.frame_b.canvas.set_image(QPixmap())
        self.frame_a.canvas.set_image_info(None)
        self.frame_b.canvas.set_image_info(None)
        self.frame_a.clear_source()
        self.frame_b.clear_source()
        self._reset_results()
        self.status_label.setText(tr("compare.ready"))
        self._refresh_compare_ready()

    def _reset_results(self) -> None:
        self.steps.reset_all()
        self.gauge.reset()
        self.progress_bar.setValue(0)
        self.verdict_label.setText("")
        self.gauge_hint.setText(tr("compare.waiting"))
        self.attr_a_label.setText("")
        self.attr_b_label.setText("")
        self.elapsed_label.setText("")
        self._elapsed = 0.0
        for metric in (self.metric_dist, self.metric_sim, self.metric_pct,
                       self.metric_umbral, self.metric_estado):
            metric.setText("—")
        self.metric_umbral.setText(f"{settings.recognition.match_threshold}")

    # ------------------------------------------------------------------ #
    def _step_index(self, name: str) -> int:
        try:
            return STEP_NAMES.index(name)
        except ValueError:
            return -1

    def _panel_for_step(self, index: int) -> str | None:
        return {0: "a", 2: "a", 1: "b", 3: "b"}.get(index)

    def _canvas(self, panel: str) -> ScanCanvas:
        return self.frame_a.canvas if panel == "a" else self.frame_b.canvas

    def _disable_ui(self) -> None:
        self.compare_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        self.frame_a.select_button.setEnabled(False)
        self.frame_b.select_button.setEnabled(False)

    def _enable_ui(self) -> None:
        self.compare_btn.setEnabled(True)
        self.clear_btn.setEnabled(True)
        self.frame_a.select_button.setEnabled(True)
        self.frame_b.select_button.setEnabled(True)

    # ------------------------------------------------------------------ #
    def _compare(self) -> None:
        if not self._path_a or not self._path_b:
            QMessageBox.warning(self, tr("compare.missing_title"),
                                tr("compare.missing_msg"))
            return
        if self._worker and self._worker.isRunning():
            return

        self._disable_ui()
        self._reset_results()
        self._start_time = time.monotonic()
        self.status_label.setText(tr("compare.analyzing"))
        self.verdict_label.setText(tr("compare.analyzing_short"))

        self._worker = CompareWorker(self._path_a, self._path_b, self)
        self._worker.step_started.connect(self._on_step_started)
        self._worker.step_succeeded.connect(self._on_step_succeeded)
        self._worker.progress.connect(self.progress_bar.setValue)
        self._worker.finished_ok.connect(self._on_compare_done)
        self._worker.failed.connect(self._on_compare_error)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(100)
        self._elapsed_timer.timeout.connect(self._update_elapsed)
        self._elapsed_timer.start()

    def _update_elapsed(self) -> None:
        self._elapsed = time.monotonic() - self._start_time
        self.elapsed_label.setText(f"TIEMPO {self._elapsed:.1f}s")

    def _on_step_started(self, name: str) -> None:
        idx = self._step_index(name)
        self._active_step_idx = idx
        self.steps.set_active(idx)
        panel = self._panel_for_step(idx)
        if panel:
            self._canvas(panel).set_scanning(True)
            other = "b" if panel == "a" else "a"
            self._canvas(other).set_scanning(False)
        else:
            self.frame_a.canvas.set_scanning(False)
            self.frame_b.canvas.set_scanning(False)
        self.gauge_hint.setText(name)
        self.status_label.setText(name)

    def _on_step_succeeded(self, name: str, payload) -> None:
        idx = self._step_index(name)
        self.steps.mark_done(idx)
        panel = self._panel_for_step(idx)

        if isinstance(payload, np.ndarray):
            if panel:
                canvas = self._canvas(panel)
                canvas.set_image(_bgr_to_pixmap(payload))
                h, w = payload.shape[:2]
                canvas.set_image_info(f"{w}×{h} px")
                if panel == "a":
                    self._image_a = payload
                else:
                    self._image_b = payload
        elif payload is not None and hasattr(payload, "embedding"):
            if panel:
                canvas = self._canvas(panel)
                canvas.set_face(payload.bbox, payload.landmarks, payload.det_score)
                canvas.set_scanning(False)
            if "imagen A" in name:
                self._face_a = payload
            else:
                self._face_b = payload

    def _on_compare_done(self, data: dict) -> None:
        result = data["result"]
        es_misma = result["es_misma_persona_probable"]
        pct = result["porcentaje_similitud"]
        color = icons.COLOR_OK if es_misma else icons.COLOR_ERROR

        self.frame_a.canvas.set_scanning(False)
        self.frame_b.canvas.set_scanning(False)
        self._face_a = data.get("face_a")
        self._face_b = data.get("face_b")
        self._image_a = data.get("image_a")
        self._image_b = data.get("image_b")
        self._last_result = result

        for canvas, face in ((self.frame_a.canvas, self._face_a),
                             (self.frame_b.canvas, self._face_b)):
            if face is not None:
                canvas.set_face(face.bbox, face.landmarks, face.det_score)

        self._update_elapsed()
        if self._elapsed_timer:
            self._elapsed_timer.stop()

        self.gauge.set_value(pct, color)
        self.verdict_label.setText(
            icons.status_html("check_circle", tr("compare.match"), icons.COLOR_OK)
            if es_misma else
            icons.status_html("error", tr("compare.no_match"), icons.COLOR_ERROR)
        )
        self.gauge_hint.setText(tr("compare.completed"))
        self.status_label.setText(tr("compare.completed"))
        self.export_btn.setEnabled(True)

        self.metric_dist.setText(f"{result['distancia_coseno']}")
        self.metric_sim.setText(f"{result['similitud']}")
        self.metric_pct.setText(f"{pct}%")
        self.metric_umbral.setText(f"{result['umbral_usado']}")
        self.metric_estado.setText(
            tr("compare.same_person") if es_misma else tr("compare.different_persons")
        )
        self.metric_estado.setStyleSheet(
            f"color: {color}; font-weight: 700; font-size: 13px;"
        )

        self.attr_a_label.setText(self._face_attributes_text(self._face_a))
        self.attr_b_label.setText(self._face_attributes_text(self._face_b))
        self.elapsed_label.setText(f"TIEMPO {self._elapsed:.1f}s")

    @staticmethod
    def _face_attributes_text(face) -> str:
        if face is None:
            return ""
        parts = []
        if face.gender is not None:
            parts.append(tr("compare.female") if face.gender == "F" else tr("compare.male"))
        if face.age is not None:
            parts.append(tr("compare.age").format(face.age))
        return " · ".join(parts)

    def _on_compare_error(self, message: str) -> None:
        self.frame_a.canvas.set_scanning(False)
        self.frame_b.canvas.set_scanning(False)
        self.steps.mark_error(self._active_step_idx)
        if hasattr(self, "_elapsed_timer") and self._elapsed_timer:
            self._elapsed_timer.stop()
        self.status_label.setText(tr("video.error_prefix").format(message))
        self.verdict_label.setText(icons.status_html("error", tr("common.error"), icons.COLOR_ERROR))
        self.gauge_hint.setText(message)
        QMessageBox.warning(self, tr("compare.fail_title"), message)

    def _on_worker_finished(self) -> None:
        self._enable_ui()
        if self._worker:
            self._worker.deleteLater()
            self._worker = None

    # ------------------------------------------------------------------ #
    # Exportación del reporte de comparación (PNG)
    # ------------------------------------------------------------------ #
    def _export_report(self) -> None:
        if not self._last_result or self._image_a is None or self._image_b is None:
            return
        default_name = build_export_name(
            "reporte_comparacion_"
            f"{Path(self._path_a).stem if self._path_a else 'imagen_a'}_"
            f"{Path(self._path_b).stem if self._path_b else 'imagen_b'}",
            "png")
        path, _ = QFileDialog.getSaveFileName(
            self, tr("compare.save_report"), default_name,
            "PNG (*.png)")
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        try:
            self._render_report_png(path)
            audit_logger.info(
                "Reporte de comparación exportado | similitud={} | destino={}",
                self._last_result.get("porcentaje_similitud"), path)
            self.status_label.setText(tr("compare.report_saved").format(Path(path).name))
        except Exception as exc:  # noqa: BLE001
            logger.error("Error al exportar el reporte: {}", exc)
            QMessageBox.critical(self, tr("common.error"),
                                 tr("compare.report_failed").format(exc))

    def _render_report_png(self, path: str) -> None:
        W, H = 1360, 940
        MARGIN = 48
        GAP = 24
        result = self._last_result
        es_misma = result["es_misma_persona_probable"]
        color = QColor(icons.COLOR_OK if es_misma else icons.COLOR_ERROR)
        pct = result["porcentaje_similitud"]

        BG = QColor("#14151a")
        CARD = QColor("#1c1d24")
        BORDER = QColor("#2b2c36")
        TEXT = QColor("#ffffff")
        MUTED = QColor("#8f92a3")
        FAINT = QColor("#5b5e6b")
        ACCENT = QColor("#4f8cff")

        canvas = QPixmap(W, H)
        canvas.fill(BG)
        p = QPainter(canvas)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        font_h = QFont("Segoe UI", 24, QFont.Weight.Bold)
        font_cap = QFont("Segoe UI", 12, QFont.Weight.Bold)
        font_sub = QFont("Segoe UI", 11)
        font_mono = QFont("Consolas", 16, QFont.Weight.Bold)
        font_small = QFont("Consolas", 11)
        font_verdict = QFont("Segoe UI", 15, QFont.Weight.Bold)
        font_tiny = QFont("Segoe UI", 9)

        def text(x, y, w, h, s, f, c,
                 flags=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter):
            p.setFont(f)
            p.setPen(c)
            p.drawText(QRectF(x, y, w, h), flags, s)

        def pill(x, y, w, h, s, bg, fg, border=None, radius=None):
            r = radius if radius is not None else h // 2
            p.setPen(QPen(border, 1) if border else Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(QRectF(x, y, w, h), r, r)
            text(x, y, w, h, s, font_cap, fg, Qt.AlignmentFlag.AlignCenter)

        def draw_image_clipped(x, y, w, h, pm):
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(x, y, w, h), 10, 10)
            p.save()
            p.setClipPath(clip)
            p.drawPixmap(x, y, w, h, pm)
            p.restore()

        def draw_circular(pm, cx, cy, d, ring_color):
            p.save()
            clip = QPainterPath()
            clip.addEllipse(QRectF(cx - d / 2, cy - d / 2, d, d))
            p.setClipPath(clip)
            p.drawPixmap(int(cx - d / 2), int(cy - d / 2), d, d, pm)
            p.restore()
            p.setPen(QPen(QColor(ring_color), 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - d / 2, cy - d / 2, d, d))

        def face_headshot(img_bgr, face, diameter):
            """Recorta y devuelve un avatar circular del rostro detectado."""
            if face is None or face.bbox is None or img_bgr is None:
                return None
            h, w = img_bgr.shape[:2]
            x1, y1, x2, y2 = [max(0.0, v) for v in face.bbox]
            cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
            side = min(max(x2 - x1, y2 - y1) * 1.35, min(w, h) * 0.9)
            x0 = int(max(0, cx - side / 2))
            y0 = int(max(0, cy - side / 2))
            x1i = int(min(w, x0 + side))
            y1i = int(min(h, y0 + side))
            if x1i - x0 < 8 or y1i - y0 < 8:
                return None
            crop = img_bgr[y0:y1i, x0:x1i]
            crop_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
            h_c, w_c = crop_rgb.shape[:2]
            bytes_per_line = crop_rgb.shape[2] * w_c
            qimg = QImage(crop_rgb.data, w_c, h_c, bytes_per_line,
                          QImage.Format.Format_RGB888)
            pm = QPixmap.fromImage(qimg.copy())
            return pm.scaled(diameter, diameter, Qt.KeepAspectRatioByExpanding,
                             Qt.SmoothTransformation)

        # ---- Cabecera -----------------------------------------------------------
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ACCENT)
        p.drawRoundedRect(QRectF(MARGIN, 40, 6, 46), 3, 3)
        text(MARGIN + 22, 34, W - 2 * MARGIN - 300, 40,
             "Reporte de comparación biométrica", font_h, TEXT)
        text(MARGIN + 22, 82, W - 2 * MARGIN - 300, 20,
             "Comparador biométrico 1:1", font_sub, MUTED)

        badge = "COINCIDENCIA" if es_misma else "SIN COINCIDENCIA"
        bw, bh, bx = 250, 36, W - MARGIN - 250
        p.setPen(QPen(color, 2))
        p.setBrush(QColor(color.red(), color.green(), color.blue(), 26))
        p.drawRoundedRect(bx, 40, bw, bh, bh // 2, bh // 2)
        text(bx, 40, bw, bh, badge, font_cap, color, Qt.AlignmentFlag.AlignCenter)

        # ---- Dos tarjetas de imagen (simétricas) -------------------------------
        card_y = 158
        card_h = 440
        card_w = (W - 2 * MARGIN - GAP) // 2
        inner_pad = 14
        fname_a = Path(self._path_a).name if self._path_a else None
        fname_b = Path(self._path_b).name if self._path_b else None

        def _draw_image_card(ix, img, caption, face, fname):
            p.setPen(QPen(BORDER, 1))
            p.setBrush(CARD)
            p.drawRoundedRect(QRectF(ix, card_y, card_w, card_h), 14, 14)

            pill(ix + 16, card_y + 14, 116, 26, caption,
                 QColor("#262830"), TEXT, QColor("#3a3d48"))

            top = card_y + 52
            avail_w = card_w - 2 * inner_pad
            avail_h = card_h - 52 - inner_pad - 40
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
            pm = QPixmap.fromImage(qimg.copy())
            scaled = pm.scaled(avail_w, avail_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            dx = ix + inner_pad + (avail_w - scaled.width()) // 2
            dy = top + (avail_h - scaled.height()) // 2
            draw_image_clipped(dx, dy, scaled.width(), scaled.height(), scaled)

            if face is not None and face.bbox is not None:
                x1, y1, x2, y2 = [float(v) for v in face.bbox]
                sx = scaled.width() / w
                sy = scaled.height() / h
                bx1, by1 = dx + x1 * sx, dy + y1 * sy
                bw_, bh_ = max(1.0, (x2 - x1) * sx), max(1.0, (y2 - y1) * sy)

                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(color.red(), color.green(), color.blue(), 26))
                p.drawRoundedRect(QRectF(bx1, by1, bw_, bh_), 6, 6)

                bracket = 20
                pen = QPen(color, 3)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                for (cx_, cy_, sgnx, sgny) in (
                        (bx1, by1, 1, 1), (bx1 + bw_, by1, -1, 1),
                        (bx1, by1 + bh_, 1, -1), (bx1 + bw_, by1 + bh_, -1, -1)):
                    p.drawLine(QPointF(cx_, cy_), QPointF(cx_ + sgnx * bracket, cy_))
                    p.drawLine(QPointF(cx_, cy_), QPointF(cx_, cy_ + sgny * bracket))

                label = f"ROSTRO {face.det_score * 100:.0f}%"
                lw = max(96, 8 + len(label) * 9)
                lx = min(max(ix + inner_pad, bx1 + bw_ / 2 - lw / 2),
                         ix + card_w - inner_pad - lw)
                ly = by1 + bh_ + 10
                if ly + 22 > top + avail_h - 4:
                    ly = by1 - 26
                p.setPen(QPen(color, 1))
                p.setBrush(QColor(20, 21, 26, 235))
                p.drawRoundedRect(QRectF(lx, ly, lw, 20), 10, 10)
                text(lx, ly, lw, 20, label, font_tiny, color, Qt.AlignmentFlag.AlignCenter)

            d = 104
            hs = face_headshot(img, face, d)
            if hs is not None:
                hx = ix + card_w - 12 - d / 2
                hy = card_y + 44 + d / 2
                draw_circular(hs, hx, hy, d, color)

            info = f"{h}×{w} px"
            if fname:
                info += f"  ·  {fname}"
            text(ix + 18, card_y + card_h - 32, card_w - 36, 20, info, font_small, MUTED)

        _draw_image_card(MARGIN, self._image_a, "IMAGEN A", self._face_a, fname_a)
        _draw_image_card(MARGIN + card_w + GAP, self._image_b, "IMAGEN B", self._face_b,
                         fname_b)

        # ---- Tarjetas de métricas ---------------------------------------------
        metrics_y = 628
        metrics_h = 96
        metric_items = [
            ("Distancia coseno", f'{result["distancia_coseno"]}', None),
            ("Similitud coseno", f'{result["similitud"]}', None),
            ("Coincidencia", f"{pct}%", color),
            ("Umbral de match", f'{result["umbral_usado"]}', None),
        ]
        n = len(metric_items)
        card_w2 = (W - 2 * MARGIN - (n - 1) * GAP) // n
        for i, (label, value, accent) in enumerate(metric_items):
            mx = MARGIN + i * (card_w2 + GAP)
            p.setPen(QPen(BORDER, 1))
            p.setBrush(CARD)
            p.drawRoundedRect(QRectF(mx, metrics_y, card_w2, metrics_h), 12, 12)
            accent_c = accent or QColor("#3a3d48")
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(accent_c)
            p.drawRoundedRect(QRectF(mx + 16, metrics_y + 12, 22, 4), 2, 2)
            text(mx + 16, metrics_y + 24, card_w2 - 32, 18, label, font_sub, MUTED)
            text(mx + 16, metrics_y + 46, card_w2 - 32, 32, value, font_mono, TEXT)

        # ---- Barra de porcentaje + veredicto ----------------------------------
        text(MARGIN, 756, W - 2 * MARGIN, 20, "PORCENTAJE DE COINCIDENCIA",
             font_cap, MUTED, Qt.AlignmentFlag.AlignCenter)

        bar_w, bar_h = 640, 30
        bar_x = (W - bar_w) // 2
        bar_y = 792

        p.setPen(QPen(BORDER, 1))
        p.setBrush(QColor("#1e1f26"))
        p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), bar_h // 2, bar_h // 2)

        fill_w = int(bar_w * pct / 100.0)
        if fill_w > 0:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            fill_path = QPainterPath()
            fill_path.addRoundedRect(QRectF(bar_x, bar_y, max(1, fill_w), bar_h),
                                     bar_h // 2, bar_h // 2)
            p.drawPath(fill_path)

        tick_y = bar_y + bar_h + 6
        p.setPen(QPen(FAINT, 1))
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            tx = bar_x + bar_w * frac
            p.drawLine(QPointF(tx, tick_y), QPointF(tx, tick_y + 5))
        for frac, label in ((0.0, "0"), (0.25, "25"), (0.5, "50"),
                            (0.75, "75"), (1.0, "100")):
            text(bar_x + bar_w * frac - 24, tick_y + 8, 48, 14, label, font_tiny, FAINT,
                 Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)

        vp_x, vp_w, vp_h = bar_x + bar_w + 18, 92, bar_h
        p.setPen(QPen(color, 1))
        p.setBrush(QColor(color.red(), color.green(), color.blue(), 30))
        p.drawRoundedRect(QRectF(vp_x, bar_y, vp_w, vp_h), vp_h // 2, vp_h // 2)
        text(vp_x, bar_y, vp_w, vp_h, f"{pct:.1f}%", font_mono, color,
             Qt.AlignmentFlag.AlignCenter)

        verdict_line = "Misma persona (probable)" if es_misma else "Personas distintas"
        text(MARGIN, 866, W - 2 * MARGIN, 26, verdict_line, font_verdict, color,
             Qt.AlignmentFlag.AlignCenter)

        # ---- Pie de página ------------------------------------------------------
        p.setPen(QPen(QColor("#262830"), 1))
        p.drawLine(QPointF(MARGIN, 902), QPointF(W - MARGIN, 902))
        text(MARGIN, 908, W - 2 * MARGIN, 20,
             "FaceScan · Comparador biométrico 1:1", font_sub, FAINT)
        text(MARGIN, 908, W - 2 * MARGIN, 20,
             f"Generado el {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
             font_sub, FAINT, Qt.AlignmentFlag.AlignRight)

        p.end()
        canvas.save(path, "PNG")

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._elapsed_timer:
            self._elapsed_timer.stop()
        if self._worker is not None:
            self._worker.wait(2000)
        super().closeEvent(event)
