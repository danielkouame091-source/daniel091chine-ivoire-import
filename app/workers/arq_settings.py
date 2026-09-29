"""Configuration ARQ — file de jobs async basée sur Redis."""
from __future__ import annotations

from typing import Any

from arq import cron
from arq.connections import RedisSettings

from app.core.config import settings
from app.workers import (
    analytical_batch,
    audit_batch,
    consolidation_batch,
    fne_batch,
    forecast_batch,
    formation_batch,
    freeze_propagation,
    hr_batch,
    mm_reconciliation,
    nlp_batch,
    notification_batch,
    notifications,
    project_batch,
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
        relance_batch.executer_relances_quotidiennes,
        treasury_batch.snapshot_quotidien,
        analytical_batch.recalculer_budgets_actifs,
        analytical_batch.alerter_depassements_budgetaires,
        consolidation_batch.executer_consolidations_mensuelles,
        fne_batch.retry_certifications_fne,
        fne_batch.sync_stickers_et_alerter,
        audit_batch.audit_quotidien,
        audit_batch.audit_hebdomadaire,
        audit_batch.audit_mensuel_conformite,
        audit_batch.escalader_findings_critiques,
        project_batch.recalculer_avancements_et_alertes,
        project_batch.liberer_retenues_garantie,
        formation_batch.verifier_sla_tickets,
        formation_batch.suggerer_articles_manquants,
        hr_batch.alerte_fins_cdd_et_periodes_essai,
        hr_batch.alerte_soldes_conges_faibles,
        hr_batch.initialiser_soldes_conges_annee,
        notification_batch.traiter_file_notifications,
        notification_batch.nettoyer_anciennes_notifications,
        notification_batch.envoyer_campagnes_planifiees,
    ]

    cron_jobs = [
        cron(forecast_batch.recalculer_toutes_les_previsions, hour=5, minute=0),
        cron(reporting_batch.generer_declarations_mensuelles, day=1, hour=6, minute=0),
        cron(reporting_batch.alerter_echeances_proches, weekday=0, hour=7, minute=0),
        cron(relance_batch.executer_relances_quotidiennes, weekday={0, 1, 2, 3, 4}, hour=8, minute=0),
        cron(treasury_batch.snapshot_quotidien, hour={5, 9, 13, 17}, minute=0),
        cron(analytical_batch.recalculer_budgets_actifs, hour=3, minute=0),
        cron(analytical_batch.alerter_depassements_budgetaires, weekday=0, hour=7, minute=30),
        cron(consolidation_batch.executer_consolidations_mensuelles, day=5, hour=4, minute=0),
        cron(fne_batch.retry_certifications_fne, minute={0, 15, 30, 45}),
        cron(fne_batch.sync_stickers_et_alerter, hour={0, 6, 12, 18}, minute=30),
        cron(audit_batch.audit_quotidien, hour=2, minute=0),
        cron(audit_batch.audit_hebdomadaire, weekday=6, hour=2, minute=30),
        cron(audit_batch.audit_mensuel_conformite, day=1, hour=3, minute=0),
        cron(audit_batch.escalader_findings_critiques, hour={0, 6, 12, 18}, minute=15),
        cron(project_batch.recalculer_avancements_et_alertes, hour=1, minute=0),
        cron(project_batch.liberer_retenues_garantie, day=1, hour=4, minute=30),
        cron(formation_batch.verifier_sla_tickets, minute=0),
        cron(formation_batch.suggerer_articles_manquants, weekday=0, hour=5, minute=0),
        cron(hr_batch.alerte_fins_cdd_et_periodes_essai, hour=6, minute=0),
        cron(hr_batch.alerte_soldes_conges_faibles, weekday=0, hour=6, minute=30),
        cron(hr_batch.initialiser_soldes_conges_annee, day=1, hour=1, minute=0),
        # Notifications : traitement toutes les minutes
        cron(notification_batch.traiter_file_notifications, minute="*"),
        # Campagnes planifiées : toutes les 5 minutes
        cron(notification_batch.envoyer_campagnes_planifiees, minute="*/5"),
        # Nettoyage nocturne
        cron(notification_batch.nettoyer_anciennes_notifications, day=1, hour=5, minute=30),
    ]

    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    max_jobs = 30
    job_timeout = 900
    keep_result = 3600
    max_tries = 3
    retry_jobs = True
