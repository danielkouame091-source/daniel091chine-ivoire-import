import uuid
from datetime import date, datetime
from sqlalchemy import String, BigInteger, Date, DateTime, ForeignKey, CheckConstraint, Index, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base

class Ecriture(Base):
    __tablename__ = "ecritures"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    numero_piece: Mapped[str] = mapped_column(String(50), nullable=False)
    date_ecriture: Mapped[date] = mapped_column(Date, nullable=False)
    journal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("journaux.id"))
    libelle: Mapped[str] = mapped_column(String(500))
    reference_ext: Mapped[str | None] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(20), default="manuel")
    statut: Mapped[str] = mapped_column(String(20), default="brouillon")
    hash_chain: Mapped[str] = mapped_column(String(64), nullable=False)
    hash_precedent: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lignes: Mapped[list["EcritureLigne"]] = relationship(back_populates="ecriture", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_ecr_tenant_date", "tenant_id", "date_ecriture"),
    )
