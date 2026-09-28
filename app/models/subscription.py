"""Modèles Subscription + SubscriptionPayment — pilotage SaaS et bascule read-only."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey, Index, SmallInteger, String, Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import MMProvider, SubStatut

if TYPE_CHECKING:
    from app.models.plan import Plan
    from app.models.tenant import Tenant


class Subscription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "subscriptions"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("plans.id"),
        nullable=False,
    )

    statut: Mapped[SubStatut] = mapped_column(
        nullable=False, default=SubStatut.TRIAL, server_default="trial"
    )

    periode_debut: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # 🔑 Clé de la bascule en lecture seule — vérifiée à chaque requête
    periode_fin: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    grace_jours: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=7, server_default="7"
    )

    montant_xof: Mapped[int] = mapped_column(BigInteger, nullable=False)
    devise: Mapped[str] = mapped_column(String(3), nullable=False, default="XOF", server_default="XOF")

    mode_paiement: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_paiement: Mapped[str | None] = mapped_column(Text, nullable=True)
    auto_renouvellement: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    # Relations
    tenant: Mapped["Tenant"] = relationship(back_populates="subscriptions")
    plan: Mapped["Plan"] = relationship()
    payments: Mapped[list["SubscriptionPayment"]] = relationship(
        back_populates="subscription", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index(
            "idx_sub_tenant_actif",
            "tenant_id",
            "periode_fin",
            postgresql_where=(statut.in_([SubStatut.TRIAL, SubStatut.ACTIF, SubStatut.IMPAYE])),
        ),
        Index(
            "idx_sub_expiration",
            "periode_fin",
            postgresql_where=(statut.in_([SubStatut.TRIAL, SubStatut.ACTIF])),
        ),
    )

    def __repr__(self) -> str:
        return f"<Subscription tenant={self.tenant_id} statut={self.statut} fin={self.periode_fin}>"

    # ------------------------------------------------------------------
    # Propriétés métier — utilisées par le middleware read-only
    # ------------------------------------------------------------------
    @property
    def est_expiree(self) -> bool:
        return self.periode_fin < datetime.now(self.periode_fin.tzinfo)

    @property
    def est_en_grace(self) -> bool:
        from datetime import timedelta
        return (
            self.est_expiree
            and self.periode_fin + timedelta(days=self.grace_jours) > datetime.now(self.periode_fin.tzinfo)
        )

    @property
    def force_read_only(self) -> bool:
        """True si l'abonnement impose le mode lecture seule."""
        return self.statut in (SubStatut.EXPIRE, SubStatut.SUSPENDU, SubStatut.RESILIE) or self.est_expiree


class SubscriptionPayment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "subscription_payments"

    subscription_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    montant_xof: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mode_paiement: Mapped[str] = mapped_column(Text, nullable=False)
    reference_externe: Mapped[str | None] = mapped_column(Text, nullable=True)

    provider: Mapped[MMProvider | None] = mapped_column(nullable=True)

    statut: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="en_attente",
        server_default="en_attente",
    )  # en_attente | confirme | echoue | rembourse

    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    confirme_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relations
    subscription: Mapped["Subscription"] = relationship(back_populates="payments")

    __table_args__ = (
        Index("idx_subpay_tenant", "tenant_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<SubscriptionPayment sub={self.subscription_id} {self.statut}>"
