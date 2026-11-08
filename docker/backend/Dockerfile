# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=5
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 humsafar \
    && useradd --uid 10001 --gid humsafar --no-create-home --shell /usr/sbin/nologin humsafar

COPY backend/requirements-api.txt backend/requirements-ml.txt /app/backend/
COPY docker/backend/constraints.txt /app/docker/backend/constraints.txt
# Host-provisioned Linux wheels avoid Docker Desktop's outbound index timeouts.
# BuildKit's read-only mount keeps wheels out of the resulting image layers.
RUN --network=none --mount=type=bind,from=wheels,target=/wheels \
    python -m pip install --no-cache-dir --no-index --find-links=/wheels --only-binary=:all: \
       -r backend/requirements-api.txt -r backend/requirements-ml.txt -c docker/backend/constraints.txt \
    && python -m pip check

COPY backend/api /app/backend/api
COPY backend/catalog.py backend/group_consensus.py backend/recommendation_service.py backend/recommender.py backend/train_baselines.py backend/train_bpr.py /app/backend/
COPY docker/humsafar_artifacts.py /app/docker/humsafar_artifacts.py
COPY docker/backend/entrypoint.py /app/docker/backend/entrypoint.py
RUN mkdir -p /app/data/processed/international /state \
    && ln -s /opt/humsafar-artifacts/catalog/catalog.jsonl /app/data/processed/international/catalog.jsonl \
    && ln -s /opt/humsafar-artifacts/models /app/models \
    && chown humsafar:humsafar /state

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=4s --start-period=45s --retries=4 \
    CMD python -c "import json,urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=2))['status']=='ok'"
CMD ["python", "docker/backend/entrypoint.py"]
