"""Export service. Covers the "Exports" module of the spec:
  - CSV, Excel, JSON: persons and recognition events (tabular).
  - PDF: statistics report with KPIs and charts.
  - SQLite: consistent backup of the entire database.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.logger import audit_logger
from app.database.models import Person, RecognitionEvent
from app.services.statistics_service import StatisticsService, primary_embedding_attrs
from app.utils.spreadsheet import sanitize_formula
from app.vision.face_attributes import ATTR_FIELDS

SUPPORTED_TABULAR_FORMATS = ("csv", "excel", "json")


def slugify(value: str, default: str = "archivo") -> str:
    """Convert text to a safe slug for filenames (without accents)."""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", ascii_text).strip("_")
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or default


def build_export_name(slug: str, ext: str = "") -> str:
    """Nombre representativo con fecha: <slug>_<AAAAMMDD_HHMMSS>.<ext>.

    Incluye un sufijo aleatorio corto para que dos exportaciones generadas el
    mismo segundo no se sobrescriban entre sí.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f".{ext.lstrip('.')}" if ext else ""
    return f"{slug}_{ts}_{uuid.uuid4().hex[:4]}{suffix}"


class ExportService:
    def __init__(self, session: Session):
        self.session = session

    # ------------------------------------------------------------------ #
    # Source dataframes
    # ------------------------------------------------------------------ #
    def _persons_dataframe(self) -> pd.DataFrame:
        personas = self.session.query(Person).options(
            selectinload(Person.photos), selectinload(Person.embeddings)
        ).all()
        rows = []
        for p in personas:
            attrs = primary_embedding_attrs(p)
            row = {
                "uuid": p.uuid,
                "nombre": sanitize_formula(p.nombre),
                "apellidos": sanitize_formula(p.apellidos),
                "alias": sanitize_formula(p.alias),
                "sexo": p.sexo,
                "edad_aproximada": p.edad_aproximada,
                "empresa": sanitize_formula(p.empresa),
                "departamento": sanitize_formula(p.departamento),
                "cargo": sanitize_formula(p.cargo),
                "telefono": sanitize_formula(p.telefono),
                "correo": sanitize_formula(p.correo),
                "fecha_creacion": p.fecha_creacion,
            }
            for field in ATTR_FIELDS:
                row[field] = bool(getattr(attrs, field, False)) if attrs else None
            row["edad_facial"] = attrs.edad if attrs else None
            row["genero"] = attrs.genero if attrs else None
            row["color_ojos"] = attrs.color_ojos if attrs else None
            row["color_pelo"] = attrs.color_pelo if attrs else None
            rows.append(row)
        return pd.DataFrame(rows)

    def _events_dataframe(self) -> pd.DataFrame:
        eventos = self.session.query(RecognitionEvent).order_by(RecognitionEvent.fecha.desc()).all()
        return pd.DataFrame([{
            "fecha": e.fecha,
            "origen": e.origen,
            "persona": sanitize_formula(e.person.nombre_completo) if e.person else "Desconocido",
            "confianza_pct": e.confianza,
            "distancia": e.distancia,
            "conf_deteccion": e.det_confidence,
            "usuario": sanitize_formula(e.usuario),
        } for e in eventos])

    # ------------------------------------------------------------------ #
    # Generic tabular export
    # ------------------------------------------------------------------ #
    @staticmethod
    def _write_dataframe(df: pd.DataFrame, path: str, fmt: str) -> None:
        fmt = fmt.lower()
        if fmt == "csv":
            df.to_csv(path, index=False, encoding="utf-8-sig")
        elif fmt == "excel":
            df.to_excel(path, index=False, engine="openpyxl")
        elif fmt == "json":
            df.to_json(path, orient="records", force_ascii=False, indent=2, date_format="iso")
        else:
            raise ValueError(
                f"Formato no soportado: '{fmt}'. Usa uno de {SUPPORTED_TABULAR_FORMATS}."
            )

    def export_persons(self, path: str, fmt: str) -> int:
        df = self._persons_dataframe()
        self._write_dataframe(df, path, fmt)
        audit_logger.info("Exportación de personas | formato={} | registros={} | destino={}",
                           fmt, len(df), Path(path).name)
        return len(df)

    def export_recognition_events(self, path: str, fmt: str) -> int:
        df = self._events_dataframe()
        self._write_dataframe(df, path, fmt)
        audit_logger.info("Exportación de eventos de reconocimiento | formato={} | registros={} | destino={}",
                           fmt, len(df), Path(path).name)
        return len(df)

    # ------------------------------------------------------------------ #
    # PDF statistics report (KPIs + charts)
    # ------------------------------------------------------------------ #
    def export_statistics_pdf(self, path: str, days: int = 30) -> None:
        from reportlab.lib import colors as rl_colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            Image as RLImage, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
        )

        stats = StatisticsService(self.session)
        summary = stats.summary_counts()

        doc = SimpleDocTemplate(path, pagesize=A4, topMargin=1.5 * cm, bottomMargin=1.5 * cm)
        styles = getSampleStyleSheet()
        story = []

        story.append(Paragraph("FaceScan — Reporte de estadísticas", styles["Title"]))
        story.append(Paragraph(datetime.now().strftime("Generado el %Y-%m-%d %H:%M"), styles["Normal"]))
        story.append(Spacer(1, 0.6 * cm))

        kpi_rows = [
            ["Métrica", "Valor"],
            ["Personas registradas", str(summary["total_personas"])],
            ["Eventos de reconocimiento", str(summary["total_eventos"])],
            ["Coincidencias", str(summary["eventos_match"])],
            ["Tasa de reconocimiento", f"{summary['tasa_reconocimiento_pct']}%"],
            ["Confianza promedio", f"{summary['confianza_promedio']}%"
                if summary["confianza_promedio"] else "—"],
            ["Eventos hoy", str(summary["eventos_hoy"])],
        ]
        table = Table(kpi_rows, colWidths=[9 * cm, 6 * cm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#2f6fed")),
            ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.white),
            ("BACKGROUND", (0, 1), (-1, -1), rl_colors.HexColor("#f1f2f6")),
            ("GRID", (0, 0), (-1, -1), 0.5, rl_colors.HexColor("#d9dce4")),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(table)
        story.append(Spacer(1, 0.8 * cm))

        chart_specs = [
            ("Personas registradas (acumulado)", stats.chart_persons_growth()),
            (f"Actividad de reconocimiento ({days} días)", stats.chart_daily_activity(days)),
            ("Distribución de confianza", stats.chart_confidence_distribution()),
            ("Personas por empresa", stats.chart_distribution_by_field("empresa", "Personas por empresa")),
            ("Reconocimientos por origen", stats.chart_recognitions_by_origin()),
            ("Análisis facial extendido", stats.chart_attributes_distribution()),
            ("Color de ojos", stats.chart_color_distribution(
                "color_ojos", "Color de ojos")),
            ("Color de pelo", stats.chart_color_distribution(
                "color_pelo", "Color de pelo")),
        ]
        for title, fig in chart_specs:
            buf = BytesIO()
            fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
            plt.close(fig)
            buf.seek(0)
            story.append(Paragraph(title, styles["Heading3"]))
            story.append(RLImage(buf, width=15 * cm, height=8.3 * cm))
            story.append(Spacer(1, 0.5 * cm))

        doc.build(story)
        audit_logger.info("Reporte PDF de estadísticas exportado a {}", Path(path).name)

    # ------------------------------------------------------------------ #
    # Database backup (consistent SQLite snapshot).
    # ------------------------------------------------------------------ #
    def backup_database(self, dest_path: str) -> None:
        """Create a consistent database backup using SQLite's native API.

        Uses ``Connection.backup`` instead of
        copiar el archivo con shutil, para garantizar una copia consistente
        incluso si hay escrituras concurrentes en curso.
        """
        db_path = settings.resolve_path(settings.database.path)
        Path(dest_path).parent.mkdir(parents=True, exist_ok=True)

        source = sqlite3.connect(str(db_path), timeout=30)
        dest = sqlite3.connect(dest_path, timeout=30)
        try:
            with dest:
                source.backup(dest)
        finally:
            source.close()
            dest.close()

        audit_logger.info("Respaldo de base de datos generado en {}", Path(dest_path).name)
