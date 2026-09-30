"""Modèles Conformité RGPD / Protection des données."""
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
# REGISTRE DES TRAITEMENTS (Art. 30 RGPD)
# ─────────────────────────────────────────────────────────────────────────────
class ProcessingRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Registre des activités de traitement.
    Chaque traitement = 1 entrée (gestion clients, paie, marketing...).
    """
    __tablename__ = "processing_records"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Identification
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Finalité & base légale
    finalite: Mapped[str] = mapped_column(String(50), nullable=False)
    base_legale: Mapped[str] = mapped_column(String(30), nullable=False)
    base_legale_justification: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Responsable du traitement
    responsable_nom: Mapped[str | None] = mapped_column(String(200), nullable=True)
    responsable_email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    responsable_telephone: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # Sous-traitants (JSONB : [{nom, email, pays, role, garanties}])
    sous_traitants: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    # Catégories de personnes concernées
    categories_personnes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    # ["clients", "employes", "fournisseurs", "prospects"]

    # Catégories de données
    categories_donnees: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    contient_donnees_sensibles: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Durée de conservation
    duree_conservation_mois: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duree_conservation_justification: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Transferts hors CI/UE
    transfert_hors_ci: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    transfert_pays: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    transfert_garanties: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Mesures de sécurité
    mesures_securite: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    # AIPD (Analyse d'Impact)
    aipd_requise: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    aipd_realisee: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    aipd_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    aipd_niveau_risque: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Statut
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    date_revue_prevue: Mapped[date | None] = mapped_column(Date, nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_processing_record_code"),
        Index("idx_proc_record_tenant_actif", "tenant_id", "actif"),
        Index("idx_proc_record_finalite", "tenant_id", "finalite"),
    )

    def __repr__(self) -> str:
        return f"<ProcessingRecord {self.code} — {self.nom}>"


# ─────────────────────────────────────────────────────────────────────────────
# CONSENTEMENTS
# ─────────────────────────────────────────────────────────────────────────────
class ConsentRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Enregistrement d'un consentement (opt-in / opt-out).
    Conforme aux exigences de preuve (Art. 7 RGPD).
    """
    __tablename__ = "consent_records"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Personne concernée (utilisateur interne OU portail OU externe par email)
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    portal_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("portal_users.id", ondelete="SET NULL"), nullable=True
    )
    email: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)
    telephone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    nom_complet: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Finalité du consentement
    finalite: Mapped[str] = mapped_column(String(50), nullable=False)
    version_politique: Mapped[str] = mapped_column(String(20), nullable=False)

    # Statut
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="accorde", server_default="accorde"
    )

    # Preuve
    texte_consentement: Mapped[str] = mapped_column(Text, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(
        String(30), nullable=False, default="web", server_default="web"
    )   # web | mobile | email | papier | api

    # Dates
    accorde_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Retrait
    motif_retrait: Mapped[str | None] = mapped_column(Text, nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_consent_tenant_finalite", "tenant_id", "finalite"),
        Index("idx_consent_tenant_statut", "tenant_id", "statut"),
        Index("idx_consent_email", "tenant_id", "email"),
        Index("idx_consent_user", "user_id"),
    )

    def __repr__(self) -> str:
        return f"<ConsentRecord {self.finalite} ({self.statut})>"


# ─────────────────────────────────────────────────────────────────────────────
# DEMANDE DE DROIT (exercice des droits)
# ─────────────────────────────────────────────────────────────────────────────
class DataSubjectRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Demande d'exercice d'un droit (accès, rectification, effacement...).
    Workflow de traitement avec délai légal (30 jours).
    """
    __tablename__ = "data_subject_requests"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Identification
    reference: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, index=True)

    # Demandeur
    demandeur_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )   # utilisateur | portail | externe
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    portal_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("portal_users.id", ondelete="SET NULL"), nullable=True
    )
    email: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    nom_complet: Mapped[str] = mapped_column(String(200), nullable=False)
    telephone: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # Droit exercé
    type_droit: Mapped[str] = mapped_column(String(30), nullable=False)
    description_demande: Mapped[str] = mapped_column(Text, nullable=False)

    # Pièces justificatives (JSONB : [{nom, url}])
    pieces_jointes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    # Vérification d'identité
    identite_verifiee: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    methode_verification: Mapped[str | None] = mapped_column(String(30), nullable=True)
    verifiee_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Statut
    statut: Mapped[str] = mapped_column(
        String(30), nullable=False, default="recue", server_default="recue"
    )

    # Délais
    date_limite: Mapped[date] = mapped_column(Date, nullable=False)
    prolongation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    nouvelle_date_limite: Mapped[date | None] = mapped_column(Date, nullable=True)
    motif_prolongation: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Traitement
    traite_par_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    traite_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Réponse
    reponse: Mapped[str | None] = mapped_column(Text, nullable=True)
    motif_refus: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_reponse_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_dsr_tenant_statut", "tenant_id", "statut"),
        Index("idx_dsr_tenant_type", "tenant_id", "type_droit"),
        Index("idx_dsr_delai", "date_limite"),
    )

    def __repr__(self) -> str:
        return f"<DataSubjectRequest {self.reference} {self.type_droit} ({self.statut})>"


# ─────────────────────────────────────────────────────────────────────────────
# VIOLATION DE DONNÉES (data breach)
# ─────────────────────────────────────────────────────────────────────────────
class DataBreach(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Incident de sécurité entraînant une violation de données.
    Notification à l'autorité sous 72h si risque avéré.
    """
    __tablename__ = "data_breaches"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Identification
    reference: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, index=True)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Classification
    type_incident: Mapped[str] = mapped_column(String(30), nullable=False)
    gravite: Mapped[str] = mapped_column(String(20), nullable=False)
    categories_donnees_affectees: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    nb_personnes_affectees: Mapped[int | None] = mapped_column(Integer, nullable=True)
    personnes_affectees_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    # Chronologie
    detecte_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    survenu_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    maitrise_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cloture_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Cause
    cause_racine: Mapped[str | None] = mapped_column(Text, nullable=True)
    vecteur: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Mesures
    mesures_immediates: Mapped[str | None] = mapped_column(Text, nullable=True)
    mesures_correctives: Mapped[str | None] = mapped_column(Text, nullable=True)
    prevention_future: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Notification autorité
    notification_autorite_requise: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    notification_autorite_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    autorite_notifiee: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reference_autorite: Mapped[str | None] = mapped_column(String(50), nullable=True)
    contenu_notification_autorite: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Notification personnes
    notification_personnes_requise: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    notification_personnes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    contenu_notification_personnes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Statut
    statut: Mapped[str] = mapped_column(
        String(30), nullable=False, default="detecte", server_default="detecte"
    )

    # Impact
    impact_estime_xof: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    impact_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        Index("idx_breach_tenant_statut", "tenant_id", "statut"),
        Index("idx_breach_tenant_gravite", "tenant_id", "gravite"),
        Index("idx_breach_detecte", "detecte_at"),
    )

    def __repr__(self) -> str:
        return f"<DataBreach {self.reference} ({self.gravite}) statut={self.statut}>"


# ─────────────────────────────────────────────────────────────────────────────
# DPO (Délégué à la Protection des Données)
# ─────────────────────────────────────────────────────────────────────────────
class DataProtectionOfficer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    DPO — interne ou externe. Information publique.
    """
    __tablename__ = "data_protection_officers"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Type
    type_dpo: Mapped[str] = mapped_column(
        String(20), nullable=False, default="interne", server_default="interne"
    )   # interne | externe

    # Identité
    nom_complet: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(150), nullable=False)
    telephone: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # Si externe
    organisation: Mapped[str | None] = mapped_column(String(200), nullable=True)
    numero_enregistrement: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Si interne
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Informations publiques
    publie_sur_site: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    adresse_postale: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Notification ARTCI
    notifie_artci: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    notifie_artci_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Statut
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    date_debut: Mapped[date] = mapped_column(Date, nullable=False)
    date_fin: Mapped[date | None] = mapped_column(Date, nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_dpo_tenant_actif", "tenant_id", "actif"),
    )

    def __repr__(self) -> str:
        return f"<DPO {self.nom_complet}>"


# ─────────────────────────────────────────────────────────────────────────────
# DOCUMENTS LÉGAUX (versions)
# ─────────────────────────────────────────────────────────────────────────────
class LegalDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Document légal (politique de confidentialité, CGU, etc.) avec versioning.
    """
    __tablename__ = "legal_documents"

    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,   # NULL = document global MTech
        index=True,
    )

    # Identification
    type_document: Mapped[str] = mapped_column(String(50), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)

    # Contenu
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    contenu: Mapped[str] = mapped_column(Text, nullable=False)   # Markdown
    langue: Mapped[str] = mapped_column(String(5), nullable=False, default="fr", server_default="fr")

    # Dates
    date_effet: Mapped[date] = mapped_column(Date, nullable=False)
    date_publication: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Statut
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    est_version_actuelle: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Publication
    pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    url_publication: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Notification utilisateurs
    notification_envoyee: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    notification_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "type_document", "version", "langue", name="uq_legal_doc_version"),
        Index("idx_legal_doc_type_actif", "tenant_id", "type_document", "actif"),
    )

    def __repr__(self) -> str:
        return f"<LegalDocument {self.type_document} v{self.version}>"


# ─────────────────────────────────────────────────────────────────────────────
# COOKIES / TRACEURS
# ─────────────────────────────────────────────────────────────────────────────
class CookieConsent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Consentement cookies d'un visiteur/utilisateur.
    """
    __tablename__ = "cookie_consents"

    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Session (visiteur anonyme)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Consentements par catégorie
    essentiels: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    fonctionnels: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    analytiques: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    marketing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    reseaux_sociaux: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    # Preuve
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    version_politique: Mapped[str] = mapped_column(String(20), nullable=False)

    # Acceptation / refus
    accepte_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    modifie_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    expire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("idx_cookie_tenant_session", "tenant_id", "session_id"),
    )

    def __repr__(self) -> str:
        return f"<CookieConsent session={self.session_id[:8]}>"


# ─────────────────────────────────────────────────────────────────────────────
# SOUS-TRAITANTS (Art. 28 RGPD)
# ─────────────────────────────────────────────────────────────────────────────
class DataProcessor(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Sous-traitant de données (fournisseur cloud, service tiers).
    """
    __tablename__ = "data_processors"

    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )

    # Identification
    nom: Mapped[str] = mapped_column(String(200), nullable=False)
    raison_sociale: Mapped[str | None] = mapped_column(String(200), nullable=True)
    pays: Mapped[str] = mapped_column(String(2), nullable=False)
    adresse: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Contact DPO
    contact_nom: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(150), nullable=True)

    # Service fourni
    service: Mapped[str] = mapped_column(Text, nullable=False)
    categories_donnees: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    # Conformité
    dpa_signe: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    dpa_signe_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    dpa_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    certifications: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )   # ["ISO27001", "SOC2", "RGPD"]

    # Transferts
    transfert_hors_ci: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    garanties_transfert: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Statut
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_processor_tenant_actif", "tenant_id", "actif"),
    )

    def __repr__(self) -> str:
        return f"<DataProcessor {self.nom}>"


# ─────────────────────────────────────────────────────────────────────────────
# AIPD (Analyse d'Impact)
# ─────────────────────────────────────────────────────────────────────────────
class ImpactAssessment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    AIPD — Analyse d'Impact relative à la Protection des Données.
    Requise pour les traitements à risque élevé.
    """
    __tablename__ = "impact_assessments"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    processing_record_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("processing_records.id", ondelete="SET NULL"), nullable=True
    )

    # Identification
    reference: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Évaluation des risques
    necessite_aipd: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    raisons_aipd: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    # Analyse
    description_traitement: Mapped[str] = mapped_column(Text, nullable=False)
    necessite_proportionnalite: Mapped[str | None] = mapped_column(Text, nullable=True)
    risques_personnes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    mesures_risques: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    # Niveau de risque global
    niveau_risque: Mapped[str] = mapped_column(
        String(20), nullable=False, default="moyen", server_default="moyen"
    )

    # Avis DPO
    avis_dpo: Mapped[str | None] = mapped_column(Text, nullable=True)
    avis_dpo_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Consultation autorité
    consultation_autorite_requise: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    consultation_autorite_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Statut
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="brouillon", server_default="brouillon"
    )

    date_validation: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_revue_prevue: Mapped[date | None] = mapped_column(Date, nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        Index("idx_aipd_tenant_statut", "tenant_id", "statut"),
    )

    def __repr__(self) -> str:
        return f"<ImpactAssessment {self.reference} ({self.niveau_risque})>"


# ─────────────────────────────────────────────────────────────────────────────
# TRAITEMENTS DES DEMANDES (workflow)
# ─────────────────────────────────────────────────────────────────────────────
class RequestActionLog(UUIDPrimaryKeyMixin, Base):
    """
    Journal des actions sur une demande de droit (traçabilité complète).
    """
    __tablename__ = "request_action_logs"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    request_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("data_subject_requests.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    action: Mapped[str] = mapped_column(String(50), nullable=False)
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    ancien_statut: Mapped[str | None] = mapped_column(String(30), nullable=True)
    nouveau_statut: Mapped[str | None] = mapped_column(String(30), nullable=True)

    commentaire: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("idx_req_action_request", "request_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<RequestActionLog {self.action}>"
