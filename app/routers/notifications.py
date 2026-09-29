"""Endpoints Notifications & Communications."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from sqlalchemy import select

from app.dependencies.auth import CurrentUser, RequireAdminTenant
from app.dependencies.tenant import CurrentTenant
from app.dependencies.tenant_db import TenantDBSession
from app.models.notification import (
    Notification,
    NotificationCampaign,
    NotificationTemplate,
    PushDevice,
)
from app.schemas.notification import (
    BulkSendIn,
    BulkSendResult,
    CampaignCreate,
    CampaignOut,
    CampaignStatsOut,
    CampaignUpdate,
    InAppNotificationOut,
    MarkReadIn,
    NotificationAnalyticsOut,
    NotificationDetailOut,
    NotificationOut,
    PreferenceOut,
    PreferenceUpsert,
    PushDeviceOut,
    PushDeviceRegisterIn,
    SendNotificationIn,
    SuppressionCreate,
    SuppressionOut,
    TemplateCreate,
    TemplateDetailOut,
    TemplateOut,
    TemplatePreviewIn,
    TemplatePreviewOut,
    TemplateUpdate,
)
from app.services.campaign_service import CampaignService
from app.services.notification_service import NotificationService

router = APIRouter()


# ═════════════════════════════════════════════════════════════════════════════
# TEMPLATES
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/templates", response_model=list[TemplateOut])
async def list_templates(
    current_tenant: CurrentTenant,
    _: RequireAdminTenant,
    db: TenantDBSession,
    canal: str | None = Query(None),
    limit: int = 200,
) -> list[TemplateOut]:
    from sqlalchemy import or_
    stmt = select(NotificationTemplate).where(
        or_(
            NotificationTemplate.tenant_id == current_tenant.id,
            NotificationTemplate.tenant_id.is_(None),
        )
    )
    if canal:
        stmt = stmt.where(NotificationTemplate.canal == canal)
    stmt = stmt.order_by(NotificationTemplate.code, NotificationTemplate.version.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [TemplateOut.model_validate(t) for t in rows]


@router.post("/templates", response_model=TemplateOut, status_code=201)
async def create_template(
    data: TemplateCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> TemplateOut:
    svc = NotificationService(db, current_tenant.id, current_user.id)
    tpl = await svc.creer_template(data)
    return TemplateOut.model_validate(tpl)


@router.patch("/templates/{template_id}", response_model=TemplateOut)
async def update_template(
    template_id: UUID,
    data: TemplateUpdate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> TemplateOut:
    tpl = await db.scalar(
        select(NotificationTemplate).where(NotificationTemplate.id == template_id)
    )
    if tpl is None:
        raise HTTPException(404, "Template introuvable")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(tpl, k, v)
    await db.flush()
    return TemplateOut.model_validate(tpl)


@router.post("/templates/{template_id}/publier", response_model=TemplateOut)
async def publish_template(
    template_id: UUID,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> TemplateOut:
    svc = NotificationService(db, current_tenant.id, current_user.id)
    tpl = await svc.publier_template(template_id)
    return TemplateOut.model_validate(tpl)


@router.post("/templates/{template_id}/preview", response_model=TemplatePreviewOut)
async def preview_template(
    template_id: UUID,
    data: TemplatePreviewIn,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> TemplatePreviewOut:
    svc = NotificationService(db, current_tenant.id, current_user.id)
    return await svc.previsualiser_template(template_id, data)


@router.post("/templates/seed")
async def seed_templates(
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> dict:
    svc = NotificationService(db, current_tenant.id, current_user.id)
    nb = await svc.seed_templates_defaut()
    return {"created": nb}


# ═════════════════════════════════════════════════════════════════════════════
# ENVOI
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/send", response_model=NotificationOut, status_code=201)
async def send_notification(
    data: SendNotificationIn,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> NotificationOut:
    svc = NotificationService(db, current_tenant.id, current_user.id)
    notif = await svc.envoyer(data)
    return NotificationOut.model_validate(notif)


@router.post("/send-bulk", response_model=BulkSendResult, status_code=202)
async def send_bulk(
    data: BulkSendIn,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> BulkSendResult:
    """Envoi groupé (ad-hoc, hors campagne)."""
    svc = NotificationService(db, current_tenant.id, current_user.id)
    batch_id = str(uuid4())
    nb_queued = 0
    nb_suppressed = 0
    nb_erreurs = 0

    for dest in data.destinataires:
        try:
            notif = await svc.envoyer(SendNotificationIn(
                user_id=dest.get("user_id"),
                portal_user_id=dest.get("portal_user_id"),
                destinataire_email=dest.get("email"),
                destinataire_telephone=dest.get("telephone"),
                destinataire_nom=dest.get("nom"),
                canal=data.canal,
                type_notification=data.type_notification,
                criticite=data.criticite,
                template_code=data.template_code,
                contexte=dest.get("contexte", {}),
            ))
            if notif.statut == "suppressed":
                nb_suppressed += 1
            else:
                nb_queued += 1
        except Exception:
            nb_erreurs += 1

    return BulkSendResult(
        nb_queued=nb_queued,
        nb_suppressed=nb_suppressed,
        nb_erreurs=nb_erreurs,
        batch_id=batch_id,
    )


# ═════════════════════════════════════════════════════════════════════════════
# CONSULTATION
# ═════════════════════════════════════════════════════════════════════════════
@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
    user_id: UUID | None = Query(None),
    canal: str | None = Query(None),
    statut: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[NotificationOut]:
    svc = NotificationService(db, current_tenant.id, current_user.id)
    rows = await svc.lister_notifications(user_id, canal, statut, limit, offset)
    return [NotificationOut.model_validate(n) for n in rows]


@router.get("/{notification_id}", response_model=NotificationDetailOut)
async def get_notification(
    notification_id: UUID,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> NotificationDetailOut:
    notif = await db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.tenant_id == current_tenant.id,
        )
    )
    if notif is None:
        raise HTTPException(404, "Notification introuvable")
    return NotificationDetailOut.model_validate(notif)


# ═════════════════════════════════════════════════════════════════════════════
# IN-APP
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/in-app/me", response_model=list[InAppNotificationOut])
async def my_in_app_notifications(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    unread_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
) -> list[InAppNotificationOut]:
    svc = NotificationService(db, current_tenant.id, current_user.id)
    rows = await svc.lister_in_app(current_user.id, unread_only, limit)
    return [InAppNotificationOut.model_validate(n) for n in rows]


@router.post("/in-app/mark-read")
async def mark_read(
    data: MarkReadIn,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> dict:
    svc = NotificationService(db, current_tenant.id, current_user.id)
    count = await svc.marquer_lu(current_user.id, data.notification_ids)
    return {"marked": count}


@router.get("/in-app/count-unread")
async def count_unread(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> dict:
    svc = NotificationService(db, current_tenant.id, current_user.id)
    count = await svc.compter_non_lus(current_user.id)
    return {"count": count}


# ═════════════════════════════════════════════════════════════════════════════
# PRÉFÉRENCES
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/preferences/me", response_model=list[PreferenceOut])
async def my_preferences(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> list[PreferenceOut]:
    svc = NotificationService(db, current_tenant.id, current_user.id)
    rows = await svc.lister_preferences(current_user.id)
    return [PreferenceOut.model_validate(p) for p in rows]


@router.put("/preferences/me", response_model=PreferenceOut)
async def upsert_preference(
    data: PreferenceUpsert,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> PreferenceOut:
    svc = NotificationService(db, current_tenant.id, current_user.id)
    pref = await svc.upsert_preference(current_user.id, data)
    return PreferenceOut.model_validate(pref)


# ═════════════════════════════════════════════════════════════════════════════
# SUPPRESSION
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/suppressions", response_model=SuppressionOut, status_code=201)
async def add_suppression(
    data: SuppressionCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> SuppressionOut:
    svc = NotificationService(db, current_tenant.id, current_user.id)
    supp = await svc.ajouter_suppression(data)
    return SuppressionOut.model_validate(supp)


@router.post("/suppressions/unsubscribe")
async def public_unsubscribe(
    email: str = Query(...),
    token: str = Query(...),
    db: TenantDBSession = None,
) -> dict:
    """Désabonnement public (lien dans l'email)."""
    # Vérifier le token (HMAC sur email + secret)
    # À implémenter : vérification signature
    svc = NotificationService(db, None, None)
    from app.schemas.notification import SuppressionCreate
    await svc.ajouter_suppression(SuppressionCreate(
        email=email,
        motif="unsubscribe",
    ))
    return {"ok": True, "message": "Vous avez été désabonné."}


# ═════════════════════════════════════════════════════════════════════════════
# PUSH DEVICES
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/push/register", response_model=PushDeviceOut, status_code=201)
async def register_push_device(
    data: PushDeviceRegisterIn,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> PushDeviceOut:
    existing = await db.scalar(
        select(PushDevice).where(PushDevice.device_token == data.device_token)
    )
    if existing:
        existing.actif = True
        existing.derniere_utilisation_at = datetime.now(timezone.utc)
        await db.flush()
        return PushDeviceOut.model_validate(existing)

    device = PushDevice(
        tenant_id=current_tenant.id,
        user_id=current_user.id,
        **data.model_dump(),
    )
    db.add(device)
    await db.flush()
    return PushDeviceOut.model_validate(device)


@router.delete("/push/{device_id}", status_code=204)
async def unregister_push_device(
    device_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> None:
    device = await db.scalar(
        select(PushDevice).where(
            PushDevice.id == device_id,
            PushDevice.user_id == current_user.id,
        )
    )
    if device:
        device.actif = False
        await db.flush()


# ═════════════════════════════════════════════════════════════════════════════
# CAMPAGNES
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/campaigns", response_model=list[CampaignOut])
async def list_campaigns(
    current_tenant: CurrentTenant,
    _: RequireAdminTenant,
    db: TenantDBSession,
    statut: str | None = Query(None),
    limit: int = 100,
) -> list[CampaignOut]:
    stmt = select(NotificationCampaign).where(NotificationCampaign.tenant_id == current_tenant.id)
    if statut:
        stmt = stmt.where(NotificationCampaign.statut == statut)
    stmt = stmt.order_by(NotificationCampaign.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [CampaignOut.model_validate(c) for c in rows]


@router.post("/campaigns", response_model=CampaignOut, status_code=201)
async def create_campaign(
    data: CampaignCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> CampaignOut:
    svc = CampaignService(db, current_tenant.id, current_user.id)
    c = await svc.creer_campagne(data)
    return CampaignOut.model_validate(c)


@router.patch("/campaigns/{campaign_id}", response_model=CampaignOut)
async def update_campaign(
    campaign_id: UUID,
    data: CampaignUpdate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> CampaignOut:
    svc = CampaignService(db, current_tenant.id, current_user.id)
    c = await svc.modifier_campagne(campaign_id, data)
    return CampaignOut.model_validate(c)


@router.post("/campaigns/{campaign_id}/lancer")
async def launch_campaign(
    campaign_id: UUID,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> dict:
    svc = CampaignService(db, current_tenant.id, current_user.id)
    return await svc.lancer_campagne(campaign_id)


@router.post("/campaigns/{campaign_id}/pause", response_model=CampaignOut)
async def pause_campaign(
    campaign_id: UUID,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> CampaignOut:
    svc = CampaignService(db, current_tenant.id, current_user.id)
    c = await svc.pause_campagne(campaign_id)
    return CampaignOut.model_validate(c)


@router.post("/campaigns/{campaign_id}/annuler", response_model=CampaignOut)
async def cancel_campaign(
    campaign_id: UUID,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> CampaignOut:
    svc = CampaignService(db, current_tenant.id, current_user.id)
    c = await svc.annuler_campagne(campaign_id)
    return CampaignOut.model_validate(c)


@router.get("/campaigns/{campaign_id}/stats", response_model=CampaignStatsOut)
async def campaign_stats(
    campaign_id: UUID,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> CampaignStatsOut:
    svc = CampaignService(db, current_tenant.id, current_user.id)
    data = await svc.stats_campagne(campaign_id)
    return CampaignStatsOut(**data)


# ═════════════════════════════════════════════════════════════════════════════
# WEBHOOKS PROVIDERS (PUBLICS)
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/webhooks/{provider}")
async def provider_webhook(
    provider: str,
    request_data: dict = Body(...),
    x_twilio_signature: str | None = Header(None),
    x_sendgrid_signature: str | None = Header(None),
    db: TenantDBSession = None,
) -> dict:
    """
    Webhook générique des providers (SendGrid, Postmark, Twilio).
    Les events traités : delivered, open, click, bounce, unsubscribe.
    """
    # À terme : vérifier la signature HMAC selon le provider
    svc = NotificationService(db, None, None)
    await svc.enregistrer_webhook_provider(provider, request_data)
    return {"ok": True}


# ═════════════════════════════════════════════════════════════════════════════
# ANALYTICS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/analytics", response_model=NotificationAnalyticsOut)
async def analytics(
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
    jours: int = Query(30, ge=1, le=365),
) -> NotificationAnalyticsOut:
    svc = NotificationService(db, current_tenant.id, current_user.id)
    fin = datetime.now(timezone.utc)
    debut = fin - timedelta(days=jours)
    data = await svc.analytics(debut, fin)
    return NotificationAnalyticsOut(
        tenant_id=current_tenant.id,
        periode_debut=debut,
        periode_fin=fin,
        **data,
    )
