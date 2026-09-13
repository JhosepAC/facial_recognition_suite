"""
B5 — ANN index persistence without pickle.

Identity metadata (uuids/emb_ids) travels in the JSON alongside the FAISS
index; the legacy ``.npz`` format (pickle-based) is removed on save and on
load.
"""
import numpy as np
import pytest

from app.recognition.ann_index import (
    AnnConfig, BiometricIndex, _faiss_available,
)

DIM = 512

_HAS_FAISS = _faiss_available()


def _gallery(n, seed=7):
    rng = np.random.default_rng(seed)
    vecs = rng.standard_normal((n, DIM)).astype(np.float32)
    vecs = vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-10)
    return [(f"uuid-{i}", i, vecs[i]) for i in range(n)]


def _cfg(tmp_path):
    return AnnConfig(
        enabled=True, min_size=1, ivf_min_size=500,
        nlist=16, nprobe=2, persist=True, index_dir=tmp_path,
    )


def _fingerprint(gallery):
    return (len(gallery), max(e for _, e, _ in gallery))


@pytest.mark.skipif(
    not __import__("app.recognition.ann_index", fromlist=["_faiss_available"])._faiss_available(),
    reason="faiss is not installed",
)
def test_persist_and_load_roundtrip(tmp_path):
    gallery = _gallery(2100)
    cfg = _cfg(tmp_path)
    idx = BiometricIndex.build(gallery, cfg)
    assert idx is not None and idx._ivf

    fingerprint = _fingerprint(gallery)
    saved = idx.save(fingerprint, cfg)
    assert saved is not None
    assert (tmp_path / "ann_2100_2099.faiss").exists()
    assert (tmp_path / "ann_2100_2099.json").exists()
    # Legacy pickle-based format is never written.
    assert not (tmp_path / "ann_2100_2099.npz").exists()

    loaded = BiometricIndex.load(fingerprint, cfg)
    assert loaded is not None
    assert loaded._uuids == idx._uuids
    assert loaded._emb_ids == idx._emb_ids
    assert loaded.size == 2100


@pytest.mark.skipif(
    not __import__("app.recognition.ann_index", fromlist=["_faiss_available"])._faiss_available(),
    reason="faiss is not installed",
)
def test_load_removes_legacy_npz(tmp_path):
    gallery = _gallery(2100)
    cfg = _cfg(tmp_path)
    idx = BiometricIndex.build(gallery, cfg)
    fingerprint = _fingerprint(gallery)
    idx.save(fingerprint, cfg)

    npz_path = tmp_path / "ann_2100_2099.npz"
    npz_path.write_bytes(b"legacy-pickle-data")

    loaded = BiometricIndex.load(fingerprint, cfg)
    assert loaded is not None
    assert not npz_path.exists()


@pytest.mark.skipif(
    not __import__("app.recognition.ann_index", fromlist=["_faiss_available"])._faiss_available(),
    reason="faiss is not installed",
)
def test_load_missing_uuids_metadata_returns_none(tmp_path):
    import json

    gallery = _gallery(2100)
    cfg = _cfg(tmp_path)
    idx = BiometricIndex.build(gallery, cfg)
    fingerprint = _fingerprint(gallery)
    idx.save(fingerprint, cfg)

    # Simulate a legacy JSON without identity metadata.
    json_path = tmp_path / "ann_2100_2099.json"
    meta = json.loads(json_path.read_text(encoding="utf-8"))
    meta.pop("uuids")
    meta.pop("emb_ids")
    json_path.write_text(json.dumps(meta), encoding="utf-8")

    assert BiometricIndex.load(fingerprint, cfg) is None


@pytest.mark.skipif(
    not __import__("app.recognition.ann_index", fromlist=["_faiss_available"])._faiss_available(),
    reason="faiss is not installed",
)
def test_search_maps_to_uuid_and_embedding_id(tmp_path):
    gallery = _gallery(2100)
    cfg = _cfg(tmp_path)
    idx = BiometricIndex.build(gallery, cfg)
    fingerprint = _fingerprint(gallery)
    idx.save(fingerprint, cfg)

    loaded = BiometricIndex.load(fingerprint, cfg)
    matches = loaded.search(gallery[7][2], top_k=3)
    assert matches
    assert matches[0].person_uuid == "uuid-7"
    assert matches[0].embedding_id == 7
