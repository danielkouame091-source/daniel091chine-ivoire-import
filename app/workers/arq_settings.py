"""Configuration ARQ — file de jobs async basée sur Redis."""
from __future__ import annotations

from typing import Any

from arq import cron
from arq.connections import RedisSettings

from app.core.config import settings
from app.workers import (
    forecast_batch,
    freeze_propagation,
    mm_reconciliation,
    nlp_batch,
    notifications,
    relance_batch,
    reporting_batch,
    treasury_batch,
)


async def startup(ctx: dict[str, Any]) -> None:
    ctx["env"] = settings.ENV


async def shutdown(ctx: dict[str, Any]) -> None:
    pass


class WorkerSettings:
    functions = [
        # Mobile Money
        mm_reconciliation.rapprocher_batch,
        mm_reconciliation.reconcile_one,
        # Freeze
        freeze_propagation.propager_gel,
        freeze_propagation.appliquer_effets_cascade,
        # Notifications
        notifications.envoyer_whatsapp,
        notifications.notifier_expiration_abonnement,
        # NLP
        nlp_batch.traiter_suggestions_en_attente,
        # Prévisions
        forecast_batch.recalculer_toutes_les_previsions,
        # Reporting
        reporting_batch.generer_declarations_mensuelles,
        reporting_batch.alerter_echeances_proches,
        # Relances
        relance_batch.executer_relances_quotidiennes,
        # Trésorerie
        treasury_batch.snapshot_quotidien,
    ]

    cron_jobs = [
        cron(forecast_batch.recalculer_toutes_les_previsions, hour=5, minute=0),
        cron(reporting_batch.generer_declarations_mensuelles, day=1, hour=6, minute=0),
        cron(reporting_batch.alerter_echeances_proches, weekday=0, hour=7, minute=0),
        cron(
            relance_batch.executer_relances_quotidiennes,
            weekday={0, 1, 2, 3, 4}, hour=8, minute=0,
        ),
        # Snapshot trésorerie toutes les 4h (6h, 10h, 14h, 18h Abidjan)
        cron(treasury_batch.snapshot_quotidien, hour={5, 9, 13, 17}, minute=0),
    ]

    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    max_jobs = 20
    job_timeout = 600
    keep_result = 3600
    max_tries = 3
    retry_jobs = True
