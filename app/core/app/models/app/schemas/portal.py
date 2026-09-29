"""DTO Portail Client / Fournisseur."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

TypeUtilPortail = Literal["client", "fournisseur", "partenaire", "auditeur_externe"]
StatutCompteP = Literal["invite", "actif", "suspendu", "revoque", "expire"]
TypeDocPartage = Literal["facture", "releve", "avoir", "bon_commande", "bon_livraison", "situation_travaux", "contrat", "attestation", "rib", "autre"]
MoyenPaiementP = Literal["mobile_money", "carte_bancaire", "virement", "cheque"]
StatutPaiementP = Literal["initie", "en_cours", "confirme", "echoue", "annule", "rembourse"]


# ─────────────────────────────────────────────────────────────────────────────
# AUTH PORTAIL
# ─────────────────────────────────────────────────────────────────────────────
class PortalInviteIn(BaseModel):
    """Créer une invitation pour un client ou fournisseur."""
    email: EmailStr
    prenom: str = Field(min_length=1, max_length=80)
    nom: str = Field(min_length=1, max_length=80)
    type_utilisateur: TypeUtilPortail
    customer_id: UUID | None = None
    supplier_id: UUID | None = None
    telephone: str | None = None
    fonction: str | None = None
    permissions: list[str] | None = None
    message_personnalise: str | None = Field(None, max_length=1000)
    acces_expire_at: datetime | None = None

    @model_validator(mode="after")
    def coherent(self):
        if self.type_utilisateur == "client" and not self.customer_id:
            raise ValueError("customer_id requis pour un client")
        if self.type_utilisateur == "fournisseur" and not self.supplier_id:
            raise ValueError("supplier_id requis pour un fournisseur")
        return self


class PortalLoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class PortalTokenOut(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    expires_in: int
    portal_user_id: UUID
    type_utilisateur: str
    nom_complet: str


class PortalUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    email: EmailStr
    prenom: str
    nom: str
    type_utilisateur: str
    customer_id: UUID | None
    supplier_id: UUID | None
    telephone: str | None
    fonction: str | None
    statut: str
    permissions: list[str]
    mfa_enabled: bool
    derniere_connexion_at: datetime | None
    created_at: datetime


class PortalUserUpdate(BaseModel):
    prenom: str | None = None
    nom: str | None = None
    telephone: str | None = None
    fonction: str | None = None
    langue: str | None = None


class PortalPasswordSetIn(BaseModel):
    """Activation compte portail via lien d'invitation."""
    token: str = Field(min_length=20)
    password: str = Field(min_length=8, max_length=128)


class PortalMagicLinkIn(BaseModel):
    email: EmailStr


# ─────────────────────────────────────────────────────────────────────────────
# DOCUMENTS PARTAGÉS
# ─────────────────────────────────────────────────────────────────────────────
class SharedDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    type_document: str
    reference: str | None
    titre: str
    description: str | None
    fichier_nom: str
    fichier_taille_kb: int | None
    mime_type: str
    source_type: str | None
    source_id: UUID | None
    nb_telechargements: int
    expire_at: datetime | None
    created_at: datetime


class SharedDocumentDetailOut(SharedDocumentOut):
    fichier_url: str  # URL signée temporaire


class SharedDocumentCreate(BaseModel):
    portal_user_id: UUID | None = None
    customer_id: UUID | None = None
    supplier_id: UUID | None = None
    type_document: TypeDocPartage
    reference: str | None = None
    titre: str = Field(min_length=2, max_length=200)
    description: str | None = None
    fichier_url: str
    fichier_nom: str
    fichier_taille_kb: int | None = None
    mime_type: str = "application/pdf"
    source_type: str | None = None
    source_id: UUID | None = None
    expire_at: datetime | None = None


# ─────────────────────────────────────────────────────────────────────────────
# ESPACE CLIENT
# ─────────────────────────────────────────────────────────────────────────────
class ClientPortalDashboard(BaseModel):
    """Vue d'ensemble pour un client connecté."""
    customer_id: UUID
    customer_nom: str
    solde_du_xof: int
    nb_factures_impayees: int
    nb_factures_en_retard: int
    montant_en_retard_xof: int
    nb_factures_mois_courant: int
    montant_facture_mois_xof: int
    derniere_facture: dict[str, Any] | None
    dernier_paiement: dict[str, Any] | None
    prochaine_echeance: date | None


class ClientInvoiceOut(BaseModel):
    """Facture vue depuis le portail client."""
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    numero: str
    date_facture: date
    date_echeance: date
    total_ht: int
    total_tva: int
    total_ttc: int
    montant_encaisse: int
    solde_du: int
    statut: str
    jours_retard: int
    peut_payer_en_ligne: bool
    fne_reference: str | None = None   # Référence FNE si certifiée
    qr_code_url: str | None = None
    document_url: str | None = None    # URL signée du PDF


class ClientStatementOut(BaseModel):
    """Relevé de compte client."""
    customer_id: UUID
    date_debut: date
    date_fin: date
    solde_ouverture: int
    total_facture: int
    total_paye: int
    solde_fin: int
    nb_factures: int
    nb_paiements: int
    pdf_url: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# ESPACE FOURNISSEUR
# ─────────────────────────────────────────────────────────────────────────────
class SupplierPortalDashboard(BaseModel):
    """Vue d'ensemble pour un fournisseur connecté."""
    supplier_id: UUID
    supplier_nom: str
    nb_commandes_en_cours: int
    montant_commandes_en_cours_xof: int
    nb_factures_en_attente: int
    montant_factures_en_attente_xof: int
    nb_factures_payees_mois: int
    montant_recu_mois_xof: int
    prochaine_livraison_date: date | None
    derniere_commande: dict[str, Any] | None


class SupplierOrderOut(BaseModel):
    """Commande fournisseur vue depuis le portail."""
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    numero: str
    date_commande: date
    date_livraison_prevue: date | None
    statut: str
    total_ht: int
    total_ttc: int
    nb_lignes: int
    peut_accuser_reception: bool
    document_url: str | None = None


class SupplierInvoiceSubmissionIn(BaseModel):
    numero_fournisseur: str = Field(min_length=1, max_length=50)
    purchase_order_id: UUID | None = None
    date_facture: date
    date_echeance: date | None = None
    montant_ht: int = Field(gt=0)
    montant_tva: int = Field(0, ge=0)
    fichier_url: str
    fichier_nom: str
    lignes: list[dict[str, Any]] = Field(default_factory=list)


class SupplierInvoiceSubmissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    numero_fournisseur: str
    date_facture: date
    date_echeance: date | None
    montant_ht: int
    montant_tva: int
    montant_ttc: int
    statut: str
    motif_rejet: str | None
    supplier_invoice_id: UUID | None
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# PAIEMENT EN LIGNE
# ─────────────────────────────────────────────────────────────────────────────
class OnlinePaymentInitIn(BaseModel):
    invoice_ids: list[UUID] = Field(min_length=1)
    moyen: MoyenPaiementP
    provider: str | None = None
    telephone_paiement: str | None = None   # Pour Mobile Money
    email_paiement: EmailStr | None = None

    @model_validator(mode="after")
    def coherent(self):
        if self.moyen == "mobile_money" and not self.telephone_paiement:
            raise ValueError("telephone_paiement requis pour Mobile Money")
        if self.moyen == "carte_bancaire" and not self.email_paiement:
            raise ValueError("email_paiement requis pour carte bancaire")
        return self


class OnlinePaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    reference: str
    montant_xof: int
    frais_xof: int
    montant_total_xof: int
    moyen: str
    provider: str | None
    statut: str
    provider_url: str | None
    provider_reference: str | None
    initie_at: datetime
    confirme_at: datetime | None
    customer_payment_id: UUID | None


class OnlinePaymentInitOut(BaseModel):
    """Réponse à l'initiation d'un paiement."""
    payment: OnlinePaymentOut
    checkout_url: str | None = None   # URL de redirection (CB) ou USSD (MM)
    instructions: str | None = None   # Instructions pour Mobile Money


# ─────────────────────────────────────────────────────────────────────────────
# MESSAGERIE
# ─────────────────────────────────────────────────────────────────────────────
class PortalConversationCreate(BaseModel):
    sujet: str = Field(min_length=3, max_length=200)
    message_initial: str = Field(min_length=10, max_length=5000)
    rattachement_type: str | None = None
    rattachement_id: UUID | None = None


class PortalConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    portal_user_id: UUID
    sujet: str
    rattachement_type: str | None
    rattachement_id: UUID | None
    statut: str
    derniere_activite_at: datetime
    nb_messages: int
    messages_non_lus_client: int
    created_at: datetime


class PortalMessageCreate(BaseModel):
    contenu: str = Field(min_length=1, max_length=5000)
    pieces_jointes: list[dict[str, Any]] = Field(default_factory=list)


class PortalMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    conversation_id: UUID
    auteur_type: str
    portal_user_id: UUID | None
    tenant_user_id: UUID | None
    contenu: str
    pieces_jointes: list[dict[str, Any]]
    lu_at: datetime | None
    created_at: datetime


class PortalConversationDetailOut(PortalConversationOut):
    messages: list[PortalMessageOut] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# NOTIFICATIONS
# ─────────────────────────────────────────────────────────────────────────────
class PortalNotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    event_type: str
    canal: str
    sujet: str
    contenu_texte: str | None
    action_url: str | None
    action_label: str | None
    envoye: bool
    envoye_at: datetime | None
    lu_at: datetime | None
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# STATS PORTAIL
# ─────────────────────────────────────────────────────────────────────────────
class PortalStatsOut(BaseModel):
    tenant_id: UUID
    periode_debut: datetime
    periode_fin: datetime
    nb_portal_users_actifs: int
    nb_connexions: int
    nb_documents_consultes: int
    nb_paiements_en_ligne: int
    montant_paiements_en_ligne_xof: int
    nb_factures_soumises: int
    montant_factures_soumises_xof: int
    taux_recouvrement_en_ligne_pct: float
    temps_moyen_paiement_jours: float
    top_clients_actifs: list[dict[str, Any]]
