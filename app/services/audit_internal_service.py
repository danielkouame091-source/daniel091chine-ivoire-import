"""
Service Audit & Contrôle interne.

Fonctionnalités :
- Piste d'audit hash-chained (immuable)
- Moteur de règles configurables (20 règles par défaut)
- Détection d'anomalies (Benford, circulaires, seuils)
- Tests de cohérence comptable
- Rapports de conformité OHADA / DGI
- Workflow de résolution des findings
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import and_, desc, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_syscohada import (
    BENFORD_DISTRIBUTION,
    CHECKLIST_CONFORMITE,
    CategorieControle,
    SeveriteFinding,
    StatutFinding,
    TypeRegleAudit,
)
from app.core.security import sha256_hex
from app.models.audit_internal import (
    AuditFinding,
    AuditRule,
    AuditRun,
    AuditTrail,
    BenfordAnalysis,
    ComplianceReport,
)
from app.models.ecriture import Ecriture, EcritureLigne
from app.models.exercice import Exercice
from app.models.fne import FneInvoice
from app.models.plan_comptable import PlanComptable
from app.models.purchase import SupplierInvoice
from app.models.sale import CustomerInvoice
from app.schemas.audit_internal import (
    AuditDashboardOut,
    AuditFindingOut,
    AuditRuleCreate,
    AuditRuleUpdate,
    AuditRunRequest,
    AuditTrailFilter,
    AuditTrailVerifyOut,
    BenfordAnalysisRequest,
    CircularTransactionOut,
    ComplianceReportOut,
    ComplianceReportRequest,
    FindingResolveRequest,
    JustBelowThresholdOut,
)
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class AuditInternalService:
    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.audit = AuditService(db)

    # ═════════════════════════════════════════════════════════════════════
    # PISTE D'AUDIT (AUDIT TRAIL)
    # ═════════════════════════════════════════════════════════════════════
    async def log_action(
        self,
        action: str,
        categorie: str,
        ressource_type: str,
        ressource_id: UUID | None = None,
        ressource_ref: str | None = None,
        avant: dict[str, Any] | None = None,
        apres: dict[str, Any] | None = None,
        details: dict[str, Any] | None = None,
        succes: bool = True,
        code_erreur: str | None = None,
        message_erreur: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        endpoint: str | None = None,
        methode_http: str | None = None,
        request_id: str | None = None,
    ) -> AuditTrail:
        """
        Enregistre une action dans la piste d'audit avec hash-chain.
        """
        # Hash précédent
        precedent = await self.db.scalar(
            select(AuditTrail.hash_courant)
            .where(AuditTrail.tenant_id == self.tenant_id)
            .order_by(desc(AuditTrail.created_at))
            .limit(1)
        )

        now = datetime.now(timezone.utc)
        contenu = "|".join([
            str(self.tenant_id or ""),
            str(self.user_id or ""),
            action,
            ressource_type,
            str(ressource_id or ""),
            str(avant or {}),
            str(apres or {}),
            now.isoformat(),
        ])
        hash_courant = sha256_hex(f"{precedent or 'GENESIS'}|{contenu}")

        entry = AuditTrail(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action=action,
            categorie=categorie,
            ressource_type=ressource_type,
            ressource_id=ressource_id,
            ressource_ref=ressource_ref,
            ip_address=ip_address,
            user_agent=user_agent,
            endpoint=endpoint,
            methode_http=methode_http,
            request_id=request_id,
            avant=avant,
            apres=apres,
            details=details,
            succes=succes,
            code_erreur=code_erreur,
            message_erreur=message_erreur,
            hash_precedent=precedent,
            hash_courant=hash_courant,
            created_at=now,
        )
        self.db.add(entry)
        await self.db.flush()
        return entry

    async def verify_audit_chain(
        self, tenant_id: UUID, limit: int = 10000
    ) -> AuditTrailVerifyOut:
        """
        Vérifie l'intégrité du hash-chain sur les `limit` dernières entrées.
        Retourne le nombre d'entrées vérifiées et le booléen d'intégrité.
        """
        rows = (
            await self.db.execute(
                select(AuditTrail)
                .where(AuditTrail.tenant_id == tenant_id)
                .order_by(AuditTrail.created_at.asc())
                .limit(limit)
            )
        ).scalars().all()

        if not rows:
            return AuditTrailVerifyOut(
                tenant_id=tenant_id,
                nb_entrees=0,
                integre=True,
                premiere_entree=None,
                derniere_entree=None,
                premiere_alteration=None,
            )

        precedent: str | None = None
        premiere_alteration: datetime | None = None

        for e in rows:
            contenu = "|".join([
                str(e.tenant_id or ""),
                str(e.user_id or ""),
                e.action,
                e.ressource_type,
                str(e.ressource_id or ""),
                str(e.avant or {}),
                str(e.apres or {}),
                e.created_at.isoformat(),
            ])
            attendu = sha256_hex(f"{precedent or 'GENESIS'}|{contenu}")
            if attendu != e.hash_courant or e.hash_precedent != precedent:
                premiere_alteration = e.created_at
                break
            precedent = e.hash_courant

        return AuditTrailVerifyOut(
            tenant_id=tenant_id,
            nb_entrees=len(rows),
            integre=premiere_alteration is None,
            premiere_entree=rows[0].created_at,
            derniere_entree=rows[-1].created_at,
            premiere_alteration=premiere_alteration,
        )

    async def list_audit_trail(
        self, filters: AuditTrailFilter, limit: int = 200, offset: int = 0
    ) -> list[AuditTrailOut]:
        stmt = select(AuditTrail).where(AuditTrail.tenant_id == self.tenant_id)
        if filters.user_id:
            stmt = stmt.where(AuditTrail.user_id == filters.user_id)
        if filters.action:
            stmt = stmt.where(AuditTrail.action == filters.action)
        if filters.ressource_type:
            stmt = stmt.where(AuditTrail.ressource_type == filters.ressource_type)
        if filters.ressource_id:
            stmt = stmt.where(AuditTrail.ressource_id == filters.ressource_id)
        if filters.succes is not None:
            stmt = stmt.where(AuditTrail.succes == filters.succes)
        if filters.date_debut:
            stmt = stmt.where(
                AuditTrail.created_at >= datetime.combine(filters.date_debut, datetime.min.time()).replace(tzinfo=timezone.utc)
            )
        if filters.date_fin:
            stmt = stmt.where(
                AuditTrail.created_at <= datetime.combine(filters.date_fin, datetime.max.time()).replace(tzinfo=timezone.utc)
            )
        stmt = stmt.order_by(desc(AuditTrail.created_at)).limit(limit).offset(offset)
        rows = (await self.db.execute(stmt)).scalars().all()
        return [AuditTrailOut.model_validate(r) for r in rows]

    # ═════════════════════════════════════════════════════════════════════
    # RÈGLES
    # ═════════════════════════════════════════════════════════════════════
    async def creer_regle(self, data: AuditRuleCreate) -> AuditRule:
        existing = await self.db.scalar(
            select(AuditRule.id).where(
                AuditRule.tenant_id == self.tenant_id,
                AuditRule.code == data.code,
            )
        )
        if existing:
            raise HTTPException(409, f"Règle {data.code} déjà existante")

        rule = AuditRule(tenant_id=self.tenant_id, **data.model_dump())
        self.db.add(rule)
        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="AUDIT_RULE_CREATE",
            ressource="audit_rule",
            ressource_id=rule.id,
            payload={"code": rule.code, "severite": rule.severite},
        )
        return rule

    async def modifier_regle(self, rule_id: UUID, data: AuditRuleUpdate) -> AuditRule:
        rule = await self._get_rule(rule_id)
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(rule, k, v)
        await self.db.flush()
        return rule

    async def lister_regles(
        self, active_only: bool = True, categorie: str | None = None
    ) -> list[AuditRule]:
        stmt = select(AuditRule).where(
            or_(
                AuditRule.tenant_id == self.tenant_id,
                AuditRule.tenant_id.is_(None),
            )
        )
        if active_only:
            stmt = stmt.where(AuditRule.active.is_(True))
        if categorie:
            stmt = stmt.where(AuditRule.categorie == categorie)
        stmt = stmt.order_by(AuditRule.categorie, AuditRule.code)
        return list((await self.db.execute(stmt)).scalars().all())

    async def seed_regles_defaut(self) -> int:
        """
        Initialise les règles par défaut pour un tenant.
        Idempotent : ne recrée pas les règles existantes.
        """
        REGLES = [
            {
                "code": "COH-001",
                "libelle": "Écriture déséquilibrée",
                "categorie": CategorieControle.COHERENCE_COMPTABLE,
                "type_regle": TypeRegleAudit.ECRITURE_DESEQUILIBREE,
                "severite": SeveriteFinding.CRITIQUE,
                "frequence": "quotidien",
                "reference_legale": "SYSCOHADA art. 17",
            },
            {
                "code": "COH-002",
                "libelle": "Écriture sans ligne",
                "categorie": CategorieControle.COHERENCE_COMPTABLE,
                "type_regle": TypeRegleAudit.ECRITURE_SANS_LIGNE,
                "severite": SeveriteFinding.HIGH,
                "frequence": "quotidien",
            },
            {
                "code": "COH-003",
                "libelle": "Écriture sur exercice clôturé",
                "categorie": CategorieControle.COHERENCE_COMPTABLE,
                "type_regle": TypeRegleAudit.EXERCICE_CLOTURE_MODIFIE,
                "severite": SeveriteFinding.HIGH,
                "frequence": "quotidien",
            },
            {
                "code": "INT-001",
                "libelle": "Écriture doublon",
                "categorie": CategorieControle.INTEGRITE_DONNEES,
                "type_regle": TypeRegleAudit.ECRITURE_DOUBLON,
                "severite": SeveriteFinding.MEDIUM,
                "frequence": "quotidien",
                "parametres": {"fenetre_jours": 3},
            },
            {
                "code": "INT-002",
                "libelle": "Compte non lettré depuis > 90 jours",
                "categorie": CategorieControle.INTEGRITE_DONNEES,
                "type_regle": TypeRegleAudit.COMPTE_NON_LETTRE_ANCIEN,
                "severite": SeveriteFinding.LOW,
                "frequence": "hebdomadaire",
                "parametres": {"jours": 90},
            },
            {
                "code": "FIS-001",
                "libelle": "Facture sans certification FNE",
                "categorie": CategorieControle.CONFORMITE_FISCALE,
                "type_regle": TypeRegleAudit.FACTURE_SANS_FNE,
                "severite": SeveriteFinding.HIGH,
                "frequence": "quotidien",
                "reference_legale": "CGI CI art. 384",
            },
            {
                "code": "FIS-002",
                "libelle": "Déclaration DGI en retard",
                "categorie": CategorieControle.CONFORMITE_FISCALE,
                "type_regle": TypeRegleAudit.DECLARATION_DGI_RETARD,
                "severite": SeveriteFinding.HIGH,
                "frequence": "quotidien",
                "parametres": {"jours_tolerance": 5},
            },
            {
                "code": "FIS-003",
                "libelle": "TVA manquante sur facture",
                "categorie": CategorieControle.CONFORMITE_FISCALE,
                "type_regle": TypeRegleAudit.TVA_MANQUANTE,
                "severite": SeveriteFinding.MEDIUM,
                "frequence": "quotidien",
            },
            {
                "code": "SEC-001",
                "libelle": "Connexion depuis IP suspecte",
                "categorie": CategorieControle.SECURITE_ACCES,
                "type_regle": TypeRegleAudit.CONNEXION_IP_SUSPECTE,
                "severite": SeveriteFinding.HIGH,
                "frequence": "temps_reel",
            },
            {
                "code": "SEC-002",
                "libelle": "Accès hors horaires de bureau",
                "categorie": CategorieControle.SECURITE_ACCES,
                "type_regle": TypeRegleAudit.ACCES_HORS_HORAIRES,
                "severite": SeveriteFinding.MEDIUM,
                "frequence": "quotidien",
                "parametres": {"heures_ouverture": 6, "heures_fermeture": 22},
            },
            {
                "code": "FRD-001",
                "libelle": "Distribution non conforme à la loi de Benford",
                "categorie": CategorieControle.FRAUDE_DETECTION,
                "type_regle": TypeRegleAudit.LOI_BENFORD,
                "severite": SeveriteFinding.MEDIUM,
                "frequence": "mensuel",
            },
            {
                "code": "FRD-002",
                "libelle": "Montants juste sous un seuil fiscal",
                "categorie": CategorieControle.FRAUDE_DETECTION,
                "type_regle": TypeRegleAudit.MONTANTS_JUSTE_SOUS_SEUIL,
                "severite": SeveriteFinding.MEDIUM,
                "frequence": "hebdomadaire",
                "parametres": {"tolerance": 1000},
            },
            {
                "code": "FRD-003",
                "libelle": "Transactions circulaires",
                "categorie": CategorieControle.FRAUDE_DETECTION,
                "type_regle": TypeRegleAudit.TRANSACTIONS_CIRCULAIRES,
                "severite": SeveriteFinding.HIGH,
                "frequence": "hebdomadaire",
            },
            {
                "code": "PERF-001",
                "libelle": "Écriture non validée depuis > 30 jours",
                "categorie": CategorieControle.PERFORMANCE,
                "type_regle": TypeRegleAudit.ECRITURE_NON_VALIDEE_ANCIENNE,
                "severite": SeveriteFinding.LOW,
                "frequence": "hebdomadaire",
                "parametres": {"jours": 30},
            },
        ]

        existing_codes = set(
            (
                await self.db.execute(
                    select(AuditRule.code).where(AuditRule.tenant_id == self.tenant_id)
                )
            ).scalars().all()
        )

        created = 0
        for r in REGLES:
            if r["code"] in existing_codes:
                continue
            self.db.add(AuditRule(tenant_id=self.tenant_id, **r))
            created += 1

        await self.db.flush()
        return created

    # ═════════════════════════════════════════════════════════════════════
    # EXÉCUTION DES RÈGLES
    # ═════════════════════════════════════════════════════════════════════
    async def executer_regles(self, data: AuditRunRequest) -> list[AuditRun]:
        """
        Exécute une ou toutes les règles actives.
        Retourne la liste des runs créés.
        """
        if data.rule_code:
            rule = await self.db.scalar(
                select(AuditRule).where(
                    or_(
                        AuditRule.tenant_id == self.tenant_id,
                        AuditRule.tenant_id.is_(None),
                    ),
                    AuditRule.code == data.rule_code,
                )
            )
            if rule is None:
                raise HTTPException(404, f"Règle {data.rule_code} introuvable")
            rules = [rule]
        else:
            rules = await self.lister_regles(active_only=True)

        runs: list[AuditRun] = []
        for rule in rules:
            try:
                run = await self._executer_regle(rule, data)
                runs.append(run)
            except Exception as exc:
                logger.exception(f"[audit] Échec règle {rule.code}")
                # Créer un run d'erreur
                run = AuditRun(
                    tenant_id=self.tenant_id,
                    rule_id=rule.id,
                    reference=f"RUN-{rule.code}-ERR",
                    statut="erreur",
                    erreur=str(exc),
                )
                self.db.add(run)
                await self.db.flush()
                runs.append(run)

        return runs

    async def _executer_regle(self, rule: AuditRule, req: AuditRunRequest) -> AuditRun:
        """Exécute une règle et crée les findings associés."""
        start = time.monotonic()
        date_debut = req.date_debut or (date.today() - timedelta(days=30))
        date_fin = req.date_fin or date.today()

        # Référence du run
        count = int(await self.db.scalar(
            select(func.count(AuditRun.id)).where(AuditRun.tenant_id == self.tenant_id)
        ) or 0)
        reference = f"RUN-{rule.code}-{count + 1:05d}"

        run = AuditRun(
            tenant_id=self.tenant_id,
            rule_id=rule.id,
            reference=reference,
            date_debut=date_debut,
            date_fin=date_fin,
            statut="en_cours",
            declencheur="manuel",
            execute_par=self.user_id,
        )
        self.db.add(run)
        await self.db.flush()

        # Dispatcher vers la fonction de contrôle appropriée
        from app.services.audit_rules import AUDIT_RULE_HANDLERS

        handler = AUDIT_RULE_HANDLERS.get(rule.type_regle)
        if handler is None:
            run.statut = "erreur"
            run.erreur = f"Aucun handler pour {rule.type_regle}"
            await self.db.flush()
            return run

        findings_data: list[dict[str, Any]] = await handler(
            self, rule, date_debut, date_fin, req.max_findings
        )

        # Créer les findings
        severites = [f.get("severite", rule.severite) for f in findings_data]
        severite_max = max(severites, key=lambda s: {
            "info": 0, "low": 1, "medium": 2, "high": 3, "critique": 4,
        }.get(s, 0)) if severites else None

        for fd in findings_data:
            f_count = int(await self.db.scalar(
                select(func.count(AuditFinding.id)).where(AuditFinding.tenant_id == self.tenant_id)
            ) or 0)
            ref = f"FND-{date_fin.year}-{f_count + 1:06d}"

            finding = AuditFinding(
                tenant_id=self.tenant_id,
                rule_id=rule.id,
                run_id=run.id,
                reference=ref,
                titre=fd.get("titre", rule.libelle),
                description=fd.get("description", ""),
                severite=fd.get("severite", rule.severite),
                ressource_type=fd.get("ressource_type", "unknown"),
                ressource_id=fd.get("ressource_id"),
                ressource_ref=fd.get("ressource_ref"),
                donnees=fd.get("donnees", {}),
                recommandation=fd.get("recommandation"),
                impact_estime=fd.get("impact_estime"),
                statut=StatutFinding.NOUVEAU,
                escalade_fondateur=fd.get("severite") == SeveriteFinding.CRITIQUE,
                escalade_at=datetime.now(timezone.utc) if fd.get("severite") == SeveriteFinding.CRITIQUE else None,
            )
            self.db.add(finding)

        run.nb_findings = len(findings_data)
        run.nb_lignes_analysees = len(findings_data)   # À affiner selon le handler
        run.severite_max = severite_max
        run.statut = "succes"
        run.duree_ms = int((time.monotonic() - start) * 1000)
        await self.db.flush()

        return run

    # ═════════════════════════════════════════════════════════════════════
    # FINDINGS — WORKFLOW
    # ═════════════════════════════════════════════════════════════════════
    async def list_findings(
        self,
        statut: str | None = None,
        severite: str | None = None,
        rule_id: UUID | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[AuditFindingOut]:
        stmt = select(AuditFinding).where(AuditFinding.tenant_id == self.tenant_id)
        if statut:
            stmt = stmt.where(AuditFinding.statut == statut)
        if severite:
            stmt = stmt.where(AuditFinding.severite == severite)
        if rule_id:
            stmt = stmt.where(AuditFinding.rule_id == rule_id)
        stmt = stmt.order_by(
            desc(AuditFinding.escalade_fondateur),
            desc(AuditFinding.created_at),
        ).limit(limit).offset(offset)
        rows = (await self.db.execute(stmt)).scalars().all()
        return [AuditFindingOut.model_validate(f) for f in rows]

    async def resoudre_finding(
        self, finding_id: UUID, data: FindingResolveRequest
    ) -> AuditFindingOut:
        finding = await self._get_finding(finding_id)
        if finding.statut in (StatutFinding.RESOLU, StatutFinding.IGNORE, StatutFinding.FAUX_POSITIF):
            raise HTTPException(400, f"Finding déjà {finding.statut}")

        # Avant/après pour l'audit trail
        avant = {"statut": finding.statut, "commentaire": finding.commentaire_resolution}
        finding.statut = data.statut
        finding.resolu_par = self.user_id
        finding.resolu_at = datetime.now(timezone.utc)
        finding.commentaire_resolution = data.commentaire
        await self.db.flush()

        await self.log_action(
            action="FINDING_RESOLVE",
            categorie="tracabilite",
            ressource_type="audit_finding",
            ressource_id=finding.id,
            ressource_ref=finding.reference,
            avant=avant,
            apres={"statut": finding.statut, "commentaire": data.commentaire},
        )
        return AuditFindingOut.model_validate(finding)

    async def escalader_finding(
        self, finding_id: UUID, motif: str
    ) -> AuditFindingOut:
        finding = await self._get_finding(finding_id)
        finding.escalade_fondateur = True
        finding.escalade_at = datetime.now(timezone.utc)
        finding.statut = StatutFinding.ESCALADE
        if finding.donnees is None:
            finding.donnees = {}
        finding.donnees["motif_escalade"] = motif
        await self.db.flush()

        await self.log_action(
            action="FINDING_ESCALATE",
            categorie="tracabilite",
            ressource_type="audit_finding",
            ressource_id=finding.id,
            ressource_ref=finding.reference,
            apres={"motif": motif},
        )
        return AuditFindingOut.model_validate(finding)

    async def assigner_finding(
        self, finding_id: UUID, user_id: UUID
    ) -> AuditFindingOut:
        finding = await self._get_finding(finding_id)
        finding.assigne_a = user_id
        if finding.statut == StatutFinding.NOUVEAU:
            finding.statut = StatutFinding.EN_COURS
        await self.db.flush()
        return AuditFindingOut.model_validate(finding)

    # ═════════════════════════════════════════════════════════════════════
    # BENFORD
    # ═════════════════════════════════════════════════════════════════════
    async def analyser_benford(
        self, data: BenfordAnalysisRequest
    ) -> BenfordAnalysisOut:
        """
        Analyse la distribution des montants selon la loi de Benford.
        """
        # Extraire les montants
        stmt = (
            select(EcritureLigne.debit_xof, EcritureLigne.credit_xof)
            .join(Ecriture, Ecriture.id == EcritureLigne.ecriture_id)
            .where(
                EcritureLigne.tenant_id == self.tenant_id,
                Ecriture.date_ecriture.between(data.periode_debut, data.periode_fin),
                Ecriture.statut == "validee",
            )
        )
        if data.compte_prefixe:
            stmt = stmt.join(PlanComptable, PlanComptable.id == EcritureLigne.compte_id).where(
                PlanComptable.compte.like(f"{data.compte_prefixe}%")
            )

        rows = (await self.db.execute(stmt)).all()

        # Premier chiffre significatif
        premier_chiffre: list[int] = []
        for debit, credit in rows:
            montant = int(debit or 0) + int(credit or 0)
            if montant >= data.min_montant:
                s = str(abs(montant))
                premier_chiffre.append(int(s[0]))

        if len(premier_chiffre) < 100:
            raise HTTPException(
                400,
                f"Échantillon insuffisant ({len(premier_chiffre)} < 100). "
                f"Élargir la période ou réduire le seuil.",
            )

        # Distribution observée
        compteur = Counter(premier_chiffre)
        total = len(premier_chiffre)
        observee = {str(i): compteur.get(i, 0) / total for i in range(1, 10)}

        # Chi-square
        chi_square = 0.0
        for i in range(1, 10):
            attendu = BENFORD_DISTRIBUTION[i] * total
            observe = compteur.get(i, 0)
            chi_square += ((observe - attendu) ** 2) / attendu

        # Score de conformité (0-1)
        # Chi-square critique pour 8 degrés de liberté à 5% = 15.507
        chi_critique = 15.507
        score = max(0.0, 1.0 - (chi_square / (2 * chi_critique)))
        conforme = chi_square < chi_critique

        # Top anomalies (chiffres les plus déviants)
        anomalies = []
        for i in range(1, 10):
            ecart = abs(observee[str(i)] - BENFORD_DISTRIBUTION[i])
            if ecart > 0.03:   # 3 points de %
                anomalies.append({
                    "chiffre": i,
                    "observe": round(observee[str(i)], 4),
                    "attendu": round(BENFORD_DISTRIBUTION[i], 4),
                    "ecart": round(ecart, 4),
                })
        anomalies.sort(key=lambda x: x["ecart"], reverse=True)

        analysis = BenfordAnalysis(
            tenant_id=self.tenant_id,
            periode_debut=data.periode_debut,
            periode_fin=data.periode_fin,
            nb_echantillons=total,
            distribution_observee=observee,
            distribution_attendue={str(k): v for k, v in BENFORD_DISTRIBUTION.items()},
            score_conformite=Decimal(str(round(score, 4))),
            chi_square=Decimal(str(round(chi_square, 4))),
            conforme=conforme,
            anomalies=anomalies[:5],
        )
        self.db.add(analysis)
        await self.db.flush()

        return BenfordAnalysisOut.model_validate(analysis)

    # ═════════════════════════════════════════════════════════════════════
    # DÉTECTION DE TRANSACTIONS CIRCULAIRES
    # ═════════════════════════════════════════════════════════════════════
    async def detecter_circulaires(
        self, date_debut: date, date_fin: date, fenetre_jours: int = 7
    ) -> list[CircularTransactionOut]:
        """
        Détecte les transactions circulaires (A → B → A) sur la période.
        """
        # Charger les écritures avec tiers (comptes 4xx)
        stmt = (
            select(
                Ecriture.id,
                Ecriture.date_ecriture,
                Ecriture.libelle,
                Ecriture.reference_ext,
                EcritureLigne.debit_xof,
                EcritureLigne.credit_xof,
                PlanComptable.compte,
            )
            .join(EcritureLigne, EcritureLigne.ecriture_id == Ecriture.id)
            .join(PlanComptable, PlanComptable.id == EcritureLigne.compte_id)
            .where(
                Ecriture.tenant_id == self.tenant_id,
                Ecriture.date_ecriture.between(date_debut, date_fin),
                Ecriture.statut == "validee",
                PlanComptable.classe == 4,
            )
            .order_by(Ecriture.date_ecriture)
        )
        rows = (await self.db.execute(stmt)).all()

        # Grouper par tiers (extrait depuis le compte ou la référence)
        par_tiers: dict[str, list[dict]] = {}
        for r in rows:
            tiers = r.reference_ext or r.compte
            if tiers not in par_tiers:
                par_tiers[tiers] = []
            par_tiers[tiers].append({
                "ecriture_id": str(r.id),
                "date": r.date_ecriture.isoformat(),
                "libelle": r.libelle,
                "montant": int(r.debit_xof or 0) - int(r.credit_xof or 0),
                "compte": r.compte,
            })

        # Détecter cycles (simplifié : même montant entrant/sortant dans la fenêtre)
        circulaires: list[CircularTransactionOut] = []
        for tiers, operations in par_tiers.items():
            if len(operations) < 2:
                continue
            # Chercher des paires débit/crédit symétriques
            debits = [op for op in operations if op["montant"] > 0]
            credits = [op for op in operations if op["montant"] < 0]
            for d in debits:
                for c in credits:
                    if abs(abs(d["montant"]) - abs(c["montant"])) < 100:
                        jours = abs(
                            (datetime.fromisoformat(d["date"]) - datetime.fromisoformat(c["date"])).days
                        )
                        if jours <= fenetre_jours:
                            circulaires.append(CircularTransactionOut(
                                cycle=[d, c],
                                montant_total=abs(d["montant"]),
                                nb_operations=2,
                                periode_jours=jours,
                                score_suspicion=0.7,
                            ))

        return circulaires

    async def detecter_montants_sous_seuil(
        self, date_debut: date, date_fin: date, seuil: int = 5_000_000, tolerance: int = 1000
    ) -> JustBelowThresholdOut:
        """
        Détecte les transactions juste sous un seuil (potentiellement fractionnées).
        """
        stmt = (
            select(Ecriture)
            .where(
                Ecriture.tenant_id == self.tenant_id,
                Ecriture.date_ecriture.between(date_debut, date_fin),
                Ecriture.statut == "validee",
            )
        )
        ecritures = (await self.db.execute(stmt)).scalars().all()

        suspects: list[dict[str, Any]] = []
        for e in ecritures:
            # Calculer le total de l'écriture
            total = int(await self.db.scalar(
                select(func.coalesce(func.sum(EcritureLigne.debit_xof), 0))
                .where(EcritureLigne.ecriture_id == e.id)
            ) or 0)
            if seuil - tolerance <= total < seuil:
                suspects.append({
                    "ecriture_id": str(e.id),
                    "numero_piece": e.numero_piece,
                    "date": e.date_ecriture.isoformat(),
                    "libelle": e.libelle,
                    "montant": total,
                    "ecart_seuil": seuil - total,
                })

        montant_total = sum(s["montant"] for s in suspects)
        score = min(1.0, len(suspects) / 20) if suspects else 0.0

        return JustBelowThresholdOut(
            seuil=seuil,
            nb_transactions=len(suspects),
            montant_total=montant_total,
            transactions=suspects[:50],
            score_suspicion=round(score, 2),
        )

    # ═════════════════════════════════════════════════════════════════════
    # RAPPORT DE CONFORMITÉ
    # ═════════════════════════════════════════════════════════════════════
    async def generer_rapport_conformite(
        self, data: ComplianceReportRequest
    ) -> ComplianceReportOut:
        """
        Génère un rapport de conformité OHADA / DGI.
        """
        count = int(await self.db.scalar(
            select(func.count(ComplianceReport.id)).where(
                ComplianceReport.tenant_id == self.tenant_id
            )
        ) or 0)
        reference = f"CONF-{data.periode_fin.year}-{count + 1:04d}"

        # Exécuter chaque check
        checks: list[dict[str, Any]] = []
        for check in CHECKLIST_CONFORMITE:
            result = await self._executer_check_conformite(
                check.code, data.periode_debut, data.periode_fin
            )
            checks.append({
                "code": check.code,
                "libelle": check.libelle,
                "reference_legale": check.reference_legale,
                "obligatoire": check.obligatoire,
                **result,
            })

        # Calcul des scores
        total = len(checks)
        reussis = sum(1 for c in checks if c["statut"] == "conforme")
        echoues = sum(1 for c in checks if c["statut"] == "non_conforme")
        na = sum(1 for c in checks if c["statut"] == "non_applicable")
        evalues = total - na

        score_global = (reussis / evalues * 100) if evalues else 0.0

        # Sous-scores par domaine
        ohada_codes = {"livre_journal", "grand_livre", "balance", "etats_financiers",
                       "registre_tiers", "inventaire_annuel", "conservation_10_ans"}
        dgi_codes = {"fne_facturation", "declaration_tva", "declaration_cnps",
                     "its_trimestriel", "liasse_fiscale", "piste_audit"}
        secu_codes = {"mfa_obligatoire", "protection_donnees"}

        def _score(codes: set[str]) -> float:
            sub = [c for c in checks if c["code"] in codes and c["statut"] != "non_applicable"]
            if not sub:
                return 100.0
            return sum(1 for c in sub if c["statut"] == "conforme") / len(sub) * 100

        score_ohada = _score(ohada_codes)
        score_dgi = _score(dgi_codes)
        score_securite = _score(secu_codes)

        # Findings associés
        findings_critiques = int(await self.db.scalar(
            select(func.count(AuditFinding.id)).where(
                AuditFinding.tenant_id == self.tenant_id,
                AuditFinding.severite == SeveriteFinding.CRITIQUE,
                AuditFinding.statut.in_([StatutFinding.NOUVEAU, StatutFinding.EN_COURS]),
            )
        ) or 0)
        findings_hauts = int(await self.db.scalar(
            select(func.count(AuditFinding.id)).where(
                AuditFinding.tenant_id == self.tenant_id,
                AuditFinding.severite == SeveriteFinding.HIGH,
                AuditFinding.statut.in_([StatutFinding.NOUVEAU, StatutFinding.EN_COURS]),
            )
        ) or 0)

        # Résumé IA
        resume = None
        if data.generer_resume_ia:
            resume = await self._generer_resume_conformite(
                score_global, score_ohada, score_dgi, score_securite,
                reussis, echoues, findings_critiques, findings_hauts, checks,
            )

        report = ComplianceReport(
            tenant_id=self.tenant_id,
            reference=reference,
            type_rapport=data.type_rapport,
            periode_debut=data.periode_debut,
            periode_fin=data.periode_fin,
            score_global=Decimal(str(round(score_global, 2))),
            score_ohada=Decimal(str(round(score_ohada, 2))),
            score_dgi=Decimal(str(round(score_dgi, 2))),
            score_securite=Decimal(str(round(score_securite, 2))),
            nb_checks_total=total,
            nb_checks_reussis=reussis,
            nb_checks_echoues=echoues,
            nb_checks_non_applicables=na,
            detail_checks=checks,
            nb_findings_critiques=findings_critiques,
            nb_findings_hauts=findings_hauts,
            resume_ia=resume,
            statut="brouillon",
            genere_par=self.user_id,
        )
        self.db.add(report)
        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="COMPLIANCE_REPORT_GENERATE",
            ressource="compliance_report",
            ressource_id=report.id,
            payload={"reference": reference, "score": score_global},
        )
        return ComplianceReportOut.model_validate(report)

    async def _executer_check_conformite(
        self, code: str, date_debut: date, date_fin: date
    ) -> dict[str, Any]:
        """Exécute un check individuel."""
        now = datetime.now(timezone.utc)

        if code == "livre_journal":
            nb = int(await self.db.scalar(
                select(func.count(Ecriture.id)).where(
                    Ecriture.tenant_id == self.tenant_id,
                    Ecriture.date_ecriture.between(date_debut, date_fin),
                )
            ) or 0)
            return {
                "statut": "conforme" if nb > 0 else "a_verifier",
                "preuve": f"{nb} écritures enregistrées sur la période",
                "derniere_verification": now,
                "commentaire": None,
            }

        if code == "piste_audit":
            verification = await self.verify_audit_chain(self.tenant_id)
            return {
                "statut": "conforme" if verification.integre else "non_conforme",
                "preuve": f"Chaîne : {verification.nb_entrees} entrées, intégrité={verification.integre}",
                "derniere_verification": now,
                "commentaire": None if verification.integre else "Altération détectée dans la chaîne",
            }

        if code == "fne_facturation":
            # Vérifier que toutes les factures validées ont une certification FNE
            total = int(await self.db.scalar(
                select(func.count(CustomerInvoice.id)).where(
                    CustomerInvoice.tenant_id == self.tenant_id,
                    CustomerInvoice.date_facture.between(date_debut, date_fin),
                    CustomerInvoice.statut.in_(["validee", "partiellement_payee", "payee"]),
                )
            ) or 0)
            if total == 0:
                return {"statut": "non_applicable", "preuve": "Aucune facture émise", "derniere_verification": now, "commentaire": None}
            certifiees = int(await self.db.scalar(
                select(func.count(FneInvoice.id))
                .join(CustomerInvoice, CustomerInvoice.id == FneInvoice.customer_invoice_id)
                .where(
                    FneInvoice.tenant_id == self.tenant_id,
                    FneInvoice.statut == "certifiee",
                    CustomerInvoice.date_facture.between(date_debut, date_fin),
                )
            ) or 0)
            taux = certifiees / total * 100
            return {
                "statut": "conforme" if taux >= 95 else "non_conforme",
                "preuve": f"{certifiees}/{total} factures certifiées ({taux:.1f}%)",
                "derniere_verification": now,
                "commentaire": None if taux >= 95 else f"Taux insuffisant : {taux:.1f}%",
            }

        if code == "mfa_obligatoire":
            from app.models.user import User
            admins = (
                await self.db.execute(
                    select(User).where(
                        User.tenant_id == self.tenant_id,
                        User.role.in_(["ADMIN_TENANT", "SUPER_ADMIN"]),
                        User.statut == "actif",
                    )
                )
            ).scalars().all()
            sans_mfa = sum(1 for u in admins if not u.mfa_enabled)
            return {
                "statut": "conforme" if sans_mfa == 0 else "non_conforme",
                "preuve": f"{len(admins) - sans_mfa}/{len(admins)} admins avec MFA",
                "derniere_verification": now,
                "commentaire": None if sans_mfa == 0 else f"{sans_mfa} admins sans MFA",
            }

        # Par défaut : à vérifier manuellement
        return {
            "statut": "a_verifier",
            "preuve": None,
            "derniere_verification": now,
            "commentaire": "Vérification manuelle requise",
        }

    async def _generer_resume_conformite(
        self, score_global: float, score_ohada: float, score_dgi: float,
        score_securite: float, reussis: int, echoues: int,
        critiques: int, hauts: int, checks: list[dict[str, Any]],
    ) -> str | None:
        """Génère un résumé IA du rapport."""
        from app.core.config import settings
        if not settings.nlp_enabled:
            return self._resume_fallback(score_global, reussis, echoues, critiques, hauts)

        try:
            from app.integrations.openai_client import get_openai_client
            client = get_openai_client()
            echecs = [c["libelle"] for c in checks if c["statut"] == "non_conforme"]
            prompt = f"""Rapport de conformité d'une entreprise ivoirienne :

- Score global : {score_global:.1f}%
- Score OHADA : {score_ohada:.1f}%
- Score DGI : {score_dgi:.1f}%
- Score sécurité : {score_securite:.1f}%
- Checks réussis : {reussis}, échoués : {echoues}
- Findings critiques ouverts : {critiques}
- Findings hauts ouverts : {hauts}
- Points non conformes : {', '.join(echecs) if echecs else 'aucun'}

Rédige un résumé en 3 phrases maximum, ton professionnel, à destination du dirigeant.
Termine par les 1-2 actions prioritaires à mener."""
            return await client.chat_text(
                "Tu es un expert-comptable OHADA et auditeur interne.",
                prompt, temperature=0.2, max_tokens=250,
            )
        except Exception:
            logger.exception("[audit] Résumé IA échoué")
            return self._resume_fallback(score_global, reussis, echoues, critiques, hauts)

    @staticmethod
    def _resume_fallback(
        score: float, reussis: int, echoues: int, critiques: int, hauts: int
    ) -> str:
        niveau = "excellent" if score >= 90 else "bon" if score >= 75 else "moyen" if score >= 60 else "insuffisant"
        msg = f"Votre niveau de conformité est {niveau} ({score:.0f}%). "
        msg += f"{reussis} contrôles réussis sur {reussis + echoues}. "
        if critiques > 0:
            msg += f"⚠️ {critiques} anomalie(s) critique(s) à traiter en priorité."
        elif hauts > 0:
            msg += f"{hauts} anomalie(s) haute(s) à corriger rapidement."
        else:
            msg += "Aucune anomalie critique ou haute en attente."
        return msg

    # ═════════════════════════════════════════════════════════════════════
    # DASHBOARD
    # ═════════════════════════════════════════════════════════════════════
    async def dashboard(self) -> AuditDashboardOut:
        """Vue d'ensemble du contrôle interne."""
        today = date.today()

        # Compteurs findings
        nouveaux = int(await self.db.scalar(
            select(func.count(AuditFinding.id)).where(
                AuditFinding.tenant_id == self.tenant_id,
                AuditFinding.statut == StatutFinding.NOUVEAU,
            )
        ) or 0)
        en_cours = int(await self.db.scalar(
            select(func.count(AuditFinding.id)).where(
                AuditFinding.tenant_id == self.tenant_id,
                AuditFinding.statut == StatutFinding.EN_COURS,
            )
        ) or 0)
        critiques = int(await self.db.scalar(
            select(func.count(AuditFinding.id)).where(
                AuditFinding.tenant_id == self.tenant_id,
                AuditFinding.severite == SeveriteFinding.CRITIQUE,
                AuditFinding.statut.in_([StatutFinding.NOUVEAU, StatutFinding.EN_COURS]),
            )
        ) or 0)
        hauts = int(await self.db.scalar(
            select(func.count(AuditFinding.id)).where(
                AuditFinding.tenant_id == self.tenant_id,
                AuditFinding.severite == SeveriteFinding.HIGH,
                AuditFinding.statut.in_([StatutFinding.NOUVEAU, StatutFinding.EN_COURS]),
            )
        ) or 0)

        # Top 5 règles déclenchantes
        top_rows = (
            await self.db.execute(
                select(AuditRule.code, AuditRule.libelle, func.count(AuditFinding.id).label("n"))
                .join(AuditFinding, AuditFinding.rule_id == AuditRule.id)
                .where(
                    AuditFinding.tenant_id == self.tenant_id,
                    AuditFinding.created_at >= datetime.now(timezone.utc) - timedelta(days=30),
                )
                .group_by(AuditRule.code, AuditRule.libelle)
                .order_by(desc("n"))
                .limit(5)
            )
        ).all()
        top_5 = [{"code": r.code, "libelle": r.libelle, "nb_findings": int(r.n)} for r in top_rows]

        # Dernier rapport conformité
        last_report = await self.db.scalar(
            select(ComplianceReport)
            .where(ComplianceReport.tenant_id == self.tenant_id)
            .order_by(desc(ComplianceReport.created_at))
            .limit(1)
        )
        score = float(last_report.score_global) if last_report else 0.0

        # Dernière exécution
        last_run = await self.db.scalar(
            select(AuditRun)
            .where(AuditRun.tenant_id == self.tenant_id)
            .order_by(desc(AuditRun.created_at))
            .limit(1)
        )

        # Vérification hash-chain
        try:
            verification = await self.verify_audit_chain(self.tenant_id, limit=1000)
            hash_ok = verification.integre
        except Exception:
            hash_ok = False

        # Tendance 30j (findings par jour)
        tendance = []
        for i in range(30, 0, -1):
            d = today - timedelta(days=i)
            nb = int(await self.db.scalar(
                select(func.count(AuditFinding.id)).where(
                    AuditFinding.tenant_id == self.tenant_id,
                    func.date(AuditFinding.created_at) == d,
                )
            ) or 0)
            tendance.append({"date": d.isoformat(), "nb": nb})

        return AuditDashboardOut(
            tenant_id=self.tenant_id,
            date_arret=today,
            nb_findings_nouveaux=nouveaux,
            nb_findings_en_cours=en_cours,
            nb_findings_critiques=critiques,
            nb_findings_hauts=hauts,
            top_5_regles_declenchantes=top_5,
            score_conformite_actuel=score,
            derniere_execution_at=last_run.created_at if last_run else None,
            derniere_verification_hash_chain=datetime.now(timezone.utc) if hash_ok else None,
            hash_chain_integre=hash_ok,
            tendance_30j=tendance,
        )

    # ═════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═════════════════════════════════════════════════════════════════════
    async def _get_rule(self, rule_id: UUID) -> AuditRule:
        rule = await self.db.scalar(
            select(AuditRule).where(
                AuditRule.id == rule_id,
                or_(
                    AuditRule.tenant_id == self.tenant_id,
                    AuditRule.tenant_id.is_(None),
                ),
            )
        )
        if rule is None:
            raise HTTPException(404, "Règle d'audit introuvable")
        return rule

    async def _get_finding(self, finding_id: UUID) -> AuditFinding:
        f = await self.db.scalar(
            select(AuditFinding).where(
                AuditFinding.id == finding_id,
                AuditFinding.tenant_id == self.tenant_id,
            )
        )
        if f is None:
            raise HTTPException(404, "Finding introuvable")
        return f


# Import en fin de fichier pour éviter les cycles
from app.schemas.audit_internal import (
    AuditTrailOut,  # noqa: E402
)
