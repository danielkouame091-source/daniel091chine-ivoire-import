"""Modèles Portail Client / Fournisseur."""
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
# UTILISATEUR PORTAIL
# ─────────────────────────────────────────────────────────────────────────────
class PortalUser(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Utilisateur externe du portail (client, fournisseur, partenaire).
    ⚠️ Entité DISTINCTE de `users` (isolation stricte).
    """
    __tablename__ = "portal_users"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Rattachement (client OU fournisseur OU partenaire)
    customer_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    supplier_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )

    # Type
    type_utilisateur: Mapped[str] = mapped_column(String(20), nullable=False)

    # Authentification
    email: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Identité
    prenom: Mapped[str] = mapped_column(String(80), nullable=False)
    nom: Mapped[str] = mapped_column(String(80), nullable=False)
    telephone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    fonction: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # Sécurité
    mfa_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    derniere_connexion_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    derniere_connexion_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    nb_tentatives_echec: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    verrouille_jusqua: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Statut
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="invite", server_default="invite"
    )

    # Permissions (JSONB array)
    permissions: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    # Langue préférée (fr par défaut)
    langue: Mapped[str] = mapped_column(
        String(5), nullable=False, default="fr", server_default="fr"
    )

    # Accès temporaire (pour auditeurs externes)
    acces_expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Consentements
    accepte_cgu: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    accepte_cgu_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_portal_user_email"),
        Index("idx_pu_tenant_type", "tenant_id", "type_utilisateur"),
        Index("idx_pu_customer", "customer_id"),
        Index("idx_pu_supplier", "supplier_id"),
        Index("idx_pu_statut", "tenant_id", "statut"),
        CheckConstraint(
            "(customer_id IS NOT NULL AND supplier_id IS NULL) OR "
            "(customer_id IS NULL AND supplier_id IS NOT NULL) OR "
            "(customer_id IS NULL AND supplier_id IS NULL)",
            name="pu_rattachement_coherent",
        ),
    )

    def __repr__(self) -> str:
        return f"<PortalUser {self.email} ({self.type_utilisateur})>"

    @property
    def nom_complet(self) -> str:
        return f"{self.prenom} {self.nom}"


# ─────────────────────────────────────────────────────────────────────────────
# SESSION PORTAIL
# ─────────────────────────────────────────────────────────────────────────────
class PortalSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Session JWT dédiée au portail (TTL court)."""
    __tablename__ = "portal_sessions"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    portal_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("portal_users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    jti: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, unique=True)
    refresh_token_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoquee_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# INVITATION / TOKEN MAGIQUE
# ─────────────────────────────────────────────────────────────────────────────
class PortalInvitation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Invitation ou lien magique pour accéder au portail."""
    __tablename__ = "portal_invitations"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    portal_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("portal_users.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )

    # Destinataire
    email: Mapped[str] = mapped_column(String(150), nullable=False)
    type_utilisateur: Mapped[str] = mapped_column(String(20), nullable=False)
    customer_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=True
    )
    supplier_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=True
    )

    # Token
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    token_purpose: Mapped[str] = mapped_column(
        String(30), nullable=False
    )   # invitation | magic_link | reset_password
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    utilise_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Traçabilité
    envoye_par_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    email_envoye: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_pi_token_purpose", "token_hash", "token_purpose"),
        Index("idx_pi_email_type", "tenant_id", "email", "type_utilisateur"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# DOCUMENT PARTAGÉ
# ─────────────────────────────────────────────────────────────────────────────
class SharedDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Document partagé avec un utilisateur portail (facture, relevé, contrat...)."""
    __tablename__ = "shared_documents"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    portal_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("portal_users.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    customer_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=True
    )
    supplier_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=True
    )

    type_document: Mapped[str] = mapped_column(String(30), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(50), nullable=True)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Fichier
    fichier_url: Mapped[str] = mapped_column(Text, nullable=False)
    fichier_nom: Mapped[str] = mapped_column(Text, nullable=False)
    fichier_taille_kb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fichier_hash_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False, default="application/pdf")

    # Lien vers la source
    source_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    source_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    # Téléchargements
    nb_telechargements: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    dernier_telechargement_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_sd_tenant_type", "tenant_id", "type_document"),
        Index("idx_sd_portal_user", "portal_user_id"),
        Index("idx_sd_customer", "customer_id", "type_document"),
        Index("idx_sd_source", "source_type", "source_id"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# PAIEMENT EN LIGNE
# ─────────────────────────────────────────────────────────────────────────────
class OnlinePayment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Paiement initié en ligne par un client via le portail."""
    __tablename__ = "online_payments"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    portal_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("portal_users.id"),
        nullable=False, index=True,
    )
    customer_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customers.id"),
        nullable=False, index=True,
    )

    # Référence portail
    reference: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)

    # Montant
    montant_xof: Mapped[int] = mapped_column(BigInteger, nullable=False)
    frais_xof: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    montant_total_xof: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Moyen
    moyen: Mapped[str] = mapped_column(String(30), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(30), nullable=True)   # wave | orange_money | stripe...

    # Statut
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="initie", server_default="initie"
    )

    # Factures liées
    invoice_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    # Provider
    provider_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    provider_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Dates
    initie_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirme_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    echoue_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    motif_echec: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Comptabilisation
    customer_payment_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customer_payments.id"), nullable=True
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_op_tenant_statut", "tenant_id", "statut"),
        Index("idx_op_customer", "customer_id", "created_at"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# SOUMISSION FACTURE FOURNISSEUR
# ─────────────────────────────────────────────────────────────────────────────
class SupplierInvoiceSubmission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Facture soumise en ligne par un fournisseur via le portail.
    Après validation par le tenant, devient une SupplierInvoice officielle.
    """
    __tablename__ = "supplier_invoice_submissions"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    portal_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("portal_users.id"),
        nullable=False, index=True,
    )
    supplier_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("suppliers.id"),
        nullable=False, index=True,
    )

    # Références
    numero_fournisseur: Mapped[str] = mapped_column(String(50), nullable=False)
    purchase_order_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=True
    )

    date_facture: Mapped[date] = mapped_column(Date, nullable=False)
    date_echeance: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Montants
    montant_ht: Mapped[int] = mapped_column(BigInteger, nullable=False)
    montant_tva: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    montant_ttc: Mapped[int] = mapped_column(BigInteger, nullable=False)
    devise: Mapped[str] = mapped_column(String(3), nullable=False, default="XOF", server_default="XOF")

    # Fichier PDF
    fichier_url: Mapped[str] = mapped_column(Text, nullable=False)
    fichier_nom: Mapped[str] = mapped_column(Text, nullable=False)

    # Lignes (JSONB : liste {designation, qte, pu, montant})
    lignes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)

    # Statut
    statut: Mapped[str] = mapped_column(
        String(30), nullable=False, default="brouillon", server_default="brouillon"
    )

    # Traitement par le tenant
    traite_par_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    traite_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    motif_rejet: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Facture officielle créée
    supplier_invoice_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("supplier_invoices.id"), nullable=True
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "supplier_id", "numero_fournisseur", name="uq_sis_num"),
        Index("idx_sis_tenant_statut", "tenant_id", "statut"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# MESSAGERIE PORTAIL
# ─────────────────────────────────────────────────────────────────────────────
class PortalConversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Fil de discussion entre un utilisateur portail et le tenant."""
    __tablename__ = "portal_conversations"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    portal_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("portal_users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    sujet: Mapped[str] = mapped_column(Text, nullable=False)

    # Rattachement optionnel (facture, commande, ticket)
    rattachement_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    rattachement_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="ouverte", server_default="ouverte"
    )
    derniere_activite_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    nb_messages: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    messages_non_lus_client: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    messages_non_lus_tenant: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_pc_tenant_statut", "tenant_id", "statut"),
        Index("idx_pc_portal_user", "portal_user_id", "derniere_activite_at"),
    )


class PortalMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Message dans une conversation portail."""
    __tablename__ = "portal_messages"

    conversation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("portal_conversations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # Auteur
    auteur_type: Mapped[str] = mapped_column(String(20), nullable=False)   # client | tenant
    portal_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("portal_users.id"), nullable=True
    )
    tenant_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    contenu: Mapped[str] = mapped_column(Text, nullable=False)
    pieces_jointes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    lu_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    def __repr__(self) -> str:
        return f"<PortalMessage {self.auteur_type}: {self.contenu[:50]}>"


# ─────────────────────────────────────────────────────────────────────────────
# NOTIFICATION PORTAIL
# ─────────────────────────────────────────────────────────────────────────────
class PortalNotification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Notification envoyée à un utilisateur portail (email, SMS, WhatsApp)."""
    __tablename__ = "portal_notifications"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    portal_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("portal_users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    canal: Mapped[str] = mapped_column(String(20), nullable=False)   # email | sms | whatsapp | push

    sujet: Mapped[str] = mapped_column(Text, nullable=False)
    contenu_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    contenu_texte: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Lien d'action
    action_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_label: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Statut
    envoye: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    envoye_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    erreur_envoi: Mapped[str | None] = mapped_column(Text, nullable=True)

    lu_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_pn_portal_user_date", "portal_user_id", "created_at"),
        Index("idx_pn_tenant_event", "tenant_id", "event_type"),
    )
