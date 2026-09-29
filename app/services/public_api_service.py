"""
Service API publique — Gestion des clients, clés, rate limiting, usage.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api_syscohada import (
    AuthMethod,
    EnvironnementAPI,
    RateLimits,
    Scope,
    StatutCleAPI,
    TOUS_SCOPES,
    TypeClientAPI,
    TYPES_CLIENT_API,
)
from app.models.public_api import (
    ApiClient,
    ApiKey,
    ApiUsageAggregate,
    ApiUsageLog,
    IdempotencyKey,
)
from app.schemas.public_api import (
    ApiClientCreate,
    ApiClientUpdate,
    ApiKeyCreate,
    ApiKeyRotateIn,
)
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


# Longueurs
KEY_LENGTH = 32
PREFIX_LIVE = "mtech_live_"
PREFIX_TEST = "mtech_test_"


class PublicApiService:
    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID | None = None) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.audit = AuditService(db)

    # ═════════════════════════════════════════════════════════════════════
    # CLIENTS API
    # ═════════════════════════════════════════════════════════════════════
    async def creer_client(self, data: ApiClientCreate) -> ApiClient:
        # Validation type
        if data.type_client not in TYPES_CLIENT_API:
            raise HTTPException(400, f"Type de client invalide : {data.type_client}")

        # Unicité
        existing = await self.db.scalar(
            select(ApiClient.id).where(
                ApiClient.tenant_id == self.tenant_id,
                ApiClient.code == data.code,
            )
        )
        if existing:
            raise HTTPException(409, f"Client API {data.code} existe déjà")

        client = ApiClient(
            tenant_id=self.tenant_id,
            **data.model_dump(),
            created_by_user_id=self.user_id,
        )
        self.db.add(client)
        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="API_CLIENT_CREATE",
            ressource="api_client",
            ressource_id=client.id,
            payload={"code": client.code, "type": client.type_client},
        )
        return client

    async def modifier_client(
        self, client_id: UUID, data: ApiClientUpdate
    ) -> ApiClient:
        client = await self._get_client(client_id)
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(client, k, v)
        await self.db.flush()
        return client

    async def lister_clients(self, actif_only: bool = True) -> list[ApiClient]:
        stmt = select(ApiClient).where(ApiClient.tenant_id == self.tenant_id)
        if actif_only:
            stmt = stmt.where(ApiClient.actif.is_(True))
        stmt = stmt.order_by(ApiClient.code)
        return list((await self.db.execute(stmt)).scalars().all())

    # ═════════════════════════════════════════════════════════════════════
    # CLÉS API
    # ═════════════════════════════════════════════════════════════════════
    async def creer_cle(
        self, client_id: UUID, data: ApiKeyCreate
    ) -> tuple[ApiKey, str]:
        """
        Crée une nouvelle clé API.
        Retourne (clé, clé_en_clair).
        ⚠️ La clé en clair n'est affichée qu'UNE fois.
        """
        client = await self._get_client(client_id)

        # Valider scopes
        for s in data.scopes:
            if s not in TOUS_SCOPES:
                raise HTTPException(400, f"Scope invalide : {s}")

        # Environnement
        env = data.environnement or client.environnement
        prefix_base = PREFIX_TEST if env == EnvironnementAPI.SANDBOX else PREFIX_LIVE

        # Générer la clé
        random_part = secrets.token_urlsafe(KEY_LENGTH)
        key_plain = f"{prefix_base}{random_part}"
        key_hash = hashlib.sha256(key_plain.encode()).hexdigest()
        prefix_affichage = f"{prefix_base}{random_part[:8]}"

        # Créer l'enregistrement
        api_key = ApiKey(
            tenant_id=self.tenant_id,
            api_client_id=client.id,
            prefix=prefix_affichage,
            nom=data.nom,
            key_hash=key_hash,
            scopes=data.scopes,
            environnement=env,
            statut=StatutCleAPI.ACTIVE,
            expire_at=data.expire_at,
            created_by_user_id=self.user_id,
        )
        self.db.add(api_key)
        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="API_KEY_CREATE",
            ressource="api_key",
            ressource_id=api_key.id,
            payload={
                "prefix": api_key.prefix,
                "client_id": str(client.id),
                "scopes": data.scopes,
            },
        )

        return api_key, key_plain

    async def valider_cle(
        self, key_plain: str, ip: str | None = None
    ) -> tuple[ApiKey, ApiClient]:
        """
        Valide une clé API et retourne (clé, client).
        Lève 401 si invalide, 403 si suspendue/expirée.
        """
        key_hash = hashlib.sha256(key_plain.encode()).hexdigest()

        api_key = await self.db.scalar(
            select(ApiKey).where(ApiKey.key_hash == key_hash)
        )
        if api_key is None:
            raise HTTPException(401, "Clé API invalide")

        # Vérifier statut
        if api_key.statut == StatutCleAPI.REVOQUEE:
            raise HTTPException(403, "Clé API révoquée")
        if api_key.statut == StatutCleAPI.SUSPENDUE:
            raise HTTPException(403, "Clé API suspendue")
        if api_key.statut == StatutCleAPI.EXPIREE:
            raise HTTPException(403, "Clé API expirée")

        # Vérifier expiration
        if api_key.expire_at and api_key.expire_at < datetime.now(timezone.utc):
            api_key.statut = StatutCleAPI.EXPIREE
            await self.db.flush()
            raise HTTPException(403, "Clé API expirée")

        # Récupérer le client
        client = await self.db.scalar(
            select(ApiClient).where(ApiClient.id == api_key.api_client_id)
        )
        if client is None or not client.actif:
            raise HTTPException(403, "Client API inactif")

        # Vérifier IP whitelist
        if client.ip_whitelist and ip:
            if ip not in client.ip_whitelist:
                raise HTTPException(403, f"IP non autorisée : {ip}")

        # Mettre à jour l'usage
        api_key.derniere_utilisation_at = datetime.now(timezone.utc)
        api_key.derniere_utilisation_ip = ip
        api_key.nb_requetes_total += 1
        await self.db.flush()

        return api_key, client

    async def revoquer_cle(
        self, key_id: UUID, motif: str
    ) -> ApiKey:
        key = await self._get_key(key_id)
        key.statut = StatutCleAPI.REVOQUEE
        key.revoquee_at = datetime.now(timezone.utc)
        key.motif_revocation = motif
        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="API_KEY_REVOKE",
            ressource="api_key",
            ressource_id=key.id,
            payload={"motif": motif, "prefix": key.prefix},
        )
        return key

    async def suspendre_cle(self, key_id: UUID, motif: str) -> ApiKey:
        key = await self._get_key(key_id)
        key.statut = StatutCleAPI.SUSPENDUE
        await self.db.flush()
        return key

    async def reactiver_cle(self, key_id: UUID) -> ApiKey:
        key = await self._get_key(key_id)
        if key.statut != StatutCleAPI.SUSPENDUE:
            raise HTTPException(400, "Seule une clé suspendue peut être réactivée")
        if key.expire_at and key.expire_at < datetime.now(timezone.utc):
            raise HTTPException(400, "Clé expirée, impossible de réactiver")
        key.statut = StatutCleAPI.ACTIVE
        await self.db.flush()
        return key

    async def roter_cle(
        self, key_id: UUID, data: ApiKeyRotateIn
    ) -> tuple[ApiKey, ApiKey, str]:
        """
        Rotation de clé : crée une nouvelle clé et planifie l'expiration de l'ancienne.
        Retourne (nouvelle_clé, ancienne_clé, clé_en_clair).
        """
        ancienne = await self._get_key(key_id)

        # Créer la nouvelle
        nouvelle_data = ApiKeyCreate(
            nom=f"{ancienne.nom} (rotation)",
            scopes=ancienne.scopes,
            expire_at=data.expire_at,
            environnement=ancienne.environnement,
        )
        nouvelle, key_plain = await self.creer_cle(
            ancienne.api_client_id, nouvelle_data
        )

        # Programmer l'expiration de l'ancienne
        grace_expire = datetime.now(timezone.utc) + timedelta(hours=data.grace_period_hours)
        ancienne.expire_at = grace_expire
        ancienne.remplacee_par_cle_id = nouvelle.id
        nouvelle.remplace_cle_id = ancienne.id

        await self.db.flush()
        return nouvelle, ancienne, key_plain

    async def lister_cles(
        self, client_id: UUID | None = None, statut: str | None = None
    ) -> list[ApiKey]:
        stmt = select(ApiKey).where(ApiKey.tenant_id == self.tenant_id)
        if client_id:
            stmt = stmt.where(ApiKey.api_client_id == client_id)
        if statut:
            stmt = stmt.where(ApiKey.statut == statut)
        stmt = stmt.order_by(desc(ApiKey.created_at))
        return list((await self.db.execute(stmt)).scalars().all())

    # ═════════════════════════════════════════════════════════════════════
    # VÉRIFICATION DES SCOPES
    # ═════════════════════════════════════════════════════════════════════
    @staticmethod
    def verifier_scope(api_key: ApiKey, scope_requis: str) -> None:
        """Vérifie qu'une clé possède un scope. Lève 403 sinon."""
        if scope_requis not in api_key.scopes:
            raise HTTPException(
                403,
                f"Scope insuffisant : {scope_requis} requis",
            )

    # ═════════════════════════════════════════════════════════════════════
    # RATE LIMITING
    # ═════════════════════════════════════════════════════════════════════
    async def verifier_rate_limit(
        self, client: ApiClient, api_key: ApiKey | None = None
    ) -> None:
        """
        Vérifie le rate limit par minute pour un client.
        Lève 429 si dépassé.
        """
        # Limite du client ou défaut selon le type
        limite = client.rate_limit_per_minute or self._limite_par_type(client.type_client)

        # Période courante (arrondie à la minute)
        now = datetime.now(timezone.utc)
        periode = now.strftime("%Y-%m-%dT%H:%M")

        # Compter les requêtes de la minute
        count = int(await self.db.scalar(
            select(func.count(ApiUsageLog.id)).where(
                ApiUsageLog.api_client_id == client.id,
                ApiUsageLog.created_at >= now.replace(second=0, microsecond=0),
            )
        ) or 0)

        if count >= limite:
            # Log le rate limit
            await self._log_usage(
                api_client_id=client.id,
                api_key_id=api_key.id if api_key else None,
                methode="RATE_LIMIT",
                endpoint="/rate-limited",
                statut_http=429,
                error_code="rate_limit_exceeded",
            )
            raise HTTPException(
                429,
                f"Rate limit dépassé : {limite} requêtes/minute",
                headers={
                    "X-RateLimit-Limit": str(limite),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int((now + timedelta(minutes=1)).timestamp())),
                },
            )

    @staticmethod
    def _limite_par_type(type_client: str) -> int:
        return {
            TypeClientAPI.PARTENAIRE: RateLimits.PARTENAIRE_PER_MINUTE,
            TypeClientAPI.EXPERT_COMPTABLE: RateLimits.EXPERT_COMPTABLE_PER_MINUTE,
            TypeClientAPI.DEVELOPPEUR: RateLimits.DEVELOPPEUR_PER_MINUTE,
            TypeClientAPI.INTEGRATION_INTERNE: RateLimits.INTEGRATION_INTERNE_PER_MINUTE,
            TypeClientAPI.AUDITEUR: RateLimits.AUDITEUR_PER_MINUTE,
        }.get(type_client, RateLimits.DEFAULT_PER_MINUTE)

    # ═════════════════════════════════════════════════════════════════════
    # LOGS D'USAGE
    # ═════════════════════════════════════════════════════════════════════
    async def _log_usage(
        self,
        api_client_id: UUID,
        api_key_id: UUID | None,
        methode: str,
        endpoint: str,
        statut_http: int,
        error_code: str | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
        latence_ms: int | None = None,
        scopes_requis: list[str] | None = None,
        idempotency_key: str | None = None,
    ) -> ApiUsageLog:
        log = ApiUsageLog(
            tenant_id=self.tenant_id,
            api_client_id=api_client_id,
            api_key_id=api_key_id,
            methode=methode,
            endpoint=endpoint,
            statut_http=statut_http,
            error_code=error_code,
            ip=ip,
            user_agent=user_agent,
            request_id=request_id,
            latence_ms=latence_ms,
            scopes_requis=scopes_requis,
            idempotency_key=idempotency_key,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(log)
        await self.db.flush()
        return log

    async def log_usage_publique(
        self,
        api_client_id: UUID,
        api_key_id: UUID | None,
        methode: str,
        endpoint: str,
        statut_http: int,
        **kwargs,
    ) -> ApiUsageLog:
        """Version publique pour l'API middleware."""
        return await self._log_usage(
            api_client_id=api_client_id,
            api_key_id=api_key_id,
            methode=methode,
            endpoint=endpoint,
            statut_http=statut_http,
            **kwargs,
        )

    async def lister_logs(
        self,
        client_id: UUID | None = None,
        statut_http: int | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[ApiUsageLog]:
        stmt = select(ApiUsageLog).where(ApiUsageLog.tenant_id == self.tenant_id)
        if client_id:
            stmt = stmt.where(ApiUsageLog.api_client_id == client_id)
        if statut_http:
            stmt = stmt.where(ApiUsageLog.statut_http == statut_http)
        stmt = stmt.order_by(desc(ApiUsageLog.created_at)).limit(limit).offset(offset)
        return list((await self.db.execute(stmt)).scalars().all())

    # ═════════════════════════════════════════════════════════════════════
    # STATISTIQUES D'USAGE
    # ═════════════════════════════════════════════════════════════════════
    async def stats_usage(
        self, client_id: UUID, debut: datetime, fin: datetime
    ) -> dict[str, Any]:
        # Compteurs
        total = int(await self.db.scalar(
            select(func.count(ApiUsageLog.id)).where(
                ApiUsageLog.api_client_id == client_id,
                ApiUsageLog.created_at.between(debut, fin),
            )
        ) or 0)

        succes = int(await self.db.scalar(
            select(func.count(ApiUsageLog.id)).where(
                ApiUsageLog.api_client_id == client_id,
                ApiUsageLog.created_at.between(debut, fin),
                ApiUsageLog.statut_http.between(200, 299),
            )
        ) or 0)

        err_4xx = int(await self.db.scalar(
            select(func.count(ApiUsageLog.id)).where(
                ApiUsageLog.api_client_id == client_id,
                ApiUsageLog.created_at.between(debut, fin),
                ApiUsageLog.statut_http.between(400, 499),
            )
        ) or 0)

        err_5xx = int(await self.db.scalar(
            select(func.count(ApiUsageLog.id)).where(
                ApiUsageLog.api_client_id == client_id,
                ApiUsageLog.created_at.between(debut, fin),
                ApiUsageLog.statut_http.between(500, 599),
            )
        ) or 0)

        rate_limited = int(await self.db.scalar(
            select(func.count(ApiUsageLog.id)).where(
                ApiUsageLog.api_client_id == client_id,
                ApiUsageLog.created_at.between(debut, fin),
                ApiUsageLog.statut_http == 429,
            )
        ) or 0)

        # Latences
        latence_moy = await self.db.scalar(
            select(func.avg(ApiUsageLog.latence_ms)).where(
                ApiUsageLog.api_client_id == client_id,
                ApiUsageLog.created_at.between(debut, fin),
                ApiUsageLog.latence_ms.isnot(None),
            )
        )

        # Top endpoints
        rows = (
            await self.db.execute(
                select(
                    ApiUsageLog.endpoint,
                    func.count(ApiUsageLog.id).label("n"),
                )
                .where(
                    ApiUsageLog.api_client_id == client_id,
                    ApiUsageLog.created_at.between(debut, fin),
                )
                .group_by(ApiUsageLog.endpoint)
                .order_by(desc("n"))
                .limit(10)
            )
        ).all()
        top_endpoints = [{"endpoint": r[0], "count": int(r[1])} for r in rows]

        # Répartition par statut
        rows2 = (
            await self.db.execute(
                select(
                    ApiUsageLog.statut_http,
                    func.count(ApiUsageLog.id),
                )
                .where(
                    ApiUsageLog.api_client_id == client_id,
                    ApiUsageLog.created_at.between(debut, fin),
                )
                .group_by(ApiUsageLog.statut_http)
            )
        ).all()
        repartition = {str(r[0]): int(r[1]) for r in rows2}

        return {
            "api_client_id": client_id,
            "periode_debut": debut,
            "periode_fin": fin,
            "nb_requetes": total,
            "nb_succes": succes,
            "nb_erreurs_4xx": err_4xx,
            "nb_erreurs_5xx": err_5xx,
            "nb_rate_limited": rate_limited,
            "taux_succes_pct": round(succes / total * 100, 2) if total else 0.0,
            "latence_moyenne_ms": round(float(latence_moy or 0), 2),
            "latence_p95_ms": 0.0,   # À calculer via percentile SQL
            "top_endpoints": top_endpoints,
            "repartition_par_statut": repartition,
        }

    # ═════════════════════════════════════════════════════════════════════
    # IDEMPOTENCE
    # ═════════════════════════════════════════════════════════════════════
    async def get_idempotent_response(
        self, api_client_id: UUID, key: str
    ) -> dict[str, Any] | None:
        """Récupère une réponse mise en cache pour une clé d'idempotence."""
        row = await self.db.scalar(
            select(IdempotencyKey).where(
                IdempotencyKey.api_client_id == api_client_id,
                IdempotencyKey.key == key,
                IdempotencyKey.expire_at > datetime.now(timezone.utc),
            )
        )
        if row is None:
            return None
        return {
            "status": row.response_status,
            "body": row.response_body,
        }

    async def save_idempotent_response(
        self,
        api_client_id: UUID,
        key: str,
        endpoint: str,
        status: int,
        body: dict[str, Any],
        ttl_hours: int = 24,
    ) -> IdempotencyKey:
        row = IdempotencyKey(
            tenant_id=self.tenant_id,
            api_client_id=api_client_id,
            key=key,
            endpoint=endpoint,
            response_status=status,
            response_body=body,
            expire_at=datetime.now(timezone.utc) + timedelta(hours=ttl_hours),
        )
        self.db.add(row)
        await self.db.flush()
        return row

    # ═════════════════════════════════════════════════════════════════════
    # CATALOGUE
    # ═════════════════════════════════════════════════════════════════════
    @staticmethod
    def catalogue_scopes() -> list[dict[str, str]]:
        """Retourne la liste de tous les scopes disponibles."""
        descriptions = {
            Scope.READ_ECRITURES: ("Lire les écritures comptables", "read"),
            Scope.READ_CLIENTS: ("Lire la liste des clients", "read"),
            Scope.READ_FOURNISSEURS: ("Lire la liste des fournisseurs", "read"),
            Scope.READ_FACTURES_CLIENTS: ("Lire les factures clients", "read"),
            Scope.READ_FACTURES_FOURNISSEURS: ("Lire les factures fournisseurs", "read"),
            Scope.READ_TRESORERIE: ("Lire les comptes de trésorerie", "read"),
            Scope.READ_STOCKS: ("Lire les stocks", "read"),
            Scope.READ_IMMOBILISATIONS: ("Lire les immobilisations", "read"),
            Scope.READ_PROJETS: ("Lire les projets", "read"),
            Scope.READ_EMPLOYES: ("Lire les employés", "read"),
            Scope.READ_PAIE: ("Lire les bulletins de paie", "read"),
            Scope.READ_BUDGETS: ("Lire les budgets", "read"),
            Scope.READ_FNE: ("Lire les factures FNE", "read"),
            Scope.READ_AUDIT: ("Lire les anomalies d'audit", "read"),
            Scope.READ_RAPPORTS: ("Lire les rapports", "read"),
            Scope.READ_ANALYTIQUE: ("Lire les données analytiques", "read"),
            Scope.WRITE_ECRITURES: ("Créer/modifier des écritures", "write"),
            Scope.WRITE_CLIENTS: ("Créer/modifier des clients", "write"),
            Scope.WRITE_FOURNISSEURS: ("Créer/modifier des fournisseurs", "write"),
            Scope.WRITE_FACTURES_CLIENTS: ("Créer des factures clients", "write"),
            Scope.WRITE_FACTURES_FOURNISSEURS: ("Créer des factures fournisseurs", "write"),
            Scope.WRITE_PAIEMENTS: ("Enregistrer des paiements", "write"),
            Scope.WRITE_STOCKS: ("Créer des mouvements de stock", "write"),
            Scope.WRITE_PROJETS: ("Créer/modifier des projets", "write"),
            Scope.ADMIN_WEBHOOKS: ("Gérer les webhooks", "admin"),
            Scope.ADMIN_API_KEYS: ("Gérer les clés API", "admin"),
            Scope.ADMIN_USERS: ("Gérer les utilisateurs", "admin"),
        }
        return [
            {"scope": s, "description": descriptions.get(s, ("", "read"))[0],
             "categorie": descriptions.get(s, ("", "read"))[1]}
            for s in TOUS_SCOPES
        ]

    # ═════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═════════════════════════════════════════════════════════════════════
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

    async def _get_key(self, key_id: UUID) -> ApiKey:
        k = await self.db.scalar(
            select(ApiKey).where(
                ApiKey.id == key_id,
                ApiKey.tenant_id == self.tenant_id,
            )
        )
        if k is None:
            raise HTTPException(404, "Clé API introuvable")
        return k
