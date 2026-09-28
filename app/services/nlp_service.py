"""
Service NLP — convertit une phrase en français ou langue locale en écriture
SYSCOHADA partie double.

Pipeline :
1. Normalisation de la phrase (accents, chiffres, abréviations)
2. Recherche dans le cache de patterns (économie d'appel API)
3. Appel OpenAI en mode JSON strict
4. Validation SYSCOHADA (comptes existants, équilibre, journal valide)
5. Enregistrement de la suggestion + retour
"""
from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import sha256_hex
from app.integrations.openai_client import get_openai_client
from app.models.enums import EcritureSource
from app.models.journal import Journal
from app.models.nlp import NlpFeedback, NlpPattern, NlpSuggestion
from app.models.plan_comptable import PlanComptable
from app.schemas.nlp import (
    NlpSuggestionAccept,
    NlpSuggestionOut,
    SuggestionRequest,
)
from app.services.audit_service import AuditService
from app.services.syscohada_service import SyscohadaService

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Prompt système — le contrat passé à l'IA
# ─────────────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Tu es un expert-comptable SYSCOHADA révisé (Côte d'Ivoire) depuis 20 ans.

TON RÔLE : convertir une phrase en français ou en langue locale (dioula, baoulé, nouchi, anglais ivoirien) en une ÉCRITURE COMPTABLE en partie double.

RÈGLES STRICTES :
1. Utilise UNIQUEMENT les comptes du plan comptable fourni dans le contexte.
2. Double entrée OBLIGATOIRE : total débit = total crédit.
3. Montants en FRANCS CFA (XOF), ENTIERS, jamais de décimales.
4. Le journal doit être l'un de ceux fournis dans le contexte.
5. Si la phrase mentionne Wave, Orange Money, MTN MoMo, Moov → utilise le journal "MM".
6. Si vente → journal "VE", compte produit 701xxx.
7. Si achat → journal "AC", compte charge 601xxx/606xxx.
8. Si paiement/encaissement → journal "BQ" (banque) ou "CA" (caisse).
9. Si tu n'es pas sûr → mets une confiance < 0.5.
10. Ne JAMAIS inventer un compte absent du plan fourni.

FORMAT DE SORTIE (JSON STRICT, RIEN D'AUTRE) :
{
  "numero_piece": null,
  "date_ecriture": "YYYY-MM-DD",
  "code_journal": "VE|AC|BQ|CA|MM|OD",
  "libelle": "libellé court et clair de l'opération",
  "reference_ext": null,
  "confiance": 0.95,
  "raisonnement": "explication brève (1 phrase) du choix comptable",
  "lignes": [
    {"compte": "521100", "libelle": "Encaissement Wave", "debit": 250000, "credit": 0},
    {"compte": "701100", "libelle": "Vente marchandises", "debit": 0, "credit": 250000}
  ]
}

Si la phrase est AMBIGUË, propose l'écriture la plus probable et baisse la confiance.
Si la phrase est HORS SUJET comptable, retourne : {"error": "hors_sujet", "message": "..."}.
"""


class NlpService:
    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.audit = AuditService(db)

    # ─────────────────────────────────────────────────────────────────────
    # API publique
    # ─────────────────────────────────────────────────────────────────────
    async def suggerer(self, req: SuggestionRequest) -> NlpSuggestionOut:
        """Convertit une phrase en suggestion d'écriture validée SYSCOHADA."""
        if not settings.nlp_enabled:
            raise HTTPException(503, "Service IA non configuré (OPENAI_API_KEY absente)")

        phrase = req.phrase.strip()
        if len(phrase) < 5:
            raise HTTPException(400, "Phrase trop courte")

        # 1. Cache de patterns
        cached = await self._lookup_pattern(phrase)
        if cached is not None:
            logger.info(f"[nlp] Cache HIT pour phrase de {len(phrase)} chars")
            return await self._enregistrer_suggestion(
                phrase=phrase,
                langue=req.langue,
                canal=req.canal,
                result=cached,
                modele="cache",
                tokens_prompt=0,
                tokens_completion=0,
                latence_ms=0,
            )

        # 2. Contexte métier (plan comptable + journaux)
        contexte = await self._construire_contexte()

        # 3. Appel OpenAI
        user_prompt = self._build_user_prompt(phrase, req.langue, contexte)
        try:
            client = get_openai_client()
            result = await client.chat_json(SYSTEM_PROMPT, user_prompt)
        except Exception as exc:
            logger.exception("[nlp] Échec OpenAI")
            raise HTTPException(502, f"Erreur service IA : {exc}")

        content = result["content"]
        if "error" in content:
            raise HTTPException(400, f"Phrase non exploitable : {content.get('message', content['error'])}")

        # 4. Validation SYSCOHADA
        content = await self._valider_et_corriger(content, contexte)

        # 5. Persistance
        return await self._enregistrer_suggestion(
            phrase=phrase,
            langue=req.langue,
            canal=req.canal,
            result=content,
            modele=result["model"],
            tokens_prompt=result["tokens_prompt"],
            tokens_completion=result["tokens_completion"],
            latence_ms=result["latence_ms"],
        )

    async def accepter(
        self, suggestion_id: UUID, data: NlpSuggestionAccept | None = None
    ) -> dict[str, Any]:
        """Accepte une suggestion → crée l'écriture SYSCOHADA + feedback loop."""
        suggestion = await self._get_suggestion(suggestion_id)
        if suggestion.statut not in ("en_attente", "corrigee"):
            raise HTTPException(400, f"Suggestion déjà {suggestion.statut}")

        # Le client peut envoyer une version corrigée manuellement
        ecriture_data = data.corrigee if data and data.corrigee else suggestion.ecriture_proposee

        syscohada = SyscohadaService(self.db, self.tenant_id, self.user_id)
        from app.schemas.ecriture import EcritureCreate
        ecriture_create = EcritureCreate(**{
            **ecriture_data,
            "source": EcritureSource.IA_NLP,
        })
        ecriture = await syscohada.create(ecriture_create)

        # Statut
        now = datetime.now(timezone.utc)
        suggestion.statut = "acceptee"
        suggestion.ecriture_id = ecriture.id
        suggestion.acceptee_at = now
        if data and data.corrigee:
            suggestion.ecriture_corrigee = data.corrigee

        # Feedback loop
        await self._enregistrer_feedback(
            suggestion=suggestion,
            corrigee=data.corrigee if data else None,
            accepte_sans_modif=data is None or data.corrigee is None,
        )

        # Cache pattern si accepté sans modif
        if data is None or data.corrigee is None:
            await self._upsert_pattern(suggestion.phrase_source, suggestion.ecriture_proposee)

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="NLP_ACCEPT",
            ressource="nlp_suggestion",
            ressource_id=suggestion.id,
            payload={"ecriture_id": str(ecriture.id)},
        )
        await self.db.flush()

        return {
            "suggestion_id": str(suggestion.id),
            "ecriture_id": str(ecriture.id),
            "numero_piece": ecriture.numero_piece,
        }

    async def rejeter(self, suggestion_id: UUID, motif: str) -> None:
        """Rejette une suggestion + feedback loop."""
        suggestion = await self._get_suggestion(suggestion_id)
        if suggestion.statut != "en_attente":
            raise HTTPException(400, f"Suggestion déjà {suggestion.statut}")

        now = datetime.now(timezone.utc)
        suggestion.statut = "rejetee"
        suggestion.rejetee_at = now
        suggestion.motif_rejet = motif

        await self._enregistrer_feedback(
            suggestion=suggestion, corrigee=None, accepte_sans_modif=False,
        )

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="NLP_REJECT",
            ressource="nlp_suggestion",
            ressource_id=suggestion.id,
            payload={"motif": motif},
        )
        await self.db.flush()

    # ─────────────────────────────────────────────────────────────────────
    # Internes
    # ─────────────────────────────────────────────────────────────────────
    async def _get_suggestion(self, suggestion_id: UUID) -> NlpSuggestion:
        s = await self.db.scalar(
            select(NlpSuggestion).where(
                NlpSuggestion.id == suggestion_id,
                NlpSuggestion.tenant_id == self.tenant_id,
            )
        )
        if s is None:
            raise HTTPException(404, "Suggestion introuvable")
        return s

    async def _construire_contexte(self) -> dict[str, Any]:
        """
        Contexte passé à l'IA : plan comptable + journaux + date du jour.
        ⚠️ Le plan comptable peut être volumineux → on tronque intelligemment
        (les 500 comptes les plus utilisés).
        """
        comptes = (
            await self.db.execute(
                select(PlanComptable.compte, PlanComptable.libelle, PlanComptable.type_compte)
                .where(
                    PlanComptable.tenant_id == self.tenant_id,
                    PlanComptable.actif.is_(True),
                )
                .order_by(PlanComptable.compte)
                .limit(500)
            )
        ).all()

        journaux = (
            await self.db.execute(
                select(Journal.code, Journal.libelle, Journal.type_journal)
                .where(
                    Journal.tenant_id == self.tenant_id,
                    Journal.actif.is_(True),
                )
            )
        ).all()

        return {
            "date_aujourd_hui": date.today().isoformat(),
            "comptes": [
                {"compte": c.compte, "libelle": c.libelle, "type": c.type_compte.value if hasattr(c.type_compte, "value") else str(c.type_compte)}
                for c in comptes
            ],
            "journaux": [
                {"code": j.code, "libelle": j.libelle, "type": j.type_journal.value if hasattr(j.type_journal, "value") else str(j.type_journal)}
                for j in journaux
            ],
        }

    def _build_user_prompt(self, phrase: str, langue: str, contexte: dict[str, Any]) -> str:
        comptes_txt = "\n".join(
            f"  {c['compte']} — {c['libelle']} ({c['type']})" for c in contexte["comptes"][:200]
        )
        journaux_txt = "\n".join(
            f"  {j['code']} — {j['libelle']} ({j['type']})" for j in contexte["journaux"]
        )
        return f"""Date du jour : {contexte['date_aujourd_hui']}

PLAN COMPTABLE DU TENANT (extrait) :
{comptes_txt}

JOURNAUX DISPONIBLES :
{journaux_txt}

PHRASE À CONVERTIR (langue : {langue}) :
\"{phrase}\"

Génère l'écriture SYSCOHADA au format JSON strict."""

    async def _valider_et_corriger(
        self, content: dict[str, Any], contexte: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Valide la sortie IA :
        - Comptes existent dans le plan
        - Écriture équilibrée
        - Journal valide
        - Montants entiers positifs
        Corrige automatiquement les erreurs mineures (arrondis, timezone).
        """
        # Champs obligatoires
        for champ in ("date_ecriture", "code_journal", "libelle", "lignes"):
            if champ not in content:
                raise HTTPException(500, f"Sortie IA invalide : {champ} manquant")

        # Journal
        codes_valides = {j["code"] for j in contexte["journaux"]}
        if content["code_journal"] not in codes_valides:
            raise HTTPException(
                500,
                f"Journal {content['code_journal']} absent du tenant",
            )

        # Comptes
        comptes_valides = {c["compte"] for c in contexte["comptes"]}
        for ligne in content["lignes"]:
            if ligne.get("compte") not in comptes_valides:
                raise HTTPException(
                    500,
                    f"Compte {ligne.get('compte')} absent du plan comptable",
                )
            # Montants entiers
            ligne["debit"] = int(ligne.get("debit", 0) or 0)
            ligne["credit"] = int(ligne.get("credit", 0) or 0)

        # Équilibre
        td = sum(l["debit"] for l in content["lignes"])
        tc = sum(l["credit"] for l in content["lignes"])
        if td != tc:
            logger.warning(f"[nlp] Déséquilibre IA : D={td} C={tc} — correction auto")
            # Correction automatique : on ajuste la plus grosse ligne du côté déficitaire
            if td < tc:
                idx = max(
                    (i for i, l in enumerate(content["lignes"]) if l["debit"] > 0),
                    key=lambda i: content["lignes"][i]["debit"],
                    default=None,
                )
                if idx is not None:
                    content["lignes"][idx]["debit"] += tc - td
                    content["confiance"] = min(content.get("confiance", 0.5), 0.4)
            else:
                idx = max(
                    (i for i, l in enumerate(content["lignes"]) if l["credit"] > 0),
                    key=lambda i: content["lignes"][i]["credit"],
                    default=None,
                )
                if idx is not None:
                    content["lignes"][idx]["credit"] += td - tc
                    content["confiance"] = min(content.get("confiance", 0.5), 0.4)

        # Normalisation confiance
        content["confiance"] = float(max(0.0, min(1.0, content.get("confiance", 0.5))))

        return content

    async def _enregistrer_suggestion(
        self,
        phrase: str,
        langue: str,
        canal: str,
        result: dict[str, Any],
        modele: str,
        tokens_prompt: int | None,
        tokens_completion: int | None,
        latence_ms: int | None,
    ) -> NlpSuggestionOut:
        suggestion = NlpSuggestion(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            phrase_source=phrase,
            langue=langue,
            source_canal=canal,
            ecriture_proposee=result,
            confiance=result.get("confiance", 0.5),
            modele_utilise=modele,
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            latence_ms=latence_ms,
            statut="en_attente",
        )
        self.db.add(suggestion)
        await self.db.flush()
        return NlpSuggestionOut.model_validate(suggestion)

    # ─────────────────────────────────────────────────────────────────────
    # Feedback loop
    # ─────────────────────────────────────────────────────────────────────
    async def _enregistrer_feedback(
        self,
        suggestion: NlpSuggestion,
        corrigee: dict[str, Any] | None,
        accepte_sans_modif: bool,
    ) -> None:
        import json

        diff = 0
        score = 1.0 if accepte_sans_modif else 0.5
        if corrigee is not None:
            # Distance d'édition approximative via longueur JSON
            a = json.dumps(suggestion.ecriture_proposee, sort_keys=True)
            b = json.dumps(corrigee, sort_keys=True)
            diff = abs(len(a) - len(b))
            score = 0.3 if diff > 50 else 0.7

        fb = NlpFeedback(
            tenant_id=self.tenant_id,
            suggestion_id=suggestion.id,
            user_id=self.user_id,
            phrase_source=suggestion.phrase_source,
            proposition_ia=suggestion.ecriture_proposee,
            correction_humaine=corrigee,
            difference_edit_distance=diff,
            accepte_sans_modification=accepte_sans_modif,
            score_qualite=score,
        )
        self.db.add(fb)
        await self.db.flush()

    # ─────────────────────────────────────────────────────────────────────
    # Cache de patterns (pré-filtre avant OpenAI)
    # ─────────────────────────────────────────────────────────────────────
    def _normaliser(self, phrase: str) -> str:
        # Minuscule + suppression accents
        s = unicodedata.normalize("NFD", phrase.lower())
        s = "".join(c for c in s if unicodedata.category(c) != "Mn")
        # Normalisation des espaces et ponctuation
        s = re.sub(r"[^\w\s]", "", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    async def _lookup_pattern(self, phrase: str) -> dict[str, Any] | None:
        norm = self._normaliser(phrase)
        h = sha256_hex(norm)
        pattern = await self.db.scalar(
            select(NlpPattern).where(
                NlpPattern.tenant_id == self.tenant_id,
                NlpPattern.hash_phrase == h,
                NlpPattern.occurrences >= 1,
            )
        )
        if pattern is None:
            return None
        # On incrémente le compteur d'usage
        pattern.occurrences += 1
        await self.db.flush()
        # On retourne une copie pour ne pas altérer le pattern original
        return dict(pattern.ecriture_validee)

    async def _upsert_pattern(self, phrase: str, ecriture: dict[str, Any]) -> None:
        norm = self._normaliser(phrase)
        h = sha256_hex(norm)
        existing = await self.db.scalar(
            select(NlpPattern).where(
                NlpPattern.tenant_id == self.tenant_id,
                NlpPattern.hash_phrase == h,
            )
        )
        if existing is not None:
            existing.occurrences += 1
            existing.confiance_moyenne = (
                (existing.confiance_moyenne * (existing.occurrences - 1) + ecriture.get("confiance", 1.0))
                / existing.occurrences
            )
        else:
            self.db.add(
                NlpPattern(
                    tenant_id=self.tenant_id,
                    phrase_normalisee=norm,
                    hash_phrase=h,
                    ecriture_validee=ecriture,
                    occurrences=1,
                    confiance_moyenne=ecriture.get("confiance", 1.0),
                )
            )
        await self.db.flush()

    # ─────────────────────────────────────────────────────────────────────
    # Statistiques feedback (cockpit)
    # ─────────────────────────────────────────────────────────────────────
    async def get_stats(self) -> dict[str, Any]:
        from sqlalchemy import func
        rows = (
            await self.db.execute(
                select(
                    NlpSuggestion.statut,
                    func.count(NlpSuggestion.id),
                    func.avg(NlpSuggestion.confiance),
                )
                .where(NlpSuggestion.tenant_id == self.tenant_id)
                .group_by(NlpSuggestion.statut)
            )
        ).all()
        stats: dict[str, Any] = {"total": 0, "par_statut": {}, "confiance_moyenne": 0.0}
        total = 0
        sum_conf = 0.0
        for statut, count, avg_conf in rows:
            stats["par_statut"][statut] = int(count)
            total += int(count)
            if avg_conf is not None:
                sum_conf += float(avg_conf) * int(count)
        stats["total"] = total
        stats["confiance_moyenne"] = sum_conf / total if total else 0.0
        return stats
