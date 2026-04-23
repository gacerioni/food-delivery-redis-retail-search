"""RediSearch index: ON HASH, optional VECTOR (see AGENT.md)."""

from __future__ import annotations

from typing import Any

import redis
from redis.exceptions import ResponseError

from core.config import Settings, get_settings
from data.redis_client import get_redis


def _use_vector(settings: Settings) -> bool:
    return settings.embedding_write_mode.lower() != "none"


def _hnsw_initial_cap(settings: Settings) -> int:
    if settings.hnsw_initial_cap > 0:
        return int(settings.hnsw_initial_cap)
    return max(100_000, int(settings.seed_target_dishes))


def build_ft_create_args(settings: Settings) -> list[str | bytes]:
    """FT.CREATE … ON HASH … SCHEMA …"""
    args: list[str | bytes] = [
        "FT.CREATE",
        settings.index_name,
        "ON",
        "HASH",
        "PREFIX",
        "1",
        settings.key_prefix,
        "SCHEMA",
        "item_name",
        "TEXT",
        "WEIGHT",
        "5",
        "item_description",
        "TEXT",
        "WEIGHT",
        "2",
        "store_name",
        "TEXT",
        "WEIGHT",
        "2",
        "retrieval_snippet",
        "TEXT",
        "WEIGHT",
        "1",
        "category",
        "TAG",
        "price",
        "NUMERIC",
        "location",
        "GEO",
    ]
    if _use_vector(settings):
        vtype = (settings.vector_index_type or "hnsw").lower()
        if vtype == "flat":
            args += [
                "embedding",
                "VECTOR",
                "FLAT",
                "6",
                "TYPE",
                "FLOAT32",
                "DIM",
                str(settings.embedding_dim),
                "DISTANCE_METRIC",
                "COSINE",
            ]
        else:
            cap = _hnsw_initial_cap(settings)
            args += [
                "embedding",
                "VECTOR",
                "HNSW",
                "12",
                "TYPE",
                "FLOAT32",
                "DIM",
                str(settings.embedding_dim),
                "DISTANCE_METRIC",
                "COSINE",
                "M",
                str(int(settings.hnsw_m)),
                "EF_CONSTRUCTION",
                str(int(settings.hnsw_ef_construction)),
                "INITIAL_CAP",
                str(cap),
            ]
    return args


def ensure_index(settings: Settings | None = None) -> dict[str, Any]:
    """Create index if missing. Returns status dict."""
    settings = settings or get_settings()
    r = get_redis()
    try:
        r.execute_command("FT.INFO", settings.index_name)
        return {"ok": True, "action": "exists", "index": settings.index_name}
    except ResponseError as e:
        err = str(e).lower()
        if "unknown" not in err and "no such index" not in err:
            raise
    args = build_ft_create_args(settings)
    r.execute_command(*args)
    return {
        "ok": True,
        "action": "created",
        "index": settings.index_name,
        "vector": _use_vector(settings),
        "vector_index": (settings.vector_index_type or "hnsw").lower() if _use_vector(settings) else None,
    }


def drop_index(delete_documents: bool = False, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    r = get_redis()
    if delete_documents:
        r.execute_command("FT.DROPINDEX", settings.index_name, "DD")
    else:
        r.execute_command("FT.DROPINDEX", settings.index_name)


def ft_info(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    r = get_redis()
    try:
        raw = r.execute_command("FT.INFO", settings.index_name)
    except ResponseError:
        return {"exists": False}
    return {"exists": True, "raw": _pairs_to_dict(raw)}


def _pairs_to_dict(raw: list | tuple) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not isinstance(raw, (list, tuple)):
        return out
    i = 0
    while i < len(raw):
        k = raw[i]
        if isinstance(k, (bytes, bytearray)):
            k = k.decode()
        i += 1
        if i >= len(raw):
            break
        v = raw[i]
        if isinstance(v, (list, tuple)) and v:
            if k == "attributes":
                out[k] = [_pairs_to_dict(block) if isinstance(block, (list, tuple)) else block for block in v]
            elif _looks_like_pairs(v):
                out[k] = _pairs_to_dict(v)
            else:
                out[k] = [_decode_val(x) for x in v]
        else:
            out[k] = _decode_val(v)
        i += 1
    return out


def _looks_like_pairs(v: list | tuple) -> bool:
    if len(v) < 2:
        return False
    return isinstance(v[0], (bytes, str))


def _decode_val(v: Any) -> Any:
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode()
        except UnicodeDecodeError:
            return f"<binary {len(v)} bytes>"
    if isinstance(v, (list, tuple)):
        return [_decode_val(x) for x in v]
    return v
