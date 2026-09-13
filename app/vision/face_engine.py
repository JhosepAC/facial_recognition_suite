"""Facial vision engine: detection + landmarks + biometric embedding.

Implementation:
    InsightFace + buffalo_l + ONNX Runtime.

In development:
    Models are looked up in ~/.insightface/models/buffalo_l.

In the packaged PyInstaller application:
    Models are looked up inside:
        <bundle>/_internal/models/buffalo_l

This allows distributing FaceScan fully offline without relying on InsightFace
downloading buffalo_l on the end-user machine.
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app.core.config import settings
from app.core.exceptions import ModelLoadError
from app.core.logger import logger


@dataclass
class FaceResult:
    """Result for a single detected face."""

    bbox: tuple[float, float, float, float]
    det_score: float
    landmarks: np.ndarray
    embedding: np.ndarray
    age: int | None = None
    gender: str | None = None


class FaceEngine:
    """Wrapper around insightface.app.FaceAnalysis.

    Features:
        - Singleton.
        - Lazy loading.
        - Thread-safe.
        - Automatically detects PyInstaller execution.
        - Uses bundled models when packaged.
        - Uses ~/.insightface/models when running from Python.
    """

    _instance: "FaceEngine | None" = None

    # Filenames that buffalo_l must contain.
    REQUIRED_MODEL_FILES = (
        "1k3d68.onnx",
        "2d106det.onnx",
        "det_10g.onnx",
        "genderage.onnx",
        "w600k_r50.onnx",
    )

    def __init__(self):
        """Initialize the engine (model is loaded lazily)."""
        self._app = None
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # SINGLETON
    # ------------------------------------------------------------------

    @classmethod
    def instance(cls) -> "FaceEngine":
        """Return the singleton instance.

        Returns:
            Shared FaceEngine instance.
        """
        if cls._instance is None:
            cls._instance = FaceEngine()
        return cls._instance

    # ------------------------------------------------------------------
    # STATE
    # ------------------------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        """Whether the underlying FaceAnalysis model is loaded."""
        return self._app is not None

    # ------------------------------------------------------------------
    # SAFE IMAGE LOADING
    # ------------------------------------------------------------------

    @staticmethod
    def load_image_bgr(image_input: str | Path | np.ndarray | None) -> np.ndarray:
        """Load or validate a BGR image safely on Windows.

        Supports paths with spaces, accents, and Unicode characters.

        Args:
            image_input: File path or in-memory BGR image.

        Returns:
            BGR image as a numpy array.

        Raises:
            ValueError: If the input is None, empty, or cannot be decoded.
            FileNotFoundError: If the file does not exist.
        """
        if image_input is None:
            raise ValueError("No image provided or path is None.")
        if isinstance(image_input, np.ndarray):
            if image_input.size == 0 or len(image_input.shape) < 2:
                raise ValueError("Provided in-memory image is empty or invalid.")
            return image_input

        path_obj = Path(image_input)
        if not path_obj.exists():
            raise FileNotFoundError(f"Image file not found: {image_input}")

        # Read file as bytes independent of the Windows filesystem handling.
        img_bytes = np.fromfile(str(path_obj), dtype=np.uint8)
        img = cv2.imdecode(img_bytes, cv2.IMREAD_COLOR)

        if img is None:
            raise ValueError(
                f"Could not decode image (unsupported format or corrupted file): {image_input}"
            )

        return img

    # ------------------------------------------------------------------
    # PYINSTALLER
    # ------------------------------------------------------------------

    @staticmethod
    def _is_frozen() -> bool:
        """Return True when running from a PyInstaller bundle.

        Returns:
            True if frozen, False otherwise.
        """
        return bool(
            getattr(sys, "frozen", False)
            and hasattr(sys, "_MEIPASS")
        )

    @classmethod
    def _bundle_root(cls) -> Path | None:
        """Get the internal root of the PyInstaller bundle.

        In PyInstaller 6.x for onedir it is typically:

            FaceScan/
                FaceScan.exe
                _internal/
                    ...

        and sys._MEIPASS points to:

            FaceScan/_internal

        Returns:
            Bundle root path or None if not frozen.
        """
        if not cls._is_frozen():
            return None

        return Path(sys._MEIPASS).resolve()

    @classmethod
    def _model_root(cls) -> Path:
        """Return the root directory InsightFace should use.

        Development:
            ~/.insightface

        PyInstaller:
            <bundle>/_internal

        Returns:
            Root path for InsightFace models.
        """
        bundle_root = cls._bundle_root()

        if bundle_root is not None:
            root = bundle_root

            logger.info(
                "FaceScan running as packaged application."
            )
            logger.info(
                "PyInstaller internal directory: {}",
                root,
            )

            return root

        # Normal execution from Python.
        root = Path.home() / ".insightface"

        logger.info(
            "FaceScan running from Python."
        )
        logger.info(
            "InsightFace root directory: {}",
            root,
        )

        return root

    @classmethod
    def _model_dir(cls) -> Path:
        """Return the exact directory where InsightFace should find buffalo_l.

        Returns:
            Model directory path.
        """
        return cls._model_root() / "models" / settings.vision.detector_model

    @classmethod
    def _validate_models(cls, model_dir: Path) -> None:
        """Verify that all required ONNX files exist.

        Prevents InsightFace from silently attempting to download models when
        the application is packaged.

        Args:
            model_dir: Directory expected to contain buffalo_l.

        Raises:
            ModelLoadError: If the directory or required files are missing.
        """
        if not model_dir.exists():
            raise ModelLoadError(
                f"InsightFace model directory does not exist:\n"
                f"{model_dir}"
            )

        missing = [
            filename
            for filename in cls.REQUIRED_MODEL_FILES
            if not (model_dir / filename).is_file()
        ]

        if missing:
            raise ModelLoadError(
                "Missing InsightFace models.\n"
                f"Directory: {model_dir}\n"
                f"Missing: {', '.join(missing)}"
            )

        found = sorted(
            path.name
            for path in model_dir.glob("*.onnx")
        )

        logger.info(
            "InsightFace models found in {}: {}",
            model_dir,
            ", ".join(found),
        )

    # ------------------------------------------------------------------
    # ONNX RUNTIME
    # ------------------------------------------------------------------

    @staticmethod
    def _available_providers() -> list[str]:
        """Select available ONNX Runtime providers.

        Preference:
            1. CUDA
            2. CPU

        Falls back to CPU if CUDA is not installed.

        Returns:
            List of provider names to use.
        """
        try:
            import onnxruntime

            available = set(
                onnxruntime.get_available_providers()
            )

            logger.info(
                "ONNX Runtime available providers: {}",
                ", ".join(sorted(available)),
            )

        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Could not query ONNX Runtime: {}. "
                "Falling back to CPU.",
                exc,
            )

            return ["CPUExecutionProvider"]

        ordered = [
            "CUDAExecutionProvider",
            "CPUExecutionProvider",
        ]

        providers = [
            provider
            for provider in ordered
            if provider in available
        ]

        if not providers:
            providers = ["CPUExecutionProvider"]

        logger.info(
            "Selected providers for InsightFace: {}",
            ", ".join(providers),
        )

        return providers

    # ------------------------------------------------------------------
    # MODEL LOADING
    # ------------------------------------------------------------------

    def warmup(self) -> None:
        """Load models synchronously.

        Useful for preloading from an initialization thread.
        """
        self._ensure_loaded()

    def _ensure_loaded(self) -> None:
        """Load FaceAnalysis once.

        Uses double-checked locking to prevent two threads from loading
        models simultaneously.
        """
        if self._app is not None:
            return

        with self._lock:

            if self._app is not None:
                return

            try:
                from insightface.app import FaceAnalysis

                model_name = settings.vision.detector_model
                model_dir = self._model_dir()

                logger.info(
                    "Loading facial recognition models ({})...",
                    model_name,
                )

                logger.info(
                    "InsightFace root directory: {}",
                    self._model_root(),
                )

                logger.info(
                    "Model directory: {}",
                    model_dir,
                )

                self._validate_models(model_dir)

                providers = self._available_providers()
                ctx_id = settings.vision.ctx_id

                logger.info(
                    "Initializing FaceAnalysis with root={}",
                    self._model_root(),
                )

                # Try loading with preferred providers (e.g., CUDA / CPU).
                try:
                    self._app = FaceAnalysis(
                        name=model_name,
                        root=str(self._model_root()),
                        providers=providers,
                    )

                    det_size = tuple(settings.vision.det_size)

                    self._app.prepare(
                        ctx_id=ctx_id,
                        det_size=det_size,
                    )
                except Exception as provider_exc:
                    # Fallback to CPU if GPU/CUDA initialization fails.
                    logger.warning(
                        "Failed to initialize InsightFace with providers={}/ctx_id={}: {}. "
                        "Retrying with CPUExecutionProvider...",
                        providers, ctx_id, provider_exc
                    )
                    self._app = FaceAnalysis(
                        name=model_name,
                        root=str(self._model_root()),
                        providers=["CPUExecutionProvider"],
                    )
                    det_size = tuple(settings.vision.det_size)
                    self._app.prepare(
                        ctx_id=-1,
                        det_size=det_size,
                    )

                logger.info(
                    "Facial recognition models loaded successfully."
                )

            except ModelLoadError:
                raise

            except Exception as exc:  # noqa: BLE001

                logger.exception(
                    "Error loading InsightFace."
                )

                raise ModelLoadError(
                    "Could not load InsightFace models.\n\n"
                    f"Model: {settings.vision.detector_model}\n"
                    f"Directory: {self._model_dir()}\n\n"
                    f"Technical detail: {exc}\n\n"
                    "Verify that Microsoft Visual C++ Redistributable (x64) is installed."
                ) from exc

    # ------------------------------------------------------------------
    # AGE
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_age(raw_age) -> int | None:
        """Map InsightFace raw age estimate to a more conservative range.

        Note:
            The model age estimate should not be treated as an exact
            measurement.

        Args:
            raw_age: Raw age value from the model.

        Returns:
            Adjusted age or None if invalid.
        """
        if raw_age is None:
            return None

        try:
            if raw_age <= 0:
                return None

            a = float(raw_age)

        except (TypeError, ValueError):
            return None

        if a <= 10:
            a = a

        elif a <= 20:
            a = 8 + (a - 10) * 0.6

        elif a <= 40:
            a = 14 + (a - 20) * 0.7

        elif a <= 70:
            a = 28 + (a - 40) * 0.75

        else:
            a = 50 + (a - 70) * 0.5

        return int(
            round(
                max(
                    2.0,
                    min(a, 100.0),
                )
            )
        )

    # ------------------------------------------------------------------
    # RESULT CONVERSION
    # ------------------------------------------------------------------

    def _to_results(
        self,
        faces,
        bbox_scale: float = 1.0,
        min_confidence: float | None = None,
    ) -> list[FaceResult]:
        """Convert raw InsightFace results to FaceResult objects.

        Args:
            faces: Raw faces from FaceAnalysis.
            bbox_scale: Scale factor to apply to bbox/landmarks.
            min_confidence: Minimum detection confidence. Defaults to settings.

        Returns:
            Sorted list of FaceResult (descending confidence).
        """
        if min_confidence is None:
            min_confidence = (
                settings.vision.min_face_confidence
            )

        results: list[FaceResult] = []

        for face in faces:

            if float(face.det_score) < min_confidence:
                continue

            embedding = face.normed_embedding.astype(
                np.float32,
                copy=False,
            )

            if bbox_scale != 1.0:

                bbox = tuple(
                    float(value) * bbox_scale
                    for value in face.bbox.tolist()
                )

                landmarks = (
                    face.kps.astype(np.float32, copy=False)
                    * bbox_scale
                )

            else:

                bbox = tuple(
                    float(value)
                    for value in face.bbox.tolist()
                )

                landmarks = face.kps

            raw_gender = getattr(
                face,
                "gender",
                None,
            )

            if raw_gender is None:
                gender = None
            else:
                gender = "M" if raw_gender == 1 else "F"

            results.append(
                FaceResult(
                    bbox=bbox,
                    det_score=float(face.det_score),
                    landmarks=landmarks,
                    embedding=embedding,
                    age=self._resolve_age(
                        getattr(face, "age", None)
                    ),
                    gender=gender,
                )
            )

        results.sort(
            key=lambda result: result.det_score,
            reverse=True,
        )

        return results

    # ------------------------------------------------------------------
    # ANALYSIS
    # ------------------------------------------------------------------

    def analyze(
        self,
        bgr_image: np.ndarray | str | Path,
    ) -> list[FaceResult]:
        """Detect all faces in a BGR image (or from a str/Path).

        Returns FaceResult objects sorted by descending confidence.

        Strategy:
            1. Load/validate the image safely.
            2. Normal attempt.
            3. If no faces, try downscaled image.
            4. If still none, try upscaled image.

        Args:
            bgr_image: BGR image array or path to an image file.

        Returns:
            List of FaceResult sorted by detection confidence.
        """
        # Load/validate image safely for paths with accents/spaces.
        bgr_image = self.load_image_bgr(bgr_image)

        self._ensure_loaded()

        with self._lock:

            relaxed = max(
                0.30,
                settings.vision.min_face_confidence - 0.05,
            )

            # ----------------------------------------------------------
            # ATTEMPT 1: original image
            # ----------------------------------------------------------

            faces = self._app.get(bgr_image)

            results = self._to_results(
                faces,
                min_confidence=(
                    settings.vision.min_face_confidence
                ),
            )

            # ----------------------------------------------------------
            # ATTEMPT 2: downscale image
            # ----------------------------------------------------------

            if not results:

                height, width = bgr_image.shape[:2]

                if (
                    min(height, width) > 200
                    and settings.vision.retry_downscale < 1.0
                ):

                    scale = settings.vision.retry_downscale

                    small = cv2.resize(
                        bgr_image,
                        (
                            max(
                                1,
                                int(width * scale),
                            ),
                            max(
                                1,
                                int(height * scale),
                            ),
                        ),
                        interpolation=cv2.INTER_AREA,
                    )

                    faces = self._app.get(small)

                    results = self._to_results(
                        faces,
                        bbox_scale=1.0 / scale,
                        min_confidence=relaxed,
                    )

            # ----------------------------------------------------------
            # ATTEMPT 3: upscale image
            # ----------------------------------------------------------

            if not results:

                height, width = bgr_image.shape[:2]

                if min(height, width) > 64:

                    upscale = 320 / min(
                        height,
                        width,
                    )

                    upscale = max(
                        1.0,
                        min(upscale, 2.0),
                    )

                    if upscale > 1.0:

                        up = cv2.resize(
                            bgr_image,
                            (
                                max(
                                    1,
                                    int(width * upscale),
                                ),
                                max(
                                    1,
                                    int(height * upscale),
                                ),
                            ),
                            interpolation=cv2.INTER_LINEAR,
                        )

                        faces = self._app.get(up)

                        results = self._to_results(
                            faces,
                            bbox_scale=1.0 / upscale,
                            min_confidence=relaxed,
                        )

        results.sort(
            key=lambda result: result.det_score,
            reverse=True,
        )

        return results

    # ------------------------------------------------------------------
    # LARGEST FACE
    # ------------------------------------------------------------------

    def largest_face(
        self,
        bgr_image: np.ndarray | str | Path,
    ) -> FaceResult | None:
        """Return the face with the largest area.

        Useful for single-person enrollment.

        Args:
            bgr_image: BGR image or path.

        Returns:
            FaceResult with largest bbox area, or None if no face.
        """
        faces = self.analyze(bgr_image)

        if not faces:
            return None

        def area(face: FaceResult) -> float:
            """Compute bbox area for a face.

            Args:
                face: Face result.

            Returns:
                Area in pixels.
            """
            x1, y1, x2, y2 = face.bbox

            return (
                max(0.0, x2 - x1)
                * max(0.0, y2 - y1)
            )

        return max(
            faces,
            key=area,
        )
