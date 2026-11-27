FROM oven/bun:1.4.5 AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json ./
COPY frontend/bun.lock* ./
RUN bun install --frozen-lockfile
COPY frontend/ ./
RUN bun run build

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates libglib2.0-0 libgl1 libv4l-0 curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.13.10

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-dev --extra dream --no-install-project

COPY backend/src ./src
COPY backend/alembic.ini ./alembic.ini
COPY backend/migrations ./migrations
COPY configs /app/configs
COPY experiments/piper_station_worker /app/experiments/piper_station_worker
COPY assets /app/assets
COPY docker/station-entrypoint.sh /app/docker/station-entrypoint.sh
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist
RUN uv sync --locked --no-dev --extra dream

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONPATH=/app/backend/src \
    RSTACK_FRONTEND_DIST=/app/frontend/dist \
    RSTACK_ROBOT_CONFIG=/app/configs/app_robot.yaml \
    RSTACK_DREAM_CONFIG=/app/experiments/piper_station_worker/config/dream.yaml

EXPOSE 8443
CMD ["/bin/sh", "/app/docker/station-entrypoint.sh"]
