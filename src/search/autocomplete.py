"""FT.SUGADD / FT.SUGGET for dish titles."""

from __future__ import annotations

from redis.exceptions import ResponseError

from core.config import Settings, get_settings
from data.redis_client import get_redis


def suggest_add(title: str, score: float = 1.0, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    t = (title or "").strip()
    if len(t) < settings.autocomplete_min_title_len:
        return
    r = get_redis()
    try:
        r.execute_command("FT.SUGADD", settings.autocomplete_key, t, str(score))
    except ResponseError:
        pass


def suggest_get(prefix: str, limit: int = 10, settings: Settings | None = None) -> list[str]:
    settings = settings or get_settings()
    r = get_redis()
    try:
        raw = r.execute_command(
            "FT.SUGGET",
            settings.autocomplete_key,
            prefix,
            "MAX",
            str(limit),
            "WITHSCORES",
        )
    except ResponseError:
        return []
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[str] = []
    i = 0
    while i < len(raw):
        s = raw[i]
        if isinstance(s, bytes):
            s = s.decode()
        out.append(str(s))
        i += 2 if i + 1 < len(raw) else 1
    return out


def suggest_rebuild_from_keys(settings: Settings | None = None) -> int:
    """Clear suggestion key by deleting it, then re-add from SCAN (MVP: cap)."""
    settings = settings or get_settings()
    r = get_redis()
    r.delete(settings.autocomplete_key)
    from data.dishes import scan_dish_keys, get_dish

    n = 0
    seen: set[str] = set()
    for key in scan_dish_keys(settings=settings):
        if n >= settings.autocomplete_max_suggestions:
            break
        suffix = key[len(settings.key_prefix) :] if key.startswith(settings.key_prefix) else key
        doc = get_dish(suffix, settings)
        if not doc:
            continue
        title = (doc.get("item_name") or "").strip()
        if not title or title in seen:
            continue
        seen.add(title)
        suggest_add(title, settings=settings)
        n += 1
    return n
