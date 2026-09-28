"""Modèle User — utilisateur rattaché à un tenant (sauf le fondateur unique)."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Index, SmallInteger, Text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import LargeBinary

from app.db.base import Base, CITEXT, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import UserRole, UserStatut

if TYPE_CHECKING:
    from app.models.session import Session
    from app.models.tenant import Tenant


class User(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "users"

    # Le fondateur a tenant_id = NULL (contrainte SQL l'impose)
    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    nom_complet: Mapped[str] = mapped_column(Text, nullable=False)
    telephone: Mapped[str | None] = mapped_column(Text, nullable=True)

    role: Mapped[UserRole] = mapped_column(
        nullable=False, default=UserRole.LECTEUR, server_default="LECTEUR"
    )
    statut: Mapped[UserStatut] = mapped_column(
        nullable=False, default=UserStatut.INVITE, server_default="invite"
    )

    is_founder: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # MFA
    mfa_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    mfa_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    mfa_backup_codes_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    # Sécurité connexion
    derniere_connexion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    derniere_ip: Mapped[str | None] = mapped_column(Text, nullable=True)  # INET cast côté DB
    tentatives_echec: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    verrouille_jusqu_a: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relations
    tenant: Mapped["Tenant | None"] = relationship(back_populates="users")
    sessions: Mapped[list["Session"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # ⚠️ Contrainte miroir de la CHECK SQL : fondateur seul, sans tenant
        CheckConstraint(
            "(is_founder = true AND tenant_id IS NULL AND role = 'SUPER_ADMIN') "
            "OR (is_founder = false AND tenant_id IS NOT NULL)",
            name="founder_must_be_alone",
        ),
        # Un seul fondateur dans toute la table
        Index(
            "uniq_founder",
            "is_founder",
            unique=True,
            postgresql_where=(mapped_column(Boolean) == True),  # noqa: E712
        ),
        Index("idx_users_tenant", "tenant_id", postgresql_where=(SoftDeleteMixin.deleted_at.is_(None))),
        Index("idx_users_email_active", "email", postgresql_where=(SoftDeleteMixin.deleted_at.is_(None))),
    )

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.role})>"
