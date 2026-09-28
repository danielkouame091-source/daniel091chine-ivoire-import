# =============================================================================
# MTech SaaS SYSCOHADA — Image production multi-stage
# =============================================================================
# Stage 1 : builder — installe les dépendances Python dans un venv isolé
# Stage 2 : runtime — copie uniquement le venv + le code applicatif
# =============================================================================

# ─── Stage 1 : BUILDER ─────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Dépendances système pour la compilation (asyncpg, cryptography, argon2)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        libffi-dev \
        libssl-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Créer un venv isolé
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip + installer les dépendances
COPY requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip setuptools wheel \
    && pip install -r /tmp/requirements.txt


# ─── Stage 2 : RUNTIME ─────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app"

# Dépendances système runtime uniquement
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --shell /bin/bash --create-home app

# Copier le venv depuis le builder
COPY --from=builder /opt/venv /opt/venv

# Répertoire de travail
WORKDIR /app

# Copier le code applicatif
COPY --chown=app:app app/               ./app/
COPY --chown=app:app alembic/           ./alembic/
COPY --chown=app:app alembic.ini        ./alembic.ini
COPY --chown=app:app scripts/           ./scripts/
COPY --chown=app:app sql/               ./sql/
COPY --chown=app:app requirements.txt   ./requirements.txt

# Créer le répertoire scripts comme package (sécurité)
RUN touch scripts/__init__.py && chown app:app scripts/__init__.py

# Utilisateur non-root
USER app

# Port exposé (documentaire)
EXPOSE 8000

# Healthcheck basé sur l'endpoint /health
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Commande par défaut : API (surchargée par docker-compose pour le worker)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
