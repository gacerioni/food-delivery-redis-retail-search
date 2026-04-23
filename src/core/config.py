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
    # RRF WINDOW: how deep each leg contributes to fusion (0 = omit, use server default for 2-arg RRF).
    rrf_window: int = 40
    hybrid_knn: int = 120
    # Optional VSIM KNN EF_RUNTIME (accuracy vs speed). Null = omit (2-arg KNN clause).
    hybrid_knn_ef_runtime: int | None = 128
    default_search_limit: int = 20
    user_geo_default_radius_km: float = 15.0

    fts_weight: float = 0.5
    vss_weight: float = 0.5

    # Strong multilingual dense retrieval (Sentence Transformers). Native dim 1024 (not 2048: few OSS
    # encoders ship 2048+dense+multilingual in ST; this model is a standard quality ceiling).
    embedding_model: str = "intfloat/multilingual-e5-large"
    embedding_dim: int = 1024
    embed_device: str = "cpu"
    embedding_write_mode: str = "all"  # all | sample | none
    # Prefixes for intfloat E5 models: "query: " / "passage: ". Use "none" for models that reject them.
    embedding_instruction_mode: str = "e5"

    seed_target_dishes: int = 500_000
    seed_embed_sample_pct: int = 15
    # Larger chunks = fewer Redis round-trips; seed also batches embeddings per chunk.
    ingest_pipeline_chunk_size: int = 1000

    autocomplete_key: str = "ac:food_dishes"
    autocomplete_max_suggestions: int = 20000
    autocomplete_min_title_len: int = 3

    api_host: str = "0.0.0.0"
    api_port: int = 8686

    allow_index_rebuild: bool = False

    fuzzy_fallback_on_miss: bool = True
    fuzzy_min_token_len: int = 4

    # VECTOR index: hnsw (recommended at scale) or flat (small / debugging).
    vector_index_type: str = "hnsw"
    hnsw_m: int = 24
    hnsw_ef_construction: int = 256
    # 0 = auto: max(100_000, seed_target_dishes)
    hnsw_initial_cap: int = 0


@lru_cache
def get_settings() -> Settings:
    return Settings()
