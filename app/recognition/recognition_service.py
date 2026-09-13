"""Facial recognition service: bridges the vision engine and biometric DB.

Connects the vision engine (app.vision) with the biometric database
(app.database) without either knowing the other directly. Business logic for:

- registering a person's photo embedding,
- comparing two faces (1:1),
- searching for the most similar person(s) to a given face (1:N),
- recognizing all faces in an image/frame (webcam, video).

Applies a quality gate in all recognition flows (not only at enrollment):
matches on blurry, dark, poorly posed, or too-small faces are not emitted,
reducing false positives in live operation.
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
    """Recognized face with identity and confidence."""

    bbox: tuple[float, float, float, float]
    person_uuid: str | None
    person_nombre: str | None
    confidence_pct: float
    distance: float
    det_score: float = 0.0
    attributes: FaceAttributes | None = None


def _largest_area(result: FaceResult) -> float:
    """Compute bounding-box area for a FaceResult.

    Args:
        result: Face detection result.

    Returns:
        Area in pixels.
    """
    x1, y1, x2, y2 = result.bbox
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


class RecognitionService:
    """Service orchestrating detection, quality gating, and matching."""

    def __init__(self, session: Session):
        """Initialize the service.

        Args:
            session: Active SQLAlchemy session.
        """
        self.session = session
        self.embedding_repo = EmbeddingRepository(session)
        self.engine = FaceEngine.instance()
        self.attributes = FaceAttributeAnalyzer.instance()
        self._gallery_cache: list[tuple[str, int, np.ndarray]] | None = None
        self._gallery_cache_fp = None

    # ------------------------------------------------------------------ #
    # Quality gate (applied to all match flows)
    # ------------------------------------------------------------------ #
    def _quality_valid(self, image_bgr: np.ndarray, face: FaceResult,
                       raise_on_fail: bool = False) -> bool:
        """Check if a face passes the quality gate.

        Args:
            image_bgr: Source image.
            face: Detected face.
            raise_on_fail: Whether to raise LowQualityFaceError on failure.

        Returns:
            True if quality is sufficient.

        Raises:
            LowQualityFaceError: If quality is insufficient and raise_on_fail is True.
        """
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
    # Enrollment
    # ------------------------------------------------------------------ #
    def enroll_photo(
        self, person_uuid: str, image_bgr: np.ndarray, photo_id: int | None = None,
        usuario: str | None = None,
    ) -> FaceEmbedding:
        """Extract a face embedding from a photo and persist it.

        Validates the photo before persisting: single face (if enabled),
        minimum quality, frontal pose, and sufficient size. Also rejects
        embeddings that collide biometrically with another person.

        Args:
            person_uuid: Owner person UUID.
            image_bgr: Photo image in BGR format.
            photo_id: Associated Photo ID, if any.
            usuario: Acting username for audit logging.

        Returns:
            Persisted FaceEmbedding.

        Raises:
            NoFaceDetectedError: If no face is found.
            MultipleFacesError: If multiple faces are found and single-face enrollment is required.
            LowQualityFaceError: If quality checks fail.
            DuplicatePersonError: If the face matches another person.
        """
        faces = self.engine.analyze(image_bgr)
        if not faces:
            raise NoFaceDetectedError("No face detected in the photo.")

        if len(faces) > 1:
            if settings.vision.enroll_require_single_face:
                raise MultipleFacesError(
                    f"Detected {len(faces)} faces in the photo. "
                    "Upload a photo with a single person."
                )
            face = max(faces, key=_largest_area)
        else:
            face = faces[0]

        quality = evaluate_quality(image_bgr, face.bbox, face.landmarks)
        reasons = []
        if not quality.size_ok:
            reasons.append("face too small or too far")
        if (abs(quality.yaw_deg) > settings.vision.max_yaw_deg
                or abs(quality.pitch_deg) > settings.vision.max_pitch_deg):
            reasons.append("non-frontal face (turn toward the camera)")
        if quality.calidad_global < settings.vision.quality_min_score:
            reasons.append(
                f"quality {quality.calidad_global:.0f}/100 "
                "(needs to be sharper or better lit)")
        if reasons:
            raise LowQualityFaceError(
                "Insufficient face quality: " + ", ".join(reasons) + "."
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
            "Embedding enrolled | person={} | quality={} | user={}",
            person_uuid, quality.calidad_global, usuario or "system",
        )
        return embedding

    def _reject_duplicate(self, person_uuid: str, embedding: np.ndarray) -> None:
        """Reject a face that collides biometrically with another person.

        Args:
            person_uuid: Enrolling person UUID (excluded from comparison).
            embedding: New face embedding.

        Raises:
            DuplicatePersonError: If a duplicate is found.
        """
        threshold = settings.recognition.dedupe_threshold
        for other_uuid, _emb_id, vector in self._load_gallery():
            if other_uuid == person_uuid:
                continue
            if cosine_distance(embedding, vector) < threshold:
                raise DuplicatePersonError(
                    "This face is already registered to another person. "
                    "Check for duplicates in the database."
                )

    # ------------------------------------------------------------------ #
    # 1:1 comparison
    # ------------------------------------------------------------------ #
    def compare_images(self, image_a_bgr: np.ndarray, image_b_bgr: np.ndarray) -> dict:
        """Compare two face images 1:1.

        Args:
            image_a_bgr: First image in BGR format.
            image_b_bgr: Second image in BGR format.

        Returns:
            Comparison result dictionary including face data.

        Raises:
            NoFaceDetectedError: If no face is detected in either image.
            LowQualityFaceError: If either face fails the quality gate.
        """
        faces = self.engine.analyze(image_a_bgr)
        face_a = max(faces, key=_largest_area) if faces else None
        faces = self.engine.analyze(image_b_bgr)
        face_b = max(faces, key=_largest_area) if faces else None
        if face_a is None or face_b is None:
            raise NoFaceDetectedError("No face detected in one of the two images.")

        self._quality_valid(image_a_bgr, face_a, raise_on_fail=True)
        self._quality_valid(image_b_bgr, face_b, raise_on_fail=True)

        result = compare_pair(face_a.embedding, face_b.embedding)
        result["face_a"] = face_a
        result["face_b"] = face_b
        return result

    # ------------------------------------------------------------------ #
    # 1:N search
    # ------------------------------------------------------------------ #
    def _gallery_fingerprint(self) -> tuple:
        """Return a fingerprint of the current gallery (count, max_id).

        Returns:
            Tuple fingerprint for cache invalidation.
        """
        row = self.session.execute(
            select(func.count(FaceEmbedding.id), func.max(FaceEmbedding.id))
        ).one()
        return (int(row[0]), int(row[1]) if row[1] is not None else -1)

    def _load_gallery(self) -> list[tuple[str, int, np.ndarray]]:
        """Return the embedding gallery, cached and normalized.

        Recomputed only when the gallery fingerprint changes (count/max id),
        instead of re-reading and deserializing on every frame.

        Returns:
            List of (person_uuid, embedding_id, normalized_vector).
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
        """Return the shared ANN index for the current gallery, or None for linear.

        Args:
            gallery: Gallery list.
            fingerprint: Precomputed fingerprint to avoid an extra DB query.

        Returns:
            BiometricIndex or None.
        """
        return get_shared_index(
            gallery, fingerprint if fingerprint is not None else self._gallery_fingerprint())

    def _rank_1n(self, query: np.ndarray, gallery: list[tuple[str, int, np.ndarray]],
                 top_k: int | None = None, fingerprint: tuple | None = None) -> list[MatchCandidate]:
        """Rank 1:N using ANN index when available; exact linear search as fallback.

        Args:
            query: Query embedding.
            gallery: Gallery list.
            top_k: Maximum results.
            fingerprint: Gallery fingerprint to avoid re-querying the DB.

        Returns:
            Ranked candidates.
        """
        index = self._index(gallery, fingerprint)
        if index is not None:
            return index.search(query, top_k or settings.recognition.top_k_results)
        return rank_candidates(query, gallery, top_k=top_k)

    def search_similar(
        self, image_bgr: np.ndarray, top_k: int | None = None,
        log_event: bool = False, usuario: str | None = None,
    ) -> list[MatchCandidate]:
        """Search for similar persons to a face image.

        Args:
            image_bgr: Query image in BGR format.
            top_k: Maximum results to return.
            log_event: Whether to log a RecognitionEvent.
            usuario: Acting username.

        Returns:
            Ranked match candidates.

        Raises:
            NoFaceDetectedError: If no face is detected.
            LowQualityFaceError: If the face fails the quality gate.
        """
        faces = self.engine.analyze(image_bgr)
        face = max(faces, key=_largest_area) if faces else None
        if face is None:
            raise NoFaceDetectedError("No face detected in the search image.")

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
    # Multi-face recognition (webcam / video / group photo)
    # ------------------------------------------------------------------ #
    def recognize_frame(
        self, image_bgr: np.ndarray, person_lookup: dict[str, str] | None = None,
        log_event: bool = False, origen: str = "webcam", usuario: str | None = None,
        log_only_matches: bool = False,
        with_attributes: bool = True,
    ) -> list[RecognizedFace]:
        """Detect and recognize all faces in a frame.

        Args:
            image_bgr: Frame in BGR format.
            person_lookup: Optional map {uuid: full_name} to avoid DB hits.
            log_event: Whether to persist RecognitionEvent entries.
            origen: Event origin label.
            usuario: Acting username.
            log_only_matches: If True, log only recognized faces (avoid flooding
                the events table with "Unknown" in webcam/video).
            with_attributes: If False, skip MediaPipe (saves ~30 ms per face).

        Returns:
            List of RecognizedFace. Faces failing the quality gate produce no
            match or event.
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
    """Build a human-readable low-quality message.

    Args:
        face: Face result (unused, kept for API symmetry).
        quality: Quality scores.

    Returns:
        Descriptive message.
    """
    reasons = []
    if not quality.size_ok:
        reasons.append("face too small")
    if abs(quality.yaw_deg) > settings.vision.max_yaw_deg:
        reasons.append(f"profile turn ({quality.yaw_deg:.0f} deg)")
    if abs(quality.pitch_deg) > settings.vision.max_pitch_deg:
        reasons.append(f"vertical head tilt ({quality.pitch_deg:.0f} deg)")
    if quality.calidad_global < settings.vision.quality_min_score:
        reasons.append(f"low quality ({quality.calidad_global:.0f}/100)")
    return ("Insufficient face quality: " + ", ".join(reasons or ["unknown"])
            + ". Move closer and improve lighting.")
