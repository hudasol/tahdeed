# syntax=docker/dockerfile:1
# Runtime image: no build tools, no network needed after build, non-root, read-only friendly.
#
#   docker build -t tahdeed .
#   docker run --rm -p 8000:8000 --read-only --tmpfs /tmp --cap-drop ALL \
#       --security-opt no-new-privileges -v "$PWD/data:/data:ro" tahdeed
#
# /data must hold gazetteer.sqlite (built with `tahdeed build`) and ranker.npz (`tahdeed train`).
# Neither is baked into the image: both are derived from OpenStreetMap (ODbL) and are large.
# See docs/DEPLOYMENT.md.

FROM python:3.12-slim-bookworm AS build
WORKDIR /src
COPY pyproject.toml README.md LICENSE constraints.txt ./
COPY src ./src
# Pinned versions only: a resolution failure must fail the build, not fall back to "latest".
RUN pip install --no-cache-dir --prefix=/install -c constraints.txt .

FROM python:3.12-slim-bookworm
LABEL org.opencontainers.image.title="tahdeed" \
      org.opencontainers.image.description="Bilingual UAE address resolver (code only; mount data at /data)" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/hudasol/tahdeed"
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    OMP_NUM_THREADS=1 TAHDEED_STRICT=1 \
    TAHDEED_DB=/data/gazetteer.sqlite TAHDEED_MODEL=/data/ranker.npz
COPY --from=build /install /usr/local
RUN groupadd --system --gid 10001 tahdeed \
 && useradd --system --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin tahdeed
USER 10001:10001
WORKDIR /app
EXPOSE 8000
# Loading the gazetteer takes ~8 s on the full data, hence the start period.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health', timeout=4)"]
# Exec form so uvicorn is PID 1 and receives SIGTERM; extra `docker run` arguments are appended.
ENTRYPOINT ["python", "-m", "uvicorn", "tahdeed.api:app_factory", "--factory", \
            "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
