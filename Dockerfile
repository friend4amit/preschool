# syntax=docker/dockerfile:1

# One image, two targets: `dev` (dev dependencies, source bind-mounted) and
# `prod` (default — no dev dependencies, source baked in). Web and worker
# containers run the same image with different commands.

ARG PYTHON_VERSION=3.13

# --- dependency builder -------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS builder-base

# The venv lives outside /app: the dev compose bind-mounts source over /app and
# would otherwise shadow /app/.venv, leaving the container with no dependencies.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

# Toolchain lives only here; the runtime stage never inherits it.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies resolve from these two files alone, so they cache independently
# of application source.
COPY pyproject.toml uv.lock ./

FROM builder-base AS builder-dev
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

FROM builder-base AS builder-prod
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
# Second pass installs the project itself, if pyproject declares a build-system.
# A no-op for a plain (non-packaged) Django project.
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --- css build -----------------------------------------------------------------
# Tailwind v4 standalone CLI: no Node, no package.json. static/css/app.css is
# build output and gitignored, so it MUST be produced here — otherwise the prod
# image ships with no stylesheet at all.
FROM debian:bookworm-slim AS tailwind
ARG TAILWIND_VERSION=v4.3.3
ARG TAILWIND_ARCH=x64
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
# Scan roots declared via @source in input.css resolve relative to that file,
# so the layout here must mirror the repo.
COPY assets ./assets
COPY templates ./templates
COPY apps ./apps
RUN curl -fsSL -o /usr/local/bin/tailwindcss \
      "https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-linux-${TAILWIND_ARCH}" \
    && chmod +x /usr/local/bin/tailwindcss \
    && mkdir -p /out \
    && tailwindcss -i assets/css/input.css -o /out/app.css --minify

# --- runtime ------------------------------------------------------------------
# Same Debian and interpreter layout as the uv image above, so /opt/venv works
# unchanged when copied across.
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime-base

# libpq5 only — the client library, not the headers. Needed by psycopg built
# from source; harmless if the lockfile pins psycopg[binary] instead.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 app

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    TZ=Asia/Kolkata

# /app must be owned by `app`: collectstatic creates STATIC_ROOT under it, and
# COPY --chown only sets ownership on the entries it copies, not on the directory.
RUN install -d -o app -g app /app
WORKDIR /app
EXPOSE 8000

FROM runtime-base AS dev
COPY --from=builder-dev /opt/venv /opt/venv
USER app
# Source arrives via bind mount; autoreload is the point of the dev image.
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

FROM runtime-base AS prod
COPY --from=builder-prod /opt/venv /opt/venv
COPY --chown=app:app . /app
COPY --from=tailwind --chown=app:app /out/app.css /app/static/css/app.css
USER app
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
