"""
Service WhatsApp — bot conversationnel de saisie comptable.

Flux utilisateur :
1. L'utilisateur envoie "Bonjour" → bot demande le code de liaison
2. Utilisateur envoie le code → bot valide et lie le numéro
3. Utilisateur envoie une phrase ("Vente 10 sacs à 5000 FCFA à M. Koné")
   → bot appelle NlpService → propose l'écriture en réponse
4. Utilisateur répond "oui" → écriture validée
5. Utilisateur répond "non" → suggestion rejetée
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.whatsapp import get_whatsapp_client
from app.models.enums import UserStatut
from app.models.nlp import NlpSuggestion
from app.models.user import User
from app.models.whatsapp import WhatsAppLink, WhatsAppMessage
from app.schemas.nlp import SuggestionRequest
from app.services.nlp_service import NlpService

logger = logging.getLogger(__name__)


class WhatsAppService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ─────────────────────────────────────────────────────────────────────
    # Liaison de compte
    # ─────────────────────────────────────────────────────────────────────
    async def initier_liaison(self, tenant_id: UUID, user_id: UUID, phone: str) -> WhatsAppLink:
        """Génère un code à 6 chiffres à envoyer au bot WhatsApp."""
        existing = await self.db.scalar(
            select(WhatsAppLink).where(WhatsAppLink.phone_number == phone)
        )
        if existing is not None:
            if existing.tenant_id == tenant_id and existing.verified:
                raise HTTPException(409, "Ce numéro est déjà lié à votre compte")
            raise HTTPException(409, "Ce numéro est lié à un autre compte")

        code = f"{secrets.randbelow(1_000_000):06d}"
        link = WhatsAppLink(
            tenant_id=tenant_id,
            user_id=user_id,
            phone_number=phone,
            verified=False,
            verification_code=code,
            verification_expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        )
        self.db.add(link)
        await self.db.flush()

        # Envoi du code via WhatsApp
        try:
            client = get_whatsapp_client()
            await client.send_text(
                phone,
                f"🔐 Votre code de liaison MTech : *{code}*\n"
                f"Envoyez ce code dans la conversation pour lier votre compte.\n"
                f"Valable 15 minutes.",
            )
        except Exception:
            logger.exception("[whatsapp] Échec envoi code de liaison")

        return link

    # ─────────────────────────────────────────────────────────────────────
    # Traitement des messages entrants
    # ─────────────────────────────────────────────────────────────────────
    async def traiter_message_entrant(
        self,
        phone_from: str,
        contenu: str,
        external_id: str | None = None,
        type_message: str = "text",
        raw_payload: dict | None = None,
    ) -> dict:
        """
        Point d'entrée principal : reçoit un message, dispatch selon le contexte.
        """
        # Persister le message
        msg = WhatsAppMessage(
            direction="in",
            phone_from=phone_from,
            phone_to=settings.WHATSAPP_META_PHONE_ID or settings.WHATSAPP_TWILIO_FROM,
            type_message=type_message,
            contenu=contenu,
            external_id=external_id,
            raw_payload=raw_payload,
        )
        self.db.add(msg)
        await self.db.flush()

        # Chercher la liaison
        link = await self.db.scalar(
            select(WhatsAppLink).where(
                WhatsAppLink.phone_number == phone_from,
                WhatsAppLink.actif.is_(True),
            )
        )

        # ─── Cas 1 : numéro non lié ──────────────────────────────────────
        if link is None or not link.verified:
            return await self._traiter_non_verifie(link, phone_from, contenu)

        # ─── Cas 2 : utilisateur connu ───────────────────────────────────
        link.derniere_activite_at = datetime.now(timezone.utc)

        # Commandes spéciales
        cmd = contenu.strip().lower()
        if cmd in ("aide", "help", "?"):
            await self._repondre(phone_from, self._message_aide())
            return {"action": "help"}
        if cmd in ("bonjour", "salut", "hello", "coucou"):
            await self._repondre(phone_from, self._message_bienvenue(link))
            return {"action": "welcome"}
        if cmd in ("solde", "tresorerie"):
            return await self._repondre_solde(link)
        if cmd in ("prevision", "forecast"):
            return await self._repondre_prevision(link)

        # Sinon : NLP saisie
        return await self._traiter_saisie_nlp(link, contenu, phone_from)

    # ─────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────
    async def _traiter_non_verifie(
        self, link: WhatsAppLink | None, phone_from: str, contenu: str
    ) -> dict:
        """Gère la liaison d'un numéro non vérifié."""
        contenu = contenu.strip()
        # Si le message est un code à 6 chiffres, on vérifie
        if contenu.isdigit() and len(contenu) == 6:
            candidate = await self.db.scalar(
                select(WhatsAppLink).where(
                    WhatsAppLink.phone_number == phone_from,
                    WhatsAppLink.verification_code == contenu,
                    WhatsAppLink.verification_expires_at > datetime.now(timezone.utc),
                )
            )
            if candidate is None:
                await self._repondre(phone_from, "❌ Code invalide ou expiré. Relancez la liaison depuis l'application.")
                return {"action": "verify_failed"}
            candidate.verified = True
            candidate.verification_code = None
            candidate.derniere_activite_at = datetime.now(timezone.utc)
            await self.db.flush()
            await self._repondre(
                phone_from,
                "✅ Votre numéro est maintenant lié à MTech !\n\n" + self._message_aide(),
            )
            return {"action": "verified", "link_id": str(candidate.id)}

        await self._repondre(
            phone_from,
            "👋 Bienvenue sur MTech SYSCOHADA !\n\n"
            "Pour lier votre numéro, ouvrez votre compte sur l'application web, "
            "allez dans *Paramètres → WhatsApp*, et générez un code à 6 chiffres.\n\n"
            "Ensuite, envoyez-moi ce code ici.",
        )
        return {"action": "awaiting_code"}

    async def _traiter_saisie_nlp(
        self, link: WhatsAppLink, contenu: str, phone_from: str
    ) -> dict:
        """Convertit une phrase en écriture SYSCOHADA via NLP."""
        if not settings.nlp_enabled:
            await self._repondre(phone_from, "⚠️ Service IA indisponible. Contactez le support.")
            return {"action": "nlp_disabled"}

        # Vérifier que l'utilisateur est actif
        user = await self.db.scalar(
            select(User).where(User.id == link.user_id, User.statut == UserStatut.ACTIF)
        )
        if user is None:
            await self._repondre(phone_from, "❌ Votre compte est inactif.")
            return {"action": "user_inactive"}

        nlp = NlpService(self.db, link.tenant_id, user.id)
        try:
            suggestion = await nlp.suggerer(
                SuggestionRequest(phrase=contenu, langue="fr", canal="whatsapp")
            )
        except HTTPException as exc:
            await self._repondre(phone_from, f"❌ {exc.detail}")
            return {"action": "nlp_error"}

        # Marquer le message lié à la suggestion
        await self._envoyer_suggestion_whatsapp(link, suggestion, phone_from)
        return {"action": "suggestion_sent", "suggestion_id": str(suggestion.id)}

    async def _envoyer_suggestion_whatsapp(
        self, link: WhatsAppLink, suggestion, phone_from: str
    ) -> None:
        """Envoie une suggestion formatée à l'utilisateur."""
        e = suggestion.ecriture_proposee
        lignes_txt = "\n".join(
            f"  • {l['compte']:<8} {('D ' + f'{l["debit"]:,}' if l.get('debit') else 'C ' + f'{l["credit"]:,}')} FCFA"
            for l in e["lignes"]
        )
        confiance_emoji = "🟢" if suggestion.confiance > 0.8 else "🟡" if suggestion.confiance > 0.5 else "🔴"
        texte = (
            f"📝 *Écriture proposée*\n\n"
            f"Date : {e['date_ecriture']}\n"
            f"Journal : {e['code_journal']}\n"
            f"Libellé : {e['libelle']}\n\n"
            f"Lignes :\n{lignes_txt}\n\n"
            f"{confiance_emoji} Confiance : {int(suggestion.confiance * 100)}%\n\n"
            f"Répondez *OK* pour valider, *NON* pour rejeter."
        )
        await self._repondre(phone_from, texte)
        # TODO : mapper le numéro → suggestion_id pour la réponse suivante
        # Solution : stocker dans une session WhatsApp temporaire (Redis)
        from app.core.config import settings as cfg
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(cfg.REDIS_URL)
            await r.setex(f"wa:pending:{phone_from}", 600, str(suggestion.id))
            await r.aclose()
        except Exception:
            logger.exception("[whatsapp] Échec stockage session Redis")

    async def _repondre_solde(self, link: WhatsAppLink) -> dict:
        """Retourne le solde de trésorerie actuel."""
        from app.models.ecriture import Ecriture, EcritureLigne
        from app.models.enums import EcritureStatut
        from app.models.plan_comptable import PlanComptable
        from sqlalchemy import func
        stmt = (
            select(func.coalesce(func.sum(EcritureLigne.debit_xof - EcritureLigne.credit_xof), 0))
            .join(PlanComptable, PlanComptable.id == EcritureLigne.compte_id)
            .join(Ecriture, Ecriture.id == EcritureLigne.ecriture_id)
            .where(
                EcritureLigne.tenant_id == link.tenant_id,
                PlanComptable.classe == 5,
                Ecriture.statut == EcritureStatut.VALIDEE,
            )
        )
        solde = int(await self.db.scalar(stmt) or 0)
        await self._repondre(
            link.phone_number,
            f"💰 *Solde de trésorerie*\n\n{solde:,} FCFA".replace(",", " "),
        )
        return {"action": "solde", "montant": solde}

    async def _repondre_prevision(self, link: WhatsAppLink) -> dict:
        """Retourne la prévision de trésorerie à 90 jours."""
        from app.services.forecast_service import ForecastService
        svc = ForecastService(self.db, link.tenant_id, link.user_id)
        try:
            forecast = await svc.calculer(horizon_jours=90)
        except Exception as exc:
            logger.exception("[whatsapp] Prévision échouée")
            await self._repondre(link.phone_number, "❌ Impossible de calculer la prévision.")
            return {"action": "forecast_error"}

        emoji = "⚠️" if forecast.alerte_tresorerie_negative else "✅"
        texte = (
            f"📊 *Prévision {forecast.horizon_jours} jours*\n\n"
            f"Solde actuel : {forecast.solde_initial_xof:,} FCFA\n"
            f"Solde prévu : {forecast.solde_final_prevu_xof:,} FCFA\n\n"
            f"{emoji} {forecast.resume_ia or ''}"
        ).replace(",", " ")
        await self._repondre(link.phone_number, texte)
        return {"action": "forecast", "forecast_id": str(forecast.id)}

    async def _repondre(self, to: str, texte: str) -> None:
        """Envoie un message et le persiste."""
        msg = WhatsAppMessage(
            direction="out",
            phone_from=settings.WHATSAPP_META_PHONE_ID or settings.WHATSAPP_TWILIO_FROM or "MTech",
            phone_to=to,
            type_message="text",
            contenu=texte,
        )
        self.db.add(msg)
        await self.db.flush()

        if not settings.whatsapp_enabled:
            logger.info(f"[whatsapp:out] {to} ← {texte[:80]}")
            return
        try:
            client = get_whatsapp_client()
            await client.send_text(to, texte)
        except Exception:
            logger.exception(f"[whatsapp] Échec envoi à {to}")

    # ─────────────────────────────────────────────────────────────────────
    # Traitement de la réponse OK/NON à une suggestion
    # ─────────────────────────────────────────────────────────────────────
    async def traiter_reponse_suggestion(
        self, phone: str, reponse: str
    ) -> dict | None:
        """
        Vérifie si le message est une réponse à une suggestion en attente.
        Retourne None si aucun contexte en attente.
        """
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(settings.REDIS_URL)
            key = f"wa:pending:{phone}"
            suggestion_id = await r.get(key)
            if not suggestion_id:
                await r.aclose()
                return None
            suggestion_id = suggestion_id.decode()

            # Vérifier le type de réponse
            rep = reponse.strip().lower()
            link = await self.db.scalar(
                select(WhatsAppLink).where(WhatsAppLink.phone_number == phone)
            )
            if link is None:
                await r.aclose()
                return None

            nlp = NlpService(self.db, link.tenant_id, link.user_id)
            if rep in ("ok", "oui", "valide", "valider", "y"):
                result = await nlp.accepter(UUID(suggestion_id))
                await r.delete(key)
                await self._repondre(phone, f"✅ Écriture {result['numero_piece']} enregistrée.")
                await r.aclose()
                return {"action": "accepted", **result}
            elif rep in ("non", "rejeter", "rejet", "n"):
                await nlp.rejeter(UUID(suggestion_id), motif="Rejet via WhatsApp")
                await r.delete(key)
                await self._repondre(phone, "❌ Suggestion rejetée.")
                await r.aclose()
                return {"action": "rejected"}
            await r.aclose()
            return None
        except Exception:
            logger.exception("[whatsapp] Traitement réponse échoué")
            return None

    # ─────────────────────────────────────────────────────────────────────
    # Messages pré-formatés
    # ─────────────────────────────────────────────────────────────────────
    @staticmethod
    def _message_aide() -> str:
        return (
            "📚 *Commandes disponibles*\n\n"
            "• *Saisie* : envoyez une phrase libre\n"
            "   Ex : _Vente 10 sacs à 5000 FCFA à M. Koné_\n"
            "• *solde* : solde de trésorerie\n"
            "• *prevision* : prévision 90 jours\n"
            "• *aide* : ce menu\n\n"
            "💡 Répondez *OK* ou *NON* pour valider une suggestion."
        )

    @staticmethod
    def _message_bienvenue(link: WhatsAppLink) -> str:
        return (
            f"👋 Bonjour !\n\n"
            f"Votre numéro est lié à MTech SYSCOHADA.\n\n"
            f"Envoyez-moi une phrase pour la comptabiliser, ou tapez *aide*."
        )
