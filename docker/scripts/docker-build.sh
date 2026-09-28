#!/usr/bin/env bash
# =============================================================================
# Build + push de l'image API/worker vers un registry.
# Usage : ./scripts/docker-build.sh [tag]
# Ex    : ./scripts/docker-build.sh v0.1.0
# =============================================================================
set -euo pipefail

TAG="${1:-latest}"
REGISTRY="${IMAGE_REGISTRY:-mtech}"
IMAGE_NAME="${REGISTRY}/saas-api"

echo "🔨 Build image ${IMAGE_NAME}:${TAG}..."
docker build \
  --platform linux/amd64 \
  -t "${IMAGE_NAME}:${TAG}" \
  -t "${IMAGE_NAME}:latest" \
  -f Dockerfile \
  .

echo "🚀 Push ${IMAGE_NAME}:${TAG}..."
docker push "${IMAGE_NAME}:${TAG}"
docker push "${IMAGE_NAME}:latest"

echo "✅ Image poussée : ${IMAGE_NAME}:${TAG}"
echo "→ Déploiement : IMAGE_TAG=${TAG} docker compose -f docker-compose.prod.yml up -d"
