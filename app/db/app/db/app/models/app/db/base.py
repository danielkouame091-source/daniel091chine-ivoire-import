"""
Base déclarative SQLAlchemy 2.0 + types custom PostgreSQL.
Tous les modèles héritent de `Base` défini ici.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator, UserDefinedType


# ---------------------------------------------------------------------------
# Convention de nommage (indispensable pour Alembic autogenerate)
# ---------------------------------------------------------------------------
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base déclarative commune à tous les modèles."""
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# ---------------------------------------------------------------------------
# Type CITEXT (case-insensitive text — extension PostgreSQL `citext`)
# ---------------------------------------------------------------------------
class CITEXT(UserDefinedType):
    """Type PostgreSQL CITEXT — comparaison case-insensitive."""
    cache_ok = True

    def get_col_spec(self, **kw) -> str:
        return "CITEXT"

    def bind_processor(self, dialect):
        return None

    def result_processor(self, dialect, coltype):
        return None


# ---------------------------------------------------------------------------
# Mixins réutilisables
# ---------------------------------------------------------------------------
class UUIDPrimaryKeyMixin:
    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
