"""
Índice ANN para la búsqueda biométrica 1:N.

La base de rostros (decenas de miles de embeddings de 512 dims) ya no se
recorre con un bucle en Python: se indexa en memoria con **FAISS** para
obtener vecinos aproximados en tiempo sub-lineal y, a partir de ahí, los
candidatos devueltos se mapean a (`person_uuid`, `embedding_id`) con las
mismas distancias/similitudes coseno que usaba la búsqueda lineal.

Garantías de diseño:

  - *Degradación automática*: si `faiss` no está instalado, si el índice
    está desactivado (`recognition.ann_enabled`) o si la galería es pequeña
    (`recognition.ann_min_size`), el módulo devuelve ``None`` y la capa de
    reconocimiento conserva la búsqueda lineal exacta (cero cambios de
    comportamiento).
  - *Exacto para bases pequeñas / aproximado para bases grandes*: por debajo
    de ``recognition.ann_ivf_min_size`` se usa ``IndexFlatIP`` (exhaustivo,
    vectorizado en C++; idéntico resultado que el recorrido lineal). Por
    encima, ``IndexIVFFlat`` (ANN real, satinado por clusters) con un reparto
    ``nprobe`` conservador que mantiene una recuperación (recall) alta.
  - *Caché global por proceso*: los índices son costosos de construir (en
    particular el entrenamiento k-means del IVF), así que se cachean por
    proceso y se reconstruyen únicamente cuando la galería cambia.
  - *Sin dependencias obligatorias*: toda la integración es *opcional*; la
    instalación de `faiss-cpu` es lo único necesario para activarla.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from app.core.config import settings
from app.core.logger import logger
from app.recognition.matcher import MatchCandidate

# --------------------------------------------------------------------------- #
# Configuración
# --------------------------------------------------------------------------- #
@dataclass
class AnnConfig:
    enabled: bool = True
    min_size: int = 256          # galería menor a esto -> búsqueda lineal exacta
    ivf_min_size: int = 2000     # sobre este tamaño -> IndexIVFFlat (ANN real)
    nlist: int = 0               # 0 = automático (min(n // 64, 1024))
    nprobe: int = 0              # 0 = automático (max(1, nlist // 8))
    persist: bool = False        # guardar el índice IVF a disco y reutilizarlo
    index_dir: Path | None = None


def ann_config() -> AnnConfig:
    index_dir = settings.recognition.ann_index_dir
    return AnnConfig(
        enabled=settings.recognition.ann_enabled,
        min_size=settings.recognition.ann_min_size,
        ivf_min_size=settings.recognition.ann_ivf_min_size,
        nlist=settings.recognition.ann_nlist,
        nprobe=settings.recognition.ann_nprobe,
        persist=settings.recognition.ann_persist,
        index_dir=settings.resolve_path(index_dir) if index_dir else None,
    )


def _faiss_available() -> bool:
    try:
        import faiss  # noqa: PLC0415
        return True
    except Exception:  # noqa: BLE001 - import opcional
        return False


# --------------------------------------------------------------------------- #
# Índice
# --------------------------------------------------------------------------- #
class BiometricIndex:
    """Índice de embeddings unitarios (coseno) construido sobre FAISS.

    En ``IndexFlatIP`` / ``IndexIVFFlat`` con vectores L2-normalizados, la
    métrica de producto interno devuelta por ``search`` ES la similitud coseno
    (mayor = mejor); la distancia coseno es su complemento ``1 - sim``.
    """

    def __init__(self, dim: int, n: int):
        import faiss  # noqa: PLC0415 - garantizado por build()

        self._dim = dim
        self._n = n
        self._ivf = False
        self._index = faiss.IndexFlatIP(dim)
        self._uuids: list[str] = []
        self._emb_ids: list[int] = []
        self._rows: np.ndarray = np.empty((0, dim), dtype=np.float32)
        self._seq: list[tuple[int, str]] | None = None

    # ------------------------------------------------------------------ #
    # Construcción
    # ------------------------------------------------------------------ #
    @staticmethod
    def build(gallery: list[tuple[str, int, np.ndarray]],
              cfg: AnnConfig | None = None,
              available: Callable[[], bool] | None = None) -> "BiometricIndex | None":
        """Construye un índice a partir de la galería, o ``None`` si no aplica.

        ``gallery``: lista de (person_uuid, embedding_id, vector). ``available``
        permite inyectar la disponibilidad de FAISS en las pruebas.
        """
        cfg = cfg or ann_config()
        if not cfg.enabled:
            return None
        n = len(gallery)
        if n < cfg.min_size:
            return None
        if (available is None and not _faiss_available()) or (available is not None
                                                              and not available()):
            logger.warning("faiss no está disponible; se usará búsqueda lineal 1:N.")
            return None

        try:
            idx = BiometricIndex(gallery[0][2].shape[0], n)
            idx._fit(gallery, cfg)
            logger.info(
                "Índice ANN construido | n={} | dim={} | modo={}",
                n, idx._dim, "ivf" if idx._ivf else "flat(exacto)")
            return idx
        except Exception as exc:  # noqa: BLE001 - nunca romper el reconocimiento
            logger.warning("No se pudo construir el índice ANN; búsqueda lineal: {}", exc)
            return None

    def _fit(self, gallery, cfg: AnnConfig) -> None:
        import faiss  # noqa: PLC0415

        matrix = np.vstack([np.asarray(v, dtype=np.float32).ravel()
                            for _, _, v in gallery])
        matrix = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-10)
        matrix = np.ascontiguousarray(matrix, dtype=np.float32)
        self._rows = matrix
        self._uuids = [uuid for uuid, _, _ in gallery]
        self._emb_ids = [emb_id for _, emb_id, _ in gallery]

        if matrix.shape[0] >= cfg.ivf_min_size:
            nlist = cfg.nlist or min(max(4, matrix.shape[0] // 64), 1024)
            nlist = min(nlist, matrix.shape[0])
            nprobe = cfg.nprobe or max(1, nlist // 8)
            if nlist >= 4:
                quantizer = faiss.IndexFlatIP(self._dim)
                index = faiss.IndexIVFFlat(quantizer, self._dim, nlist,
                                           faiss.METRIC_INNER_PRODUCT)
                index.train(matrix)
                index.add(matrix)
                index.nprobe = nprobe
                self._index = index
                self._ivf = True
                return
        self._index.add(matrix)

    # ------------------------------------------------------------------ #
    # Persistencia a disco (solo modo IVF; evita re-entrenar k-means)
    # ------------------------------------------------------------------ #
    def save(self, fingerprint: tuple, cfg: AnnConfig) -> Path | None:
        """Guarda el índice IVF (FAISS) + metadatos. Devuelve la ruta o ``None``."""
        if not cfg.persist or cfg.index_dir is None or not self._ivf:
            return None
        import faiss  # noqa: PLC0415

        files = _index_files(fingerprint, cfg.index_dir)
        try:
            files["dir"].mkdir(parents=True, exist_ok=True)
            faiss.write_index(self._index, str(files["faiss"]))
            files["json"].write_text(json.dumps({
                "fingerprint": [int(fingerprint[0]), int(fingerprint[1])],
                "dim": self._dim,
                "n": self._n,
                "mode": self.mode,
                "uuids": list(self._uuids),
                "emb_ids": [int(e) for e in self._emb_ids],
            }), encoding="utf-8")
            if files["npz"].exists():
                # Formato legacy (pickle): ya no se usa; se elimina al persistir.
                files["npz"].unlink(missing_ok=True)
            logger.info("Índice ANN persistido | n={} | {}", self._n, files["faiss"].name)
            return files["faiss"]
        except Exception as exc:  # noqa: BLE001 - nunca romper el reconocimiento
            logger.warning("No se pudo persistir el índice ANN: {}", exc)
            return None

    @classmethod
    def load(cls, fingerprint: tuple, cfg: AnnConfig) -> "BiometricIndex | None":
        """Reconstruye un índice persistido, o ``None`` si no existe/corresponde."""
        if not cfg.persist or cfg.index_dir is None:
            return None
        files = _index_files(fingerprint, cfg.index_dir)
        try:
            if not (files["faiss"].exists() and files["json"].exists()):
                return None
            meta = json.loads(files["json"].read_text(encoding="utf-8"))
            if tuple(meta.get("fingerprint") or ()) != tuple(int(x) for x in fingerprint):
                return None
            uuids = meta.get("uuids")
            emb_ids = meta.get("emb_ids")
            if uuids is None or emb_ids is None:
                # Formato legacy sin metadatos de identidad: no se puede cargar.
                return None
            import faiss  # noqa: PLC0415

            idx = cls.__new__(cls)
            idx._index = faiss.read_index(str(files["faiss"]))
            idx._ivf = meta.get("mode") == "ivf"
            idx._dim = int(meta.get("dim", 0))
            idx._n = int(meta.get("n", 0))
            idx._uuids = list(uuids)
            idx._emb_ids = [int(e) for e in emb_ids]
            idx._rows = np.empty((0, idx._dim), dtype=np.float32)
            if idx._ivf:
                nlist_loaded = int(idx._index.nlist)
                idx._index.nprobe = cfg.nprobe or max(1, nlist_loaded // 8)
            if files["npz"].exists():
                # Formato legacy (pickle): se elimina; el JSON ya es la única fuente.
                files["npz"].unlink(missing_ok=True)
            logger.info("Índice ANN cargado desde disco | n={} | modo={}",
                        idx._n, idx.mode)
            return idx
        except Exception as exc:  # noqa: BLE001 - degradar a reconstrucción
            logger.warning("No se pudo cargar el índice ANN desde disco: {}", exc)
            return None

    # ------------------------------------------------------------------ #
    # Búsqueda
    # ------------------------------------------------------------------ #
    def set_nprobe(self, nprobe: int) -> None:
        """Ajusta los clusters explorados por el índice IVF (sin reconstruir).

        Permite calibrar la exactitud/velocidad en el benchmark de recall sin
        volver a entrenar el k-means. No tiene efecto en modo flat.
        """
        if self._ivf:
            self._index.nprobe = max(1, int(nprobe))

    def search(self, query_vector: np.ndarray, top_k: int = 5) -> list[MatchCandidate]:
        """Devuelve los ``top_k`` candidatos más cercanos por similitud coseno."""
        q = np.asarray(query_vector, dtype=np.float32).ravel()
        norm = float(np.linalg.norm(q))
        if norm > 0:
            q = q / norm
        q = np.ascontiguousarray(q.reshape(1, -1), dtype=np.float32)

        sims, labels = self._index.search(q, max(1, int(top_k)))
        out: list[MatchCandidate] = []
        for sim, label in zip(sims[0], labels[0]):
            label = int(label)
            if label < 0 or label >= self._n:
                break
            sim = float(sim)
            out.append(MatchCandidate(
                person_uuid=self._uuids[label],
                embedding_id=self._emb_ids[label],
                distance=1.0 - sim,
                similarity=sim,
            ))
        return out

    @property
    def size(self) -> int:
        return self._n

    @property
    def mode(self) -> str:
        return "ivf" if self._ivf else "flat"


# --------------------------------------------------------------------------- #
# Caché global por proceso (los índices son costosos de construir)
# --------------------------------------------------------------------------- #
_LOCK = threading.RLock()
_SHARED: dict[tuple, BiometricIndex | None] = {}


def _index_seq(gallery: list[tuple[str, int, np.ndarray]]) -> list[tuple[int, str]]:
    """Firma del contenido de una galería: (embedding_id, person_uuid) ordenados.

    A diferencia del fingerprint ``(count, max_id)``, dos galerías distintas
    (p. ej. tras restaurar la BD sobre un archivo persistido antiguo) nunca
    comparten esta firma, así que un índice cacheadado/persistido no se
    reutiliza sobre datos a los que no corresponde (evita resultados TOCTOU).
    """
    return sorted((int(emb_id), uuid) for uuid, emb_id, _ in gallery)


def _index_files(fingerprint: tuple, index_dir: Path) -> dict[str, Path]:
    """Rutas de los archivos que componen un índice persistido.

    ``faiss`` guarda el índice vectorial y ``json`` los metadatos de identidad
    (uuids/emb_ids). ``npz`` es el formato legacy basado en pickle; se conserva
    la ruta solo para detectarlo y eliminarlo al persistir/cargar.
    """
    count, maxid = int(fingerprint[0]), int(fingerprint[1])
    return {
        "dir": index_dir,
        "faiss": index_dir / f"ann_{count}_{maxid}.faiss",
        "npz": index_dir / f"ann_{count}_{maxid}.npz",
        "json": index_dir / f"ann_{count}_{maxid}.json",
    }


def get_shared_index(gallery: list[tuple[str, int, np.ndarray]],
                     fingerprint: tuple) -> BiometricIndex | None:
    """Devuelve un índice compartido para ``gallery``, reconstruido solo si cambió.

    ``fingerprint``: marca de la galería (count, max_id); se usa como clave de
    caché rápida. Como esa marca puede colisionar entre galerías distintas y
    los índices pueden venir de disco (``recognition.ann_persist``), el índice
    solo se reutiliza si su contenido ``(embedding_id, person_uuid)`` coincide
    exactamente con el de la galería actual; en caso contrario se reconstruye.
    Solo se conserva el índice más reciente; los anteriores se descartan.
    """
    with _LOCK:
        seq = _index_seq(gallery)
        cached = _SHARED.get(fingerprint)
        if cached is not None and cached._seq == seq:
            return cached
        cfg = ann_config()
        built: BiometricIndex | None = BiometricIndex.load(fingerprint, cfg)
        if built is not None:
            built._seq = _index_seq([
                (uuid, emb_id, np.empty(0, dtype=np.float32))
                for uuid, emb_id in zip(built._uuids, built._emb_ids)
            ])
            if built._seq == seq:
                _SHARED.clear()
                _SHARED[fingerprint] = built
                return built
        built = BiometricIndex.build(gallery, cfg)
        if built is not None:
            built._seq = seq
            built.save(fingerprint, cfg)
        _SHARED.clear()
        _SHARED[fingerprint] = built
        return built