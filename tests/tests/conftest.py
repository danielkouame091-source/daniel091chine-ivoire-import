"""
Fixtures pytest partagées.

⚠️ Ce conftest suppose une base PostgreSQL de test dédiée.
   Variable d'env requise : TEST_DATABASE_URL
   Ex : postgresql+asyncpg://mtech:pass@localhost:5432/mtech_test

   Créer la base une fois :
     createdb -U mtech mtech_test
     psql mtech_test -c "CREATE EXTENSION IF NOT EXISTS citext;"
     psql mtech_test -c "CREATE EXTENSION IF NOT EXISTS pgcrypto;"
     psql mtech_test -c "CREATE EXTENSION IF NOT EXISTS btree_gin;"
"""
from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Force l'env de test AVANT d'importer l'app
os.environ.setdefault("ENV", "test")

from app.core.config import settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.models.enums import (  # noqa: E402
    CompteType,
    JournalType,
    SubPlan,
    SubStatut,
    TenantStatut,
    UserRole,
    UserStatut,
)
from app.models.journal import Journal  # noqa: E402
from app.models.plan import Plan  # noqa: E402
from app.models.plan_comptable import PlanComptable  # noqa: E402
from app.models.subscription import Subscription  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.user import User  # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
# Event loop
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ─────────────────────────────────────────────────────────────────────────────
# Engine de test (session-scoped)
# ─────────────────────────────────────────────────────────────────────────────
TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", settings.DATABASE_URL)
TEST_DB_URL = TEST_DB_URL.replace("+asyncpg", "+asyncpg")  # sanity


@pytest_asyncio.fixture(scope="session")
async def test_engine() -> AsyncGenerator[AsyncEngine, None]:
    engine = create_async_engine(TEST_DB_URL, pool_pre_ping=True, echo=False)
    # Créer le schéma (une fois)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gin"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ─────────────────────────────────────────────────────────────────────────────
# Session DB isolée par test (rollback à la fin)
# ─────────────────────────────────────────────────────────────────────────────
@pytest_asyncio.fixture
async def db_session(test_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """
    Chaque test s'exécute dans une transaction qui est ROLLBACK à la fin.
    Isolation parfaite entre tests, pas de nettoyage manuel.
    """
    connection = await test_engine.connect()
    trans = await connection.begin()

    factory = async_sessionmaker(
        bind=connection, class_=AsyncSession, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    session = factory()

    try:
        yield session
    finally:
        await session.close()
        await trans.rollback()
        await connection.close()


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures métier
# ─────────────────────────────────────────────────────────────────────────────
@pytest_asyncio.fixture
async def tenant(db_session: AsyncSession) -> Tenant:
    t = Tenant(
        slug=f"test-{uuid4().hex[:8]}",
        raison_sociale="Test SARL",
        pays="CI",
        devise="XOF",
        statut=TenantStatut.ACTIF,
        regime_fiscal="RME",
    )
    db_session.add(t)
    await db_session.flush()
    return t


@pytest_asyncio.fixture
async def tenant_b(db_session: AsyncSession) -> Tenant:
    """Second tenant pour les tests d'isolation cross-tenant (RLS)."""
    t = Tenant(
        slug=f"test-b-{uuid4().hex[:8]}",
        raison_sociale="Test B SARL",
        pays="CI",
        devise="XOF",
        statut=TenantStatut.ACTIF,
        regime_fiscal="RME",
    )
    db_session.add(t)
    await db_session.flush()
    return t


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession, tenant: Tenant) -> User:
    u = User(
        tenant_id=tenant.id,
        email=f"admin-{uuid4().hex[:6]}@test.ci",
        password_hash=hash_password("MotDePasse!2025"),
        nom_complet="Admin Test",
        role=UserRole.ADMIN_TENANT,
        statut=UserStatut.ACTIF,
        is_founder=False,
    )
    db_session.add(u)
    await db_session.flush()
    return u


@pytest_asyncio.fixture
async def admin_user_b(db_session: AsyncSession, tenant_b: Tenant) -> User:
    u = User(
        tenant_id=tenant_b.id,
        email=f"adminb-{uuid4().hex[:6]}@test.ci",
        password_hash=hash_password("MotDePasse!2025"),
        nom_complet="Admin B",
        role=UserRole.ADMIN_TENANT,
        statut=UserStatut.ACTIF,
        is_founder=False,
    )
    db_session.add(u)
    await db_session.flush()
    return u


@pytest_asyncio.fixture
async def founder_user(db_session: AsyncSession) -> User:
    u = User(
        tenant_id=None,
        email=f"founder-{uuid4().hex[:6]}@mtech.ci",
        password_hash=hash_password("MotDePasse!2025"),
        nom_complet="Fondateur",
        role=UserRole.SUPER_ADMIN,
        statut=UserStatut.ACTIF,
        is_founder=True,
        mfa_enabled=True,       # Requis pour cockpit
    )
    db_session.add(u)
    await db_session.flush()
    return u


@pytest_asyncio.fixture
async def plan_starter(db_session: AsyncSession) -> Plan:
    p = Plan(
        code=SubPlan.STARTER,
        libelle="Starter",
        prix_mensuel_xof=15000,
        prix_annuel_xof=150000,
        max_users=3,
        max_ecritures_mois=1000,
        max_mm_transactions=500,
        features={},
    )
    db_session.add(p)
    await db_session.flush()
    return p


@pytest_asyncio.fixture
async def active_subscription(
    db_session: AsyncSession, tenant: Tenant, plan_starter: Plan
) -> Subscription:
    now = datetime.now(timezone.utc)
    s = Subscription(
        tenant_id=tenant.id,
        plan_id=plan_starter.id,
        statut=SubStatut.ACTIF,
        periode_debut=now - timedelta(days=5),
        periode_fin=now + timedelta(days=25),
        grace_jours=7,
        montant_xof=15000,
        devise="XOF",
        mode_paiement="wave",
    )
    db_session.add(s)
    await db_session.flush()
    return s


@pytest_asyncio.fixture
async def expired_subscription(
    db_session: AsyncSession, tenant: Tenant, plan_starter: Plan
) -> Subscription:
    now = datetime.now(timezone.utc)
    s = Subscription(
        tenant_id=tenant.id,
        plan_id=plan_starter.id,
        statut=SubStatut.ACTIF,   # statut dit actif, mais période expirée
        periode_debut=now - timedelta(days=40),
        periode_fin=now - timedelta(days=10),
        grace_jours=7,
        montant_xof=15000,
        devise="XOF",
        mode_paiement="wave",
    )
    db_session.add(s)
    await db_session.flush()
    return s


@pytest_asyncio.fixture
async def exercice(db_session: AsyncSession, tenant: Tenant):
    from app.models.exercice import Exercice
    e = Exercice(
        tenant_id=tenant.id,
        libelle="Exercice 2025",
        date_debut=date(2025, 1, 1),
        date_fin=date(2025, 12, 31),
        cloture=False,
    )
    db_session.add(e)
    await db_session.flush()
    return e


@pytest_asyncio.fixture
async def plan_comptable_ci(db_session: AsyncSession, tenant: Tenant):
    """
    Plan comptable minimal SYSCOHADA pour les tests.
    Retourne un dict { code: PlanComptable }.
    """
    comptes = [
        ("401100", "Fournisseurs", 4, CompteType.PASSIF),
        ("411100", "Clients", 4, CompteType.ACTIF),
        ("521000", "Banque", 5, CompteType.TRESORERIE),
        ("521100", "Banque Mobile Money", 5, CompteType.TRESORERIE),
        ("571000", "Caisse", 5, CompteType.TRESORERIE),
        ("601100", "Achats de marchandises", 6, CompteType.CHARGE),
        ("631800", "Frais bancaires", 6, CompteType.CHARGE),
        ("701100", "Ventes de marchandises", 7, CompteType.PRODUIT),
        ("471800", "Compte d'attente", 4, CompteType.ACTIF),
    ]
    created: dict[str, PlanComptable] = {}
    for code, libelle, classe, type_compte in comptes:
        c = PlanComptable(
            tenant_id=tenant.id,
            compte=code,
            libelle=libelle,
            classe=classe,
            type_compte=type_compte,
        )
        db_session.add(c)
        created[code] = c
    await db_session.flush()
    return created


@pytest_asyncio.fixture
async def journal_ve(db_session: AsyncSession, tenant: Tenant):
    j = Journal(
        tenant_id=tenant.id,
        code="VE",
        libelle="Journal des ventes",
        type_journal=JournalType.VENTE,
    )
    db_session.add(j)
    await db_session.flush()
    return j


@pytest_asyncio.fixture
async def journal_mm(db_session: AsyncSession, tenant: Tenant):
    j = Journal(
        tenant_id=tenant.id,
        code="MM",
        libelle="Mobile Money",
        type_journal=JournalType.MOBILE_MONEY,
        compte_contrepartie="521100",
    )
    db_session.add(j)
    await db_session.flush()
    return j


# ─────────────────────────────────────────────────────────────────────────────
# Client HTTP (via ASGITransport — pas de serveur réel)
# ─────────────────────────────────────────────────────────────────────────────
@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    Client HTTP FastAPI pointant sur l'app, partageant la session DB du test.
    Le middleware TenancyMiddleware sera bypassé pour simplifier — on injecte
    directement `request.state` via une surcharge de get_db.
    """
    from app.main import app
    from app.db import deps as db_deps

    # Override : on utilise la même session que le test
    async def _override_get_db():
        yield db_session

    async def _override_get_tenant_db(request):
        # Pose les variables RLS à partir de request.state (posé manuellement dans les tests)
        tenant_id = getattr(request.state, "tenant_id", None)
        read_only = getattr(request.state, "read_only", False)
        frozen = getattr(request.state, "frozen", False)
        await db_session.execute(
            text(
                "SELECT "
                "  set_config('app.tenant_id', :tid, true), "
                "  set_config('app.read_only', :ro, true), "
                "  set_config('app.frozen',    :fz, true)"
            ),
            {
                "tid": str(tenant_id) if tenant_id else "",
                "ro": "true" if read_only else "false",
                "fz": "true" if frozen else "false",
            },
        )
        yield db_session

    app.dependency_overrides[db_deps.get_db] = _override_get_db
    app.dependency_overrides[db_deps.get_tenant_db] = _override_get_tenant_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers JWT
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def make_token():
    from app.core.security import create_access_token

    def _make(user: User) -> str:
        return create_access_token(
            user_id=user.id,
            tenant_id=user.tenant_id,
            role=user.role.value,
            is_founder=user.is_founder,
        )

    return _make


@pytest.fixture
def auth_headers(make_token):
    def _make(user: User) -> dict[str, str]:
        return {"Authorization": f"Bearer {make_token(user)}"}

    return _make
