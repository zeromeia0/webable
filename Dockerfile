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

COPY webapp.py .
COPY app ./app

EXPOSE 8000

# Production: no --reload. Listen on all interfaces for Docker.
CMD ["uvicorn", "webapp:app", "--host", "0.0.0.0", "--port", "8000"]
