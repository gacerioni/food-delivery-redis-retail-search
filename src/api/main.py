"""FastAPI entry: demo UI + JSON APIs."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from api.routes import router
from data.food_index import ensure_index
from search.synonyms import apply_default_synonyms
from seed.catalog import upsert_strogonoff_demo_dishes


def _asset_root() -> Path:
    """Resolve repo root with templates/ and static/.

    ``pip install`` places ``api/main.py`` under ``site-packages/``; three ``.parent`` hops no
    longer reach the project tree. Docker copies assets to ``/app``. Local dev keeps ``src/api``.
    """
    for key in ("DEMO_ASSET_ROOT", "ASSET_ROOT"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            p = Path(raw).resolve()
            if (p / "templates").is_dir() and (p / "static").is_dir():
                return p
    here = Path(__file__).resolve()
    dev = here.parent.parent.parent
    if (dev / "templates").is_dir() and (dev / "static").is_dir():
        return dev
    beside_pkg = here.parent
    if (beside_pkg / "templates").is_dir() and (beside_pkg / "static").is_dir():
        return beside_pkg
    docker = Path("/app")
    if (docker / "templates").is_dir() and (docker / "static").is_dir():
        return docker
    raise RuntimeError(
        "Missing templates/ and static/. Set DEMO_ASSET_ROOT to a directory that contains both, "
        "or run from a repo checkout / Docker image with assets copied under /app."
    )


ROOT = _asset_root()
templates = Jinja2Templates(directory=str(ROOT / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_index()
    # FT.SYNUPDATE from packaged groups — demo is ready on ./start.sh without Admin clicks.
    apply_default_synonyms()
    # Five fixed strogonoff SKUs (Faker catalog rarely contains the word).
    upsert_strogonoff_demo_dishes()
    yield


app = FastAPI(
    title="Redis retail food search demo",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(router)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
def index_page(request: Request):
    # Starlette 1.x+: TemplateResponse(request, name, context=...) — request is positional first.
    return templates.TemplateResponse(
        request,
        "index.html",
        {"title": "Redis hybrid search — demo"},
    )
