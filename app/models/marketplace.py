"""Modèles Marketplace — Publishers, Extensions, Installations, Reviews."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index,
    Integer, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


# ─────────────────────────────────────────────────────────────────────────────
# PUBLISHER
# ─────────────────────────────────────────────────────────────────────────────
class Publisher(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Éditeur d'extensions — développeur individuel ou entreprise.
    """
    __tablename__ = "marketplace_publishers"

    # Identité
    slug: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    nom: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    site_web: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Contact
    email: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)
    telephone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    adresse: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Type
    type_publisher: Mapped[str] = mapped_column(
        String(20), nullable=False, default="individuel", server_default="individuel"
    )   # individuel | entreprise | partenaire

    # Informations légales / fiscales
    pays: Mapped[str] = mapped_column(String(2), nullable=False, default="CI", server_default="CI")
    numero_contribuable: Mapped[str | None] = mapped_column(String(50), nullable=True)
    rccm: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Informations bancaires (paiement des revenus)
    iban: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mode_paiement: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # wave | orange_money | mtn_momo | virement

    # Compte utilisateur lié (auth)
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Statut
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="en_attente", server_default="en_attente"
    )
    verification_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verifie_par_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    # Certification
    certification: Mapped[str] = mapped_column(
        String(30), nullable=False, default="non_certifie", server_default="non_certifie"
    )

    # Stats
    nb_extensions_publiees: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    nb_installations_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    note_moyenne: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False, default=0, server_default="0")

    # Revenus accumulés
    revenus_total_xof: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    revenus_versees_xof: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    revenus_en_attente_xof: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_publisher_statut", "statut"),
        Index("idx_publisher_certification", "certification"),
    )

    def __repr__(self) -> str:
        return f"<Publisher {self.slug} — {self.nom}>"


# ─────────────────────────────────────────────────────────────────────────────
# EXTENSION
# ─────────────────────────────────────────────────────────────────────────────
class Extension(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Extension (plugin ou intégration) publiée dans le catalogue.
    """
    __tablename__ = "marketplace_extensions"

    publisher_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("marketplace_publishers.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # Identification
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    nom: Mapped[str] = mapped_column(String(200), nullable=False)
    resume: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Classification
    type_extension: Mapped[str] = mapped_column(String(30), nullable=False)
    categorie: Mapped[str] = mapped_column(String(30), nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")

    # Visuels
    icone_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    captures_urls: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    video_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Version courante
    version_actuelle: Mapped[str] = mapped_column(String(20), nullable=False)
    version_min_mtech: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Tarification
    modele_tarification: Mapped[str] = mapped_column(String(20), nullable=False)
    prix_mensuel_xof: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    prix_annuel_xof: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    prix_unique_xof: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    essai_gratuit_jours: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Permissions déclarées
    permissions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    hooks: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")

    # URLs légales
    cgu_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    politique_confidentialite_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    support_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    documentation_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Configuration
    config_schema: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    ui_extensions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    # Statut
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="brouillon", server_default="brouillon"
    )
    approuvee_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approuvee_par_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    motif_rejet: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Certification
    certification: Mapped[str] = mapped_column(
        String(30), nullable=False, default="non_certifie", server_default="non_certifie"
    )

    # Stats (dénormalisées)
    nb_installations: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    nb_installations_actives: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    nb_vues: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    note_moyenne: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False, default=0, server_default="0")
    nb_avis: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Mise en avant
    epinglee: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    featured_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    ordre_affichage: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Métadonnées
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("publisher_id", "slug", name="uq_extension_publisher_slug"),
        Index("idx_ext_statut", "statut"),
        Index("idx_ext_categorie", "categorie", "statut"),
        Index("idx_ext_type", "type_extension", "statut"),
        Index("idx_ext_featured", "epinglee", "featured_until"),
    )

    def __repr__(self) -> str:
        return f"<Extension {self.slug} v{self.version_actuelle}>"


# ─────────────────────────────────────────────────────────────────────────────
# VERSION D'EXTENSION
# ─────────────────────────────────────────────────────────────────────────────
class ExtensionVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Version publiée d'une extension (semver).
    """
    __tablename__ = "marketplace_extension_versions"

    extension_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("marketplace_extensions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    version: Mapped[str] = mapped_column(String(20), nullable=False)
    changelog: Mapped[str] = mapped_column(Text, nullable=False)

    # Artefacts
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    bundle_url: Mapped[str] = mapped_column(Text, nullable=False)   # S3 URL du code
    bundle_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    bundle_size_kb: Mapped[int] = mapped_column(Integer, nullable=False)

    # Compatibilité
    version_min_mtech: Mapped[str | None] = mapped_column(String(20), nullable=True)
    breaking_changes: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Statut
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="brouillon", server_default="brouillon"
    )
    publiee_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Adoption
    nb_installations: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    est_stable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    # Auteur
    publiee_par_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("extension_id", "version", name="uq_ext_version"),
        Index("idx_ext_version_ext", "extension_id", "publiee_at"),
    )

    def __repr__(self) -> str:
        return f"<ExtensionVersion {self.extension_id} v{self.version}>"


# ─────────────────────────────────────────────────────────────────────────────
# INSTALLATION
# ─────────────────────────────────────────────────────────────────────────────
class ExtensionInstallation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Installation d'une extension par un tenant.
    """
    __tablename__ = "marketplace_installations"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    extension_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("marketplace_extensions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("marketplace_extension_versions.id"),
        nullable=False,
    )

    # Configuration du tenant (remplie via config_schema)
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    config_secrets_enc: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Les secrets (clés API) sont chiffrés séparément

    # Permissions accordées (par le tenant)
    permissions_accordees: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    # Statut
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="en_cours", server_default="en_cours"
    )
    activee_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    desactivee_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    motif_desactivation: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Abonnement (si payant)
    abonnement_debut: Mapped[date | None] = mapped_column(Date, nullable=True)
    abonnement_fin: Mapped[date | None] = mapped_column(Date, nullable=True)
    essai_fin: Mapped[date | None] = mapped_column(Date, nullable=True)
    prix_paye_xof: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    mode_paiement: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Webhook URL (si config fournie par le plugin)
    webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Usage
    nb_appels_jour: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    nb_erreurs_jour: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    dernier_appel_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    derniere_erreur_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    derniere_erreur: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Installation / désinstallation
    installee_par_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    desinstallee_par_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    desinstallee_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    motif_desinstallation: Mapped[str | None] = mapped_column(Text, nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "extension_id", name="uq_install_tenant_ext"),
        Index("idx_install_tenant_statut", "tenant_id", "statut"),
        Index("idx_install_ext", "extension_id", "statut"),
        Index("idx_install_abonnement_fin", "abonnement_fin"),
    )

    def __repr__(self) -> str:
        return f"<Installation tenant={self.tenant_id} ext={self.extension_id} ({self.statut})>"


# ─────────────────────────────────────────────────────────────────────────────
# LOG D'EXÉCUTION (hooks)
# ─────────────────────────────────────────────────────────────────────────────
class HookExecution(UUIDPrimaryKeyMixin, Base):
    """
    Journal d'exécution d'un hook.
    """
    __tablename__ = "marketplace_hook_executions"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    installation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("marketplace_installations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    hook_event: Mapped[str] = mapped_column(String(50), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False)

    # Payload
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload_size_kb: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Résultat
    statut: Mapped[str] = mapped_column(String(20), nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    latence_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    erreur: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Retry
    nb_tentatives: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    # Traçabilité
    source_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    source_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("idx_hook_tenant_date", "tenant_id", "created_at"),
        Index("idx_hook_install_date", "installation_id", "created_at"),
        Index("idx_hook_event", "hook_event", "statut"),
    )

    def __repr__(self) -> str:
        return f"<HookExecution {self.hook_event} ({self.statut})>"


# ─────────────────────────────────────────────────────────────────────────────
# REVIEW / AVIS
# ─────────────────────────────────────────────────────────────────────────────
class ExtensionReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Avis d'un tenant sur une extension installée.
    """
    __tablename__ = "marketplace_extension_reviews"

    extension_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("marketplace_extensions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    installation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("marketplace_installations.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Auteur
    auteur_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    auteur_nom: Mapped[str] = mapped_column(String(200), nullable=False)

    # Note
    note: Mapped[int] = mapped_column(Integer, nullable=False)   # 1-5

    # Contenu
    titre: Mapped[str | None] = mapped_column(String(200), nullable=True)
    commentaire: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Utilité (votes)
    nb_utile: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    nb_non_utile: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Réponse du publisher
    reponse_publisher: Mapped[str | None] = mapped_column(Text, nullable=True)
    reponse_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Statut
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    signale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    motif_signalement: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("extension_id", "tenant_id", name="uq_review_ext_tenant"),
        Index("idx_review_ext_visible", "extension_id", "visible"),
        Index("idx_review_note", "extension_id", "note"),
    )

    def __repr__(self) -> str:
        return f"<ExtensionReview ext={self.extension_id} note={self.note}>"


# ─────────────────────────────────────────────────────────────────────────────
# TRANSACTION FINANCIÈRE
# ─────────────────────────────────────────────────────────────────────────────
class MarketplaceTransaction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Transaction financière (achat plugin, abonnement, reversement).
    """
    __tablename__ = "marketplace_transactions"

    reference: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    type_transaction: Mapped[str] = mapped_column(String(30), nullable=False)

    # Parties
    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    publisher_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("marketplace_publishers.id", ondelete="SET NULL"), nullable=True
    )
    installation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("marketplace_installations.id", ondelete="SET NULL"), nullable=True
    )

    # Montants
    montant_total_xof: Mapped[int] = mapped_column(BigInteger, nullable=False)
    commission_mtech_xof: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    montant_publisher_xof: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    # Paiement
    mode_paiement: Mapped[str] = mapped_column(String(20), nullable=False)
    reference_paiement: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # Statut
    statut: Mapped[str] = mapped_column(String(20), nullable=False)

    # Dates
    payee_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reversee_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    remboursee_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Remboursement
    motif_remboursement: Mapped[str | None] = mapped_column(Text, nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_mkt_tx_tenant", "tenant_id", "created_at"),
        Index("idx_mkt_tx_publisher", "publisher_id", "created_at"),
        Index("idx_mkt_tx_type_statut", "type_transaction", "statut"),
    )

    def __repr__(self) -> str:
        return f"<MarketplaceTransaction {self.reference} ({self.type_transaction})>"


# ─────────────────────────────────────────────────────────────────────────────
# SIGNALEMENT / SUSPENSION
# ─────────────────────────────────────────────────────────────────────────────
class ExtensionReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Signalement d'une extension (contenu inapproprié, sécurité, spam).
    """
    __tablename__ = "marketplace_extension_reports"

    extension_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("marketplace_extensions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    reported_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    motif: Mapped[str] = mapped_column(String(50), nullable=False)
    # securite | contenu | spam | arnaque | bug | violation_conditions

    description: Mapped[str] = mapped_column(Text, nullable=False)

    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="nouveau", server_default="nouveau"
    )
    # nouveau | en_examen | resolu | rejete

    traite_par_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    traite_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    action_prise: Mapped[str | None] = mapped_column(Text, nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_report_ext_statut", "extension_id", "statut"),
    )

    def __repr__(self) -> str:
        return f"<ExtensionReport ext={self.extension_id} motif={self.motif}>"


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION DES SECRETS (chiffrés par tenant)
# ─────────────────────────────────────────────────────────────────────────────
class InstallationSecret(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Secrets d'une installation (clés API chiffrées).
    """
    __tablename__ = "marketplace_installation_secrets"

    installation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("marketplace_installations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    cle: Mapped[str] = mapped_column(String(100), nullable=False)
    valeur_chiffree: Mapped[str] = mapped_column(Text, nullable=False)
    derniere_rotation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("installation_id", "cle", name="uq_install_secret_key"),
    )

    def __repr__(self) -> str:
        return f"<InstallationSecret installation={self.installation_id} key={self.cle}>"


# ─────────────────────────────────────────────────────────────────────────────
# SDK TOKENS (développeurs)
# ─────────────────────────────────────────────────────────────────────────────
class DeveloperApiToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Token API pour développeurs (test de plugin en sandbox).
    """
    __tablename__ = "marketplace_developer_tokens"

    publisher_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("marketplace_publishers.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    nom: Mapped[str] = mapped_column(String(200), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    token_prefix: Mapped[str] = mapped_column(String(20), nullable=False)

    # Environnement
    environnement: Mapped[str] = mapped_column(
        String(20), nullable=False, default="sandbox", server_default="sandbox"
    )

    # Scopes
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")

    # Statut
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    derniere_utilisation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_dev_token_publisher", "publisher_id", "actif"),
    )

    def __repr__(self) -> str:
        return f"<DeveloperApiToken {self.nom} ({self.environnement})>"
