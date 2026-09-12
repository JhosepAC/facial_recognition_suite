"""
Puntuaciones de calidad facial para una detección concreta.

Cubre la sección "Análisis facial" del spec: nitidez (desenfoque), iluminación
y pose (yaw/pitch/roll) a partir de los 5 landmarks devueltos por el detector.
Gafas/mascarilla/barba/bigote/sonrisa quedan como TODO de Fase 2 (requieren
un clasificador de atributos entrenado; no se simula esa salida aquí).

La calidad global se calcula como una media ponderada de nitidez e
iluminación multiplicada por un factor de pose (0..1): la pose penaliza de
forma multiplicativa, no aditiva, de modo que un rostro borroso, oscuro y
mal encarado jamás alcanza un umbral alto "gratis".
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.core.config import settings


@dataclass
class QualityScores:
    nitidez: float        # 0-100, mayor = más nítido (varianza del Laplaciano, normalizada)
    iluminacion: float    # 0-100, 50 = exposición óptima
    inclinacion_deg: float  # "roll" (rotación en el plano de la imagen)
    yaw_deg: float          # giro lateral (mirando a los lados)
    pitch_deg: float        # inclinación vertical (arriba/abajo)
    pose_factor: float      # 0..1, multiplicador de pose aplicado a la calidad
    size_ok: bool           # True si el bbox supera el tamaño mínimo utilizable
    calidad_global: float   # 0-100, combinación ponderada * factor de pose


def _crop_bbox(image_bgr: np.ndarray, bbox: tuple[float, float, float, float]) -> np.ndarray:
    h, w = image_bgr.shape[:2]
    x1, y1, x2, y2 = [int(max(0, v)) for v in bbox]
    x2, y2 = min(w, x2), min(h, y2)
    return image_bgr[y1:y2, x1:x2]


def compute_pose_angles(landmarks: np.ndarray) -> tuple[float, float, float]:
    """Estima (yaw, pitch, roll) en grados con los 5 landmarks de InsightFace.

    InsightFace no entrega orientación de cabeza; esta es una aproximación
    geométrica con la asimetría de la nariz respecto de la línea de ojos y la
    boca (suficiente para un gate de calidad, no para tracking preciso).
    """
    left_eye, right_eye, nose = landmarks[0], landmarks[1], landmarks[2]
    left_mouth, right_mouth = landmarks[3], landmarks[4]
    interocular = float(np.linalg.norm(right_eye - left_eye)) + 1e-6
    mouth_span = float(np.linalg.norm(right_mouth - left_mouth)) + 1e-6

    roll = float(np.degrees(np.arctan2(
        right_eye[1] - left_eye[1], right_eye[0] - left_eye[0])))
    eye_mid = (left_eye + right_eye) / 2.0
    yaw = float(np.degrees(np.arctan2(nose[0] - eye_mid[0], interocular)))
    pitch = float(np.degrees(np.arctan2(nose[1] - eye_mid[1], mouth_span)))

    return yaw, pitch, roll


def align_face(image_bgr: np.ndarray, landmarks: np.ndarray, size: int = 96) -> np.ndarray:
    """Recorte facial normalizado: centrado y alineado por la línea de ojos.

    Produce una plantilla uniforme (rotación/traslación normalizadas) para que
    nitidez e iluminación se midan siempre sobre la misma región del rostro.
    """
    src = np.asarray(landmarks[:5], dtype=np.float32)
    dst = np.float32([
        [size * 0.30, size * 0.30],
        [size * 0.70, size * 0.30],
        [size * 0.50, size * 0.55],
        [size * 0.30, size * 0.80],
        [size * 0.70, size * 0.80],
    ])
    transform, _ = cv2.estimateAffinePartial2D(src, dst, method=cv2.LMEDS)
    if transform is None:
        return _crop_bbox(image_bgr, (
            np.min(landmarks[:, 0]) - size * 0.2, np.min(landmarks[:, 1]) - size * 0.2,
            np.max(landmarks[:, 0]) + size * 0.2, np.max(landmarks[:, 1]) + size * 0.2,
        ))
    return cv2.warpAffine(
        image_bgr, transform, (size, size),
        flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE,
    )


def compute_sharpness(face_crop_bgr: np.ndarray) -> float:
    if face_crop_bgr.size == 0:
        return 0.0
    gray = cv2.cvtColor(face_crop_bgr, cv2.COLOR_BGR2GRAY)
    variance = cv2.Laplacian(gray, cv2.CV_64F).var()
    # Normalización empírica: ~1200 de varianza ya se considera muy nítido
    return float(np.clip(variance / 1200.0 * 100.0, 0, 100))


def compute_illumination(face_crop_bgr: np.ndarray, enhance: bool = True) -> float:
    if face_crop_bgr.size == 0:
        return 0.0
    gray = cv2.cvtColor(face_crop_bgr, cv2.COLOR_BGR2GRAY)
    if enhance:
        # CLAHE corrige contraluz y sombras antes de medir la exposición,
        # para no penalizar rostros válidos en escenas de alto contraste.
        gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    mean_brightness = float(np.mean(gray))  # 0-255
    # Puntuación máxima cerca de 130/255 (exposición media), penaliza extremos
    score = 100.0 - (abs(mean_brightness - 130.0) / 130.0) * 100.0
    return float(np.clip(score, 0, 100))


def _pose_factor(yaw: float, pitch: float) -> float:
    """Factor multiplicativo (0..1): tolerancias de ángulo antes de penalizar."""
    max_yaw = settings.vision.max_yaw_deg
    max_pitch = settings.vision.max_pitch_deg
    yaw_pen = max(0.0, abs(yaw) - max_yaw) / max(1.0, max_yaw)
    pitch_pen = max(0.0, abs(pitch) - max_pitch) / max(1.0, max_pitch)
    return float(np.clip(1.0 - (yaw_pen + 0.5 * pitch_pen), 0.0, 1.0))


def evaluate(
    image_bgr: np.ndarray, bbox: tuple[float, float, float, float],
    landmarks: np.ndarray, min_face_size: int | None = None,
) -> QualityScores:
    if min_face_size is None:
        min_face_size = settings.vision.min_face_size

    x1, y1, x2, y2 = bbox
    size_ok = (x2 - x1) >= min_face_size and (y2 - y1) >= min_face_size

    aligned = align_face(image_bgr, landmarks)
    nitidez = compute_sharpness(aligned)
    iluminacion = compute_illumination(aligned)
    yaw, pitch, roll = compute_pose_angles(landmarks)
    factor = _pose_factor(yaw, pitch)

    calidad_global = (0.6 * nitidez + 0.4 * iluminacion) * factor

    return QualityScores(
        nitidez=round(nitidez, 1),
        iluminacion=round(iluminacion, 1),
        inclinacion_deg=round(roll, 1),
        yaw_deg=round(yaw, 1),
        pitch_deg=round(pitch, 1),
        pose_factor=round(factor, 3),
        size_ok=size_ok,
        calidad_global=round(float(np.clip(calidad_global, 0, 100)), 1),
    )