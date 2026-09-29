#!/usr/bin/env bash
# =============================================================================
# Déploiement complet — API + Worker + migrations.
# Usage : ./scripts/deploy.sh [fly|railway]
# =============================================================================
set -euo pipefail

PLATFORM="${1:-fly}"
API_APP="mtech-saas-api"
WORKER_APP="mtech-saas-worker"

echo "🚀 Déploiement MTech SaaS SYSCOHADA — plateforme : $PLATFORM"
echo ""

case "$PLATFORM" in
  fly)
    # ─── 1. Build + push images ─────────────────────────────────────
    echo "→ Build API..."
    flyctl deploy --remote-only --config fly.toml

    echo "→ Build Worker..."
    flyctl deploy --remote-only --config fly.worker.toml

    # ─── 2. Vérifier la santé ───────────────────────────────────────
    echo "→ Vérification santé API..."
    sleep 10
    for i in {1..6}; do
      if curl -fsS "https://${API_APP}.fly.dev/health"; then
        echo "✅ API healthy"
        break
      fi
      if [ "$i" -eq 6 ]; then
        echo "❌ API health check échoué"
        exit 1
      fi
      sleep 10
    done

    # ─── 3. Vérifier les migrations ─────────────────────────────────
    echo "→ Vérification migrations..."
    flyctl ssh console -a "$API_APP" -C "alembic current" || true

    echo ""
    echo "✅ Déploiement Fly.io réussi."
    echo "→ API   : https://${API_APP}.fly.dev"
    echo "→ Worker: app ${WORKER_APP}"
    echo "→ Logs  : flyctl logs -a ${API_APP}"
    ;;

  railway)
    echo "→ Déploiement API Railway..."
    railway up --service api --detach

    echo "→ Déploiement Worker Railway..."
    railway up --service worker --detach

    echo "✅ Déploiement Railway lancé."
    ;;

  *)
    echo "❌ Plateforme inconnue : $PLATFORM (utilise 'fly' ou 'railway')"
    exit 1
    ;;
esac
