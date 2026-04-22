"""Central config from environment (see AGENT.md §6)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    redis_url: str = "redis://localhost:6379/0"

    index_name: str = "idx:food_listing"
    key_prefix: str = "dish:"

    rrf_k: int = 10
    hybrid_knn: int = 80
    default_search_limit: int = 20
    user_geo_default_radius_km: float = 15.0

    fts_weight: float = 0.5
    vss_weight: float = 0.5

    embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dim: int = 384
    embed_device: str = "cpu"
    embedding_write_mode: str = "all"  # all | sample | none

    seed_target_dishes: int = 500_000
    seed_embed_sample_pct: int = 15
    # Larger chunks = fewer Redis round-trips; balance with RAM for batched embeddings.
    ingest_pipeline_chunk_size: int = 1000

    autocomplete_key: str = "ac:food_dishes"
    autocomplete_max_suggestions: int = 20000
    autocomplete_min_title_len: int = 3

    api_host: str = "0.0.0.0"
    # Deliberately not 8000/8080 — demo default (Redis 8.6+ story).
    api_port: int = 8686

    allow_index_rebuild: bool = False

    # When strict FTS returns no hits, retry once with RediSearch fuzzy tokens (%word% = ~1 edit).
    # Off on every query: keeps precision and steady-state latency; on miss only: one extra round-trip.
    fuzzy_fallback_on_miss: bool = True
    fuzzy_min_token_len: int = 4


@lru_cache
def get_settings() -> Settings:
    return Settings()
