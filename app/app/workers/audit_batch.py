"""
Job batch — Audit & contrôle interne automatique.

- Audit quotidien : règles temps réel (desequilibre, doublons, FNE manquante)
- Audit hebdomadaire : intégrité, comptes non lettrés, transactions circulaires
- Audit mensuel : Benford, rapport de conformité, escalade des findings critiques
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.enums import SubStatut, TenantStatut, UserRole, UserStatut
from app.models.subscription import Subscription
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.audit_internal import (
    AuditRunRequest,
    ComplianceReportRequest,
)
from app.services.audit_internal_service import AuditInternalService

logger = logging.getLogger(__name__)


async def _iter_active_tenants_with_admin():
    """Générateur : (tenant_id, admin_id) pour les tenants actifs."""
    async with AsyncSessionLocal() as db:
        tenants = (
            await db.execute(
                select(Tenant.id)
                .join(Subscription, Subscription.tenant_id == Tenant.id)
                .where(
                    Tenant.statut == TenantStatut.ACTIF,
                    Tenant.deleted_at.is_(None),
                    Subscription.statut.in_([SubStatut.TRIAL, SubStatut.ACTIF]),
                )
                .distinct()
            )
        ).scalars().all()

        for tenant_id in tenants:
            admin = await db.scalar(
                select(User).where(
                    User.tenant_id == tenant_id,
                    User.role == UserRole.ADMIN_TENANT,
                    User.statut == UserStatut.ACTIF,
                ).limit(1)
            )
            if admin:
                yield tenant_id, admin.id


async def audit_quotidien(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Audit quotidien des règles critiques :
    - Écriture déséquilibrée
    - Facture sans FNE
    - Déclaration DGI en retard
    """
    today = date.today()
    hier = today - timedelta(days=1)
    processed = 0
    total_findings = 0

    async for tenant_id, admin_id in _iter_active_tenants_with_admin():
        try:
            async with AsyncSessionLocal() as db:
                svc = AuditInternalService(db, tenant_id, admin_id)

                # S'assurer que les règles par défaut existent
                await svc.seed_regles_defaut()

                for code in ["COH-001", "FIS-001", "FIS-002"]:
                    runs = await svc.executer_regles(AuditRunRequest(
                        rule_code=code,
                        date_debut=hier,
                        date_fin=today,
                        max_findings=200,
                    ))
                    total_findings += sum(r.nb_findings for r in runs)

                await db.commit()
                processed += 1
        except Exception:
            logger.exception(f"[audit_batch] Échec audit quotidien {tenant_id}")

    return {"tenants_processed": processed, "total_findings": total_findings}


async def audit_hebdomadaire(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Audit hebdomadaire complet : toutes les règles actives.
    """
    today = date.today()
    debut_semaine = today - timedelta(days=7)
    processed = 0
    total_findings = 0

    async for tenant_id, admin_id in _iter_active_tenants_with_admin():
        try:
            async with AsyncSessionLocal() as db:
                svc = AuditInternalService(db, tenant_id, admin_id)
                runs = await svc.executer_regles(AuditRunRequest(
                    date_debut=debut_semaine,
                    date_fin=today,
                    max_findings=1000,
                ))
                total_findings += sum(r.nb_findings for r in runs)
                await db.commit()
                processed += 1
        except Exception:
            logger.exception(f"[audit_batch] Échec audit hebdo {tenant_id}")

    return {"tenants_processed": processed, "total_findings": total_findings}


async def audit_mensuel_conformite(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Génère les rapports de conformité mensuels + Benford.
    """
    today = date.today()
    debut_m
