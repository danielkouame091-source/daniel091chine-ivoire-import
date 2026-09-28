"""Modèle Plan — catalogue SaaS (starter, pro, business, enterprise)."""
from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import SubPlan


class Plan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "plans"

    code: Mapped[SubPlan] = mapped_column(unique=True, nullable=False)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)

    prix_mensuel_xof: Mapped[int] = mapped_column(BigInteger, nullable=False)
    prix_annuel_xof: Mapped[int] = mapped_column(BigInteger, nullable=False)

    max_users: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    max_ecritures_mois: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1000, server_default="1000"
    )
    max_mm_transactions: Mapped[int] = mapped_column(
        Integer, nullable=False, default=500, server_default="500"
    )

    features: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    def __repr__(self) -> str:
        return f"<Plan {self.code}>"
