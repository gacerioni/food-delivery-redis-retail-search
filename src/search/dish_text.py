"""Deterministic text for embeddings (AGENT.md §4)."""

from __future__ import annotations

MAX_CHARS = 2000


def dish_embedding_text(
    item_name: str,
    item_description: str,
    category: str,
    store_name: str,
) -> str:
    parts: list[str] = []
    n = (item_name or "").strip()
    d = (item_description or "").strip()
    c = (category or "").strip()
    s = (store_name or "").strip()
    if n:
        parts.append(f"Prato: {n}")
    if d:
        parts.append(f"Descrição: {d}")
    if c:
        parts.append(f"Categoria: {c}")
    if s:
        parts.append(f"Restaurante: {s}")
    text = "\n".join(parts) if parts else "item"
    text = " ".join(text.split())
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
    return text
