"""Serialización de vectores biométricos (numpy.ndarray <-> bytes) para SQLite."""
import numpy as np


def vector_to_bytes(vector: np.ndarray) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


def bytes_to_vector(data: bytes, dim: int = 512) -> np.ndarray:
    arr = np.frombuffer(data, dtype=np.float32)
    if arr.shape[0] != dim:
        raise ValueError(f"Dimensión de embedding inesperada: {arr.shape[0]} (esperado {dim})")
    return arr


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Similitud coseno en [-1, 1]. 1 = idénticos."""
    a_norm = a / (np.linalg.norm(a) + 1e-10)
    b_norm = b / (np.linalg.norm(b) + 1e-10)
    return float(np.dot(a_norm, b_norm))


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Distancia coseno en [0, 2]. 0 = idénticos."""
    return 1.0 - cosine_similarity(a, b)
