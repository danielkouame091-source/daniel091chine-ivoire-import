"""Modèles GED — Dossiers, Documents, Versions, Signatures, Partages."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index,
    Integer, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


# ─────────────────────────────────────────────────────────────────────────────
# DOSSIER
# ─────────────────────────────────────────────────────────────────────────────
class DocumentFolder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Dossier (arborescence). Supporte une hiérarchie illimitée.
    """
    __tablename__ = "document_folders"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Hiérarchie
    parent_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("document_folders.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Identification
    code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Type
    type_dossier: Mapped[str] = mapped_column(
        String(20), nullable=False, default="custom", server_default="custom"
    )

    # Rattachement optionnel
    lien_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    lien_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    # Affichage
    icone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    couleur: Mapped[str | None] = mapped_column(String(7), nullable=True)
    ordre: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Sécurité
    restreint: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    roles_autorises: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    # Stats
    nb_documents: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    taille_totale_mo: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, default=0, server_default="0"
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        Index("idx_folder_tenant_parent", "tenant_id", "parent_id"),
        Index("idx_folder_tenant_type", "tenant_id", "type_dossier"),
        Index("idx_folder_lien", "lien_type", "lien_id"),
    )

    def __repr__(self) -> str:
        return f"<DocumentFolder {self.nom}>"


# ─────────────────────────────────────────────────────────────────────────────
# DOCUMENT
# ─────────────────────────────────────────────────────────────────────────────
class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Document (pièce justificative). Un document peut avoir plusieurs versions.
    """
    __tablename__ = "documents"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Localisation
    folder_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("document_folders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Identification
    reference: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Classification
    type_document: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")

    # Fichier (version actuelle)
    version_actuelle: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    fichier_url: Mapped[str] = mapped_column(Text, nullable=False)
    fichier_nom_original: Mapped[str] = mapped_column(Text, nullable=False)
    fichier_taille_kb: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    hash_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    hash_blake2b: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # PDF/A (conformité archivage)
    pdf_a_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_a_conforme: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # OCR (extraction texte)
    ocr_statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="en_attente", server_default="en_attente"
    )
    ocr_texte: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_langue: Mapped[str] = mapped_column(String(10), nullable=False, default="fra", server_default="fra")
    ocr_confiance: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    ocr_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ocr_erreur: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Recherche full-text (indexé sur nom + description + ocr_texte)
    search_vector: Mapped[Any | None] = mapped_column(TSVECTOR, nullable=True)

    # Métadonnées métier (extraites ou saisies)
    date_document: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_expiration: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Montants (pour les factures)
    montant_ht: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    montant_tva: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    montant_ttc: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    devise: Mapped[str] = mapped_column(String(3), nullable=False, default="XOF", server_default="XOF")

    # Rattachements métier
    tiers_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # client | fournisseur
    tiers_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    ecriture_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("ecritures.id", ondelete="SET NULL"), nullable=True
    )
    facture_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    projet_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    employe_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    # Conformité légale
    retention_annees: Mapped[int] = mapped_column(Integer, nullable=False, default=10, server_default="10")
    date_destruction_prevue: Mapped[date | None] = mapped_column(Date, nullable=True)
    est_archive_legal: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Statut
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="brouillon", server_default="brouillon"
    )
    epingle: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    favori: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Statistiques
    nb_telechargements: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    nb_vues: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    derniere_consultation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Signature électronique
    signature_requise: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    signature_statut: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Soft delete
    supprime: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    supprime_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    supprime_par: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    # Auteur
    uploaded_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_doc_tenant_folder", "tenant_id", "folder_id"),
        Index("idx_doc_tenant_type", "tenant_id", "type_document"),
        Index("idx_doc_tenant_statut", "tenant_id", "statut"),
        Index("idx_doc_hash", "tenant_id", "hash_sha256"),
        Index("idx_doc_search", "search_vector", postgresql_using="gin"),
        Index("idx_doc_tiers", "tiers_type", "tiers_id"),
        Index("idx_doc_expiration", "date_expiration"),
        Index("idx_doc_retention", "date_destruction_prevue"),
        CheckConstraint("fichier_taille_kb > 0", name="doc_taille_positive"),
    )

    def __repr__(self) -> str:
        return f"<Document {self.reference} ({self.type_document}) v{self.version_actuelle}>"


# ─────────────────────────────────────────────────────────────────────────────
# VERSION DE DOCUMENT
# ─────────────────────────────────────────────────────────────────────────────
class DocumentVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Version d'un document. Chaque upload nouveau = nouvelle version.
    """
    __tablename__ = "document_versions"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    numero_version: Mapped[int] = mapped_column(Integer, nullable=False)

    # Fichier
    fichier_url: Mapped[str] = mapped_column(Text, nullable=False)
    fichier_nom_original: Mapped[str] = mapped_column(Text, nullable=False)
    fichier_taille_kb: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    hash_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    # OCR de cette version
    ocr_texte: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Commentaire de changement
    commentaire: Mapped[str | None] = mapped_column(Text, nullable=True)
    est_version_actuelle: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    uploaded_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("document_id", "numero_version", name="uq_doc_version"),
        Index("idx_doc_version_doc", "document_id", "numero_version"),
    )

    def __repr__(self) -> str:
        return f"<DocumentVersion doc={self.document_id} v{self.numero_version}>"


# ─────────────────────────────────────────────────────────────────────────────
# SIGNATURE ÉLECTRONIQUE
# ─────────────────────────────────────────────────────────────────────────────
class DocumentSignature(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Signature électronique d'un document.
    Supporte : signature interne (utilisateur MTech) ou externe (client par OTP).
    """
    __tablename__ = "document_signatures"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # Type
    type_signature: Mapped[str] = mapped_column(
        String(20), nullable=False, default="avancee", server_default="avancee"
    )

    # Signataire (interne : user_id, externe : email + OTP)
    signataire_type: Mapped[str] = mapped_column(String(20), nullable=False)  # interne | externe
    signataire_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    signataire_email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    signataire_nom: Mapped[str] = mapped_column(String(200), nullable=False)
    signataire_telephone: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # OTP (pour signature externe)
    otp_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    otp_envoye_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    otp_expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    otp_verifie_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Preuve technique
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Position (optionnel — pour signature manuscrite sur PDF)
    position_x: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    position_y: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    position_page: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Statut
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="en_attente", server_default="en_attente"
    )

    # Preuve finale (hash du PDF signé)
    signature_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pdf_signe_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    signe_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refuse_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    motif_refus: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Demande
    demande_par_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    message_demande: Mapped[str | None] = mapped_column(Text, nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_sig_doc", "document_id"),
        Index("idx_sig_statut", "tenant_id", "statut"),
        Index("idx_sig_email", "signataire_email"),
    )

    def __repr__(self) -> str:
        return f"<DocumentSignature doc={self.document_id} ({self.statut})>"


# ─────────────────────────────────────────────────────────────────────────────
# PARTAGE SÉCURISÉ
# ─────────────────────────────────────────────────────────────────────────────
class DocumentShare(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Partage sécurisé d'un document via lien token.
    """
    __tablename__ = "document_shares"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # Token
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    token_prefix: Mapped[str] = mapped_column(String(12), nullable=False)

    # Destinataire (optionnel)
    destinataire_email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    destinataire_nom: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Permissions
    peut_telecharger: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    peut_signer: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    protege_par_mot_de_passe: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    mot_de_passe_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Expiration
    expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_telechargements: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Usage
    nb_telechargements: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    nb_vues: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    derniere_utilisation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Statut
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    revoque_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    motif_revocation: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        Index("idx_share_doc", "document_id"),
        Index("idx_share_actif", "tenant_id", "actif"),
        Index("idx_share_expire", "expire_at"),
    )

    def __repr__(self) -> str:
        return f"<DocumentShare doc={self.document_id} token={self.token_prefix}...>"


# ─────────────────────────────────────────────────────────────────────────────
# LOG D'ACCÈS (audit GED)
# ─────────────────────────────────────────────────────────────────────────────
class DocumentAccessLog(UUIDPrimaryKeyMixin, Base):
    """
    Log d'accès aux documents (immuable).
    """
    __tablename__ = "document_access_logs"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    document_version_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Acteur
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    portal_user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    share_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document_shares.id", ondelete="SET NULL"), nullable=True
    )

    action: Mapped[str] = mapped_column(String(50), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    succes: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("idx_doc_log_tenant_date", "tenant_id", "created_at"),
        Index("idx_doc_log_doc_date", "document_id", "created_at"),
        Index("idx_doc_log_action", "tenant_id", "action"),
    )

    def __repr__(self) -> str:
        return f"<DocumentAccessLog {self.action} doc={self.document_id}>"


# ─────────────────────────────────────────────────────────────────────────────
# MODÈLE OCR (extraction structurée)
# ─────────────────────────────────────────────────────────────────────────────
class DocumentOCRResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Résultat structuré de l'OCR (montants, dates, numéros, etc.).
    Permet l'auto-classification.
    """
    __tablename__ = "document_ocr_results"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False, index=True, unique=True,
    )

    # Moteur OCR
    moteur: Mapped[str] = mapped_column(String(30), nullable=False)
    version_moteur: Mapped[str | None] = mapped_column(String(30), nullable=True)
    langues: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")

    # Résultats structurés
    num_facture: Mapped[str | None] = mapped_column(String(80), nullable=True)
    date_facture: Mapped[date | None] = mapped_column(Date, nullable=True)
    nom_fournisseur: Mapped[str | None] = mapped_column(String(200), nullable=True)
    numero_contribuable: Mapped[str | None] = mapped_column(String(50), nullable=True)
    montant_ht: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    montant_tva: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    montant_ttc: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    iban: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Score de confiance global
    score_global: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)

    # Suggestions d'association
    suggestions: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # {"fournisseur_id": "...", "facture_suggeree": "..."}

    # Correction manuelle
    corrige_manuellement: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    corrige_par_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    corrige_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_ocr_tenant_montant", "tenant_id", "montant_ttc"),
        Index("idx_ocr_num_facture", "tenant_id", "num_facture"),
    )
