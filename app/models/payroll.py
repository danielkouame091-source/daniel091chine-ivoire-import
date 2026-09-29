"""Modèles de paie et de déclarations sociales (CNPS, ITS)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Employee(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Salarié d'un tenant — données nécessaires au calcul de la paie."""
    __tablename__ = "employees"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    matricule: Mapped[str] = mapped_column(String(30), nullable=False)
    nom_prenoms: Mapped[str] = mapped_column(Text, nullable=False)
    date_naissance: Mapped[date | None] = mapped_column(Date, nullable=True)
    numero_cnps: Mapped[str | None] = mapped_column(String(30), nullable=True)
    numero_cmu: Mapped[str | None] = mapped_column(String(30), nullable=True)
    numero_contribuable: Mapped[str | None] = mapped_column(String(30), nullable=True)

    poste: Mapped[str | None] = mapped_column(Text, nullable=True)
    date_embauche: Mapped[date] = mapped_column(Date, nullable=False)
    date_depart: Mapped[date | None] = mapped_column(Date, nullable=True)
    type_contrat: Mapped[str] = mapped_column(
        String(20), nullable=False, default="CDI", server_default="CDI"
    )  # CDI | CDD | Stage | Apprentissage

    # Situation familiale → parts fiscales (RICF)
    situation_familiale: Mapped[str] = mapped_column(
        String(20), nullable=False, default="celibataire", server_default="celibataire"
    )  # celibataire | marie | divorce | veuf
    nombre_enfants: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    parts_fiscales: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0, server_default="1.0"
    )  # 1 à 5 parts (RICF)

    # Rémunération
    salaire_base_mensuel: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sursalaire: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    primes_fixes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    avantages_nature: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    # Statut expatrié → taxe sur salaires patronale majorée
    est_expatrie: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Secteur pour AT/MP (2 à 5%)
    taux_at_mp: Mapped[float] = mapped_column(
        Float, nullable=False, default=3.0, server_default="3.0"
    )

    actif: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "matricule", name="uq_employee_matricule"),
        Index("idx_emp_tenant_actif", "tenant_id", "actif"),
    )

    def __repr__(self) -> str:
        return f"<Employee {self.matricule} — {self.nom_prenoms}>"


class Payslip(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Bulletin de paie mensuel d'un salarié."""
    __tablename__ = "payslips"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    periode: Mapped[str] = mapped_column(String(7), nullable=False)   # "2025-03"
    date_paie: Mapped[date] = mapped_column(Date, nullable=False)

    # ─── Éléments bruts ──────────────────────────────────────────────
    salaire_base: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sursalaire: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    primes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    heures_sup: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    avantages_nature: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    indemnites_non_imposables: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )

    salaire_brut: Mapped[int] = mapped_column(BigInteger, nullable=False)
    salaire_brut_imposable: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # ─── Cotisations salariales ──────────────────────────────────────
    cnps_salarial: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    cmu_salarial: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    # ─── ITS ─────────────────────────────────────────────────────────
    its_brut: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    ricf_reduction: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    its_net: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    # ─── Charges patronales ──────────────────────────────────────────
    cnps_patronal: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    prestations_familiales: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    accidents_travail: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    cmu_patronal: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    taxe_salaires_patronale: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    fdfp: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    contribution_nationale: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )

    # ─── Net à payer ─────────────────────────────────────────────────
    total_retenues: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    net_a_payer: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cout_employeur: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Détail du calcul ITS (traçabilité)
    detail_its: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    # Lien avec écriture comptable
    ecriture_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("ecritures.id"), nullable=True
    )

    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="brouillon", server_default="brouillon"
    )  # brouillon | valide | paye

    __table_args__ = (
        UniqueConstraint("tenant_id", "employee_id", "periode", name="uq_payslip_periode"),
        Index("idx_payslip_tenant_periode", "tenant_id", "periode"),
    )

    def __repr__(self) -> str:
        return f"<Payslip {self.periode} emp={self.employee_id} net={self.net_a_payer}>"


class CnpsDeclaration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Déclaration CNPS mensuelle ou trimestrielle."""
    __tablename__ = "cnps_declarations"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    periode_debut: Mapped[date] = mapped_column(Date, nullable=False)
    periode_fin: Mapped[date] = mapped_column(Date, nullable=False)
    type_periode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="mensuelle", server_default="mensuelle"
    )  # mensuelle | trimestrielle

    # Totaux
    masse_salariale_brute: Mapped[int] = mapped_column(BigInteger, nullable=False)
    masse_salariale_plafonnee: Mapped[int] = mapped_column(BigInteger, nullable=False)
    nb_salaries: Mapped[int] = mapped_column(Integer, nullable=False)

    # Cotisations
    cnps_patronal: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cnps_salarial: Mapped[int] = mapped_column(BigInteger, nullable=False)
    prestations_familiales: Mapped[int] = mapped_column(BigInteger, nullable=False)
    accidents_travail: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cmu_total: Mapped[int] = mapped_column(BigInteger, nullable=False)

    total_a_payer: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Détail par salarié
    detail_salaries: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)

    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="brouillon", server_default="brouillon"
    )  # brouillon | depose | paye
    date_echeance: Mapped[date] = mapped_column(Date, nullable=False)
    reference_paiement: Mapped[str | None] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        Index("idx_cnps_tenant_periode", "tenant_id", "periode_debut", "periode_fin"),
    )


class DgiDeclaration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Déclaration fiscale DGI (TVA, ITS, IS, etc.)."""
    __tablename__ = "dgi_declarations"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type_declaration: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # tva | its | is | patente | cn | fdfp
    periode: Mapped[str] = mapped_column(String(10), nullable=False)   # "2025-03", "2025-T1", "2025"
    date_echeance: Mapped[date] = mapped_column(Date, nullable=False)

    # Bases imposables
    base_imposable: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    taux: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Montants
    montant_du: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    credits: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    montant_net: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    # Détail (JSONB pour flexibilité)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")

    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="brouillon", server_default="brouillon"
    )
    reference_paiement: Mapped[str | None] = mapped_column(String(50), nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "type_declaration", "periode",
            name="uq_dgi_declaration_periode",
        ),
        Index("idx_dgi_tenant_type", "tenant_id", "type_declaration"),
    )


class FinancialStatement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Snapshot d'états financiers SYSCOHADA révisé."""
    __tablename__ = "financial_statements"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    exercice_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("exercices.id"),
        nullable=False,
    )

    type_etat: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # bilan | compte_resultat | tafire | notes

    # Données structurées
    donnees: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    # Totaux clés (pour recherches)
    total_actif: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_passif: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    resultat_net: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    chiffre_affaires: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    valeur_ajoutee: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="brouillon", server_default="brouillon"
    )  # brouillon | valide | depose

    __table_args__ = (
        UniqueConstraint("tenant_id", "exercice_id", "type_etat", name="uq_fs_exercice_type"),
    )
