"""
Service Alert Engine — Évaluation des règles d'alerte en streaming.

Chaque event publié déclenche l'évaluation des règles actives du tenant.
Si condition remplie + cooldown dépassé → alerte créée + actions exécutées.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.realtime_syscohada import (
    KafkaTopic,
    LimitesAnalytics,
    SEVERITE_POIDS,
    SeveriteAlerte,
    StatutAlerte,
    TypeAlerte,
)
from app.models.realtime import AlertRule, RealtimeAlert
from app.schemas.realtime import (
    AlertRuleCreateIn,
    AlertRuleUpdateIn,
)
from app.services.audit_service import AuditService
from app.services.clickhouse_service import ClickHouseService
from app.services.kafka_producer_service import KafkaProducerService

logger = logging.getLogger(__name__)


class AlertEngineService:
    """
    Moteur d'évaluation d'alertes.
    """

    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID | None = None) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.audit = AuditService(db)

    # ═════════════════════════════════════════════════════════════════════
    # CRUD RÈGLES
    # ═════════════════════════════════════════════════════════════════════
    async def creer_regle(self, data: AlertRuleCreateIn) -> AlertRule:
        # Quota
        count = 0
        from sqlalchemy import func
        count = int(await self.db.scalar(
            select(func.count(AlertRule.id)).where(
                AlertRule.tenant_id == self.tenant_id,
                AlertRule.active.is_(True),
            )
        ) or 0)
        if count >= LimitesAnalytics.MAX_ALERT_RULES_PER_TENANT:
            raise HTTPException(400, f"Quota de règles atteint ({LimitesAnalytics.MAX_ALERT_RULES_PER_TENANT})")

        # Unicité
        existing = await self.db.scalar(
            select(AlertRule.id).where(
                AlertRule.tenant_id == self.tenant_id,
                AlertRule.code == data.code,
            )
        )
        if existing:
            raise HTTPException(409, f"Règle {data.code} existe déjà")

        rule = AlertRule(
            tenant_id=self.tenant_id,
            **data.model_dump(),
            active=True,
            created_by_user_id=self.user_id,
        )
        self.db.add(rule)
        await self.db.flush()
        return rule

    async def modifier_regle(
        self, rule_id: UUID, data: AlertRuleUpdateIn
    ) -> AlertRule:
        rule = await self._get_rule(rule_id)
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(rule, k, v)
        await self.db.flush()
        return rule

    async def lister_regles(self, active_only: bool = True) -> list[AlertRule]:
        stmt = select(AlertRule).where(AlertRule.tenant_id == self.tenant_id)
        if active_only:
            stmt = stmt.where(AlertRule.active.is_(True))
        return list((await self.db.execute(stmt.order_by(AlertRule.code))).scalars().all())

    # ═════════════════════════════════════════════════════════════════════
    # ÉVALUATION (appelé pour chaque event)
    # ═════════════════════════════════════════════════════════════════════
    async def evaluer_event(self, event: dict[str, Any]) -> list[RealtimeAlert]:
        """
        Évalue toutes les règles actives pour un event.
        Retourne les alertes déclenchées.
        """
        topic = event.get("topic")
        event_type = event.get("event_type")
        payload = event.get("payload", {})

        if not topic:
            return []

        # Règles actives de ce topic
        regles = (
            await self.db.execute(
                select(AlertRule).where(
                    AlertRule.tenant_id == self.tenant_id,
                    AlertRule.active.is_(True),
                    AlertRule.topic == topic,
                )
            )
        ).scalars().all()

        alertes: list[RealtimeAlert] = []

        for rule in regles:
            # Filtre event_type
            if rule.event_type and rule.event_type != event_type:
                continue

            # Filtre custom
            if rule.filtre and not self._matcher_filtre(rule.filtre, payload):
                continue

            # Évaluer la condition
            try:
                declenche = await self._evaluer_condition(rule, event)
            except Exception:
                logger.exception(f"[alert_engine] Erreur évaluation règle {rule.code}")
                continue

            if not declenche:
                continue

            # Cooldown
            if rule.dernier_declenchement_at:
                delta = (datetime.now(timezone.utc) - rule.dernier_declenchement_at).total_seconds()
                if delta < rule.cooldown_s:
                    continue

            # Créer l'alerte
            alerte = await self._creer_alerte(rule, event)
            alertes.append(alerte)

            # Mettre à jour le dernier déclenchement
            rule.dernier_declenchement_at = datetime.now(timezone.utc)

        return alertes

    async def _evaluer_condition(
        self, rule: AlertRule, event: dict[str, Any]
    ) -> bool:
        """Évalue la condition selon le type d'alerte."""
        cond = rule.condition or {}
        payload = event.get("payload", {})

        if rule.type_alerte == TypeAlerte.SEUIL_MONTANT:
            field = cond.get("field")
            operator = cond.get("operator", ">")
            value = cond.get("value")
            if not field or value is None:
                return False
            montant = self._extraire_valeur(payload, field)
            return self._comparer(montant, operator, value)

        if rule.type_alerte == TypeAlerte.SEUIL_VOLUME:
            # Nécessite ClickHouse pour compter la fenêtre
            window_s = cond.get("window_s", rule.fenetre_duree_s)
            threshold = cond.get("threshold", 10)
            try:
                ch = ClickHouseService(self.tenant_id)
                count = await ch.compter_events(rule.topic, window_s, self.tenant_id)
                return count >= threshold
            except Exception:
                logger.warning("[alert_engine] ClickHouse indisponible pour seuil_volume")
                return False

        if rule.type_alerte == TypeAlerte.SEUIL_VITESSE:
            # Vitesse = events/sec
            window_s = cond.get("window_s", 60)
            threshold = cond.get("threshold_per_sec", 10)
            try:
                ch = ClickHouseService(self.tenant_id)
                count = await ch.compter_events(rule.topic, window_s, self.tenant_id)
                vitesse = count / window_s if window_s else 0
                return vitesse >= threshold_per_sec
            except Exception:
                return False

        if rule.type_alerte == TypeAlerte.VARIATION_PCT:
            field = cond.get("field")
            period_s = cond.get("period_s", 3600)
            threshold_pct = cond.get("threshold_pct", 50)
            if not field:
                return False
            # Compare N vs N-1 (nécessite ClickHouse)
            try:
                ch = ClickHouseService(self.tenant_id)
                # Implémentation simplifiée : comparer la valeur de la dernière période
                # avec la valeur moyenne
                # À enrichir en production
                return False
            except Exception:
                return False

        return False

    async def _creer_alerte(
        self, rule: AlertRule, event: dict[str, Any]
    ) -> RealtimeAlert:
        """Crée une alerte depuis une règle et un event."""
        year = datetime.now(timezone.utc).year
        ref = f"ALT-{year}-{secrets.token_hex(4).upper()}"

        # Extraire info du payload
        titre = rule.nom
        description = rule.description or f"Règle {rule.code} déclenchée"

        alerte = RealtimeAlert(
            tenant_id=self.tenant_id,
            rule_id=rule.id,
            reference=ref,
            severite=rule.severite,
            titre=titre,
            description=description,
            event_declencheur=event,
            metriques=rule.condition,
            source_type=event.get("topic"),
            source_id=None,
            statut=StatutAlerte.ACTIVE,
        )
        self.db.add(alerte)
        await self.db.flush()

        # Exécuter les actions
        await self._executer_actions(rule, alerte)
        await self.db.flush()

        # Publier sur Kafka (topic alerts)
        try:
            producer = KafkaProducerService(self.db, self.tenant_id, self.user_id)
            await producer.emit_alert(alerte.id, rule.severite, titre)
        except Exception:
            logger.exception("[alert_engine] Échec publication Kafka alerte")

        # Audit
        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="REALTIME_ALERT_TRIGGERED",
            ressource="realtime_alert",
            ressource_id=alerte.id,
            payload={
                "reference": ref,
                "rule_code": rule.code,
                "severite": rule.severite,
            },
        )

        logger.warning(
            f"[alert_engine] 🚨 Alerte {ref} déclenchée "
            f"(règle {rule.code}, sévérité {rule.severite})"
        )

        return alerte

    async def _executer_actions(
        self, rule: AlertRule, alerte: RealtimeAlert
    ) -> None:
        """Exécute les actions configurées (notifications, webhooks, gel)."""
        executees: list[dict[str, Any]] = []

        for action in rule.actions or []:
            try:
                atype = action.get("type")

                if atype == "notification":
                    # Enqueue notification via worker
                    from arq import create_pool
                    from app.workers.arq_settings import WorkerSettings
                    redis = await create_pool(WorkerSettings.redis_settings)
                    await redis.enqueue_job(
                        "envoyer_alerte_notification",
                        str(alerte.id),
                        action,
                    )
                    await redis.aclose()
                    executees.append({"type": "notification", "status": "enqueued"})

                elif atype == "webhook":
                    from arq import create_pool
                    from app.workers.arq_settings import WorkerSettings
                    redis = await create_pool(WorkerSettings.redis_settings)
                    await redis.enqueue_job(
                        "envoyer_alerte_webhook",
                        str(alerte.id),
                        action.get("url"),
                    )
                    await redis.aclose()
                    executees.append({"type": "webhook", "status": "enqueued"})

                elif atype == "freeze_tenant":
                    # Gel automatique du tenant (rigueur bancaire)
                    from app.services.freeze_service import FreezeService
                    from app.schemas.freeze import FreezeRequest
                    from app.core.freeze_syscohada import FreezeCible

                    if SEVERITE_POIDS.get(rule.severite, 0) >= 3:
                        freeze_svc = FreezeService(self.db, self.tenant_id, self.user_id or self.tenant_id)
                        await freeze_svc.geler(
                            FreezeRequest(
                                cible_type=FreezeCible.TENANT,
                                cible_id=self.tenant_id,
                                motif=f"Alerte automatique : {alerte.titre}",
                                cascade=True,
                            )
                        )
                        executees.append({"type": "freeze_tenant", "status": "executed"})

                else:
                    executees.append({"type": atype, "status": "unknown"})

            except Exception as exc:
                logger.exception(f"[alert_engine] Échec action {action}")
                executees.append({"type": action.get("type"), "status": "failed", "error": str(exc)})

        alerte.actions_executees = executees

    # ═════════════════════════════════════════════════════════════════════
    # CYCLE DE VIE ALERTE
    # ═════════════════════════════════════════════════════════════════════
    async def acquitter_alerte(
        self, alert_id: UUID, commentaire: str
    ) -> RealtimeAlert:
        alerte = await self._get_alerte(alert_id)
        alerte.statut = StatutAlerte.ACQUITTEE
        alerte.acquittee_par_user_id = self.user_id
        alerte.acquittee_at = datetime.now(timezone.utc)
        alerte.commentaire_acquittement = commentaire
        await self.db.flush()
        return alerte

    async def resoudre_alerte(
        self, alert_id: UUID, resolution: str
    ) -> RealtimeAlert:
        alerte = await self._get_alerte(alert_id)
        alerte.statut = StatutAlerte.RESOLUE
        alerte.resolue_at = datetime.now(timezone.utc)
        alerte.resolution = resolution
        await self.db.flush()
        return alerte

    async def escalader_alerte(
        self, alert_id: UUID, escaladee_a_user_id: UUID, motif: str
    ) -> RealtimeAlert:
        alerte = await self._get_alerte(alert_id)
        alerte.statut = StatutAlerte.ESCALADEE
        alerte.escaladee = True
        alerte.escalade_at = datetime.now(timezone.utc)
        alerte.escaladee_a_user_id = escaladee_a_user_id
        alerte.metadata_ = {**(alerte.metadata_ or {}), "motif_escalade": motif}
        await self.db.flush()
        return alerte

    async def lister_alertes(
        self,
        statut: str | None = None,
        severite: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RealtimeAlert]:
        stmt = select(RealtimeAlert).where(RealtimeAlert.tenant_id == self.tenant_id)
        if statut:
            stmt = stmt.where(RealtimeAlert.statut == statut)
        if severite:
            stmt = stmt.where(RealtimeAlert.severite == severite)
        stmt = stmt.order_by(desc(RealtimeAlert.created_at)).limit(limit).offset(offset)
        return list((await self.db.execute(stmt)).scalars().all())

    # ═════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═════════════════════════════════════════════════════════════════════
    async def _get_rule(self, rule_id: UUID) -> AlertRule:
        r = await self.db.scalar(
            select(AlertRule).where(
                AlertRule.id == rule_id,
                AlertRule.tenant_id == self.tenant_id,
            )
        )
        if r is None:
            raise HTTPException(404, "Règle introuvable")
        return r

    async def _get_alerte(self, alert_id: UUID) -> RealtimeAlert:
        a = await self.db.scalar(
            select(RealtimeAlert).where(
                RealtimeAlert.id == alert_id,
                RealtimeAlert.tenant_id == self.tenant_id,
            )
        )
        if a is None:
            raise HTTPException(404, "Alerte introuvable")
        return a

    @staticmethod
    def _matcher_filtre(filtre: dict[str, Any], payload: dict[str, Any]) -> bool:
        """Match simple : {field: expected_value}."""
        for key, expected in filtre.items():
            actual = payload.get(key)
            if actual != expected:
                return False
        return True

    @staticmethod
    def _extraire_valeur(payload: dict[str, Any], field: str) -> Any:
        """Extrait une valeur d'un payload (supporte nested avec .)."""
        if "." in field:
            parts = field.split(".")
            v = payload
            for p in parts:
                v = v.get(p) if isinstance(v, dict) else None
                if v is None:
                    return None
            return v
        return payload.get(field)

    @staticmethod
    def _comparer(a: Any, operator: str, b: Any) -> bool:
        if a is None:
            return False
        try:
            if operator == ">":   return a > b
            if operator == ">=":  return a >= b
            if operator == "<":   return a < b
            if operator == "<=":  return a <= b
            if operator == "==":  return a == b
            if operator == "!=":  return a != b
        except TypeError:
            return False
        return False
