"""Sentence-transformers lazy singleton (configurable model + E5-style prompts)."""

from __future__ import annotations

import time
from typing import Any, Literal

import numpy as np

from core.config import Settings, get_settings

_model: Any = None


def reset_embedding_model() -> None:
    """Drop cached model (e.g. after changing EMBEDDING_MODEL in tests)."""
    global _model
    _model = None


def _wrap_instruction(text: str, role: Literal["query", "passage"], settings: Settings) -> str:
    t = (text or "").strip() or "empty"
    mode = (settings.embedding_instruction_mode or "none").lower()
    if mode == "e5":
        prefix = "query: " if role == "query" else "passage: "
        return prefix + t
    return t


def _load_model(settings: Settings) -> Any:
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(settings.embedding_model, device=settings.embed_device)
    return _model


def embed_text(
    text: str,
    settings: Settings | None = None,
    *,
    role: Literal["query", "passage"] = "passage",
) -> tuple[list[float], float]:
    """Returns (vector as list of float, latency_ms)."""
    settings = settings or get_settings()
    t0 = time.perf_counter()
    model = _load_model(settings)
    payload = _wrap_instruction(text, role, settings)
    vec = model.encode(payload, convert_to_numpy=True, normalize_embeddings=True)
    if vec.dtype != np.float32:
        vec = vec.astype(np.float32)
    ms = (time.perf_counter() - t0) * 1000
    return vec.tolist(), round(ms, 2)


def embed_text_to_bytes(
    text: str,
    settings: Settings | None = None,
    *,
    role: Literal["query", "passage"] = "passage",
) -> tuple[bytes, float]:
    vec, ms = embed_text(text, settings, role=role)
    return np.array(vec, dtype=np.float32).tobytes(), ms


def embed_many_to_bytes(
    texts: list[str],
    settings: Settings | None = None,
    *,
    role: Literal["query", "passage"] = "passage",
) -> tuple[list[bytes], float]:
    """Batch encode for ingest (much faster than one ``encode`` per document)."""
    if not texts:
        return [], 0.0
    settings = settings or get_settings()
    t0 = time.perf_counter()
    model = _load_model(settings)
    payloads = [_wrap_instruction(t, role, settings) for t in texts]
    bs = min(128, max(8, len(payloads)))
    arr = model.encode(
        payloads,
        convert_to_numpy=True,
        normalize_embeddings=True,
        batch_size=bs,
        show_progress_bar=False,
    )
    if arr.dtype != np.float32:
        arr = arr.astype(np.float32)
    ms = round((time.perf_counter() - t0) * 1000, 2)
    out = [arr[i].tobytes() for i in range(arr.shape[0])]
    return out, ms


def embedding_enabled(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    return s.embedding_write_mode.lower() != "none"
