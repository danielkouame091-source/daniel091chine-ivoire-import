"""DTO GED — Dossiers, Documents, Versions, Signatures, Partages."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

TypeDossierT = Literal["racine", "systeme", "client", "fournisseur", "employe", "projet", "annee", "custom"]
StatutDocT = Literal["brouillon", "en_revision", "valide", "signe", "archive", "expire", "supprime"]
StatutOCRT = Literal["en_attente", "en_cours", "termine", "echec", "non_applicable"]
StatutSigT = Literal["en_attente", "otp_envoye", "signee", "refusee", "expiree"]
TypeSigT = Literal["simple", "avancee", "qualifiee"]


# ─────────────────────────────────────────────────────────────────────────────
# DOSSIERS
# ─────────────────────────────────────────────────────────────────────────────
class FolderCreate(BaseModel):
    nom: str = Field(min_length=2, max_length=200)
    description: str | None = None
    parent_id: UUID | None = None
    type_dossier: TypeDossierT = "custom"
    code: str | None = Field(None, max_length=50)
    icone: str | None = None
    couleur: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    ordre: int = 0
    lien_type: str | None = None
    lien_id: UUID | None = None
    restreint: bool = False
    roles_autorises: list[str] = Field(default_factory=list)


class FolderUpdate(BaseModel):
    nom: str | None = None
    description: str | None = None
    parent_id: UUID | None = None
    icone: str | None = None
    couleur: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    ordre: int | None = None
    restreint: bool | None = None
    roles_autorises: list[str] | None = None


class FolderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    parent_id: UUID | None
    code: str | None
    nom: str
    description: str | None
    type_dossier: str
    lien_type: str | None
    lien_id: UUID | None
    icone: str | None
    couleur: str | None
    ordre: int
    restreint: bool
    roles_autorises: list[str]
    nb_documents: int
    taille_totale_mo: float
    created_at: datetime


class FolderTreeNode(FolderOut):
    enfants: list["FolderTreeNode"] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# DOCUMENTS
# ─────────────────────────────────────────────────────────────────────────────
class DocumentMetadataUpdate(BaseModel):
    nom: str | None = Field(None, min_length=2, max_length=200)
    description: str | None = None
    folder_id: UUID | None = None
    type_document: str | None = None
    tags: list[str] | None = None
    date_document: date | None = None
    date_expiration: date | None = None
    montant_ht: int | None = Field(None, ge=0)
    montant_tva: int | None = Field(None, ge=0)
    montant_ttc: int | None = Field(None, ge=0)
    tiers_type: str | None = None
    tiers_id: UUID | None = None
    statut: StatutDocT | None = None
    epingle: bool | None = None
    favori: bool | None = None
    retention_annees: int | None = Field(None, ge=1, le=50)


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    folder_id: UUID | None
    reference: str
    nom: str
    description: str | None
    type_document: str
    tags: list[str]
    version_actuelle: int
    fichier_nom_original: str
    fichier_taille_kb: int
    mime_type: str
    hash_sha256: str
    pdf_a_conforme: bool
    ocr_statut: str
    date_document: date | None
    date_expiration: date | None
    montant_ht: int | None
    montant_tva: int | None
    montant_ttc: int | None
    devise: str
    tiers_type: str | None
    tiers_id: UUID | None
    ecriture_id: UUID | None
    statut: str
    epingle: bool
    favori: bool
    nb_telechargements: int
    nb_vues: int
    signature_requise: bool
    signature_statut: str | None
    retention_annees: int
    date_destruction_prevue: date | None
    created_at: datetime
    updated_at: datetime


class DocumentDetailOut(DocumentOut):
    fichier_url: str | None = None
    ocr_texte: str | None = None
    versions_count: int = 0
    signatures_count: int = 0
    shares_count: int = 0
    ocr_extraction: dict[str, Any] | None = None


class DocumentUploadResult(BaseModel):
    document: DocumentOut
    version_numero: int
    ocr_queued: bool
    message: str


class DocumentVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    document_id: UUID
    numero_version: int
    fichier_nom_original: str
    fichier_taille_kb: int
    mime_type: str
    hash_sha256: str
    commentaire: str | None
    est_version_actuelle: bool
    uploaded_by_user_id: UUID | None
    created_at: datetime


class DocumentSearchResult(BaseModel):
    document: DocumentOut
    score: float
    extrait: str | None = None


class DocumentBulkActionIn(BaseModel):
    document_ids: list[UUID] = Field(min_length=1, max_length=500)
    action: Literal["move", "delete", "restore", "archive", "add_tags"]
    folder_id: UUID | None = None
    tags: list[str] = Field(default_factory=list)


class DocumentBulkActionResult(BaseModel):
    nb_traites: int
    nb_erreurs: int
    details: list[dict[str, Any]] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# OCR
# ─────────────────────────────────────────────────────────────────────────────
class OCRResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    document_id: UUID
    moteur: str
    langues: list[str]
    num_facture: str | None
    date_facture: date | None
    nom_fournisseur: str | None
    numero_contribuable: str | None
    montant_ht: int | None
    montant_tva: int | None
    montant_ttc: int | None
    iban: str | None
    score_global: float | None
    suggestions: dict[str, Any] | None
    corrige_manuellement: bool
    created_at: datetime


class OCRManualCorrectionIn(BaseModel):
    num_facture: str | None = None
    date_facture: date | None = None
    nom_fournisseur: str | None = None
    numero_contribuable: str | None = None
    montant_ht: int | None = Field(None, ge=0)
    montant_tva: int | None = Field(None, ge=0)
    montant_ttc: int | None = Field(None, ge=0)
    iban: str | None = None


class OCRRequeueIn(BaseModel):
    moteur: Literal["tesseract", "paddleocr", "vision_api", "no_ocr"] = "tesseract"
    langues: list[str] = Field(default_factory=lambda: ["fra"])


# ─────────────────────────────────────────────────────────────────────────────
# SIGNATURES
# ─────────────────────────────────────────────────────────────────────────────
class SignatureRequestIn(BaseModel):
    """Demande de signature (interne ou externe)."""
    type_signature: TypeSigT = "avancee"
    signataire_email: EmailStr | None = None
    signataire_nom: str = Field(min_length=2, max_length=200)
    signataire_telephone: str | None = None
    message_demande: str | None = Field(None, max_length=2000)
    position_page: int | None = Field(None, ge=1)
    position_x: float | None = Field(None, ge=0, le=1)
    position_y: float | None = Field(None, ge=0, le=1)

    @model_validator(mode="after")
    def coherent(self):
        if self.type_signature in ("avancee", "qualifiee") and not self.signataire_email:
            raise ValueError("Email requis pour signature avancée")
        return self


class SignatureVerifyOTPIn(BaseModel):
    signature_id: UUID
    otp_code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class SignatureRefuseIn(BaseModel):
    motif: str = Field(min_length=5, max_length=500)


class SignatureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    document_id: UUID
    type_signature: str
    signataire_type: str
    signataire_email: str | None
    signataire_nom: str
    statut: str
    otp_envoye_at: datetime | None
    otp_expire_at: datetime | None
    otp_verifie_at: datetime | None
    signature_hash: str | None
    signe_at: datetime | None
    refuse_at: datetime | None
    motif_refus: str | None
    demande_par_user_id: UUID | None
    message_demande: str | None
    created_at: datetime


class SignatureRequestOut(SignatureOut):
    """Retourné après création : inclut le lien de signature pour l'externe."""
    lien_signature: str | None = None


class PublicSignatureOut(BaseModel):
    """Vue publique d'une signature externe (masque les infos sensibles)."""
    signature_id: UUID
    document_nom: str
    signataire_nom: str
    signataire_email: str | None
    statut: str
    otp_envoye: bool
    expire_at: datetime | None
    message_demande: str | None


# ─────────────────────────────────────────────────────────────────────────────
# PARTAGE
# ─────────────────────────────────────────────────────────────────────────────
class ShareCreateIn(BaseModel):
    destinataire_email: EmailStr | None = None
    destinataire_nom: str | None = None
    peut_telecharger: bool = True
    peut_signer: bool = False
    mot_de_passe: str | None = Field(None, min_length=8, max_length=128)
    expire_dans_heures: int = Field(72, ge=1, le=720)
    max_telechargements: int | None = Field(None, ge=1, le=1000)


class ShareOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    document_id: UUID
    token_prefix: str
    destinataire_email: str | None
    destinataire_nom: str | None
    peut_telecharger: bool
    peut_signer: bool
    protege_par_mot_de_passe: bool
    expire_at: datetime | None
    max_telechargements: int | None
    nb_telechargements: int
    nb_vues: int
    derniere_utilisation_at: datetime | None
    actif: bool
    revoque_at: datetime | None
    created_at: datetime


class ShareCreatedOut(ShareOut):
    token_plain: str = Field(description="⚠️ Ne sera plus jamais affiché")
    url_partage: str


class ShareRevokeIn(BaseModel):
    motif: str = Field(min_length=5, max_length=500)


class PublicDownloadIn(BaseModel):
    token: str
    mot_de_passe: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# AUDIT
# ─────────────────────────────────────────────────────────────────────────────
class DocumentAccessLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    document_id: UUID | None
    user_id: UUID | None
    portal_user_id: UUID | None
    share_id: UUID | None
    action: str
    ip_address: str | None
    succes: bool
    details: dict[str, Any] | None
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# STATS / ANALYTICS
# ─────────────────────────────────────────────────────────────────────────────
class GEDDashboardOut(BaseModel):
    tenant_id: UUID
    date_arret: date
    nb_documents_total: int
    nb_dossiers_total: int
    taille_totale_mo: float
    nb_ocr_en_attente: int
    nb_signatures_attente: int
    nb_partages_actifs: int
    nb_documents_expires: int
    nb_documents_a_detruire_30j: int
    repartition_par_type: dict[str, int]
    documents_recents: list[dict[str, Any]]
    top_documents_consultes: list[dict[str, Any]]


class GEDStorageUsageOut(BaseModel):
    tenant_id: UUID
    taille_actuelle_mo: float
    taille_max_mo: float
    pourcentage_utilise: float
    nb_documents: int
    repartition_par_mime: dict[str, float]
