"""
Análisis facial extendido: gafas, mascarilla, barba, bigote, sonrisa y ojos
abiertos.

Implementación 100 % local sobre MediaPipe FaceMesh (el modelo de landmarks —
468/478 puntos — viene empaquetado en la librería `mediapipe`, así que NO
necesita descargas ni conexión a Internet), complementado con clasificadores
geométricos y de textura sobre OpenCV.

Aviso importante: gafas/mascarilla/barba/bigote son *aproximaciones
heurísticas* (no hay un clasificador neuronal entrenado para ellos en este
proyecto). Las métricas se calculan sobre regiones definidas geométricamente
a partir de los landmarks (banda de ojos, mentón, bigote, frente) comparando
densidad de bordes y luminancia relativa. Funcionan razonablemente en tomas
frontales y nítidas (el mismo régimen que exige ya el gate de calidad), pero
no deben tratarse como un veredicto biométrico definitivo:

  - ojos_abiertos / sonrisa: se derivan de la geometría de los landmarks
    (Eye Aspect Ratio y ensanchamiento de la boca), métodos bien establecidos.
  - gafas: densidad de bordes horizontales en la banda de los ojos frente a
    la mejilla (los aros/monturas generan líneas horizontales intensas).
  - mascarilla: textura del tercio inferior muy baja y boca cerrada (una tela
    lisa difumina el mentón/boca, que dejan de aportar bordes).
  - barba / bigote: densidad de bordes (vello) en mentón / zona naso-labial
    frente a la mejilla (piel lisa) como referencia.
  - color_ojos / color_pelo: clasificadores discretos de color (HSV) sobre el
    rostro alineado — iris (índices 468/473) y banda superior de la frente.
    Muy sensibles a la iluminación y al recorte alineado; ``None`` cuando no
    hay evidencia clara. También son aproximaciones, no un veredicto.

La activación global se gobierna con `settings.vision.enable_face_attributes`
y, cuando algo falla (modelo no disponible, rostro demasiado pequeño), el
método `analyze` devuelve ``None`` en lugar de romper el reconocimiento.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

import cv2
import numpy as np

from app.core.config import settings
from app.core.logger import logger
from app.vision.face_quality import align_face

# --- Índices de landmarks de MediaPipe FaceMesh (con refine_landmarks llega a 478) ---
LEFT_EYE = [33, 160, 158, 133, 153, 144]
RIGHT_EYE = [362, 385, 387, 263, 373, 380]
MOUTH_CORNERS = [61, 291]          # comisuras exteriores de la boca
NOSE_TIP = 4                        # punta de la nariz
CHIN = 152                          # barbilla
NOSE_BRIDGE = 6                     # zona alta de la nariz (referencia frente)
EYEBROW_LEFT, EYEBROW_RIGHT = 70, 300
CHEEK_LEFT, CHEEK_RIGHT = 234, 454  # mejillas laterales

# --- Iris (modelo 478 puntos con refine_landmarks) para el color de ojos ---
LEFT_IRIS_CENTER = 468
RIGHT_IRIS_CENTER = 473

# --- Etiquetas discretas de color (ojo/pelo): fuentes de verdad para UI/filtros ---
EYE_COLOR_LABELS = ("negro", "marrón", "azul", "verde", "gris")
HAIR_COLOR_LABELS = ("negro", "castaño", "rubio", "pelirrojo", "gris", "canoso")

# --- Umbrales heurísticos (documentados; artefacto de calibración empírica) ---
EYE_OPEN_EAR = 0.200      # EAR medio bajo el cual se considera "ojos cerrados"
SMILE_WIDTH_RATIO = 0.52  # ancho de boca / distancia interpupilar que indica sonrisa
MASK_TEXTURE_RATIO = 0.55  # (textura mentón / mejilla) bajo el cual se sospecha mascarilla
HAIR_TEXTURE_RATIO = 1.35  # (textura vello / mejilla) sobre el cual se decide barba/bigote
GLASSES_TEXTURE_RATIO = 1.30  # (bordes ojo / mejilla) sobre el cual se sospecha gafas

ALIGN_SIZE = 96            # plantilla de alineación que ya produce face_quality
MESH_SIZE = 192            # tamaño de trabajo para MediaPipe (192x192 es óptimo)

ATTR_FIELDS = ("gafas", "mascarilla", "barba", "bigote", "sonrisa", "ojos_abiertos")


@dataclass
class FaceAttributes:
    """Conjunto de atributos faciales extendidos de un rostro detectado.

    Cada atributo es un booleano decidido por umbral, pero se conservan las
    probabilidades crudas (0..1) en ``conf`` para un diagnóstico más fino y
    para futuros ajustes de umbral sin re-procesar imágenes.

    ``edad`` y ``genero`` provienen del modelo de atributos de InsightFace
    (buffalo_l) en el momento de la captura; se guardan junto al análisis de
    MediaPipe para tener la ficha facial completa en un solo JSON.

    ``color_ojos`` y ``color_pelo`` son clasificaciones discretas (heurísticas
    de color sobre el rostro alineado), aproximadas y dependientes de la
    iluminación; ``None`` indica que no se pudo decidir con confianza.
    """
    gafas: bool = False
    mascarilla: bool = False
    barba: bool = False
    bigote: bool = False
    sonrisa: bool = False
    ojos_abiertos: bool = False
    conf: dict[str, float] = field(default_factory=dict)
    edad: int | None = None
    genero: str | None = None
    color_ojos: str | None = None
    color_pelo: str | None = None

    def as_booleans(self) -> dict[str, bool]:
        return {name: bool(getattr(self, name)) for name in ATTR_FIELDS}

    def to_dict(self) -> dict:
        return {
            **self.as_booleans(),
            "conf": dict(self.conf),
            "edad": self.edad,
            "genero": self.genero,
            "color_ojos": self.color_ojos,
            "color_pelo": self.color_pelo,
        }

    @classmethod
    def from_dict(cls, data) -> "FaceAttributes | None":
        if not data or not isinstance(data, dict):
            return None
        edad = data.get("edad")
        edad = int(edad) if isinstance(edad, (int, float)) and not isinstance(edad, bool) else None
        genero = data.get("genero")
        genero = str(genero).strip() if isinstance(genero, str) else None
        return cls(
            gafas=bool(data.get("gafas", False)),
            mascarilla=bool(data.get("mascarilla", False)),
            barba=bool(data.get("barba", False)),
            bigote=bool(data.get("bigote", False)),
            sonrisa=bool(data.get("sonrisa", False)),
            ojos_abiertos=bool(data.get("ojos_abiertos", False)),
            conf=dict(data.get("conf") or {}),
            edad=edad,
            genero=genero,
            color_ojos=_clean_color(data.get("color_ojos"), EYE_COLOR_LABELS),
            color_pelo=_clean_color(data.get("color_pelo"), HAIR_COLOR_LABELS),
        )


# --------------------------------------------------------------------------- #
# Geometría (Eye Aspect Ratio, apertura de boca)
# --------------------------------------------------------------------------- #
def eye_aspect_ratio(landmarks: np.ndarray, indices: list[int]) -> float:
    """Eye Aspect Ratio de un ojo (EAR). ~0.28 abierto, ~0.10 cerrado."""
    p = [np.asarray(landmarks[i], dtype=float) for i in indices]
    if any(p[i].size < 2 for i in range(6)):
        return 0.0
    horizontal = float(np.linalg.norm(p[0] - p[3]))
    vertical = float(np.linalg.norm(p[1] - p[5]) + np.linalg.norm(p[2] - p[4]))
    if horizontal <= 1e-6:
        return 0.0
    return float(vertical / (2.0 * horizontal))


def _pair_distance(landmarks: np.ndarray, a: int, b: int) -> float:
    return float(np.linalg.norm(np.asarray(landmarks[a], dtype=float)
                                - np.asarray(landmarks[b], dtype=float)))


def _point(landmarks: np.ndarray, i: int) -> np.ndarray:
    return np.asarray(landmarks[i], dtype=float)


def _midpoint(landmarks: np.ndarray, a: int, b: int) -> np.ndarray:
    return (_point(landmarks, a) + _point(landmarks, b)) / 2.0


# --------------------------------------------------------------------------- #
# Métricas puras (evaluables sin MediaPipe, usadas también en tests)
# --------------------------------------------------------------------------- #
def metric_eyes_open(landmarks: np.ndarray) -> float:
    """0..1: promedio del EAR de ambos ojos."""
    return float(np.clip(
        (eye_aspect_ratio(landmarks, LEFT_EYE)
         + eye_aspect_ratio(landmarks, RIGHT_EYE)) / 2.0, 0.0, 1.0))


def metric_smile(landmarks: np.ndarray) -> float:
    """0..1: ensanchamiento de la boca vs distance interpupilar."""
    interocular = float(np.linalg.norm(
        _midpoint(landmarks, 33, 133) - _midpoint(landmarks, 362, 263)))
    if interocular <= 1e-6:
        return 0.0
    ratio = _pair_distance(landmarks, MOUTH_CORNERS[0], MOUTH_CORNERS[1]) / interocular
    return float(np.clip(ratio, 0.0, 1.0))


def _gradient_density(gray: np.ndarray, x0: int, y0: int, x1: int, y1: int,
                      thresh: int = 40) -> float:
    """Fracción (0..1) de píxeles con gradiente fuerte en una ROI.

    Umbral sobre la magnitud sobresaturada de Sobel. Valor alto = región
    texturizada (vello, monturas); valor bajo = superficie lisa (piel, tela).
    """
    h, w = gray.shape[:2]
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(w, int(round(x1))), min(h, int(round(y1)))
    if x1 - x0 < 3 or y1 - y0 < 3:
        return 0.0
    roi = gray[y0:y1, x0:x1]
    gx = cv2.Sobel(roi, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(roi, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    return float(np.count_nonzero(mag > thresh) / mag.size)


def _roi_box(landmarks: np.ndarray, cx: float, cy: float,
             half_w: float, y0: float, y1: float) -> tuple[int, int, int, int]:
    """Caja de ROI centrada en (cx, cy) con media anchura y bandas verticales."""
    return (int(cx - half_w), int(cy + y0), int(cx + half_w), int(cy + y1))


# --------------------------------------------------------------------------- #
# Clasificadores de región (sobre el rostro alineado de MESH_SIZE px)
# --------------------------------------------------------------------------- #
def _geometry(landmarks: np.ndarray, gray: np.ndarray) -> dict:
    """Calcula puntos clave y métricas regionales de una sola vez."""
    eye_left_c = _midpoint(landmarks, 33, 133)
    eye_right_c = _midpoint(landmarks, 362, 263)
    interocular = float(np.linalg.norm(eye_right_c - eye_left_c)) + 1e-6
    eye_mid_y = float((eye_left_c[1] + eye_right_c[1]) / 2.0)
    cx = float((eye_left_c[0] + eye_right_c[0]) / 2.0)
    nose = _point(landmarks, NOSE_TIP)
    mouth_c = _midpoint(landmarks, MOUTH_CORNERS[0], MOUTH_CORNERS[1])
    mouth_close = min(
        eye_aspect_ratio(landmarks, [61, 0, 13, 291, 14, 17]) * 4.0, 1.0)

    # Regiones (coordenadas en píxeles del rostro alineado).
    eye_band = _roi_box(landmarks, cx, eye_mid_y,
                        interocular * 0.85, -0.45 * interocular, 0.22 * interocular)
    cheek_band = _roi_box(landmarks, cx, (eye_mid_y + mouth_c[1]) / 2,
                          interocular * 0.85, 0.30 * interocular, -0.02 * interocular)
    forehead_band = _roi_box(landmarks, cx, eye_mid_y,
                             interocular * 0.9, -1.9 * interocular, -0.95 * interocular)
    mustache_band = _roi_box(landmarks, mouth_c[0], (nose[1] + mouth_c[1]) / 2,
                             interocular * 0.7, -0.18 * interocular, 0.18 * interocular)
    chin_band = _roi_box(landmarks, mouth_c[0], mouth_c[1],
                         interocular * 0.75, 0.5 * interocular, 1.55 * interocular)

    return {
        "interocular": interocular,
        "eye_mid_y": eye_mid_y,
        "cx": cx,
        "nose": nose,
        "mouth_c": mouth_c,
        "mouth_closed": 1.0 - mouth_close,
        "eye_grad": _gradient_density(gray, *eye_band),
        "cheek_grad": _gradient_density(gray, *cheek_band),
        "forehead_grad": _gradient_density(gray, *forehead_band),
        "mustache_grad": _gradient_density(gray, *mustache_band),
        "chin_grad": _gradient_density(gray, *chin_band),
    }


def default_thresholds() -> dict[str, float]:
    """Umbrales de decisión por atributo (0..1 sobre la confianza cruda).

    Fuente única de verdad para la calibración: la GUI la ajusta en tiempo
    real y el clasificador solo aplica lo que aquí llegue.
    """
    return {
        "gafas": 0.5,
        "mascarilla": 0.5,
        "barba": 0.5,
        "bigote": 0.5,
        "sonrisa": 0.5,
        "ojos_abiertos": 0.5,
    }


def classify_from_conf(conf: dict | None,
                       thresholds: dict[str, float] | None = None) -> FaceAttributes:
    """Clasifica los seis atributos a partir de las confianzas crudas (0..1).

    ``thresholds`` permite sobreescribir umbrales por atributo sin recalcular
    el modelo; si no se pasa, se usan ``default_thresholds()``. Es la función
    que también re-clasifica las confianzas ya almacenadas para calibrar.
    """
    conf = dict(conf or {})
    thresholds = {**default_thresholds(), **(thresholds or {})}

    def decided(field: str) -> bool:
        return float(conf.get(field, 0.0)) >= float(thresholds.get(field, 0.5))

    return FaceAttributes(
        gafas=decided("gafas"),
        mascarilla=decided("mascarilla"),
        barba=decided("barba"),
        bigote=decided("bigote"),
        sonrisa=decided("sonrisa"),
        ojos_abiertos=decided("ojos_abiertos"),
        conf=conf,
    )


# --------------------------------------------------------------------------- #
# Color de ojos / pelo (heurísticas HSV sobre el rostro alineado)
# --------------------------------------------------------------------------- #
def _clean_color(value, labels: tuple[str, ...]) -> str | None:
    if isinstance(value, str) and value in labels:
        return value
    return None


def classify_eye_color_hsv(h: float, s: float, v: float) -> str:
    """Clasifica el color del iris (HSV 0-180 / 0-255 / 0-255).

    Reglas empíricas: muy oscuro -> negro; poca saturación -> gris;
    luego por matiz (marrón, verde, azul). Aproximación sensible a la
    iluminación: se documenta como tal, no como veredicto biométrico.
    """
    if v < 35:
        return "negro"
    if s < 25:
        return "gris"
    if 9 <= h < 24:
        return "marrón"
    if 37 <= h < 80:
        return "verde"
    if 90 <= h < 140:
        return "azul"
    return "marrón"


def classify_hair_color_hsv(h: float, s: float, v: float) -> str:
    """Clasifica el color del cabello (HSV 0-180 / 0-255 / 0-255)."""
    if v < 45:
        return "negro"
    if s < 25:
        return "canoso" if v >= 165 else "gris"
    if v >= 175 and h < 40:
        return "rubio"
    if (h < 14 or h >= 160) and s >= 45:
        return "pelirrojo"
    return "castaño"


def _roi_hsv_median(image_bgr: np.ndarray,
                    x0: int, y0: int, x1: int, y1: int,
                    center: tuple[int, int] | None = None,
                    radius: int = 0) -> tuple[float, float, float] | None:
    """Mediana HSV de una ROI (o de un cuadrado centrado en ``center``)."""
    if center is not None:
        y, x = center
        x0, y0 = x - radius, y - radius
        x1, y1 = x + radius, y + radius
    h, w = image_bgr.shape[:2]
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(w, int(x1)), min(h, int(y1))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    roi = image_bgr[y0:y1, x0:x1]
    if roi.size == 0:
        return None
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    return (float(np.median(hsv[..., 0])),
            float(np.median(hsv[..., 1])),
            float(np.median(hsv[..., 2])))


def metric_eye_color(image_bgr: np.ndarray, landmarks: np.ndarray) -> str | None:
    """Color discreto de ojos muestreando el iris (índices 468/473)."""
    if landmarks.shape[0] <= RIGHT_IRIS_CENTER:
        return None
    eye_left = _point(landmarks, 33)
    eye_right = _point(landmarks, 362)
    interocular = float(np.linalg.norm(eye_right - eye_left)) + 1e-6
    radius = max(2, int(interocular * 0.07))
    vals: list[tuple[float, float, float]] = []
    for idx in (LEFT_IRIS_CENTER, RIGHT_IRIS_CENTER):
        center = (int(landmarks[idx][1]), int(landmarks[idx][0]))
        med = _roi_hsv_median(image_bgr, 0, 0, 0, 0, center=center, radius=radius)
        if med is not None:
            vals.append(med)
    if not vals:
        eye_mid = (_point(landmarks, 33) + _point(landmarks, 362)) / 2.0
        for offset in (-1.0, 1.0):
            center = (int(eye_mid[1]), int(eye_mid[0] + offset * interocular * 0.25))
            med = _roi_hsv_median(image_bgr, 0, 0, 0, 0, center=center, radius=radius)
            if med is not None:
                vals.append(med)
    if not vals:
        return None
    h = float(np.median([v[0] for v in vals]))
    s = float(np.median([v[1] for v in vals]))
    v = float(np.median([v[2] for v in vals]))
    return classify_eye_color_hsv(h, s, v)


def metric_hair_color(image_bgr: np.ndarray, landmarks: np.ndarray) -> str | None:
    """Color discreto del cabello muestreando la banda superior de la frente.

    Compara la banda "pelo" con una referencia de piel (frente); si resulta
    indistinguishable de la piel, el cabello no queda dentro del encuadre
    alineado y se devuelve ``None``.
    """
    eye_left = _point(landmarks, 33)
    eye_right = _point(landmarks, 362)
    interocular = float(np.linalg.norm(eye_right - eye_left)) + 1e-6
    cx = float((eye_left[0] + eye_right[0]) / 2.0)
    eye_mid_y = float((eye_left[1] + eye_right[1]) / 2.0)

    hair_med = _roi_hsv_median(
        image_bgr,
        int(cx - interocular * 0.55),
        int(eye_mid_y - 2.3 * interocular),
        int(cx + interocular * 0.55),
        int(eye_mid_y - 1.5 * interocular))
    skin_med = _roi_hsv_median(
        image_bgr,
        int(cx - interocular * 0.55),
        int(eye_mid_y - 1.45 * interocular),
        int(cx + interocular * 0.55),
        int(eye_mid_y - 0.95 * interocular))
    if hair_med is None or skin_med is None:
        return None
    # Si la banda superior es prácticamente la misma piel, no hay pelo visible.
    if (abs(hair_med[0] - skin_med[0]) < 18
            and abs(hair_med[2] - skin_med[2]) < 18):
        return None
    return classify_hair_color_hsv(*hair_med)


def classify_aligned(landmarks: np.ndarray, image_bgr: np.ndarray) -> FaceAttributes:
    """Clasifica los seis atributos (más color de ojos/pelo) desde el rostro alineado.

    ``landmarks``: (N, 2) en píxeles de la imagen ``image_bgr`` (N=478 con iris,
    MediaPipe FaceMesh). Función pura: también usada en las pruebas con datos
    sintéticos.
    """
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    ears = metric_eyes_open(landmarks)
    smile = metric_smile(landmarks)
    g = _geometry(landmarks, gray)

    eyes_factor = ears / EYE_OPEN_EAR       # >1 = abierto con holgura
    smile_factor = smile / SMILE_WIDTH_RATIO
    conf = {
        "ojos_abiertos": float(np.clip(eyes_factor, 0.0, 1.0)),
        "sonrisa": float(np.clip(smile_factor, 0.0, 1.0)),
        "gafas": float(np.clip(g["eye_grad"] / (g["cheek_grad"] + 1e-6)
                                / GLASSES_TEXTURE_RATIO, 0.0, 1.0)),
        "mascarilla": float(np.clip(
            (g["cheek_grad"] + 1e-6) / (g["chin_grad"] + 1e-6)
            * 0.25 * (1.0 + g["mouth_closed"]), 0.0, 1.0)),
        "barba": float(np.clip(g["chin_grad"] / (g["cheek_grad"] + 1e-6)
                                / HAIR_TEXTURE_RATIO, 0.0, 1.0)),
        "bigote": float(np.clip(g["mustache_grad"] / (g["cheek_grad"] + 1e-6)
                                 / HAIR_TEXTURE_RATIO, 0.0, 1.0)),
    }
    attrs = classify_from_conf(conf)
    attrs.color_ojos = metric_eye_color(image_bgr, landmarks)
    attrs.color_pelo = metric_hair_color(image_bgr, landmarks)
    return attrs


# --------------------------------------------------------------------------- #
# Analizador con MediaPipe FaceMesh (lazy, offline)
# --------------------------------------------------------------------------- #
class FaceAttributeAnalyzer:
    """Envoltura perezosa sobre `mediapipe.solutions.face_mesh` (modelo incluido).

    Singleton por proceso, igual que FaceEngine: la carga del modelo de
    landmarks ocurre solo en el primer análisis, nunca al importar.
    """

    _instance: "FaceAttributeAnalyzer | None" = None

    def __init__(self):
        self._mesh = None
        self._load_failed = False
        self._lock = threading.RLock()

    @classmethod
    def instance(cls) -> "FaceAttributeAnalyzer":
        if cls._instance is None:
            cls._instance = FaceAttributeAnalyzer()
        return cls._instance

    @property
    def is_loaded(self) -> bool:
        return self._mesh is not None

    def warmup(self) -> None:
        self._ensure_loaded()

    def _ensure_loaded(self) -> None:
        if self._mesh is not None or self._load_failed:
            return
        with self._lock:
            if self._mesh is not None or self._load_failed:
                return
            try:
                from mediapipe.python.solutions import face_mesh as mp_face_mesh

                logger.info("Cargando modelo de landmarks faciales (MediaPipe)…")
                self._mesh = mp_face_mesh.FaceMesh(
                    static_image_mode=True,
                    max_num_faces=1,
                    refine_landmarks=True,
                    min_detection_confidence=0.3,
                )
                logger.info("Modelo de landmarks faciales cargado.")
            except Exception as exc:  # noqa: BLE001
                logger.warning("No se pudo inicializar MediaPipe FaceMesh: {}", exc)
                self._mesh = None
                self._load_failed = True

    def analyze(self, bgr_image: np.ndarray, bbox, landmarks5) -> FaceAttributes | None:
        """Analiza un rostro ya detectado por InsightFace.

        Normaliza el rostro con la plantilla de `face_quality.align_face`
        (misma geometría en todas las tomas), corre MediaPipe sobre ella y
        clasifica. Devuelve ``None`` si el modelo no está disponible, el refinado
        falla o el atributo extendido está desactivado.
        """
        if not settings.vision.enable_face_attributes:
            return None
        self._ensure_loaded()
        if self._mesh is None:
            return None

        try:
            aligned = align_face(bgr_image, np.asarray(landmarks5, dtype=np.float32))
            if aligned is None or aligned.size == 0:
                return None
            work = cv2.resize(aligned, (MESH_SIZE, MESH_SIZE),
                              interpolation=cv2.INTER_LINEAR)
            rgb = cv2.cvtColor(work, cv2.COLOR_BGR2RGB)
            with self._lock:
                result = self._mesh.process(rgb)
            if not result.multi_face_landmarks:
                return None
            raw = result.multi_face_landmarks[0]
            points = np.array([
                [raw.landmark[i].x * MESH_SIZE, raw.landmark[i].y * MESH_SIZE]
                for i in range(len(raw.landmark))
            ], dtype=np.float32)
            return classify_aligned(points, work)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Análisis facial extendido omitido para este rostro: {}", exc)
            return None