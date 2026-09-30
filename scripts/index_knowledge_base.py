"""
Indexe la base de connaissance MTech dans pgvector.
À exécuter une fois au déploiement + après chaque mise à jour majeure.

Usage :
    python -m scripts.index_knowledge_base
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from app.db.session import AsyncSessionLocal
from app.models.embeddings import KnowledgeDocument
from app.services.embedding_service import EmbeddingService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def index_articles_mtech(db):
    """Indexe les articles de la base documentaire MTech (brique 25)."""
    from sqlalchemy import select
    from app.models.formation import Article

    articles = (await db.execute(
        select(Article).where(Article.statut == "publie")
    )).scalars().all()

    svc = EmbeddingService(db, tenant_id=None)
    for article in articles:
        await svc.indexer_document(
            titre=article.titre,
            contenu=article.contenu,
            source_type="article_doc",
            source_id=article.id,
            categorie=article.category_id.hex if hasattr(article, "category_id") else None,
            langue=article.langue if hasattr(article, "langue") else "fr",
        )
        logger.info(f"  ✓ {article.titre[:60]}")


async def index_regles_syscohada(db):
    """Indexe les règles SYSCOHADA et fiscales CI (statique)."""
    REGLES = [
        {
            "titre": "Principe de la partie double",
            "contenu": (
                "En SYSCOHADA, toute écriture comptable respecte le principe de la partie double : "
                "le total des débits est toujours égal au total des crédits. Cette règle est "
                "fondamentale et aucune exception n'est admise. Toute écriture déséquilibrée est rejetée."
            ),
            "categorie": "syscohada_base",
        },
        {
            "titre": "TVA en Côte d'Ivoire",
            "contenu": (
                "Le taux normal de TVA en Côte d'Ivoire est de 18%. Le taux réduit est de 9%. "
                "La déclaration TVA est trimestrielle et doit être déposée avant le 10 du mois "
                "suivant le trimestre. Comptes : 443xxx pour la TVA collectée, 445xxx pour la TVA déductible."
            ),
            "categorie": "fiscalite_ci",
        },
        {
            "titre": "Calcul de l'ITS en Côte d'Ivoire",
            "contenu": (
                "L'ITS (Impôt sur les Traitements et Salaires) est calculé selon un barème progressif "
                "depuis la réforme de 2023. Les tranches vont de 0% (jusqu'à 75 000 FCFA) jusqu'à 32% "
                "(au-delà de 8 000 000 FCFA). Un abattement de 20% pour frais professionnels s'applique "
                "dans la limite de 50 000 FCFA. La réduction RICF s'applique selon le nombre de parts fiscales."
            ),
            "categorie": "fiscalite_ci",
        },
        {
            "titre": "Comptabilisation des stocks",
            "contenu": (
                "SYSCOHADA admet deux méthodes : CUMP (par défaut) et FIFO. La méthode est permanente : "
                "le CUMP est recalculé après chaque entrée. À la clôture, la variation de stock est "
                "constatée en compte 603x (comptes de variation). Le compte 311x enregistre le stock de "
                "marchandises à l'actif."
            ),
            "categorie": "syscohada_stocks",
        },
        {
            "titre": "Rapprochement bancaire",
            "contenu": (
                "Le rapprochement bancaire compare le solde comptable (compte 521x) au solde du relevé "
                "bancaire. Les écarts proviennent généralement de chèques non encaissés, virements en "
                "cours, frais bancaires non comptabilisés. Le compte 471800 est utilisé pour les écarts "
                "en attente de régularisation."
            ),
            "categorie": "tresorerie",
        },
    ]

    svc = EmbeddingService(db, tenant_id=None)
    for r in REGLES:
        await svc.indexer_document(
            titre=r["titre"],
            contenu=r["contenu"],
            source_type="regle_metier",
            categorie=r["categorie"],
            langue="fr",
        )
        logger.info(f"  ✓ Règle : {r['titre']}")


async def main():
    async with AsyncSessionLocal() as db:
        logger.info("=== Indexation de la base de connaissance ===")

        # Purge optionnelle (attention en prod !)
        if "--reset" in sys.argv:
            logger.warning("⚠️ Purge des documents existants...")
            from sqlalchemy import delete
            await db.execute(delete(KnowledgeDocument).where(
                KnowledgeDocument.tenant_id.is_(None)
            ))
            await db.commit()

        logger.info("→ Articles MTech")
        await index_articles_mtech(db)

        logger.info("→ Règles SYSCOHADA / Fiscalité CI")
        await index_regles_syscohada(db)

        await db.commit()
        logger.info("✅ Indexation terminée.")


if __name__ == "__main__":
    asyncio.run(main())
