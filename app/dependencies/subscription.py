"""
Dépendances d'abonnement — appliquent la logique de bascule en lecture seule.

Stratégie :
- `get_subscription_status()`  → calcule l'état SANS bloquer (informatif).
- `require_active_subscription` → BLOQUE les mutations si expiré.
- `allow_read_only`            → autorise un endpoint même en read-only
                                  (utilisé pour /billing, /auth, /me).
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.deps import get_db, get_tenant_db
from app.dependencies.auth import CurrentUser
from app.models.enums import SubStatut, TenantStatut
from app.models.subscription import Subscription
from app.schemas.subscription import SubscriptionStatusOut


# ---------------------------------------------------------------------------
# Calcul d'état (informatif, jamais bloquant)
# ---------------------------------------------------------------------------
async def get_subscription_status(
    request: Request,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SubscriptionStatusOut | None:
    """
    Retourne l'état d'abonnement du tenant courant.
    - None si l'utilisateur est fondateur (pas d'abonnement).
    - Sinon calcule : jours restants, expiration, grâce, read-only.
    """
    if current_user.is_founder or current_user.tenant_id is None:
        return None

    stmt = (
        select(Subscription)
        .where(
            Subscription.tenant_id == current_user.tenant_id,
            Subscription.statut.in_(
                [SubStatut.TRIAL, SubStatut.ACTIF, SubStatut.IMPAYE]
            ),
        )
        .order_by(Subscription.periode_fin.desc())
        .limit(1)
    )
    sub = (await db.execute(stmt)).scalar_one_or_none()

    now = datetime.now(timezone.utc)

    if sub is None:
        # Aucun abonnement actif du tout
        return SubscriptionStatusOut(
            statut=SubStatut.EXPIRE,
            periode_fin=now,
            jours_restants=0,
            est_expiree=True,
            est_en_grace=False,
            force_read_only=True,
        )

    periode_fin = sub.periode_fin
    # Normalisation timezone
    if periode_fin.tzinfo is None:
        periode_fin = periode_fin.replace(tzinfo=timezone.utc)

    est_expiree = periode_fin < now
    est_en_grace = (
        est_expiree
        and (periode_fin + timedelta(days=sub.grace_jours)) > now
    )
    force_read_only = (
        sub.statut in (SubStatut.EXPIRE, SubStatut.SUSPENDU, SubStatut.RESILIE)
        or est_expiree
    )
    jours_restants = max(0, (periode_fin - now).days)

    # Propagation au middleware (utilisé par get_tenant_db)
    request.state.read_only = force_read_only

    return SubscriptionStatusOut(
        statut=sub.statut,
        periode_fin=periode_fin,
        jours_restants=jours_restants,
        est_expiree=est_expiree,
        est_en_grace=est_en_grace,
        force_read_only=force_read_only,
        plan_code=None,  # optionnel : enrichir via JOIN si besoin
    )


SubscriptionStatus = Annotated[
    SubscriptionStatusOut | None, Depends(get_subscription_status)
]


# ---------------------------------------------------------------------------
# Guard : bloque les mutations si read-only
# ---------------------------------------------------------------------------
READ_ONLY_EXEMPT_PREFIXES = (
    "/api/v1/billing",
    "/api/v1/auth",
    "/api/v1/me",
)


def require_active_subscription() -> Callable[..., None]:
    """
    Dépendance à poser sur tout endpoint MUTANT (POST/PUT/PATCH/DELETE).
    Lève 402 Payment Required si l'abonnement est expiré.

    ⚠️ À utiliser conjointement avec `get_tenant_db` (RLS bloque aussi, mais
    on veut un message clair côté API).
    """

    async def _checker(
        request: Request,
        status_: SubscriptionStatus,
    ) -> None:
        # Endpoints exemptés (renouvellement, auth, profil)
        path = request.url.path
        if any(path.startswith(p) for p in READ_ONLY_EXEMPT_PREFIXES):
            return

        if status_ is None:
            # Pas d'abonnement pour un non-fondateur = anormal
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Aucun abonnement actif",
            )

        if status_.force_read_only:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "code": "SUBSCRIPTION_EXPIRED",
                    "message": (
                        "Abonnement expiré — compte en lecture seule. "
                        "Renouvelez pour réactiver les écritures."
                    ),
                    "periode_fin": status_.periode_fin.isoformat(),
                    "renew_url": "/api/v1/billing/renew",
                },
            )

    return _checker


RequireActiveSubscription = Annotated[None, Depends(require_active_subscription())]
