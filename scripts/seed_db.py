"""
Charge le plan comptable SYSCOHADA révisé + les journaux standards dans un tenant.
Source : sql/seed/plan_comptable_syscohada.csv (fourni séparément).
Usage :
    python -m scripts.seed_db --tenant-slug demo-ci
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.enums import JournalType
from app.models.journal import Journal
from app.models.plan_comptable import PlanComptable
from app.models.tenant import Tenant

CSV_PATH = Path(__file__).resolve().parent.parent / "sql" / "seed" / "plan_comptable_syscohada.csv"

# Journaux SYSCOHADA standards pour tout nouveau tenant
JOURNAUX_STANDARD = [
    ("VE", "Journal des ventes", JournalType.VENTE, None),
    ("AC", "Journal des achats", JournalType.ACHAT, None),
    ("BQ", "Journal de banque", JournalType.BANQUE, "521000"),
    ("CA", "Journal de caisse", JournalType.CAISSE, "571000"),
    ("OD", "Opérations diverses", JournalType.OD, None),
    ("AN", "À-nouveaux", JournalType.AN, None),
    ("MM", "Mobile Money", JournalType.MOBILE_MONEY, "521100"),
    ("PA", "Paie", JournalType.PAIE, "422000"),
    ("IM", "Impôts et taxes", JournalType.IMPOT, "441000"),
]


async def seed(tenant_slug: str) -> int:
    async with AsyncSessionLocal() as db:
        tenant = (
            await db.execute(select(Tenant).where(Tenant.slug == tenant_slug))
        ).scalar_one_or_none()
        if tenant is None:
            print(f"❌ Tenant introuvable : {tenant_slug}", file=sys.stderr)
            return 1

        # 1. Journaux standards
        existing_journaux = set(
            (
                await db.execute(
                    select(Journal.code).where(Journal.tenant_id == tenant.id)
                )
            ).scalars().all()
        )
        added_j = 0
        for code, libelle, jtype, contrepartie in JOURNAUX_STANDARD:
            if code in existing_journaux:
                continue
            db.add(
                Journal(
                    tenant_id=tenant.id,
                    code=code,
                    libelle=libelle,
                    type_journal=jtype,
                    compte_contrepartie=contrepartie,
                )
            )
            added_j += 1
        await db.flush()
        print(f"✅ {added_j} journaux ajoutés")

        # 2. Plan comptable
        if not CSV_PATH.exists():
            print(f"⚠️  CSV absent : {CSV_PATH}", file=sys.stderr)
            print("   → Le plan comptable ne sera pas chargé.")
            await db.commit()
            return 0

        existing_comptes = set(
            (
                await db.execute(
                    select(PlanComptable.compte).where(PlanComptable.tenant_id == tenant.id)
                )
            ).scalars().all()
        )

        added_c, skipped_c, errors_c = 0, 0, 0
        with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                compte = (row.get("compte") or "").strip()
                libelle = (row.get("libelle") or "").strip()
                type_compte = (row.get("type_compte") or "").strip().lower()
                if not compte or not libelle or not type_compte:
                    errors_c += 1
                    continue
                if compte in existing_comptes:
                    skipped_c += 1
                    continue
                try:
                    classe = int(compte[0])
                except (ValueError, IndexError):
                    errors_c += 1
                    continue
                if classe < 1 or classe > 9:
                    errors_c += 1
                    continue
                db.add(
                    PlanComptable(
                        tenant_id=tenant.id,
                        compte=compte,
                        libelle=libelle,
                        classe=classe,
                        type_compte=type_compte,
                    )
                )
                existing_comptes.add(compte)
                added_c += 1

        await db.commit()
        print(f"✅ Plan comptable : {added_c} créés, {skipped_c} ignorés, {errors_c} erreurs")
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed plan comptable + journaux.")
    parser.add_argument("--tenant-slug", required=True)
    args = parser.parse_args()
    sys.exit(asyncio.run(seed(args.tenant_slug)))


if __name__ == "__main__":
    main()
