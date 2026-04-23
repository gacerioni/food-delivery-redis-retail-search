"""Smoke tests against a local Redis (docker compose)."""

from __future__ import annotations

import os

import pytest
import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


@pytest.fixture
def redis_client():
    r = redis.from_url(REDIS_URL, decode_responses=False)
    try:
        r.ping()
    except redis.exceptions.ConnectionError:
        pytest.skip("Redis not reachable at " + REDIS_URL)
    yield r
    r.close()


def test_ft_create_and_search_hash(redis_client):
    from core.config import Settings
    from data.food_index import build_ft_create_args, drop_index

    idx = "idx:test_food_smoke"
    prefix = "tdish:"
    s = Settings(
        redis_url=REDIS_URL,
        index_name=idx,
        key_prefix=prefix,
        embedding_write_mode="none",
    )
    r = redis_client
    try:
        r.execute_command("FT.DROPINDEX", idx)
    except redis.exceptions.ResponseError:
        pass
    args = build_ft_create_args(s)
    r.execute_command(*args)
    key = prefix + "1"
    r.delete(key)
    r.hset(
        key,
        mapping={
            b"item_name": b"pizza margherita",
            b"item_description": b"mussarela e manjericao",
            b"store_name": b"Pizzaria Smoke",
            b"retrieval_snippet": b"forno napolitana delivery",
            b"category": b"Pizza",
            b"price": b"49.90",
            b"location": b"-46.63,-23.55",
        },
    )
    res = r.execute_command("FT.SEARCH", idx, "pizza", "LIMIT", "0", "5")
    assert isinstance(res, (list, tuple))
    assert int(res[0]) >= 1
    r.delete(key)
    try:
        drop_index(settings=s)
    except redis.exceptions.ResponseError:
        r.execute_command("FT.DROPINDEX", idx)


def test_build_fts_clause_geo_no_star_with_wildcard_text():
    """RediSearch does not accept ``* @location:[...]`` — geo-only must omit ``*``."""
    from search.hybrid import build_fts_clause

    q = build_fts_clause("*", -23.16003, -46.55620, 15.0, None)
    assert q.startswith("@location:[")
    assert "*" not in q
    assert q.endswith(" km]")


def test_build_fts_clause_empty_is_star_only():
    from search.hybrid import build_fts_clause

    assert build_fts_clause("", None, None, 15.0, None) == "*"


def test_build_fts_clause_text_plus_geo():
    from search.hybrid import build_fts_clause

    q = build_fts_clause("pizza", -23.16, -46.55, 10.0, None)
    assert q.startswith("pizza ")
    assert "@location:[-46.55 -23.16 10.0 km]" in q


def test_embed_many_to_bytes_empty():
    from search.embeddings import embed_many_to_bytes

    out, ms = embed_many_to_bytes([])
    assert out == [] and ms == 0.0


def test_build_fts_clause_category_only_no_star():
    from search.hybrid import build_fts_clause

    q = build_fts_clause("", None, None, 15.0, "Pizza")
    assert q == "@category:{Pizza}"
    assert "*" not in q


def test_build_fts_clause_fuzzy_retry_differs_from_strict():
    from search.hybrid import build_fts_clause

    strict = build_fts_clause("pitza napolitana", None, None, 15.0, None)
    fuzzy = build_fts_clause(
        "pitza napolitana",
        None,
        None,
        15.0,
        None,
        fuzzy_tokens=True,
        fuzzy_min_len=4,
    )
    assert "pitza" in strict and "%pitza%" in fuzzy
    assert "napolitana" in strict and "%napolitana%" in fuzzy


def test_build_fts_clause_fuzzy_short_token_unwrapped():
    from search.hybrid import build_fts_clause

    fuzzy = build_fts_clause(
        "xi salada",
        None,
        None,
        15.0,
        None,
        fuzzy_tokens=True,
        fuzzy_min_len=4,
    )
    assert fuzzy.startswith("xi ")
    assert "%salada%" in fuzzy


def test_api_search_empty(monkeypatch):
    """App loads; search route returns JSON (uses live Redis if up)."""
    monkeypatch.setenv("EMBEDDING_WRITE_MODE", "none")
    from core.config import get_settings
    from data.redis_client import reset_redis

    get_settings.cache_clear()
    reset_redis()
    from fastapi.testclient import TestClient
    from api.main import app

    with TestClient(app) as c:
        r = c.get("/api/search", params={"q": "zzzznotfound12345"})
        assert r.status_code == 200
        body = r.json()
        assert "results" in body and "meta" in body
