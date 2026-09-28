"""
Seed E2E — prépare les données de test pour Playwright.
Idempotent : réexécutable sans casser les données existantes.
Sortie : JSON sur stdout avec les identifiants des fixtures.

Usage :
    python -m scripts.seed_e2e
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pyotp
from sqlalchemy import select

from app.core.crypto import encrypt
from app.core.security import hash_password
from app.models.enums import (
    CompteType,
    JournalType,
    SubPlan,
    SubStatut,
    TenantStatut,
    UserRole,
    UserStatut,
)
from app.models.journal import Journal
from app.models.plan import Plan
from app.models.plan_comptable import PlanComptable
from app.models.subscription import Subscription
from app.models.tenant import Tenant
from app.models.user import User
from app.db.session import AsyncSessionLocal

# ─────────────────────────────────────────────────────────────────────────────
# Constantes E2E — les tests s'attendent à ces valeurs exactes
# ─────────────────────────────────────────────────────────────────────────────
FOUNDER_EMAIL = "founder.e2e@mtech.ci"
FOUNDER_PASSWORD = "FounderE2E!2025"
FOUNDER_MFA_SECRET = "JBSWY3DPEHPK3PXP"  # base32 fixe pour les tests

TENANT_A_SLUG = "e2e-tenant-a"
TENANT_A_EMAIL = "admin.a@e2e.ci"
TENANT_A_PASSWORD = "AdminA!2025"

TENANT_B_SLUG = "e2e-tenant-b"
TENANT_B_EMAIL = "admin.b@e2e.ci"
TENANT_B_PASSWORD = "AdminB!2025"

TENANT_EXPIRED_SLUG = "e2e-tenant-expired"
TENANT_EXPIRED_EMAIL = "admin.expired@e2e.ci"
TENANT_EXPIRED_PASSWORD = "AdminExp!2025"

PLAN_COMPTABLE_E2E = [
    ("401100", "Fournisseurs", 4, CompteType.PASSIF),
    ("411100", "Clients", 4, CompteType.ACTIF),
    ("421000", "Personnel — rémunérations dues", 4, CompteType.PASSIF),
    ("441000", "État — impôts sur salaires", 4, CompteType.PASSIF),
    ("471800", "Compte d'attente", 4, CompteType.ACTIF),
    ("521000", "Banque", 5, CompteType.TRESORERIE),
    ("521100", "Banque Mobile Money", 5, CompteType.TRESORERIE),
    ("571000", "Caisse", 5, CompteType.TRESORERIE),
    ("601100", "Achats de marchandises", 6, CompteType.CHARGE),
    ("622800", "Fournitures de bureau", 6, CompteType.CHARGE),
    ("631800", "Frais bancaires", 6, CompteType.CHARGE),
    ("661000", "Rémunérations du personnel", 6, CompteType.CHARGE),
    ("701100", "Ventes de marchandises", 7, CompteType.PRODUIT),
]

JOURNAUX_E2E = [
    ("VE", "Journal des ventes", JournalType.VENTE, None),
    ("AC", "Journal des achats", JournalType.ACHAT, None),
    ("BQ", "Journal de banque", JournalType.BANQUE, "521000"),
    ("CA", "Journal de caisse", JournalType.CAISSE, "571000"),
    ("OD", "Opérations diverses", JournalType.OD, None),
    ("AN", "À-nouveaux", JournalType.AN, None),
    ("MM", "Mobile Money", JournalType.MOBILE_MONEY, "521100"),
]


async def _get_or_create_plan(db) -> Plan:
    plan = await db.scalar(select(Plan).where(Plan.code == SubPlan.STARTER))
    if plan is None:
        plan = Plan(
            code=SubPlan.STARTER,
            libelle="Starter",
            prix_mensuel_xof=15000,
            prix_annuel_xof=150000,
            max_users=3,
            max_ecritures_mois=1000,
            max_mm_transactions=500,
            features={},
        )
        db.add(plan)
        await db.flush()
    return plan


async def _get_or_create_tenant(db, slug: str, raison: str) -> Tenant:
    tenant = await db.scalar(select(Tenant).where(Tenant.slug == slug))
    if tenant is None:
        tenant = Tenant(
            slug=slug,
            raison_sociale=raison,
            pays="CI",
            devise="XOF",
            fuseau="Africa/Abidjan",
            statut=TenantStatut.ACTIF,
            regime_fiscal="RME",
        )
        db.add(tenant)
        await db.flush()
    return tenant


async def _get_or_create_user(
    db,
    tenant: Tenant | None,
    email: str,
    password: str,
    role: UserRole,
    is_founder: bool,
    mfa_secret: str | None = None,
) -> User:
    user = await db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(
            tenant_id=tenant.id if tenant else None,
            email=email,
            password_hash=hash_password(password),
            nom_complet=email.split("@")[0].replace(".", " ").title(),
            role=role,
            statut=UserStatut.ACTIF,
            is_founder=is_founder,
            mfa_enabled=mfa_secret is not None,
            mfa_secret_enc=encrypt(mfa_secret) if mfa_secret else None,
        )
        db.add(user)
        await db.flush()
    return user


async def _seed_tenant_data(db, tenant: Tenant, plan: Plan, active: bool = True) -> None:
    """Insère plan comptable + journaux + abonnement pour un tenant."""
    # Abonnement
    existing_sub = await db.scalar(
        select(Subscription)
        .where(Subscription.tenant_id == tenant.id)
        .order_by(Subscription.periode_fin.desc())
        .limit(1)
    )
    now = datetime.now(timezone.utc)
    if existing_sub is None:
        if active:
            sub = Subscription(
                tenant_id=tenant.id,
                plan_id=plan.id,
                statut=SubStatut.ACTIF,
                periode_debut=now - timedelta(days=10),
                periode_fin=now + timedelta(days=20),
                grace_jours=7,
                montant_xof=15000,
                devise="XOF",
                mode_paiement="wave",
            )
        else:
            sub = Subscription(
                tenant_id=tenant.id,
                plan_id=plan.id,
                statut=SubStatut.ACTIF,
                periode_debut=now - timedelta(days=40),
                periode_fin=now - timedelta(days=10),   # expirée
                grace_jours=7,
                montant_xof=15000,
                devise="XOF",
                mode_paiement="wave",
            )
        db.add(sub)

    # Plan comptable
    existing_codes = set(
        (
            await db.execute(
                select(PlanComptable.compte).where(PlanComptable.tenant_id == tenant.id)
            )
        ).scalars().all()
    )
    for code, libelle, classe, type_compte in PLAN_COMPTABLE_E2E:
        if code in existing_codes:
            continue
        db.add(
            PlanComptable(
                tenant_id=tenant.id,
                compte=code,
                libelle=libelle,
                classe=classe,
                type_compte=type_compte,
            )
        )

    # Journaux
    existing_journaux = set(
        (
            await db.execute(
                select(Journal.code).where(Journal.tenant_id == tenant.id)
            )
        ).scalars().all()
    )
    for code, libelle, jtype, contrepartie in JOURNAUX_E2E:
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

    # Exercice courant
    from app.models.exercice import Exercice
    from datetime import date
    existing_ex = await db.scalar(
        select(Exercice).where(
            Exercice.tenant_id == tenant.id,
            Exercice.date_debut <= date.today(),
            Exercice.date_fin >= date.today(),
        )
    )
    if existing_ex is None:
        db.add(
            Exercice(
                tenant_id=tenant.id,
                libelle=f"Exercice {date.today().year}",
                date_debut=date(date.today().year, 1, 1),
                date_fin=date(date.today().year, 12, 31),
                cloture=False,
            )
        )

    await db.flush()


async def seed() -> dict:
    async with AsyncSessionLocal() as db:
        plan = await _get_or_create_plan(db)

        # ─── Fondateur (avec MFA) ──────────────────────────────────────
        founder = await _get_or_create_user(
            db=db,
            tenant=None,
            email=FOUNDER_EMAIL,
            password=FOUNDER_PASSWORD,
            role=UserRole.SUPER_ADMIN,
            is_founder=True,
            mfa_secret=FOUNDER_MFA_SECRET,
        )

        # ─── Tenant A (actif) ──────────────────────────────────────────
        tenant_a = await _get_or_create_tenant(db, TENANT_A_SLUG, "E2E Tenant A SARL")
        await _seed_tenant_data(db, tenant_a, plan, active=True)
        user_a = await _get_or_create_user(
            db=db,
            tenant=tenant_a,
            email=TENANT_A_EMAIL,
            password=TENANT_A_PASSWORD,
            role=UserRole.ADMIN_TENANT,
            is_founder=False,
        )

        # ─── Tenant B (actif — isolation) ──────────────────────────────
        tenant_b = await _get_or_create_tenant(db, TENANT_B_SLUG, "E2E Tenant B SARL")
        await _seed_tenant_data(db, tenant_b, plan, active=True)
        user_b = await _get_or_create_user(
            db=db,
            tenant=tenant_b,
            email=TENANT_B_EMAIL,
            password=TENANT_B_PASSWORD,
            role=UserRole.ADMIN_TENANT,
            is_founder=False,
        )

        # ─── Tenant Expired (read-only) ────────────────────────────────
        tenant_exp = await _get_or_create_tenant(
            db, TENANT_EXPIRED_SLUG, "E2E Expired SARL"
        )
        await _seed_tenant_data(db, tenant_exp, plan, active=False)
        user_exp = await _get_or_create_user(
            db=db,
            tenant=tenant_exp,
            email=TENANT_EXPIRED_EMAIL,
            password=TENANT_EXPIRED_PASSWORD,
            role=UserRole.ADMIN_TENANT,
            is_founder=False,
        )

        await db.commit()

        return {
            "founder": {
                "email": FOUNDER_EMAIL,
                "password": FOUNDER_PASSWORD,
                "mfa_secret": FOUNDER_MFA_SECRET,
            },
            "tenant_a": {
                "slug": TENANT_A_SLUG,
                "tenant_id": str(tenant_a.id),
                "email": TENANT_A_EMAIL,
                "password": TENANT_A_PASSWORD,
            },
            "tenant_b": {
                "slug": TENANT_B_SLUG,
                "tenant_id": str(tenant_b.id),
                "email": TENANT_B_EMAIL,
                "password": TENANT_B_PASSWORD,
            },
            "tenant_expired": {
                "slug": TENANT_EXPIRED_SLUG,
                "tenant_id": str(tenant_exp.id),
                "email": TENANT_EXPIRED_EMAIL,
                "password": TENANT_EXPIRED_PASSWORD,
            },
        }


def main() -> None:
    try:
        data = asyncio.run(seed())
        print(json.dumps(data))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
