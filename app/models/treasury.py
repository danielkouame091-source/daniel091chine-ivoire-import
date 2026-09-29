"""Modèles SYSCOHADA — Comptes de trésorerie, Relevés bancaires, Rapprochement."""
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
# COMPTE DE TRÉSORERIE
# ─────────────────────────────────────────────────────────────────────────────
class TreasuryAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Compte de trésorerie (banque, caisse, Mobile Money).
    Chaque compte correspond à un compte SYSCOHADA (5xx).
    """
    __tablename__ = "treasury_accounts"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    code: Mapped[str] = mapped_column(String(20), nullable=False)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)
    type_compte: Mapped[str] = mapped_column(
        String(20), nullable=False, default="banque", server_default="banque"
    )  # banque | caisse | mobile_money | placement

    # Compte SYSCOHADA rattaché
    compte_comptable: Mapped[str] = mapped_column(String(10), nullable=False)

    # Identification externe
    banque: Mapped[str | None] = mapped_column(Text, nullable=True)
    numero_compte: Mapped[str | None] = mapped_column(String(50), nullable=True)
    iban: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bic: Mapped[str | None] = mapped_column(String(20), nullable=True)
    devise: Mapped[str] = mapped_column(String(3), nullable=False, default="XOF", server_default="XOF")

    # Solde courant (cache, mis à jour à chaque écriture impactant ce compte)
    solde_comptable: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    solde_dernier_releve: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    date_dernier_releve: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Paramètres
    compte_principal: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_treasury_account_code"),
        UniqueConstraint("tenant_id", "compte_comptable", name="uq_treasury_account_compte"),
        Index("idx_tre_acc_tenant_type", "tenant_id", "type_compte"),
        Index("idx_tre_acc_tenant_actif", "tenant_id", "actif"),
    )

    def __repr__(self) -> str:
        return f"<TreasuryAccount {self.code} — {self.libelle} ({self.solde_comptable})>"


# ─────────────────────────────────────────────────────────────────────────────
# RELEVÉ BANCAIRE (import)
# ─────────────────────────────────────────────────────────────────────────────
class BankStatement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Relevé bancaire importé (CSV, OFX, MT940)."""
    __tablename__ = "bank_statements"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    treasury_account_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("treasury_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Identification
    reference: Mapped[str] = mapped_column(String(50), nullable=False)
    date_debut: Mapped[date] = mapped_column(Date, nullable=False)
    date_fin: Mapped[date] = mapped_column(Date, nullable=False)

    # Fichier source
    format_source: Mapped[str] = mapped_column(
        String(10), nullable=False, default="csv", server_default="csv"
    )  # csv | ofx | mt940 | manuel
    fichier_nom: Mapped[str | None] = mapped_column(Text, nullable=True)
    fichier_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Soldes
    solde_ouverture: Mapped[int] = mapped_column(BigInteger, nullable=False)
    solde_cloture: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Statistiques
    nb_lignes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    nb_lignes_rapprochees: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Statut
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="importe", server_default="importe"
    )  # importe | en_cours | rapproche | cloture
    date_cloture: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    raw_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    imported_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "treasury_account_id", "reference", name="uq_bank_stmt_ref"),
        Index("idx_bank_stmt_tenant_periode", "tenant_id", "date_debut", "date_fin"),
    )

    def __repr__(self) -> str:
        return f"<BankStatement {self.reference} {self.date_debut}→{self.date_fin}>"


# ─────────────────────────────────────────────────────────────────────────────
# LIGNE DE RELEVÉ BANCAIRE
# ─────────────────────────────────────────────────────────────────────────────
class BankStatementLine(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Ligne de relevé bancaire (débit ou crédit)."""
    __tablename__ = "bank_statement_lines"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    statement_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("bank_statements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    treasury_account_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("treasury_accounts.id"),
        nullable=False,
        index=True,
    )

    # Données bancaires
    date_operation: Mapped[date] = mapped_column(Date, nullable=False)
    date_valeur: Mapped[date | None] = mapped_column(Date, nullable=True)

    libelle: Mapped[str] = mapped_column(Text, nullable=False)
    reference_banque: Mapped[str | None] = mapped_column(String(50), nullable=True)

    type_mouvement: Mapped[str] = mapped_column(String(10), nullable=False)   # debit | credit
    montant: Mapped[int] = mapped_column(BigInteger, nullable=False)          # toujours > 0

    # Catégorisation automatique
    categorie: Mapped[str | None] = mapped_column(String(30), nullable=True)
    code_banque: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Rapprochement
    statut_rapprochement: Mapped[str] = mapped_column(
        String(30), nullable=False, default="non_rapprochee", server_default="non_rapprochee"
    )
    ecriture_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("ecritures.id"), nullable=True
    )
    ecriture_ligne_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("ecriture_lignes.id"), nullable=True
    )
    score_matching: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    rapproche_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rapproche_par: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    raw_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("idx_bsl_stmt_date", "statement_id", "date_operation"),
        Index("idx_bsl_tenant_statut", "tenant_id", "statut_rapprochement"),
        Index("idx_bsl_tre_acc", "treasury_account_id"),
    )

    def __repr__(self) -> str:
        return f"<BankStatementLine {self.date_operation} {self.type_mouvement} {self.montant}>"


# ─────────────────────────────────────────────────────────────────────────────
# SESSION DE RAPPROCHEMENT
# ─────────────────────────────────────────────────────────────────────────────
class ReconciliationSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Session de rapprochement bancaire pour un compte sur une période.
    Contient l'état final (solde comptable vs bancaire) + les écarts.
    """
    __tablename__ = "reconciliation_sessions"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    treasury_account_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("treasury_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    statement_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("bank_statements.id"), nullable=True
    )

    reference: Mapped[str] = mapped_column(String(50), nullable=False)
    date_debut: Mapped[date] = mapped_column(Date, nullable=False)
    date_fin: Mapped[date] = mapped_column(Date, nullable=False)

    # Soldes
    solde_comptable: Mapped[int] = mapped_column(BigInteger, nullable=False)
    solde_bancaire: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Ajustements
    total_credits_non_comptabilises: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    total_debits_non_comptabilises: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    total_frais_bancaires: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    total_interets: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )

    # Résultat
    ecart: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    etat: Mapped[str] = mapped_column(
        String(20), nullable=False, default="en_cours", server_default="en_cours"
    )
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="en_cours", server_default="en_cours"
    )

    # Statistiques
    nb_lignes_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    nb_lignes_rapprochees: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    nb_ecarts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Détails des écarts
    ecarts_detail: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    # Écriture de régularisation générée
    ecriture_regularisation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("ecritures.id"), nullable=True
    )

    valide_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valide_par: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "reference", name="uq_recon_session_ref"),
        Index("idx_recon_tenant_periode", "tenant_id", "date_debut", "date_fin"),
        Index("idx_recon_tenant_statut", "tenant_id", "statut"),
    )

    def __repr__(self) -> str:
        return f"<ReconciliationSession {self.reference} ecart={self.ecart}>"


# ─────────────────────────────────────────────────────────────────────────────
# PRÉVISION DE TRÉSORERIE 13 SEMAINES
# ─────────────────────────────────────────────────────────────────────────────
class CashPositionSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Snapshot quotidien de la position de trésorerie consolidée.
    Utilisé pour le tableau de bord 13 semaines.
    """
    __tablename__ = "cash_position_snapshots"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    date_snapshot: Mapped[date] = mapped_column(Date, nullable=False)
    solde_total: Mapped[int] = mapped_column(BigInteger, nullable=False)
    solde_banques: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    solde_caisses: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    solde_mobile_money: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    solde_placements: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    # Détail par compte
    detail_comptes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    # Variations
    variation_j1: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    variation_s1: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    variation_m1: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "date_snapshot", name="uq_cash_snapshot_date"),
        Index("idx_cash_snap_tenant_date", "tenant_id", "date_snapshot"),
    )


class CashForecastWeek(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Prévision de trésorerie hebdomadaire (13 semaines glissantes).
    Chaque ligne = une semaine future avec entrées/sorties prévues.
    """
    __tablename__ = "cash_forecast_weeks"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    semaine_iso: Mapped[str] = mapped_column(String(10), nullable=False)   # "2025-W12"
    date_debut: Mapped[date] = mapped_column(Date, nullable=False)
    date_fin: Mapped[date] = mapped_column(Date, nullable=False)

    solde_ouverture: Mapped[int] = mapped_column(BigInteger, nullable=False)
    entrees_prevues: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    sorties_prevues: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    solde_cloture_prevu: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Détails par catégorie
    encaissements_clients: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    paiements_fournisseurs: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    salaires: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    impots_taxes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    autres_entrees: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    autres_sorties: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    # Fiabilité
    fiabilite: Mapped[str] = mapped_column(
        String(20), nullable=False, default="moyenne", server_default="moyenne"
    )  # faible | moyenne | elevee

    # Alerte
    alerte_negative: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    detail_previsions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "semaine_iso", name="uq_cash_forecast_week"),
        Index("idx_cash_fc_tenant_date", "tenant_id", "date_debut"),
    )
