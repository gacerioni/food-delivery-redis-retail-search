"""FastAPI entry: demo UI + JSON APIs."""

from __future__ import annotations

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

ROOT = Path(__file__).resolve().parent.parent.parent
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
