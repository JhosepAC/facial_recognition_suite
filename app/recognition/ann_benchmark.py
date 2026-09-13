"""Benchmark and diagnostics for the ANN (FAISS) index for 1:N biometric search.

Compares the exact linear search (reference) against ``IndexIVFFlat`` with
different ``nprobe`` values so the operator can calibrate
``recognition.ann_nprobe`` for the desired recall, gallery size, and latency.

CLI usage (production DB):

    python -m app.recognition.ann_benchmark

Also invoked from Administration -> Recognition Parameters via
``run_ann_diagnosis()`` (which feeds the status panel).
"""

from __future__ import annotations

import time

import numpy as np

from app.core.logger import logger
from app.recognition.ann_index import (
    AnnConfig, BiometricIndex, _faiss_available, ann_config,
)
from app.recognition.matcher import rank_candidates
from app.recognition.recognition_service import RecognitionService

DEFAULT_NPROBES = (1, 2, 4, 8, 16)
DEFAULT_TOP_K = 5
DEFAULT_SAMPLE = 250


def _recall_at_k(exact: list, ranked: list, k: int) -> float:
    """Compute recall@k: fraction of exact top-k recovered by the index.

    Args:
        exact: Exact ranked candidates.
        ranked: ANN ranked candidates.
        k: Cut-off.

    Returns:
        Recall value in [0, 1].
    """
    if not exact or not ranked:
        return 0.0
    exact_ids = {c.embedding_id for c in exact[:k]}
    if not exact_ids:
        return 1.0
    found = sum(1 for c in ranked[:k] if c.embedding_id in exact_ids)
    return found / len(exact_ids)


def benchmark_recall(gallery, nprobes=DEFAULT_NPROBES, top_k: int = DEFAULT_TOP_K,
                     sample: int = DEFAULT_SAMPLE, seed: int = 0) -> dict:
    """Build the IVF index once and measure recall@top_k per nprobe.

    Args:
        gallery: List of (person_uuid, embedding_id, vector) unit vectors.
        nprobes: Nprobe values to evaluate.
        top_k: Number of top results for recall.
        sample: Number of random queries to sample.
        seed: RNG seed.

    Returns:
        Dict with rows (nprobe, recall, timings) and suggestion.
    """
    if not _faiss_available():
        logger.warning("faiss not available; benchmark skipped.")
        return {"available": False}

    cfg = ann_config()
    min_ivf = max(cfg.ivf_min_size, 16)
    if len(gallery) < min_ivf:
        return {"available": True, "too_small": len(gallery)}

    nlist = cfg.nlist or min(max(4, len(gallery) // 64), 1024)
    nlist = min(nlist, len(gallery))

    rng = np.random.default_rng(seed)
    n_q = min(int(sample), len(gallery))
    queries = [gallery[i][2]
               for i in rng.choice(len(gallery), size=n_q, replace=False)]

    exact_rows = [rank_candidates(q, gallery, top_k=top_k) for q in queries]

    build_cfg = AnnConfig(enabled=True, min_size=0, ivf_min_size=0,
                          nlist=nlist, nprobe=1)
    t0 = time.perf_counter()
    idx = BiometricIndex.build(gallery, cfg=build_cfg)
    build_ms = (time.perf_counter() - t0) * 1000.0
    if idx is None or idx.mode != "ivf":
        return {"available": True, "build_failed": True, "n": len(gallery),
                "nlist": nlist}

    rows: list[dict] = []
    for nprobe in nprobes:
        idx.set_nprobe(nprobe)
        recalls: list[float] = []
        t1 = time.perf_counter()
        for q, exact in zip(queries, exact_rows):
            ranked = idx.search(q, top_k=top_k)
            recalls.append(_recall_at_k(exact, ranked, top_k))
        avg_ms = (time.perf_counter() - t1) / n_q * 1000.0
        rows.append({
            "nprobe": int(nprobe),
            "recall": round(float(np.mean(recalls)), 4),
            "avg_search_ms": round(avg_ms, 3),
        })

    best = max(rows, key=lambda r: r["recall"])
    suggested = int(next((r["nprobe"] for r in rows if r["recall"] >= 0.98),
                         best["nprobe"]))
    return {
        "available": True, "too_small": None, "n": len(gallery),
        "dim": int(gallery[0][2].shape[0]), "nlist": nlist, "top_k": top_k,
        "build_ms": round(build_ms, 1), "rows": rows, "suggested": suggested,
    }


def describe_ann_state(session) -> dict:
    """Return the index state as used by the production 1:N search.

    Args:
        session: Active SQLAlchemy session.

    Returns:
        Dictionary describing ANN state.
    """
    service = RecognitionService(session)
    gallery = service._load_gallery()
    cfg = ann_config()
    faiss_ok = _faiss_available()
    mode = "linear"
    if faiss_ok and cfg.enabled and len(gallery) >= cfg.min_size:
        mode = "ivf" if len(gallery) >= cfg.ivf_min_size else "flat"
    info = {
        "available": faiss_ok,
        "enabled": cfg.enabled,
        "n": len(gallery),
        "mode": mode,
        "min_size": cfg.min_size,
        "ivf_min_size": cfg.ivf_min_size,
        "nlist": cfg.nlist,
        "nprobe": cfg.nprobe,
    }
    if mode == "ivf":
        t0 = time.perf_counter()
        index = service._index(gallery)
        info["build_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
        info["index_built"] = index is not None
        if index is not None:
            info["index_mode"] = index.mode
            info["nlist_used"] = int(getattr(index._index, "nlist", cfg.nlist))
            info["nprobe_used"] = int(getattr(index._index, "nprobe", cfg.nprobe))
    return info


def run_ann_diagnosis(session, nprobes=DEFAULT_NPROBES, top_k: int = DEFAULT_TOP_K,
                      sample: int = DEFAULT_SAMPLE) -> dict:
    """Run a full diagnosis: index state + recall benchmark if applicable.

    Args:
        session: Active SQLAlchemy session.
        nprobes: Nprobe values to benchmark.
        top_k: Top-k for recall.
        sample: Number of queries.

    Returns:
        Dictionary with state and optional benchmark.
    """
    info = describe_ann_state(session)
    if info["mode"] == "ivf":
        service = RecognitionService(session)
        gallery = service._load_gallery()
        info["benchmark"] = benchmark_recall(gallery, nprobes=nprobes,
                                             top_k=top_k, sample=sample)
    return info


def format_diagnosis_report(info: dict) -> str:
    """Format a human-readable (light HTML, suitable for QLabel and console) report.

    Args:
        info: Diagnosis dictionary.

    Returns:
        HTML string.
    """
    faiss_txt = ("faiss-cpu detected" if info["available"]
                 else "faiss-cpu NOT installed (exact linear search)")
    lines = [f"<b>ANN Index</b> · {faiss_txt}"]
    lines.append(f"Configuration: enabled={str(info['enabled']).lower()} · "
                 f"min {info['min_size']} faces · IVF from {info['ivf_min_size']} · "
                 f"clusters={info['nlist'] or 'auto'} · probes={info['nprobe'] or 'auto'}")
    lines.append(f"Gallery: {info['n']} embeddings -> mode <b>{info['mode'].upper()}</b>")
    if info["mode"] == "ivf":
        lines.append(f"Index built: {info.get('index_built')} · "
                     f"time {info.get('build_ms', 'n/a')} ms · "
                     f"type {info.get('index_mode', 'n/a')} · "
                     f"nlist used {info.get('nlist_used', 'n/a')} · "
                     f"nprobe used {info.get('nprobe_used', 'n/a')}")
        bench = info.get("benchmark") or {}
        if bench.get("too_small"):
            lines.append(f"Benchmark: small gallery ({bench['too_small']}); "
                         "calibrating nprobe not applicable.")
        elif bench.get("rows"):
            lines.append("<b>Benchmark recall@{} (vs exact linear)</b>:".format(
                bench.get("top_k") or DEFAULT_TOP_K))
            for row in bench["rows"]:
                lines.append(
                    f"  nprobe={row['nprobe']:<3} recall={row['recall']:.2%} "
                    f"average {row['avg_search_ms']:.2f} ms")
            lines.append(f"Suggestion: <b>nprobe={bench.get('suggested')}</b> "
                         "(recall >= 98% or best measured).")
            lines.append("You can set that value above in 'Clusters probed "
                         "(0 = auto)'.")
        elif bench.get("build_failed"):
            lines.append("Benchmark: could not build IVF index.")
    elif info["mode"] == "flat":
        lines.append("Flat mode (exact, vectorized): no recall to calibrate.")
    else:
        lines.append("Index disabled or FAISS missing: searches use "
                     "exact linear scan.")
    return "<br>".join(lines)


def main() -> None:  # pragma: no cover - console utility
    """Entry point for CLI execution."""
    import sys

    from app.database.session import SessionLocal  # noqa: PLC0415

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles (cp1252).
    except Exception:  # noqa: BLE001 - optional
        pass

    print("Loading biometric gallery from database...")
    with SessionLocal() as session:
        info = run_ann_diagnosis(session)
    print(format_diagnosis_report(info).replace("<br>", "\n")
          .replace("<b>", "").replace("</b>", ""))


if __name__ == "__main__":
    main()
