"""Statistics service: computes aggregated metrics and builds charts
(matplotlib, Agg backend — no window, safe to call from any thread) from the
database. This layer does not depend on PySide6; the GUI is responsible for
converting returned figures to QPixmap (see app/gui/widgets/statistics_widget.py).
This keeps strict separation between data logic/visualization and the UI.

All queries are lightweight and can be executed repeatedly (e.g., from a GUI
timer to keep statistics live).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from sqlalchemy import case, func
from sqlalchemy.orm import Session, selectinload

from app.database.models import FaceEmbedding, Person, Photo, RecognitionEvent
from app.vision.face_attributes import (
    ATTR_FIELDS, EYE_COLOR_LABELS, HAIR_COLOR_LABELS, FaceAttributes,
)

# --- Visual palette consistent with the app dark theme (see app/gui/theme.py) ---
BG_FIGURE = "#22232c"
BG_AXES = "#22232c"
TEXT_COLOR = "#c9cbd6"
GRID_COLOR = "#34353f"
PALETTE = ["#2f6fed", "#6fa8ff", "#46c37b", "#f2b134", "#e85d5d", "#a06cd5", "#3fc7c1"]

_DAY_NAMES = ["Domingo", "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]

_ALLOWED_DISTRIBUTION_FIELDS = {"empresa", "departamento", "sexo", "cargo"}

_ORIGIN_LABELS = {"webcam": "Webcam", "video": "Video", "imagen": "Imagen"}


def attrs_from_json(raw: str | None) -> FaceAttributes | None:
    """Parsea el JSON de `facial_attributes` (tolerante a valores corruptos)."""
    if not raw:
        return None
    try:
        return FaceAttributes.from_dict(json.loads(raw))
    except (ValueError, TypeError):
        return None


def primary_embedding_attrs(person: Person) -> FaceAttributes | None:
    """Atributos faciales del embedding de la foto principal (o del primero con datos).

    Reutilizado por export_service.py para las columnas de la exportación de
    personas y por el gráfico de distribución de atributos.
    """
    if not person.embeddings:
        return None
    primary = next((p for p in person.photos if p.es_principal),
                   person.photos[0] if person.photos else None)
    primary_id = primary.id if primary else None
    for emb in person.embeddings:
        if primary_id is not None and emb.photo_id == primary_id:
            parsed = attrs_from_json(emb.facial_attributes)
            if parsed is not None:
                return parsed
    for emb in person.embeddings:
        parsed = attrs_from_json(emb.facial_attributes)
        if parsed is not None:
            return parsed
    return None


def present_attribute_fields(attrs: FaceAttributes | None) -> list[str]:
    """Campos de ATTR_FIELDS que están activos en un análisis facial."""
    if attrs is None:
        return []
    return [f for f in ATTR_FIELDS if bool(getattr(attrs, f))]


def diff_attribute_fields(live: FaceAttributes | None,
                          stored: FaceAttributes | None) -> list[str]:
    """Campos donde el análisis 'en vivo' difiere de la ficha registrada.

    Devuelve lista vacía si falta cualquiera de los dos análisis (no se
    puede comparar). Utilizado por webcam en tiempo real y por los tests.
    """
    if live is None or stored is None:
        return []
    return [f for f in ATTR_FIELDS
            if bool(getattr(live, f)) != bool(getattr(stored, f))]


def _style_axes(ax) -> None:
    ax.set_facecolor(BG_AXES)
    ax.figure.set_facecolor(BG_FIGURE)
    ax.tick_params(colors=TEXT_COLOR, labelsize=9)
    ax.xaxis.label.set_color(TEXT_COLOR)
    ax.yaxis.label.set_color(TEXT_COLOR)
    ax.title.set_color(TEXT_COLOR)
    for spine in ax.spines.values():
        spine.set_color(GRID_COLOR)
    ax.grid(True, color=GRID_COLOR, linewidth=0.6, alpha=0.6)


class StatisticsService:
    def __init__(self, session: Session):
        self.session = session

    # ------------------------------------------------------------------ #
    # Consultas agregadas — devuelven dict/DataFrame, reutilizables por
    # export_service.py para el reporte PDF.
    # ------------------------------------------------------------------ #
    def summary_counts(self, days: int = 30) -> dict:
        total_personas = self.session.query(Person).count()
        total_eventos = self.session.query(RecognitionEvent).count()
        eventos_match = (
            self.session.query(RecognitionEvent)
            .filter(RecognitionEvent.person_uuid.isnot(None))
            .count()
        )
        avg_conf = self.session.query(func.avg(RecognitionEvent.confianza)).scalar()
        hoy = datetime.utcnow().date()
        eventos_hoy = (
            self.session.query(RecognitionEvent)
            .filter(RecognitionEvent.fecha >= hoy)
            .count()
        )
        tasa = round((eventos_match / total_eventos) * 100, 1) if total_eventos else 0.0

        # Rate by origin: webcam/video log only matches
        # (log_only_matches=True), so the global rate is not comparable
        # across origins. Broken down to avoid misinterpretation.
        por_origen = {}
        origin_rows = (
            self.session.query(
                RecognitionEvent.origen,
                func.count(RecognitionEvent.id),
                func.sum(case((RecognitionEvent.person_uuid.isnot(None), 1), else_=0)),
            )
            .group_by(RecognitionEvent.origen)
            .all()
        )
        for origen, total_o, match_o in origin_rows:
            total_o = int(total_o)
            match_o = int(match_o or 0)
            por_origen[origen] = {
                "eventos": total_o,
                "match": match_o,
                "tasa": round((match_o / total_o) * 100, 1) if total_o else 0.0,
            }

        # --- extended metrics ---
        since = datetime.utcnow() - timedelta(days=days)
        personas_periodo = (
            self.session.query(Person).filter(Person.fecha_creacion >= since).count()
        )
        eventos_ultima_hora = (
            self.session.query(RecognitionEvent)
            .filter(RecognitionEvent.fecha >= datetime.utcnow() - timedelta(hours=1))
            .count()
        )
        fotos_totales = self.session.query(Photo).count()
        personas_con_fotos = (
            self.session.query(Photo.person_uuid).distinct().count()
        )
        embeddings_totales = self.session.query(FaceEmbedding).count()

        confianza_row = (
            self.session.query(func.min(RecognitionEvent.confianza),
                                func.max(RecognitionEvent.confianza))
            .filter(RecognitionEvent.person_uuid.isnot(None))
            .one()
        )
        confianza_min = round(float(confianza_row[0]), 1) if confianza_row[0] is not None else None
        confianza_max = round(float(confianza_row[1]), 1) if confianza_row[1] is not None else None

        top_empresa_row = (
            self.session.query(Person.empresa, func.count(Person.uuid))
            .filter(Person.empresa.isnot(None), Person.empresa != "")
            .group_by(Person.empresa)
            .order_by(func.count(Person.uuid).desc())
            .first()
        )

        return {
            "total_personas": total_personas,
            "personas_periodo": personas_periodo,
            "total_eventos": total_eventos,
            "eventos_match": eventos_match,
            "eventos_sin_match": total_eventos - eventos_match,
            "tasa_reconocimiento_pct": tasa,
            "tasa_reconocimiento_por_origen": por_origen,
            "confianza_promedio": round(avg_conf, 1) if avg_conf else None,
            "confianza_maxima": confianza_max,
            "confianza_minima": confianza_min,
            "eventos_hoy": eventos_hoy,
            "eventos_ultima_hora": eventos_ultima_hora,
            "fotos_totales": fotos_totales,
            "personas_con_fotos": personas_con_fotos,
            "personas_sin_fotos": max(0, total_personas - personas_con_fotos),
            "embeddings_totales": embeddings_totales,
            "avg_fotos_por_persona": round(fotos_totales / total_personas, 2)
            if total_personas else 0,
            "top_empresa": top_empresa_row[0] if top_empresa_row else None,
            "top_empresa_count": top_empresa_row[1] if top_empresa_row else 0,
        }

    def persons_growth_df(self) -> pd.DataFrame:
        rows = (
            self.session.query(
                func.date(Person.fecha_creacion).label("fecha"), func.count(Person.uuid)
            )
            .group_by(func.date(Person.fecha_creacion))
            .order_by(func.date(Person.fecha_creacion))
            .all()
        )
        df = pd.DataFrame(rows, columns=["fecha", "altas"])
        if df.empty:
            return df
        df["fecha"] = pd.to_datetime(df["fecha"])
        df["acumulado"] = df["altas"].cumsum()
        return df

    def daily_activity_df(self, days: int = 30) -> pd.DataFrame:
        since = datetime.utcnow() - timedelta(days=days)
        rows = (
            self.session.query(
                func.date(RecognitionEvent.fecha).label("fecha"), func.count(RecognitionEvent.id)
            )
            .filter(RecognitionEvent.fecha >= since)
            .group_by(func.date(RecognitionEvent.fecha))
            .order_by(func.date(RecognitionEvent.fecha))
            .all()
        )
        df = pd.DataFrame(rows, columns=["fecha", "reconocimientos"])
        if df.empty:
            return df
        df["fecha"] = pd.to_datetime(df["fecha"])
        return df

    def confidence_values(self, only_matches: bool = True) -> pd.Series:
        q = self.session.query(RecognitionEvent.confianza)
        if only_matches:
            q = q.filter(RecognitionEvent.person_uuid.isnot(None))
        values = [v[0] for v in q.all() if v[0] is not None]
        return pd.Series(values, name="confianza", dtype="float64")

    def distribution_df(self, field: str, limit: int = 10) -> pd.DataFrame:
        """field debe ser uno de: empresa, departamento, sexo, cargo."""
        if field not in _ALLOWED_DISTRIBUTION_FIELDS:
            raise ValueError(f"Campo no permitido para distribución: {field}")
        column = getattr(Person, field)
        rows = (
            self.session.query(column, func.count(Person.uuid))
            .filter(column.isnot(None), column != "")
            .group_by(column)
            .order_by(func.count(Person.uuid).desc())
            .limit(limit)
            .all()
        )
        return pd.DataFrame(rows, columns=[field, "total"])

    def recognitions_by_origin_df(self) -> pd.DataFrame:
        rows = (
            self.session.query(RecognitionEvent.origen, func.count(RecognitionEvent.id))
            .group_by(RecognitionEvent.origen)
            .all()
        )
        df = pd.DataFrame(rows, columns=["origen", "total"])
        return df

    def attributes_distribution_df(self) -> pd.DataFrame:
        """N.º de personas (únicas) que presentan cada atributo facial extendido."""
        counts = {field: 0 for field in ATTR_FIELDS}
        persons = self.session.query(Person).options(
            selectinload(Person.photos), selectinload(Person.embeddings)
        ).all()
        for person in persons:
            attrs = primary_embedding_attrs(person)
            if attrs is None:
                continue
            for field in ATTR_FIELDS:
                if getattr(attrs, field):
                    counts[field] += 1
        return pd.DataFrame(
            {"atributo": list(counts.keys()), "personas": list(counts.values())}
        )

    def color_distribution_df(self, field: str) -> pd.DataFrame:
        """Distribución de personas según el color (de ojos o de pelo) de su foto principal."""
        if field not in ("color_ojos", "color_pelo"):
            raise ValueError(f"Campo no permitido para distribución de color: {field}")
        labels = EYE_COLOR_LABELS if field == "color_ojos" else HAIR_COLOR_LABELS
        counts = {label: 0 for label in labels}
        persons = self.session.query(Person).options(
            selectinload(Person.photos), selectinload(Person.embeddings)
        ).all()
        for person in persons:
            attrs = primary_embedding_attrs(person)
            if attrs is None:
                continue
            color = getattr(attrs, field)
            if color in counts:
                counts[color] += 1
        return pd.DataFrame(
            {"color": list(counts.keys()), "personas": list(counts.values())}
        )

    # ------------------------------------------------------------------ #
    # Additional queries (detailed analysis)
    # ------------------------------------------------------------------ #
    def recent_events_df(self, limit: int = 50) -> pd.DataFrame:
        rows = (
            self.session.query(
                RecognitionEvent.fecha, RecognitionEvent.origen,
                RecognitionEvent.person_uuid, RecognitionEvent.confianza,
                Person.nombre, Person.apellidos,
            )
            .outerjoin(Person, RecognitionEvent.person_uuid == Person.uuid)
            .order_by(RecognitionEvent.fecha.desc())
            .limit(limit)
            .all()
        )
        df = pd.DataFrame(
            rows, columns=["fecha", "origen", "person_uuid", "confianza", "nombre", "apellidos"]
        )
        if df.empty:
            return df
        df["origen"] = df["origen"].map(lambda o: _ORIGIN_LABELS.get(o, o))
        df["persona"] = (df["nombre"].fillna("") + " " + df["apellidos"].fillna("")).str.strip()
        df.loc[df["persona"] == "", "persona"] = "Desconocido"
        return df

    def top_recognized_df(self, limit: int = 8) -> pd.DataFrame:
        rows = (
            self.session.query(RecognitionEvent.person_uuid, func.count(RecognitionEvent.id))
            .filter(RecognitionEvent.person_uuid.isnot(None))
            .group_by(RecognitionEvent.person_uuid)
            .order_by(func.count(RecognitionEvent.id).desc())
            .limit(limit)
            .all()
        )
        df = pd.DataFrame(rows, columns=["person_uuid", "reconocimientos"])
        if df.empty:
            return df
        names = {p.uuid: p.nombre_completo for p in self.session.query(Person).all()}
        df["persona"] = df["person_uuid"].map(lambda u: names.get(u, "Desconocido"))
        return df

    def activity_by_hour_df(self, days: int = 30) -> pd.DataFrame:
        since = datetime.utcnow() - timedelta(days=days)
        hour_expr = func.strftime("%H", RecognitionEvent.fecha).label("hora")
        rows = (
            self.session.query(hour_expr, func.count(RecognitionEvent.id))
            .filter(RecognitionEvent.fecha >= since)
            .group_by(hour_expr)
            .all()
        )
        counts = {int(h): int(c) for h, c in rows}
        df = pd.DataFrame(
            {"hora": range(24), "total": [counts.get(h, 0) for h in range(24)]}
        )
        df["etiqueta"] = df["hora"].apply(lambda h: f"{h:02d}:00")
        return df

    def day_of_week_activity_df(self, days: int = 30) -> pd.DataFrame:
        since = datetime.utcnow() - timedelta(days=days)
        dow_expr = func.strftime("%w", RecognitionEvent.fecha).label("dow")
        rows = (
            self.session.query(dow_expr, func.count(RecognitionEvent.id))
            .filter(RecognitionEvent.fecha >= since)
            .group_by(dow_expr)
            .all()
        )
        counts = {int(d): int(c) for d, c in rows}
        return pd.DataFrame({
            "dia": _DAY_NAMES,
            "total": [counts.get(i, 0) for i in range(7)],
        })

    def confidence_by_origin_df(self) -> pd.DataFrame:
        rows = (
            self.session.query(
                RecognitionEvent.origen,
                func.avg(RecognitionEvent.confianza),
                func.count(RecognitionEvent.id),
            )
            .filter(RecognitionEvent.person_uuid.isnot(None))
            .group_by(RecognitionEvent.origen)
            .all()
        )
        df = pd.DataFrame(rows, columns=["origen", "confianza_promedio", "eventos"])
        return df

    def confidence_over_time_df(self, days: int = 30) -> pd.DataFrame:
        since = datetime.utcnow() - timedelta(days=days)
        rows = (
            self.session.query(
                func.date(RecognitionEvent.fecha).label("fecha"),
                func.avg(RecognitionEvent.confianza),
            )
            .filter(RecognitionEvent.fecha >= since,
                    RecognitionEvent.person_uuid.isnot(None))
            .group_by(func.date(RecognitionEvent.fecha))
            .order_by(func.date(RecognitionEvent.fecha))
            .all()
        )
        df = pd.DataFrame(rows, columns=["fecha", "confianza"])
        if df.empty:
            return df
        df["fecha"] = pd.to_datetime(df["fecha"])
        return df

    def match_vs_unknown_counts(self, days: int = 30) -> dict:
        since = datetime.utcnow() - timedelta(days=days)
        base = self.session.query(RecognitionEvent.id).filter(RecognitionEvent.fecha >= since)
        total = base.count()
        matches = base.filter(RecognitionEvent.person_uuid.isnot(None)).count()
        return {"total": total, "match": matches, "unknown": total - matches}

    # ------------------------------------------------------------------ #
    # Charts — return matplotlib.figure.Figure (no Qt).
    # The caller (GUI) is responsible for closing the figure after use
    # (plt.close(fig)) to avoid memory buildup.
    # ------------------------------------------------------------------ #
    def chart_persons_growth(self):
        df = self.persons_growth_df()
        fig, ax = plt.subplots(figsize=(5.4, 3.2), dpi=110)
        _style_axes(ax)
        if df.empty:
            ax.text(0.5, 0.5, "Sin datos aún", ha="center", va="center", color=TEXT_COLOR)
        else:
            ax.plot(df["fecha"], df["acumulado"], color=PALETTE[0], linewidth=2.2,
                    marker="o", markersize=3)
            ax.fill_between(df["fecha"], df["acumulado"], color=PALETTE[0], alpha=0.15)
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%b"))
            fig.autofmt_xdate(rotation=30)
        ax.set_title("Personas registradas (acumulado)")
        fig.tight_layout()
        return fig

    def chart_daily_activity(self, days: int = 30):
        df = self.daily_activity_df(days)
        fig, ax = plt.subplots(figsize=(5.4, 3.2), dpi=110)
        _style_axes(ax)
        if df.empty:
            ax.text(0.5, 0.5, "Sin actividad en este período", ha="center", va="center", color=TEXT_COLOR)
        else:
            ax.bar(df["fecha"], df["reconocimientos"], color=PALETTE[1], width=0.7)
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%b"))
            fig.autofmt_xdate(rotation=30)
        ax.set_title(f"Actividad de reconocimiento (últimos {days} días)")
        fig.tight_layout()
        return fig

    def chart_confidence_distribution(self):
        values = self.confidence_values(only_matches=True)
        fig, ax = plt.subplots(figsize=(5.4, 3.2), dpi=110)
        _style_axes(ax)
        if values.empty:
            ax.text(0.5, 0.5, "Aún no hay coincidencias registradas",
                    ha="center", va="center", color=TEXT_COLOR)
        else:
            ax.hist(values, bins=10, range=(0, 100), color=PALETTE[2], edgecolor=BG_FIGURE)
            ax.set_xlabel("Confianza (%)")
            ax.set_ylabel("Reconocimientos")
        ax.set_title("Distribución de confianza (coincidencias)")
        fig.tight_layout()
        return fig

    def chart_distribution_by_field(self, field: str, title: str):
        df = self.distribution_df(field)
        fig, ax = plt.subplots(figsize=(5.4, 3.2), dpi=110)
        _style_axes(ax)
        if df.empty:
            ax.text(0.5, 0.5, "Sin datos suficientes", ha="center", va="center", color=TEXT_COLOR)
        else:
            colors = [PALETTE[i % len(PALETTE)] for i in range(len(df))]
            ax.barh(df[field].astype(str), df["total"], color=colors)
            ax.invert_yaxis()
            ax.set_xlabel("Personas")
        ax.set_title(title)
        fig.tight_layout()
        return fig

    def chart_recognitions_by_origin(self):
        df = self.recognitions_by_origin_df()
        fig, ax = plt.subplots(figsize=(5.4, 3.2), dpi=110)
        fig.set_facecolor(BG_FIGURE)
        if df.empty:
            ax.set_facecolor(BG_AXES)
            ax.text(0.5, 0.5, "Sin eventos registrados", ha="center", va="center", color=TEXT_COLOR)
            ax.axis("off")
        else:
            labels = [_ORIGIN_LABELS.get(o, o) for o in df["origen"]]
            colors = [PALETTE[i % len(PALETTE)] for i in range(len(df))]
            ax.pie(
                df["total"], labels=labels, autopct="%1.0f%%",
                colors=colors, textprops={"color": TEXT_COLOR},
            )
        ax.set_title("Reconocimientos por origen", color=TEXT_COLOR)
        fig.tight_layout()
        return fig

    # ------------------------------------------------------------------ #
    # Additional charts (detailed analysis)
    # ------------------------------------------------------------------ #
    def chart_weekly_activity(self, days: int = 30):
        df = self.day_of_week_activity_df(days)
        fig, ax = plt.subplots(figsize=(5.4, 3.2), dpi=110)
        _style_axes(ax)
        if df["total"].sum() == 0:
            ax.text(0.5, 0.5, "Sin actividad en este período", ha="center", va="center", color=TEXT_COLOR)
        else:
            colors = [PALETTE[i % len(PALETTE)] for i in range(len(df))]
            ax.bar(df["dia"], df["total"], color=colors)
            ax.set_xlabel("Día de la semana")
            ax.set_ylabel("Reconocimientos")
        ax.set_title(f"Actividad por día de la semana (últimos {days} días)")
        fig.tight_layout()
        return fig

    def chart_activity_by_hour(self, days: int = 30):
        df = self.activity_by_hour_df(days)
        fig, ax = plt.subplots(figsize=(5.4, 3.2), dpi=110)
        _style_axes(ax)
        if df["total"].sum() == 0:
            ax.text(0.5, 0.5, "Sin actividad en este período", ha="center", va="center", color=TEXT_COLOR)
        else:
            colors = [
                PALETTE[4] if h < 6 else PALETTE[3] if h < 12
                else PALETTE[0] if h < 18 else PALETTE[2]
                for h in df["hora"]
            ]
            ax.bar(df["etiqueta"], df["total"], color=colors)
            ax.set_xticks(df["etiqueta"][::3])
            ax.set_xlabel("Hora del día")
            ax.set_ylabel("Reconocimientos")
        ax.set_title(f"Actividad por hora (últimos {days} días)")
        fig.tight_layout()
        return fig

    def chart_top_persons(self, limit: int = 8):
        df = self.top_recognized_df(limit)
        fig, ax = plt.subplots(figsize=(5.4, 3.2), dpi=110)
        _style_axes(ax)
        if df.empty or df["reconocimientos"].sum() == 0:
            ax.text(0.5, 0.5, "Aún no hay personas reconocidas", ha="center", va="center", color=TEXT_COLOR)
        else:
            ax.barh(df["persona"], df["reconocimientos"], color=PALETTE[2])
            ax.invert_yaxis()
            ax.set_xlabel("Reconocimientos")
        ax.set_title("Personas más reconocidas")
        fig.tight_layout()
        return fig

    def chart_confidence_over_time(self, days: int = 30):
        df = self.confidence_over_time_df(days)
        fig, ax = plt.subplots(figsize=(5.4, 3.2), dpi=110)
        _style_axes(ax)
        if df.empty:
            ax.text(0.5, 0.5, "Sin coincidencias en este período", ha="center", va="center", color=TEXT_COLOR)
        else:
            ax.plot(df["fecha"], df["confianza"], color=PALETTE[0], linewidth=2.0,
                    marker="o", markersize=3)
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%b"))
            fig.autofmt_xdate(rotation=30)
            ax.set_ylim(0, 100)
            ax.set_ylabel("Confianza promedio (%)")
        ax.set_title(f"Confianza promedio diaria (últimos {days} días)")
        fig.tight_layout()
        return fig

    def chart_confidence_by_origin(self):
        df = self.confidence_by_origin_df()
        fig, ax = plt.subplots(figsize=(5.4, 3.2), dpi=110)
        _style_axes(ax)
        if df.empty:
            ax.text(0.5, 0.5, "Sin coincidencias registradas", ha="center", va="center", color=TEXT_COLOR)
        else:
            labels = [_ORIGIN_LABELS.get(o, o) for o in df["origen"]]
            colors = [PALETTE[i % len(PALETTE)] for i in range(len(df))]
            bars = ax.bar(labels, df["confianza_promedio"], color=colors)
            for bar, (_, row) in zip(bars, df.iterrows()):
                ax.text(bar.get_x() + bar.get_width() / 2, row["confianza_promedio"] + 1.5,
                        f"{row['confianza_promedio']:.0f}%", ha="center", color=TEXT_COLOR, fontsize=9)
            ax.set_ylim(0, 105)
            ax.set_ylabel("Confianza promedio (%)")
        ax.set_title("Confianza promedio por origen")
        fig.tight_layout()
        return fig

    def chart_match_vs_unknown(self, days: int = 30):
        d = self.match_vs_unknown_counts(days)
        fig, ax = plt.subplots(figsize=(5.4, 3.2), dpi=110)
        fig.set_facecolor(BG_FIGURE)
        if d["total"] == 0:
            ax.set_facecolor(BG_AXES)
            ax.text(0.5, 0.5, "Sin eventos en este período", ha="center", va="center", color=TEXT_COLOR)
            ax.axis("off")
        else:
            ax.pie(
                [d["match"], d["unknown"]],
                labels=["Coincidencias", "Desconocidos"],
                colors=[PALETTE[2], PALETTE[4]],
                autopct="%1.0f%%", startangle=90,
                textprops={"color": TEXT_COLOR},
                wedgeprops={"width": 0.38},
            )
        ax.set_title(f"Coincidencias vs. Desconocidos (últimos {days} días)", color=TEXT_COLOR)
        fig.tight_layout()
        return fig

    def chart_attributes_distribution(self):
        """Distribución de personas según el análisis facial extendido de su foto principal."""
        df = self.attributes_distribution_df()
        fig, ax = plt.subplots(figsize=(5.4, 3.2), dpi=110)
        _style_axes(ax)
        if df["personas"].sum() == 0:
            ax.text(0.5, 0.5, "Aún no hay análisis facial registrado", ha="center",
                    va="center", color=TEXT_COLOR)
        else:
            colors = [PALETTE[i % len(PALETTE)] for i in range(len(df))]
            bars = ax.bar(df["atributo"], df["personas"], color=colors)
            for bar, count in zip(bars, df["personas"]):
                if count:
                    ax.text(bar.get_x() + bar.get_width() / 2, count,
                            str(count), ha="center", color=TEXT_COLOR, fontsize=9)
            ax.set_ylabel("Personas")
            ax.set_xticks(range(len(df)))
            ax.set_xticklabels(df["atributo"], rotation=20, ha="right")
        ax.set_title("Análisis facial extendido (por foto principal)")
        fig.tight_layout()
        return fig

    def chart_color_distribution(self, field: str, title: str):
        df = self.color_distribution_df(field)
        fig, ax = plt.subplots(figsize=(5.4, 3.2), dpi=110)
        _style_axes(ax)
        if df["personas"].sum() == 0:
            ax.text(0.5, 0.5, "Aún no hay color registrado", ha="center",
                    va="center", color=TEXT_COLOR)
        else:
            colors = [PALETTE[i % len(PALETTE)] for i in range(len(df))]
            bars = ax.bar(df["color"], df["personas"], color=colors)
            for bar, count in zip(bars, df["personas"]):
                if count:
                    ax.text(bar.get_x() + bar.get_width() / 2, count,
                            str(count), ha="center", color=TEXT_COLOR, fontsize=9)
            ax.set_ylabel("Personas")
            ax.set_xticks(range(len(df)))
            ax.set_xticklabels(df["color"], rotation=20, ha="right")
        ax.set_title(title)
        fig.tight_layout()
        return fig
