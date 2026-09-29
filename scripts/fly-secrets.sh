#!/usr/bin/env bash
# =============================================================================
# Configuration des secrets Fly.io pour l'API + Worker.
# Usage : ./scripts/fly-secrets.sh
# =============================================================================
set -euo pipefail

API_APP="mtech-saas-api"
WORKER_APP="mtech-saas-worker"

if [ ! -f .env ]; then
  echo "❌ Fichier .env introuvable."
  exit 1
fi

# Charger les variables depuis .env
set -a
source .env
set +a

echo "🔐 Configuration des secrets Fly.io..."
echo ""

# ─── Secrets communs (API + Worker) ─────────────────────────────────────
COMMON_SECRETS=(
  "JWT_PRIVATE_KEY=$JWT_PRIVATE_KEY"
  "JWT_PUBLIC_KEY=$JWT_PUBLIC_KEY"
  "ENCRYPTION_KEY=$ENCRYPTION_KEY"
  "OPENAI_API_KEY=$OPENAI_API_KEY"
)

# ─── Secrets spécifiques à l'API ────────────────────────────────────────
API_SECRETS=(
  "WAVE_WEBHOOK_SECRET=$WAVE_WEBHOOK_SECRET"
  "ORANGE_WEBHOOK_SECRET=$ORANGE_WEBHOOK_SECRET"
  "MTN_WEBHOOK_SECRET=$MTN_WEBHOOK_SECRET"
  "MOOV_WEBHOOK_SECRET=$MOOV_WEBHOOK_SECRET"
  "FOUNDER_EMAIL=${FOUNDER_EMAIL:-daniel@mtech.ci}"
  "WHATSAPP_META_TOKEN=${WHATSAPP_META_TOKEN:-}"
  "WHATSAPP_META_PHONE_ID=${WHATSAPP_META_PHONE_ID:-}"
  "WHATSAPP_META_VERIFY_TOKEN=${WHATSAPP_META_VERIFY_TOKEN:-}"
)

echo "→ API : $((${#COMMON_SECRETS[@]} + ${#API_SECRETS[@]})) secrets..."
flyctl secrets set -a "$API_APP" "${COMMON_SECRETS[@]}" "${API_SECRETS[@]}"

echo "→ Worker : ${#COMMON_SECRETS[@]} secrets..."
flyctl secrets set -a "$WORKER_APP" "${COMMON_SECRETS[@]}"

echo ""
echo "✅ Secrets configurés."
echo "→ Vérifier : flyctl secrets list -a $API_APP"
