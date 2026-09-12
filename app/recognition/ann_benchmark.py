"""
Benchmark y diagnóstico del índice ANN (FAISS) para la búsqueda biométrica 1:N.

Compara la búsqueda lineal exacta (referencia) contra el índice `IndexIVFFlat`
con distintos valores de `nprobe`, de modo que el operador pueda calibrar
`recognition.ann_nprobe` según el recall que necesite, el tamaño de su base y
su presupuesto de latencia.

Uso desde CLI (base en producción):

    python -m app.recognition.ann_benchmark

También se invoca desde Administración → Parámetros de reconocimiento a través
de `run_ann_diagnosis()` (que alimenta el panel de estado).
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
    """Recall@k: fracción de los top-k exactos recuperados por el índice."""
    if not exact or not ranked:
        return 0.0
    exact_ids = {c.embedding_id for c in exact[:k]}
    if not exact_ids:
        return 1.0
    found = sum(1 for c in ranked[:k] if c.embedding_id in exact_ids)
    return found / len(exact_ids)


def benchmark_recall(gallery, nprobes=DEFAULT_NPROBES, top_k: int = DEFAULT_TOP_K,
                     sample: int = DEFAULT_SAMPLE, seed: int = 0) -> dict:
    """Construye el índice IVF una sola vez y mide recall@top_k por cada nprobe.

    ``gallery``: lista de (person_uuid, embedding_id, vector) unitarios.
    Devuelve un dict con las filas (nprobe, recall, tiempos) y la sugerencia.
    """
    if not _faiss_available():
        logger.warning("faiss no está disponible; benchmark omitido.")
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
    """Estado del índice tal y como lo usaría la búsqueda 1:N en producción."""
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
    """Diagnóstico completo: estado del índice + benchmark de recall si aplica."""
    info = describe_ann_state(session)
    if info["mode"] == "ivf":
        service = RecognitionService(session)
        gallery = service._load_gallery()
        info["benchmark"] = benchmark_recall(gallery, nprobes=nprobes,
                                             top_k=top_k, sample=sample)
    return info


def format_diagnosis_report(info: dict) -> str:
    """Texto legible (HTML ligero, apto para QLabel y consola) del diagnóstico."""
    faiss_txt = ("faiss-cpu detectado" if info["available"]
                 else "faiss-cpu NO está instalado (búsqueda lineal exacta)")
    lines = [f"<b>Índice ANN</b> · {faiss_txt}"]
    lines.append(f"Configuración: activo={str(info['enabled']).lower()} · "
                 f"min {info['min_size']} rostros · IVF desde {info['ivf_min_size']} · "
                 f"clusters={info['nlist'] or 'auto'} · probes={info['nprobe'] or 'auto'}")
    lines.append(f"Galería: {info['n']} embeddings -> modo <b>{info['mode'].upper()}</b>")
    if info["mode"] == "ivf":
        lines.append(f"Índice construido: {info.get('index_built')} · "
                     f"tiempo {info.get('build_ms', 'n/a')} ms · "
                     f"tipo {info.get('index_mode', 'n/a')} · "
                     f"nlist usado {info.get('nlist_used', 'n/a')} · "
                     f"nprobe usado {info.get('nprobe_used', 'n/a')}")
        bench = info.get("benchmark") or {}
        if bench.get("too_small"):
            lines.append(f"Benchmark: galería pequeña ({bench['too_small']}); "
                         "calibrar nprobe no aplica.")
        elif bench.get("rows"):
            lines.append("<b>Benchmark recall@{} (vs lineal exacta)</b>:".format(
                bench.get("top_k") or DEFAULT_TOP_K))
            for row in bench["rows"]:
                lines.append(
                    f"  nprobe={row['nprobe']:<3} recall={row['recall']:.2%} "
                    f"promedio {row['avg_search_ms']:.2f} ms")
            lines.append(f"Sugerencia: <b>nprobe={bench.get('suggested')}</b> "
                         "(recall ≥ 98% o el mejor medido).")
            lines.append("Puedes fijar ese valor arriba en 'Clusters explorados "
                         "(0 = automático)'.")
        elif bench.get("build_failed"):
            lines.append("Benchmark: no se pudo construir el índice IVF.")
    elif info["mode"] == "flat":
        lines.append("Modo flat (exacto, vectorizado): no hay recall que calibrar.")
    else:
        lines.append("Índice desactivado o FAISS ausente: las búsquedas usan "
                     "recorrido lineal exacto.")
    return "<br>".join(lines)


def main() -> None:  # pragma: no cover - utilidad de consola
    import sys

    from app.database.session import SessionLocal  # noqa: PLC0415

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # consolas Windows (cp1252)
    except Exception:  # noqa: BLE001 - opcional
        pass

    print("Cargando galería biométrica desde la base de datos…")
    with SessionLocal() as session:
        info = run_ann_diagnosis(session)
    print(format_diagnosis_report(info).replace("<br>", "\n")
          .replace("<b>", "").replace("</b>", ""))


if __name__ == "__main__":
    main()