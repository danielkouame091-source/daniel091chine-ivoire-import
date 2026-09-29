"""DTO Business Intelligence & Reporting."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

TypeWidgetT = Literal[
    "kpi_card", "line_chart", "bar_chart", "pie_chart", "donut_chart",
    "area_chart", "table", "heatmap", "gauge", "funnel", "scatter",
    "treemap", "waterfall", "sparkline", "calendar_heatmap",
]
SourceT = Literal[
    "ecritures", "balance", "grand_livre", "compte_resultat", "bilan",
    "clients", "fournisseurs", "factures_clients", "factures_fournisseurs",
    "tresorerie", "rapprochement", "stocks", "immobilisations",
    "projets", "situations_travaux", "paie", "employes", "conges",
    "budgets", "analytique", "fne", "audit", "abonnements",
]
FormatT = Literal["number", "montant", "montant_compact", "pourcentage", "date", "duree", "boolean"]
AgregationT = Literal["sum", "count", "avg", "min", "max", "distinct_count", "median", "stddev"]
OperateurT = Literal["eq", "neq", "gt", "gte", "lt", "lte", "in", "not_in", "between", "like", "is_null", "is_not_null"]


# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARDS
# ─────────────────────────────────────────────────────────────────────────────
class WidgetPosition(BaseModel):
    x: int = Field(0, ge=0, le=11)
    y: int = Field(0, ge=0)
    w: int = Field(3, ge=1, le=12)
    h: int = Field(2, ge=1, le=20)

    @model_validator(mode="after")
    def coherent(self):
        if self.x + self.w > 12:
            raise ValueError("x + w ne doit pas dépasser 12")
        return self


class WidgetCreate(BaseModel):
    titre: str = Field(min_length=2, max_length=200)
    description: str | None = None
    type_widget: TypeWidgetT
    source: SourceT
    kpi_code: str | None = None
    requete: dict[str, Any] | None = None

    position_x: int = Field(0, ge=0, le=11)
    position_y: int = Field(0, ge=0)
    largeur: int = Field(3, ge=1, le=12)
    hauteur: int = Field(2, ge=1, le=20)

    format_affichage: FormatT = "montant"
    couleur: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    icone: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)

    afficher_variation: bool = True
    periode_comparaison: str | None = None

    objectif_valeur: float | None = None
    objectif_type: Literal["above", "below"] | None = None

    drill_down_url: str | None = None
    drill_down_filtres: dict[str, Any] | None = None

    seuil_alerte_bas: float | None = None
    seuil_alerte_haut: float | None = None

    ordre: int = 0

    @model_validator(mode="after")
    def coherent(self):
        if not self.kpi_code and not self.requete:
            raise ValueError("kpi_code OU requete requis")
        if self.position_x + self.largeur > 12:
            raise ValueError("position_x + largeur ne doit pas dépasser 12")
        return self


class WidgetUpdate(BaseModel):
    titre: str | None = None
    description: str | None = None
    kpi_code: str | None = None
    requete: dict[str, Any] | None = None
    position_x: int | None = Field(None, ge=0, le=11)
    position_y: int | None = Field(None, ge=0)
    largeur: int | None = Field(None, ge=1, le=12)
    hauteur: int | None = Field(None, ge=1, le=20)
    format_affichage: FormatT | None = None
    couleur: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    icone: str | None = None
    options: dict[str, Any] | None = None
    afficher_variation: bool | None = None
    objectif_valeur: float | None = None
    objectif_type: Literal["above", "below"] | None = None
    seuil_alerte_bas: float | None = None
    seuil_alerte_haut: float | None = None
    ordre: int | None = None
    actif: bool | None = None


class WidgetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    dashboard_id: UUID
    titre: str
    description: str | None
    type_widget: str
    source: str
    kpi_code: str | None
    requete: dict[str, Any] | None
    position_x: int
    position_y: int
    largeur: int
    hauteur: int
    format_affichage: str
    couleur: str | None
    icone: str | None
    options: dict[str, Any]
    afficher_variation: bool
    objectif_valeur: float | None
    objectif_type: str | None
    drill_down_url: str | None
    seuil_alerte_bas: float | None
    seuil_alerte_haut: float | None
    ordre: int
    actif: bool
    created_at: datetime


class DashboardCreate(BaseModel):
    code: str = Field(min_length=2, max_length=50, pattern=r"^[A-Z0-9_-]+$")
    nom: str = Field(min_length=2, max_length=200)
    description: str | None = None
    categorie: str = "general"
    layout_columns: int = Field(12, ge=6, le=24)
    ordre: int = 0
    filtres_defaut: dict[str, Any] = Field(default_factory=dict)
    theme: Literal["light", "dark", "auto"] = "light"
    palette: list[str] = Field(default_factory=list)
    roles_autorises: list[str] = Field(default_factory=list)
    epingle: bool = False


class DashboardUpdate(BaseModel):
    nom: str | None = None
    description: str | None = None
    categorie: str | None = None
    layout_columns: int | None = Field(None, ge=6, le=24)
    ordre: int | None = None
    filtres_defaut: dict[str, Any] | None = None
    theme: Literal["light", "dark", "auto"] | None = None
    palette: list[str] | None = None
    roles_autorises: list[str] | None = None
    est_defaut: bool | None = None
    epingle: bool | None = None
    actif: bool | None = None


class DashboardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    code: str
    nom: str
    description: str | None
    categorie: str
    layout_columns: int
    ordre: int
    filtres_defaut: dict[str, Any]
    theme: str
    palette: list[str]
    est_public: bool
    roles_autorises: list[str]
    est_defaut: bool
    epingle: bool
    actif: bool
    created_at: datetime
    updated_at: datetime


class DashboardDetailOut(DashboardOut):
    widgets: list[WidgetOut] = Field(default_factory=list)


class DashboardDuplicateIn(BaseModel):
    code: str = Field(min_length=2, max_length=50, pattern=r"^[A-Z0-9_-]+$")
    nom: str = Field(min_length=2, max_length=200)


class DashboardPartageIn(BaseModel):
    expire_at: datetime | None = None
    roles_autorises: list[str] = Field(default_factory=list)


class DashboardPartageOut(BaseModel):
    dashboard_id: UUID
    partage_token: str
    partage_url: str
    expire_at: datetime | None


# ─────────────────────────────────────────────────────────────────────────────
# FILTRES DYNAMIQUES
# ─────────────────────────────────────────────────────────────────────────────
class FiltreItem(BaseModel):
    field: str = Field(min_length=1, max_length=50)
    operateur: OperateurT
    valeur: Any = None


class FiltreDashboard(BaseModel):
    date_debut: date | None = None
    date_fin: date | None = None
    periode: str | None = None
    exercice: int | None = None
    departement_id: UUID | None = None
    client_id: UUID | None = None
    fournisseur_id: UUID | None = None
    projet_id: UUID | None = None
    compte_prefixe: str | None = None
    filtres_custom: list[FiltreItem] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# RÉSULTAT KPI
# ─────────────────────────────────────────────────────────────────────────────
class KPIValueOut(BaseModel):
    kpi_code: str
    source: str
    libelle: str | None
    valeur: float
    valeur_formatee: str
    format_affichage: str
    unite: str | None
    valeur_precedente: float | None = None
    variation_pct: float | None = None
    tendance: Literal["up", "down", "flat"] | None = None
    objectif_valeur: float | None = None
    objectif_atteint_pct: float | None = None
    en_alerte: bool = False
    serie: list[dict[str, Any]] | None = None     # Pour les séries temporelles
    breakdown: list[dict[str, Any]] | None = None  # Pour les répartitions
    calcule_at: datetime
    depuis_cache: bool = False


class KPIStandardOut(BaseModel):
    code: str
    libelle: str
    description: str
    source: str
    format_affichage: str
    unite: str | None


class KPIResultSetOut(BaseModel):
    dashboard_id: UUID
    filtres_appliques: dict[str, Any]
    kpis: dict[str, KPIValueOut]   # key = widget_id ou kpi_code
    calcule_at: datetime
    duree_ms: int


# ─────────────────────────────────────────────────────────────────────────────
# RAPPORTS SAUVEGARDÉS
# ─────────────────────────────────────────────────────────────────────────────
class ReportCreate(BaseModel):
    code: str = Field(min_length=2, max_length=50, pattern=r"^[A-Z0-9_-]+$")
    nom: str = Field(min_length=2, max_length=200)
    description: str | None = None
    categorie: str = "general"
    source: SourceT
    config: dict[str, Any]
    roles_autorises: list[str] = Field(default_factory=list)
    planifie: bool = False
    cron_expression: str | None = None
    destinataires_email: list[str] = Field(default_factory=list)
    format_export: Literal["xlsx", "pdf", "csv"] = "xlsx"


class ReportUpdate(BaseModel):
    nom: str | None = None
    description: str | None = None
    categorie: str | None = None
    config: dict[str, Any] | None = None
    roles_autorises: list[str] | None = None
    planifie: bool | None = None
    cron_expression: str | None = None
    destinataires_email: list[str] | None = None
    format_export: Literal["xlsx", "pdf", "csv"] | None = None
    actif: bool | None = None


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    code: str
    nom: str
    description: str | None
    categorie: str
    source: str
    config: dict[str, Any]
    planifie: bool
    cron_expression: str | None
    destinataires_email: list[str]
    format_export: str
    derniere_execution_at: datetime | None
    derniere_execution_statut: str | None
    actif: bool
    created_at: datetime


class ReportRunIn(BaseModel):
    filtres: FiltreDashboard | None = None
    limit: int = Field(500, ge=1, le=10_000)
    page: int = Field(1, ge=1)


class ReportRunOut(BaseModel):
    report_id: UUID
    colonnes: list[dict[str, Any]]
    lignes: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
    total_pages: int
    duree_ms: int


# ─────────────────────────────────────────────────────────────────────────────
# EXPORTS
# ─────────────────────────────────────────────────────────────────────────────
class ExportRequestIn(BaseModel):
    type_source: Literal["dashboard", "report", "ad_hoc"]
    source_id: UUID | None = None
    format: Literal["xlsx", "pdf", "csv"]
    filtres: FiltreDashboard | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class ExportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    reference: str
    type_source: str
    source_id: UUID | None
    format: str
    statut: str
    progression_pct: int
    fichier_url: str | None
    fichier_nom: str | None
    fichier_taille_kb: int | None
    erreur: str | None
    expire_at: datetime | None
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# SNAPSHOTS KPI
# ─────────────────────────────────────────────────────────────────────────────
class KPISnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    kpi_code: str
    source: str
    date_snapshot: date
    periodicite: str
    valeur: float
    valeur_precedente: float | None
    variation_pct: float | None
    created_at: datetime


class KPITrendOut(BaseModel):
    kpi_code: str
    date_debut: date
    date_fin: date
    periodicite: str
    points: list[dict[str, Any]]     # [{"date": ..., "valeur": ...}, ...]
    valeur_min: float
    valeur_max: float
    valeur_moyenne: float
    tendance: Literal["hausse", "baisse", "stable"]
    variation_pct: float


# ─────────────────────────────────────────────────────────────────────────────
# ANALYTICS BI
# ─────────────────────────────────────────────────────────────────────────────
class BIAnalyticsOut(BaseModel):
    tenant_id: UUID
    periode_debut: datetime
    periode_fin: datetime
    nb_dashboards: int
    nb_widgets: int
    nb_rapports: int
    nb_exports: int
    nb_consultations: int
    top_dashboards: list[dict[str, Any]]
    top_kpis: list[dict[str, Any]]
    duree_moyenne_calcul_ms: int
    taux_cache_hit_pct: float
