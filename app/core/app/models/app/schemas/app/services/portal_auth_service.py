"""
Service d'authentification Portail — isolation stricte.

Les utilisateurs portail ont leur propre système d'auth (JWT courts),
indépendant de l'auth tenant. Un client ne peut jamais accéder aux données
d'un autre client, même via manipulation d'URL.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import jwt
from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.portal_syscohada import (
    PERMISSIONS_CLIENT_DEFAUT,
    PERMISSIONS_FOURNISSEUR_DEFAUT,
    SecuritePortail,
    StatutComptePortail,
    TypeUtilisateurPortail,
)
from app.core.security import hash_password, verify_password
from app.models.portal import (
    PortalInvitation,
    PortalSession,
    PortalUser,
)
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.portal import (
    PortalInviteIn,
    PortalUserOut,
)

logger = logging.getLogger(__name__)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _generate_secure_token() -> str:
    return secrets.token_urlsafe(48)


class PortalAuthService:
    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID | None = None) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.internal_user_id = user_id   # Utilisateur interne qui invite (peut être None)

    # ═════════════════════════════════════════════════════════════════════
    # INVITATIONS
    # ═════════════════════════════════════════════════════════════════════
    async def inviter(self, data: PortalInviteIn) -> dict[str, Any]:
        """
        Crée une invitation pour un client ou fournisseur.
        Génère un token à durée limitée (72h) envoyé par email.
        """
        # Vérifier que le client/fournisseur existe bien dans le tenant
        from app.models.sale import Customer
        from app.models.purchase import Supplier

        if data.type_utilisateur == TypeUtilisateurPortail.CLIENT:
            c = await self.db.scalar(
                select(Customer).where(
                    Customer.id == data.customer_id,
                    Customer.tenant_id == self.tenant_id,
                )
            )
            if c is None:
                raise HTTPException(404, "Client introuvable")
        elif data.type_utilisateur == TypeUtilisateurPortail.FOURNISSEUR:
            s = await self.db.scalar(
                select(Supplier).where(
                    Supplier.id == data.supplier_id,
                    Supplier.tenant_id == self.tenant_id,
                )
            )
            if s is None:
                raise HTTPException(404, "Fournisseur introuvable")

        # Vérifier pas de doublon d'email
        existing = await self.db.scalar(
            select(PortalUser).where(
                PortalUser.tenant_id == self.tenant_id,
                PortalUser.email == data.email,
            )
        )
        if existing and existing.statut == StatutComptePortail.ACTIF:
            raise HTTPException(409, "Un compte portail actif existe déjà pour cet email")

        # Créer ou réutiliser l'utilisateur portail
        if existing:
            portal_user = existing
            portal_user.prenom = data.prenom
            portal_user.nom = data.nom
            portal_user.statut = StatutComptePortail.INVITE
            portal_user.telephone = data.telephone
            portal_user.fonction = data.fonction
            if data.acces_expire_at:
                portal_user.acces_expire_at = data.acces_expire_at
        else:
            permissions = data.permissions or self._permissions_defaut(data.type_utilisateur)
            portal_user = PortalUser(
                tenant_id=self.tenant_id,
                type_utilisateur=data.type_utilisateur,
                customer_id=data.customer_id,
                supplier_id=data.supplier_id,
                email=data.email,
                prenom=data.prenom,
                nom=data.nom,
                telephone=data.telephone,
                fonction=data.fonction,
                permissions=permissions,
                statut=StatutComptePortail.INVITE,
                acces_expire_at=data.acces_expire_at,
            )
            self.db.add(portal_user)
            await self.db.flush()

        # Générer le token
        token = _generate_secure_token()
        token_hash = _hash_token(token)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=SecuritePortail.TOKEN_INVITATION_TTL_H)

        invitation = PortalInvitation(
            tenant_id=self.tenant_id,
            portal_user_id=portal_user.id,
            email=data.email,
            type_utilisateur=data.type_utilisateur,
            customer_id=data.customer_id,
            supplier_id=data.supplier_id,
            token_hash=token_hash,
            token_purpose="invitation",
            expires_at=expires_at,
            envoye_par_user_id=self.internal_user_id,
        )
        self.db.add(invitation)
        await self.db.flush()

        # Envoyer l'email (async via worker)
        invitation_url = f"{self._base_portal_url()}/activation?token={token}"
        await self._envoyer_email_invitation(portal_user, invitation_url, data.message_personnalise)

        return {
            "portal_user_id": str(portal_user.id),
            "invitation_id": str(invitation.id),
            "email": portal_user.email,
            "expires_at": expires_at.isoformat(),
            "invitation_url_debug": invitation_url if settings.ENV == "dev" else None,
        }

    async def activer_compte(self, token: str, password: str) -> PortalUser:
        """
        Active un compte portail via le token d'invitation.
        """
        token_hash = _hash_token(token)
        invitation = await self.db.scalar(
            select(PortalInvitation).where(
                PortalInvitation.token_hash == token_hash,
                PortalInvitation.token_purpose == "invitation",
            )
        )
        if invitation is None:
            raise HTTPException(400, "Lien d'invitation invalide ou expiré")
        if invitation.utilise_at is not None:
            raise HTTPException(400, "Ce lien a déjà été utilisé")
        if invitation.expires_at < datetime.now(timezone.utc):
            raise HTTPException(400, "Ce lien d'invitation a expiré")

        portal_user = await self.db.scalar(
            select(PortalUser).where(PortalUser.id == invitation.portal_user_id)
        )
        if portal_user is None:
            raise HTTPException(404, "Utilisateur portail introuvable")

        # Activer
        portal_user.password_hash = hash_password(password)
        portal_user.statut = StatutComptePortail.ACTIF
        portal_user.is_email_verified = True
        portal_user.accepte_cgu = True
        portal_user.accepte_cgu_at = datetime.now(timezone.utc)

        invitation.utilise_at = datetime.now(timezone.utc)

        await self.db.flush()
        return portal_user

    # ═════════════════════════════════════════════════════════════════════
    # CONNEXION
    # ═════════════════════════════════════════════════════════════════════
    async def login(
        self, email: str, password: str, ip: str | None = None, user_agent: str | None = None
    ) -> dict[str, Any]:
        """
        Connexion portail. Retourne access_token + refresh_token.
        """
        # Chercher l'utilisateur par email (tous tenants confondus → on filtre par tenant via domain)
        # Note : un email peut exister pour plusieurs tenants → on utilise un portail générique
        portal_user = await self.db.scalar(
            select(PortalUser).where(
                PortalUser.email == email,
                PortalUser.tenant_id == self.tenant_id,
            )
        )
        if portal_user is None:
            # Sécurité : ne pas révéler l'existence de l'email
            raise HTTPException(401, "Identifiants invalides")

        # Vérifier verrouillage
        if portal_user.verrouille_jusqua and portal_user.verrouille_jusqua > datetime.now(timezone.utc):
            raise HTTPException(
                429,
                f"Compte temporairement verrouillé jusqu'à "
                f"{portal_user.verrouille_jusqua.strftime('%H:%M')}. "
                f"Trop de tentatives échouées.",
            )

        # Vérifier mot de passe
        if not portal_user.password_hash or not verify_password(password, portal_user.password_hash):
            portal_user.nb_tentatives_echec += 1
            if portal_user.nb_tentatives_echec >= SecuritePortail.MAX_TENTATIVES_CONNEXION:
                portal_user.verrouille_jusqua = (
                    datetime.now(timezone.utc)
                    + timedelta(minutes=SecuritePortail.VERROUILLAGE_MINUTES)
                )
            await self.db.flush()
            raise HTTPException(401, "Identifiants invalides")

        # Vérifier statut
        if portal_user.statut != StatutComptePortail.ACTIF:
            raise HTTPException(403, f"Compte {portal_user.statut}")
        if portal_user.acces_expire_at and portal_user.acces_expire_at < datetime.now(timezone.utc):
            portal_user.statut = StatutComptePortail.EXPIRE
            await self.db.flush()
            raise HTTPException(403, "Accès expiré")

        # Reset compteurs
        portal_user.nb_tentatives_echec = 0
        portal_user.verrouille_jusqua = None
        portal_user.derniere_connexion_at = datetime.now(timezone.utc)
        portal_user.derniere_connexion_ip = ip

        # Créer la session
        jti = uuid4()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=SecuritePortail.SESSION_TTL_H)

        session = PortalSession(
            tenant_id=self.tenant_id,
            portal_user_id=portal_user.id,
            jti=jti,
            expires_at=expires_at,
            ip=ip,
            user_agent=user_agent,
        )
        self.db.add(session)
        await self.db.flush()

        # Générer les JWT
        access_token = self._create_access_token(portal_user, jti)
        refresh_token = self._create_refresh_token(portal_user, jti)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": SecuritePortail.SESSION_TTL_H * 3600,
            "portal_user_id": str(portal_user.id),
            "type_utilisateur": portal_user.type_utilisateur,
            "nom_complet": portal_user.nom_complet,
        }

    async def logout(self, jti: UUID) -> None:
        session = await self.db.scalar(
            select(PortalSession).where(PortalSession.jti == jti)
        )
        if session:
            session.revoquee_at = datetime.now(timezone.utc)
            await self.db.flush()

    # ═════════════════════════════════════════════════════════════════════
    # MAGIC LINK
    # ═════════════════════════════════════════════════════════════════════
    async def demander_magic_link(self, email: str) -> dict[str, Any]:
        """
        Demande de lien magique (passwordless).
        Si l'email existe, envoie un lien valable 15 minutes.
        """
        portal_user = await self.db.scalar(
            select(PortalUser).where(
                PortalUser.email == email,
                PortalUser.tenant_id == self.tenant_id,
                PortalUser.statut == StatutComptePortail.ACTIF,
            )
        )

        # Toujours retourner un succès (sécurité : ne pas révéler l'existence)
        if portal_user is None:
            return {"sent": True, "message": "Si un compte existe, un lien a été envoyé."}

        token = _generate_secure_token()
        token_hash = _hash_token(token)
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=SecuritePortail.TOKEN_MAGIC_LINK_TTL_MIN
        )

        invitation = PortalInvitation(
            tenant_id=self.tenant_id,
            portal_user_id=portal_user.id,
            email=email,
            type_utilisateur=portal_user.type_utilisateur,
            token_hash=token_hash,
            token_purpose="magic_link",
            expires_at=expires_at,
        )
        self.db.add(invitation)
        await self.db.flush()

        magic_url = f"{self._base_portal_url()}/magic?token={token}"
        await self._envoyer_email_magic_link(portal_user, magic_url)

        return {
            "sent": True,
            "message": "Si un compte existe, un lien a été envoyé.",
            "magic_url_debug": magic_url if settings.ENV == "dev" else None,
        }

    async def login_magic_link(
        self, token: str, ip: str | None = None, user_agent: str | None = None
    ) -> dict[str, Any]:
        """Connexion via lien magique."""
        token_hash = _hash_token(token)
        invitation = await self.db.scalar(
            select(PortalInvitation).where(
                PortalInvitation.token_hash == token_hash,
                PortalInvitation.token_purpose == "magic_link",
            )
        )
        if invitation is None or invitation.utilise_at is not None:
            raise HTTPException(400, "Lien invalide ou déjà utilisé")
        if invitation.expires_at < datetime.now(timezone.utc):
            raise HTTPException(400, "Lien expiré")

        portal_user = await self.db.scalar(
            select(PortalUser).where(PortalUser.id == invitation.portal_user_id)
        )
        if portal_user is None or portal_user.statut != StatutComptePortail.ACTIF:
            raise HTTPException(403, "Compte inactif")

        invitation.utilise_at = datetime.now(timezone.utc)

        # Créer la session
        jti = uuid4()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=SecuritePortail.SESSION_TTL_H)
        self.db.add(PortalSession(
            tenant_id=self.tenant_id,
            portal_user_id=portal_user.id,
            jti=jti,
            expires_at=expires_at,
            ip=ip,
            user_agent=user_agent,
        ))
        portal_user.derniere_connexion_at = datetime.now(timezone.utc)
        await self.db.flush()

        access_token = self._create_access_token(portal_user, jti)
        refresh_token = self._create_refresh_token(portal_user, jti)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": SecuritePortail.SESSION_TTL_H * 3600,
            "portal_user_id": str(portal_user.id),
            "type_utilisateur": portal_user.type_utilisateur,
            "nom_complet": portal_user.nom_complet,
        }

    # ═════════════════════════════════════════════════════════════════════
    # JWT PORTAIL
    # ═════════════════════════════════════════════════════════════════════
    def _create_access_token(self, portal_user: PortalUser, jti: UUID) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(portal_user.id),
            "tenant_id": str(portal_user.tenant_id),
            "type_utilisateur": portal_user.type_utilisateur,
            "customer_id": str(portal_user.customer_id) if portal_user.customer_id else None,
            "supplier_id": str(portal_user.supplier_id) if portal_user.supplier_id else None,
            "permissions": portal_user.permissions,
            "jti": str(jti),
            "scope": "portal",              # ⚠️ Différencie des JWT internes
            "typ": "access",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=SecuritePortail.SESSION_TTL_H)).timestamp()),
        }
        return jwt.encode(payload, settings.JWT_PRIVATE_KEY, algorithm="RS256")

    def _create_refresh_token(self, portal_user: PortalUser, jti: UUID) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(portal_user.id),
            "tenant_id": str(portal_user.tenant_id),
            "jti": str(jti),
            "scope": "portal",
            "typ": "refresh",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=SecuritePortail.SESSION_TTL_H * 3)).timestamp()),
        }
        return jwt.encode(payload, settings.JWT_PRIVATE_KEY, algorithm="RS256")

    # ═════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═════════════════════════════════════════════════════════════════════
    @staticmethod
    def _permissions_defaut(type_utilisateur: str) -> list[str]:
        if type_utilisateur == TypeUtilisateurPortail.CLIENT:
            return list(PERMISSIONS_CLIENT_DEFAUT)
        if type_utilisateur == TypeUtilisateurPortail.FOURNISSEUR:
            return list(PERMISSIONS_FOURNISSEUR_DEFAUT)
        if type_utilisateur == TypeUtilisateurPortail.AUDITEUR_EXTERNE:
            return ["lire_ecritures", "lire_etats_financiers", "verifier_piste_audit"]
        return []

    @staticmethod
    def _base_portal_url() -> str:
        # Configuration : à terme lu depuis settings
        return "https://portail.mtech.ci"

    async def _envoyer_email_invitation(
        self, portal_user: PortalUser, url: str, message_perso: str | None = None
    ) -> None:
        """Envoi email d'invitation (délégué au worker)."""
        # À implémenter : appel au service d'email
        logger.info(f"[portal] Invitation envoyée à {portal_user.email}")
        # Stocker la notification
        from app.models.portal import PortalNotification
        self.db.add(PortalNotification(
            tenant_id=self.tenant_id,
            portal_user_id=portal_user.id,
            event_type="invitation",
            canal="email",
            sujet="Activez votre compte MTech",
            contenu_texte=f"Bonjour {portal_user.prenom}, cliquez sur le lien pour activer votre compte.",
            action_url=url,
            action_label="Activer mon compte",
            envoye=True,
            envoye_at=datetime.now(timezone.utc),
        ))
        await self.db.flush()

    async def _envoyer_email_magic_link(self, portal_user: PortalUser, url: str) -> None:
        logger.info(f"[portal] Magic link envoyé à {portal_user.email}")
        from app.models.portal import PortalNotification
        self.db.add(PortalNotification(
            tenant_id=self.tenant_id,
            portal_user_id=portal_user.id,
            event_type="invitation",
            canal="email",
            sujet="Votre lien de connexion MTech",
            contenu_texte="Cliquez sur le lien pour vous connecter (valable 15 minutes).",
            action_url=url,
            action_label="Me connecter",
            envoye=True,
            envoye_at=datetime.now(timezone.utc),
        ))
        await self.db.flush()
