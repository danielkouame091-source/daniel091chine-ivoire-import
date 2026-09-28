# MTech SaaS SYSCOHADA — commandes opérationnelles
PYTHON := python
UVICORN := uvicorn
ALEMBIC := alembic
WEB := web

.PHONY: help dev api worker migrate revision seed founder tenant rotate test \
        e2e e2e-ui e2e-debug e2e-install

help:
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ─── Backend ────────────────────────────────────────────────────────────
dev:  ## Lance l'API + le worker en parallèle
	$(UVICORN) app.main:app --reload --port 8000 & \
	arq app.workers.arq_settings.WorkerSettings & \
	wait

api:  ## Lance l'API FastAPI
	$(UVICORN) app.main:app --reload --port 8000

worker:  ## Lance le worker ARQ
	arq app.workers.arq_settings.WorkerSettings

migrate:  ## Applique les migrations Alembic
	$(ALEMBIC) upgrade head

revision:  ## Génère une migration (make revision m="message")
	$(ALEMBIC) revision --autogenerate -m "$(m)"

# ─── Seeds ──────────────────────────────────────────────────────────────
seed:  ## Charge plan comptable SYSCOHADA (make seed slug=demo-ci)
	$(PYTHON) -m scripts.seed_db --tenant-slug $(slug)

seed-e2e:  ## Prépare les fixtures E2E
	$(PYTHON) -m scripts.seed_e2e

founder:  ## Crée le fondateur unique
	$(PYTHON) -m scripts.create_founder --email $(email)

tenant:  ## Crée un tenant + admin
	$(PYTHON) -m scripts.create_tenant --slug $(slug) --raison-sociale "$(name)" --admin-email $(email)

rotate:  ## Génère de nouvelles clés JWT/AES
	$(PYTHON) -m scripts.rotate_secrets --output .env.new

# ─── Tests backend ──────────────────────────────────────────────────────
test:  ## Lance les tests pytest
	pytest -v --asyncio-mode=auto

# ─── Tests E2E ──────────────────────────────────────────────────────────
e2e:  ## Lance les tests Playwright
	cd $(WEB) && npm run e2e

e2e-ui:  ## Playwright en mode UI
	cd $(WEB) && npm run e2e:ui

e2e-debug:  ## Playwright en mode debug
	cd $(WEB) && npm run e2e:debug

e2e-headed:  ## Playwright avec navigateur visible
	cd $(WEB) && npm run e2e:headed

e2e-install:  ## Installe les navigateurs Playwright
	cd $(WEB) && npm run e2e:install

e2e-report:  ## Affiche le dernier rapport Playwright
	cd $(WEB) && npm run e2e:report

# ─── Frontend ───────────────────────────────────────────────────────────
web-dev:  ## Lance le frontend Next.js
	cd $(WEB) && npm run dev

web-build:  ## Build production du frontend
	cd $(WEB) && npm run build

# ─── Qualité ────────────────────────────────────────────────────────────
lint:  ## Lint + format
	ruff check app scripts
	ruff format --check app scripts
	cd $(WEB) && npm run lint
	cd $(WEB) && npm run typecheck
