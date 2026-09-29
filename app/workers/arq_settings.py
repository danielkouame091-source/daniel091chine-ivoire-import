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
    reporting_batch,
)


async def startup(ctx: dict[str, Any]) -> None:
    ctx["env"] = settings.ENV


async def shutdown(ctx: dict[str, Any]) -> None:
    pass


class WorkerSettings:
    functions = [
        mm_reconciliation.rapprocher_batch,
        mm_reconciliation.reconcile_one,
        freeze_propagation.propager_gel,
        freeze_propagation.appliquer_effets_cascade,
        notifications.envoyer_whatsapp,
        notifications.notifier_expiration_abonnement,
        nlp_batch.traiter_suggestions_en_attente,
        forecast_batch.recalculer_toutes_les_previsions,
        reporting_batch.generer_declarations_mensuelles,
        reporting_batch.alerter_echeances_proches,
    ]

    cron_jobs = [
        # Prévisions quotidiennes à 05h UTC (06h Abidjan)
        cron(forecast_batch.recalculer_toutes_les_previsions, hour=5, minute=0),
        # Déclarations mensuelles le 1er de chaque mois à 06h UTC
        cron(reporting_batch.generer_declarations_mensuelles, day=1, hour=6, minute=0),
        # Alertes échéances chaque lundi à 07h UTC
        cron(reporting_batch.alerter_echeances_proches, weekday=0, hour=7, minute=0),
    ]

    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    max_jobs = 20
    job_timeout = 600
    keep_result = 3600
    max_tries = 3
    retry_jobs = True
