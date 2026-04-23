"""FT.HYBRID + RRF when vectors exist; else FT.SEARCH."""

from __future__ import annotations

import re
import time
from typing import Any

import redis
from redis.exceptions import ResponseError

from core.config import Settings, get_settings
from data.dishes import get_dishes_by_ids
from data.redis_client import get_redis
from search.embeddings import embed_text_to_bytes, embedding_enabled


def _ft_hybrid_command(
    settings: Settings,
    fts: str,
    qvec: bytes,
    lim: int,
    rk: int,
) -> list[Any]:
    parts: list[Any] = [
        "FT.HYBRID",
        settings.index_name,
        "SEARCH",
        fts,
        "VSIM",
        "@embedding",
        "$query_vec",
    ]
    if settings.hybrid_knn_ef_runtime is not None and int(settings.hybrid_knn_ef_runtime) > 0:
        parts += [
            "KNN",
            "4",
            "K",
            str(settings.hybrid_knn),
            "EF_RUNTIME",
            str(int(settings.hybrid_knn_ef_runtime)),
        ]
    else:
        parts += ["KNN", "2", "K", str(settings.hybrid_knn)]
    parts += ["COMBINE", "RRF"]
    if int(settings.rrf_window) > 0:
        parts += ["4", "WINDOW", str(int(settings.rrf_window)), "CONSTANT", str(rk)]
    else:
        parts += ["2", "CONSTANT", str(rk)]
    parts += [
        "PARAMS",
        "2",
        "query_vec",
        qvec,
        "LIMIT",
        "0",
        str(lim),
    ]
    return parts


def _sanitize_fts_words(q: str) -> str:
    cleaned = re.sub(r"[^\w\s\u00C0-\u024F]", " ", q or "", flags=re.UNICODE)
    words = [w for w in cleaned.split() if w]
    if not words:
        return ""
    return " ".join(words)


def _text_clause_for_fts(q: str, *, fuzzy_tokens: bool, fuzzy_min_len: int) -> str:
    """Plain token string, or RediSearch fuzzy ``%token%`` (Levenshtein ~1) per long token."""
    w = _sanitize_fts_words(q)
    if not w:
        return ""
    if not fuzzy_tokens:
        return w
    out: list[str] = []
    for t in w.split():
        if len(t) >= fuzzy_min_len:
            out.append(f"%{t}%")
        else:
            out.append(t)
    return " ".join(out)


def build_fts_clause(
    q: str,
    lat: float | None,
    lon: float | None,
    radius_km: float,
    category: str | None,
    *,
    fuzzy_tokens: bool = False,
    fuzzy_min_len: int = 4,
) -> str:
    """Build FT.SEARCH / FT.HYBRID SEARCH string.

    RediSearch rejects ``* @field:...`` (Syntax error near field). If there are no
    textual terms, omit ``*`` and rely on @category / @location alone, or ``*``
    only when there is no filter at all.
    """
    parts: list[str] = []
    w = _text_clause_for_fts(q, fuzzy_tokens=fuzzy_tokens, fuzzy_min_len=fuzzy_min_len)
    if w:
        parts.append(w)
    has_cat = bool(category and category.strip())
    has_geo = lat is not None and lon is not None
    if not w:
        if not has_cat and not has_geo:
            parts.append("*")
    if has_cat:
        esc = category.strip().replace("\\", "\\\\").replace(",", "\\,")  # type: ignore[union-attr]
        parts.append(f"@category:{{{esc}}}")
    if has_geo:
        parts.append(f"@location:[{lon} {lat} {radius_km} km]")
    return " ".join(parts)


def _b(x: Any) -> str:
    if isinstance(x, bytes):
        return x.decode()
    return str(x)


def _parse_hybrid_rows(result: Any) -> list[tuple[str, float]]:
    rows: list[tuple[str, float]] = []
    if not isinstance(result, (list, tuple)) or len(result) < 2:
        return rows
    body: Any = None
    if len(result) > 3 and isinstance(result[3], (list, tuple)):
        body = result[3]
    elif len(result) > 1 and isinstance(result[1], (list, tuple)):
        body = result[1]
    if not isinstance(body, (list, tuple)):
        return rows
    for item in body:
        if not isinstance(item, (list, tuple)):
            continue
        doc_key: str | None = None
        score = 0.0
        for i in range(0, len(item), 2):
            if i + 1 >= len(item):
                break
            field = _b(item[i])
            val = item[i + 1]
            if isinstance(val, bytes):
                try:
                    val = val.decode()
                except UnicodeDecodeError:
                    val = str(val)
            else:
                val = str(val)
            if field == "__key":
                doc_key = val
            elif field == "__score":
                try:
                    score = float(val)
                except (TypeError, ValueError):
                    score = 0.0
        if doc_key:
            rows.append((doc_key, score))
    return rows


def _parse_ft_search_rows(result: Any) -> list[tuple[str, float]]:
    """Parse FT.SEARCH … WITHSCORES … RETURN (optional)."""
    rows: list[tuple[str, float]] = []
    if not isinstance(result, (list, tuple)) or len(result) < 2:
        return rows
    try:
        int(result[0])
    except (TypeError, ValueError):
        return rows
    i = 1
    while i < len(result):
        docid = _b(result[i])
        i += 1
        score = 1.0
        if i < len(result) and not isinstance(result[i], (list, tuple)):
            try:
                score = float(_b(result[i]))
            except (TypeError, ValueError):
                score = 1.0
            i += 1
        if i < len(result) and isinstance(result[i], (list, tuple)):
            i += 1
        rows.append((docid, score))
    return rows


def _fts_search_only(
    r: redis.Redis,
    settings: Settings,
    fts: str,
    lim: int,
    meta: dict[str, Any],
    t0: float,
) -> list[tuple[str, float]]:
    raw = r.execute_command(
        "FT.SEARCH",
        settings.index_name,
        fts,
        "WITHSCORES",
        "LIMIT",
        "0",
        str(lim),
    )
    meta["redis_search_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    return _parse_ft_search_rows(raw)


def hybrid_search(
    q: str,
    *,
    lat: float | None = None,
    lon: float | None = None,
    radius_km: float | None = None,
    category: str | None = None,
    limit: int | None = None,
    rrf_k: int | None = None,
    settings: Settings | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    settings = settings or get_settings()
    r = get_redis()
    lim = limit if limit is not None else settings.default_search_limit
    rk = rrf_k if rrf_k is not None else settings.rrf_k
    rad = radius_km if radius_km is not None else settings.user_geo_default_radius_km

    meta: dict[str, Any] = {
        "mode": "hybrid",
        "query": q or "",
        "category_filter": category or "",
        "geo_active": lat is not None and lon is not None,
        "embedding_ms": 0.0,
        "redis_search_ms": 0.0,
        "total_ms": 0.0,
        "fts_weight": settings.fts_weight,
        "vss_weight": settings.vss_weight,
        "rrf_k": rk,
        "hybrid_knn": settings.hybrid_knn,
        "rrf_window": settings.rrf_window,
        "hybrid_knn_ef_runtime": settings.hybrid_knn_ef_runtime,
    }

    fts_strict = build_fts_clause(q, lat, lon, rad, category)
    fts_fuzzy = build_fts_clause(
        q,
        lat,
        lon,
        rad,
        category,
        fuzzy_tokens=True,
        fuzzy_min_len=settings.fuzzy_min_token_len,
    )
    can_fuzzy_retry = bool(
        settings.fuzzy_fallback_on_miss
        and _sanitize_fts_words(q)
        and fts_fuzzy != fts_strict
    )
    t_all = time.perf_counter()

    def _run_hybrid(fts: str) -> tuple[list[tuple[str, float]], float]:
        t0 = time.perf_counter()
        raw = r.execute_command(*_ft_hybrid_command(settings, fts, qvec, lim, rk))
        ms = round((time.perf_counter() - t0) * 1000, 2)
        return _parse_hybrid_rows(raw), ms

    if not embedding_enabled(settings):
        meta["mode"] = "fts_geo"
        t0 = time.perf_counter()
        try:
            rows = _fts_search_only(r, settings, fts_strict, lim, meta, t0)
        except ResponseError as e:
            meta["error"] = str(e)
            meta["total_ms"] = round((time.perf_counter() - t_all) * 1000, 2)
            return [], meta
        redis_ms = meta["redis_search_ms"]
        if not rows and can_fuzzy_retry:
            t1 = time.perf_counter()
            try:
                rows = _fts_search_only(r, settings, fts_fuzzy, lim, meta, t1)
            except ResponseError:
                rows = []
            meta["fuzzy_retry"] = True
            meta["fts_clause_fuzzy"] = fts_fuzzy
            redis_ms += meta["redis_search_ms"]
        meta["redis_search_ms"] = round(redis_ms, 2)
        meta["fts_clause"] = fts_fuzzy if meta.get("fuzzy_retry") else fts_strict
        results = _hydrate_rows(rows, settings)
        meta["total_ms"] = round((time.perf_counter() - t_all) * 1000, 2)
        return results, meta

    embed_q = (q or "").strip() or "comida prato restaurante"
    qvec, emb_ms = embed_text_to_bytes(embed_q, settings, role="query")
    meta["embedding_ms"] = emb_ms

    rows: list[tuple[str, float]]
    redis_ms_total = 0.0
    fts_used = fts_strict
    try:
        rows, redis_ms_total = _run_hybrid(fts_strict)
    except ResponseError as e:
        err = str(e).lower()
        if any(x in err for x in ("hybrid", "vector", "embedding", "vsim")):
            meta["mode"] = "fts_geo_fallback"
            meta["fallback_reason"] = str(e)
            t0 = time.perf_counter()
            try:
                rows = _fts_search_only(r, settings, fts_strict, lim, meta, t0)
            except ResponseError as e2:
                meta["error"] = str(e2)
                meta["redis_search_ms"] = round((time.perf_counter() - t0) * 1000, 2)
                meta["total_ms"] = round((time.perf_counter() - t_all) * 1000, 2)
                return [], meta
            redis_ms_total = meta["redis_search_ms"]
            if not rows and can_fuzzy_retry:
                t1 = time.perf_counter()
                try:
                    rows = _fts_search_only(r, settings, fts_fuzzy, lim, meta, t1)
                except ResponseError:
                    rows = []
                meta["fuzzy_retry"] = True
                meta["fts_clause_fuzzy"] = fts_fuzzy
                redis_ms_total += meta["redis_search_ms"]
            meta["redis_search_ms"] = round(redis_ms_total, 2)
            meta["fts_clause"] = fts_fuzzy if meta.get("fuzzy_retry") else fts_strict
            results = _hydrate_rows(rows, settings)
            meta["total_ms"] = round((time.perf_counter() - t_all) * 1000, 2)
            return results, meta
        t_err = time.perf_counter()
        meta["error"] = str(e)
        meta["redis_search_ms"] = round((t_err - t_all) * 1000, 2)
        meta["total_ms"] = round((t_err - t_all) * 1000, 2)
        return [], meta

    if not rows and can_fuzzy_retry:
        try:
            rows, ms2 = _run_hybrid(fts_fuzzy)
            redis_ms_total += ms2
            meta["fuzzy_retry"] = True
            meta["fts_clause_fuzzy"] = fts_fuzzy
            fts_used = fts_fuzzy
        except ResponseError:
            pass

    meta["redis_search_ms"] = round(redis_ms_total, 2)
    meta["fts_clause"] = fts_used
    results = _hydrate_rows(rows, settings)
    meta["total_ms"] = round((time.perf_counter() - t_all) * 1000, 2)
    return results, meta


def _hydrate_rows(rows: list[tuple[str, float]], settings: Settings) -> list[dict[str, Any]]:
    order: list[tuple[str, str, float]] = []
    for redis_key, score in rows:
        rk = redis_key.decode() if isinstance(redis_key, bytes) else str(redis_key)
        suffix = rk[len(settings.key_prefix) :] if rk.startswith(settings.key_prefix) else rk
        order.append((rk, suffix, score))
    unique_ids = list(dict.fromkeys(s for _, s, _ in order))
    bulk = get_dishes_by_ids(unique_ids, settings)
    out: list[dict[str, Any]] = []
    for rk, suffix, score in order:
        doc0 = bulk.get(suffix)
        if not doc0:
            continue
        doc = dict(doc0)
        doc["_score"] = score
        doc["_redis_key"] = rk
        out.append(doc)
    return out


def indexed_doc_count(settings: Settings | None = None) -> int | None:
    settings = settings or get_settings()
    r = get_redis()
    try:
        raw = r.execute_command(
            "FT.SEARCH",
            settings.index_name,
            "*",
            "LIMIT",
            "0",
            "0",
        )
        if isinstance(raw, (list, tuple)) and raw:
            first = raw[0]
            if isinstance(first, bytes):
                return int(first.decode())
            return int(first)
    except ResponseError:
        return None
    return None
