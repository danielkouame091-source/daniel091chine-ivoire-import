"""Modèle Tenant — entreprise cliente (racine de l'isolation RLS)."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CITEXT, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import TenantStatut

if TYPE_CHECKING:
    from app.models.exercice import Exercice
    from app.models.journal import Journal
    from app.models.plan_comptable import PlanComptable
    from app.models.subscription import Subscription
    from app.models.user import User


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "tenants"

    slug: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    raison_sociale: Mapped[str] = mapped_column(Text, nullable=False)
    forme_juridique: Mapped[str | None] = mapped_column(Text, nullable=True)
    rccm: Mapped[str | None] = mapped_column(Text, nullable=True)
    compte_contribuable: Mapped[str | None] = mapped_column(Text, nullable=True)
    numero_cnps: Mapped[str | None] = mapped_column(Text, nullable=True)

    regime_fiscal: Mapped[str | None] = mapped_column(Text, nullable=True)
    centre_impots: Mapped[str | None] = mapped_column(Text, nullable=True)

    pays: Mapped[str] = mapped_column(String(2), nullable=False, default="CI", server_default="CI")
    devise: Mapped[str] = mapped_column(String(3), nullable=False, default="XOF", server_default="XOF")
    fuseau: Mapped[str] = mapped_column(
        Text, nullable=False, default="Africa/Abidjan", server_default="Africa/Abidjan"
    )

    adresse: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    telephone: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(CITEXT, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    statut: Mapped[TenantStatut] = mapped_column(
        nullable=False, default=TenantStatut.ACTIF, server_default="actif"
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    # Relations
    users: Mapped[list["User"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    subscriptions: Mapped[list["Subscription"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    exercices: Mapped[list["Exercice"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    plan_comptable: Mapped[list["PlanComptable"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    journaux: Mapped[list["Journal"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "regime_fiscal IN ('RME','RNI','RSI','TPU','ZONE_FRANCHE') OR regime_fiscal IS NULL",
            name="regime_fiscal_valide",
        ),
        Index("idx_tenants_statut", "statut"),
    )

    def __repr__(self) -> str:
        return f"<Tenant {self.slug} ({self.id})>"
