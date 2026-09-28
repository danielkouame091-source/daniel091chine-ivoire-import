"""
Crée un tenant + son admin (usage debug / onboarding manuel).
Usage :
    python -m scripts.create_tenant \
        --slug demo-ci --raison-sociale "Démo CI SARL" \
        --admin-email admin@demo.ci --admin-password 'MotDePasse!2025'
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.enums import TenantStatut, UserRole, UserStatut
from app.models.tenant import Tenant
from app.models.user import User


async def create_tenant(
    slug: str,
    raison_sociale: str,
    admin_email: str,
    admin_password: str,
    admin_nom: str,
    regime_fiscal: str | None,
) -> int:
    async with AsyncSessionLocal() as db:
        # Tenant
        if (await db.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none():
            print(f"❌ Slug déjà utilisé : {slug}", file=sys.stderr)
            return 1

        tenant = Tenant(
            slug=slug,
            raison_sociale=raison_sociale,
            pays="CI",
            devise="XOF",
            fuseau="Africa/Abidjan",
            statut=TenantStatut.ACTIF,
            regime_fiscal=regime_fiscal,
        )
        db.add(tenant)
        await db.flush()

        # Admin tenant
        if (await db.execute(select(User).where(User.email == admin_email))).scalar_one_or_none():
            print(f"❌ Email déjà utilisé : {admin_email}", file=sys.stderr)
            return 1

        admin = User(
            tenant_id=tenant.id,
            email=admin_email,
            password_hash=hash_password(admin_password),
            nom_complet=admin_nom,
            role=UserRole.ADMIN_TENANT,
            statut=UserStatut.ACTIF,
            is_founder=False,
        )
        db.add(admin)
        await db.commit()

        print(f"✅ Tenant créé : {slug} ({tenant.id})")
        print(f"✅ Admin tenant  : {admin_email}")
        print("→ Pensez à créer un abonnement via POST /api/v1/billing/subscribe")
        print("→ Pensez à importer le plan comptable via /api/v1/plan-comptable/import")
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Crée un tenant + admin.")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--raison-sociale", required=True)
    parser.add_argument("--admin-email", required=True)
    parser.add_argument("--admin-password")
    parser.add_argument("--admin-nom", default="Admin")
    parser.add_argument(
        "--regime-fiscal",
        choices=["RME", "RNI", "RSI", "TPU", "ZONE_FRANCHE"],
        default=None,
    )
    args = parser.parse_args()

    password = args.admin_password or getpass.getpass("Mot de passe admin : ")
    if len(password) < 12:
        print("❌ Mot de passe trop court (min 12 caractères)", file=sys.stderr)
        sys.exit(1)

    sys.exit(asyncio.run(create_tenant(
        slug=args.slug,
        raison_sociale=args.raison_sociale,
        admin_email=args.admin_email,
        admin_password=password,
        admin_nom=args.admin_nom,
        regime_fiscal=args.regime_fiscal,
    )))


if __name__ == "__main__":
    main()
