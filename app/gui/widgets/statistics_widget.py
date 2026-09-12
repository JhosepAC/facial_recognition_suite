"""
Vista de estadísticas — rediseñada.

Organizada en pestañas según el nivel del usuario:

- **Resumen**: KPIs esenciales + resumen ejecutivo en lenguaje natural +
  gráficos principales.
- **Personas**: crecimiento y distribución de la base registrada.
- **Reconocimiento**: actividad, horarios, personas más reconocidas y
  calidad de las coincidencias.
- **Técnico**: datos crudos (tablas) e información del sistema.

Incluye **actualización en tiempo real**: un temporizador refresca las
métricas y gráficos automáticamente mientras la aplicación está abierta
(intervalo configurable y desactivable), además del botón manual.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QFrame, QComboBox, QFileDialog, QMessageBox, QScrollArea, QTabWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox,
)

from app.core.config import settings
from app.database.session import get_session
from app.gui import icons
from app.i18n import bus as i18n_bus, tr
from app.services.statistics_service import StatisticsService
from app.services.export_service import ExportService, build_export_name
from app.core.logger import logger

_ORIGIN_DISPLAY = {"webcam": "Webcam", "video": "Video", "imagen": "Imagen"}

DAYS_OPTIONS = [("stats.days_7", 7), ("stats.days_30", 30),
                ("stats.days_90", 90), ("stats.days_year", 365)]

TABULAR_FORMATS = [
    ("stats.fmt_csv", "csv", ".csv"),
    ("stats.fmt_excel", "excel", ".xlsx"),
    ("stats.fmt_json", "json", ".json"),
]


def _figure_to_pixmap(fig) -> QPixmap:
    """Renderiza una figura de matplotlib (backend Agg) a un QPixmap, sin pasar por disco."""
    canvas = FigureCanvasAgg(fig)
    canvas.draw()
    w, h = canvas.get_width_height()
    buf = bytes(canvas.buffer_rgba())
    qimage = QImage(buf, w, h, QImage.Format_RGBA8888)
    pixmap = QPixmap.fromImage(qimage.copy())
    plt.close(fig)
    return pixmap


def _wrap_scroll(widget: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setWidget(widget)
    return scroll


# --------------------------------------------------------------------------- #
# Tarjeta de métrica (KPI) con icono, valor, etiqueta y subtítulo
# --------------------------------------------------------------------------- #
class MetricCard(QFrame):
    def __init__(self, title: str, value: str = "—", icon_name: str = "info",
                 icon_color: str = "#6fa8ff", caption: str = "",
                 description: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setMinimumWidth(180)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(6)
        self._info_labels: list[QLabel] = []
        icon_label = QLabel()
        icon_label.setPixmap(icons.pixmap(icon_name, 22, icon_color))
        if description:
            icon_label.setToolTip(description)
        top.addWidget(icon_label)
        if description:
            info_label = QLabel()
            info_label.setPixmap(icons.pixmap("info", 13, "#6b6e7d"))
            info_label.setToolTip(description)
            self._info_labels.append(info_label)
            top.addWidget(info_label)
        top.addStretch()
        lay.addLayout(top)

        self.value_label = QLabel(value)
        self.value_label.setObjectName("StatValue")
        lay.addWidget(self.value_label)

        self._title_label = QLabel(title)
        self._title_label.setObjectName("StatLabel")
        lay.addWidget(self._title_label)

        self.caption_label = QLabel(caption)
        self.caption_label.setStyleSheet("color: #6b6e7d; font-size: 11px;")
        self.caption_label.setWordWrap(True)
        lay.addWidget(self.caption_label)

    def set_value(self, value) -> None:
        self.value_label.setText(str(value))

    def set_caption(self, caption: str) -> None:
        self.caption_label.setText(caption)

    def retranslate(self, title: str, description: str) -> None:
        self._title_label.setText(title)
        for label in self._info_labels:
            label.setToolTip(description)


# --------------------------------------------------------------------------- #
# Tarjeta de gráfico con título y descripción (tooltip)
# --------------------------------------------------------------------------- #
class ChartCard(QFrame):
    def __init__(self, title: str, description: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        header = QHBoxLayout()
        self._title_label = QLabel(title)
        self._title_label.setStyleSheet("font-size: 14px; font-weight: 700;")
        header.addWidget(self._title_label)
        self._info_labels: list[QLabel] = []
        if description:
            info_label = QLabel()
            info_label.setPixmap(icons.pixmap("info", 15, "#6b6e7d"))
            info_label.setToolTip(description)
            self._info_labels.append(info_label)
            header.addWidget(info_label)
        header.addStretch()
        lay.addLayout(header)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(380, 260)
        self.image_label.setText("—")
        self.image_label.setStyleSheet("color: #8f92a3;")
        lay.addWidget(self.image_label)

    def set_figure(self, fig) -> None:
        self.image_label.setPixmap(_figure_to_pixmap(fig) if fig is not None else QPixmap())

    def retranslate(self, title: str, description: str) -> None:
        self._title_label.setText(title)
        for label in self._info_labels:
            label.setToolTip(description)


# --------------------------------------------------------------------------- #
# Widget principal
# --------------------------------------------------------------------------- #
class StatisticsWidget(QWidget):
    _INTERVALS_MS = [5_000, 15_000, 30_000, 60_000, 300_000]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._days = 30
        self._card_keys: list[tuple] = []

        def _reg(obj, title_key, desc_key=""):
            self._card_keys.append((obj, title_key, desc_key))

        self._reg = _reg
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timer_tick)
        self._apply_auto_state()
        self.refresh()
        i18n_bus().languageChanged.connect(self._retranslate)

    def _retranslate(self) -> None:
        self.tabs.setTabText(0, tr("stats.tab_summary"))
        self.tabs.setTabText(1, tr("stats.tab_persons"))
        self.tabs.setTabText(2, tr("stats.tab_recognition"))
        self.tabs.setTabText(3, tr("stats.tab_technical"))
        self._title.setText(tr("stats.title"))
        self._subtitle.setText(tr("stats.subtitle"))
        self._period_label.setText(tr("stats.period"))
        self._auto_check.setText(tr("stats.auto"))
        self._auto_check.setToolTip(tr("stats.auto_tooltip"))
        self._interval_combo.setToolTip(tr("stats.interval_tooltip"))
        self._refresh_btn.setText(tr("stats.refresh"))
        self._retranslate_days()
        self._retranslate_format()
        self._export_persons_btn.setText(tr("stats.export_persons"))
        self._export_events_btn.setText(tr("stats.export_events"))
        self._export_pdf_btn.setText(tr("stats.export_pdf"))
        self._backup_btn.setText(tr("stats.backup_db"))
        self._export_title.setText(tr("stats.export_title"))
        self._format_label.setText(tr("stats.format"))
        self._retranslate_cards()

    def _retranslate_days(self) -> None:
        current = self.days_combo.currentData()
        self.days_combo.clear()
        for key, _days in DAYS_OPTIONS:
            self.days_combo.addItem(tr(key), _days)
        if current is not None:
            idx = next((i for i in range(self.days_combo.count())
                        if self.days_combo.itemData(i) == current), 1)
            self.days_combo.setCurrentIndex(idx)

    def _retranslate_format(self) -> None:
        current = self.format_combo.currentIndex()
        self.format_combo.clear()
        for label, _fmt, _ext in TABULAR_FORMATS:
            self.format_combo.addItem(tr(label))
        self.format_combo.setCurrentIndex(current)

    def _retranslate_cards(self) -> None:
        for obj, title_key, desc_key in self._card_keys:
            obj.retranslate(tr(title_key), tr(desc_key) if desc_key else "")

    # ------------------------------------------------------------------ #
    # Construcción de la interfaz
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)
        root.addLayout(self._build_header())

        self.tabs = QTabWidget()
        self.tabs.addTab(_wrap_scroll(self._build_resumen_tab()), tr("stats.tab_summary"))
        self.tabs.addTab(_wrap_scroll(self._build_personas_tab()), tr("stats.tab_persons"))
        self.tabs.addTab(_wrap_scroll(self._build_reconocimiento_tab()), tr("stats.tab_recognition"))
        self.tabs.addTab(_wrap_scroll(self._build_tecnico_tab()), tr("stats.tab_technical"))
        self.tabs.currentChanged.connect(lambda _i: self.refresh(all_tabs=False))
        root.addWidget(self.tabs, stretch=1)

        root.addWidget(self._build_export_card())

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(12)
        header.addWidget(icons.icon_label("chart", 26, "#6fa8ff"))

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        self._title = QLabel(tr("stats.title"))
        self._title.setStyleSheet("font-size: 22px; font-weight: 700;")
        self._subtitle = QLabel(tr("stats.subtitle"))
        self._subtitle.setStyleSheet("color: #8f92a3; font-size: 12px;")
        title_col.addWidget(self._title)
        title_col.addWidget(self._subtitle)
        header.addLayout(title_col)
        header.addStretch()

        self._period_label = QLabel(tr("stats.period"))
        header.addWidget(self._period_label)
        self.days_combo = QComboBox()
        for label, _days in DAYS_OPTIONS:
            self.days_combo.addItem(tr(label), _days)
        self.days_combo.setCurrentIndex(1)
        self.days_combo.currentIndexChanged.connect(lambda _i: self.refresh())
        header.addWidget(self.days_combo)

        self.last_update_label = QLabel("—")
        self.last_update_label.setStyleSheet("color: #6b6e7d; font-size: 11px;")
        header.addWidget(self.last_update_label)

        self._auto_check = QCheckBox(tr("stats.auto"))
        self._auto_check.setChecked(True)
        self._auto_check.setToolTip(tr("stats.auto_tooltip"))
        self._auto_check.toggled.connect(self._apply_auto_state)
        header.addWidget(self._auto_check)

        self._interval_combo = QComboBox()
        for label in ["5 s", "15 s", "30 s", "1 min", "5 min"]:
            self._interval_combo.addItem(label)
        self._interval_combo.setCurrentIndex(1)
        self._interval_combo.setToolTip(tr("stats.interval_tooltip"))
        self._interval_combo.currentIndexChanged.connect(self._apply_auto_state)
        header.addWidget(self._interval_combo)

        self._refresh_btn = QPushButton(tr("stats.refresh"))
        self._refresh_btn.setIcon(icons.icon("refresh", 16, "#ffffff"))
        self._refresh_btn.setCursor(Qt.PointingHandCursor)
        self._refresh_btn.clicked.connect(self.refresh)
        header.addWidget(self._refresh_btn)
        return header

    # ------------------------------------------------------------------ #
    # Pestaña Resumen
    # ------------------------------------------------------------------ #
    def _build_resumen_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(16)

        kpi_grid = QGridLayout()
        kpi_grid.setSpacing(12)
        self.card_personas = MetricCard("", "0", "people", "#6fa8ff")
        self._reg(self.card_personas, "stats.card_persons", "stats.card_persons_desc")
        self.card_fotos = MetricCard("", "0", "photo_library", "#46c37b")
        self._reg(self.card_fotos, "stats.card_photos", "stats.card_photos_desc")
        self.card_eventos = MetricCard("", "0", "search", "#f2b134")
        self._reg(self.card_eventos, "stats.card_events", "stats.card_events_desc")
        self.card_hoy = MetricCard("", "0", "schedule", "#3fc7c1")
        self._reg(self.card_hoy, "stats.card_today", "stats.card_today_desc")
        self.card_tasa = MetricCard("", "0%", "check_circle", "#46c37b")
        self._reg(self.card_tasa, "stats.card_rate", "stats.card_rate_desc")
        self.card_confianza = MetricCard("", "—", "star", "#a06cd5")
        self._reg(self.card_confianza, "stats.card_avg_conf", "stats.card_avg_conf_desc")

        for card, (r, c) in zip(
                (self.card_personas, self.card_fotos, self.card_eventos,
                 self.card_hoy, self.card_tasa, self.card_confianza),
                ((0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2))):
            kpi_grid.addWidget(card, r, c)
        lay.addLayout(kpi_grid)

        summary_card = QFrame()
        summary_card.setObjectName("Card")
        summary_lay = QVBoxLayout(summary_card)
        summary_lay.setContentsMargins(16, 14, 16, 14)
        summary_lay.setSpacing(6)
        summary_title = QLabel(tr("stats.summary_title"))
        summary_title.setStyleSheet("font-size: 15px; font-weight: 700;")
        summary_lay.addWidget(summary_title)
        self.summary_text_label = QLabel(tr("stats.loading"))
        self.summary_text_label.setWordWrap(True)
        self.summary_text_label.setStyleSheet(
            "color: #c9cbd4; font-size: 13px; line-height: 1.4;")
        summary_lay.addWidget(self.summary_text_label)
        lay.addWidget(summary_card)

        charts = QGridLayout()
        charts.setSpacing(16)
        self.chart_growth = ChartCard("", "")
        self._reg(self.chart_growth, "stats.chart_growth", "stats.chart_growth_desc")
        self.chart_activity = ChartCard("", "")
        self._reg(self.chart_activity, "stats.chart_activity", "stats.chart_activity_desc")
        self.chart_origen = ChartCard("", "")
        self._reg(self.chart_origen, "stats.chart_origin", "stats.chart_origin_desc")
        self.chart_confidence = ChartCard("", "")
        self._reg(self.chart_confidence, "stats.chart_confidence", "stats.chart_confidence_desc")
        charts.addWidget(self.chart_growth, 0, 0)
        charts.addWidget(self.chart_activity, 0, 1)
        charts.addWidget(self.chart_confidence, 1, 0)
        charts.addWidget(self.chart_origen, 1, 1)
        lay.addLayout(charts)
        lay.addStretch()
        return w

    # ------------------------------------------------------------------ #
    # Pestaña Personas
    # ------------------------------------------------------------------ #
    def _build_personas_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(16)

        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(12)
        self.card_personas_con_fotos = MetricCard("", "0", "photo_library", "#46c37b")
        self._reg(self.card_personas_con_fotos, "stats.card_with_photos", "stats.card_with_photos_desc")
        self.card_personas_sin_fotos = MetricCard("", "0", "image", "#e85d5d")
        self._reg(self.card_personas_sin_fotos, "stats.card_without_photos", "stats.card_without_photos_desc")
        self.card_promedio_fotos = MetricCard("", "0", "image", "#6fa8ff")
        self._reg(self.card_promedio_fotos, "stats.card_avg_photos", "stats.card_avg_photos_desc")
        self.card_embeddings = MetricCard("", "0", "fingerprint", "#a06cd5")
        self._reg(self.card_embeddings, "stats.card_embeddings", "stats.card_embeddings_desc")
        for card in (self.card_personas_con_fotos, self.card_personas_sin_fotos,
                     self.card_promedio_fotos, self.card_embeddings):
            kpi_row.addWidget(card)
        kpi_row.addStretch()
        lay.addLayout(kpi_row)

        self.chart_growth_full = ChartCard("", "")
        self._reg(self.chart_growth_full, "stats.chart_growth_full", "stats.chart_growth_full_desc")
        lay.addWidget(self.chart_growth_full)

        dist = QGridLayout()
        dist.setSpacing(16)
        self.chart_empresa = ChartCard("", "")
        self._reg(self.chart_empresa, "stats.chart_company", "stats.chart_company_desc")
        self.chart_departamento = ChartCard("", "")
        self._reg(self.chart_departamento, "stats.chart_department", "stats.chart_department_desc")
        self.chart_sexo = ChartCard("", "")
        self._reg(self.chart_sexo, "stats.chart_sex", "stats.chart_sex_desc")
        self.chart_cargo = ChartCard("", "")
        self._reg(self.chart_cargo, "stats.chart_role", "stats.chart_role_desc")
        dist.addWidget(self.chart_empresa, 0, 0)
        dist.addWidget(self.chart_departamento, 0, 1)
        dist.addWidget(self.chart_sexo, 1, 0)
        dist.addWidget(self.chart_cargo, 1, 1)
        lay.addLayout(dist)

        self.chart_attrs = ChartCard("", "")
        self._reg(self.chart_attrs, "stats.chart_attrs", "stats.chart_attrs_desc")
        lay.addWidget(self.chart_attrs)

        color_grid = QGridLayout()
        color_grid.setSpacing(16)
        self.chart_eye_color = ChartCard("", "")
        self._reg(self.chart_eye_color, "stats.chart_eye_color",
                  "stats.chart_eye_color_desc")
        self.chart_hair_color = ChartCard("", "")
        self._reg(self.chart_hair_color, "stats.chart_hair_color",
                  "stats.chart_hair_color_desc")
        color_grid.addWidget(self.chart_eye_color, 0, 0)
        color_grid.addWidget(self.chart_hair_color, 0, 1)
        lay.addLayout(color_grid)
        lay.addStretch()
        return w

    # ------------------------------------------------------------------ #
    # Pestaña Reconocimiento
    # ------------------------------------------------------------------ #
    def _build_reconocimiento_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(16)

        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(12)
        self.card_ev_periodo = MetricCard("", "0", "search", "#f2b134")
        self._reg(self.card_ev_periodo, "stats.card_events_period", "stats.card_events_period_desc")
        self.card_ev_match = MetricCard("", "0", "check_circle", "#46c37b")
        self._reg(self.card_ev_match, "stats.card_matches", "stats.card_matches_desc")
        self.card_ev_unknown = MetricCard("", "0", "warning", "#e85d5d")
        self._reg(self.card_ev_unknown, "stats.card_unknown", "stats.card_unknown_desc")
        self.card_tasa_periodo = MetricCard("", "0%", "star", "#a06cd5")
        self._reg(self.card_tasa_periodo, "stats.card_rate_period", "stats.card_rate_period_desc")
        for card in (self.card_ev_periodo, self.card_ev_match, self.card_ev_unknown,
                     self.card_tasa_periodo):
            kpi_row.addWidget(card)
        kpi_row.addStretch()
        lay.addLayout(kpi_row)

        self.chart_daily = ChartCard("", "")
        self._reg(self.chart_daily, "stats.chart_activity", "stats.chart_activity_desc")
        lay.addWidget(self.chart_daily)

        grid = QGridLayout()
        grid.setSpacing(16)
        self.chart_week = ChartCard("", "")
        self._reg(self.chart_week, "stats.chart_weekday", "stats.chart_weekday_desc")
        self.chart_hour = ChartCard("", "")
        self._reg(self.chart_hour, "stats.chart_hour", "stats.chart_hour_desc")
        self.chart_top = ChartCard("", "")
        self._reg(self.chart_top, "stats.chart_top", "stats.chart_top_desc")
        self.chart_conf_time = ChartCard("", "")
        self._reg(self.chart_conf_time, "stats.chart_conf_time", "stats.chart_conf_time_desc")
        self.chart_conf_origin = ChartCard("", "")
        self._reg(self.chart_conf_origin, "stats.chart_conf_origin", "stats.chart_conf_origin_desc")
        self.chart_mv = ChartCard("", "")
        self._reg(self.chart_mv, "stats.chart_match_unknown", "stats.chart_match_unknown_desc")
        grid.addWidget(self.chart_week, 0, 0)
        grid.addWidget(self.chart_hour, 0, 1)
        grid.addWidget(self.chart_top, 1, 0)
        grid.addWidget(self.chart_conf_time, 1, 1)
        grid.addWidget(self.chart_conf_origin, 2, 0)
        grid.addWidget(self.chart_mv, 2, 1)
        lay.addLayout(grid)
        lay.addStretch()
        return w

    # ------------------------------------------------------------------ #
    # Pestaña Técnico
    # ------------------------------------------------------------------ #
    def _build_tecnico_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(16)

        self._events_title = QLabel(tr("stats.events_title"))
        self._events_title.setStyleSheet("font-size: 15px; font-weight: 700;")
        lay.addWidget(self._events_title)

        self.events_table = QTableWidget(0, 4)
        self.events_table.setHorizontalHeaderLabels(
            [tr("stats.col_date"), tr("stats.col_origin"),
             tr("webcam.event_name"), tr("webcam.event_confidence")])
        self.events_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents)
        self.events_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents)
        self.events_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.events_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeToContents)
        self.events_table.verticalHeader().setVisible(False)
        self.events_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.events_table.setMaximumHeight(280)
        lay.addWidget(self.events_table)

        self._metrics_title = QLabel(tr("stats.metrics_title"))
        self._metrics_title.setStyleSheet("font-size: 15px; font-weight: 700; margin-top: 8px;")
        lay.addWidget(self._metrics_title)

        self.metrics_table = QTableWidget(0, 2)
        self.metrics_table.setHorizontalHeaderLabels([tr("stats.col_metric"), tr("stats.col_value")])
        self.metrics_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.metrics_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents)
        self.metrics_table.verticalHeader().setVisible(False)
        self.metrics_table.setEditTriggers(QTableWidget.NoEditTriggers)
        lay.addWidget(self.metrics_table)

        self.db_info_label = QLabel("")
        self.db_info_label.setStyleSheet(
            "color: #6b6e7d; font-size: 12px; font-family: 'Consolas';")
        self.db_info_label.setWordWrap(True)
        lay.addWidget(self.db_info_label)
        lay.addStretch()
        return w

    # ------------------------------------------------------------------ #
    # Panel de exportación
    # ------------------------------------------------------------------ #
    def _build_export_card(self) -> QFrame:
        export_frame = QFrame()
        export_frame.setObjectName("Card")
        export_layout = QVBoxLayout(export_frame)
        export_layout.setContentsMargins(16, 14, 16, 14)
        export_layout.setSpacing(10)

        self._export_title = QLabel(tr("stats.export_title"))
        self._export_title.setStyleSheet("font-size: 16px; font-weight: 600;")
        export_layout.addWidget(self._export_title)

        tabular_row = QHBoxLayout()
        self._format_label = QLabel(tr("stats.format"))
        tabular_row.addWidget(self._format_label)
        self.format_combo = QComboBox()
        for label, _fmt, _ext in TABULAR_FORMATS:
            self.format_combo.addItem(tr(label))
        tabular_row.addWidget(self.format_combo)

        self._export_persons_btn = QPushButton(tr("stats.export_persons"))
        self._export_persons_btn.setObjectName("SecondaryButton")
        self._export_persons_btn.clicked.connect(self._export_persons)
        tabular_row.addWidget(self._export_persons_btn)

        self._export_events_btn = QPushButton(tr("stats.export_events"))
        self._export_events_btn.setObjectName("SecondaryButton")
        self._export_events_btn.clicked.connect(self._export_events)
        tabular_row.addWidget(self._export_events_btn)
        tabular_row.addStretch()
        export_layout.addLayout(tabular_row)

        other_row = QHBoxLayout()
        self._export_pdf_btn = QPushButton(tr("stats.export_pdf"))
        self._export_pdf_btn.clicked.connect(self._export_pdf)
        other_row.addWidget(self._export_pdf_btn)

        self._backup_btn = QPushButton(tr("stats.backup_db"))
        self._backup_btn.setObjectName("SecondaryButton")
        self._backup_btn.clicked.connect(self._backup_database)
        other_row.addWidget(self._backup_btn)
        other_row.addStretch()
        export_layout.addLayout(other_row)

        self.export_status_label = QLabel("")
        self.export_status_label.setStyleSheet("color: #8f92a3;")
        self.export_status_label.setWordWrap(True)
        export_layout.addWidget(self.export_status_label)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #8f92a3;")
        self.status_label.setWordWrap(True)
        export_layout.addWidget(self.status_label)
        return export_frame

    # ------------------------------------------------------------------ #
    # Utilidades
    # ------------------------------------------------------------------ #
    def _selected_days(self) -> int:
        return DAYS_OPTIONS[self.days_combo.currentIndex()][1]

    def _selected_format(self) -> tuple[str, str]:
        _label, fmt, ext = TABULAR_FORMATS[self.format_combo.currentIndex()]
        return fmt, ext

    def _apply_auto_state(self) -> None:
        if self._auto_check.isChecked():
            self._timer.start(self._INTERVALS_MS[self._interval_combo.currentIndex()])
        else:
            self._timer.stop()

    def _on_timer_tick(self) -> None:
        self.refresh(all_tabs=False)

    # ------------------------------------------------------------------ #
    # Refresco (tiempo real)
    # ------------------------------------------------------------------ #
    def refresh(self, all_tabs: bool = True) -> None:
        self._days = self._selected_days()
        try:
            with get_session() as session:
                stats = StatisticsService(session)
                summary = stats.summary_counts(self._days)
                self._update_kpis(summary)
                self._update_summary_text(summary)
                if all_tabs:
                    self._render_resumen(stats)
                    self._render_personas(stats)
                    self._render_reconocimiento(stats)
                    self._render_tecnico(stats, summary)
                else:
                    idx = min(max(self.tabs.currentIndex(), 0), 3)
                    if idx == 0:
                        self._render_resumen(stats)
                    elif idx == 1:
                        self._render_personas(stats)
                    elif idx == 2:
                        self._render_reconocimiento(stats)
                    else:
                        self._render_tecnico(stats, summary)
            self.status_label.setText("")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error al refrescar estadísticas")
            self.status_label.setText(icons.err(tr("stats.error_update").format(exc)))
        self.last_update_label.setText(
            tr("stats.last_update").format(datetime.now().strftime("%H:%M:%S")))

    def _update_kpis(self, s: dict) -> None:
        # Resumen
        self.card_personas.set_value(s["total_personas"])
        self.card_personas.set_caption(f"{s['personas_periodo']} alta(s) en el período")
        self.card_fotos.set_value(s["fotos_totales"])
        self.card_fotos.set_caption(f"{s['personas_con_fotos']} personas con fotos")
        self.card_eventos.set_value(s["total_eventos"])
        self.card_eventos.set_caption(f"{s['eventos_ultima_hora']} en la última hora")
        self.card_hoy.set_value(s["eventos_hoy"])
        self.card_hoy.set_caption(f"{s['eventos_match']} coincidencias")
        self.card_tasa.set_value(f"{s['tasa_reconocimiento_pct']}%")
        origin_text = " · ".join(
            f"{_ORIGIN_DISPLAY.get(o, o)} {v['tasa']}%"
            for o, v in s.get("tasa_reconocimiento_por_origen", {}).items()
        )
        caption = f"{s['eventos_match']}/{s['total_eventos']} exitosos"
        if origin_text:
            caption += f"  —  {origin_text}"
        self.card_tasa.set_caption(caption)
        self.card_confianza.set_value(
            f"{s['confianza_promedio']}%" if s["confianza_promedio"] is not None else "—")
        self.card_confianza.set_caption(
            f"máx {s['confianza_maxima']}% · mín {s['confianza_minima']}%"
            if s["confianza_maxima"] is not None else "Sin coincidencias")

        # Personas
        self.card_personas_con_fotos.set_value(s["personas_con_fotos"])
        self.card_personas_sin_fotos.set_value(s["personas_sin_fotos"])
        self.card_promedio_fotos.set_value(s["avg_fotos_por_persona"])
        self.card_embeddings.set_value(s["embeddings_totales"])

    def _update_summary_text(self, s: dict) -> None:
        parts = [
            f"Actualmente hay <b>{s['total_personas']}</b> persona(s) registrada(s) "
            f"con <b>{s['fotos_totales']}</b> fotografía(s) en el dataset."
        ]
        if s["total_eventos"]:
            parts.append(
                f"Se registraron <b>{s['total_eventos']}</b> eventos de reconocimiento: "
                f"<b>{s['eventos_match']}</b> fueron coincidencias "
                f"({s['tasa_reconocimiento_pct']}%) y <b>{s['eventos_sin_match']}</b> "
                "correspondieron a personas desconocidas."
            )
            por_origen = s.get("tasa_reconocimiento_por_origen", {})
            if por_origen:
                detalle = " · ".join(
                    f"{_ORIGIN_DISPLAY.get(o, o)}: {v['tasa']}%"
                    for o, v in por_origen.items()
                )
                parts.append(
                    f"Tasa por origen — {detalle}. Webcam y video solo registran "
                    "coincidencias, así que su tasa no es directamente comparable "
                    "con la de imágenes."
                )
            if s["confianza_promedio"] is not None:
                parts.append(
                    f"La confianza promedio de las coincidencias es "
                    f"<b>{s['confianza_promedio']}%</b> (máximo {s['confianza_maxima']}%)."
                )
        if s["eventos_hoy"]:
            parts.append(f"<b>{s['eventos_hoy']}</b> reconocimiento(s) ocurrieron hoy.")
        if s["top_empresa"]:
            parts.append(
                f"La empresa con más registros es <b>{s['top_empresa']}</b> "
                f"({s['top_empresa_count']} persona(s))."
            )
        self.summary_text_label.setText(" ".join(parts) + " ")

    # ------------------------------------------------------------------ #
    def _render_resumen(self, stats: StatisticsService) -> None:
        self.chart_growth.set_figure(stats.chart_persons_growth())
        self.chart_activity.set_figure(stats.chart_daily_activity(self._days))
        self.chart_confidence.set_figure(stats.chart_confidence_distribution())
        self.chart_origen.set_figure(stats.chart_recognitions_by_origin())

    def _render_personas(self, stats: StatisticsService) -> None:
        self.chart_growth_full.set_figure(stats.chart_persons_growth())
        self.chart_empresa.set_figure(
            stats.chart_distribution_by_field("empresa", "Personas por empresa"))
        self.chart_departamento.set_figure(
            stats.chart_distribution_by_field("departamento", "Personas por departamento"))
        self.chart_sexo.set_figure(
            stats.chart_distribution_by_field("sexo", "Personas por sexo"))
        self.chart_cargo.set_figure(
            stats.chart_distribution_by_field("cargo", "Personas por cargo"))
        self.chart_attrs.set_figure(stats.chart_attributes_distribution())
        self.chart_eye_color.set_figure(
            stats.chart_color_distribution("color_ojos", tr("stats.chart_eye_color")))
        self.chart_hair_color.set_figure(
            stats.chart_color_distribution("color_pelo", tr("stats.chart_hair_color")))

    def _render_reconocimiento(self, stats: StatisticsService) -> None:
        d = stats.match_vs_unknown_counts(self._days)
        self.card_ev_periodo.set_value(d["total"])
        self.card_ev_match.set_value(d["match"])
        self.card_ev_unknown.set_value(d["unknown"])
        tasa = round((d["match"] / d["total"]) * 100, 1) if d["total"] else 0
        self.card_tasa_periodo.set_value(f"{tasa}%")

        self.chart_daily.set_figure(stats.chart_daily_activity(self._days))
        self.chart_week.set_figure(stats.chart_weekly_activity(self._days))
        self.chart_hour.set_figure(stats.chart_activity_by_hour(self._days))
        self.chart_top.set_figure(stats.chart_top_persons())
        self.chart_conf_time.set_figure(stats.chart_confidence_over_time(self._days))
        self.chart_conf_origin.set_figure(stats.chart_confidence_by_origin())
        self.chart_mv.set_figure(stats.chart_match_vs_unknown(self._days))

    def _render_tecnico(self, stats: StatisticsService, summary: dict) -> None:
        df = stats.recent_events_df(50)
        self.events_table.setRowCount(len(df))
        for i, r in df.iterrows():
            fecha = r["fecha"]
            texto_fecha = fecha.strftime("%d/%m/%Y %H:%M") if hasattr(fecha, "strftime") else str(fecha)
            self.events_table.setItem(i, 0, QTableWidgetItem(texto_fecha))
            self.events_table.setItem(i, 1, QTableWidgetItem(str(r["origen"])))
            self.events_table.setItem(i, 2, QTableWidgetItem(str(r["persona"])))
            conf = r["confianza"]
            item_conf = QTableWidgetItem(f"{conf:.1f}%" if conf is not None else "—")
            item_conf.setForeground(
                QColor(icons.COLOR_OK) if conf is not None else QColor("#8f92a3"))
            item_conf.setTextAlignment(Qt.AlignCenter)
            self.events_table.setItem(i, 3, item_conf)

        d = stats.match_vs_unknown_counts(self._days)
        metrics = [
            ("Personas registradas (total)", summary["total_personas"]),
            (f"Altas en el período ({self._days} días)", summary["personas_periodo"]),
            ("Personas con fotografías", summary["personas_con_fotos"]),
            ("Personas sin fotografías", summary["personas_sin_fotos"]),
            ("Fotografías en el dataset", summary["fotos_totales"]),
            ("Embeddings biométricos", summary["embeddings_totales"]),
            ("Promedio de fotos por persona", summary["avg_fotos_por_persona"]),
            ("Eventos de reconocimiento (total)", summary["total_eventos"]),
            ("Eventos hoy", summary["eventos_hoy"]),
            ("Eventos en la última hora", summary["eventos_ultima_hora"]),
            (f"Eventos en el período ({self._days} días)", d["total"]),
            ("Coincidencias (período)", d["match"]),
            ("Desconocidos (período)", d["unknown"]),
            ("Tasa de reconocimiento", f"{summary['tasa_reconocimiento_pct']}%"),
            ("Confianza promedio", f"{summary['confianza_promedio']}%"
                if summary["confianza_promedio"] is not None else "—"),
            ("Confianza máxima", f"{summary['confianza_maxima']}%"
                if summary["confianza_maxima"] is not None else "—"),
            ("Confianza mínima", f"{summary['confianza_minima']}%"
                if summary["confianza_minima"] is not None else "—"),
        ]
        self.metrics_table.setRowCount(len(metrics))
        for i, (k, v) in enumerate(metrics):
            self.metrics_table.setItem(i, 0, QTableWidgetItem(k))
            self.metrics_table.setItem(i, 1, QTableWidgetItem(str(v)))

        db_path = settings.resolve_path(settings.database.path)
        try:
            size_kb = db_path.stat().st_size / 1024
            self.db_info_label.setText(
                f"Base de datos: {db_path} · Tamaño: {size_kb:.1f} KB · "
                f"Engine: SQLite / SQLAlchemy")
        except OSError:
            self.db_info_label.setText(f"Base de datos: {db_path}")

    # ------------------------------------------------------------------ #
    # Exportación
    # ------------------------------------------------------------------ #
    def _export_persons(self) -> None:
        fmt, ext = self._selected_format()
        path, _ = QFileDialog.getSaveFileName(self, tr("stats.export_dialog_persons"),
                                               build_export_name("personas", ext),
                                               tr("stats.files_filter").format(ext))
        if not path:
            return
        try:
            with get_session() as session:
                count = ExportService(session).export_persons(path, fmt)
            self.export_status_label.setText(icons.ok(tr("stats.exported_ok").format(count, path)))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error exportando personas")
            QMessageBox.warning(self, tr("stats.export_error_title"),
                                tr("stats.export_error_msg").format(exc))

    def _export_events(self) -> None:
        fmt, ext = self._selected_format()
        path, _ = QFileDialog.getSaveFileName(self, tr("stats.export_dialog_events"),
                                               build_export_name("eventos_reconocimiento", ext),
                                               tr("stats.files_filter").format(ext))
        if not path:
            return
        try:
            with get_session() as session:
                count = ExportService(session).export_recognition_events(path, fmt)
            self.export_status_label.setText(
                icons.ok(tr("stats.exported_events_ok").format(count, path)))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error exportando eventos")
            QMessageBox.warning(self, tr("stats.export_error_title"),
                                tr("stats.export_error_msg").format(exc))

    def _export_pdf(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, tr("stats.export_dialog_pdf"),
                                               build_export_name("reporte_estadisticas", "pdf"),
                                               "PDF (*.pdf)")
        if not path:
            return
        try:
            with get_session() as session:
                ExportService(session).export_statistics_pdf(path, days=self._days)
            self.export_status_label.setText(icons.ok(tr("stats.pdf_ok").format(path)))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error generando reporte PDF")
            QMessageBox.warning(self, tr("stats.export_error_title"),
                                tr("stats.export_error_msg").format(exc))

    def _backup_database(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, tr("stats.export_dialog_backup"),
                                               build_export_name("biovision_backup", "db"),
                                               "SQLite (*.db)")
        if not path:
            return
        try:
            with get_session() as session:
                ExportService(session).backup_database(path)
            self.export_status_label.setText(
                icons.ok(tr("stats.backup_ok").format(path)))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error generando respaldo")
            QMessageBox.warning(self, tr("stats.backup_error_title"),
                                tr("stats.export_error_msg").format(exc))
