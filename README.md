# Food delivery retail search — Redis hybrid demo

MVP demo: **HASH** documents, **RediSearch** full-text + geo, optional **vectors**, **`FT.HYBRID` + RRF** on **Redis 8.4+** (8.6-compatible APIs). Includes a small **web UI** with **Search**, **Admin (catalog + index)**, and **Observability** (timings, `FT.INFO`, memory, slowlog).

See [`AGENT.md`](AGENT.md) for the full contract.

**Redis is never started by this repo.** Point the app at your cluster with **`REDIS_URL`** (for example Redis Cloud).

## Quick start (local Python)

1. **Redis 8.4+** with Search / hybrid available at your **`REDIS_URL`** (you provision it; not part of this repo).

2. One command on a Mac (creates `.venv`, installs deps, copies `.env` if missing, runs the app):

   ```bash
   cd food-delivery-redis-retail-search
   ./start.sh
   ```

   - **`./start.sh --reset`** — delete `.venv` and reinstall everything.
   - **`DEMO_PORT=9000 ./start.sh`** — override listen port (default from **`API_PORT`** in `.env`, else **8686**).
   - If that port is busy (Errno 48), **`start.sh`** picks the **next free** port and says so. To fail instead: **`START_SH_STRICT_PORT=1 ./start.sh`**.
   - Edit **`.env`**: set **`REDIS_URL`** (and TLS URL if your cloud requires it).

   Manual equivalent:

   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -e ".[dev]"
   cp .env.example .env
   uvicorn api.main:app --reload --host 0.0.0.0 --port 8686
   ```

3. Open **http://localhost:8686** (or whatever **`API_PORT`** you set) — use **Seed catalog** in Admin if the DB is empty, then **Search**.

On API boot the app runs **`FT.CREATE` (if needed)** and applies packaged **synonyms** (`FT.SYNUPDATE`) so you do not need Admin → “apply synonyms”. It also **upserts 5 fixed strogonoff dishes** (`dish:demo-strogonoff-01` … `05`) because the Faker catalog almost never emits that word — so searches like **estrogonofe** have real rows. First hybrid search may be slower while **sentence-transformers** loads into memory.

**Synonym policy:** [`src/data/default_synonyms.json`](src/data/default_synonyms.json) stays **small** — only frequent spelling variants for the same idea (e.g. pitza→pizza). Big or creative groups **widen FTS**; with **`FT.HYBRID` + RRF** that can float unrelated dishes (vector leg). Do not equate a **category** with a **dish** (we do not put “japonesa” in the sushi group). Prefer **fuzzy retry on miss** for rare typos; add synonym groups only when analytics say they help.

## Run with Docker (app image only)

Build and run the **API/UI container**; pass **`REDIS_URL`** (and any other env vars) from your environment or secrets store.

```bash
docker build -t food-search-demo .
docker run --rm -p 8686:8686 \
  -e REDIS_URL='redis://default:YOUR_PASSWORD@YOUR_HOST:PORT/0' \
  food-search-demo
```

The `Dockerfile` installs and runs **only** this application — it does not run Redis. It forces **CPU-only PyTorch** (`2.x+cpu`) and removes **`nvidia-*` / `triton` / `cuda-*`** wheels so multi-arch builds do not ship a useless ~1.5GB CUDA stack for this demo. The app runs as **non-root** (`uid 10001`) and exposes a **HEALTHCHECK** on `/api/observability`.

**Docker Hub (buildx, amd64 + arm64)** — use two tags (the second is usually `:latest`, not a second version suffix):

```bash
docker buildx build --builder imusica-builder \
  --platform linux/amd64,linux/arm64 \
  -f Dockerfile \
  -t gacerioni/gabs-sku-hybridsearch-redis:0.0.1-gabs \
  -t gacerioni/gabs-sku-hybridsearch-redis:latest \
  --push .
```

(`-t …:0.0.1-gabs:latest` in one tag is invalid: Docker interprets the part after the **last** colon as the tag, so you would get tag `latest` on repo `…:0.0.1-gabs`, which is not what you want.)

**Compose (pull image from Docker Hub — no build):**

Set `DOCKER_IMAGE` in `.env` (see `.env.example`), then:

```bash
docker compose up -d
```

`pull_policy: always` keeps the Hub tag fresh on each `up`. UI: `http://127.0.0.1:$API_PORT` (e.g. `8001` from your `.env`).

If Redis runs **on the host** (`localhost:…` in `.env`), use `REDIS_URL=redis://host.docker.internal:<port>/0` in `.env` so the container can reach it.

## Environment

- **`REDIS_URL`**: required for real use (no default suitable for production). `.env.example` shows a placeholder.
- **`EMBEDDING_WRITE_MODE`**: `all` | `sample` | `none` — `none` builds an index **without** a vector field and uses **FT.SEARCH** only (good for CI or low-RAM machines). `all` embeds every seeded dish (needs RAM + time for large `SEED_TARGET_DISHES`).
- **`ALLOW_INDEX_REBUILD`**: must be `true` to call **Drop & recreate index** from the Admin UI.
- **`FUZZY_FALLBACK_ON_MISS`** (default `true`): if a text query returns **zero** hits, the app retries once with RediSearch **`%token%`** fuzzy (≈1 edit) on tokens at least **`FUZZY_MIN_TOKEN_LEN`** long — extra latency **only on misses**, not on every query.
- **`SEED_TARGET_DISHES`**: default in code is **500000** (the demo contract). For quick iteration on a laptop, lower the count in `.env` or in the Admin seed field; for repeatable “full catalog” cold starts, prefer baking a **Redis snapshot (`.rdb` / managed backup)** and restoring from object storage — see [`AGENT.md` §7.5](AGENT.md#75-warm-dataset-gerar-tudo-no-seed-vs-snapshot-rdb-ex-s3).

## Tests

Point **`REDIS_URL`** at a reachable Redis 8.4+ instance, then:

```bash
pytest -q
```

Smoke tests skip if Redis is unreachable or lacks RediSearch.
