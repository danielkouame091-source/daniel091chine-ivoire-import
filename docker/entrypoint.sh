#!/bin/sh
# =============================================================================
# Entrypoint Docker — attend la DB puis exécute la commande passée.
# Utilisé pour fiabiliser le démarrage en production.
# =============================================================================
set -e

echo "[entrypoint] Attente de PostgreSQL..."
until python -c "
import os, sys, time, psycopg2
url = os.environ.get('DATABASE_URL', '').replace('+asyncpg', '').replace('+psycopg2', '')
try:
    psycopg2.connect(url).close()
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; do
    echo "[entrypoint] PostgreSQL indisponible — retry dans 2s..."
    sleep 2
done
echo "[entrypoint] PostgreSQL OK"

echo "[entrypoint] Exécution : $@"
exec "$@"
