# MTech SaaS SYSCOHADA — commandes opérationnelles
PYTHON := python
UVICORN := uvicorn
ALEMBIC := alembic

.PHONY: help dev api worker migrate revision seed founder tenant rotate test lint

help:
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

dev:  ## Lance l'API + le worker en parallèle (dev)
	$(UVICORN) app.main:app --reload --port 8000 & \
	arq app.workers.arq_settings.WorkerSettings & \
	wait

api:  ## Lance uniquement l'API FastAPI
	$(UVICORN) app.main:app --reload --port 8000

worker:  ## Lance uniquement le worker ARQ
	arq app.workers.arq_settings.WorkerSettings

migrate:  ## Applique les migrations Alembic
	$(ALEMBIC) upgrade head

revision:  ## Génère une migration autogenerate (usage: make revision m="message")
	$(ALEMBIC) revision --autogenerate -m "$(m)"

seed:  ## Charge le plan comptable SYSCOHADA (usage: make seed slug=demo-ci)
	$(PYTHON) -m scripts.seed_db --tenant-slug $(slug)

founder:  ## Crée le fondateur unique
	$(PYTHON) -m scripts.create_founder --email $(email)

tenant:  ## Crée un tenant + admin (usage: make tenant slug=demo-ci email=admin@demo.ci)
	$(PYTHON) -m scripts.create_tenant --slug $(slug) --raison-sociale "$(name)" --admin-email $(email)

rotate:  ## Génère de nouvelles clés JWT/AES
	$(PYTHON) -m scripts.rotate_secrets --output .env.new

test:  ## Lance la suite de tests
	pytest -v --asyncio-mode=auto

lint:  ## Lint + format
	ruff check app scripts
	ruff format --check app scripts
