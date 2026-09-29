"""Modèles Audit & Contrôle interne."""
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
# RÈGLE D'AUDIT (paramétrable par tenant)
# ─────────────────────────────────────────────────────────────────────────────
class AuditRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Règle de contrôle interne paramétrable.
    Chaque tenant peut activer/désactiver et ajuster les seuils.
    """
    __tablename__ = "audit_rules"

    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,       # NULL = règle globale système
        index=True,
    )

    code: Mapped[str] = mapped_column(String(50), nullable=False)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    categorie: Mapped[str] = mapped_column(String(30), nullable=False)
    type_regle: Mapped[str] = mapped_column(String(50), nullable=False)

    severite: Mapped[str] = mapped_column(
        String(20), nullable=False, default="medium", server_default="medium"
    )

    # Activation
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    frequence: Mapped[str] = mapped_column(
        String(20), nullable=False, default="quotidien", server_default="quotidien"
    )   # temps_reel | quotidien | hebdomadaire | mensuel | annuel | manuel

    # Paramètres (seuils spécifiques à cette règle)
    parametres: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    # Documentation
    reference_legale: Mapped[str | None] = mapped_column(Text, nullable=True)
    procedure_resolution: Mapped[str | None] = mapped_column(Text, nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_audit_rule_tenant_code"),
        Index("idx_audit_rule_tenant_active", "tenant_id", "active"),
        Index("idx_audit_rule_categorie", "tenant_id", "categorie"),
    )

    def __repr__(self) -> str:
        return f"<AuditRule {self.code} ({self.severite})>"


# ─────────────────────────────────────────────────────────────────────────────
# EXÉCUTION DE RÈGLE (run)
# ─────────────────────────────────────────────────────────────────────────────
class AuditRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Une exécution de règle d'audit (batch ou temps réel).
    Snapshot immuable des résultats.
    """
    __tablename__ = "audit_runs"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rule_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("audit_rules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    reference: Mapped[str] = mapped_column(String(50), nullable=False)
    date_debut: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_fin: Mapped[date | None] = mapped_column(Date, nullable=True)

    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="en_cours", server_default="en_cours"
    )   # en_cours | succes | erreur

    nb_lignes_analysees: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    nb_findings: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    severite_max: Mapped[str | None] = mapped_column(String(20), nullable=True)

    duree_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    erreur: Mapped[str | None] = mapped_column(Text, nullable=True)

    declencheur: Mapped[str] = mapped_column(
        String(20), nullable=False, default="cron", server_default="cron"
    )   # cron | manuel | webhook

    execute_par: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "reference", name="uq_audit_run_ref"),
        Index("idx_audit_run_tenant_date", "tenant_id", "created_at"),
        Index("idx_audit_run_rule", "rule_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<AuditRun {self.reference} ({self.nb_findings} findings)>"


# ─────────────────────────────────────────────────────────────────────────────
# FINDING D'AUDIT (anomalie détectée)
# ─────────────────────────────────────────────────────────────────────────────
class AuditFinding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Anomalie détectée par une règle d'audit.
    Chaque finding peut être résolu, ignoré ou escaladé.
    """
    __tablename__ = "audit_findings"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rule_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("audit_rules.id"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("audit_runs.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Identification
    reference: Mapped[str] = mapped_column(String(50), nullable=False)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severite: Mapped[str] = mapped_column(String(20), nullable=False)

    # Ressource concernée
    ressource_type: Mapped[str] = mapped_column(String(30), nullable=False)
    ressource_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True, index=True)
    ressource_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Données détaillées (pour investigation)
    donnees: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    # Recommandation
    recommandation: Mapped[str | None] = mapped_column(Text, nullable=True)
    impact_estime: Mapped[int | None] = mapped_column(BigInteger, nullable=True)   # FCFA

    # Workflow
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="nouveau", server_default="nouveau"
    )
    assigne_a: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    resolu_par: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    resolu_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    commentaire_resolution: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Escalade
    escalade_fondateur: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    escalade_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "reference", name="uq_audit_finding_ref"),
        Index("idx_audit_finding_tenant_statut", "tenant_id", "statut"),
        Index("idx_audit_finding_tenant_severite", "tenant_id", "severite"),
        Index("idx_audit_finding_rule", "rule_id", "created_at"),
        Index("idx_audit_finding_ressource", "ressource_type", "ressource_id"),
    )

    def __repr__(self) -> str:
        return f"<AuditFinding {self.reference} ({self.severite}) statut={self.statut}>"


# ─────────────────────────────────────────────────────────────────────────────
# PISTE D'AUDIT (audit trail immuable)
# ─────────────────────────────────────────────────────────────────────────────
class AuditTrail(UUIDPrimaryKeyMixin, Base):
    """
    Piste d'audit exhaustive — chaque action sensible est tracée.
    Immuable : aucun UPDATE/DELETE autorisé (RLS policy stricte).
    Hash-chained pour détecter toute altération.
    """
    __tablename__ = "audit_trails"

    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Action
    action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    categorie: Mapped[str] = mapped_column(String(30), nullable=False)

    # Ressource
    ressource_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    ressource_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    ressource_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Contexte
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)   # IPv6
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    endpoint: Mapped[str | None] = mapped_column(String(200), nullable=True)
    methode_http: Mapped[str | None] = mapped_column(String(10), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    session_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    # Données
    avant: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    apres: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Statut
    succes: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    code_erreur: Mapped[str | None] = mapped_column(String(50), nullable=True)
    message_erreur: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Hash-chain (immuabilité)
    hash_precedent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hash_courant: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        Index("idx_at_tenant_date", "tenant_id", "created_at"),
        Index("idx_at_tenant_action", "tenant_id", "action"),
        Index("idx_at_tenant_user", "tenant_id", "user_id"),
        Index("idx_at_ressource", "ressource_type", "ressource_id"),
        Index("idx_at_hash", "tenant_id", "hash_courant"),
    )

    def __repr__(self) -> str:
        return f"<AuditTrail {self.action} on {self.ressource_type}>"


# ─────────────────────────────────────────────────────────────────────────────
# RAPPORT DE CONFORMITÉ
# ─────────────────────────────────────────────────────────────────────────────
class ComplianceReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Rapport de conformité OHADA / DGI.
    Généré périodiquement, liste les contrôles passés/échoués.
    """
    __tablename__ = "compliance_reports"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    reference: Mapped[str] = mapped_column(String(50), nullable=False)
    type_rapport: Mapped[str] = mapped_column(
        String(30), nullable=False, default="mensuel", server_default="mensuel"
    )   # mensuel | trimestriel | annuel | ad_hoc

    periode_debut: Mapped[date] = mapped_column(Date, nullable=False)
    periode_fin: Mapped[date] = mapped_column(Date, nullable=False)

    # Scores
    score_global: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    score_ohada: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    score_dgi: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    score_securite: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)

    nb_checks_total: Mapped[int] = mapped_column(Integer, nullable=False)
    nb_checks_reussis: Mapped[int] = mapped_column(Integer, nullable=False)
    nb_checks_echoues: Mapped[int] = mapped_column(Integer, nullable=False)
    nb_checks_non_applicables: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Détail (liste des checks avec statut et preuves)
    detail_checks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)

    # Findings liés
    nb_findings_critiques: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    nb_findings_hauts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    resume_ia: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="brouillon", server_default="brouillon"
    )
    genere_par: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "reference", name="uq_compliance_report_ref"),
        Index("idx_compliance_tenant_periode", "tenant_id", "periode_fin"),
    )

    def __repr__(self) -> str:
        return f"<ComplianceReport {self.reference} score={self.score_global}>"


# ─────────────────────────────────────────────────────────────────────────────
# ANOMALIE COMPTABLE DÉTECTÉE PAR LOI DE BENFORD
# ─────────────────────────────────────────────────────────────────────────────
class BenfordAnalysis(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Analyse de conformité à la loi de Benford sur une période.
    Détecte les distributions de montants statistiquement anormales.
    """
    __tablename__ = "benford_analyses"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    periode_debut: Mapped[date] = mapped_column(Date, nullable=False)
    periode_fin: Mapped[date] = mapped_column(Date, nullable=False)

    nb_echantillons: Mapped[int] = mapped_column(Integer, nullable=False)

    # Distribution observée (chiffre 1-9 → proportion)
    distribution_observee: Mapped[dict[str, float]] = mapped_column(JSONB, nullable=False)
    distribution_attendue: Mapped[dict[str, float]] = mapped_column(JSONB, nullable=False)

    # Score de conformité (0-1)
    score_conformite: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    chi_square: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    conforme: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # Top anomalies
    anomalies: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "periode_debut", "periode_fin", name="uq_benford_periode"),
        Index("idx_benford_tenant_periode", "tenant_id", "periode_fin"),
    )

    def __repr__(self) -> str:
        return f"<BenfordAnalysis {self.periode_debut}→{self.periode_fin} score={self.score_conformite}>"
