# Redis hybrid search — food delivery / retail SKU demo

A **hands-on demo** of **iFood-style discovery** (dishes + merchants) on **one Redis** — not a toy script, not a second “search appliance”. The story we prove: **full-text + geo + vectors + native fusion** (`FT.HYBRID` + **RRF**) live beside your catalog data, with a small **web UI** and **admin-style** controls so buyers can *see* latency, index shape, and tuning trade-offs.

**Redis is never bundled here.** You point the app at **Redis 8.4+** (Search + JSON-style workflows; hybrid APIs align with **8.6+** positioning). Bring your own cluster (Redis Cloud, VPC, ElastiCache, laptop).

---

## What this demo actually does

| Capability | What we built |
|------------|----------------|
| **Hybrid search** | `FT.HYBRID`: BM25-style **FTS** + **KNN** vectors fused with **RRF** in Redis — no hand-rolled score math in Python for the fusion step. |
| **Geo** | Dish documents carry merchant location; queries can filter by **radius** around user lat/lon. |
| **Typos & variants** | Small **synonym** set (`FT.SYNUPDATE`) applied **on API boot** — no “click to load synonyms” step. **Fuzzy `%token%` retry** only when strict text returns **zero** hits (keeps precision on the happy path). |
| **Catalog at scale** | Seeded **HASH** dishes (`dish:{uuid}`) with pipelined ingest; contract in [`AGENT.md`](AGENT.md) targets **hundreds of thousands** of rows (lower `SEED_TARGET_DISHES` on a laptop). |
| **“Real” strogonoff rows** | Faker rarely emits that word — we **always upsert 5 fixed strogonoff SKUs** on boot so synonym + search demos never look empty. |
| **Operator UX** | **Search** tab, **Admin** (seed, CRUD, index tools), **Observability** (`FT.INFO`, memory, slowlog, per-request timing metadata). |
| **Container-ready** | `Dockerfile`: **CPU-only PyTorch**, strips accidental **CUDA** wheels for lean **linux/amd64** + **linux/arm64** images; non-root user; healthcheck. |

**What we deliberately did *not* build:** intent routers, chat/concierge, or a separate Elasticsearch/OpenSearch cluster. This repo is **pure search** on Redis so the conversation stays: *latency, simplicity, one bill, one ops model.*

---

## Who it is for

- **Sales / solution architects** demoing Redis Search + hybrid to accounts comparing managed retail search or “always bolt Elasticsearch”.
- **Engineers** who want a **working reference** for `FT.HYBRID`, HASH indexing, and a FastAPI façade with honest observability hooks.

Full product contract (field rules, non-goals, env dictionary) lives in **[`AGENT.md`](AGENT.md)**.

---

## Quick start (local Python)

1. **Redis 8.4+** with Search (and hybrid where your tier supports it) reachable via **`REDIS_URL`**.

2. One command on a Mac (creates `.venv`, installs deps, copies `.env` if missing, runs the API):

   ```bash
   cd food-delivery-redis-retail-search
   ./start.sh
   ```

   - **`./start.sh --reset`** — delete `.venv` and reinstall.
   - **`DEMO_PORT=9000 ./start.sh`** — override listen port (default from **`API_PORT`** in `.env`, else **8686**).
   - If the port is busy, **`start.sh`** picks the **next free** port unless **`START_SH_STRICT_PORT=1`**.

3. Open **`http://127.0.0.1:<API_PORT>`** — if Redis is empty, use **Admin → Seed catalog**, then **Search**.

First hybrid query may be slow while **sentence-transformers** loads the embedding model into memory.

**Synonym policy:** [`src/data/default_synonyms.json`](src/data/default_synonyms.json) stays **small** (high-traffic spelling variants only). Large synonym groups widen FTS; with hybrid + RRF that can surface unrelated hits. Prefer **fuzzy-on-miss** for rare typos; extend synonyms when data says so.

---

## Docker

### Build & run (single container)

```bash
docker build -t food-search-demo .
docker run --rm -p 8686:8686 \
  -e REDIS_URL='redis://default:YOUR_PASSWORD@YOUR_HOST:PORT/0' \
  food-search-demo
```

### Multi-arch push (Docker Hub)

Use **two** `-t` flags (do not put `:latest` after a versioned image name in a single tag):

```bash
docker buildx build --builder imusica-builder \
  --platform linux/amd64,linux/arm64 \
  -f Dockerfile \
  -t gacerioni/gabs-sku-hybridsearch-redis:0.0.1-gabs \
  -t gacerioni/gabs-sku-hybridsearch-redis:latest \
  --push .
```

### Compose (pull from Hub — no `build`)

Set **`DOCKER_IMAGE`** in `.env` (see [`.env.example`](.env.example)), then:

```bash
docker compose up -d
```

`pull_policy: always` refreshes the image on each `up`. Map **`API_PORT`** in `.env` to the published port.

If Redis runs **on the Docker host** (`localhost` in `.env`), set:

`REDIS_URL=redis://host.docker.internal:<port>/0`

so the container reaches the host (`extra_hosts` is already set in [`docker-compose.yml`](docker-compose.yml) for Linux).

---

## Environment (short)

| Variable | Role |
|----------|------|
| **`REDIS_URL`** | Required for real runs. |
| **`DOCKER_IMAGE`** | Compose-only: image to pull from Hub. |
| **`EMBEDDING_WRITE_MODE`** | `all` \| `sample` \| `none` — `none` = index **without** vectors, **FT.SEARCH** only (CI / low RAM). |
| **`FUZZY_FALLBACK_ON_MISS`** | Second pass with `%token%` fuzzy **only** when strict search returns no hits. |
| **`SEED_TARGET_DISHES`** | Catalog size for seed (default in code is large; shrink for laptops). Warm snapshots vs full re-seed: see **[`AGENT.md` §7](AGENT.md)**. |
| **`ALLOW_INDEX_REBUILD`** | Must be `true` to allow destructive index actions from Admin. |

---

## Tests

With **`REDIS_URL`** pointing at a reachable Redis 8.4+ instance:

```bash
pytest -q
```

Smoke tests skip if Redis is down or lacks RediSearch.

---

## Repo layout (high level)

- **`src/api/`** — FastAPI routes + Jinja UI wiring.
- **`src/search/`** — Hybrid query builder, autocomplete, synonyms, embeddings.
- **`src/data/`** — Redis client, HASH CRUD, `FT.CREATE` / index helpers.
- **`src/seed/`** — Faker catalog + strogonoff fixtures.
- **`templates/`**, **`static/`** — Demo UI.
