"""
Service Webhooks sortants — dispatcher + livraison + retry.

Signe le payload avec HMAC-SHA256 (comme Stripe).
Retry avec backoff exponentiel.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api_syscohada import (
    WEBHOOK_MAX_BODY_SIZE_KB,
    WEBHOOK_RETRY_DELAYS_S,
    WEBHOOK_SIGNATURE_HEADER,
    WEBHOOK_TIMEOUT_S,
    WEBHOOK_TIMESTAMP_HEADER,
    WEBHOOK_ID_HEADER,
    WEBHOOK_EVENT_HEADER,
    StatutWebhookDelivery,
    TOUS_WEBHOOK_EVENTS,
)
from app.models.public_api import (
    ApiClient,
    WebhookDelivery,
    WebhookEndpoint,
)
from app.schemas.public_api import (
    WebhookEndpointCreate,
    WebhookEndpointUpdate,
    WebhookTestIn,
)
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class WebhookDispatchService:
    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID | None = None) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.audit = AuditService(db)

    # ═════════════════════════════════════════════════════════════════════
    # GESTION DES ENDPOINTS
    # ═════════════════════════════════════════════════════════════════════
    async def creer_endpoint(
        self, client_id: UUID, data: WebhookEndpointCreate
    ) -> tuple[WebhookEndpoint, str]:
        """
        Crée un endpoint webhook.
        Retourne (endpoint, secret_en_clair).
        ⚠️ Le secret n'est affiché qu'une fois.
        """
        # Vérifier client
        client = await self._get_client(client_id)

        # Valider les événements
        for evt in data.events:
            if evt not in TOUS_WEBHOOK_EVENTS:
                raise HTTPException(400, f"Événement invalide : {evt}")

        # Vérifier unicité URL
        existing = await self.db.scalar(
            select(WebhookEndpoint.id).where(
                WebhookEndpoint.api_client_id == client.id,
                WebhookEndpoint.url == str(data.url),
            )
        )
        if existing:
            raise HTTPException(409, "Un endpoint existe déjà pour cette URL")

        # Générer le secret
        secret = secrets.token_urlsafe(32)
        secret_hash = self._hash_secret(secret)

        endpoint = WebhookEndpoint(
            tenant_id=self.tenant_id,
            api_client_id=client.id,
            nom=data.nom,
            description=data.description,
            url=str(data.url),
            secret_enc=secret_hash,   # Simplification : hash, à terme chiffré AES
            events=data.events,
            headers_custom=data.headers_custom,
            actif=True,
            created_by_user_id=self.user_id,
        )
        self.db.add(endpoint)
        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="WEBHOOK_ENDPOINT_CREATE",
            ressource="webhook_endpoint",
            ressource_id=endpoint.id,
            payload={"nom": endpoint.nom, "url": endpoint.url, "events": endpoint.events},
        )

        return endpoint, secret

    async def modifier_endpoint(
        self, endpoint_id: UUID, data: WebhookEndpointUpdate
    ) -> WebhookEndpoint:
        ep = await self._get_endpoint(endpoint_id)
        for k, v in data.model_dump(exclude_unset=True).items():
            if k == "url" and v is not None:
                setattr(ep, k, str(v))
            else:
                setattr(ep, k, v)
        await self.db.flush()
        return ep

    async def lister_endpoints(
        self, client_id: UUID | None = None, actif_only: bool = True
    ) -> list[WebhookEndpoint]:
        stmt = select(WebhookEndpoint).where(WebhookEndpoint.tenant_id == self.tenant_id)
        if client_id:
            stmt = stmt.where(WebhookEndpoint.api_client_id == client_id)
        if actif_only:
            stmt = stmt.where(WebhookEndpoint.actif.is_(True))
        stmt = stmt.order_by(desc(WebhookEndpoint.created_at))
        return list((await self.db.execute(stmt)).scalars().all())

    async def regenerer_secret(self, endpoint_id: UUID) -> tuple[WebhookEndpoint, str]:
        ep = await self._get_endpoint(endpoint_id)
        secret = secrets.token_urlsafe(32)
        ep.secret_enc = self._hash_secret(secret)
        await self.db.flush()
        return ep, secret

    async def supprimer_endpoint(self, endpoint_id: UUID) -> None:
        ep = await self._get_endpoint(endpoint_id)
        ep.actif = False
        await self.db.flush()

    # ═════════════════════════════════════════════════════════════════════
    # DISPATCH D'ÉVÉNEMENT
    # ═════════════════════════════════════════════════════════════════════
    async def dispatcher_evenement(
        self,
        event_type: str,
        payload: dict[str, Any],
        source_type: str | None = None,
        source_id: UUID | None = None,
    ) -> list[WebhookDelivery]:
        """
        Dispatch un événement vers tous les endpoints abonnés.
        Retourne les livraisons créées (en file d'attente).
        """
        # Trouver les endpoints abonnés
        endpoints = (
            await self.db.execute(
                select(WebhookEndpoint).where(
                    WebhookEndpoint.tenant_id == self.tenant_id,
                    WebhookEndpoint.actif.is_(True),
                    WebhookEndpoint.events.contains([event_type]),
                )
            )
        ).scalars().all()

        deliveries: list[WebhookDelivery] = []
        now = datetime.now(timezone.utc)

        for endpoint in endpoints:
            # Vérifier circuit breaker
            if endpoint.echecs_consecutifs >= 20:
                logger.warning(
                    f"[webhook] Endpoint {endpoint.id} désactivé auto "
                    f"(20 échecs consécutifs)"
                )
                endpoint.actif = False
                endpoint.desactive_auto_at = now
                continue

            # Créer la livraison
            delivery_id = f"whd_{secrets.token_urlsafe(24)}"
            timestamp = int(now.timestamp())

            # Payload enrichi (id, event, created, data)
            full_payload = {
                "id": delivery_id,
                "event": event_type,
                "created": timestamp,
                "data": payload,
            }

            # Signature HMAC (timestamp + payload)
            # Le secret est dans `secret_enc` (hash simplifié)
            # À terme : déchiffrer le secret, signer avec le secret réel
            secret_hash = endpoint.secret_enc or ""
            signature = self._signer_payload(full_payload, timestamp, secret_hash)

            delivery = WebhookDelivery(
                tenant_id=self.tenant_id,
                endpoint_id=endpoint.id,
                delivery_id=delivery_id,
                event_type=event_type,
                payload=full_payload,
                signature=signature,
                timestamp=timestamp,
                statut=StatutWebhookDelivery.PENDING,
                nb_tentatives=0,
                max_tentatives=len(WEBHOOK_RETRY_DELAYS_S) + 1,
                prochaine_tentative_at=now,
                source_type=source_type,
                source_id=source_id,
            )
            self.db.add(delivery)
            deliveries.append(delivery)

        if deliveries:
            await self.db.flush()
            logger.info(
                f"[webhook] Événement {event_type} dispatché à "
                f"{len(deliveries)} endpoint(s)"
            )

        return deliveries

    # ═════════════════════════════════════════════════════════════════════
    # LIVRAISON EFFECTIVE (appelé par le worker)
    # ═════════════════════════════════════════════════════════════════════
    async def livrer(self, delivery_id: UUID) -> dict[str, Any]:
        """
        Effectue UNE tentative de livraison HTTP.
        """
        delivery = await self.db.scalar(
            select(WebhookDelivery).where(WebhookDelivery.id == delivery_id)
        )
        if delivery is None:
            return {"ok": False, "reason": "not_found"}

        if delivery.statut == StatutWebhookDelivery.SUCCESS:
            return {"ok": True, "already_delivered": True}

        endpoint = await self.db.scalar(
            select(WebhookEndpoint).where(WebhookEndpoint.id == delivery.endpoint_id)
        )
        if endpoint is None or not endpoint.actif:
            delivery.statut = StatutWebhookDelivery.FAILED
            delivery.erreur = "Endpoint introuvable ou inactif"
            await self.db.flush()
            return {"ok": False, "reason": "endpoint_inactive"}

        # Incrémenter le compteur
        delivery.nb_tentatives += 1
        delivery.derniere_tentative_at = datetime.now(timezone.utc)
        if delivery.premiere_tentative_at is None:
            delivery.premiere_tentative_at = delivery.derniere_tentative_at

        # Construire les headers
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "MTech-Webhooks/1.0",
            WEBHOOK_ID_HEADER: delivery.delivery_id,
            WEBHOOK_EVENT_HEADER: delivery.event_type,
            WEBHOOK_TIMESTAMP_HEADER: str(delivery.timestamp),
            WEBHOOK_SIGNATURE_HEADER: f"t={delivery.timestamp},v1={delivery.signature}",
        }
        if endpoint.headers_custom:
            headers.update(endpoint.headers_custom)

        # Sérialiser le payload
        body = json.dumps(delivery.payload, separators=(",", ":"), ensure_ascii=False)
        if len(body.encode("utf-8")) > WEBHOOK_MAX_BODY_SIZE_KB * 1024:
            delivery.statut = StatutWebhookDelivery.FAILED
            delivery.erreur = f"Payload > {WEBHOOK_MAX_BODY_SIZE_KB} Ko"
            await self.db.flush()
            return {"ok": False, "reason": "payload_too_large"}

        # Envoyer HTTP
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT_S) as client:
                r = await client.post(endpoint.url, content=body, headers=headers)
            latence_ms = int((time.monotonic() - start) * 1000)

            delivery.response_status = r.status_code
            delivery.response_body = r.text[:2000]   # Tronqué
            delivery.latence_ms = latence_ms

            if 200 <= r.status_code < 300:
                delivery.statut = StatutWebhookDelivery.SUCCESS
                delivery.reussie_at = datetime.now(timezone.utc)
                endpoint.nb_succes += 1
                endpoint.echecs_consecutifs = 0
                endpoint.derniere_delivery_statut = "success"
                endpoint.dernier_code_http = r.status_code
                endpoint.derniere_delivery_at = datetime.now(timezone.utc)
                endpoint.nb_deliveries_total += 1
                await self.db.flush()
                return {"ok": True, "status": r.status_code, "latence_ms": latence_ms}
            else:
                # Échec HTTP
                return await self._gerer_echec(
                    delivery, endpoint,
                    f"HTTP {r.status_code}: {r.text[:200]}"
                )

        except httpx.TimeoutException:
            return await self._gerer_echec(delivery, endpoint, "Timeout")
        except httpx.ConnectError as exc:
            return await self._gerer_echec(delivery, endpoint, f"Connexion refusée : {exc}")
        except Exception as exc:
            logger.exception(f"[webhook] Erreur livraison {delivery.delivery_id}")
            return await self._gerer_echec(delivery, endpoint, str(exc))

    async def _gerer_echec(
        self, delivery: WebhookDelivery, endpoint: WebhookEndpoint, erreur: str
    ) -> dict[str, Any]:
        """Gère un échec de livraison (retry ou abandon)."""
        delivery.erreur = erreur[:2000]
        endpoint.nb_echecs += 1
        endpoint.echecs_consecutifs += 1
        endpoint.derniere_delivery_statut = "failed"
        endpoint.derniere_delivery_at = datetime.now(timezone.utc)
        endpoint.nb_deliveries_total += 1

        # Retry si possible
        if delivery.nb_tentatives < delivery.max_tentatives:
            delivery.statut = StatutWebhookDelivery.RETRYING
            idx = min(delivery.nb_tentatives - 1, len(WEBHOOK_RETRY_DELAYS_S) - 1)
            delay_s = WEBHOOK_RETRY_DELAYS_S[idx]
            delivery.prochaine_tentative_at = (
                datetime.now(timezone.utc) + timedelta(seconds=delay_s)
            )
            logger.info(
                f"[webhook] Échec {delivery.delivery_id} (tentative {delivery.nb_tentatives}), "
                f"retry dans {delay_s}s"
            )
        else:
            delivery.statut = StatutWebhookDelivery.EXHAUSTED
            delivery.prochaine_tentative_at = None
            logger.warning(
                f"[webhook] {delivery.delivery_id} EXHAUSTED après "
                f"{delivery.nb_tentatives} tentatives"
            )

        await self.db.flush()
        return {"ok": False, "reason": "delivery_failed", "retry_in_s": delay_s if delivery.statut == StatutWebhookDelivery.RETRYING else None}

    # ═════════════════════════════════════════════════════════════════════
    # TEST MANUEL
    # ═════════════════════════════════════════════════════════════════════
    async def tester_endpoint(
        self, endpoint_id: UUID, data: WebhookTestIn
    ) -> dict[str, Any]:
        """Envoie un événement de test à un endpoint."""
        ep = await self._get_endpoint(endpoint_id)

        if data.event_type not in TOUS_WEBHOOK_EVENTS:
            raise HTTPException(400, f"Événement invalide : {data.event_type}")

        payload = data.payload_custom or {
            "test": True,
            "message": "Ceci est un test de webhook MTech",
            "endpoint_id": str(ep.id),
            "event_type": data.event_type,
        }

        # Créer une livraison directe
        now = datetime.now(timezone.utc)
        delivery_id = f"whd_test_{secrets.token_urlsafe(20)}"
        timestamp = int(now.timestamp())
        full_payload = {
            "id": delivery_id,
            "event": data.event_type,
            "created": timestamp,
            "data": payload,
            "test": True,
        }

        signature = self._signer_payload(full_payload, timestamp, ep.secret_enc or "")

        delivery = WebhookDelivery(
            tenant_id=self.tenant_id,
            endpoint_id=ep.id,
            delivery_id=delivery_id,
            event_type=data.event_type,
            payload=full_payload,
            signature=signature,
            timestamp=timestamp,
            statut=StatutWebhookDelivery.PENDING,
            nb_tentatives=0,
            max_tentatives=1,   # Test = 1 seule tentative
            prochaine_tentative_at=now,
            metadata_={"test": True},
        )
        self.db.add(delivery)
        await self.db.flush()

        # Livrer immédiatement
        result = await self.livrer(delivery.id)

        return {
            "delivery_id": delivery_id,
            "statut": delivery.statut,
            "response_status": delivery.response_status,
            "latence_ms": delivery.latence_ms,
            "erreur": delivery.erreur,
        }

    # ═════════════════════════════════════════════════════════════════════
    # STATS
    # ═════════════════════════════════════════════════════════════════════
    async def stats_endpoint(
        self, endpoint_id: UUID, debut: datetime, fin: datetime
    ) -> dict[str, Any]:
        total = int(await self.db.scalar(
            select(func.count(WebhookDelivery.id)).where(
                WebhookDelivery.endpoint_id == endpoint_id,
                WebhookDelivery.created_at.between(debut, fin),
            )
        ) or 0)

        succes = int(await self.db.scalar(
            select(func.count(WebhookDelivery.id)).where(
                WebhookDelivery.endpoint_id == endpoint_id,
                WebhookDelivery.statut == StatutWebhookDelivery.SUCCESS,
                WebhookDelivery.created_at.between(debut, fin),
            )
        ) or 0)

        echecs = int(await self.db.scalar(
            select(func.count(WebhookDelivery.id)).where(
                WebhookDelivery.endpoint_id == endpoint_id,
                WebhookDelivery.statut.in_([
                    StatutWebhookDelivery.FAILED,
                    StatutWebhookDelivery.EXHAUSTED,
                ]),
                WebhookDelivery.created_at.between(debut, fin),
            )
        ) or 0)

        latence_moy = await self.db.scalar(
            select(func.avg(WebhookDelivery.latence_ms)).where(
                WebhookDelivery.endpoint_id == endpoint_id,
                WebhookDelivery.latence_ms.isnot(None),
                WebhookDelivery.created_at.between(debut, fin),
            )
        )

        top_events_rows = (
            await self.db.execute(
                select(
                    WebhookDelivery.event_type,
                    func.count(WebhookDelivery.id).label("n"),
                )
                .where(
                    WebhookDelivery.endpoint_id == endpoint_id,
                    WebhookDelivery.created_at.between(debut, fin),
                )
                .group_by(WebhookDelivery.event_type)
                .order_by(desc("n"))
                .limit(10)
            )
        ).all()

        derniere_erreur = await self.db.scalar(
            select(WebhookDelivery.erreur).where(
                WebhookDelivery.endpoint_id == endpoint_id,
                WebhookDelivery.erreur.isnot(None),
            ).order_by(desc(WebhookDelivery.created_at)).limit(1)
        )

        return {
            "endpoint_id": endpoint_id,
            "periode_debut": debut,
            "periode_fin": fin,
            "nb_deliveries": total,
            "nb_succes": succes,
            "nb_echecs": echecs,
            "taux_succes_pct": round(succes / total * 100, 2) if total else 0.0,
            "latence_moyenne_ms": round(float(latence_moy or 0), 2),
            "top_events": [{"event": r[0], "count": int(r[1])} for r in top_events_rows],
            "derniere_erreur": derniere_erreur,
        }

    # ═════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═════════════════════════════════════════════════════════════════════
    @staticmethod
    def _hash_secret(secret: str) -> str:
        """Hash du secret (simplification MVP — à terme chiffrement AES)."""
        return hashlib.sha256(secret.encode()).hexdigest()

    @staticmethod
    def _signer_payload(
        payload: dict[str, Any], timestamp: int, secret_hash: str
    ) -> str:
        """
        Signature HMAC-SHA256.
        Format : HMAC(secret, "{timestamp}.{body}")
        Inspiré de Stripe.
        """
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        signed = f"{timestamp}.{body}"
        return hmac.new(
            secret_hash.encode(),
            signed.encode(),
            hashlib.sha256,
        ).hexdigest()

    async def _get_endpoint(self, endpoint_id: UUID) -> WebhookEndpoint:
        ep = await self.db.scalar(
            select(WebhookEndpoint).where(
                WebhookEndpoint.id == endpoint_id,
                WebhookEndpoint.tenant_id == self.tenant_id,
            )
        )
        if ep is None:
            raise HTTPException(404, "Endpoint webhook introuvable")
        return ep

    async def _get_client(self, client_id: UUID) -> ApiClient:
        c = await self.db.scalar(
            select(ApiClient).where(
                ApiClient.id == client_id,
                ApiClient.tenant_id == self.tenant_id,
            )
        )
        if c is None:
            raise HTTPException(404, "Client API introuvable")
        return c

    async def lister_deliveries(
        self,
        endpoint_id: UUID | None = None,
        statut: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[WebhookDelivery]:
        stmt = select(WebhookDelivery).where(WebhookDelivery.tenant_id == self.tenant_id)
        if endpoint_id:
            stmt = stmt.where(WebhookDelivery.endpoint_id == endpoint_id)
        if statut:
            stmt = stmt.where(WebhookDelivery.statut == statut)
        stmt = stmt.order_by(desc(WebhookDelivery.created_at)).limit(limit).offset(offset)
        return list((await self.db.execute(stmt)).scalars().all())

    async def rejouer_delivery(self, delivery_id: UUID) -> WebhookDelivery:
        """Rejoue manuellement une livraison échouée."""
        d = await self.db.scalar(
            select(WebhookDelivery).where(
                WebhookDelivery.id == delivery_id,
                WebhookDelivery.tenant_id == self.tenant_id,
            )
        )
        if d is None:
            raise HTTPException(404, "Livraison introuvable")

        d.statut = StatutWebhookDelivery.PENDING
        d.nb_tentatives = 0
        d.prochaine_tentative_at = datetime.now(timezone.utc)
        d.erreur = None
        await self.db.flush()

        await self.livrer(d.id)
        return d
