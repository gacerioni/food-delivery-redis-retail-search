#!/usr/bin/env python3
"""Console benchmark: hybrid_search (needs Redis, index, seeded data).

  PYTHONPATH=src python scripts/benchmark_search.py
  # or from repo root with uv:
  uv run python scripts/benchmark_search.py
"""

from __future__ import annotations

import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.join(ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "src"))


def main() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(ROOT, ".env"))
    except ImportError:
        pass

    from core.config import get_settings
    from search.embeddings import reset_embedding_model
    from search.hybrid import hybrid_search

    get_settings.cache_clear()
    reset_embedding_model()

    cases: list[tuple[str, float | None, float | None, str | None]] = [
        ("pizza margherita", None, None, None),
        ("estrogonofe frango", None, None, None),
        ("smash burger duplo", None, None, None),
        ("açaí granola morango", None, None, None),
        ("sushi salmão combo", None, None, None),
        ("", -23.56, -46.66, None),
        ("marmitex", -23.56, -46.66, "Brasileira"),
    ]

    # Warmup (model load + Redis)
    hybrid_search("warmup pizza", limit=5)

    rows: list[tuple[str, float, int, str]] = []
    for q, la, lo, cat in cases:
        label = (q or "<geo>").replace("\n", " ")[:48]
        t0 = time.perf_counter()
        results, meta = hybrid_search(
            q,
            lat=la,
            lon=lo,
            category=cat,
            limit=20,
        )
        wall = (time.perf_counter() - t0) * 1000
        total = float(meta.get("total_ms") or 0)
        n = len(results)
        mode = str(meta.get("mode") or "")
        rows.append((label, wall, n, mode))
        print(
            f"{label:50}  wall={wall:7.1f}ms  meta_total={total:6.1f}ms  n={n:2}  mode={mode}"
            + ("  fuzzy" if meta.get("fuzzy_retry") else "")
        )

    walls = [r[1] for r in rows]
    print()
    print(
        "wall ms: p50=",
        round(statistics.median(walls), 1),
        " mean=",
        round(statistics.mean(walls), 1),
        sep="",
    )


if __name__ == "__main__":
    main()
