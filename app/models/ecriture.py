"""Modèles Ecriture + EcritureLigne — partie double SYSCOHADA avec hash-chain."""
from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Index, SmallInteger, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import EcritureSource, EcritureStatut

if TYPE_CHECKING:
    from app.models.ecriture import EcritureLigne
    from app.models.exercice import Exercice
    from app.models.journal import Journal
    from app.models.plan_comptable import PlanComptable


class Ecriture(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ecritures"

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
        index=True,
    )
    journal_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("journaux.id"),
        nullable=False,
        index=True,
    )

    numero_piece: Mapped[str] = mapped_column(String(50), nullable=False)   # VE-2025-0001
    date_ecriture: Mapped[date] = mapped_column(Date, nullable=False)
    date_saisie: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    libelle: Mapped[str] = mapped_column(Text, nullable=False)

    # Référence externe : ID transaction Mobile Money, numéro facture...
    reference_ext: Mapped[str | None] = mapped_column(String(100), nullable=True)

    source: Mapped[EcritureSource] = mapped_column(
        nullable=False, default=EcritureSource.MANUEL, server_default="manuel"
    )
    statut: Mapped[EcritureStatut] = mapped_column(
        nullable=False, default=EcritureStatut.BROUILLON, server_default="brouillon"
    )

    validee_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validee_par: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    # ⚠️ Chaînage cryptographique (traçabilité bancaire)
    hash_chain: Mapped[str] = mapped_column(String(64), nullable=False)
    hash_precedent: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    # Relations
    lignes: Mapped[list["EcritureLigne"]] = relationship(
        back_populates="ecriture",
        cascade="all, delete-orphan",
        order_by="EcritureLigne.ordre",
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "numero_piece", name="uq_ecriture_numero"),
        Index("idx_ecr_tenant_date", "tenant_id", "date_ecriture"),
        Index("idx_ecr_tenant_statut", "tenant_id", "statut"),
        Index("idx_ecr_journal_date", "journal_id", "date_ecriture"),
        Index("idx_ecr_reference", "tenant_id", "reference_ext"),
        Index("idx_ecr_hash", "tenant_id", "hash_chain"),
    )

    def __repr__(self) -> str:
        return f"<Ecriture {self.numero_piece} ({self.statut})>"

    # ------------------------------------------------------------------
    # Propriétés métier
    # ------------------------------------------------------------------
    @property
    def total_debit(self) -> int:
        return sum(l.debit_xof for l in self.lignes)

    @property
    def total_credit(self) -> int:
        return sum(l.credit_xof for l in self.lignes)

    @property
    def est_equilibree(self) -> bool:
        return self.total_debit == self.total_credit and self.total_debit > 0

    @property
    def est_modifiable(self) -> bool:
        return self.statut in (EcritureStatut.BROUILLON,)


class EcritureLigne(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ecriture_lignes"

    ecriture_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("ecritures.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    compte_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("plan_comptable.id"),
        nullable=False,
        index=True,
    )

    libelle: Mapped[str | None] = mapped_column(Text, nullable=True)

    debit_xof: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    credit_xof: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )

    # Lettrage (rapprochement bancaire / tiers)
    lettrage_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    lettrage_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    ordre: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, server_default="1"
    )

    # Relations
    ecriture: Mapped["Ecriture"] = relationship(back_populates="lignes")

    __table_args__ = (
        CheckConstraint("debit_xof >= 0", name="ligne_debit_positif"),
        CheckConstraint("credit_xof >= 0", name="ligne_credit_positif"),
        CheckConstraint(
            "NOT (debit_xof > 0 AND credit_xof > 0)",
            name="ligne_non_mixte",
        ),
        CheckConstraint(
            "debit_xof > 0 OR credit_xof > 0",
            name="ligne_non_nulle",
        ),
        Index("idx_lignes_compte", "tenant_id", "compte_id"),
        Index("idx_lignes_lettrage", "tenant_id", "lettrage_code"),
    )

    def __repr__(self) -> str:
        return f"<Ligne compte={self.compte_id} D={self.debit_xof} C={self.credit_xof}>"
