"""FT.SYNUPDATE for RediSearch index."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from redis.exceptions import ResponseError

from core.config import Settings, get_settings
from data.redis_client import get_redis


def apply_synonym_group(group_id: str, terms: list[str], settings: Settings | None = None) -> None:
    """terms are synonym equivalents (see Redis FT.SYNUPDATE)."""
    settings = settings or get_settings()
    if not terms:
        return
    r = get_redis()
    args: list[str | bytes] = ["FT.SYNUPDATE", settings.index_name, group_id, *terms]
    r.execute_command(*args)


def apply_default_synonyms(settings: Settings | None = None) -> dict[str, Any]:
    """Load packaged PT food synonym groups."""
    settings = settings or get_settings()
    path = Path(__file__).resolve().parent.parent / "data" / "default_synonyms.json"
    if not path.exists():
        return {"ok": False, "error": "missing default_synonyms.json"}
    data = json.loads(path.read_text(encoding="utf-8"))
    groups: list[dict[str, Any]] = data.get("groups", [])
    for g in groups:
        gid = str(g.get("id", ""))
        terms = [str(t) for t in g.get("terms", []) if t]
        if len(terms) >= 2 and gid:
            try:
                apply_synonym_group(gid, terms, settings)
            except ResponseError:
                pass
    return {"ok": True, "groups_applied": len(groups)}
