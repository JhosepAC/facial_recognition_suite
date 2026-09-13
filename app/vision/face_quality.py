"""Facial quality scores for a specific detection.

Covers the "Facial Analysis" section of the spec: sharpness (blur),
illumination, and pose (yaw/pitch/roll) from the 5 landmarks returned by the
detector.

TODO(Phase 2): Glasses/mask/beard/moustache/smile detection requires a trained
attribute classifier and is not simulated here.

The overall quality is computed as a weighted average of sharpness and
illumination multiplied by a pose factor (0..1): pose penalizes multiplicatively
rather than additively, so a blurry, dark, and poorly oriented face never
reaches a high threshold for free.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.core.config import settings


@dataclass
class QualityScores:
    """Quality metrics for a detected face."""

    nitidez: float  # 0-100, higher is sharper (normalized Laplacian variance).
    iluminacion: float  # 0-100, 50 is optimal exposure.
    inclinacion_deg: float  # Roll (in-plane rotation).
    yaw_deg: float  # Lateral turn (looking sideways).
    pitch_deg: float  # Vertical tilt (up/down).
    pose_factor: float  # 0..1, pose multiplier applied to quality.
    size_ok: bool  # True if the bbox exceeds the minimum usable size.
    calidad_global: float  # 0-100, weighted combination * pose factor.


def _crop_bbox(image_bgr: np.ndarray, bbox: tuple[float, float, float, float]) -> np.ndarray:
    """Crop the image to the bounding box, clamped to image bounds.

    Args:
        image_bgr: Source image in BGR format.
        bbox: Bounding box as (x1, y1, x2, y2).

    Returns:
        Cropped image region.
    """
    h, w = image_bgr.shape[:2]
    x1, y1, x2, y2 = [int(max(0, v)) for v in bbox]
    x2, y2 = min(w, x2), min(h, y2)
    return image_bgr[y1:y2, x1:x2]


def compute_pose_angles(landmarks: np.ndarray) -> tuple[float, float, float]:
    """Estimate (yaw, pitch, roll) in degrees from the 5 InsightFace landmarks.

    InsightFace does not provide head orientation; this is a geometric
    approximation using nose asymmetry relative to the eye line and mouth
    (sufficient for a quality gate, not for precise tracking).

    Args:
        landmarks: Array of 5 landmark points.

    Returns:
        Tuple of (yaw, pitch, roll) in degrees.
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
    """Return a normalized face crop centered and eye-line aligned.

    Produces a uniform template (rotation/translation normalized) so that
    sharpness and illumination are always measured over the same facial region.

    Args:
        image_bgr: Source image in BGR format.
        landmarks: Array of 5 landmark points.
        size: Output square size in pixels.

    Returns:
        Aligned face image of shape (size, size, 3).
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
    """Compute sharpness score via Laplacian variance.

    Args:
        face_crop_bgr: Cropped face image in BGR format.

    Returns:
        Sharpness score in [0, 100].
    """
    if face_crop_bgr.size == 0:
        return 0.0
    gray = cv2.cvtColor(face_crop_bgr, cv2.COLOR_BGR2GRAY)
    variance = cv2.Laplacian(gray, cv2.CV_64F).var()
    # Empirical normalization: ~1200 variance is considered very sharp.
    return float(np.clip(variance / 1200.0 * 100.0, 0, 100))


def compute_illumination(face_crop_bgr: np.ndarray, enhance: bool = True) -> float:
    """Compute illumination score from mean brightness.

    Args:
        face_crop_bgr: Cropped face image in BGR format.
        enhance: Whether to apply CLAHE before measuring exposure.

    Returns:
        Illumination score in [0, 100].
    """
    if face_crop_bgr.size == 0:
        return 0.0
    gray = cv2.cvtColor(face_crop_bgr, cv2.COLOR_BGR2GRAY)
    if enhance:
        # CLAHE corrects backlight and shadows before measuring exposure
        # to avoid penalizing valid faces in high-contrast scenes.
        gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    mean_brightness = float(np.mean(gray))  # 0-255
    # Peak score near 130/255 (average exposure), penalizes extremes.
    score = 100.0 - (abs(mean_brightness - 130.0) / 130.0) * 100.0
    return float(np.clip(score, 0, 100))


def _pose_factor(yaw: float, pitch: float) -> float:
    """Compute multiplicative pose factor (0..1) with angle tolerances.

    Args:
        yaw: Yaw angle in degrees.
        pitch: Pitch angle in degrees.

    Returns:
        Multiplicative factor in [0, 1].
    """
    max_yaw = settings.vision.max_yaw_deg
    max_pitch = settings.vision.max_pitch_deg
    yaw_pen = max(0.0, abs(yaw) - max_yaw) / max(1.0, max_yaw)
    pitch_pen = max(0.0, abs(pitch) - max_pitch) / max(1.0, max_pitch)
    return float(np.clip(1.0 - (yaw_pen + 0.5 * pitch_pen), 0.0, 1.0))


def evaluate(
    image_bgr: np.ndarray, bbox: tuple[float, float, float, float],
    landmarks: np.ndarray, min_face_size: int | None = None,
) -> QualityScores:
    """Evaluate facial quality for a detection.

    Args:
        image_bgr: Source image in BGR format.
        bbox: Face bounding box as (x1, y1, x2, y2).
        landmarks: Array of 5 landmark points.
        min_face_size: Minimum face size in pixels. Defaults to settings.

    Returns:
        QualityScores with all metrics populated.
    """
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
