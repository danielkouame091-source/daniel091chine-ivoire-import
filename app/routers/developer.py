"""Endpoints Developer Portal — Publishers, tokens, docs."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from app.dependencies.auth import CurrentUser
from app.dependencies.tenant_db import TenantDBSession
from app.schemas.marketplace import (
    DeveloperTokenCreateIn,
    DeveloperTokenCreatedOut,
    DeveloperTokenOut,
    ExtensionCreateIn,
    ExtensionOut,
    ExtensionUpdateIn,
    ExtensionVersionOut,
    ExtensionVersionPublishIn,
    PublisherDashboardOut,
    PublisherOut,
    PublisherRegisterIn,
    PublisherUpdateIn,
)
from app.services.marketplace_service import MarketplaceService

router = APIRouter()


# ═════════════════════════════════════════════════════════════════════════════
# PROFIL PUBLISHER
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/register", response_model=PublisherOut, status_code=201)
async def register_publisher(
    data: PublisherRegisterIn,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> PublisherOut:
    """Enregistrement comme publisher (une fois par utilisateur)."""
    svc = MarketplaceService(db, current_user.id)
    pub = await svc.enregistrer_publisher(data)
    return PublisherOut.model_validate(pub)


@router.get("/me", response_model=PublisherDetailOut | None)
async def get_my_publisher_profile(
    current_user: CurrentUser,
    db: TenantDBSession,
) -> PublisherDetailOut | None:
    from sqlalchemy import select
    from app.models.marketplace import Publisher

    pub = await db.scalar(
        select(Publisher).where(Publisher.user_id == current_user.id)
    )
    return PublisherDetailOut.model_validate(pub) if pub else None


@router.patch("/me", response_model=PublisherOut)
async def update_my_publisher_profile(
    data: PublisherUpdateIn,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> PublisherOut:
    from sqlalchemy import select
    from app.models.marketplace import Publisher

    pub = await db.scalar(
        select(Publisher).where(Publisher.user_id == current_user.id)
    )
    if pub is None:
        from fastapi import HTTPException
        raise HTTPException(404, "Publisher introuvable")

    svc = MarketplaceService(db, current_user.id)
    updated = await svc.modifier_publisher(pub.id, data)
    return PublisherOut.model_validate(updated)


@router.get("/dashboard", response_model=PublisherDashboardOut)
async def get_publisher_dashboard(
    current_user: CurrentUser,
    db: TenantDBSession,
) -> PublisherDashboardOut:
    from sqlalchemy import select
    from app.models.marketplace import Publisher

    pub = await db.scalar(
        select(Publisher).where(Publisher.user_id == current_user.id)
    )
    if pub is None:
        from fastapi import HTTPException
        raise HTTPException(404, "Publisher introuvable")

    svc = MarketplaceService(db, current_user.id)
    data = await svc.dashboard_publisher(pub.id)
    return PublisherDashboardOut(**data)


# ═════════════════════════════════════════════════════════════════════════════
# MES EXTENSIONS
# ═════════════════════════════════════════════════════════════════════════════
async def _get_my_publisher_id(db, user_id) -> UUID:
    from sqlalchemy import select
    from app.models.marketplace import Publisher
    from fastapi import HTTPException

    pub = await db.scalar(select(Publisher).where(Publisher.user_id == user_id))
    if pub is None:
        raise HTTPException(404, "Publisher introuvable — inscrivez-vous d'abord")
    return pub.id


@router.get("/extensions", response_model=list[ExtensionOut])
async def list_my_extensions(
    current_user: CurrentUser,
    db: TenantDBSession,
) -> list[ExtensionOut]:
    from sqlalchemy import desc, select
    from app.models.marketplace import Extension

    pub_id = await _get_my_publisher_id(db, current_user.id)
    rows = (
        await db.execute(
            select(Extension)
            .where(Extension.publisher_id == pub_id)
            .order_by(desc(Extension.created_at))
        )
    ).scalars().all()
    return [ExtensionOut.model_validate(e) for e in rows]


@router.post("/extensions", response_model=ExtensionOut, status_code=201)
async def create_extension(
    data: ExtensionCreateIn,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> ExtensionOut:
    pub_id = await _get_my_publisher_id(db, current_user.id)
    svc = MarketplaceService(db, current_user.id)
    ext = await svc.creer_extension(pub_id, data)
    return ExtensionOut.model_validate(ext)


@router.patch("/extensions/{extension_id}", response_model=ExtensionOut)
async def update_extension(
    extension_id: UUID,
    data: ExtensionUpdateIn,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> ExtensionOut:
    pub_id = await _get_my_publisher_id(db, current_user.id)

    from sqlalchemy import select
    from app.models.marketplace import Extension
    ext = await db.scalar(
        select(Extension).where(
            Extension.id == extension_id,
            Extension.publisher_id == pub_id,
        )
    )
    if ext is None:
        from fastapi import HTTPException
        raise HTTPException(404, "Extension introuvable")

    svc = MarketplaceService(db, current_user.id)
    updated = await svc.modifier_extension(extension_id, data)
    return ExtensionOut.model_validate(updated)


@router.post("/extensions/{extension_id}/soumettre", response_model=ExtensionOut)
async def submit_extension_for_review(
    extension_id: UUID,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> ExtensionOut:
    pub_id = await _get_my_publisher_id(db, current_user.id)
    svc = MarketplaceService(db, current_user.id)
    ext = await svc.soumettre_extension(extension_id)
    return ExtensionOut.model_validate(ext)


# ═════════════════════════════════════════════════════════════════════════════
# VERSIONS
# ═════════════════════════════════════════════════════════════════════════════
@router.post(
    "/extensions/{extension_id}/versions",
    response_model=ExtensionVersionOut,
    status_code=201,
)
async def publish_new_version(
    extension_id: UUID,
    data: ExtensionVersionPublishIn,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> ExtensionVersionOut:
    pub_id = await _get_my_publisher_id(db, current_user.id)

    from sqlalchemy import select
    from app.models.marketplace import Extension
    ext = await db.scalar(
        select(Extension).where(
            Extension.id == extension_id,
            Extension.publisher_id == pub_id,
        )
    )
    if ext is None:
        from fastapi import HTTPException
        raise HTTPException(404, "Extension introuvable")

    svc = MarketplaceService(db, current_user.id)
    version = await svc.publier_version(extension_id, data)
    return ExtensionVersionOut.model_validate(version)


# ═════════════════════════════════════════════════════════════════════════════
# TOKENS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/tokens", response_model=list[DeveloperTokenOut])
async def list_my_tokens(
    current_user: CurrentUser,
    db: TenantDBSession,
) -> list[DeveloperTokenOut]:
    pub_id = await _get_my_publisher_id(db, current_user.id)
    svc = MarketplaceService(db, current_user.id)
    rows = await svc.lister_tokens_dev(pub_id)
    return [DeveloperTokenOut.model_validate(t) for t in rows]


@router.post("/tokens", response_model=DeveloperTokenCreatedOut, status_code=201)
async def create_dev_token(
    data: DeveloperTokenCreateIn,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> DeveloperTokenCreatedOut:
    pub_id = await _get_my_publisher_id(db, current_user.id)
    svc = MarketplaceService(db, current_user.id)
    token, token_plain = await svc.creer_token_dev(
        pub_id, data.nom, data.environnement, data.scopes, data.expire_at,
    )
    return DeveloperTokenCreatedOut(
        id=token.id,
        nom=token.nom,
        token_plain=token_plain,
        token_prefix=token.token_prefix,
        environnement=token.environnement,
        scopes=token.scopes,
        expire_at=token.expire_at,
    )


# ═════════════════════════════════════════════════════════════════════════════
# DOCS / SDK
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/docs")
async def developer_docs() -> dict:
    """Documentation SDK pour développeurs."""
    from app.core.marketplace_syscohada import (
        HOOKS_DISPONIBLES,
        MANIFEST_EXEMPLE,
        PermissionExtension,
    )

    return {
        "manifest_exemple": MANIFEST_EXEMPLE,
        "hooks_disponibles": sorted(HOOKS_DISPONIBLES),
        "permissions_disponibles": sorted(
            v for k, v in PermissionExtension.__dict__.items()
            if not k.startswith("_") and isinstance(v, str)
        ),
        "signature_webhook": {
            "header": "X-MTech-Signature",
            "format": "HMAC-SHA256(secret, '{timestamp}.{body}')",
            "verification_exemple_python": (
                "import hmac, hashlib, json\n"
                "def verify(secret, timestamp, body_bytes, signature):\n"
                "    signed = f'{timestamp}.{body_bytes.decode()}'\n"
                "    expected = hmac.new(secret.encode(), signed.encode(), hashlib.sha256).hexdigest()\n"
                "    return hmac.compare_digest(expected, signature)\n"
            ),
        },
        "endpoints_sandbox": {
            "base_url": "https://sandbox-api.mtech.ci/v1",
            "auth": "Bearer mtech_dev_xxx",
        },
        "endpoints_production": {
            "base_url": "https://api.mtech.ci/v1",
            "auth": "Bearer mtech_live_xxx",
        },
        "rate_limits": {
            "sandbox": "100 req/min",
            "production": "1000 req/min",
        },
        "support": {
            "email": "dev@mtech.ci",
            "docs_url": "https://developers.mtech.ci",
            "slack": "https://mtech-ci.slack.com",
        },
    }
