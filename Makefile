.PHONY: up down logs restart update ps config

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
