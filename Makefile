.PHONY: install run run-local ai ai-run ai-down ai-logs up down logs restart update ps config backup migrate safe-update up-image up-image-ai up-watchtower

# --- Compose file sets (core vs optional AI) ---
COMPOSE ?= docker compose
COMPOSE_CORE := $(COMPOSE) -f docker-compose.yml
COMPOSE_AI := $(COMPOSE) -f docker-compose.yml -f docker-compose.ai.yml
COMPOSE_IMAGE := $(COMPOSE) -f docker-compose.image.yml
COMPOSE_IMAGE_AI := $(COMPOSE) -f docker-compose.image.yml -f docker-compose.ai.yml

WEBABLE_VERSION ?= $(shell tr -d '\n\r' < VERSION 2>/dev/null || echo latest)

# --- Default workflow (no AI downloads) ---

install:
	bash scripts/webable-install.sh

run: up

run-local:
	@test -d .venv || (echo "Run 'make install' first." && exit 1)
	.venv/bin/uvicorn webapp:app --host 127.0.0.1 --port 8000 --reload

up:
	$(COMPOSE_CORE) up -d --build

down:
	$(COMPOSE_CORE) down

logs:
	$(COMPOSE_CORE) logs -f

restart: down up

update:
	git pull && $(COMPOSE_CORE) up -d --build

ps:
	$(COMPOSE_CORE) ps

config:
	$(COMPOSE_CORE) config

# --- Optional AI (isolated from install/run) ---

ai:
	bash scripts/webable-ai-setup.sh

ai-run:
	$(COMPOSE_AI) up -d --build

ai-down:
	$(COMPOSE_AI) stop ollama

ai-logs:
	$(COMPOSE_AI) logs -f ollama

# --- GHCR image deploy (no local build) ---

up-image:
	WEBABLE_VERSION=$(WEBABLE_VERSION) $(COMPOSE_IMAGE) up -d

up-image-ai:
	WEBABLE_VERSION=$(WEBABLE_VERSION) $(COMPOSE_IMAGE_AI) up -d

up-watchtower:
	WEBABLE_VERSION=$(WEBABLE_VERSION) $(COMPOSE_IMAGE) -f docker-compose.watchtower.yml up -d

# --- Data / migrations ---

backup:
	bash scripts/webable-backup.sh

migrate:
	bash scripts/webable-migrate.sh

safe-update:
	bash scripts/webable-safe-update.sh
