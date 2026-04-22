"""Faker-driven dish HASH documents for Brazil-ish demo data."""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from typing import Any

from faker import Faker

from core.config import Settings, get_settings
from data.dishes import dish_key, delete_all_dishes, save_dish
from data.redis_client import get_redis
from search.autocomplete import suggest_add
from search.dish_text import dish_embedding_text
from search.embeddings import embed_many_to_bytes, embed_text_to_bytes, embedding_enabled


@dataclass
class DishDraft:
    item_id: str
    store_id: str
    item_name: str
    item_description: str
    store_name: str
    category: str
    price: str
    lat: float
    lon: float


def _faker_locale() -> Faker:
    try:
        return Faker("pt_BR")
    except Exception:
        return Faker()


CATEGORIES = [
    "Pizza",
    "Hambúrguer",
    "Japonesa",
    "Brasileira",
    "Doces",
    "Açaí",
    "Bebidas",
    "Padaria",
    "Árabe",
    "Italiana",
]

_BAIRROS = [
    "Pinheiros",
    "Vila Madalena",
    "Moema",
    "Liberdade",
    "Centro",
    "Tatuapé",
    "Lapa",
    "Copacabana",
    "Botafogo",
    "Savassi",
]

_VIBE = [
    "daquele jeito",
    "sem frescura",
    "fitness mente / comfort food corpo",
    "o chef tá inspirado",
    "pediu, chegou quente",
    "desde 2019 enganando delivery app",
]

_HOOKS = [
    "Vem com molho da casa e zero drama.",
    "Acompanha aquele arroz soltinho que a gente sabe que você quer.",
    "Ideal pra maratonar série e fingir que amanhã volta a dieta.",
    "Crocante por fora, drama por dentro.",
    "Se sobrar, vira café da manhã — mas não vai sobrar.",
]


def _store_name(fk: Faker) -> str:
    base = random.choice(
        [
            fk.company(),
            f"{fk.last_name()} & {fk.last_name()}",
            f"Casa do {fk.word().title()}",
            f"{fk.word().title()} Cozinha",
        ]
    )
    suf = random.choice(["Delivery", "Express", "no Box", "Kitchen", "Go", ""])
    bairro = random.choice(_BAIRROS)
    return f"{base} {suf}".strip() + f" · {bairro}"


def _dish_name(cat: str, fk: Faker) -> str:
    adj = random.choice(
        ["Supremo", "Da casa", "Turbinado", "Clássico", "Ninja", "Raiz", "Fit-ish", "Comfort"]
    )
    dish_templates = {
        "Pizza": lambda: random.choice(
            [
                f"Pizza {adj} {fk.word().title()} — borda {random.choice(['catupiry', 'cheddar', 'sem borda (respeito)'])}",
                f"Calzone {fk.word().title()} recheado de {random.choice(['presunto', 'ricota', 'esperança'])}",
                f"Pinsa romana {fk.word().title()} (sim, é diferente de pizza — confia)",
            ]
        ),
        "Hambúrguer": lambda: random.choice(
            [
                f"{random.choice(['Smash', 'Smash duplo', 'Artesanal'])} {fk.word().title()} + bacon {random.choice(['crocante', 'bem passado', 'na medida'])}",
                f"Burger {adj} com maionese trufada (ou de saquinho, depende do dia)",
                f"Duplo cheddar derretendo — pão brioche e {random.choice(['cebola caramelizada', 'picles', 'jalapeño'])}",
            ]
        ),
        "Japonesa": lambda: random.choice(
            [
                f"Combo {random.choice(['32', '40', '52'])} peças — {random.choice(['salmão', 'mix', 'só hot'])}",
                f"Temaki {random.choice(['salmão', 'skin', 'philadelphia'])} gigante (modo tartaruga)",
                f"Hot roll {fk.word().title()} com cream cheese e culpa leve",
                f"Yakisoba {random.choice(['misto', 'frango', 'carne'])} — porção de guerra",
            ]
        ),
        "Brasileira": lambda: random.choice(
            [
                f"Feijoada {random.choice(['completa', 'light (oxímoro)', 'sábado de resenha'])}",
                f"PF {random.choice(['churrasco', 'contrafilé', 'costela'])} + farofa que decide o jogo",
                f"Moqueca de {random.choice(['peixe', 'camarão', 'mistão'])} com dendê na veia",
                f"Frango à parmegiana — {random.choice(['tamanho família', 'individual heróico'])}",
            ]
        ),
        "Doces": lambda: random.choice(
            [
                f"Brownie {random.choice(['nervoso', 'com nutella', 'zero açúcar (quase)'])}",
                f"Pudim de leite condensado — fatia que desafia a física",
                f"Torta holandesa {adj}",
                f"Brigadeiro gourmet {random.choice(['meio amargo', 'belga', 'de panela'])}",
            ]
        ),
        "Açaí": lambda: random.choice(
            [
                f"Açaí {random.choice(['500ml', '700ml', 'tigela'])} + {random.choice(['granola', 'paçoca', 'leite ninho', 'morango'])}",
                f"Bowl tropical com frutas que fingem ser saudáveis",
                f"Açaí premium com topping de {random.choice(['amendoim', 'coco', 'mel'])}",
            ]
        ),
        "Bebidas": lambda: random.choice(
            [
                f"Suco natural {random.choice(['Laranja', 'Acerola', 'Abacaxi com hortelã'])} — copo Americano",
                f"Refrigerante 2L + gelo na moral",
                f"Água com gás importada / nacional braba",
                f"Mate gelado com limão — energia de reunião que poderia ser e-mail",
            ]
        ),
        "Padaria": lambda: random.choice(
            [
                f"Pão na chapa com manteiga {random.choice(['de garrafa', 'clarificada', 'na dose'])}",
                f"Coxinha de {random.choice(['frango', 'catupiry', 'calabresa'])} — massa fininha",
                f"Esfiha {random.choice(['aberta', 'fechada', 'mistério'])}",
                f"Pastel de feira — {random.choice(['carne', 'queijo', 'pizza'])}",
            ]
        ),
        "Árabe": lambda: random.choice(
            [
                f"Kibe {random.choice(['frito', 'assado', 'na airfryer da vó'])}",
                f"Esfiha aberta de {random.choice(['carne', 'queijo', 'calabresa'])}",
                f"Shawarma no pão sírio — {random.choice(['frango', 'carne', 'mistão'])}",
            ]
        ),
        "Italiana": lambda: random.choice(
            [
                f"Lasanha bolonhesa — camadas de {random.choice(['amor', 'queijo', 'carne moída'])}",
                f"Espaguete ao pesto com {random.choice(['parmesão', 'nozes', 'basil fresco'])}",
                f"Risoto de {random.choice(['funghi', 'limão siciliano', 'camarão'])}",
            ]
        ),
    }
    name_fn = dish_templates.get(cat, lambda: fk.catch_phrase()[:60])
    return name_fn()


def _description(cat: str, fk: Faker) -> str:
    if random.random() < 0.35:
        return f"{random.choice(_HOOKS)} {random.choice(_VIBE)} · {cat}."
    return (fk.text(max_nb_chars=220) + " " + random.choice(_HOOKS)).strip()[:280]


def _draft_one(fk: Faker) -> DishDraft:
    cat = random.choice(CATEGORIES)
    store = _store_name(fk)
    name = _dish_name(cat, fk)
    desc = _description(cat, fk)
    lat = -23.5 + random.uniform(-0.35, 0.35)
    lon = -46.65 + random.uniform(-0.35, 0.35)
    price = f"{random.randint(12, 120)}.{random.randint(0, 99):02d}"
    return DishDraft(
        item_id=str(random.randint(10_000_000, 99_999_999)),
        store_id=str(random.randint(1000, 999_999)),
        item_name=name,
        item_description=desc,
        store_name=store,
        category=cat,
        price=price,
        lat=lat,
        lon=lon,
    )


def _should_embed(dish_id: str, settings: Settings) -> bool:
    mode = settings.embedding_write_mode.lower()
    if mode == "none":
        return False
    if mode == "all":
        return True
    h = hash(dish_id) % 100
    return h < settings.seed_embed_sample_pct


def _draft_hash_mapping(d: DishDraft) -> dict[str, Any]:
    loc = f"{d.lon},{d.lat}"
    return {
        "item_id": d.item_id,
        "store_id": d.store_id,
        "item_name": d.item_name,
        "item_description": d.item_description,
        "store_name": d.store_name,
        "category": d.category,
        "price": d.price,
        "location": loc,
    }


def draft_to_hash_fields(d: DishDraft, dish_id: str, settings: Settings) -> dict[str, Any]:
    fields = dict(_draft_hash_mapping(d))
    if embedding_enabled(settings) and _should_embed(dish_id, settings):
        text = dish_embedding_text(d.item_name, d.item_description, d.category, d.store_name)
        blob, _ = embed_text_to_bytes(text, settings)
        fields["embedding"] = blob
    return fields


def _flush_seed_chunk(
    pipe: Any,
    rows: list[tuple[str, DishDraft, str, bool]],
    settings: Settings,
) -> None:
    """Encode all embeddings for this chunk in one model call, then HSET on pipeline."""
    texts: list[str] = []
    for _key, d, did, need_e in rows:
        if need_e:
            texts.append(dish_embedding_text(d.item_name, d.item_description, d.category, d.store_name))
    blobs: list[bytes] = []
    if texts:
        blobs, _ = embed_many_to_bytes(texts, settings)
    bi = 0
    for key, d, did, need_e in rows:
        m = {k: (v if isinstance(v, (bytes, bytearray)) else str(v)) for k, v in _draft_hash_mapping(d).items()}
        if need_e:
            m["embedding"] = blobs[bi]
            bi += 1
        pipe.hset(key, mapping=m)


# Fixed demo SKUs so "strogonoff / estrogonofe" searches always have real rows (Faker rarely emits this word).
_STROGONOFF_DEMOS: list[tuple[str, str, str, str, float, float, str, str]] = [
    (
        "Strogonoff de filé mignon — marmitex 400g",
        "Molho creme, champignon, arroz branco e batata palha separada. Clássico de bistrô.",
        "Cantinho do Filé · Moema",
        "42.90",
        -23.605,
        -46.673,
        "Brasileira",
        "demo-sku-strogo-01",
    ),
    (
        "Estrogonofe de frango da casa",
        "Peito em tiras, ketchup + mostarda na medida; vem com arroz e fritas.",
        "Casa da Vovó Delivery · Tatuapé",
        "31.50",
        -23.541,
        -46.574,
        "Brasileira",
        "demo-sku-strogo-02",
    ),
    (
        "Executivo: bife ao strogonoff + salada",
        "Pedaços macios, molho encorpado; prato fechado para o almoço rápido.",
        "Lanchonete Express Centro",
        "28.90",
        -23.548,
        -46.636,
        "Brasileira",
        "demo-sku-strogo-03",
    ),
    (
        "Strogonoff de cogumelo shimeji (fit-ish)",
        "Sem carne vermelha; creme leve e arroz integral opcional no app.",
        "Green Box Kitchen · Pinheiros",
        "36.00",
        -23.562,
        -46.688,
        "Brasileira",
        "demo-sku-strogo-04",
    ),
    (
        "Kit casal: 2 strogonoffs + guaraná 2L",
        "Monte: 1 frango + 1 carne; embalagem térmica; strogonoff nome forte pra busca demo.",
        "Restaurante Duplo Sabor · Liberdade",
        "89.00",
        -23.570,
        -46.625,
        "Brasileira",
        "demo-sku-strogo-05",
    ),
]


def upsert_strogonoff_demo_dishes(settings: Settings | None = None) -> int:
    """Always (re)write 5 HASH docs under ``dish:demo-strogonoff-NN`` for strogonoff-related demos."""
    settings = settings or get_settings()
    blobs: list[bytes] = []
    if embedding_enabled(settings):
        texts = [
            dish_embedding_text(r[0], r[1], r[6], r[2])
            for r in _STROGONOFF_DEMOS
        ]
        blobs, _ = embed_many_to_bytes(texts, settings)
    n = 0
    for idx, row in enumerate(_STROGONOFF_DEMOS, start=1):
        item_name, desc, store_name, price, lat, lon, category, item_id = row
        did = f"demo-strogonoff-{idx:02d}"
        fields: dict[str, Any] = {
            "item_id": item_id,
            "store_id": "demo-loja-strogo",
            "item_name": item_name,
            "item_description": desc,
            "store_name": store_name,
            "category": category,
            "price": price,
            "location": f"{lon},{lat}",
        }
        if blobs:
            fields["embedding"] = blobs[idx - 1]
        save_dish(fields, dish_id=did, settings=settings)
        suggest_add(item_name, settings=settings)
        n += 1
    return n


def seed_dishes(
    count: int | None = None,
    *,
    replace: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    n = count if count is not None else settings.seed_target_dishes
    if n <= 0:
        stro = upsert_strogonoff_demo_dishes(settings)
        return {
            "created": 0,
            "removed_previous_keys": 0,
            "autocomplete_seeded": 0,
            "embedding_mode": settings.embedding_write_mode,
            "strogonoff_demo_upserted": stro,
        }
    r = get_redis()
    fk = _faker_locale()

    removed = 0
    if replace:
        removed = delete_all_dishes(settings)

    pipe = r.pipeline(transaction=False)
    created = 0
    chunk = max(1, settings.ingest_pipeline_chunk_size)
    embed_on = embedding_enabled(settings)
    chunk_rows: list[tuple[str, DishDraft, str, bool]] = []
    ac_titles: list[str] = []
    seen_ac: set[str] = set()

    def maybe_record_ac(d: DishDraft) -> None:
        if len(ac_titles) >= settings.autocomplete_max_suggestions:
            return
        t = (d.item_name or "").strip()
        if len(t) >= settings.autocomplete_min_title_len and t not in seen_ac:
            seen_ac.add(t)
            ac_titles.append(t)

    for _ in range(n):
        did = str(uuid.uuid4())
        d = _draft_one(fk)
        key = dish_key(did, settings)
        need_e = bool(embed_on and _should_embed(did, settings))
        chunk_rows.append((key, d, did, need_e))
        maybe_record_ac(d)
        created += 1
        if len(chunk_rows) >= chunk:
            _flush_seed_chunk(pipe, chunk_rows, settings)
            chunk_rows.clear()
            pipe.execute()
            pipe = r.pipeline(transaction=False)

    if chunk_rows:
        _flush_seed_chunk(pipe, chunk_rows, settings)
        chunk_rows.clear()
    if created > 0:
        pipe.execute()

    ac = 0
    if ac_titles:
        sug = r.pipeline(transaction=False)
        for t in ac_titles:
            sug.execute_command("FT.SUGADD", settings.autocomplete_key, t, "1.0")
        try:
            sug.execute()
            ac = len(ac_titles)
        except Exception:
            for t in ac_titles:
                suggest_add(t, settings=settings)
            ac = len(ac_titles)

    stro = upsert_strogonoff_demo_dishes(settings)

    return {
        "created": created,
        "removed_previous_keys": removed,
        "autocomplete_seeded": ac,
        "embedding_mode": settings.embedding_write_mode,
        "strogonoff_demo_upserted": stro,
    }
