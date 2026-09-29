"""Modèles Business Intelligence — Dashboards, Widgets, KPI snapshots."""
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
# DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────
class Dashboard(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Dashboard configurable avec widgets."""
    __tablename__ = "dashboards"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    code: Mapped[str] = mapped_column(String(50), nullable=False)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    categorie: Mapped[str] = mapped_column(
        String(30), nullable=False, default="general", server_default="general"
    )

    # Mise en page
    layout_columns: Mapped[int] = mapped_column(Integer, nullable=False, default=12, server_default="12")
    ordre: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Filtres par défaut du dashboard
    filtres_defaut: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    # Thème & préférences d'affichage
    theme: Mapped[str] = mapped_column(
        String(20), nullable=False, default="light", server_default="light"
    )
    palette: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    # Partage
    est_public: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    partage_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    partage_expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Sécurité
    roles_autorises: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )   # [] = tous les rôles

    # Statut
    est_defaut: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    epingle: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    # Auteur
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_dashboard_code"),
        Index("idx_dash_tenant_actif", "tenant_id", "actif"),
        Index("idx_dash_tenant_categorie", "tenant_id", "categorie"),
    )

    def __repr__(self) -> str:
        return f"<Dashboard {self.code} — {self.nom}>"


# ─────────────────────────────────────────────────────────────────────────────
# WIDGET
# ─────────────────────────────────────────────────────────────────────────────
class DashboardWidget(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Widget individuel dans un dashboard.
    Contient la définition du KPI, la source, la position, et les options.
    """
    __tablename__ = "dashboard_widgets"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dashboard_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("dashboards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Identification
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    type_widget: Mapped[str] = mapped_column(String(30), nullable=False)

    # Source de données
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    # Requête : soit un kpi_code (défini), soit une requête JSONB personnalisée
    kpi_code: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Requête personnalisée (JSONB)
    # Ex : {"filters": [...], "group_by": "month", "aggregation": "sum", "field": "total_ttc"}
    requete: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Position (grid layout 12 colonnes)
    position_x: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    position_y: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    largeur: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    hauteur: Mapped[int] = mapped_column(Integer, nullable=False, default=2, server_default="2")

    # Affichage
    format_affichage: Mapped[str] = mapped_column(
        String(20), nullable=False, default="montant", server_default="montant"
    )
    couleur: Mapped[str | None] = mapped_column(String(7), nullable=True)
    icone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    options: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    # Ex : {"show_legend": true, "show_grid": false, "stacked": true}

    # Comparaison (afficher variation vs période précédente)
    afficher_variation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    periode_comparaison: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # Objectif (target)
    objectif_valeur: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    objectif_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # above | below

    # Drill-down
    drill_down_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    drill_down_filtres: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Alertes
    seuil_alerte_bas: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    seuil_alerte_haut: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)

    ordre: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_widget_dashboard", "dashboard_id", "ordre"),
        Index("idx_widget_tenant_type", "tenant_id", "type_widget"),
    )

    def __repr__(self) -> str:
        return f"<DashboardWidget {self.titre} ({self.type_widget})>"


# ─────────────────────────────────────────────────────────────────────────────
# SNAPSHOT KPI (historique)
# ─────────────────────────────────────────────────────────────────────────────
class KPISnapshot(UUIDPrimaryKeyMixin, Base):
    """
    Snapshot périodique d'un KPI (pour tracer les tendances).
    Généré par le worker quotidien.
    """
    __tablename__ = "kpi_snapshots"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    kpi_code: Mapped[str] = mapped_column(String(50), nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)

    date_snapshot: Mapped[date] = mapped_column(Date, nullable=False)
    periodicite: Mapped[str] = mapped_column(
        String(20), nullable=False, default="jour", server_default="jour"
    )

    # Valeur calculée
    valeur: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    valeur_precedente: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    variation_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)

    # Contexte
    filtres_appliques: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "kpi_code", "date_snapshot", "periodicite",
            name="uq_kpi_snapshot",
        ),
        Index("idx_kpi_snapshot_tenant_date", "tenant_id", "date_snapshot"),
        Index("idx_kpi_snapshot_kpi", "tenant_id", "kpi_code", "date_snapshot"),
    )

    def __repr__(self) -> str:
        return f"<KPISnapshot {self.kpi_code} @ {self.date_snapshot}={self.valeur}>"


# ─────────────────────────────────────────────────────────────────────────────
# RAPPORT SAUVEGARDÉ
# ─────────────────────────────────────────────────────────────────────────────
class SavedReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Rapport tabulaire sauvegardé (vue filtrable + exportable).
    """
    __tablename__ = "saved_reports"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    code: Mapped[str] = mapped_column(String(50), nullable=False)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    categorie: Mapped[str] = mapped_column(
        String(30), nullable=False, default="general", server_default="general"
    )

    # Source
    source: Mapped[str] = mapped_column(String(30), nullable=False)

    # Configuration (JSONB)
    # Ex : {"columns": [...], "filters": [...], "sort": [...], "group_by": [...]}
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    # Exécution programmée
    planifie: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    cron_expression: Mapped[str | None] = mapped_column(String(50), nullable=True)
    destinataires_email: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    format_export: Mapped[str] = mapped_column(
        String(10), nullable=False, default="xlsx", server_default="xlsx"
    )

    # Dernière exécution
    derniere_execution_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    derniere_execution_statut: Mapped[str | None] = mapped_column(String(20), nullable=True)
    derniere_erreur: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Partage
    roles_autorises: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_saved_report_code"),
        Index("idx_report_tenant_actif", "tenant_id", "actif"),
    )

    def __repr__(self) -> str:
        return f"<SavedReport {self.code} — {self.nom}>"


# ─────────────────────────────────────────────────────────────────────────────
# EXPORT
# ─────────────────────────────────────────────────────────────────────────────
class ReportExport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Export de rapport (asynchrone) — fichier stocké dans S3."""
    __tablename__ = "report_exports"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    reference: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)

    # Source
    type_source: Mapped[str] = mapped_column(String(30), nullable=False)
    # dashboard | report | ad_hoc
    source_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    format: Mapped[str] = mapped_column(String(10), nullable=False)   # xlsx | pdf | csv

    # Paramètres (filtres au moment de l'export)
    parametres: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    # Statut
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="en_cours", server_default="en_cours"
    )   # en_cours | termine | echoue | expire
    progression_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Fichier généré
    fichier_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    fichier_nom: Mapped[str | None] = mapped_column(Text, nullable=True)
    fichier_taille_kb: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Erreur
    erreur: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Expiration (nettoyage auto)
    expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_export_tenant_statut", "tenant_id", "statut"),
    )

    def __repr__(self) -> str:
        return f"<ReportExport {self.reference} ({self.format}) statut={self.statut}>"


# ─────────────────────────────────────────────────────────────────────────────
# CACHE KPI (mémoire courte)
# ─────────────────────────────────────────────────────────────────────────────
class KPICache(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Cache court-terme des résultats KPI.
    Évite de recalculer un même KPI 100 fois par minute.
    """
    __tablename__ = "kpi_cache"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Clé de cache : hash de (kpi_code + filtres sérialisés)
    cache_key: Mapped[str] = mapped_column(String(64), nullable=False)

    kpi_code: Mapped[str] = mapped_column(String(50), nullable=False)
    filtres_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Valeur mise en cache
    valeur: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    valeur_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # TTL
    calcule_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "cache_key", name="uq_kpi_cache_key"),
        Index("idx_kpi_cache_expire", "expire_at"),
    )

    def __repr__(self) -> str:
        return f"<KPICache {self.kpi_code} key={self.cache_key[:8]}>"
