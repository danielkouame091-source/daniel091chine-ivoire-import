"""
Crée LE fondateur unique (is_founder=True) — à n'exécuter qu'UNE FOIS.
Usage :
    python -m scripts.create_founder --email daniel@mtech.ci --password 'MotDePasse!2025'
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.enums import UserRole, UserStatut
from app.models.user import User


async def create_founder(email: str, password: str, nom: str = "Fondateur") -> int:
    async with AsyncSessionLocal() as db:
        # Vérifie qu'aucun fondateur n'existe déjà
        existing = (
            await db.execute(select(User).where(User.is_founder.is_(True)))
        ).scalar_one_or_none()
        if existing is not None:
            print(f"❌ Un fondateur existe déjà : {existing.email}", file=sys.stderr)
            return 1

        # Vérifie l'unicité de l'email
        by_email = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if by_email is not None:
            print(f"❌ Email déjà utilisé : {email}", file=sys.stderr)
            return 1

        user = User(
            tenant_id=None,
            email=email,
            password_hash=hash_password(password),
            nom_complet=nom,
            role=UserRole.SUPER_ADMIN,
            statut=UserStatut.ACTIF,
            is_founder=True,
            mfa_enabled=False,      # à activer via /auth/mfa/setup au 1er login
        )
        db.add(user)
        await db.commit()

        print(f"✅ Fondateur créé : {email}")
        print("⚠️  Activez le MFA via POST /api/v1/auth/mfa/setup dès la 1re connexion.")
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Crée le fondateur unique.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", help="Si absent, prompt sécurisé.")
    parser.add_argument("--nom", default="Fondateur")
    args = parser.parse_args()

    password = args.password or getpass.getpass("Mot de passe fondateur : ")
    if len(password) < 12:
        print("❌ Mot de passe trop court (min 12 caractères)", file=sys.stderr)
        sys.exit(1)

    sys.exit(asyncio.run(create_founder(args.email, password, args.nom)))


if __name__ == "__main__":
    main()
