.PHONY: up down logs restart update ps config backup migrate safe-update up-image up-watchtower

# Pin image tag (defaults to VERSION file contents, trimmed).
WEBABLE_VERSION ?= $(shell tr -d '\n\r' < VERSION 2>/dev/null || echo latest)

backup:
	bash scripts/webable-backup.sh

migrate:
	bash scripts/webable-migrate.sh

safe-update:
	bash scripts/webable-safe-update.sh

up:
	docker compose up -d --build

# Pre-built image from GHCR (no local build). Set WEBABLE_VERSION=1.2.3 to pin a tag.
up-image:
	WEBABLE_VERSION=$(WEBABLE_VERSION) docker compose -f docker-compose.image.yml up -d

# GHCR image + Watchtower sidecar (label-only updates; needs Docker socket).
up-watchtower:
	WEBABLE_VERSION=$(WEBABLE_VERSION) docker compose -f docker-compose.image.yml -f docker-compose.watchtower.yml up -d

down:
	docker compose down

logs:
	docker compose logs -f

restart:
	docker compose restart

update:
	git pull && docker compose up -d --build

ps:
	docker compose ps

config:
	docker compose config
