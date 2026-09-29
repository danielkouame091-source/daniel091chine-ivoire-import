#!/usr/bin/env bash
# =============================================================================
# Configuration des variables Railway (via le dashboard ou CLI).
# Usage : ./scripts/railway-secrets.sh
# =============================================================================
set -euo pipefail

echo "🔐 Configuration Railway — Variables"
echo ""
echo "Railway gère les variables via le dashboard web."
echo "→ Va sur https://railway.app/dashboard"
echo "→ Sélectionne ton projet → Service (api ou worker) → Variables"
echo ""
echo "Variables à configurer pour le service 'api' :"
echo ""
echo "  DATABASE_URL              → \${{ Postgres.DATABASE_URL }}"
echo "  REDIS_URL                 → \${{ Redis.REDIS_URL }}"
echo "  JWT_PRIVATE_KEY           → (copier depuis .env)"
echo "  JWT_PUBLIC_KEY            → (copier depuis .env)"
echo "  ENCRYPTION_KEY            → (copier depuis .env)"
echo "  WAVE_WEBHOOK_SECRET       → (copier depuis .env)"
echo "  ORANGE_WEBHOOK_SECRET     → (copier depuis .env)"
echo "  MTN_WEBHOOK_SECRET        → (copier depuis .env)"
echo "  MOOV_WEBHOOK_SECRET       → (copier depuis .env)"
echo "  OPENAI_API_KEY            → (copier depuis .env)"
echo "  FOUNDER_EMAIL             → daniel@mtech.ci"
echo "  ENV                       → prod"
echo ""
echo "Variables à configurer pour le service 'worker' :"
echo ""
echo "  DATABASE_URL              → \${{ Postgres.DATABASE_URL }}"
echo "  REDIS_URL                 → \${{ Redis.REDIS_URL }}"
echo "  JWT_PRIVATE_KEY           → (copier depuis .env)"
echo "  ENCRYPTION_KEY            → (copier depuis .env)"
echo "  OPENAI_API_KEY            → (copier depuis .env)"
echo "  ENV                       → prod"
echo ""
echo "💡 Utilise les URLs PRIVÉES (*.railway.internal) pour éviter les coûts d'egress."
echo "   Railway injecte automatiquement \$PORT — ne le définis PAS manuellement."
