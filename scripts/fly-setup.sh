#!/usr/bin/env bash
# =============================================================================
# Setup initial Fly.io — à exécuter UNE SEULE FOIS.
# Usage : ./scripts/fly-setup.sh
# =============================================================================
set -euo pipefail

API_APP="mtech-saas-api"
WORKER_APP="mtech-saas-worker"
REGION="cdg"   # Paris

echo "🚀 Setup Fly.io — MTech SaaS SYSCOHADA"
echo ""

# ─── 1. Vérifier flyctl ─────────────────────────────────────────────────
if ! command -v flyctl &> /dev/null; then
  echo "❌ flyctl n'est pas installé."
  echo "→ Installe-le : curl -L https://fly.io/install.sh | sh"
  exit 1
fi

if ! flyctl auth whoami &> /dev/null; then
  echo "→ Connexion à Fly.io..."
  flyctl auth login
fi

# ─── 2. Créer l'app API ─────────────────────────────────────────────────
if ! flyctl apps list | grep -q "$API_APP"; then
  echo "→ Création de l'app API : $API_APP"
  flyctl apps create "$API_APP" --org personal
fi

# ─── 3. Créer l'app Worker ──────────────────────────────────────────────
if ! flyctl apps list | grep -q "$WORKER_APP"; then
  echo "→ Création de l'app Worker : $WORKER_APP"
  flyctl apps create "$WORKER_APP" --org personal
fi

# ─── 4. Créer la base PostgreSQL managée ────────────────────────────────
echo "→ Création de PostgreSQL managé (région $REGION)..."
flyctl mpg create --name mtech-saas-db --region "$REGION" || \
  echo "⚠️  La base existe peut-être déjà"

# ─── 5. Créer Redis (Upstash) ───────────────────────────────────────────
echo "→ Création de Redis (Upstash)..."
flyctl redis create --name mtech-saas-redis --region "$REGION" || \
  echo "⚠️  Redis existe peut-être déjà"

# ─── 6. Attacher la DB à l'API ──────────────────────────────────────────
echo "→ Attachement PostgreSQL à l'API..."
flyctl mpg attach mtech-saas-db --app "$API_APP" || true

echo "→ Attachement Redis à l'API..."
flyctl redis attach mtech-saas-redis --app "$API_APP" || true

# ─── 7. Attacher la DB au Worker ────────────────────────────────────────
echo "→ Attachement PostgreSQL au Worker..."
flyctl mpg attach mtech-saas-db --app "$WORKER_APP" || true

echo "→ Attachement Redis au Worker..."
flyctl redis attach mtech-saas-redis --app "$WORKER_APP" || true

# ─── 8. Configurer les secrets ──────────────────────────────────────────
echo ""
echo "🔐 Configuration des secrets..."
echo "→ Les secrets doivent être configurés via 'flyctl secrets set' (voir README)"
echo ""
echo "Commandes à exécuter manuellement :"
echo ""
echo "  flyctl secrets set -a $API_APP \\"
echo "    JWT_PRIVATE_KEY=\"...\" \\"
echo "    JWT_PUBLIC_KEY=\"...\" \\"
echo "    ENCRYPTION_KEY=\"...\" \\"
echo "    WAVE_WEBHOOK_SECRET=\"...\" \\"
echo "    ORANGE_WEBHOOK_SECRET=\"...\" \\"
echo "    MTN_WEBHOOK_SECRET=\"...\" \\"
echo "    MOOV_WEBHOOK_SECRET=\"...\" \\"
echo "    OPENAI_API_KEY=\"...\" \\"
echo "    FOUNDER_EMAIL=\"daniel@mtech.ci\""
echo ""
echo "  flyctl secrets set -a $WORKER_APP \\"
echo "    JWT_PRIVATE_KEY=\"...\" \\"
echo "    ENCRYPTION_KEY=\"...\" \\"
echo "    OPENAI_API_KEY=\"...\""
echo ""
echo "✅ Setup Fly.io terminé."
echo "→ Déploie avec : flyctl deploy --config fly.toml"
