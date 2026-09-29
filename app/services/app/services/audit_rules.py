"""
Handlers d'exécution des règles d'audit.

Chaque handler reçoit :
- service : l'instance AuditInternalService (pour accéder à db, tenant_id)
- rule : la règle à exécuter
- date_debut, date_fin : la période
- max_findings : limite

Et retourne une liste de dicts finding.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Awaitable
from uuid import UUID

from sqlalchemy import func, select

from app.core.audit_syscohada import SeveriteFinding, TypeRegleAudit
from app.models.audit_internal import AuditRule
from app.models.ecriture import Ecriture, EcritureLigne
from app.models.exercice import Exercice
from app.models.plan_comptable import PlanComptable

logger = logging.getLogger(__name__)

HandlerType = Callable[..., Awaitable[list[dict[str, Any]]]]


# ═════════════════════════════════════════════════════════════════════════════
# COHÉRENCE COMPTABLE
# ═════════════════════════════════════════════════════════════════════════════
async def check_ecriture_desequilibree(
    service, rule: AuditRule, date_debut: date, date_fin: date, max_findings: int
) -> list[dict[str, Any]]:
    """Détecte les écritures déséquilibrées (debit ≠ credit)."""
    stmt = (
        select(
            Ecriture.id,
            Ecriture.numero_piece,
            Ecriture.date_ecriture,
            Ecriture.libelle,
            func.coalesce(func.sum(EcritureLigne.debit_xof), 0).label("total_debit"),
            func.coalesce(func.sum(EcritureLigne.credit_xof), 0).label("total_credit"),
        )
        .join(EcritureLigne, EcritureLigne.ecriture_id == Ecriture.id)
        .where(
            Ecriture.tenant_id == service.tenant_id,
            Ecriture.date_ecriture.between(date_debut, date_fin),
        )
        .group_by(Ecriture.id, Ecriture.numero_piece, Ecriture.date_ecriture, Ecriture.libelle)
        .having(func.sum(EcritureLigne.debit_xof) != func.sum(EcritureLigne.credit_xof))
        .limit(max_findings)
    )
    rows = (await service.db.execute(stmt)).all()

    findings = []
    for r in rows:
        debit = int(r.total_debit)
        credit = int(r.total_credit)
        ecart = debit - credit
        findings.append({
            "titre": f"Écriture déséquilibrée {r.numero_piece}",
            "description": (
                f"Écriture du {r.date_ecriture} : débit={debit}, crédit={credit}, "
                f"écart={ecart} FCFA. Règle fondamentale SYSCOHADA violée."
            ),
            "severite": SeveriteFinding.CRITIQUE,
            "ressource_type": "ecriture",
            "ressource_id": r.id,
            "ressource_ref": r.numero_piece,
            "donnees": {"debit": debit, "credit": credit, "ecart": ecart, "libelle": r.libelle},
            "recommandation": "Corriger l'écriture ou la valider en brouillon.",
            "impact_estime": abs(ecart),
        })
    return findings


async def check_ecriture_sans_ligne(
    service, rule: AuditRule, date_debut: date, date_fin: date, max_findings: int
) -> list[dict[str, Any]]:
    """Détecte les écritures sans aucune ligne."""
    stmt = (
        select(Ecriture)
        .outerjoin(EcritureLigne, EcritureLigne.ecriture_id == Ecriture.id)
        .where(
            Ecriture.tenant_id == service.tenant_id,
            Ecriture.date_ecriture.between(date_debut, date_fin),
            EcritureLigne.id.is_(None),
        )
        .limit(max_findings)
    )
    rows = (await service.db.execute(stmt)).scalars().all()

    return [
        {
            "titre": f"Écriture sans ligne {e.numero_piece}",
            "description": f"L'écriture {e.numero_piece} du {e.date_ecriture} n'a aucune ligne.",
            "severite": SeveriteFinding.HIGH,
            "ressource_type": "ecriture",
            "ressource_id": e.id,
            "ressource_ref": e.numero_piece,
            "donnees": {"libelle": e.libelle, "statut": e.statut},
            "recommandation": "Supprimer l'écriture vide ou compléter les lignes.",
        }
        for e in rows
    ]


async def check_exercice_cloture_modifie(
    service, rule: AuditRule, date_debut: date, date_fin: date, max_findings: int
) -> list[dict[str, Any]]:
    """Détecte les écritures créées dans un exercice clôturé."""
    stmt = (
        select(Ecriture, Exercice)
        .join(Exercice, Exercice.id == Ecriture.exercice_id)
        .where(
            Ecriture.tenant_id == service.tenant_id,
            Exercice.cloture.is_(True),
            Ecriture.date_ecriture.between(date_debut, date_fin),
        )
        .limit(max_findings)
    )
    rows = (await service.db.execute(stmt)).all()

    return [
        {
            "titre": f"Écriture dans exercice clôturé {ex.libelle}",
            "description": (
                f"Écriture {e.numero_piece} créée dans l'exercice clôturé {ex.libelle}. "
                f"Violation du principe d'intangibilité."
            ),
            "severite": SeveriteFinding.HIGH,
            "ressource_type": "ecriture",
            "ressource_id": e.id,
            "ressource_ref": e.numero_piece,
            "donnees": {"exercice": ex.libelle, "date_cloture": str(ex.cloture_at)},
            "recommandation": "Extourner l'écriture ou la reclasser dans l'exercice courant.",
        }
        for e, ex in rows
    ]


# ═════════════════════════════════════════════════════════════════════════════
# INTÉGRITÉ
# ═════════════════════════════════════════════════════════════════════════════
async def check_ecriture_doublon(
    service, rule: AuditRule, date_debut: date, date_fin: date, max_findings: int
) -> list[dict[str, Any]]:
    """Détecte les écritures avec le même montant + libellé + date proche."""
    params = rule.parametres or {}
    fenetre_jours = params.get("fenetre_jours", 3)

    stmt = (
        select(
            Ecriture.numero_piece,
            Ecriture.date_ecriture,
            Ecriture.libelle,
            func.sum(EcritureLigne.debit_xof).label("montant"),
            func.count(Ecriture.id).label("nb"),
        )
        .join(EcritureLigne, EcritureLigne.ecriture_id == Ecriture.id)
        .where(
            Ecriture.tenant_id == service.tenant_id,
            Ecriture.date_ecriture.between(date_debut, date_fin),
            Ecriture.statut == "validee",
        )
        .group_by(Ecriture.numero_piece, Ecriture.date_ecriture, Ecriture.libelle)
        .having(func.count(Ecriture.id) > 1)
        .limit(max_findings)
    )
    rows = (await service.db.execute(stmt)).all()

    findings = []
    for r in rows:
        findings.append({
            "titre": f"Doublon potentiel : {r.libelle[:60]}",
            "description": (
                f"{r.nb} écritures identiques : '{r.libelle}' "
                f"pour {int(r.montant)} FCFA le {r.date_ecriture}."
            ),
            "severite": SeveriteFinding.MEDIUM,
            "ressource_type": "ecriture",
            "ressource_ref": r.numero_piece,
            "donnees": {"libelle": r.libelle, "montant": int(r.montant), "nb": int(r.nb)},
            "recommandation": "Vérifier s'il s'agit d'une double saisie.",
            "impact_estime": int(r.montant) * (int(r.nb) - 1),
        })
    return findings


async def check_compte_non_lettre_ancien(
    service, rule: AuditRule, date_debut: date, date_fin: date, max_findings: int
) -> list[dict[str, Any]]:
    """Détecte les lignes de tiers non lettrées depuis longtemps."""
    params = rule.parametres or {}
    jours = params.get("jours", 90)
    seuil_date = date.today() - timedelta(days=jours)

    stmt = (
        select(EcritureLigne, Ecriture, PlanComptable)
        .join(Ecriture, Ecriture.id == EcritureLigne.ecriture_id)
        .join(PlanComptable, PlanComptable.id == EcritureLigne.compte_id)
        .where(
            EcritureLigne.tenant_id == service.tenant_id,
            PlanComptable.classe == 4,
            EcritureLigne.lettrage_code.is_(None),
            Ecriture.date_ecriture < seuil_date,
            Ecriture.statut == "validee",
        )
        .limit(max_findings)
    )
    rows = (await service.db.execute(stmt)).all()

    return [
        {
            "titre": f"Compte tiers {pc.compte} non lettré > {jours}j",
            "description": (
                f"Ligne du {e.date_ecriture} sur le compte {pc.compte} ({pc.libelle}) "
                f"non lettrée depuis plus de {jours} jours."
            ),
            "severite": SeveriteFinding.LOW,
            "ressource_type": "ecriture_ligne",
            "ressource_id": el.id,
            "ressource_ref": e.numero_piece,
            "donnees": {
                "compte": pc.compte,
                "libelle": pc.libelle,
                "date_ecriture": str(e.date_ecriture),
                "montant": int(el.debit_xof or el.credit_xof),
            },
            "recommandation": "Rapprocher avec le règlement ou provisionner si irrécouvrable.",
        }
        for el, e, pc in rows
    ]


# ═════════════════════════════════════════════════════════════════════════════
# CONFORMITÉ FISCALE
# ═════════════════════════════════════════════════════════════════════════════
async def check_facture_sans_fne(
    service, rule: AuditRule, date_debut: date, date_fin: date, max_findings: int
) -> list[dict[str, Any]]:
    """Détecte les factures clients validées sans certification FNE."""
    from app.models.fne import FneInvoice
    from app.models.sale import CustomerInvoice

    stmt = (
        select(CustomerInvoice)
        .outerjoin(FneInvoice, FneInvoice.customer_invoice_id == CustomerInvoice.id)
        .where(
            CustomerInvoice.tenant_id == service.tenant_id,
            CustomerInvoice.date_facture.between(date_debut, date_fin),
            CustomerInvoice.statut.in_(["validee", "partiellement_payee", "payee"]),
            FneInvoice.id.is_(None),
        )
        .limit(max_findings)
    )
    rows = (await service.db.execute(stmt)).scalars().all()

    return [
        {
            "titre": f"Facture {inv.numero} sans certification FNE",
            "description": (
                f"Facture {inv.numero} du {inv.date_facture} ({inv.total_ttc} FCFA) "
                f"non certifiée FNE. Non-conformité fiscale depuis le 01/07/2025."
            ),
            "severite": SeveriteFinding.HIGH,
            "ressource_type": "customer_invoice",
            "ressource_id": inv.id,
            "ressource_ref": inv.numero,
            "donnees": {"date_facture": str(inv.date_facture), "total_ttc": inv.total_ttc},
            "recommandation": "Certifier la facture immédiatement via /api/v1/fne/certify.",
            "impact_estime": inv.total_ttc,
        }
        for inv in rows
    ]


async def check_declaration_dgi_retard(
    service, rule: AuditRule, date_debut: date, date_fin: date, max_findings: int
) -> list[dict[str, Any]]:
    """Détecte les déclarations DGI en retard."""
    from app.models.payroll import DgiDeclaration

    today = date.today()
    stmt = (
        select(DgiDeclaration)
        .where(
            DgiDeclaration.tenant_id == service.tenant_id,
            DgiDeclaration.date_echeance < today,
            DgiDeclaration.statut.in_(["brouillon"]),
        )
        .limit(max_findings)
    )
    rows = (await service.db.execute(stmt)).scalars().all()

    return [
        {
            "titre": f"Déclaration {d.type_declaration.upper()} en retard",
            "description": (
                f"Déclaration {d.type_declaration} {d.periode} non déposée. "
                f"Échéance : {d.date_echeance} ({(today - d.date_echeance).days} jours de retard)."
            ),
            "severite": SeveriteFinding.HIGH,
            "ressource_type": "dgi_declaration",
            "ressource_id": d.id,
            "ressource_ref": f"{d.type_declaration}-{d.periode}",
            "donnees": {
                "type": d.type_declaration,
                "periode": d.periode,
                "echeance": str(d.date_echeance),
                "montant": d.montant_net,
            },
            "recommandation": "Déposer immédiatement la déclaration pour éviter les pénalités.",
            "impact_estime": d.montant_net,
        }
        for d in rows
    ]


# ═════════════════════════════════════════════════════════════════════════════
# FRAUDE
# ═════════════════════════════════════════════════════════════════════════════
async def check_loi_benford(
    service, rule: AuditRule, date_debut: date, date_fin: date, max_findings: int
) -> list[dict[str, Any]]:
    """Analyse la conformité à la loi de Benford."""
    from app.schemas.audit_internal import BenfordAnalysisRequest

    try:
        analysis = await service.analyser_benford(BenfordAnalysisRequest(
            periode_debut=date_debut, periode_fin=date_fin,
        ))
    except Exception as exc:
        logger.info(f"[audit] Benford impossible : {exc}")
        return []

    if analysis.conforme:
        return []

    return [{
        "titre": f"Distribution non conforme à la loi de Benford",
        "description": (
            f"Score de conformité : {analysis.score_conformite:.2%}. "
            f"Chi² = {analysis.chi_square:.2f} (critique : 15.51). "
            f"{len(analysis.anomalies)} chiffres anormaux détectés. "
            f"Indication possible de fraude ou d'erreurs systématiques."
        ),
        "severite": SeveriteFinding.MEDIUM,
        "ressource_type": "benford_analysis",
        "ressource_id": analysis.id,
        "donnees": {
            "score": float(analysis.score_conformite),
            "chi_square": float(analysis.chi_square),
            "anomalies": analysis.anomalies,
        },
        "recommandation": "Analyser les écritures suspectes manuellement.",
    }]


async def check_montants_juste_sous_seuil(
    service, rule: AuditRule, date_debut: date, date_fin: date, max_findings: int
) -> list[dict[str, Any]]:
    """Détecte les montants juste sous un seuil fiscal."""
    params = rule.parametres or {}
    tolerance = params.get("tolerance", 1000)

    result = await service.detecter_montants_sous_seuil(
        date_debut, date_fin, seuil=5_000_000, tolerance=tolerance
    )
    if result.nb_transactions == 0:
        return []

    return [{
        "titre": f"{result.nb_transactions} transactions juste sous 5 000 000 FCFA",
        "description": (
            f"Détection de {result.nb_transactions} transactions à moins de "
            f"{tolerance} FCFA du seuil de 5 000 000. Possible fractionnement "
            f"pour éviter le contrôle DGI."
        ),
        "severite": SeveriteFinding.MEDIUM,
        "ressource_type": "ecriture",
        "donnees": {
            "seuil": result.seuil,
            "nb_transactions": result.nb_transactions,
            "montant_total": result.montant_total,
            "transactions": result.transactions[:20],
        },
        "recommandation": "Vérifier la réalité économique des transactions.",
        "impact_estime": result.montant_total,
    }]


async def check_transactions_circulaires(
    service, rule: AuditRule, date_debut: date, date_fin: date, max_findings: int
) -> list[dict[str, Any]]:
    """Détecte les cycles A → B → A."""
    cycles = await service.detecter_circulaires(date_debut, date_fin)
    return [
        {
            "titre": f"Transaction circulaire suspecte",
            "description": (
                f"Cycle de {c.nb_operations} opérations sur {c.periode_jours} jours, "
                f"montant total {c.montant_total} FCFA."
            ),
            "severite": SeveriteFinding.HIGH,
            "ressource_type": "ecriture",
            "donnees": {"cycle": c.cycle, "score_suspicion": c.score_suspicion},
            "recommandation": "Investigation manuelle requise.",
            "impact_estime": c.montant_total,
        }
        for c in cycles[:max_findings]
    ]


# ═════════════════════════════════════════════════════════════════════════════
# PERFORMANCE
# ═════════════════════════════════════════════════════════════════════════════
async def check_ecriture_non_validee_ancienne(
    service, rule: AuditRule, date_debut: date, date_fin: date, max_findings: int
) -> list[dict[str, Any]]:
    """Détecte les écritures en brouillon depuis trop longtemps."""
    params = rule.parametres or {}
    jours = params.get("jours", 30)
    seuil_date = date.today() - timedelta(days=jours)

    stmt = (
        select(Ecriture)
        .where(
            Ecriture.tenant_id == service.tenant_id,
            Ecriture.statut == "brouillon",
            Ecriture.date_ecriture < seuil_date,
        )
        .limit(max_findings)
    )
    rows = (await service.db.execute(stmt)).scalars().all()

    return [
        {
            "titre": f"Écriture brouillon depuis > {jours} jours",
            "description": (
                f"Écriture {e.numero_piece} du {e.date_ecriture} toujours en brouillon "
                f"après {(date.today() - e.date_ecriture).days} jours."
            ),
            "severite": SeveriteFinding.LOW,
            "ressource_type": "ecriture",
            "ressource_id": e.id,
            "ressource_ref": e.numero_piece,
            "donnees": {"date": str(e.date_ecriture), "libelle": e.libelle},
            "recommandation": "Valider ou annuler l'écriture.",
        }
        for e in rows
    ]


# ═════════════════════════════════════════════════════════════════════════════
# REGISTRE DES HANDLERS
# ═════════════════════════════════════════════════════════════════════════════
AUDIT_RULE_HANDLERS: dict[str, HandlerType] = {
    TypeRegleAudit.ECRITURE_DESEQUILIBREE: check_ecriture_desequilibree,
    TypeRegleAudit.ECRITURE_SANS_LIGNE: check_ecriture_sans_ligne,
    TypeRegleAudit.EXERCICE_CLOTURE_MODIFIE: check_exercice_cloture_modifie,
    TypeRegleAudit.ECRITURE_DOUBLON: check_ecriture_doublon,
    TypeRegleAudit.COMPTE_NON_LETTRE_ANCIEN: check_compte_non_lettre_ancien,
    TypeRegleAudit.FACTURE_SANS_FNE: check_facture_sans_fne,
    TypeRegleAudit.DECLARATION_DGI_RETARD: check_declaration_dgi_retard,
    TypeRegleAudit.LOI_BENFORD: check_loi_benford,
    TypeRegleAudit.MONTANTS_JUSTE_SOUS_SEUIL: check_montants_juste_sous_seuil,
    TypeRegleAudit.TRANSACTIONS_CIRCULAIRES: check_transactions_circulaires,
    TypeRegleAudit.ECRITURE_NON_VALIDEE_ANCIENNE: check_ecriture_non_validee_ancienne,
    # À implémenter en V2 : TVA_MANQUANTE, RAS_NON_DECLAREE, etc.
}
