"""Biometric vector serialization (numpy.ndarray <-> bytes) for SQLite."""

import numpy as np


def vector_to_bytes(vector: np.ndarray) -> bytes:
    """Serialize a vector to bytes.

    Args:
        vector: Numpy array to serialize.

    Returns:
        Raw bytes in float32 format.
    """
    return np.asarray(vector, dtype=np.float32).tobytes()


def bytes_to_vector(data: bytes, dim: int = 512) -> np.ndarray:
    """Deserialize bytes to a vector.

    Args:
        data: Raw bytes in float32 format.
        dim: Expected vector dimension.

    Returns:
        Numpy array of shape (dim,).

    Raises:
        ValueError: If the decoded size does not match dim.
    """
    arr = np.frombuffer(data, dtype=np.float32)
    if arr.shape[0] != dim:
        raise ValueError(f"Unexpected embedding dimension: {arr.shape[0]} (expected {dim})")
    return arr


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity in [-1, 1].

    Args:
        a: First vector.
        b: Second vector.

    Returns:
        Cosine similarity. 1 means identical.
    """
    a_norm = a / (np.linalg.norm(a) + 1e-10)
    b_norm = b / (np.linalg.norm(b) + 1e-10)
    return float(np.dot(a_norm, b_norm))


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine distance in [0, 2].

    Args:
        a: First vector.
        b: Second vector.

    Returns:
        Cosine distance. 0 means identical.
    """
    return 1.0 - cosine_similarity(a, b)
