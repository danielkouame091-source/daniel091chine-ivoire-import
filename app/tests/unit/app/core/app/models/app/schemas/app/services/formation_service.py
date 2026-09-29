"""
Service Formation & Support — Base documentaire, tutoriels, onboarding.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, desc, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.formation_syscohada import (
    CATEGORIES_PRIORITAIRES,
    StatutPublication,
)
from app.models.formation import (
    Article,
    ArticleCategory,
    OnboardingPath,
    TutorialStep,
    UserArticleProgress,
    UserOnboardingProgress,
)
from app.models.user import User
from app.schemas.formation import (
    ArticleCategoryCreate,
    ArticleCreate,
    ArticleFeedbackIn,
    ArticleOut,
    ArticleProgressIn,
    ArticleSearchResult,
    ArticleUpdate,
    OnboardingPathCreate,
    OnboardingProgressOut,
    TutorialStepCreate,
)
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class FormationService:
    def __init__(self, db: AsyncSession, tenant_id: UUID | None, user_id: UUID | None) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.audit = AuditService(db)

    # ═════════════════════════════════════════════════════════════════════
    # CATÉGORIES
    # ═════════════════════════════════════════════════════════════════════
    async def creer_categorie(self, data: ArticleCategoryCreate) -> ArticleCategory:
        existing = await self.db.scalar(
            select(ArticleCategory.id).where(ArticleCategory.code == data.code)
        )
        if existing:
            raise HTTPException(409, f"Catégorie {data.code} déjà existante")

        cat = ArticleCategory(**data.model_dump())
        self.db.add(cat)
        await self.db.flush()
        return cat

    async def lister_categories(self) -> list[ArticleCategory]:
        stmt = (
            select(ArticleCategory)
            .where(ArticleCategory.actif.is_(True))
            .order_by(ArticleCategory.ordre, ArticleCategory.code)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    # ═════════════════════════════════════════════════════════════════════
    # ARTICLES
    # ═════════════════════════════════════════════════════════════════════
    async def creer_article(self, data: ArticleCreate) -> Article:
        # Vérifier unicité slug
        existing = await self.db.scalar(
            select(Article.id).where(Article.slug == data.slug)
        )
        if existing:
            raise HTTPException(409, f"Slug {data.slug} déjà utilisé")

        # Vérifier catégorie
        cat = await self.db.scalar(
            select(ArticleCategory).where(ArticleCategory.id == data.category_id)
        )
        if cat is None:
            raise HTTPException(404, "Catégorie introuvable")

        article = Article(
            tenant_id=None,   # Article global par défaut
            **data.model_dump(),
            statut=StatutPublication.BROUILLON,
            auteur_user_id=self.user_id,
        )
        self.db.add(article)
        await self.db.flush()

        # Mise à jour du search_vector
        await self._update_search_vector(article.id)

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="ARTICLE_CREATE",
            ressource="article",
            ressource_id=article.id,
            payload={"slug": article.slug, "titre": article.titre},
        )
        return article

    async def modifier_article(self, article_id: UUID, data: ArticleUpdate) -> Article:
        article = await self._get_article(article_id)
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(article, k, v)

        # Si passage à "publié", set publie_at
        if data.statut == StatutPublication.PUBLIE and article.publie_at is None:
            article.publie_at = datetime.now(timezone.utc)

        article.version += 1
        await self.db.flush()
        await self._update_search_vector(article.id)
        return article

    async def publier_article(self, article_id: UUID) -> Article:
        article = await self._get_article(article_id)
        if article.statut == StatutPublication.PUBLIE:
            return article
        article.statut = StatutPublication.PUBLIE
        article.publie_at = datetime.now(timezone.utc)
        await self.db.flush()
        return article

    async def _update_search_vector(self, article_id: UUID) -> None:
        """
        Met à jour le tsvector pour la recherche full-text (français).
        Utilise la config 'french' de PostgreSQL.
        """
        await self.db.execute(
            text("""
                UPDATE articles
                SET search_vector = to_tsvector('french',
                    COALESCE(titre, '') || ' ' ||
                    COALESCE(resume, '') || ' ' ||
                    COALESCE(contenu, '') || ' ' ||
                    COALESCE(array_to_string(tags, ' '), '')
                )
                WHERE id = :aid
            """),
            {"aid": article_id},
        )

    async def rechercher(
        self, q: str, categorie: str | None = None, limit: int = 20
    ) -> list[ArticleSearchResult]:
        """
        Recherche full-text avec ranking ts_rank.
        """
        if not q or len(q.strip()) < 2:
            return []

        # Nettoyer la requête
        query = q.strip()

        sql = """
            SELECT id, slug, titre, resume, type_contenu,
                   ts_rank(search_vector, plainto_tsquery('french', :q)) AS score,
                   ts_headline('french', contenu, plainto_tsquery('french', :q),
                               'StartSel=<mark>, StopSel=</mark>, MaxWords=40') AS extrait
            FROM articles
            WHERE statut = 'publie'
              AND search_vector @@ plainto_tsquery('french', :q)
        """
        params: dict[str, Any] = {"q": query}

        if categorie:
            sql += """
                AND category_id IN (
                    SELECT id FROM article_categories WHERE code = :cat
                )
            """
            params["cat"] = categorie

        sql += " ORDER BY score DESC LIMIT :limit"
        params["limit"] = limit

        rows = (await self.db.execute(text(sql), params)).all()

        results: list[ArticleSearchResult] = []
        for r in rows:
            results.append(ArticleSearchResult(
                article={
                    "id": str(r.id),
                    "slug": r.slug,
                    "titre": r.titre,
                    "resume": r.resume,
                    "type_contenu": r.type_contenu,
                },
                score=float(r.score or 0),
                extrait=r.extrait,
            ))
        return results

    async def lister_articles(
        self, categorie: str | None = None, role: str | None = None,
        epingle_only: bool = False, limit: int = 100,
    ) -> list[Article]:
        stmt = select(Article).where(Article.statut == StatutPublication.PUBLIE)
        if categorie:
            stmt = stmt.join(ArticleCategory, ArticleCategory.id == Article.category_id).where(
                ArticleCategory.code == categorie
            )
        if epingle_only:
            stmt = stmt.where(Article.epingle.is_(True))
        if role:
            # Filtre JSONB : l'article est visible si roles_cibles contient 'tous' ou le rôle
            stmt = stmt.where(
                or_(
                    Article.roles_cibles.contains(["tous"]),
                    Article.roles_cibles.contains([role]),
                )
            )
        stmt = stmt.order_by(desc(Article.epingle), Article.ordre, desc(Article.nb_vues)).limit(limit)
        return list((await self.db.execute(stmt)).scalars().all())

    async def get_article_detail(self, slug: str) -> Article:
        article = await self.db.scalar(
            select(Article).where(
                Article.slug == slug,
                Article.statut == StatutPublication.PUBLIE,
            )
        )
        if article is None:
            raise HTTPException(404, "Article introuvable")

        # Incrémenter les vues (compteur global)
        article.nb_vues += 1
        await self.db.flush()

        # Tracker la vue utilisateur
        if self.user_id:
            await self._tracker_vue_user(article.id)

        return article

    async def _tracker_vue_user(self, article_id: UUID) -> None:
        """Enregistre une vue utilisateur (upsert)."""
        existing = await self.db.scalar(
            select(UserArticleProgress).where(
                UserArticleProgress.user_id == self.user_id,
                UserArticleProgress.article_id == article_id,
            )
        )
        now = datetime.now(timezone.utc)
        if existing:
            existing.nb_vues += 1
            existing.vu = True
            existing.vu_at = now
        else:
            self.db.add(UserArticleProgress(
                tenant_id=self.tenant_id,
                user_id=self.user_id,
                article_id=article_id,
                vu=True,
                vu_at=now,
                nb_vues=1,
            ))
        await self.db.flush()

    async def donner_feedback(
        self, article_id: UUID, data: ArticleFeedbackIn
    ) -> Article:
        """Enregistre le feedback d'un utilisateur sur un article."""
        article = await self._get_article(article_id)

        # Mettre à jour les compteurs globaux
        if data.utile:
            article.nb_utile += 1
        else:
            article.nb_non_utile += 1

        # Mettre à jour la progression utilisateur
        if self.user_id:
            existing = await self.db.scalar(
                select(UserArticleProgress).where(
                    UserArticleProgress.user_id == self.user_id,
                    UserArticleProgress.article_id == article_id,
                )
            )
            now = datetime.now(timezone.utc)
            note = 1 if data.utile else -1
            if existing:
                existing.note_utilite = note
                existing.feedback_texte = data.commentaire
            else:
                self.db.add(UserArticleProgress(
                    tenant_id=self.tenant_id,
                    user_id=self.user_id,
                    article_id=article_id,
                    note_utilite=note,
                    feedback_texte=data.commentaire,
                    vu=True,
                    vu_at=now,
                ))

        await self.db.flush()
        return article

    async def mettre_a_jour_progression(
        self, article_id: UUID, data: ArticleProgressIn
    ) -> UserArticleProgress:
        """Met à jour la progression d'un utilisateur sur un article/tutoriel."""
        if self.user_id is None:
            raise HTTPException(401, "Utilisateur non authentifié")

        progress = await self.db.scalar(
            select(UserArticleProgress).where(
                UserArticleProgress.user_id == self.user_id,
                UserArticleProgress.article_id == article_id,
            )
        )

        if progress is None:
            progress = UserArticleProgress(
                tenant_id=self.tenant_id,
                user_id=self.user_id,
                article_id=article_id,
                vu=True,
                vu_at=datetime.now(timezone.utc),
                nb_vues=1,
            )
            self.db.add(progress)
            await self.db.flush()

        if data.etape_completee is not None:
            if data.etape_completee not in (progress.etapes_completees or []):
                progress.etapes_completees = (progress.etapes_completees or []) + [data.etape_completee]

        if data.etape_actuelle is not None:
            progress.etape_actuelle = data.etape_actuelle

        if data.termine:
            progress.termine = True
            progress.termine_at = datetime.now(timezone.utc)

        if data.duree_passee_s is not None:
            progress.duree_passee_s += data.duree_passee_s

        if data.note_utilite is not None:
            progress.note_utilite = data.note_utilite
        if data.feedback_texte is not None:
            progress.feedback_texte = data.feedback_texte

        await self.db.flush()
        return progress

    # ═════════════════════════════════════════════════════════════════════
    # ÉTAPES DE TUTORIEL
    # ═════════════════════════════════════════════════════════════════════
    async def creer_etape(self, article_id: UUID, data: TutorialStepCreate) -> TutorialStep:
        article = await self._get_article(article_id)
        existing = await self.db.scalar(
            select(TutorialStep.id).where(
                TutorialStep.article_id == article.id,
                TutorialStep.ordre == data.ordre,
            )
        )
        if existing:
            raise HTTPException(409, f"Ordre {data.ordre} déjà utilisé")

        step = TutorialStep(article_id=article.id, **data.model_dump())
        self.db.add(step)
        await self.db.flush()
        return step

    async def lister_etapes(self, article_id: UUID) -> list[TutorialStep]:
        stmt = (
            select(TutorialStep)
            .where(TutorialStep.article_id == article_id)
            .order_by(TutorialStep.ordre)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    # ═════════════════════════════════════════════════════════════════════
    # ONBOARDING
    # ═════════════════════════════════════════════════════════════════════
    async def creer_parcours(self, data: OnboardingPathCreate) -> OnboardingPath:
        existing = await self.db.scalar(
            select(OnboardingPath.id).where(OnboardingPath.code == data.code)
        )
        if existing:
            raise HTTPException(409, f"Parcours {data.code} déjà existant")

        path = OnboardingPath(**data.model_dump())
        self.db.add(path)
        await self.db.flush()
        return path

    async def lister_parcours(
        self, role: str | None = None, type_parcours: str | None = None
    ) -> list[OnboardingPath]:
        stmt = select(OnboardingPath).where(OnboardingPath.actif.is_(True))
        if role:
            stmt = stmt.where(
                or_(
                    OnboardingPath.role_cible == role,
                    OnboardingPath.role_cible == "tous",
                )
            )
        if type_parcours:
            stmt = stmt.where(OnboardingPath.parcours_type == type_parcours)
        stmt = stmt.order_by(OnboardingPath.ordre)
        return list((await self.db.execute(stmt)).scalars().all())

    async def demarrer_parcours(self, path_id: UUID) -> UserOnboardingProgress:
        """Démarre un parcours pour l'utilisateur courant."""
        if self.user_id is None:
            raise HTTPException(401, "Utilisateur non authentifié")

        path = await self.db.scalar(
            select(OnboardingPath).where(OnboardingPath.id == path_id)
        )
        if path is None:
            raise HTTPException(404, "Parcours introuvable")

        existing = await self.db.scalar(
            select(UserOnboardingProgress).where(
                UserOnboardingProgress.user_id == self.user_id,
                UserOnboardingProgress.path_id == path_id,
            )
        )
        if existing:
            return existing

        progress = UserOnboardingProgress(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            path_id=path_id,
            demarre_at=datetime.now(timezone.utc),
            pourcentage=0,
            etapes_completees=[],
        )
        self.db.add(progress)
        await self.db.flush()
        return progress

    async def completer_etape_onboarding(
        self, path_id: UUID, etape_key: str
    ) -> UserOnboardingProgress:
        """Marque une étape comme complétée et recalcule le pourcentage."""
        if self.user_id is None:
            raise HTTPException(401, "Utilisateur non authentifié")

        path = await self.db.scalar(
            select(OnboardingPath).where(OnboardingPath.id == path_id)
        )
        if path is None:
            raise HTTPException(404, "Parcours introuvable")

        progress = await self.db.scalar(
            select(UserOnboardingProgress).where(
                UserOnboardingProgress.user_id == self.user_id,
                UserOnboardingProgress.path_id == path_id,
            )
        )
        if progress is None:
            progress = await self.demarrer_parcours(path_id)

        # Vérifier que l'étape existe
        etapes_config = path.etapes or []
        valid_keys = {e.get("key") for e in etapes_config}
        if etape_key not in valid_keys:
            raise HTTPException(400, f"Étape '{etape_key}' inconnue")

        # Ajouter si pas déjà complétée
        existing_keys = {e["key"] for e in (progress.etapes_completees or [])}
        if etape_key not in existing_keys:
            progress.etapes_completees = (progress.etapes_completees or []) + [{
                "key": etape_key,
                "done": True,
                "done_at": datetime.now(timezone.utc).isoformat(),
            }]

        # Recalcul du pourcentage
        done = len(progress.etapes_completees or [])
        total = len(etapes_config)
        progress.pourcentage = round(done / total * 100, 2) if total > 0 else 0
        progress.derniere_etape = etape_key

        # Marquer comme terminé si 100%
        if progress.pourcentage >= 100 and progress.termine_at is None:
            progress.termine_at = datetime.now(timezone.utc)

        await self.db.flush()
        return progress

    async def get_progression_onboarding(
        self, path_id: UUID
    ) -> UserOnboardingProgress | None:
        if self.user_id is None:
            return None
        return await self.db.scalar(
            select(UserOnboardingProgress).where(
                UserOnboardingProgress.user_id == self.user_id,
                UserOnboardingProgress.path_id == path_id,
            )
        )

    async def lister_progressions_onboarding(self) -> list[UserOnboardingProgress]:
        if self.user_id is None:
            return []
        stmt = (
            select(UserOnboardingProgress)
            .where(UserOnboardingProgress.user_id == self.user_id)
            .order_by(UserOnboardingProgress.demarre_at.desc())
        )
        return list((await self.db.execute(stmt)).scalars().all())

    # ═════════════════════════════════════════════════════════════════════
    # SEED — Contenu initial
    # ═════════════════════════════════════════════════════════════════════
    async def seed_categories_defaut(self) -> int:
        """Initialise les catégories d'articles par défaut."""
        from app.core.formation_syscohada import CategorieArticle

        CATEGORIES = {
            CategorieArticle.DEMARRAGE: ("Démarrage", "Premiers pas avec MTech", "rocket", "#3B82F6", 1),
            CategorieArticle.COMPTABILITE: ("Comptabilité", "Écritures SYSCOHADA, balance, états", "book-open", "#10B981", 2),
            CategorieArticle.FISCALITE: ("Fiscalité", "TVA, IS, ITS, DGI", "receipt", "#F59E0B", 3),
            CategorieArticle.SOCIAL: ("Social", "Paie, CNPS, ITS salaires", "users", "#8B5CF6", 4),
            CategorieArticle.STOCKS: ("Stocks", "Entrées, sorties, inventaire", "package", "#EC4899", 5),
            CategorieArticle.IMMOBILISATIONS: ("Immobilisations", "Amortissements, cessions", "building", "#6366F1", 6),
            CategorieArticle.VENTES: ("Ventes", "Clients, factures, relances", "shopping-cart", "#EF4444", 7),
            CategorieArticle.ACHATS: ("Achats", "Fournisseurs, commandes", "truck", "#14B8A6", 8),
            CategorieArticle.TRESORERIE: ("Trésorerie", "Banque, rapprochement", "landmark", "#0EA5E9", 9),
            CategorieArticle.ANALYTIQUE: ("Analytique", "Budget, centres de coût", "pie-chart", "#F97316", 10),
            CategorieArticle.CONSOLIDATION: ("Consolidation", "Groupes, filiales", "layers", "#A855F7", 11),
            CategorieArticle.FNE: ("Facture FNE", "e-Invoicing DGI", "file-check", "#22C55E", 12),
            CategorieArticle.AUDIT: ("Audit", "Contrôle interne, piste d'audit", "shield-check", "#EAB308", 13),
            CategorieArticle.PROJETS: ("Projets", "Chantiers, situations de travaux", "hard-hat", "#DC2626", 14),
            CategorieArticle.IA: ("Intelligence artificielle", "Saisie magique, prévisions", "sparkles", "#7C3AED", 15),
            CategorieArticle.MOBILE_MONEY: ("Mobile Money", "Wave, Orange, MTN, Moov", "smartphone", "#06B6D4", 16),
            CategorieArticle.SECURITE: ("Sécurité", "MFA, sessions, RGPD", "lock", "#64748B", 17),
            CategorieArticle.ABONNEMENT: ("Abonnement", "Facturation SaaS, plans", "credit-card", "#0891B2", 18),
            CategorieArticle.INTEGRATIONS: ("Intégrations", "WhatsApp, API, exports", "plug", "#84CC16", 19),
            CategorieArticle.AVANCE: ("Fonctions avancées", "Consolidation, multi-devises", "zap", "#FBBF24", 20),
        }

        existing_codes = set(
            (await self.db.execute(select(ArticleCategory.code))).scalars().all()
        )

        created = 0
        for code, (libelle, description, icone, couleur, ordre) in CATEGORIES.items():
            if code in existing_codes:
                continue
            self.db.add(ArticleCategory(
                code=code,
                libelle=libelle,
                description=description,
                icone=icone,
                couleur=couleur,
                ordre=ordre,
            ))
            created += 1

        await self.db.flush()
        return created

    async def seed_articles_demarrage(self) -> int:
        """
        Crée les articles de démarrage prioritaires.
        ⚠️ Le contenu réel est à rédiger par l'équipe produit.
        """
        cat = await self.db.scalar(
            select(ArticleCategory).where(ArticleCategory.code == "demarrage")
        )
        if cat is None:
            return 0

        ARTICLES = [
            {
                "slug": "creer-mon-compte-entreprise",
                "titre": "Créer mon compte entreprise",
                "resume": "Guide pas-à-pas pour créer votre compte MTech et configurer votre entreprise.",
                "contenu": "# Créer mon compte entreprise\n\n## Étape 1 : Inscription\n...",
                "type_contenu": "article",
                "niveau_difficulte": "debutant",
                "tags": ["démarrage", "compte", "inscription"],
                "modules_lies": ["auth", "tenants"],
                "ordre": 1,
                "epingle": True,
                "obligatoire_onboarding": True,
            },
            {
                "slug": "importer-plan-comptable-syscohada",
                "titre": "Importer mon plan comptable SYSCOHADA",
                "resume": "Comment importer le plan comptable SYSCOHADA révisé en quelques clics.",
                "contenu": "# Importer mon plan comptable\n\n...",
                "type_contenu": "tutoriel",
                "niveau_difficulte": "debutant",
                "tags": ["syscohada", "plan-comptable", "import"],
                "modules_lies": ["plan_comptable"],
                "ordre": 2,
                "obligatoire_onboarding": True,
            },
            {
                "slug": "saisir-premiere-ecriture-ia",
                "titre": "Saisir ma première écriture avec l'IA",
                "resume": "Découvrez la saisie magique : décrivez en français, l'IA crée l'écriture.",
                "contenu": "# Saisie magique avec l'IA\n\n...",
                "type_contenu": "tutoriel",
                "niveau_difficulte": "debutant",
                "tags": ["ia", "nlp", "saisie-magique"],
                "modules_lies": ["ia"],
                "ordre": 3,
                "epingle": True,
            },
            {
                "slug": "inviter-collaborateurs",
                "titre": "Inviter mes collaborateurs",
                "resume": "Ajouter vos comptables, auditeurs et lecteurs avec les bons rôles.",
                "contenu": "# Inviter mes collaborateurs\n\n...",
                "type_contenu": "article",
                "niveau_difficulte": "debutant",
                "tags": ["collaborateurs", "roles", "invitation"],
                "modules_lies": ["users"],
                "ordre": 4,
            },
        ]

        existing_slugs = set(
            (await self.db.execute(select(Article.slug))).scalars().all()
        )

        created = 0
        for a in ARTICLES:
            if a["slug"] in existing_slugs:
                continue
            article = Article(
                tenant_id=None,
                category_id=cat.id,
                statut=StatutPublication.PUBLIE,
                publie_at=datetime.now(timezone.utc),
                auteur_user_id=self.user_id,
                **a,
            )
            self.db.add(article)
            await self.db.flush()
            await self._update_search_vector(article.id)
            created += 1

        return created

    async def seed_parcours_onboarding(self) -> int:
        """Initialise les parcours d'onboarding par défaut."""
        PARCOURS = [
            {
                "code": "ONB-NEW-TENANT",
                "libelle": "Bien démarrer avec MTech",
                "description": "Parcours obligatoire pour configurer votre entreprise",
                "parcours_type": "nouveau_tenant",
                "role_cible": "admin_tenant",
                "ordre": 1,
                "etapes": [
                    {"key": "profil_complet", "libelle": "Compléter le profil de l'entreprise", "article_slug": "creer-mon-compte-entreprise", "obligatoire": True},
                    {"key": "plan_comptable", "libelle": "Importer le plan comptable SYSCOHADA", "article_slug": "importer-plan-comptable-syscohada", "obligatoire": True},
                    {"key": "exercice", "libelle": "Créer le premier exercice comptable", "article_slug": None, "obligatoire": True},
                    {"key": "premier_client", "libelle": "Créer mon premier client", "article_slug": None, "obligatoire": False},
                    {"key": "premiere_ecriture", "libelle": "Saisir ma première écriture", "article_slug": "saisir-premiere-ecriture-ia", "obligatoire": True},
                    {"key": "inviter_equipe", "libelle": "Inviter mon équipe", "article_slug": "inviter-collaborateurs", "obligatoire": False},
                    {"key": "abonnement", "libelle": "Choisir un plan d'abonnement", "article_slug": None, "obligatoire": True},
                ],
            },
            {
                "code": "ONB-FNE",
                "libelle": "Activer la facturation normalisée (FNE)",
                "description": "Configurer l'interfaçage DGI pour la FNE",
                "parcours_type": "activation_fne",
                "role_cible": "admin_tenant",
                "ordre": 2,
                "etapes": [
                    {"key": "ncc", "libelle": "Renseigner le NCC de l'entreprise", "obligatoire": True},
                    {"key": "cle_api_dgi", "libelle": "Obtenir et saisir la clé API DGI", "obligatoire": True},
                    {"key": "test_sandbox", "libelle": "Tester en environnement sandbox", "obligatoire": True},
                    {"key": "certifier_facture", "libelle": "Certifier la première facture", "obligatoire": True},
                    {"key": "sticker_achat", "libelle": "Acheter des stickers FNE", "obligatoire": True},
                ],
            },
            {
                "code": "ONB-MM",
                "libelle": "Connecter Mobile Money",
                "description": "Configurer Wave / Orange Money / MTN / Moov",
                "parcours_type": "config_mm",
                "role_cible": "admin_tenant",
                "ordre": 3,
                "etapes": [
                    {"key": "wave_secret", "libelle": "Configurer le secret Wave", "obligatoire": False},
                    {"key": "om_secret", "libelle": "Configurer le secret Orange Money", "obligatoire": False},
                    {"key": "test_webhook", "libelle": "Tester le webhook", "obligatoire": True},
                ],
            },
        ]

        existing_codes = set(
            (await self.db.execute(select(OnboardingPath.code))).scalars().all()
        )

        created = 0
        for p in PARCOURS:
            if p["code"] in existing_codes:
                continue
            self.db.add(OnboardingPath(**p))
            created += 1

        await self.db.flush()
        return created

    # ═════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═════════════════════════════════════════════════════════════════════
    async def _get_article(self, article_id: UUID) -> Article:
        a = await self.db.scalar(
            select(Article).where(Article.id == article_id)
        )
        if a is None:
            raise HTTPException(404, "Article introuvable")
        return a

    @staticmethod
    def _normaliser(s: str) -> str:
        s = s.lower()
        s = unicodedata.normalize("NFD", s)
        s = "".join(c for c in s if unicodedata.category(c) != "Mn")
        s = re.sub(r"[^a-z0-9\s]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s
