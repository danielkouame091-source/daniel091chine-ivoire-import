"""DTO Écriture comptable — validation SYSCOHADA partie double."""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import EcritureSource, EcritureStatut
from app.schemas.common import MontantXOF


class LigneIn(BaseModel):
    """Une ligne d'écriture — soit débit, soit crédit, jamais les deux."""
    compte: str = Field(min_length=2, max_length=10, pattern=r"^\d{2,10}$")
    libelle: str | None = Field(default=None, max_length=200)
    debit: MontantXOF = 0
    credit: MontantXOF = 0

    @model_validator(mode="after")
    def ligne_coherente(self):
        if self.debit > 0 and self.credit > 0:
            raise ValueError(
                f"Ligne compte {self.compte} : débit ET crédit simultanés interdits"
            )
        if self.debit == 0 and self.credit == 0:
            raise ValueError(f"Ligne compte {self.compte} : montant nul interdit")
        return self

    @property
    def sens(self) -> str:
        return "debit" if self.debit > 0 else "credit"

    @property
    def montant(self) -> int:
        return self.debit if self.debit > 0 else self.credit


class EcritureCreate(BaseModel):
    """Payload de création d'écriture — validation SYSCOHADA complète."""
    numero_piece: str | None = Field(
        default=None,
        max_length=50,
        description="Si absent, généré automatiquement (ex: VE-2025-0001)",
    )
    date_ecriture: date
    code_journal: str = Field(min_length=2, max_length=5, pattern=r"^[A-Z]{2,5}$")
    libelle: str = Field(min_length=2, max_length=500)
    reference_ext: str | None = Field(default=None, max_length=100)
    source: EcritureSource = EcritureSource.MANUEL
    lignes: list[LigneIn] = Field(min_length=2)

    @model_validator(mode="after")
    def equilibre_partie_double(self):
        total_debit = sum(l.debit for l in self.lignes)
        total_credit = sum(l.credit for l in self.lignes)
        if total_debit != total_credit:
            raise ValueError(
                f"Écriture déséquilibrée SYSCOHADA : "
                f"débit={total_debit} XOF ≠ crédit={total_credit} XOF "
                f"(écart={total_debit - total_credit})"
            )
        if total_debit == 0:
            raise ValueError("Écriture vide : total débit = 0")
        return self

    @field_validator("lignes")
    @classmethod
    def lignes_uniques_ordre(cls, v: list[LigneIn]) -> list[LigneIn]:
        if len(v) < 2:
            raise ValueError("Une écriture SYSCOHADA nécessite au moins 2 lignes")
        return v


class EcritureUpdate(BaseModel):
    """Mise à jour d'une écriture BROUILLON uniquement."""
    libelle: str | None = Field(default=None, max_length=500)
    reference_ext: str | None = None
    lignes: list[LigneIn] | None = None

    @model_validator(mode="after")
    def equilibre_si_lignes(self):
        if self.lignes is not None:
            if len(self.lignes) < 2:
                raise ValueError("Une écriture nécessite au moins 2 lignes")
            td = sum(l.debit for l in self.lignes)
            tc = sum(l.credit for l in self.lignes)
            if td != tc:
                raise ValueError(f"Écriture déséquilibrée : débit={td} crédit={tc}")
        return self


class LigneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    compte_id: UUID
    libelle: str | None
    debit_xof: int
    credit_xof: int
    lettrage_code: str | None
    ordre: int


class EcritureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    exercice_id: UUID
    journal_id: UUID
    numero_piece: str
    date_ecriture: date
    date_saisie: datetime
    libelle: str
    reference_ext: str | None
    source: EcritureSource
    statut: EcritureStatut
    validee_at: datetime | None
    validee_par: UUID | None
    hash_chain: str
    hash_precedent: str | None
    created_by: UUID | None
    created_at: datetime
    lignes: list[LigneOut] = Field(default_factory=list)


class EcritureBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    numero_piece: str
    date_ecriture: date
    libelle: str
    statut: EcritureStatut


class EcritureFilter(BaseModel):
    """Filtres de recherche pour la liste des écritures."""
    date_debut: date | None = None
    date_fin: date | None = None
    journal_code: str | None = Field(default=None, pattern=r"^[A-Z]{2,5}$")
    statut: EcritureStatut | None = None
    source: EcritureSource | None = None
    compte: str | None = Field(default=None, pattern=r"^\d{2,10}$")
    numero_piece: str | None = None
