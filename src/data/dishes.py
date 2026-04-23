"""HASH dish:{uuid} — CRUD + SCAN helpers."""

from __future__ import annotations

import uuid
from typing import Any, Iterator

from redis.exceptions import ResponseError

from core.config import Settings, get_settings
from data.redis_client import get_redis


def dish_key(dish_id: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    return f"{settings.key_prefix}{dish_id}"


def _decode_hash(data: dict[Any, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in data.items():
        kb = k.decode() if isinstance(k, bytes) else k
        if kb == "embedding" and isinstance(v, (bytes, bytearray)):
            continue
        if isinstance(v, (bytes, bytearray)):
            try:
                out[kb] = v.decode("utf-8")
            except UnicodeDecodeError:
                out[kb] = None
        else:
            out[kb] = v
    return out


def _enrich_lat_lon_from_location(doc: dict[str, Any]) -> None:
    """GEO is stored only as `location` (lon,lat). API adds floats for clients that need a map."""
    loc = doc.get("location")
    if not loc or not isinstance(loc, str):
        return
    parts = [p.strip() for p in loc.split(",")]
    if len(parts) != 2:
        return
    try:
        doc["longitude"] = float(parts[0])
        doc["latitude"] = float(parts[1])
    except ValueError:
        pass


def get_dish(dish_id: str, settings: Settings | None = None) -> dict[str, Any] | None:
    r = get_redis()
    raw = r.hgetall(dish_key(dish_id, settings))
    if not raw:
        return None
    d = _decode_hash(raw)
    d["id"] = dish_id
    _enrich_lat_lon_from_location(d)
    return d


def get_dishes_by_ids(dish_ids: list[str], settings: Settings | None = None) -> dict[str, dict[str, Any]]:
    """Pipeline ``HGETALL`` for search hydration (one round-trip vs N)."""
    settings = settings or get_settings()
    if not dish_ids:
        return {}
    r = get_redis()
    pipe = r.pipeline(transaction=False)
    for did in dish_ids:
        pipe.hgetall(dish_key(did, settings))
    rows = pipe.execute()
    out: dict[str, dict[str, Any]] = {}
    for did, raw in zip(dish_ids, rows):
        if not raw:
            continue
        d = _decode_hash(raw)
        d["id"] = did
        _enrich_lat_lon_from_location(d)
        out[did] = d
    return out


def delete_dish(dish_id: str, settings: Settings | None = None) -> bool:
    r = get_redis()
    n = r.delete(dish_key(dish_id, settings))
    return bool(n)


def save_dish(
    fields: dict[str, Any],
    dish_id: str | None = None,
    settings: Settings | None = None,
) -> str:
    """HSET dish fields. Returns dish id (from arg or new uuid)."""
    settings = settings or get_settings()
    did = dish_id or str(uuid.uuid4())
    key = dish_key(did, settings)
    r = get_redis()
    mapping: dict[str | bytes, str | bytes] = {}
    for k, v in fields.items():
        if v is None:
            continue
        if k == "id":
            continue
        if k == "embedding" and isinstance(v, bytes):
            mapping[k] = v
        else:
            mapping[k] = str(v)
    if mapping:
        r.hset(key, mapping=mapping)
    return did


def scan_dish_keys(
    count: int = 500,
    settings: Settings | None = None,
) -> Iterator[str]:
    settings = settings or get_settings()
    r = get_redis()
    prefix = settings.key_prefix.encode()
    cur = b"0"
    while True:
        cur, keys = r.scan(cur, match=prefix + b"*", count=count)
        for k in keys:
            if isinstance(k, bytes):
                ks = k.decode()
            else:
                ks = str(k)
            yield ks
        if cur in (0, b"0"):
            break


def count_dishes(settings: Settings | None = None) -> int:
    return sum(1 for _ in scan_dish_keys(settings=settings))


def delete_all_dishes(settings: Settings | None = None) -> int:
    """SCAN + unlink batches. Returns deleted key count."""
    settings = settings or get_settings()
    r = get_redis()
    deleted = 0
    batch: list[str | bytes] = []
    for key in scan_dish_keys(settings=settings):
        batch.append(key)
        if len(batch) >= 500:
            deleted += r.unlink(*batch)
            batch.clear()
    if batch:
        deleted += r.unlink(*batch)
    return deleted


def dish_ids_page(limit: int = 50, settings: Settings | None = None) -> list[str]:
    settings = settings or get_settings()
    p = settings.key_prefix
    out: list[str] = []
    for key in scan_dish_keys(settings=settings):
        if key.startswith(p):
            out.append(key[len(p) :])
        if len(out) >= limit:
            break
    return out


def suggest_remove(autocomplete_key: str, title: str) -> None:
    try:
        get_redis().execute_command("FT.SUGDEL", autocomplete_key, title)
    except ResponseError:
        pass
