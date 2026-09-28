"""Modèle PlanComptable — plan SYSCOHADA révisé, propre à chaque tenant."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import CompteType

if TYPE_CHECKING:
    from app.models.tenant import Tenant


class PlanComptable(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "plan_comptable"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Code SYSCOHADA : "401100", "521000", "701100"...
    compte: Mapped[str] = mapped_column(String(10), nullable=False)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)

    # Classe 1 à 9 (SYSCOHADA révisé)
    classe: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    type_compte: Mapped[CompteType] = mapped_column(nullable=False)

    collectif: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Lettrable = peut recevoir un lettrage (rapprochement bancaire / tiers)
    lettrable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # Auxiliaire = sous-compte tiers (401xxx, 411xxx)
    auxiliaire: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    actif: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    # Relations
    tenant: Mapped["Tenant"] = relationship(back_populates="plan_comptable")

    __table_args__ = (
        UniqueConstraint("tenant_id", "compte", name="uq_plan_comptable_tenant_compte"),
        CheckConstraint("classe BETWEEN 1 AND 9", name="plan_comptable_classe_valide"),
        Index("idx_pc_tenant_classe", "tenant_id", "classe"),
        Index("idx_pc_tenant_actif", "tenant_id", "actif"),
    )

    def __repr__(self) -> str:
        return f"<PlanComptable {self.compte} — {self.libelle}>"
