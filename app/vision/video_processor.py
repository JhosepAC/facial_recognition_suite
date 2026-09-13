"""Frame extraction from a video file for analysis.

Performance strategy: instead of analyzing every frame (costly and unnecessary
for most videos), sample 1 of every N frames (configurable) and optionally
resize the frame before passing it to the detector, scaling coordinates back to
the original size for high-resolution evidence crops.
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
    """Metadata extracted from a video file."""

    fps: float
    total_frames: int
    duration_seg: float
    width: int
    height: int


@dataclass
class SampledFrame:
    """A sampled frame with its index and timestamp."""

    frame_number: int
    timestamp_seg: float
    frame_bgr: np.ndarray


class VideoReader:
    """Wrapper around cv2.VideoCapture for sequential and random access."""

    def __init__(self, file_path: str):
        """Initialize the reader.

        Args:
            file_path: Path to the video file.
        """
        self.file_path = file_path
        self._cap: cv2.VideoCapture | None = None

    def open(self) -> VideoMetadata:
        """Open the video file and return its metadata.

        Returns:
            VideoMetadata for the opened file.

        Raises:
            BioVisionError: If the file does not exist or cannot be opened.
        """
        if not Path(self.file_path).exists():
            raise BioVisionError(f"Video file does not exist: {self.file_path}")

        self._cap = cv2.VideoCapture(self.file_path)
        if not self._cap.isOpened():
            raise BioVisionError(
                f"Could not open video (unsupported codec or corrupted file): {self.file_path}"
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
        """Iterate sequentially, yielding 1 of every ``interval_frames``.

        Args:
            interval_frames: Sampling interval (1 means every frame).

        Yields:
            SampledFrame objects.

        Raises:
            BioVisionError: If the video has not been opened.
        """
        if self._cap is None:
            raise BioVisionError("Video has not been opened. Call open() first.")

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
        """Random access read for GUI navigation/preview.

        Args:
            frame_number: Target frame index.

        Returns:
            BGR frame or None if not available.

        Raises:
            BioVisionError: If the video has not been opened.
        """
        if self._cap is None:
            raise BioVisionError("Video has not been opened. Call open() first.")
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame_number))
        ok, frame = self._cap.read()
        return frame if ok else None

    def close(self) -> None:
        """Release the underlying VideoCapture."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self) -> "VideoReader":
        """Enter context manager, opening the video.

        Returns:
            Self after opening.
        """
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        """Exit context manager, releasing resources."""
        self.close()


def resize_for_detection(frame: np.ndarray, max_width: int) -> tuple[np.ndarray, float]:
    """Resize the frame if it exceeds max_width.

    Args:
        frame: Source image.
        max_width: Maximum allowed width.

    Returns:
        Tuple of (resized_frame, scale_factor).
    """
    h, w = frame.shape[:2]
    if w <= max_width:
        return frame, 1.0
    scale = max_width / w
    resized = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return resized, scale


def scale_bbox(bbox: tuple[float, float, float, float], scale: float) -> tuple[float, float, float, float]:
    """Rescale a bbox detected on a resized frame back to the original size.

    Args:
        bbox: Bounding box in resized coordinates.
        scale: Scale factor used for resizing.

    Returns:
        Bounding box in original coordinates.
    """
    x1, y1, x2, y2 = bbox
    return (x1 / scale, y1 / scale, x2 / scale, y2 / scale)


def crop_with_padding(
    frame: np.ndarray, bbox: tuple[float, float, float, float], padding_ratio: float
) -> np.ndarray:
    """Crop a padded region around the bounding box.

    Args:
        frame: Source image.
        bbox: Bounding box as (x1, y1, x2, y2).
        padding_ratio: Padding as a fraction of bbox size.

    Returns:
        Cropped image region.
    """
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = bbox
    bw, bh = x2 - x1, y2 - y1
    pad_x, pad_y = bw * padding_ratio, bh * padding_ratio

    x1 = max(0, int(x1 - pad_x))
    y1 = max(0, int(y1 - pad_y))
    x2 = min(w, int(x2 + pad_x))
    y2 = min(h, int(y2 + pad_y))
    return frame[y1:y2, x1:x2]
