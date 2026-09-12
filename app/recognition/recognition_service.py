"""
Servicio de reconocimiento facial: capa que conecta el motor de visión
(app.vision) con la base biométrica (app.database) sin que ninguna de las
dos conozca a la otra directamente. Aquí vive la lógica de negocio de:

- registrar el embedding de una foto de una persona,
- comparar dos rostros (1:1),
- buscar la(s) persona(s) más parecida(s) a un rostro dado (1:N),
- reconocer todos los rostros presentes en una imagen/frame (webcam, video).

Aplica un GATE de calidad en todos los flujos de reconocimiento (no solo al
registrar): los matches sobre rostros borrosos, oscuros, mal encarados o
demasiado pequeños no se emiten, para reducir falsos positivos en vivo.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import (
    DuplicatePersonError, LowQualityFaceError, MultipleFacesError, NoFaceDetectedError,
)
from app.core.logger import audit_logger, logger
from app.database.models import FaceEmbedding, RecognitionEvent
from app.database.repositories.embedding_repository import EmbeddingRepository
from app.recognition.ann_index import get_shared_index
from app.recognition.matcher import MatchCandidate, compare_pair, rank_candidates
from app.utils.vector_utils import bytes_to_vector, cosine_distance, vector_to_bytes
from app.vision.face_attributes import FaceAttributeAnalyzer, FaceAttributes
from app.vision.face_engine import FaceEngine, FaceResult
from app.vision.face_quality import QualityScores, evaluate as evaluate_quality


@dataclass
class RecognizedFace:
    bbox: tuple[float, float, float, float]
    person_uuid: str | None
    person_nombre: str | None
    confidence_pct: float
    distance: float
    det_score: float = 0.0
    attributes: FaceAttributes | None = None


def _largest_area(result: FaceResult) -> float:
    x1, y1, x2, y2 = result.bbox
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


class RecognitionService:
    def __init__(self, session: Session):
        self.session = session
        self.embedding_repo = EmbeddingRepository(session)
        self.engine = FaceEngine.instance()
        self.attributes = FaceAttributeAnalyzer.instance()
        self._gallery_cache: list[tuple[str, int, np.ndarray]] | None = None
        self._gallery_cache_fp = None

    # ------------------------------------------------------------------ #
    # Calidad (gate aplicado a todos los flujos de match)
    # ------------------------------------------------------------------ #
    def _quality_valid(self, image_bgr: np.ndarray, face: FaceResult,
                       raise_on_fail: bool = False) -> bool:
        if not settings.recognition.apply_quality_gate:
            return True
        quality = evaluate_quality(image_bgr, face.bbox, face.landmarks)
        ok = (
            quality.size_ok
            and abs(quality.yaw_deg) <= settings.vision.max_yaw_deg
            and abs(quality.pitch_deg) <= settings.vision.max_pitch_deg
            and quality.calidad_global >= settings.vision.quality_min_score
        )
        if not ok and raise_on_fail:
            raise LowQualityFaceError(
                _low_quality_message(face, quality)
            )
        return ok

    # ------------------------------------------------------------------ #
    # Registro
    # ------------------------------------------------------------------ #
    def enroll_photo(
        self, person_uuid: str, image_bgr: np.ndarray, photo_id: int | None = None,
        usuario: str | None = None,
    ) -> FaceEmbedding:
        """Extrae el embedding del rostro de una foto y lo guarda.

        Valida la foto antes de persistir: un solo rostro (si está habilitado),
        calidad mínima, pose frontal y tamaño suficiente. Además rechaza
        embeddings que colisionan biométricamente con otra persona.
        """
        faces = self.engine.analyze(image_bgr)
        if not faces:
            raise NoFaceDetectedError("No se detectó ningún rostro en la fotografía.")

        if len(faces) > 1:
            if settings.vision.enroll_require_single_face:
                raise MultipleFacesError(
                    f"Se detectaron {len(faces)} rostros en la fotografía. "
                    "Sube una foto con una sola persona."
                )
            face = max(faces, key=_largest_area)
        else:
            face = faces[0]

        quality = evaluate_quality(image_bgr, face.bbox, face.landmarks)
        reasons = []
        if not quality.size_ok:
            reasons.append("rostro demasiado pequeño o lejano")
        if (abs(quality.yaw_deg) > settings.vision.max_yaw_deg
                or abs(quality.pitch_deg) > settings.vision.max_pitch_deg):
            reasons.append("rostro no frontal (gira la cabeza hacia la cámara)")
        if quality.calidad_global < settings.vision.quality_min_score:
            reasons.append(
                f"calidad de {quality.calidad_global:.0f}/100 "
                "(necesita ser más nítido o mejor iluminado)")
        if reasons:
            raise LowQualityFaceError(
                "Calidad de rostro insuficiente: " + ", ".join(reasons) + "."
            )

        self._reject_duplicate(person_uuid, face.embedding)

        attrs = self.attributes.analyze(image_bgr, face.bbox, face.landmarks)
        if attrs is None:
            attrs = FaceAttributes()
        attrs.edad = face.age
        attrs.genero = face.gender
        embedding = FaceEmbedding(
            person_uuid=person_uuid,
            photo_id=photo_id,
            vector=vector_to_bytes(face.embedding),
            dim=face.embedding.shape[0],
            model_name=settings.vision.detector_model,
            det_confidence=face.det_score,
            quality_score=quality.calidad_global,
            facial_attributes=json.dumps(attrs.to_dict(), ensure_ascii=False),
        )
        self.embedding_repo.add(embedding)
        audit_logger.info(
            "Embedding registrado | persona={} | calidad={} | usuario={}",
            person_uuid, quality.calidad_global, usuario or "sistema",
        )
        return embedding

    def _reject_duplicate(self, person_uuid: str, embedding: np.ndarray) -> None:
        """Evita duplicar rostros: rechaza colisión biométrica con otra persona."""
        threshold = settings.recognition.dedupe_threshold
        for other_uuid, _emb_id, vector in self._load_gallery():
            if other_uuid == person_uuid:
                continue
            if cosine_distance(embedding, vector) < threshold:
                raise DuplicatePersonError(
                    "Este rostro ya está registrado a nombre de otra persona. "
                    "Verifica que no exista un duplicado en la base."
                )

    # ------------------------------------------------------------------ #
    # Comparador biométrico 1:1
    # ------------------------------------------------------------------ #
    def compare_images(self, image_a_bgr: np.ndarray, image_b_bgr: np.ndarray) -> dict:
        faces = self.engine.analyze(image_a_bgr)
        face_a = max(faces, key=_largest_area) if faces else None
        faces = self.engine.analyze(image_b_bgr)
        face_b = max(faces, key=_largest_area) if faces else None
        if face_a is None or face_b is None:
            raise NoFaceDetectedError("No se detectó rostro en una de las dos imágenes.")

        self._quality_valid(image_a_bgr, face_a, raise_on_fail=True)
        self._quality_valid(image_b_bgr, face_b, raise_on_fail=True)

        result = compare_pair(face_a.embedding, face_b.embedding)
        result["face_a"] = face_a
        result["face_b"] = face_b
        return result

    # ------------------------------------------------------------------ #
    # Búsqueda 1:N
    # ------------------------------------------------------------------ #
    def _gallery_fingerprint(self) -> tuple:
        row = self.session.execute(
            select(func.count(FaceEmbedding.id), func.max(FaceEmbedding.id))
        ).one()
        return (int(row[0]), int(row[1]) if row[1] is not None else -1)

    def _load_gallery(self) -> list[tuple[str, int, np.ndarray]]:
        """Galería de embeddings cacheada (vectores unitarios).

        Se recalcula solo cuando el conjunto de la base cambia (count/max id),
        en vez de releer y deserializar toda la base en cada frame.
        """
        fingerprint = self._gallery_fingerprint()
        if self._gallery_cache is not None and fingerprint == self._gallery_cache_fp:
            return self._gallery_cache

        gallery: list[tuple[str, int, np.ndarray]] = []
        for emb in self.embedding_repo.list_all():
            vector = bytes_to_vector(emb.vector, dim=emb.dim)
            norm = float(np.linalg.norm(vector))
            if norm > 0:
                vector = (vector / norm).astype(np.float32)
            gallery.append((emb.person_uuid, emb.id, vector))

        self._gallery_cache = gallery
        self._gallery_cache_fp = fingerprint
        return gallery

    def _index(self, gallery: list[tuple[str, int, np.ndarray]],
               fingerprint: tuple | None = None):
        """Índice ANN compartido para la galería actual (o ``None`` para lineal).

        ``fingerprint`` evita recalcular la marca de la galería (una consulta
        SQL ``count/max``) cuando ya se conoce.
        """
        return get_shared_index(
            gallery, fingerprint if fingerprint is not None else self._gallery_fingerprint())

    def _rank_1n(self, query: np.ndarray, gallery: list[tuple[str, int, np.ndarray]],
                 top_k: int | None = None, fingerprint: tuple | None = None) -> list[MatchCandidate]:
        """Ranking 1:N con índice ANN cuando aplica; búsqueda lineal exacta como fallback.

        ``fingerprint`` se propaga para no consultar la BD por cada rostro.
        """
        index = self._index(gallery, fingerprint)
        if index is not None:
            return index.search(query, top_k or settings.recognition.top_k_results)
        return rank_candidates(query, gallery, top_k=top_k)

    def search_similar(
        self, image_bgr: np.ndarray, top_k: int | None = None,
        log_event: bool = False, usuario: str | None = None,
    ) -> list[MatchCandidate]:
        faces = self.engine.analyze(image_bgr)
        face = max(faces, key=_largest_area) if faces else None
        if face is None:
            raise NoFaceDetectedError("No se detectó ningún rostro en la imagen de búsqueda.")

        self._quality_valid(image_bgr, face, raise_on_fail=True)

        gallery = self._load_gallery()
        fingerprint = self._gallery_fingerprint()
        results = self._rank_1n(face.embedding, gallery, top_k=top_k, fingerprint=fingerprint)

        if log_event:
            best = results[0] if results else None
            event = RecognitionEvent(
                origen="imagen",
                person_uuid=best.person_uuid if best and best.is_match else None,
                confianza=best.confidence_pct if best else 0.0,
                distancia=best.distance if best else 1.0,
                det_confidence=face.det_score,
                usuario=usuario,
            )
            self.session.add(event)

        return results

    # ------------------------------------------------------------------ #
    # Reconocimiento multi-rostro (webcam / video / foto grupal)
    # ------------------------------------------------------------------ #
    def recognize_frame(
        self, image_bgr: np.ndarray, person_lookup: dict[str, str] | None = None,
        log_event: bool = False, origen: str = "webcam", usuario: str | None = None,
        log_only_matches: bool = False,
        with_attributes: bool = True,
    ) -> list[RecognizedFace]:
        """
        Detecta y reconoce TODOS los rostros de un frame.
        person_lookup: mapa opcional {uuid: nombre_completo} para no golpear la BD por cada rostro.
        log_only_matches: cuando True solo se registra el historial para rostros reconocidos
            (evita inundar la tabla de eventos con 'Desconocido' en webcam/video).
        with_attributes: si False, omite MediaPipe (ahorra ~30ms por cara en vivo).
        Los rostros que no superan el gate de calidad no generan match ni evento.
        """
        faces = self.engine.analyze(image_bgr)
        gallery = self._load_gallery()
        fingerprint = self._gallery_fingerprint() if gallery else None
        results: list[RecognizedFace] = []

        for face in faces:
            if not self._quality_valid(image_bgr, face):
                continue

            best_match: MatchCandidate | None = None
            if gallery:
                ranked = self._rank_1n(face.embedding, gallery, top_k=1,
                                       fingerprint=fingerprint)
                if ranked and ranked[0].is_match:
                    best_match = ranked[0]

            nombre = None
            if best_match and person_lookup:
                nombre = person_lookup.get(best_match.person_uuid)

            attrs = None
            if with_attributes:
                attrs = self.attributes.analyze(image_bgr, face.bbox, face.landmarks)
            recognized = RecognizedFace(
                bbox=face.bbox,
                person_uuid=best_match.person_uuid if best_match else None,
                person_nombre=nombre,
                confidence_pct=best_match.confidence_pct if best_match else 0.0,
                distance=best_match.distance if best_match else 1.0,
                det_score=face.det_score,
                attributes=attrs,
            )
            results.append(recognized)

            if log_event and (not log_only_matches or recognized.person_uuid is not None):
                event = RecognitionEvent(
                    origen=origen,
                    person_uuid=recognized.person_uuid,
                    confianza=recognized.confidence_pct,
                    distancia=recognized.distance,
                    det_confidence=face.det_score,
                    usuario=usuario,
                )
                self.session.add(event)

        return results


def _low_quality_message(face: FaceResult, quality: QualityScores) -> str:
    reasons = []
    if not quality.size_ok:
        reasons.append("el rostro es demasiado pequeño")
    if abs(quality.yaw_deg) > settings.vision.max_yaw_deg:
        reasons.append(f"girado de perfil ({quality.yaw_deg:.0f}°)")
    if abs(quality.pitch_deg) > settings.vision.max_pitch_deg:
        reasons.append(f"cabeza inclinada verticalmente ({quality.pitch_deg:.0f}°)")
    if quality.calidad_global < settings.vision.quality_min_score:
        reasons.append(f"calidad baja ({quality.calidad_global:.0f}/100)")
    return ("Rostro con calidad insuficiente: " + ", ".join(reasons or ["desconocida"])
            + ". Acércate y mejora la iluminación.")