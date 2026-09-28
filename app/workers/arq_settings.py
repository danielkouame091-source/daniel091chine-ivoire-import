"""
Configuration ARQ — file de jobs async basée sur Redis.
Démarrage : `arq app.workers.arq_settings.WorkerSettings`
"""
from __future__ import annotations

from typing import Any

from arq.connections import RedisSettings

from app.core.config import settings
from app.workers import (
    freeze_propagation,
    mm_reconciliation,
    nlp_batch,
    notifications,
)


async def startup(ctx: dict[str, Any]) -> None:
    """Initialise le contexte partagé par tous les jobs."""
    ctx["env"] = settings.ENV
    ctx["app_name"] = settings.APP_NAME


async def shutdown(ctx: dict[str, Any]) -> None:
    """Nettoyage (rien à faire ici, ARQ ferme Redis)."""
    pass


class WorkerSettings:
    # Fonctions exposées à la queue
    functions = [
        mm_reconciliation.rapprocher_batch,
        mm_reconciliation.reconcile_one,
        freeze_propagation.propager_gel,
        freeze_propagation.appliquer_effets_cascade,
        notifications.envoyer_whatsapp,
        notifications.notifier_expiration_abonnement,
        nlp_batch.traiter_suggestions_en_attente,
    ]

    # Cron jobs (optionnel, tous les jours à 06h UTC)
    cron_jobs = [
        # Vérifie chaque nuit les abonnements expirant sous 7 jours
        # et envoie notifications WhatsApp / email
        # Utiliser arq.cron si nécessaire — laissé en commentaire pour MVP
    ]

    on_startup = startup
    on_shutdown = shutdown

    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)

    # Fiabilité
    max_jobs = 20
    job_timeout = 300                  # 5 min par job
    keep_result = 3600                 # résultats conservés 1h
    max_tries = 5
    retry_jobs = True
