# syntax=docker/dockerfile:1
# Runtime image: no build tools, no network needed after build, non-root, read-only friendly.
FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml README.md LICENSE constraints.txt ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install -c constraints.txt . 2>/dev/null || \
    pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    OMP_NUM_THREADS=1 TAHDEED_STRICT=1 \
    TAHDEED_DB=/data/gazetteer.sqlite TAHDEED_MODEL=/data/ranker.npz
COPY --from=build /install /usr/local
COPY web /app/web
RUN useradd --system --uid 10001 --no-create-home tahdeed
USER 10001
WORKDIR /app
EXPOSE 8000
# /data is mounted read-only: gazetteer.sqlite (built with `tahdeed build`) and ranker.npz
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health', timeout=4)"
CMD ["python", "-m", "uvicorn", "tahdeed.api:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000"]
