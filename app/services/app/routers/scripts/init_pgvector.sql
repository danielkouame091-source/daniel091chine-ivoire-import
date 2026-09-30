-- =============================================================================
-- Initialisation pgvector — à exécuter UNE SEULE FOIS avant les migrations.
-- =============================================================================
CREATE EXTENSION IF NOT EXISTS vector;

-- Vérification
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';

-- ─── Index HNSW par défaut (créé par la migration Alembic) ───
-- Pour des performances optimales :
-- m = 16 (connexions par nœud) — augmenter pour + de précision, + de RAM
-- ef_construction = 64 — augmenter pour + de qualité, + de temps de build
