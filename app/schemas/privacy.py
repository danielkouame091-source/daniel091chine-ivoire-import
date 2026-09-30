"""DTO Conformité RGPD / Protection des données."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

BaseLegaleT = Literal["consentement", "contrat", "obligation_legale", "interet_vital", "mission_publique", "interet_legitime"]
TypeDroitT = Literal["acces", "rectification", "effacement", "limitation", "portabilite", "opposition", "retrait_consentement", "reclamation", "decision_automatisee"]
StatutDemandeT = Literal["recue", "en_cours", "en_attente_verification", "acceptee", "refusee", "partiellement_satisfaite", "cloturee", "annulee"]
TypeIncidentT = Literal["acces_non_autorise", "divulgation", "perte", "alteration", "destruction", "vol", "ransomware", "phishing", "erreur_humaine"]
GraviteT = Literal["faible", "moyen", "eleve", "critique"]
StatutIncidentT = Literal["detecte", "en_investigation", "confirme", "notifie_autorite", "notifie_personnes", "cloture", "faux_positif"]
NiveauRisqueT = Literal["faible", "moyen", "eleve", "tres_eleve"]


# ─────────────────────────────────────────────────────────────────────────────
# REGISTRE DES TRAITEMENTS
# ─────────────────────────────────────────────────────────────────────────────
class ProcessingRecordCreate(BaseModel):
    code: str = Field(min_length=2, max_length=50, pattern=r"^[A-Z0-9_-]+$")
    nom: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=10, max_length=5000)

    finalite: str
    base_legale: BaseLegaleT
    base_legale_justification: str | None = None

    responsable_nom: str | None = None
    responsable_email: EmailStr | None = None
    responsable_telephone: str | None = None

    sous_traitants: list[dict[str, Any]] = Field(default_factory=list)
    categories_personnes: list[str] = Field(default_factory=list)
    categories_donnees: list[str] = Field(default_factory=list)
    contient_donnees_sensibles: bool = False

    duree_conservation_mois: int | None = Field(None, ge=1, le=600)
    duree_conservation_justification: str | None = None

    transfert_hors_ci: bool = False
    transfert_pays: list[str] = Field(default_factory=list)
    transfert_garanties: str | None = None

    mesures_securite: list[str] = Field(default_factory=list)

    aipd_requise: bool = False
    date_revue_prevue: date | None = None


class ProcessingRecordUpdate(BaseModel):
    nom: str | None = None
    description: str | None = None
    base_legale: BaseLegaleT | None = None
    base_legale_justification: str | None = None
    responsable_nom: str | None = None
    responsable_email: EmailStr | None = None
    responsable_telephone: str | None = None
    sous_traitants: list[dict[str, Any]] | None = None
    categories_personnes: list[str] | None = None
    categories_donnees: list[str] | None = None
    contient_donnees_sensibles: bool | None = None
    duree_conservation_mois: int | None = Field(None, ge=1, le=600)
    transfert_hors_ci: bool | None = None
    transfert_pays: list[str] | None = None
    mesures_securite: list[str] | None = None
    aipd_requise: bool | None = None
    aipd_realisee: bool | None = None
    aipd_niveau_risque: NiveauRisqueT | None = None
    actif: bool | None = None
    date_revue_prevue: date | None = None


class ProcessingRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    code: str
    nom: str
    description: str
    finalite: str
    base_legale: str
    base_legale_justification: str | None
    responsable_nom: str | None
    responsable_email: str | None
    sous_traitants: list[dict[str, Any]]
    categories_personnes: list[str]
    categories_donnees: list[str]
    contient_donnees_sensibles: bool
    duree_conservation_mois: int | None
    transfert_hors_ci: bool
    transfert_pays: list[str]
    mesures_securite: list[str]
    aipd_requise: bool
    aipd_realisee: bool
    aipd_niveau_risque: str | None
    actif: bool
    date_revue_prevue: date | None
    created_at: datetime
    updated_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# CONSENTEMENTS
# ─────────────────────────────────────────────────────────────────────────────
class ConsentCreate(BaseModel):
    finalite: str
    version_politique: str = Field(min_length=1, max_length=20)
    texte_consentement: str = Field(min_length=10)
    email: EmailStr | None = None
    telephone: str | None = None
    nom_complet: str | None = None
    source: Literal["web", "mobile", "email", "papier", "api"] = "web"


class ConsentRetraitIn(BaseModel):
    motif: str = Field(min_length=5, max_length=500)


class ConsentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    user_id: UUID | None
    portal_user_id: UUID | None
    email: str | None
    telephone: str | None
    nom_complet: str | None
    finalite: str
    version_politique: str
    statut: str
    texte_consentement: str
    ip_address: str | None
    source: str
    accorde_at: datetime
    retire_at: datetime | None
    expire_at: datetime | None
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# DEMANDES DE DROIT
# ─────────────────────────────────────────────────────────────────────────────
class DataSubjectRequestCreate(BaseModel):
    email: EmailStr
    nom_complet: str = Field(min_length=2, max_length=200)
    telephone: str | None = None
    type_droit: TypeDroitT
    description_demande: str = Field(min_length=10, max_length=5000)
    pieces_jointes: list[dict[str, Any]] = Field(default_factory=list)
    user_id: UUID | None = None
    portal_user_id: UUID | None = None


class DSRVerifyIdentityIn(BaseModel):
    methode_verification: str = Field(min_length=3, max_length=50)
    commentaire: str | None = None


class DSRProlongationIn(BaseModel):
    motif: str = Field(min_length=10, max_length=500)


class DSRReponseIn(BaseModel):
    reponse: str = Field(min_length=10, max_length=10000)
    document_reponse_url: str | None = None
    statut: Literal["acceptee", "refusee", "partiellement_satisfaite"] = "acceptee"


class DataSubjectRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    reference: str
    demandeur_type: str
    user_id: UUID | None
    portal_user_id: UUID | None
    email: str
    nom_complet: str
    telephone: str | None
    type_droit: str
    description_demande: str
    pieces_jointes: list[dict[str, Any]]
    identite_verifiee: bool
    methode_verification: str | None
    statut: str
    date_limite: date
    prolongation: bool
    nouvelle_date_limite: date | None
    motif_prolongation: str | None
    traite_par_user_id: UUID | None
    traite_at: datetime | None
    reponse: str | None
    motif_refus: str | None
    document_reponse_url: str | None
    created_at: datetime
    updated_at: datetime


class RequestActionLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    action: str
    user_id: UUID | None
    ancien_statut: str | None
    nouveau_statut: str | None
    commentaire: str | None
    created_at: datetime


class DataSubjectRequestDetailOut(DataSubjectRequestOut):
    actions: list[RequestActionLogOut] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# VIOLATIONS DE DONNÉES
# ─────────────────────────────────────────────────────────────────────────────
class DataBreachCreate(BaseModel):
    titre: str = Field(min_length=5, max_length=200)
    description: str = Field(min_length=20, max_length=10000)
    type_incident: TypeIncidentT
    gravite: GraviteT
    categories_donnees_affectees: list[str] = Field(default_factory=list)
    nb_personnes_affectees: int | None = Field(None, ge=0)
    personnes_affectees_ids: list[str] = Field(default_factory=list)
    detecte_at: datetime
    survenu_at: datetime | None = None
    cause_racine: str | None = None
    vecteur: str | None = None
    mesures_immediates: str | None = None
    mesures_correctives: str | None = None
    prevention_future: str | None = None
    impact_estime_xof: int | None = Field(None, ge=0)
    impact_description: str | None = None


class DataBreachUpdate(BaseModel):
    titre: str | None = None
    description: str | None = None
    gravite: GraviteT | None = None
    nb_personnes_affectees: int | None = None
    maitrise_at: datetime | None = None
    cause_racine: str | None = None
    mesures_correctives: str | None = None
    prevention_future: str | None = None
    statut: StatutIncidentT | None = None


class DataBreachNotifyAuthorityIn(BaseModel):
    autorite: Literal["artci", "cnil", "autre"]
    reference_autorite: str | None = None
    contenu_notification: str = Field(min_length=20, max_length=10000)


class DataBreachNotifyPersonsIn(BaseModel):
    contenu_notification: str = Field(min_length=20, max_length=10000)


class DataBreachOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    reference: str
    titre: str
    description: str
    type_incident: str
    gravite: str
    categories_donnees_affectees: list[str]
    nb_personnes_affectees: int | None
    detecte_at: datetime
    survenu_at: datetime | None
    maitrise_at: datetime | None
    cloture_at: datetime | None
    cause_racine: str | None
    vecteur: str | None
    mesures_immediates: str | None
    mesures_correctives: str | None
    notification_autorite_requise: bool
    notification_autorite_at: datetime | None
    autorite_notifiee: str | None
    reference_autorite: str | None
    notification_personnes_requise: bool
    notification_personnes_at: datetime | None
    statut: str
    impact_estime_xof: int | None
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# DPO
# ─────────────────────────────────────────────────────────────────────────────
class DPOCreate(BaseModel):
    type_dpo: Literal["interne", "externe"] = "interne"
    nom_complet: str = Field(min_length=2, max_length=200)
    email: EmailStr
    telephone: str | None = None
    organisation: str | None = None
    numero_enregistrement: str | None = None
    user_id: UUID | None = None
    publie_sur_site: bool = True
    adresse_postale: str | None = None
    date_debut: date


class DPOOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    type_dpo: str
    nom_complet: str
    email: str
    telephone: str | None
    organisation: str | None
    numero_enregistrement: str | None
    publie_sur_site: bool
    notifie_artci: bool
    notifie_artci_at: datetime | None
    actif: bool
    date_debut: date
    date_fin: date | None
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# DOCUMENTS LÉGAUX
# ─────────────────────────────────────────────────────────────────────────────
class LegalDocumentCreate(BaseModel):
    type_document: str
    version: str = Field(min_length=1, max_length=20)
    titre: str = Field(min_length=3, max_length=200)
    contenu: str = Field(min_length=100)
    langue: str = Field("fr", min_length=2, max_length=5)
    date_effet: date
    url_publication: str | None = None


class LegalDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID | None
    type_document: str
    version: str
    titre: str
    contenu: str
    langue: str
    date_effet: date
    date_publication: datetime | None
    actif: bool
    est_version_actuelle: bool
    pdf_url: str | None
    url_publication: str | None
    notification_envoyee: bool
    created_at: datetime


class LegalDocumentBriefOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    type_document: str
    version: str
    titre: str
    langue: str
    date_effet: date
    est_version_actuelle: bool


# ─────────────────────────────────────────────────────────────────────────────
# COOKIES
# ─────────────────────────────────────────────────────────────────────────────
class CookieConsentIn(BaseModel):
    session_id: str = Field(min_length=10, max_length=64)
    essentiels: bool = True
    fonctionnels: bool = False
    analytiques: bool = False
    marketing: bool = False
    reseaux_sociaux: bool = False
    version_politique: str = Field(min_length=1, max_length=20)


class CookieConsentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    session_id: str
    essentiels: bool
    fonctionnels: bool
    analytiques: bool
    marketing: bool
    reseaux_sociaux: bool
    version_politique: str
    accepte_at: datetime
    modifie_at: datetime | None
    expire_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# SOUS-TRAITANTS
# ─────────────────────────────────────────────────────────────────────────────
class DataProcessorCreate(BaseModel):
    nom: str = Field(min_length=2, max_length=200)
    raison_sociale: str | None = None
    pays: str = Field(min_length=2, max_length=2)
    adresse: str | None = None
    contact_nom: str | None = None
    contact_email: EmailStr | None = None
    service: str = Field(min_length=3, max_length=500)
    categories_donnees: list[str] = Field(default_factory=list)
    dpa_signe: bool = False
    dpa_signe_at: date | None = None
    dpa_url: str | None = None
    certifications: list[str] = Field(default_factory=list)
    transfert_hors_ci: bool = False
    garanties_transfert: str | None = None


class DataProcessorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID | None
    nom: str
    raison_sociale: str | None
    pays: str
    contact_nom: str | None
    contact_email: str | None
    service: str
    categories_donnees: list[str]
    dpa_signe: bool
    dpa_signe_at: date | None
    certifications: list[str]
    transfert_hors_ci: bool
    actif: bool
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# AIPD
# ─────────────────────────────────────────────────────────────────────────────
class ImpactAssessmentCreate(BaseModel):
    processing_record_id: UUID | None = None
    titre: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=20)
    raisons_aipd: list[str] = Field(default_factory=list)
    description_traitement: str = Field(min_length=20)
    necessite_proportionnalite: str | None = None
    risques_personnes: list[dict[str, Any]] = Field(default_factory=list)
    mesures_risques: list[dict[str, Any]] = Field(default_factory=list)
    niveau_risque: NiveauRisqueT = "moyen"
    date_revue_prevue: date | None = None


class ImpactAssessmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    processing_record_id: UUID | None
    reference: str
    titre: str
    description: str
    necessite_aipd: bool
    raisons_aipd: list[str]
    description_traitement: str
    risques_personnes: list[dict[str, Any]]
    mesures_risques: list[dict[str, Any]]
    niveau_risque: str
    avis_dpo: str | None
    avis_dpo_at: datetime | None
    consultation_autorite_requise: bool
    consultation_autorite_at: datetime | None
    statut: str
    date_validation: date | None
    date_revue_prevue: date | None
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD CONFORMITÉ
# ─────────────────────────────────────────────────────────────────────────────
class PrivacyDashboardOut(BaseModel):
    tenant_id: UUID
    date_arret: date
    nb_traitements_actifs: int
    nb_traitements_donnees_sensibles: int
    nb_aipd_requises: int
    nb_aipd_realisees: int
    nb_demandeurs_droits_ouverts: int
    nb_demandes_en_retard: int
    nb_demandes_cloturees_30j: int
    nb_incidents_ouverts: int
    nb_incidents_critiques: int
    nb_consentements_actifs: int
    nb_consentements_retires: int
    dpo_actif: bool
    dpo_nom: str | None
    score_conformite_pct: float
    alertes: list[dict[str, Any]]


class ComplianceScoreBreakdown(BaseModel):
    registre_traitements_pct: float
    droits_personnes_pct: float
    securite_pct: float
    violations_pct: float
    consentements_pct: float
    documentation_pct: float
    score_global_pct: float
    recommandations: list[str]


# ─────────────────────────────────────────────────────────────────────────────
# PORTABILITÉ (export des données)
# ─────────────────────────────────────────────────────────────────────────────
class PortabilityExportIn(BaseModel):
    email: EmailStr
    format: Literal["json", "csv", "xlsx"] = "json"
    inclure_donnees: list[str] = Field(default_factory=list)
    # ["profil", "factures", "paiements", "ecritures", "documents"]


class PortabilityExportOut(BaseModel):
    reference: str
    format: str
    statut: str
    fichier_url: str | None
    expire_at: datetime
    created_at: datetime
