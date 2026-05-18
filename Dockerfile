# Webable — FastAPI app (local-first). Bind host port in docker-compose (default 8080 -> 8000).
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    WEBABLE_DATA_DIR=/app/data

WORKDIR /app

# Optional PDF/chart stack may need font libs on some platforms; curl is used by healthchecks.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY VERSION /app/VERSION
COPY webapp.py .
COPY app ./app
COPY update.md ./update.md

# Optional: override /app/VERSION (e.g. CI tag) while keeping repo VERSION as default.
ARG WEBABLE_APP_VERSION=
RUN if [ -n "$WEBABLE_APP_VERSION" ]; then printf '%s\n' "$WEBABLE_APP_VERSION" > /app/VERSION; fi

ARG WEBABLE_GIT_COMMIT=
RUN if [ -n "$WEBABLE_GIT_COMMIT" ]; then printf '%s\n' "$WEBABLE_GIT_COMMIT" > /app/.webable-git-rev; else printf '%s\n' "unknown" > /app/.webable-git-rev; fi

ARG WEBABLE_BUILD_TIME=
RUN if [ -n "$WEBABLE_BUILD_TIME" ]; then printf '%s\n' "$WEBABLE_BUILD_TIME" > /app/.webable-build-time; fi

EXPOSE 8000

# Production: no --reload. Listen on all interfaces for Docker.
CMD ["uvicorn", "webapp:app", "--host", "0.0.0.0", "--port", "8000"]
