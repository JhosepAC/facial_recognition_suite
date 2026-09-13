"""ANN index for 1:N biometric search.

The face gallery (tens of thousands of 512-d embeddings) is no longer scanned
with a Python loop: it is indexed in memory with **FAISS** for sub-linear
approximate nearest-neighbor lookup, mapping returned candidates to
(``person_uuid``, ``embedding_id``) with the same cosine distances/similarities
as the linear search.

Design guarantees:

  - *Automatic degradation*: if ``faiss`` is not installed, the index is
    disabled (``recognition.ann_enabled``), or the gallery is small
    (``recognition.ann_min_size``), the module returns ``None`` and the
    recognition layer keeps the exact linear search (zero behavior change).
  - *Exact for small galleries / approximate for large*: below
    ``recognition.ann_ivf_min_size`` uses ``IndexFlatIP`` (exhaustive,
    vectorized in C++; identical results to the linear scan). Above it,
    ``IndexIVFFlat`` (real ANN, clustered) with a conservative ``nprobe``
    that keeps recall high.
  - *Process-wide cache*: indices are expensive to build (especially k-means
    training for IVF), so they are cached per process and rebuilt only when the
    gallery changes.
  - *No hard dependencies*: integration is optional; installing ``faiss-cpu``
    is all that is needed to enable it.
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
# Configuration
# --------------------------------------------------------------------------- #
@dataclass
class AnnConfig:
    """Configuration for the ANN index."""

    enabled: bool = True
    min_size: int = 256  # Gallery smaller than this uses exact linear search.
    ivf_min_size: int = 2000  # Above this size uses IndexIVFFlat (real ANN).
    nlist: int = 0  # 0 means auto (min(n // 64, 1024)).
    nprobe: int = 0  # 0 means auto (max(1, nlist // 8)).
    persist: bool = False  # Persist IVF index to disk for reuse.
    index_dir: Path | None = None


def ann_config() -> AnnConfig:
    """Build ANN config from application settings.

    Returns:
        Populated AnnConfig.
    """
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
    """Check if FAISS is importable.

    Returns:
        True if available, False otherwise.
    """
    try:
        import faiss  # noqa: PLC0415
        return True
    except Exception:  # noqa: BLE001 - optional import
        return False


# --------------------------------------------------------------------------- #
# Index
# --------------------------------------------------------------------------- #
class BiometricIndex:
    """Index of unit embeddings (cosine) built on FAISS.

    With ``IndexFlatIP`` / ``IndexIVFFlat`` on L2-normalized vectors, the inner
    product returned by ``search`` is the cosine similarity (higher is better);
    cosine distance is ``1 - sim``.
    """

    def __init__(self, dim: int, n: int):
        """Initialize an empty index.

        Args:
            dim: Embedding dimension.
            n: Expected gallery size.
        """
        import faiss  # noqa: PLC0415 - guaranteed by build()

        self._dim = dim
        self._n = n
        self._ivf = False
        self._index = faiss.IndexFlatIP(dim)
        self._uuids: list[str] = []
        self._emb_ids: list[int] = []
        self._rows: np.ndarray = np.empty((0, dim), dtype=np.float32)
        self._seq: list[tuple[int, str]] | None = None

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #
    @staticmethod
    def build(gallery: list[tuple[str, int, np.ndarray]],
              cfg: AnnConfig | None = None,
              available: Callable[[], bool] | None = None) -> "BiometricIndex | None":
        """Build an index from the gallery, or ``None`` if not applicable.

        Args:
            gallery: List of (person_uuid, embedding_id, vector).
            cfg: ANN config. Defaults to ``ann_config()``.
            available: Optional callable to inject FAISS availability for tests.

        Returns:
            Built index or None.
        """
        cfg = cfg or ann_config()
        if not cfg.enabled:
            return None
        n = len(gallery)
        if n < cfg.min_size:
            return None
        if (available is None and not _faiss_available()) or (available is not None
                                                              and not available()):
            logger.warning("faiss not available; falling back to linear 1:N search.")
            return None

        try:
            idx = BiometricIndex(gallery[0][2].shape[0], n)
            idx._fit(gallery, cfg)
            logger.info(
                "ANN index built | n={} | dim={} | mode={}",
                n, idx._dim, "ivf" if idx._ivf else "flat(exact)")
            return idx
        except Exception as exc:  # noqa: BLE001 - never break recognition
            logger.warning("Could not build ANN index; linear search: {}", exc)
            return None

    def _fit(self, gallery, cfg: AnnConfig) -> None:
        """Fit the FAISS index to the gallery.

        Args:
            gallery: Gallery list.
            cfg: ANN config.
        """
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
    # Disk persistence (IVF only; avoids re-training k-means)
    # ------------------------------------------------------------------ #
    def save(self, fingerprint: tuple, cfg: AnnConfig) -> Path | None:
        """Persist the IVF index (FAISS) + metadata. Returns path or ``None``.

        Args:
            fingerprint: Gallery fingerprint.
            cfg: ANN config.

        Returns:
            Path to persisted index or None.
        """
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
                # Legacy format (pickle): no longer used; remove on persist.
                files["npz"].unlink(missing_ok=True)
            logger.info("ANN index persisted | n={} | {}", self._n, files["faiss"].name)
            return files["faiss"]
        except Exception as exc:  # noqa: BLE001 - never break recognition
            logger.warning("Could not persist ANN index: {}", exc)
            return None

    @classmethod
    def load(cls, fingerprint: tuple, cfg: AnnConfig) -> "BiometricIndex | None":
        """Load a persisted index, or ``None`` if missing/mismatched.

        Args:
            fingerprint: Gallery fingerprint.
            cfg: ANN config.

        Returns:
            Loaded index or None.
        """
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
                # Legacy format without identity metadata: cannot load.
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
                # Legacy format (pickle): remove; JSON is now the single source.
                files["npz"].unlink(missing_ok=True)
            logger.info("ANN index loaded from disk | n={} | mode={}",
                        idx._n, idx.mode)
            return idx
        except Exception as exc:  # noqa: BLE001 - degrade to rebuild
            logger.warning("Could not load ANN index from disk: {}", exc)
            return None

    # ------------------------------------------------------------------ #
    # Search
    # ------------------------------------------------------------------ #
    def set_nprobe(self, nprobe: int) -> None:
        """Adjust clusters explored by the IVF index without rebuilding.

        Allows calibrating accuracy/speed in the recall benchmark without
        retraining k-means. Has no effect in flat mode.

        Args:
            nprobe: Number of clusters to probe.
        """
        if self._ivf:
            self._index.nprobe = max(1, int(nprobe))

    def search(self, query_vector: np.ndarray, top_k: int = 5) -> list[MatchCandidate]:
        """Return the ``top_k`` nearest candidates by cosine similarity.

        Args:
            query_vector: Query embedding.
            top_k: Number of results.

        Returns:
            List of MatchCandidate.
        """
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
        """Number of indexed embeddings."""
        return self._n

    @property
    def mode(self) -> str:
        """Index mode: 'ivf' or 'flat'."""
        return "ivf" if self._ivf else "flat"


# --------------------------------------------------------------------------- #
# Process-wide cache (indices are expensive to build)
# --------------------------------------------------------------------------- #
_LOCK = threading.RLock()
_SHARED: dict[tuple, BiometricIndex | None] = {}


def _index_seq(gallery: list[tuple[str, int, np.ndarray]]) -> list[tuple[int, str]]:
    """Return the content signature of a gallery: sorted (embedding_id, person_uuid).

    Unlike the ``(count, max_id)`` fingerprint, two distinct galleries (e.g.,
    after restoring the DB over an old persisted file) never share this signature,
    so a cached/persisted index is not reused on mismatched data (avoids TOCTOU).

    Args:
        gallery: Gallery list.

    Returns:
        Sorted list of (embedding_id, person_uuid).
    """
    return sorted((int(emb_id), uuid) for uuid, emb_id, _ in gallery)


def _index_files(fingerprint: tuple, index_dir: Path) -> dict[str, Path]:
    """Return paths for files comprising a persisted index.

    ``faiss`` stores the vector index and ``json`` stores identity metadata
    (uuids/emb_ids). ``npz`` is the legacy pickle-based format; its path is
    kept only to detect and remove it on persist/load.

    Args:
        fingerprint: Gallery fingerprint.
        index_dir: Directory for index files.

    Returns:
        Dict with keys dir, faiss, npz, json.
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
    """Return a shared index for ``gallery``, rebuilding only if it changed.

    Args:
        gallery: Gallery list.
        fingerprint: Gallery fingerprint (count, max_id); used as a fast cache
            key. Because it may collide across distinct galleries and indices may
            come from disk (``recognition.ann_persist``), the index is reused
            only if its ``(embedding_id, person_uuid)`` content exactly matches
            the current gallery; otherwise it is rebuilt. Only the most recent
            index is retained; prior ones are discarded.

    Returns:
        Shared BiometricIndex or None.
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
