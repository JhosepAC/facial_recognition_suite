"""
Extracción de frames de un archivo de video para su análisis.

Estrategia de rendimiento: en vez de analizar cada frame (costoso e
innecesario para la mayoría de videos), se muestrea 1 de cada N frames
(configurable), y opcionalmente se redimensiona el frame antes de pasarlo
al detector, escalando las coordenadas de vuelta al tamaño original para
recortes de evidencia con buena resolución.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np

from app.core.exceptions import BioVisionError


@dataclass
class VideoMetadata:
    fps: float
    total_frames: int
    duration_seg: float
    width: int
    height: int


@dataclass
class SampledFrame:
    frame_number: int
    timestamp_seg: float
    frame_bgr: np.ndarray


class VideoReader:
    """Envoltura sobre cv2.VideoCapture para lectura secuencial y por posición."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self._cap: cv2.VideoCapture | None = None

    def open(self) -> VideoMetadata:
        if not Path(self.file_path).exists():
            raise BioVisionError(f"El archivo de video no existe: {self.file_path}")

        self._cap = cv2.VideoCapture(self.file_path)
        if not self._cap.isOpened():
            raise BioVisionError(
                f"No se pudo abrir el video (códec no soportado o archivo corrupto): {self.file_path}"
            )

        fps = self._cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        duration = total_frames / fps if fps else 0.0

        return VideoMetadata(
            fps=fps, total_frames=total_frames, duration_seg=duration,
            width=width, height=height,
        )

    def iter_sampled_frames(self, interval_frames: int) -> Iterator[SampledFrame]:
        """Recorre el video secuencialmente, entregando 1 de cada `interval_frames`."""
        if self._cap is None:
            raise BioVisionError("El video no ha sido abierto. Llama a open() primero.")

        interval_frames = max(1, interval_frames)
        fps = self._cap.get(cv2.CAP_PROP_FPS) or 25.0
        frame_idx = 0

        while True:
            ok, frame = self._cap.read()
            if not ok:
                break
            if frame_idx % interval_frames == 0:
                yield SampledFrame(
                    frame_number=frame_idx,
                    timestamp_seg=frame_idx / fps,
                    frame_bgr=frame,
                )
            frame_idx += 1

    def read_frame_at(self, frame_number: int) -> np.ndarray | None:
        """Lectura aleatoria: usada por la GUI para navegar/previsualizar el video."""
        if self._cap is None:
            raise BioVisionError("El video no ha sido abierto. Llama a open() primero.")
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame_number))
        ok, frame = self._cap.read()
        return frame if ok else None

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self) -> "VideoReader":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def resize_for_detection(frame: np.ndarray, max_width: int) -> tuple[np.ndarray, float]:
    """Redimensiona el frame si excede max_width. Devuelve (frame_redimensionado, escala)."""
    h, w = frame.shape[:2]
    if w <= max_width:
        return frame, 1.0
    scale = max_width / w
    resized = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return resized, scale


def scale_bbox(bbox: tuple[float, float, float, float], scale: float) -> tuple[float, float, float, float]:
    """Reescala un bbox detectado en un frame redimensionado de vuelta al tamaño original."""
    x1, y1, x2, y2 = bbox
    return (x1 / scale, y1 / scale, x2 / scale, y2 / scale)


def crop_with_padding(
    frame: np.ndarray, bbox: tuple[float, float, float, float], padding_ratio: float
) -> np.ndarray:
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = bbox
    bw, bh = x2 - x1, y2 - y1
    pad_x, pad_y = bw * padding_ratio, bh * padding_ratio

    x1 = max(0, int(x1 - pad_x))
    y1 = max(0, int(y1 - pad_y))
    x2 = min(w, int(x2 + pad_x))
    y2 = min(h, int(y2 + pad_y))
    return frame[y1:y2, x1:x2]
