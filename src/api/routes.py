"""HTTP API for search, admin, observability."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from core.config import get_settings
from data.dishes import delete_dish, dish_ids_page, get_dish, save_dish, suggest_remove
from data.food_index import drop_index, ensure_index, ft_info
from data.redis_client import get_redis
from search.autocomplete import suggest_add, suggest_get, suggest_rebuild_from_keys
from search.hybrid import hybrid_search, indexed_doc_count
from search.synonyms import apply_default_synonyms
from seed.catalog import CATEGORIES, seed_dishes

router = APIRouter()


@router.get("/api/search")
def api_search(
    q: str = "",
    lat: float | None = None,
    lon: float | None = None,
    radius_km: float | None = None,
    category: str | None = None,
    limit: int | None = None,
    rrf_k: int | None = None,
) -> dict[str, Any]:
    results, meta = hybrid_search(
        q,
        lat=lat,
        lon=lon,
        radius_km=radius_km,
        category=category,
        limit=limit,
        rrf_k=rrf_k,
    )
    return {"results": results, "meta": meta}


@router.get("/api/autocomplete")
def api_autocomplete(q: str = "", limit: int = 8) -> dict[str, list[str]]:
    s = get_settings()
    return {"suggestions": suggest_get(q, limit=limit, settings=s)}


@router.get("/api/categories")
def api_categories() -> dict[str, list[str]]:
    return {"categories": list(CATEGORIES)}


@router.get("/api/observability")
def api_observability() -> dict[str, Any]:
    s = get_settings()
    r = get_redis()
    mem = None
    try:
        mem = r.info("memory")
    except Exception as e:
        mem = {"error": str(e)}
    slow = None
    try:
        slow = r.slowlog_get(8)
    except Exception as e:
        slow = {"error": str(e)}
    dbsize = r.dbsize()
    idx = ft_info(s)
    approx = indexed_doc_count(s)
    redis_version = None
    try:
        srv = r.info("server")
        if isinstance(srv, dict):
            rv = srv.get(b"redis_version", srv.get("redis_version"))
            redis_version = rv.decode() if isinstance(rv, bytes) else rv
    except Exception:
        pass
    return {
        "redis": {
            "dbsize": dbsize,
            "version": redis_version,
            "memory": _decode_redis_info(mem),
            "slowlog": _decode_slowlog(slow),
        },
        "index": idx,
        "indexed_doc_count": approx,
        "config": {
            "index_name": s.index_name,
            "key_prefix": s.key_prefix,
            "embedding_model": s.embedding_model,
            "embedding_write_mode": s.embedding_write_mode,
            "embedding_dim": s.embedding_dim,
            "embedding_instruction_mode": s.embedding_instruction_mode,
            "vector_index_type": s.vector_index_type,
            "hybrid_knn": s.hybrid_knn,
            "hybrid_knn_ef_runtime": s.hybrid_knn_ef_runtime,
            "rrf_k": s.rrf_k,
            "rrf_window": s.rrf_window,
        },
    }


def _decode_redis_info(mem: Any) -> Any:
    if not isinstance(mem, dict):
        return mem
    out: dict[str, Any] = {}
    for k, v in mem.items():
        kb = k.decode() if isinstance(k, bytes) else k
        if isinstance(v, bytes):
            try:
                out[kb] = v.decode()
            except UnicodeDecodeError:
                out[kb] = repr(v)
        else:
            out[kb] = v
    return out


def _decode_slowlog(entries: Any) -> Any:
    if not isinstance(entries, (list, tuple)):
        return entries
    out: list[Any] = []
    for e in entries:
        if isinstance(e, dict):
            row: dict[str, Any] = {}
            for k, v in e.items():
                kk = k.decode() if isinstance(k, bytes) else str(k)
                if isinstance(v, bytes):
                    try:
                        row[kk] = v.decode()
                    except UnicodeDecodeError:
                        row[kk] = repr(v)
                elif isinstance(v, (list, tuple)):
                    row[kk] = [x.decode() if isinstance(x, bytes) else x for x in v]
                else:
                    row[kk] = v
            out.append(row)
        else:
            out.append(e)
    return out


class SeedBody(BaseModel):
    count: int | None = None
    replace: bool = False


@router.post("/admin/api/seed/run")
def admin_seed(body: SeedBody | None = None) -> dict[str, Any]:
    b = body or SeedBody()
    return seed_dishes(b.count, replace=b.replace)


class DishCreate(BaseModel):
    item_name: str
    item_description: str = ""
    store_name: str
    category: str = "Brasileira"
    price: str = "29.90"
    latitude: float = Field(default=-23.55, description="Degrees; stored only inside GEO `location`")
    longitude: float = Field(default=-46.63, description="Degrees; stored only inside GEO `location`")
    retrieval_snippet: str | None = Field(
        default=None,
        description="Optional extra TEXT for BM25 + embedding; auto from category if empty.",
    )
    item_id: str | None = None
    store_id: str | None = None


@router.get("/admin/api/dishes")
def admin_list_dishes(limit: int = Query(80, le=500)) -> dict[str, Any]:
    ids = dish_ids_page(limit, settings=get_settings())
    items = []
    for did in ids:
        d = get_dish(did)
        if d:
            items.append(d)
    return {"items": items, "truncated": len(ids) >= limit}


@router.get("/admin/api/dishes/{dish_id}")
def admin_get_dish(dish_id: str) -> dict[str, Any]:
    d = get_dish(dish_id)
    if not d:
        raise HTTPException(404, "dish not found")
    return d


@router.post("/admin/api/dishes")
def admin_create_dish(body: DishCreate) -> dict[str, Any]:
    from search.dish_text import dish_embedding_text
    from search.embeddings import embed_text_to_bytes, embedding_enabled

    s = get_settings()
    rs = (body.retrieval_snippet or "").strip()
    if not rs:
        rs = f"{body.category.lower()} delivery prato restaurante caseiro"
    fields: dict[str, Any] = {
        "item_id": body.item_id or "",
        "store_id": body.store_id or "",
        "item_name": body.item_name,
        "item_description": body.item_description,
        "store_name": body.store_name,
        "category": body.category,
        "price": body.price,
        "location": f"{body.longitude},{body.latitude}",
        "retrieval_snippet": rs,
    }
    did = save_dish(fields, settings=s)
    if embedding_enabled(s):
        text = dish_embedding_text(
            body.item_name,
            body.item_description,
            body.category,
            body.store_name,
            retrieval_snippet=rs,
        )
        blob, _ = embed_text_to_bytes(text, s, role="passage")
        save_dish({"embedding": blob}, dish_id=did, settings=s)
    suggest_add(body.item_name, settings=s)
    return {"id": did, "ok": True}


@router.delete("/admin/api/dishes/{dish_id}")
def admin_delete_dish(dish_id: str) -> dict[str, Any]:
    d = get_dish(dish_id)
    if d:
        suggest_remove(get_settings().autocomplete_key, d.get("item_name") or "")
    ok = delete_dish(dish_id)
    if not ok:
        raise HTTPException(404, "dish not found")
    return {"ok": True}


@router.post("/admin/api/index/rebuild")
def admin_rebuild_index() -> dict[str, Any]:
    s = get_settings()
    if not s.allow_index_rebuild:
        raise HTTPException(403, "set ALLOW_INDEX_REBUILD=true to drop/recreate index")
    drop_index(delete_documents=False, settings=s)
    st = ensure_index(s)
    n = suggest_rebuild_from_keys(s)
    return {"ok": True, "index": st, "autocomplete_rebuilt": n}


@router.post("/admin/api/synonyms/apply-default")
def admin_synonyms_default() -> dict[str, Any]:
    return apply_default_synonyms()
