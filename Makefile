.PHONY: up down logs restart update ps config backup migrate safe-update

backup:
	bash scripts/webable-backup.sh

migrate:
	bash scripts/webable-migrate.sh

safe-update:
	bash scripts/webable-safe-update.sh

up:
	docker compose up -d --build

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
