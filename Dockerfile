# Application image only. Redis is external — set REDIS_URL at run time.
#
# Multi-arch (linux/amd64, linux/arm64): `pip install .` still resolves `torch` from PyPI with
# CUDA/cuDNN meta-deps on arm64 (~1.5GB+). We reinstall **CPU** torch from PyTorch's index, then
# strip leftover `nvidia-*` / `triton` wheels so the image stays suitable for CPU-only K8s/Cloud Run.

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY templates ./templates
COPY static ./static

RUN pip install --upgrade pip \
    && pip install --no-cache-dir . \
    && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu --force-reinstall --no-deps \
    && pip list --format=freeze | grep -iE '^(nvidia-|triton|cuda-)' | cut -d= -f1 | xargs -r pip uninstall -y \
    && python -c "import torch; raise SystemExit(1 if torch.cuda.is_available() else 0)"

RUN useradd --create-home --shell /bin/bash --uid 10001 app \
    && chown -R app:app /app
USER app

# Installed package lives under site-packages; templates/static stay at /app from COPY above.
ENV DEMO_ASSET_ROOT=/app
ENV API_PORT=8686

EXPOSE 8686

HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
    CMD python -c "import os,urllib.request; p=os.environ.get('API_PORT','8686'); urllib.request.urlopen(f'http://127.0.0.1:{p}/api/observability', timeout=4).read()" || exit 1

CMD ["sh", "-c", "exec uvicorn api.main:app --host 0.0.0.0 --port ${API_PORT:-8686}"]
