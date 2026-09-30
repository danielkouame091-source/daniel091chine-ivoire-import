"""
Service Marketplace — Catalogue, Publishers, Installations, Reviews.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.marketplace_syscohada import (
    Certification,
    DELAI_REMBOURSEMENT_JOURS,
    ModeleTarification,
    PERMISSIONS_SENSIBLES,
    REVENUE_SHARE_MTECH_PCT,
    REVENUE_SHARE_PUBLISHER_PCT,
    SEUIL_SIGNALEMENTS_SUSPENSION,
    StatutExtension,
    StatutInstallation,
    StatutPublisher,
    TypeExtension,
    TypeTransactionMarketplace,
)
from app.models.marketplace import (
    DeveloperApiToken,
    Extension,
    ExtensionInstallation,
    ExtensionReport,
    ExtensionReview,
    ExtensionVersion,
    MarketplaceTransaction,
    Publisher,
)
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.marketplace import (
    ExtensionCreateIn,
    ExtensionUpdateIn,
    ExtensionVersionPublishIn,
    InstallationCreateIn,
    InstallationUpdateIn,
    PublisherRegisterIn,
    PublisherUpdateIn,
    ReviewCreateIn,
)
from app.services.audit_service import AuditService
from app.services.crypto_service import CryptoService

logger = logging.getLogger(__name__)


class MarketplaceService:
    def __init__(self, db: AsyncSession, user_id: UUID | None = None) -> None:
        self.db = db
        self.user_id = user_id
        self.audit = AuditService(db)
        self.crypto = CryptoService()

    # ═════════════════════════════════════════════════════════════════════
    # PUBLISHERS
    # ═════════════════════════════════════════════════════════════════════
    async def enregistrer_publisher(
        self, data: PublisherRegisterIn
    ) -> Publisher:
        existing = await self.db.scalar(
            select(Publisher.id).where(
                or_(Publisher.slug == data.slug, Publisher.email == data.email)
            )
        )
        if existing:
            raise HTTPException(409, "Slug ou email déjà utilisé")

        publisher = Publisher(
            slug=data.slug,
            nom=data.nom,
            description=data.description,
            email=data.email,
            telephone=data.telephone,
            site_web=data.site_web,
            type_publisher=data.type_publisher,
            pays=data.pays,
            numero_contribuable=data.numero_contribuable,
            rccm=data.rccm,
            user_id=self.user_id,
            statut=StatutPublisher.EN_ATTENTE,
        )
        self.db.add(publisher)
        await self.db.flush()

        await self.audit.log(
            tenant_id=None,
            user_id=self.user_id,
            action="MARKETPLACE_PUBLISHER_REGISTER",
            ressource="publisher",
            ressource_id=publisher.id,
            payload={"slug": publisher.slug, "nom": publisher.nom},
        )
        return publisher

    async def modifier_publisher(
        self, publisher_id: UUID, data: PublisherUpdateIn
    ) -> Publisher:
        pub = await self._get_publisher(publisher_id)
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(pub, k, v)
        await self.db.flush()
        return pub

    async def verifier_publisher(
        self, publisher_id: UUID, certification: str = "verifie"
    ) -> Publisher:
        """Action fondateur : vérifier un publisher."""
        pub = await self._get_publisher(publisher_id)
        pub.statut = StatutPublisher.VERIFIE
        pub.certification = certification
        pub.verification_at = datetime.now(timezone.utc)
        pub.verifie_par_user_id = self.user_id
        await self.db.flush()
        return pub

    async def lister_publishers(
        self, statut: str | None = None
    ) -> list[Publisher]:
        stmt = select(Publisher)
        if statut:
            stmt = stmt.where(Publisher.statut == statut)
        stmt = stmt.order_by(desc(Publisher.nb_installations_total))
        return list((await self.db.execute(stmt)).scalars().all())

    # ═════════════════════════════════════════════════════════════════════
    # EXTENSIONS
    # ═════════════════════════════════════════════════════════════════════
    async def creer_extension(
        self, publisher_id: UUID, data: ExtensionCreateIn
    ) -> Extension:
        pub = await self._get_publisher(publisher_id)
        if pub.statut == StatutPublisher.SUSPENDU:
            raise HTTPException(403, "Publisher suspendu")

        # Unicité globale du slug
        existing = await self.db.scalar(
            select(Extension.id).where(Extension.slug == data.slug)
        )
        if existing:
            raise HTTPException(409, f"Slug {data.slug} déjà utilisé")

        # Vérifier permissions valides
        from app.core.marketplace_syscohada import PermissionExtension
        valid_perms = {v for k, v in PermissionExtension.__dict__.items()
                       if not k.startswith("_") and isinstance(v, str)}
        for p in data.permissions:
            if p not in valid_perms:
                raise HTTPException(400, f"Permission invalide : {p}")

        extension = Extension(
            publisher_id=pub.id,
            slug=data.slug,
            nom=data.nom,
            resume=data.resume,
            description=data.description,
            type_extension=data.type_extension,
            categorie=data.categorie,
            tags=data.tags,
            icone_url=data.icone_url,
            logo_url=data.logo_url,
            captures_urls=data.captures_urls,
            video_url=data.video_url,
            version_actuelle=data.version_actuelle,
            version_min_mtech=data.version_min_mtech,
            modele_tarification=data.modele_tarification,
            prix_mensuel_xof=data.prix_mensuel_xof,
            prix_annuel_xof=data.prix_annuel_xof,
            prix_unique_xof=data.prix_unique_xof,
            essai_gratuit_jours=data.essai_gratuit_jours,
            permissions=data.permissions,
            hooks=data.hooks,
            cgu_url=data.cgu_url,
            politique_confidentialite_url=data.politique_confidentialite_url,
            support_url=data.support_url,
            documentation_url=data.documentation_url,
            config_schema=data.config_schema,
            ui_extensions=data.ui_extensions,
            statut=StatutExtension.BROUILLON,
            certification=Certification.NON_CERTIFIE,
        )
        self.db.add(extension)
        await self.db.flush()

        await self.audit.log(
            tenant_id=None,
            user_id=self.user_id,
            action="MARKETPLACE_EXTENSION_CREATE",
            ressource="extension",
            ressource_id=extension.id,
            payload={"slug": extension.slug, "type": extension.type_extension},
        )
        return extension

    async def modifier_extension(
        self, extension_id: UUID, data: ExtensionUpdateIn
    ) -> Extension:
        ext = await self._get_extension(extension_id)
        if ext.statut == StatutExtension.ARCHIVEE:
            raise HTTPException(400, "Extension archivée — non modifiable")
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(ext, k, v)
        await self.db.flush()
        return ext

    async def soumettre_extension(self, extension_id: UUID) -> Extension:
        ext = await self._get_extension(extension_id)
        if ext.statut not in (StatutExtension.BROUILLON, StatutExtension.REJETEE):
            raise HTTPException(400, f"Extension déjà {ext.statut}")

        # Vérifications basiques
        if not ext.cgu_url or not ext.politique_confidentialite_url:
            raise HTTPException(400, "CGU et politique de confidentialité obligatoires")

        ext.statut = StatutExtension.EN_REVISION
        await self.db.flush()
        return ext

    async def approuver_extension(
        self, extension_id: UUID, certification: str | None = None
    ) -> Extension:
        """Action fondateur."""
        ext = await self._get_extension(extension_id)
        ext.statut = StatutExtension.APPROUVEE
        ext.approuvee_at = datetime.now(timezone.utc)
        ext.approuvee_par_user_id = self.user_id
        if certification:
            ext.certification = certification
        await self.db.flush()
        return ext

    async def rejeter_extension(
        self, extension_id: UUID, motif: str
    ) -> Extension:
        ext = await self._get_extension(extension_id)
        ext.statut = StatutExtension.REJETEE
        ext.motif_rejet = motif
        await self.db.flush()
        return ext

    async def lister_extensions(
        self,
        categorie: str | None = None,
        type_extension: str | None = None,
        statut: str | None = None,
        search: str | None = None,
        epinglees_seulement: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Extension], int]:
        stmt = select(Extension)
        count_stmt = select(func.count(Extension.id))

        if statut:
            stmt = stmt.where(Extension.statut == statut)
            count_stmt = count_stmt.where(Extension.statut == statut)
        else:
            # Par défaut, seulement les approuvées
            stmt = stmt.where(Extension.statut == StatutExtension.APPROUVEE)
            count_stmt = count_stmt.where(Extension.statut == StatutExtension.APPROUVEE)

        if categorie:
            stmt = stmt.where(Extension.categorie == categorie)
            count_stmt = count_stmt.where(Extension.categorie == categorie)
        if type_extension:
            stmt = stmt.where(Extension.type_extension == type_extension)
            count_stmt = count_stmt.where(Extension.type_extension == type_extension)
        if epinglees_seulement:
            stmt = stmt.where(Extension.epinglee.is_(True))
            count_stmt = count_stmt.where(Extension.epinglee.is_(True))
        if search:
            search_pattern = f"%{search}%"
            stmt = stmt.where(or_(
                Extension.nom.ilike(search_pattern),
                Extension.resume.ilike(search_pattern),
                Extension.description.ilike(search_pattern),
            ))
            count_stmt = count_stmt.where(or_(
                Extension.nom.ilike(search_pattern),
                Extension.resume.ilike(search_pattern),
                Extension.description.ilike(search_pattern),
            ))

        total = int(await self.db.scalar(count_stmt) or 0)
        stmt = stmt.order_by(
            Extension.epinglee.desc(),
            Extension.nb_installations.desc(),
            Extension.note_moyenne.desc(),
        ).limit(limit).offset(offset)

        rows = list((await self.db.execute(stmt)).scalars().all())
        return rows, total

    async def get_extension_by_slug(self, slug: str) -> Extension:
        ext = await self.db.scalar(
            select(Extension).where(Extension.slug == slug)
        )
        if ext is None:
            raise HTTPException(404, "Extension introuvable")

        # Incrémenter les vues
        ext.nb_vues += 1
        await self.db.flush()
        return ext

    # ═════════════════════════════════════════════════════════════════════
    # VERSIONS
    # ═════════════════════════════════════════════════════════════════════
    async def publier_version(
        self, extension_id: UUID, data: ExtensionVersionPublishIn
    ) -> ExtensionVersion:
        ext = await self._get_extension(extension_id)

        # Vérifier unicité
        existing = await self.db.scalar(
            select(ExtensionVersion.id).where(
                ExtensionVersion.extension_id == ext.id,
                ExtensionVersion.version == data.version,
            )
        )
        if existing:
            raise HTTPException(409, f"Version {data.version} existe déjà")

        version = ExtensionVersion(
            extension_id=ext.id,
            version=data.version,
            changelog=data.changelog,
            manifest=ext.config_schema,   # Snapshot du manifest actuel
            bundle_url=data.bundle_url,
            bundle_hash=data.bundle_hash,
            bundle_size_kb=data.bundle_size_kb,
            version_min_mtech=data.version_min_mtech,
            breaking_changes=data.breaking_changes,
            statut="publiee",
            publiee_at=datetime.now(timezone.utc),
            est_stable=True,
            publiee_par_user_id=self.user_id,
        )
        self.db.add(version)

        # Mettre à jour la version courante
        ext.version_actuelle = data.version
        await self.db.flush()
        return version

    # ═════════════════════════════════════════════════════════════════════
    # INSTALLATIONS
    # ═════════════════════════════════════════════════════════════════════
    async def installer(
        self, tenant_id: UUID, data: InstallationCreateIn
    ) -> ExtensionInstallation:
        ext = await self._get_extension(data.extension_id)

        if ext.statut != StatutExtension.APPROUVEE:
            raise HTTPException(400, f"Extension {ext.statut} — non installable")

        # Vérifier si déjà installée
        existing = await self.db.scalar(
            select(ExtensionInstallation).where(
                ExtensionInstallation.tenant_id == tenant_id,
                ExtensionInstallation.extension_id == ext.id,
                ExtensionInstallation.statut != StatutInstallation.DESINSTALLEE,
            )
        )
        if existing:
            raise HTTPException(409, "Extension déjà installée")

        # Choisir la version
        version_id = data.version_id
        if not version_id:
            latest = await self.db.scalar(
                select(ExtensionVersion).where(
                    ExtensionVersion.extension_id == ext.id,
                    ExtensionVersion.est_stable.is_(True),
                    ExtensionVersion.statut == "publiee",
                ).order_by(desc(ExtensionVersion.publiee_at)).limit(1)
            )
            if latest is None:
                raise HTTPException(400, "Aucune version stable disponible")
            version_id = latest.id

        # Permissions
        perms = data.permissions_accordees or ext.permissions

        # Période d'essai
        now = datetime.now(timezone.utc)
        essai_fin = None
        if ext.essai_gratuit_jours > 0:
            essai_fin = (now + timedelta(days=ext.essai_gratuit_jours)).date()

        # Abonnement
        abonnement_debut = None
        abonnement_fin = None
        prix_paye = 0
        if ext.modele_tarification == ModeleTarification.ABONNEMENT:
            abonnement_debut = now.date()
            abonnement_fin = (now + timedelta(days=30)).date()
            prix_paye = ext.prix_mensuel_xof or 0
        elif ext.modele_tarification == ModeleTarification.ONE_TIME:
            prix_paye = ext.prix_unique_xof or 0

        # Créer l'installation
        installation = ExtensionInstallation(
            tenant_id=tenant_id,
            extension_id=ext.id,
            version_id=version_id,
            config=data.config,
            permissions_accordees=perms,
            statut=StatutInstallation.EN_COURS,
            abonnement_debut=abonnement_debut,
            abonnement_fin=abonnement_fin,
            essai_fin=essai_fin,
            prix_paye_xof=prix_paye,
            mode_paiement=data.mode_paiement,
            webhook_url=data.webhook_url,
            installee_par_user_id=self.user_id,
        )
        self.db.add(installation)
        await self.db.flush()

        # Chiffrer les secrets
        if data.secrets:
            for key, value in data.secrets.items():
                from app.models.marketplace import InstallationSecret
                secret = InstallationSecret(
                    installation_id=installation.id,
                    tenant_id=tenant_id,
                    cle=key,
                    valeur_chiffree=self.crypto.encrypt(value),
                )
                self.db.add(secret)

        # Mettre à jour les stats
        ext.nb_installations += 1
        ext.nb_installations_actives += 1
        installation.statut = StatutInstallation.ACTIVE
        installation.activee_at = now
        await self.db.flush()

        # Créer une transaction si payant
        if prix_paye > 0:
            commission = int(prix_paye * REVENUE_SHARE_MTECH_PCT / 100)
            montant_pub = prix_paye - commission
            ref = f"MKT-{date.today().year}-{secrets.token_hex(4).upper()}"
            tx = MarketplaceTransaction(
                reference=ref,
                type_transaction=(TypeTransactionMarketplace.ACHAT_PLUGIN
                                  if ext.modele_tarification == ModeleTarification.ONE_TIME
                                  else TypeTransactionMarketplace.ABONNEMENT_PLUGIN),
                tenant_id=tenant_id,
                publisher_id=ext.publisher_id,
                installation_id=installation.id,
                montant_total_xof=prix_paye,
                commission_mtech_xof=commission,
                montant_publisher_xof=montant_pub,
                mode_paiement=data.mode_paiement or "virement",
                statut="payee",
                payee_at=now,
            )
            self.db.add(tx)

            # Mettre à jour le publisher
            pub = await self._get_publisher(ext.publisher_id)
            pub.revenus_total_xof += montant_pub
            pub.revenus_en_attente_xof += montant_pub
            pub.nb_installations_total += 1

        await self.db.flush()

        await self.audit.log(
            tenant_id=tenant_id,
            user_id=self.user_id,
            action="MARKETPLACE_EXTENSION_INSTALL",
            ressource="extension_installation",
            ressource_id=installation.id,
            payload={
                "extension_slug": ext.slug,
                "version_id": str(version_id),
                "prix_paye": prix_paye,
            },
        )

        # Déclencher le hook APP_INSTALLED (async)
        await self._trigger_hook(
            installation.id, tenant_id, "app.installed",
            {"installation_id": str(installation.id), "extension_slug": ext.slug},
        )

        return installation

    async def modifier_installation(
        self, installation_id: UUID, data: InstallationUpdateIn
    ) -> ExtensionInstallation:
        inst = await self._get_installation(installation_id)
        for k, v in data.model_dump(exclude_unset=True).items():
            if k == "secrets" and v:
                for key, value in v.items():
                    await self._upsert_secret(inst, key, value)
            else:
                setattr(inst, k, value)
        await self.db.flush()
        return inst

    async def activer_installation(
        self, installation_id: UUID
    ) -> ExtensionInstallation:
        inst = await self._get_installation(installation_id)
        inst.statut = StatutInstallation.ACTIVE
        inst.activee_at = datetime.now(timezone.utc)
        await self.db.flush()

        await self._trigger_hook(
            inst.id, inst.tenant_id, "app.enabled",
            {"installation_id": str(inst.id)},
        )
        return inst

    async def desactiver_installation(
        self, installation_id: UUID, motif: str | None = None
    ) -> ExtensionInstallation:
        inst = await self._get_installation(installation_id)
        inst.statut = StatutInstallation.DESACTIVEE
        inst.desactivee_at = datetime.now(timezone.utc)
        inst.motif_desactivation = motif
        await self.db.flush()

        await self._trigger_hook(
            inst.id, inst.tenant_id, "app.disabled",
            {"installation_id": str(inst.id), "motif": motif},
        )
        return inst

    async def desinstaller(
        self, installation_id: UUID, motif: str | None = None
    ) -> ExtensionInstallation:
        inst = await self._get_installation(installation_id)

        # Hook avant désinstallation
        await self._trigger_hook(
            inst.id, inst.tenant_id, "app.uninstalled",
            {"installation_id": str(inst.id), "motif": motif},
        )

        inst.statut = StatutInstallation.DESINSTALLEE
        inst.desinstallee_at = datetime.now(timezone.utc)
        inst.desinstallee_par_user_id = self.user_id
        inst.motif_desinstallation = motif

        # Mettre à jour les stats de l'extension
        ext = await self._get_extension(inst.extension_id)
        ext.nb_installations_actives = max(0, ext.nb_installations_actives - 1)

        await self.db.flush()
        return inst

    async def lister_installations(
        self, tenant_id: UUID, statut: str | None = None
    ) -> list[ExtensionInstallation]:
        stmt = select(ExtensionInstallation).where(
            ExtensionInstallation.tenant_id == tenant_id
        )
        if statut:
            stmt = stmt.where(ExtensionInstallation.statut == statut)
        stmt = stmt.order_by(desc(ExtensionInstallation.created_at))
        return list((await self.db.execute(stmt)).scalars().all())

    # ═════════════════════════════════════════════════════════════════════
    # REVIEWS
    # ═════════════════════════════════════════════════════════════════════
    async def laisser_avis(
        self, tenant_id: UUID, extension_id: UUID, data: ReviewCreateIn
    ) -> ExtensionReview:
        ext = await self._get_extension(extension_id)

        # Vérifier que l'extension est installée
        inst = await self.db.scalar(
            select(ExtensionInstallation).where(
                ExtensionInstallation.tenant_id == tenant_id,
                ExtensionInstallation.extension_id == ext.id,
                ExtensionInstallation.statut == StatutInstallation.ACTIVE,
            )
        )
        if inst is None:
            raise HTTPException(400, "Vous devez avoir installé l'extension pour la noter")

        # Vérifier pas déjà noté
        existing = await self.db.scalar(
            select(ExtensionReview).where(
                ExtensionReview.extension_id == ext.id,
                ExtensionReview.tenant_id == tenant_id,
            )
        )
        if existing:
            raise HTTPException(409, "Vous avez déjà laissé un avis")

        # Récupérer le nom de l'auteur
        auteur = await self.db.scalar(select(User).where(User.id == self.user_id))
        auteur_nom = auteur.nom_complet if auteur else "Utilisateur anonyme"

        review = ExtensionReview(
            extension_id=ext.id,
            tenant_id=tenant_id,
            installation_id=inst.id,
            auteur_user_id=self.user_id,
            auteur_nom=auteur_nom,
            note=data.note,
            titre=data.titre,
            commentaire=data.commentaire,
        )
        self.db.add(review)
        await self.db.flush()

        # Mettre à jour la note moyenne
        await self._recalculer_note_moyenne(ext.id)

        return review

    async def _recalculer_note_moyenne(self, extension_id: UUID) -> None:
        result = await self.db.execute(
            select(
                func.avg(ExtensionReview.note),
                func.count(ExtensionReview.id),
            ).where(
                ExtensionReview.extension_id == extension_id,
                ExtensionReview.visible.is_(True),
            )
        )
        row = result.one()
        moyenne = float(row[0] or 0)
        count = int(row[1] or 0)

        ext = await self.db.scalar(select(Extension).where(Extension.id == extension_id))
        if ext:
            ext.note_moyenne = round(moyenne, 2)
            ext.nb_avis = count
            await self.db.flush()

    async def repondre_avis(
        self, review_id: UUID, reponse: str
    ) -> ExtensionReview:
        review = await self.db.scalar(
            select(ExtensionReview).where(ExtensionReview.id == review_id)
        )
        if review is None:
            raise HTTPException(404, "Avis introuvable")
        review.reponse_publisher = reponse
        review.reponse_at = datetime.now(timezone.utc)
        await self.db.flush()
        return review

    async def lister_avis(
        self, extension_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[ExtensionReview]:
        stmt = (
            select(ExtensionReview)
            .where(
                ExtensionReview.extension_id == extension_id,
                ExtensionReview.visible.is_(True),
            )
            .order_by(desc(ExtensionReview.created_at))
            .limit(limit)
            .offset(offset)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    # ═════════════════════════════════════════════════════════════════════
    # SIGNALEMENTS
    # ═════════════════════════════════════════════════════════════════════
    async def signaler_extension(
        self, extension_id: UUID, motif: str, description: str,
        tenant_id: UUID | None = None,
    ) -> ExtensionReport:
        ext = await self._get_extension(extension_id)

        report = ExtensionReport(
            extension_id=ext.id,
            tenant_id=tenant_id,
            reported_by_user_id=self.user_id,
            motif=motif,
            description=description,
        )
        self.db.add(report)
        await self.db.flush()

        # Auto-suspension si seuil atteint
        count = int(await self.db.scalar(
            select(func.count(ExtensionReport.id)).where(
                ExtensionReport.extension_id == ext.id,
                ExtensionReport.statut == "nouveau",
            )
        ) or 0)
        if count >= SEUIL_SIGNALEMENTS_SUSPENSION:
            logger.warning(
                f"[marketplace] ⚠️ Extension {ext.slug} a atteint "
                f"{count} signalements — review manuelle requise"
            )

        return report

    # ═════════════════════════════════════════════════════════════════════
    # TOKENS DÉVELOPPEUR
    # ═════════════════════════════════════════════════════════════════════
    async def creer_token_dev(
        self, publisher_id: UUID, nom: str, environnement: str,
        scopes: list[str], expire_at: datetime | None = None,
    ) -> tuple[DeveloperApiToken, str]:
        pub = await self._get_publisher(publisher_id)

        token_plain = f"mtech_dev_{secrets.token_urlsafe(32)}"
        token_hash = hashlib.sha256(token_plain.encode()).hexdigest()

        token = DeveloperApiToken(
            publisher_id=pub.id,
            nom=nom,
            token_hash=token_hash,
            token_prefix=token_plain[:20],
            environnement=environnement,
            scopes=scopes,
            expire_at=expire_at,
            actif=True,
        )
        self.db.add(token)
        await self.db.flush()
        return token, token_plain

    async def lister_tokens_dev(
        self, publisher_id: UUID
    ) -> list[DeveloperApiToken]:
        stmt = select(DeveloperApiToken).where(
            DeveloperApiToken.publisher_id == publisher_id,
        ).order_by(desc(DeveloperApiToken.created_at))
        return list((await self.db.execute(stmt)).scalars().all())

    # ═════════════════════════════════════════════════════════════════════
    # DASHBOARDS
    # ═════════════════════════════════════════════════════════════════════
    async def dashboard_fondateur(self) -> dict[str, Any]:
        today = date.today()
        debut_mois = today.replace(day=1)
        debut_mois_dt = datetime.combine(debut_mois, datetime.min.time()).replace(tzinfo=timezone.utc)

        nb_ext_total = int(await self.db.scalar(
            select(func.count(Extension.id))
        ) or 0)
        nb_ext_publiees = int(await self.db.scalar(
            select(func.count(Extension.id)).where(
                Extension.statut == StatutExtension.APPROUVEE,
            )
        ) or 0)
        nb_ext_review = int(await self.db.scalar(
            select(func.count(Extension.id)).where(
                Extension.statut == StatutExtension.EN_REVISION,
            )
        ) or 0)

        nb_publishers = int(await self.db.scalar(
            select(func.count(Publisher.id))
        ) or 0)
        nb_publishers_verifies = int(await self.db.scalar(
            select(func.count(Publisher.id)).where(
                Publisher.statut.in_([StatutPublisher.VERIFIE, StatutPublisher.PARTENAIRE]),
            )
        ) or 0)

        nb_install_total = int(await self.db.scalar(
            select(func.count(ExtensionInstallation.id))
        ) or 0)
        nb_install_actives = int(await self.db.scalar(
            select(func.count(ExtensionInstallation.id)).where(
                ExtensionInstallation.statut == StatutInstallation.ACTIVE,
            )
        ) or 0)

        revenus_mois = int(await self.db.scalar(
            select(func.coalesce(func.sum(MarketplaceTransaction.montant_total_xof), 0)).where(
                MarketplaceTransaction.created_at >= debut_mois_dt,
                MarketplaceTransaction.type_transaction.in_([
                    TypeTransactionMarketplace.ACHAT_PLUGIN,
                    TypeTransactionMarketplace.ABONNEMENT_PLUGIN,
                ]),
                MarketplaceTransaction.statut == "payee",
            )
        ) or 0)

        commissions_mois = int(await self.db.scalar(
            select(func.coalesce(func.sum(MarketplaceTransaction.commission_mtech_xof), 0)).where(
                MarketplaceTransaction.created_at >= debut_mois_dt,
                MarketplaceTransaction.statut == "payee",
            )
        ) or 0)

        reversements_attente = int(await self.db.scalar(
            select(func.coalesce(func.sum(Publisher.revenus_en_attente_xof), 0))
        ) or 0)

        # Top extensions
        top_ext_rows = (
            await self.db.execute(
                select(
                    Extension.slug, Extension.nom,
                    Extension.nb_installations_actives, Extension.note_moyenne,
                )
                .where(Extension.statut == StatutExtension.APPROUVEE)
                .order_by(desc(Extension.nb_installations_actives))
                .limit(10)
            )
        ).all()
        top_ext = [
            {"slug": r[0], "nom": r[1], "installations": int(r[2]), "note": float(r[3])}
            for r in top_ext_rows
        ]

        # Top publishers
        top_pub_rows = (
            await self.db.execute(
                select(
                    Publisher.slug, Publisher.nom,
                    Publisher.nb_installations_total, Publisher.revenus_total_xof,
                )
                .order_by(desc(Publisher.revenus_total_xof))
                .limit(10)
            )
        ).all()
        top_pub = [
            {"slug": r[0], "nom": r[1], "installations": int(r[2]), "revenus": int(r[3])}
            for r in top_pub_rows
        ]

        signalements = int(await self.db.scalar(
            select(func.count(ExtensionReport.id)).where(
                ExtensionReport.statut == "nouveau",
            )
        ) or 0)

        return {
            "date_arret": today,
            "nb_extensions_total": nb_ext_total,
            "nb_extensions_publiees": nb_ext_publiees,
            "nb_extensions_en_revision": nb_ext_review,
            "nb_publishers": nb_publishers,
            "nb_publishers_verifies": nb_publishers_verifies,
            "nb_installations_total": nb_install_total,
            "nb_installations_actives": nb_install_actives,
            "revenus_mois_xof": revenus_mois,
            "commissions_mois_xof": commissions_mois,
            "reversements_attente_xof": reversements_attente,
            "top_extensions": top_ext,
            "top_publishers": top_pub,
            "signalements_ouverts": signalements,
        }

    async def dashboard_publisher(self, publisher_id: UUID) -> dict[str, Any]:
        pub = await self._get_publisher(publisher_id)
        today = date.today()
        debut_mois = today.replace(day=1)
        debut_mois_dt = datetime.combine(debut_mois, datetime.min.time()).replace(tzinfo=timezone.utc)

        nb_ext = int(await self.db.scalar(
            select(func.count(Extension.id)).where(Extension.publisher_id == pub.id)
        ) or 0)

        revenus_mois = int(await self.db.scalar(
            select(func.coalesce(func.sum(MarketplaceTransaction.montant_publisher_xof), 0)).where(
                MarketplaceTransaction.publisher_id == pub.id,
                MarketplaceTransaction.created_at >= debut_mois_dt,
                MarketplaceTransaction.statut == "payee",
            )
        ) or 0)

        top_ext_rows = (
            await self.db.execute(
                select(
                    Extension.slug, Extension.nom,
                    Extension.nb_installations_actives, Extension.note_moyenne,
                )
                .where(Extension.publisher_id == pub.id)
                .order_by(desc(Extension.nb_installations_actives))
                .limit(10)
            )
        ).all()
        top_ext = [
            {"slug": r[0], "nom": r[1], "installations": int(r[2]), "note": float(r[3])}
            for r in top_ext_rows
        ]

        derniers_tx = (
            await self.db.execute(
                select(MarketplaceTransaction)
                .where(MarketplaceTransaction.publisher_id == pub.id)
                .order_by(desc(MarketplaceTransaction.created_at))
                .limit(10)
            )
        ).scalars().all()

        signalements = int(await self.db.scalar(
            select(func.count(ExtensionReport.id))
            .join(Extension, Extension.id == ExtensionReport.extension_id)
            .where(
                Extension.publisher_id == pub.id,
                ExtensionReport.statut == "nouveau",
            )
        ) or 0)

        return {
            "publisher_id": pub.id,
            "nb_extensions": nb_ext,
            "nb_installations_total": pub.nb_installations_total,
            "nb_installations_actives": int(await self.db.scalar(
                select(func.coalesce(func.sum(Extension.nb_installations_actives), 0))
                .where(Extension.publisher_id == pub.id)
            ) or 0),
            "revenus_total_xof": pub.revenus_total_xof,
            "revenus_mois_xof": revenus_mois,
            "revenus_en_attente_xof": pub.revenus_en_attente_xof,
            "note_moyenne": float(pub.note_moyenne),
            "top_extensions": top_ext,
            "dernieres_transactions": derniers_tx,
            "signalements_ouverts": signalements,
        }

    # ═════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═════════════════════════════════════════════════════════════════════
    async def _get_publisher(self, publisher_id: UUID) -> Publisher:
        pub = await self.db.scalar(
            select(Publisher).where(Publisher.id == publisher_id)
        )
        if pub is None:
            raise HTTPException(404, "Publisher introuvable")
        return pub

    async def _get_extension(self, extension_id: UUID) -> Extension:
        ext = await self.db.scalar(
            select(Extension).where(Extension.id == extension_id)
        )
        if ext is None:
            raise HTTPException(404, "Extension introuvable")
        return ext

    async def _get_installation(self, installation_id: UUID) -> ExtensionInstallation:
        inst = await self.db.scalar(
            select(ExtensionInstallation).where(ExtensionInstallation.id == installation_id)
        )
        if inst is None:
            raise HTTPException(404, "Installation introuvable")
        return inst

    async def _upsert_secret(
        self, installation: ExtensionInstallation, cle: str, valeur: str
    ) -> None:
        from app.models.marketplace import InstallationSecret
        existing = await self.db.scalar(
            select(InstallationSecret).where(
                InstallationSecret.installation_id == installation.id,
                InstallationSecret.cle == cle,
            )
        )
        if existing:
            existing.valeur_chiffree = self.crypto.encrypt(valeur)
            existing.derniere_rotation_at = datetime.now(timezone.utc)
        else:
            self.db.add(InstallationSecret(
                installation_id=installation.id,
                tenant_id=installation.tenant_id,
                cle=cle,
                valeur_chiffree=self.crypto.encrypt(valeur),
            ))
        await self.db.flush()

    async def _trigger_hook(
        self, installation_id: UUID, tenant_id: UUID,
        hook_event: str, payload: dict[str, Any],
    ) -> None:
        """Enqueue l'exécution d'un hook (asynchrone)."""
        try:
            from arq import create_pool
            from app.workers.arq_settings import WorkerSettings
            redis = await create_pool(WorkerSettings.redis_settings)
            await redis.enqueue_job(
                "executer_hook_plugin",
                str(installation_id),
                str(tenant_id),
                hook_event,
                payload,
            )
            await redis.aclose()
        except Exception:
            logger.exception(
                f"[marketplace] Échec enqueue hook {hook_event} "
                f"pour installation {installation_id}"
            )
