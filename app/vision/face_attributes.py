"""Extended facial analysis: glasses, mask, beard, moustache, smile, and open eyes.

100% local implementation on MediaPipe FaceMesh (the 468/478-point landmark model
is bundled in the ``mediapipe`` library, so no downloads or internet access are
required), complemented by geometric and texture classifiers on OpenCV.

Important note: glasses/mask/beard/moustache are heuristic approximations (no
trained neural classifier for them exists in this project). Metrics are computed
over geometrically defined regions derived from landmarks (eye band, chin,
moustache, forehead) by comparing edge density and relative luminance. They work
reasonably on frontal, sharp shots (the same regime already required by the
quality gate) but should not be treated as a definitive biometric verdict:

  - eyes_open / smile: derived from landmark geometry (Eye Aspect Ratio and mouth
    widening), well-established methods.
  - glasses: horizontal edge density in the eye band vs. the cheek (frames create
    intense horizontal lines).
  - mask: very low texture in the lower third and closed mouth (a smooth fabric
    blurs the chin/mouth, removing edges).
  - beard / moustache: edge density (hair) on chin / nasolabial area vs. the
    cheek (smooth skin) as reference.
  - eye_color / hair_color: discrete color classifiers (HSV) over the aligned
    face — iris (indices 468/473) and upper forehead band. Highly sensitive to
    illumination and aligned crop; ``None`` when no clear evidence. Also
    approximations, not a verdict.

Global activation is governed by ``settings.vision.enable_face_attributes`` and,
when anything fails (model unavailable, face too small), ``analyze`` returns
``None`` instead of breaking recognition.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

import cv2
import numpy as np

from app.core.config import settings
from app.core.logger import logger
from app.vision.face_quality import align_face

# --- MediaPipe FaceMesh landmark indices (478 with refine_landmarks) ---
LEFT_EYE = [33, 160, 158, 133, 153, 144]
RIGHT_EYE = [362, 385, 387, 263, 373, 380]
MOUTH_CORNERS = [61, 291]  # Outer mouth corners.
NOSE_TIP = 4  # Nose tip.
CHIN = 152  # Chin.
NOSE_BRIDGE = 6  # Upper nose bridge (forehead reference).
EYEBROW_LEFT, EYEBROW_RIGHT = 70, 300
CHEEK_LEFT, CHEEK_RIGHT = 234, 454  # Lateral cheeks.

# --- Iris (478-point model with refine_landmarks) for eye color ---
LEFT_IRIS_CENTER = 468
RIGHT_IRIS_CENTER = 473

# --- Discrete color labels (eye/hair): single source of truth for UI/filters ---
EYE_COLOR_LABELS = ("negro", "marrón", "azul", "verde", "gris")
HAIR_COLOR_LABELS = ("negro", "castaño", "rubio", "pelirrojo", "gris", "canoso")

# --- Heuristic thresholds (documented; empirically calibrated) ---
EYE_OPEN_EAR = 0.200  # Average EAR below which eyes are considered closed.
SMILE_WIDTH_RATIO = 0.52  # Mouth width / interocular distance indicating smile.
MASK_TEXTURE_RATIO = 0.55  # (chin texture / cheek) below which mask is suspected.
HAIR_TEXTURE_RATIO = 1.35  # (hair texture / cheek) above which beard/moustache decided.
GLASSES_TEXTURE_RATIO = 1.30  # (eye edges / cheek) above which glasses suspected.

ALIGN_SIZE = 96  # Alignment template already produced by face_quality.
MESH_SIZE = 192  # Working size for MediaPipe (192x192 is optimal).

ATTR_FIELDS = ("gafas", "mascarilla", "barba", "bigote", "sonrisa", "ojos_abiertos")


@dataclass
class FaceAttributes:
    """Extended facial attributes for a detected face.

    Each attribute is a thresholded boolean, but raw probabilities (0..1) are
    kept in ``conf`` for finer diagnostics and future threshold tuning without
    reprocessing images.

    ``edad`` and ``genero`` come from the InsightFace attribute model (buffalo_l)
    at capture time; they are stored alongside the MediaPipe analysis to keep the
    complete facial record in a single JSON.

    ``color_ojos`` and ``color_pelo`` are discrete color classifications (color
    heuristics over the aligned face), approximate and illumination-dependent;
    ``None`` means no confident decision could be made.
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
        """Return attributes as a boolean dictionary.

        Returns:
            Dict mapping field names to booleans.
        """
        return {name: bool(getattr(self, name)) for name in ATTR_FIELDS}

    def to_dict(self) -> dict:
        """Serialize to a dictionary for JSON storage.

        Returns:
            Dictionary with booleans, conf, age, gender, and colors.
        """
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
        """Deserialize from a dictionary.

        Args:
            data: Dictionary with attribute data.

        Returns:
            FaceAttributes instance or None if data is invalid.
        """
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
# Geometry (Eye Aspect Ratio, mouth opening)
# --------------------------------------------------------------------------- #
def eye_aspect_ratio(landmarks: np.ndarray, indices: list[int]) -> float:
    """Compute Eye Aspect Ratio (EAR) for one eye. ~0.28 open, ~0.10 closed.

    Args:
        landmarks: Full landmark array.
        indices: Six indices defining the eye.

    Returns:
        EAR value.
    """
    p = [np.asarray(landmarks[i], dtype=float) for i in indices]
    if any(p[i].size < 2 for i in range(6)):
        return 0.0
    horizontal = float(np.linalg.norm(p[0] - p[3]))
    vertical = float(np.linalg.norm(p[1] - p[5]) + np.linalg.norm(p[2] - p[4]))
    if horizontal <= 1e-6:
        return 0.0
    return float(vertical / (2.0 * horizontal))


def _pair_distance(landmarks: np.ndarray, a: int, b: int) -> float:
    """Return Euclidean distance between two landmarks.

    Args:
        landmarks: Landmark array.
        a: First index.
        b: Second index.

    Returns:
        Distance.
    """
    return float(np.linalg.norm(np.asarray(landmarks[a], dtype=float)
                                - np.asarray(landmarks[b], dtype=float)))


def _point(landmarks: np.ndarray, i: int) -> np.ndarray:
    """Return a landmark point as an array.

    Args:
        landmarks: Landmark array.
        i: Index.

    Returns:
        Point coordinates.
    """
    return np.asarray(landmarks[i], dtype=float)


def _midpoint(landmarks: np.ndarray, a: int, b: int) -> np.ndarray:
    """Return the midpoint between two landmarks.

    Args:
        landmarks: Landmark array.
        a: First index.
        b: Second index.

    Returns:
        Midpoint coordinates.
    """
    return (_point(landmarks, a) + _point(landmarks, b)) / 2.0


# --------------------------------------------------------------------------- #
# Pure metrics (testable without MediaPipe)
# --------------------------------------------------------------------------- #
def metric_eyes_open(landmarks: np.ndarray) -> float:
    """Compute eyes-open metric (0..1) as average EAR of both eyes.

    Args:
        landmarks: Landmark array.

    Returns:
        Average EAR clipped to [0, 1].
    """
    return float(np.clip(
        (eye_aspect_ratio(landmarks, LEFT_EYE)
         + eye_aspect_ratio(landmarks, RIGHT_EYE)) / 2.0, 0.0, 1.0))


def metric_smile(landmarks: np.ndarray) -> float:
    """Compute smile metric (0..1) as mouth widening vs interocular distance.

    Args:
        landmarks: Landmark array.

    Returns:
        Mouth width ratio clipped to [0, 1].
    """
    interocular = float(np.linalg.norm(
        _midpoint(landmarks, 33, 133) - _midpoint(landmarks, 362, 263)))
    if interocular <= 1e-6:
        return 0.0
    ratio = _pair_distance(landmarks, MOUTH_CORNERS[0], MOUTH_CORNERS[1]) / interocular
    return float(np.clip(ratio, 0.0, 1.0))


def _gradient_density(gray: np.ndarray, x0: int, y0: int, x1: int, y1: int,
                      thresh: int = 40) -> float:
    """Compute fraction (0..1) of pixels with strong gradient in an ROI.

    Threshold is applied to Sobel magnitude. High value means textured region
    (hair, frames); low value means smooth surface (skin, fabric).

    Args:
        gray: Grayscale image.
        x0: Left coordinate.
        y0: Top coordinate.
        x1: Right coordinate.
        y1: Bottom coordinate.
        thresh: Sobel magnitude threshold.

    Returns:
        Gradient density in [0, 1].
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
    """Build an ROI box centered at (cx, cy) with half-width and vertical bands.

    Args:
        landmarks: Unused, kept for signature compatibility.
        cx: Center x.
        cy: Center y.
        half_w: Half width.
        y0: Top offset.
        y1: Bottom offset.

    Returns:
        ROI box as (x0, y0, x1, y1).
    """
    return (int(cx - half_w), int(cy + y0), int(cx + half_w), int(cy + y1))


# --------------------------------------------------------------------------- #
# Region classifiers (on MESH_SIZE px aligned face)
# --------------------------------------------------------------------------- #
def _geometry(landmarks: np.ndarray, gray: np.ndarray) -> dict:
    """Compute key points and regional metrics at once.

    Args:
        landmarks: Landmark array in aligned image coordinates.
        gray: Grayscale aligned face.

    Returns:
        Dictionary with geometric metrics.
    """
    eye_left_c = _midpoint(landmarks, 33, 133)
    eye_right_c = _midpoint(landmarks, 362, 263)
    interocular = float(np.linalg.norm(eye_right_c - eye_left_c)) + 1e-6
    eye_mid_y = float((eye_left_c[1] + eye_right_c[1]) / 2.0)
    cx = float((eye_left_c[0] + eye_right_c[0]) / 2.0)
    nose = _point(landmarks, NOSE_TIP)
    mouth_c = _midpoint(landmarks, MOUTH_CORNERS[0], MOUTH_CORNERS[1])
    mouth_close = min(
        eye_aspect_ratio(landmarks, [61, 0, 13, 291, 14, 17]) * 4.0, 1.0)

    # Regions (coordinates in aligned face pixels).
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
    """Return decision thresholds per attribute (0..1 over raw confidence).

    Single source of truth for calibration: the GUI adjusts them in real time
    and the classifier only applies what is passed here.

    Returns:
        Dictionary of attribute thresholds.
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
    """Classify six attributes from raw confidences (0..1).

    ``thresholds`` allows overriding per-attribute thresholds without
    recomputing the model; defaults to ``default_thresholds()``. This also
    re-classifies already stored confidences for calibration.

    Args:
        conf: Raw confidence dictionary.
        thresholds: Optional threshold overrides.

    Returns:
        Classified FaceAttributes.
    """
    conf = dict(conf or {})
    thresholds = {**default_thresholds(), **(thresholds or {})}

    def decided(field: str) -> bool:
        """Check if a field exceeds its threshold.

        Args:
            field: Attribute field name.

        Returns:
            True if above threshold.
        """
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
# Eye / hair color (HSV heuristics on aligned face)
# --------------------------------------------------------------------------- #
def _clean_color(value, labels: tuple[str, ...]) -> str | None:
    """Validate a color value against allowed labels.

    Args:
        value: Candidate value.
        labels: Allowed labels.

    Returns:
        Validated color or None.
    """
    if isinstance(value, str) and value in labels:
        return value
    return None


def classify_eye_color_hsv(h: float, s: float, v: float) -> str:
    """Classify iris color from HSV (0-180 / 0-255 / 0-255).

    Empirical rules: very dark -> black; low saturation -> gray; then by hue
    (brown, green, blue). Approximation sensitive to illumination.

    Args:
        h: Hue.
        s: Saturation.
        v: Value.

    Returns:
        Color label.
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
    """Classify hair color from HSV (0-180 / 0-255 / 0-255).

    Args:
        h: Hue.
        s: Saturation.
        v: Value.

    Returns:
        Color label.
    """
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
    """Compute median HSV of an ROI (or a square centered at ``center``).

    Args:
        image_bgr: BGR image.
        x0: Left coordinate.
        y0: Top coordinate.
        x1: Right coordinate.
        y1: Bottom coordinate.
        center: Optional center point (y, x).
        radius: Radius around center.

    Returns:
        Median (h, s, v) or None if ROI is too small.
    """
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
    """Classify discrete eye color by sampling the iris (indices 468/473).

    Args:
        image_bgr: Aligned BGR face image.
        landmarks: Landmark array.

    Returns:
        Color label or None if not determinable.
    """
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
    """Classify discrete hair color sampling the upper forehead band.

    Compares the "hair" band with a skin reference (forehead); if
    indistinguishable from skin, hair is not in the aligned frame and ``None``
    is returned.

    Args:
        image_bgr: Aligned BGR face image.
        landmarks: Landmark array.

    Returns:
        Color label or None.
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
    # If the upper band is essentially the same skin, no visible hair.
    if (abs(hair_med[0] - skin_med[0]) < 18
            and abs(hair_med[2] - skin_med[2]) < 18):
        return None
    return classify_hair_color_hsv(*hair_med)


def classify_aligned(landmarks: np.ndarray, image_bgr: np.ndarray) -> FaceAttributes:
    """Classify six attributes (plus eye/hair color) from the aligned face.

    Args:
        landmarks: (N, 2) in pixels of ``image_bgr`` (N=478 with iris,
            MediaPipe FaceMesh). Pure function, also used in tests with
            synthetic data.
        image_bgr: Aligned BGR face image.

    Returns:
        Populated FaceAttributes.
    """
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    ears = metric_eyes_open(landmarks)
    smile = metric_smile(landmarks)
    g = _geometry(landmarks, gray)

    eyes_factor = ears / EYE_OPEN_EAR  # >1 means comfortably open.
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
# Analyzer with MediaPipe FaceMesh (lazy, offline)
# --------------------------------------------------------------------------- #
class FaceAttributeAnalyzer:
    """Lazy wrapper around ``mediapipe.solutions.face_mesh`` (bundled model).

    Process-wide singleton, like FaceEngine: landmark model loading occurs only
    on first analysis, never at import time.
    """

    _instance: "FaceAttributeAnalyzer | None" = None

    def __init__(self):
        """Initialize the analyzer (model loaded lazily)."""
        self._mesh = None
        self._load_failed = False
        self._lock = threading.RLock()

    @classmethod
    def instance(cls) -> "FaceAttributeAnalyzer":
        """Return the singleton instance.

        Returns:
            Shared FaceAttributeAnalyzer.
        """
        if cls._instance is None:
            cls._instance = FaceAttributeAnalyzer()
        return cls._instance

    @property
    def is_loaded(self) -> bool:
        """Whether the FaceMesh model is loaded."""
        return self._mesh is not None

    def warmup(self) -> None:
        """Preload the FaceMesh model synchronously."""
        self._ensure_loaded()

    def _ensure_loaded(self) -> None:
        """Load the FaceMesh model lazily, thread-safe."""
        if self._mesh is not None or self._load_failed:
            return
        with self._lock:
            if self._mesh is not None or self._load_failed:
                return
            try:
                from mediapipe.python.solutions import face_mesh as mp_face_mesh

                logger.info("Loading facial landmark model (MediaPipe)...")
                self._mesh = mp_face_mesh.FaceMesh(
                    static_image_mode=True,
                    max_num_faces=1,
                    refine_landmarks=True,
                    min_detection_confidence=0.3,
                )
                logger.info("Facial landmark model loaded.")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not initialize MediaPipe FaceMesh: {}", exc)
                self._mesh = None
                self._load_failed = True

    def analyze(self, bgr_image: np.ndarray, bbox, landmarks5) -> FaceAttributes | None:
        """Analyze a face already detected by InsightFace.

        Normalizes the face with the ``face_quality.align_face`` template (same
        geometry for all shots), runs MediaPipe on it, and classifies. Returns
        ``None`` if the model is unavailable, refinement fails, or extended
        attributes are disabled.

        Args:
            bgr_image: Source BGR image.
            bbox: Face bounding box (unused, kept for API symmetry).
            landmarks5: 5-point landmarks from InsightFace.

        Returns:
            FaceAttributes or None.
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
            logger.debug("Extended facial analysis skipped for this face: {}", exc)
            return None
