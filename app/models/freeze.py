"""Modèles du protocole de gel en cascade (rigueur bancaire)."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index, SmallInteger, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import FreezeCible, FreezeStatut


class FreezeEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Événement racine de gel — déclencheur unique, traçable, auditable."""
    __tablename__ = "freeze_events"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    cible_type: Mapped[FreezeCible] = mapped_column(nullable=False)
    cible_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)

    motif: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    declencheur_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    declencheur_ip: Mapped[str | None] = mapped_column(Text, nullable=True)

    cascade_profondeur: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    statut: Mapped[FreezeStatut] = mapped_column(
        nullable=False, default=FreezeStatut.ACTIF, server_default="actif"
    )

    leve_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    leve_par: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    # Relations
    targets: Mapped[list["FreezeTarget"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_freeze_tenant_actif", "tenant_id"),
        Index("idx_freeze_cible", "cible_type", "cible_id"),
    )

    def __repr__(self) -> str:
        return f"<FreezeEvent {self.cible_type}:{self.cible_id} ({self.statut})>"


class FreezeTarget(UUIDPrimaryKeyMixin, Base):
    """Ressource effectivement atteinte par la cascade (matérialisation)."""
    __tablename__ = "freeze_targets"

    freeze_event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("freeze_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    cible_type: Mapped[FreezeCible] = mapped_column(nullable=False)
    cible_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)

    # 0 = racine, 1 = enfant direct, etc.
    niveau_profondeur: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    raison: Mapped[str] = mapped_column(Text, nullable=False)   # "cascade_user", "cascade_ecriture"...

    statut: Mapped[FreezeStatut] = mapped_column(
        nullable=False, default=FreezeStatut.ACTIF, server_default="actif"
    )
    gele_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    leve_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relations
    event: Mapped["FreezeEvent"] = relationship(back_populates="targets")

    __table_args__ = (
        UniqueConstraint(
            "freeze_event_id", "cible_type", "cible_id",
            name="uq_freeze_target_event_cible",
        ),
        Index("idx_ft_tenant", "tenant_id", "statut"),
        Index("idx_ft_cible", "cible_type", "cible_id"),
    )

    def __repr__(self) -> str:
        return f"<FreezeTarget {self.cible_type}:{self.cible_id} d={self.niveau_profondeur}>"


class FreezeCascadeRule(UUIDPrimaryKeyMixin, Base):
    """Règles déclaratives du graphe de propagation (modifiable en DB)."""
    __tablename__ = "freeze_cascade_rules"

    source_type: Mapped[FreezeCible] = mapped_column(nullable=False)
    cible_type: Mapped[FreezeCible] = mapped_column(nullable=False)

    propagation: Mapped[str] = mapped_column(
        Text, nullable=False, default="immediate", server_default="immediate"
    )  # immediate | differee
    blocage_ecriture: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "source_type", "cible_type",
            name="uq_freeze_rule_source_cible",
        ),
    )

    def __repr__(self) -> str:
        return f"<FreezeCascadeRule {self.source_type} → {self.cible_type}>"


class TenantFreezeState(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Cache chaud — consulté à CHAQUE requête pour éviter les JOIN coûteux."""
    __tablename__ = "tenant_freeze_state"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )

    gele: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    freeze_event_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("freeze_events.id"), nullable=True
    )
    motif: Mapped[str | None] = mapped_column(Text, nullable=True)
    gele_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<TenantFreezeState tenant={self.tenant_id} gele={self.gele}>"
