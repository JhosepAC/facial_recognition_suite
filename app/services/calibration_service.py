"""Calibration service for extended facial analysis.

Its purpose is to allow diagnosing and tuning the heuristic thresholds in
``app.vision.face_attributes`` without reprocessing images for each attempt:

  - ``collect()`` gathers, for each person\'s primary photo, the raw
    confidence (0..1 per attribute) already stored in the embedding.
  - The GUI slides thresholds and re-classifies in memory via
    ``classify_from_conf`` (pure), instantly seeing how many persons change.
  - ``apply_thresholds()`` persists new boolean values over existing
    embeddings (leaving age/gender intact).
  - ``refresh_*()`` re-runs models (InsightFace + MediaPipe) over primary
    photos to regenerate confidences, e.g., for legacy records saved before
    analysis existed.

This layer does not depend on PySide6; the GUI (Admin -> Facial Calibration)
invokes it.
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
from sqlalchemy.orm import Session

from app.database.models import FaceEmbedding, Person
from app.services.statistics_service import attrs_from_json
from app.vision.face_attributes import (
    ATTR_FIELDS, FaceAttributeAnalyzer, FaceAttributes, classify_from_conf,
)
from app.vision.face_engine import FaceEngine


def _face_area(face) -> float:
    x1, y1, x2, y2 = face.bbox
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


class CalibrationService:
    def __init__(self, session: Session):
        self.session = session
        self.engine = FaceEngine.instance()
        self.attributes = FaceAttributeAnalyzer.instance()

    # ------------------------------------------------------------------ #
    # Sample collection
    # ------------------------------------------------------------------ #
    def _primary_photo_and_embedding(self, person):
        """Foto principal + embedding asociado (o el primero con atributos)."""
        photos = person.photos or []
        primary = next((p for p in photos if p.es_principal),
                       photos[0] if photos else None)
        if primary is not None:
            for emb in person.embeddings:
                if emb.photo_id == primary.id:
                    return primary, emb
        for emb in person.embeddings:
            if emb.facial_attributes:
                return primary, emb
        return primary, (person.embeddings[0] if person.embeddings else None)

    def collect(self, limit: int = 300) -> list[dict]:
        """Calibration records (one entry per person, primary photo)."""
        persons = (
            self.session.query(Person)
            .order_by(Person.apellidos, Person.nombre)
            .limit(limit)
            .all()
        )
        entries = []
        for person in persons:
            photo, emb = self._primary_photo_and_embedding(person)
            entries.append({
                "uuid": person.uuid,
                "nombre": person.nombre_completo,
                "thumb": photo.thumbnail_path if photo else None,
                "foto": photo.file_path if photo else None,
                "emb_id": emb.id if emb else None,
                "calidad": emb.quality_score if emb else None,
                "attrs": attrs_from_json(emb.facial_attributes) if emb else None,
            })
        return entries

    # ------------------------------------------------------------------ #
    # In-memory re-classification (threshold change without touching DB)
    # ------------------------------------------------------------------ #
    @staticmethod
    def reclassify(attrs: FaceAttributes | None,
                   thresholds: dict[str, float]) -> FaceAttributes | None:
        """Aplica los umbrales dados sobre la confianza cruda ya almacenada."""
        if attrs is None:
            return None
        out = classify_from_conf(attrs.conf, thresholds)
        out.edad = attrs.edad
        out.genero = attrs.genero
        out.color_ojos = attrs.color_ojos
        out.color_pelo = attrs.color_pelo
        return out

    def aggregate(self, entries: list[dict],
                  thresholds: dict[str, float]) -> dict[str, dict]:
        """Por atributo: n.º de personas presentes vs. n.º con confianza evaluable."""
        result = {}
        for field in ATTR_FIELDS:
            presente = con_conf = 0
            for e in entries:
                attrs = e["attrs"]
                conf = attrs.conf if attrs is not None else {}
                if field not in conf:
                    continue
                con_conf += 1
                if getattr(classify_from_conf(conf, thresholds), field):
                    presente += 1
            result[field] = {"presente": presente, "con_conf": con_conf}
        return result

    # ------------------------------------------------------------------ #
    # Persistence of a new threshold set over embeddings
    # ------------------------------------------------------------------ #
    def apply_thresholds(self, thresholds: dict[str, float]) -> int:
        """Re-clasifica y guarda los booleanos de todos los embeddings con análisis."""
        count = 0
        embeddings = (
            self.session.query(FaceEmbedding)
            .filter(FaceEmbedding.facial_attributes.isnot(None))
            .all()
        )
        for emb in embeddings:
            parsed = attrs_from_json(emb.facial_attributes)
            if parsed is None:
                continue
            recls = classify_from_conf(parsed.conf, thresholds)
            recls.edad = parsed.edad
            recls.genero = parsed.genero
            recls.color_ojos = parsed.color_ojos
            recls.color_pelo = parsed.color_pelo
            emb.facial_attributes = json.dumps(recls.to_dict(), ensure_ascii=False)
            count += 1
        self.session.commit()
        return count

    # ------------------------------------------------------------------ #
    # Re-analysis of photos with models (regenerate confidences)
    # ------------------------------------------------------------------ #
    def refresh_primary_photo(self, entry: dict) -> FaceAttributes | None:
        """Ejecuta InsightFace + MediaPipe sobre la foto principal de una persona."""
        path = entry.get("foto")
        if not path or not Path(path).exists():
            return None
        img = cv2.imread(path)
        if img is None:
            return None
        faces = self.engine.analyze(img)
        if not faces:
            return None
        main = max(faces, key=_face_area)
        attrs = self.attributes.analyze(img, main.bbox, main.landmarks)
        if attrs is None:
            attrs = FaceAttributes()
        attrs.edad = main.age
        attrs.genero = main.gender
        return attrs

    def refresh_all(self, limit: int = 300, progress=None) -> int:
        """Reanaliza las fotos principales y guarda nuevas confianzas en los embeddings."""
        entries = self.collect(limit=limit)
        refreshed = 0
        for i, entry in enumerate(entries):
            new = self.refresh_primary_photo(entry)
            if new is not None and entry.get("emb_id"):
                emb = self.session.get(FaceEmbedding, entry["emb_id"])
                if emb is not None:
                    emb.facial_attributes = json.dumps(
                        new.to_dict(), ensure_ascii=False)
                    refreshed += 1
            if progress is not None:
                progress(i + 1, len(entries))
        self.session.commit()
        return refreshed