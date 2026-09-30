"""DTO Marketplace & Extensions."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, model_validator

TypeExtensionT = Literal[
    "plugin", "integration", "dashboard_widget", "report_template",
    "payment_gateway", "accounting_bridge", "tax_provider", "hr_connector",
    "ecommerce_connector", "whatsapp_bot", "theme",
]
CategorieT = Literal[
    "comptabilite", "fiscalite", "tresorerie", "ventes", "achats", "stocks",
    "rh", "analytique", "consolidation", "banque", "paiement", "data",
    "ia", "securite", "productivite", "communication", "ecommerce", "autre",
]
StatutExtensionT = Literal[
    "brouillon", "en_revision", "approuvee", "rejetee", "suspendue", "depreciee", "archivee",
]
ModeleTarifT = Literal["gratuit", "one_time", "abonnement", "freemium", "usage_based", "revenue_share"]
StatutInstallT = Literal["en_cours", "active", "desactivee", "erreur", "desinstallee", "expiree"]
StatutPublisherT = Literal["en_attente", "verifie", "partenaire", "suspendu", "banni"]
CertificationT = Literal["non_certifie", "verifie", "certifie", "partenaire_officiel"]


# ─────────────────────────────────────────────────────────────────────────────
# PUBLISHERS
# ─────────────────────────────────────────────────────────────────────────────
class PublisherRegisterIn(BaseModel):
    slug: str = Field(min_length=3, max_length=50, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
    nom: str = Field(min_length=2, max_length=200)
    description: str | None = None
    email: EmailStr
    telephone: str | None = None
    site_web: str | None = None
    type_publisher: Literal["individuel", "entreprise", "partenaire"] = "individuel"
    pays: str = Field("CI", min_length=2, max_length=2)
    numero_contribuable: str | None = None
    rccm: str | None = None


class PublisherUpdateIn(BaseModel):
    nom: str | None = None
    description: str | None = None
    logo_url: str | None = None
    site_web: str | None = None
    telephone: str | None = None
    iban: str | None = None
    mode_paiement: Literal["wave", "orange_money", "mtn_momo", "virement"] | None = None


class PublisherOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    slug: str
    nom: str
    description: str | None
    logo_url: str | None
    site_web: str | None
    email: str
    type_publisher: str
    pays: str
    statut: str
    certification: str
    nb_extensions_publiees: int
    nb_installations_total: int
    note_moyenne: float
    created_at: datetime


class PublisherDetailOut(PublisherOut):
    telephone: str | None
    adresse: dict[str, Any] | None
    revenus_total_xof: int
    revenus_versees_xof: int
    revenus_en_attente_xof: int


# ─────────────────────────────────────────────────────────────────────────────
# EXTENSIONS
# ─────────────────────────────────────────────────────────────────────────────
class ExtensionCreateIn(BaseModel):
    slug: str = Field(min_length=3, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
    nom: str = Field(min_length=2, max_length=200)
    resume: str = Field(min_length=10, max_length=300)
    description: str = Field(min_length=50)
    type_extension: TypeExtensionT
    categorie: CategorieT
    tags: list[str] = Field(default_factory=list)

    icone_url: str | None = None
    logo_url: str | None = None
    captures_urls: list[str] = Field(default_factory=list)
    video_url: str | None = None

    version_actuelle: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    version_min_mtech: str | None = None

    modele_tarification: ModeleTarifT
    prix_mensuel_xof: int | None = Field(None, ge=0)
    prix_annuel_xof: int | None = Field(None, ge=0)
    prix_unique_xof: int | None = Field(None, ge=0)
    essai_gratuit_jours: int = Field(0, ge=0, le=90)

    permissions: list[str] = Field(default_factory=list)
    hooks: list[str] = Field(default_factory=list)

    cgu_url: str | None = None
    politique_confidentialite_url: str | None = None
    support_url: str | None = None
    documentation_url: str | None = None

    config_schema: dict[str, Any] = Field(default_factory=dict)
    ui_extensions: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def coherent(self):
        if self.modele_tarification == "one_time" and not self.prix_unique_xof:
            raise ValueError("prix_unique_xof requis pour le mode one_time")
        if self.modele_tarification == "abonnement" and not self.prix_mensuel_xof:
            raise ValueError("prix_mensuel_xof requis pour le mode abonnement")
        return self


class ExtensionUpdateIn(BaseModel):
    nom: str | None = None
    resume: str | None = None
    description: str | None = None
    categorie: CategorieT | None = None
    tags: list[str] | None = None
    icone_url: str | None = None
    logo_url: str | None = None
    captures_urls: list[str] | None = None
    video_url: str | None = None
    modele_tarification: ModeleTarifT | None = None
    prix_mensuel_xof: int | None = None
    prix_annuel_xof: int | None = None
    prix_unique_xof: int | None = None
    essai_gratuit_jours: int | None = None
    permissions: list[str] | None = None
    hooks: list[str] | None = None
    cgu_url: str | None = None
    politique_confidentialite_url: str | None = None
    support_url: str | None = None
    documentation_url: str | None = None
    config_schema: dict[str, Any] | None = None
    ui_extensions: dict[str, Any] | None = None


class ExtensionBriefOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    slug: str
    nom: str
    resume: str
    type_extension: str
    categorie: str
    icone_url: str | None
    logo_url: str | None
    version_actuelle: str
    modele_tarification: str
    prix_mensuel_xof: int | None
    prix_unique_xof: int | None
    nb_installations: int
    note_moyenne: float
    nb_avis: int
    certification: str
    epinglee: bool


class ExtensionOut(ExtensionBriefOut):
    publisher_id: UUID
    description: str
    tags: list[str]
    captures_urls: list[str]
    video_url: str | None
    version_min_mtech: str | None
    prix_annuel_xof: int | None
    essai_gratuit_jours: int
    permissions: list[str]
    hooks: list[str]
    cgu_url: str | None
    politique_confidentialite_url: str | None
    support_url: str | None
    documentation_url: str | None
    config_schema: dict[str, Any]
    ui_extensions: dict[str, Any]
    statut: str
    approuvee_at: datetime | None
    nb_installations_actives: int
    nb_vues: int
    ordre_affichage: int
    created_at: datetime
    updated_at: datetime


class ExtensionDetailOut(ExtensionOut):
    publisher: PublisherOut | None = None
    derniere_version: "ExtensionVersionOut | None" = None
    reviews: list["ExtensionReviewOut"] = Field(default_factory=list)


class ExtensionVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    extension_id: UUID
    version: str
    changelog: str
    bundle_url: str
    bundle_hash: str
    bundle_size_kb: int
    version_min_mtech: str | None
    breaking_changes: bool
    statut: str
    publiee_at: datetime | None
    nb_installations: int
    est_stable: bool
    created_at: datetime


class ExtensionVersionPublishIn(BaseModel):
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    changelog: str = Field(min_length=10)
    bundle_url: str
    bundle_hash: str
    bundle_size_kb: int = Field(gt=0)
    version_min_mtech: str | None = None
    breaking_changes: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# INSTALLATIONS
# ─────────────────────────────────────────────────────────────────────────────
class InstallationCreateIn(BaseModel):
    extension_id: UUID
    version_id: UUID | None = None   # Si None, prend la dernière stable
    config: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)   # {cle: valeur_en_clair}
    permissions_accordees: list[str] | None = None          # Si None, prend toutes celles du manifest
    webhook_url: str | None = None
    mode_paiement: Literal["wave", "orange_money", "mtn_momo", "virement", "espece"] | None = None
    accepter_cgu: bool = Field(..., description="Obligatoire : acceptation des CGU")

    @model_validator(mode="after")
    def coherent(self):
        if not self.accepter_cgu:
            raise ValueError("Vous devez accepter les CGU de l'extension")
        return self


class InstallationUpdateIn(BaseModel):
    config: dict[str, Any] | None = None
    secrets: dict[str, str] | None = None
    webhook_url: str | None = None
    permissions_accordees: list[str] | None = None


class InstallationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    extension_id: UUID
    version_id: UUID
    config: dict[str, Any]
    permissions_accordees: list[str]
    statut: str
    activee_at: datetime | None
    desactivee_at: datetime | None
    abonnement_debut: date | None
    abonnement_fin: date | None
    essai_fin: date | None
    prix_paye_xof: int
    mode_paiement: str | None
    nb_appels_jour: int
    nb_erreurs_jour: int
    dernier_appel_at: datetime | None
    derniere_erreur_at: datetime | None
    derniere_erreur: str | None
    installee_par_user_id: UUID | None
    created_at: datetime
    updated_at: datetime


class InstallationDetailOut(InstallationOut):
    extension: ExtensionBriefOut | None = None
    version: ExtensionVersionOut | None = None


# ─────────────────────────────────────────────────────────────────────────────
# REVIEWS
# ─────────────────────────────────────────────────────────────────────────────
class ReviewCreateIn(BaseModel):
    note: int = Field(ge=1, le=5)
    titre: str | None = Field(None, max_length=200)
    commentaire: str | None = Field(None, max_length=5000)


class ReviewPublisherResponseIn(BaseModel):
    reponse: str = Field(min_length=10, max_length=3000)


class ReviewReportIn(BaseModel):
    motif: Literal["securite", "contenu", "spam", "arnaque", "bug", "violation_conditions"]
    description: str = Field(min_length=10, max_length=2000)


class ExtensionReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    extension_id: UUID
    tenant_id: UUID
    auteur_user_id: UUID | None
    auteur_nom: str
    note: int
    titre: str | None
    commentaire: str | None
    nb_utile: int
    nb_non_utile: int
    reponse_publisher: str | None
    reponse_at: datetime | None
    visible: bool
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# TRANSACTIONS
# ─────────────────────────────────────────────────────────────────────────────
class MarketplaceTransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    reference: str
    type_transaction: str
    tenant_id: UUID | None
    publisher_id: UUID | None
    installation_id: UUID | None
    montant_total_xof: int
    commission_mtech_xof: int
    montant_publisher_xof: int
    mode_paiement: str
    reference_paiement: str | None
    provider: str | None
    statut: str
    payee_at: datetime | None
    reversee_at: datetime | None
    remboursee_at: datetime | None
    created_at: datetime


class ReversementRequestIn(BaseModel):
    montant_xof: int = Field(gt=0)
    mode_paiement: Literal["wave", "orange_money", "mtn_momo", "virement"]
    reference_paiement: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD MARKETPLACE (fondateur)
# ─────────────────────────────────────────────────────────────────────────────
class MarketplaceDashboardOut(BaseModel):
    date_arret: date
    nb_extensions_total: int
    nb_extensions_publiees: int
    nb_extensions_en_revision: int
    nb_publishers: int
    nb_publishers_verifies: int
    nb_installations_total: int
    nb_installations_actives: int
    revenus_mois_xof: int
    commissions_mois_xof: int
    reversements_attente_xof: int
    top_extensions: list[dict[str, Any]]
    top_publishers: list[dict[str, Any]]
    signalements_ouverts: int


class PublisherDashboardOut(BaseModel):
    publisher_id: UUID
    nb_extensions: int
    nb_installations_total: int
    nb_installations_actives: int
    revenus_total_xof: int
    revenus_mois_xof: int
    revenus_en_attente_xof: int
    note_moyenne: float
    top_extensions: list[dict[str, Any]]
    dernieres_transactions: list[MarketplaceTransactionOut]
    signalements_ouverts: int


# ─────────────────────────────────────────────────────────────────────────────
# SDK / DEV TOKENS
# ─────────────────────────────────────────────────────────────────────────────
class DeveloperTokenCreateIn(BaseModel):
    nom: str = Field(min_length=2, max_length=200)
    environnement: Literal["sandbox", "production"] = "sandbox"
    scopes: list[str] = Field(default_factory=list)
    expire_at: datetime | None = None


class DeveloperTokenCreatedOut(BaseModel):
    id: UUID
    nom: str
    token_plain: str = Field(description="⚠️ Ne sera plus jamais affiché")
    token_prefix: str
    environnement: str
    scopes: list[str]
    expire_at: datetime | None


class DeveloperTokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    nom: str
    token_prefix: str
    environnement: str
    scopes: list[str]
    actif: bool
    expire_at: datetime | None
    derniere_utilisation_at: datetime | None
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# HOOK EXECUTIONS (logs)
# ─────────────────────────────────────────────────────────────────────────────
class HookExecutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    installation_id: UUID
    hook_event: str
    trigger_type: str
    payload_size_kb: int | None
    statut: str
    response_status: int | None
    latence_ms: int | None
    erreur: str | None
    nb_tentatives: int
    source_type: str | None
    source_id: UUID | None
    created_at: datetime


# Fix forward reference
ExtensionDetailOut.model_rebuild()
