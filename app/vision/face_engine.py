"""
Motor de visión facial: detección + landmarks + embedding biométrico.

Implementación:
    InsightFace + buffalo_l + ONNX Runtime.

En desarrollo:
    Los modelos se buscan en ~/.insightface/models/buffalo_l.

En la aplicación empaquetada con PyInstaller:
    Los modelos se buscan dentro de:
        <bundle>/_internal/models/buffalo_l

Esto permite distribuir FaceScan completamente offline, sin depender
de que InsightFace descargue buffalo_l en el equipo del usuario.
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
    bbox: tuple[float, float, float, float]
    det_score: float
    landmarks: np.ndarray
    embedding: np.ndarray
    age: int | None = None
    gender: str | None = None


class FaceEngine:
    """
    Envoltura sobre insightface.app.FaceAnalysis.

    Características:

    - Singleton.
    - Carga lazy.
    - Thread-safe.
    - Detecta automáticamente si se está ejecutando desde PyInstaller.
    - Usa los modelos incluidos en el bundle cuando está empaquetado.
    - Usa ~/.insightface/models cuando se ejecuta desde Python.
    """

    _instance: "FaceEngine | None" = None

    # Nombres de los archivos que obligatoriamente debe contener buffalo_l.
    REQUIRED_MODEL_FILES = (
        "1k3d68.onnx",
        "2d106det.onnx",
        "det_10g.onnx",
        "genderage.onnx",
        "w600k_r50.onnx",
    )

    def __init__(self):
        self._app = None
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # SINGLETON
    # ------------------------------------------------------------------

    @classmethod
    def instance(cls) -> "FaceEngine":
        if cls._instance is None:
            cls._instance = FaceEngine()
        return cls._instance

    # ------------------------------------------------------------------
    # ESTADO
    # ------------------------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        return self._app is not None

    # ------------------------------------------------------------------
    # LECTURA SEGURA DE IMÁGENES (NUEVO)
    # ------------------------------------------------------------------

    @staticmethod
    def load_image_bgr(image_input: str | Path | np.ndarray | None) -> np.ndarray:
        """
        Carga o valida una imagen BGR de forma segura en Windows,
        soportando rutas con espacios, tildes y caracteres Unicode.
        """
        if image_input is None:
            raise ValueError("No se proporcionó ninguna imagen o la ruta es nula (None).")

        if isinstance(image_input, np.ndarray):
            if image_input.size == 0 or len(image_input.shape) < 2:
                raise ValueError("La imagen en memoria proporcionada está vacía o es inválida.")
            return image_input

        path_obj = Path(image_input)
        if not path_obj.exists():
            raise FileNotFoundError(f"No se encontró el archivo de imagen: {image_input}")

        # Leer archivo como bytes independientes del sistema de archivos de Windows
        img_bytes = np.fromfile(str(path_obj), dtype=np.uint8)
        img = cv2.imdecode(img_bytes, cv2.IMREAD_COLOR)

        if img is None:
            raise ValueError(
                f"No se pudo decodificar la imagen (formato no soportado o archivo corrupto): {image_input}"
            )

        return img

    # ------------------------------------------------------------------
    # PYINSTALLER
    # ------------------------------------------------------------------

    @staticmethod
    def _is_frozen() -> bool:
        """
        Devuelve True cuando la aplicación está ejecutándose desde
        un bundle generado por PyInstaller.
        """
        return bool(
            getattr(sys, "frozen", False)
            and hasattr(sys, "_MEIPASS")
        )

    @classmethod
    def _bundle_root(cls) -> Path | None:
        """
        Obtiene la raíz interna del bundle PyInstaller.

        En PyInstaller 6.x para onedir normalmente será:

            FaceScan/
                FaceScan.exe
                _internal/
                    ...

        y sys._MEIPASS apunta a:

            FaceScan/_internal
        """
        if not cls._is_frozen():
            return None

        return Path(sys._MEIPASS).resolve()

    @classmethod
    def _model_root(cls) -> Path:
        """
        Devuelve el directorio raíz que InsightFace debe utilizar.

        Desarrollo:
            ~/.insightface

        PyInstaller:
            <bundle>/_internal
        """

        bundle_root = cls._bundle_root()

        if bundle_root is not None:
            root = bundle_root

            logger.info(
                "FaceScan ejecutándose como aplicación empaquetada."
            )
            logger.info(
                "Directorio interno de PyInstaller: {}",
                root,
            )

            return root

        # Ejecución normal desde Python.
        root = Path.home() / ".insightface"

        logger.info(
            "FaceScan ejecutándose desde Python."
        )
        logger.info(
            "Directorio raíz de InsightFace: {}",
            root,
        )

        return root

    @classmethod
    def _model_dir(cls) -> Path:
        """
        Directorio exacto donde InsightFace debe encontrar buffalo_l.
        """

        return cls._model_root() / "models" / settings.vision.detector_model

    @classmethod
    def _validate_models(cls, model_dir: Path) -> None:
        """
        Verifica que todos los ONNX necesarios existan.

        Esto evita que InsightFace intente descargar modelos
        silenciosamente cuando la aplicación está empaquetada.
        """

        if not model_dir.exists():
            raise ModelLoadError(
                f"No existe el directorio de modelos de InsightFace:\n"
                f"{model_dir}"
            )

        missing = [
            filename
            for filename in cls.REQUIRED_MODEL_FILES
            if not (model_dir / filename).is_file()
        ]

        if missing:
            raise ModelLoadError(
                "Faltan modelos de InsightFace.\n"
                f"Directorio: {model_dir}\n"
                f"Faltantes: {', '.join(missing)}"
            )

        found = sorted(
            path.name
            for path in model_dir.glob("*.onnx")
        )

        logger.info(
            "Modelos InsightFace encontrados en {}: {}",
            model_dir,
            ", ".join(found),
        )

    # ------------------------------------------------------------------
    # ONNX RUNTIME
    # ------------------------------------------------------------------

    @staticmethod
    def _available_providers() -> list[str]:
        """
        Selecciona los providers disponibles de ONNX Runtime.

        Preferencia:
            1. CUDA
            2. CPU

        Si CUDA no está instalado, se utiliza CPU automáticamente.
        """

        try:
            import onnxruntime

            available = set(
                onnxruntime.get_available_providers()
            )

            logger.info(
                "Proveedores ONNX Runtime disponibles: {}",
                ", ".join(sorted(available)),
            )

        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "No se pudo consultar ONNX Runtime: {}. "
                "Se utilizará CPU.",
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
            "Proveedores seleccionados para InsightFace: {}",
            ", ".join(providers),
        )

        return providers

    # ------------------------------------------------------------------
    # CARGA DEL MODELO
    # ------------------------------------------------------------------

    def warmup(self) -> None:
        """
        Carga los modelos de forma síncrona.

        Útil para realizar una precarga desde un hilo de inicialización.
        """
        self._ensure_loaded()

    def _ensure_loaded(self) -> None:
        """
        Carga FaceAnalysis una sola vez.

        Utiliza doble comprobación para evitar que dos hilos
        carguen simultáneamente los modelos.
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
                    "Cargando modelos de reconocimiento facial ({})...",
                    model_name,
                )

                logger.info(
                    "Directorio raíz de InsightFace: {}",
                    self._model_root(),
                )

                logger.info(
                    "Directorio del modelo: {}",
                    model_dir,
                )

                self._validate_models(model_dir)

                providers = self._available_providers()
                ctx_id = settings.vision.ctx_id

                logger.info(
                    "Inicializando FaceAnalysis con root={}",
                    self._model_root(),
                )

                # Intentar cargar con los proveedores preferidos (ej. CUDA / CPU)
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
                    # Fallback a CPU en caso de que falle la inicialización por GPU/CUDA
                    logger.warning(
                        "Fallo al inicializar InsightFace con providers={}/ctx_id={}: {}. "
                        "Reintentando con CPUExecutionProvider...",
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
                    "Modelos de reconocimiento facial cargados correctamente."
                )

            except ModelLoadError:
                raise

            except Exception as exc:  # noqa: BLE001

                logger.exception(
                    "Error cargando InsightFace."
                )

                raise ModelLoadError(
                    "No se pudieron cargar los modelos de InsightFace.\n\n"
                    f"Modelo: {settings.vision.detector_model}\n"
                    f"Directorio: {self._model_dir()}\n\n"
                    f"Detalle técnico: {exc}\n\n"
                    "Verifica que el paquete Microsoft Visual C++ Redistributable (x64) esté instalado en el sistema."
                ) from exc

    # ------------------------------------------------------------------
    # EDAD
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_age(raw_age) -> int | None:
        """
        Convierte la edad estimada por InsightFace a un rango
        más conservador.

        Nota:
            La edad estimada por el modelo no debe interpretarse
            como una medición exacta.
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
    # CONVERSIÓN DE RESULTADOS
    # ------------------------------------------------------------------

    def _to_results(
        self,
        faces,
        bbox_scale: float = 1.0,
        min_confidence: float | None = None,
    ) -> list[FaceResult]:

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
    # ANÁLISIS
    # ------------------------------------------------------------------

    def analyze(
        self,
        bgr_image: np.ndarray | str | Path,
    ) -> list[FaceResult]:
        """
        Detecta todos los rostros de una imagen BGR (o desde una ruta str/Path).

        Devuelve FaceResult ordenados por confianza descendente.

        Estrategia:

        1. Carga / valida de forma segura la imagen.
        2. Intento normal.
        3. Si no encuentra rostros, reduce la imagen.
        4. Si tampoco encuentra, amplía la imagen.
        """

        # Cargar / validar imagen de forma segura ante rutas con acentos/espacios
        bgr_image = self.load_image_bgr(bgr_image)

        self._ensure_loaded()

        with self._lock:

            relaxed = max(
                0.30,
                settings.vision.min_face_confidence - 0.05,
            )

            # ----------------------------------------------------------
            # INTENTO 1: imagen original
            # ----------------------------------------------------------

            faces = self._app.get(bgr_image)

            results = self._to_results(
                faces,
                min_confidence=(
                    settings.vision.min_face_confidence
                ),
            )

            # ----------------------------------------------------------
            # INTENTO 2: reducir imagen
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
            # INTENTO 3: ampliar imagen
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
    # ROSTRO PRINCIPAL
    # ------------------------------------------------------------------

    def largest_face(
        self,
        bgr_image: np.ndarray | str | Path,
    ) -> FaceResult | None:
        """
        Devuelve el rostro de mayor área.

        Útil para el registro de una sola persona.
        """

        faces = self.analyze(bgr_image)

        if not faces:
            return None

        def area(face: FaceResult) -> float:

            x1, y1, x2, y2 = face.bbox

            return (
                max(0.0, x2 - x1)
                * max(0.0, y2 - y1)
            )

        return max(
            faces,
            key=area,
        )