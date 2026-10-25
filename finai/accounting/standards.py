"""Profils par zone géographique / référentiel comptable et retraitements entre normes.

IMPORTANT (honnêteté scientifique) : les retraitements ci-dessous sont des APPROXIMATIONS
pédagogiques pour comparer des indicateurs ; ils ne remplacent ni un retraitement complet
selon IFRS 1 / ASC, ni l'avis d'un auditeur. Les taux d'impôt sont indicatifs et à vérifier
auprès de l'administration fiscale compétente avant tout usage professionnel.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from .sig import calculer_sig
from .statement import Statement


@dataclass(frozen=True)
class ZoneProfile:
    cle: str
    zone: str
    referentiel: str
    devise: str
    taux_is_indicatif: float           # taux d'impôt sur les sociétés indicatif (à vérifier)
    presentation: str                  # nature / fonction
    indicateur_operationnel: str       # libellé de l'indicateur clé de performance opérationnelle
    differences: tuple[str, ...]


ZONES: dict[str, ZoneProfile] = {
    "OHADA": ZoneProfile(
        "OHADA", "Afrique (OHADA — Côte d'Ivoire)", "SYSCOHADA révisé", "XOF", 0.25, "nature",
        "Excédent Brut d'Exploitation (EBE)",
        ("Compte de résultat par nature avec cascade de SIG (EBE, résultat d'exploitation, RAO).",
         "Distinction activités ordinaires / hors activités ordinaires (HAO).",
         "Crédit-bail et locations : charge d'exploitation (pas de capitalisation systématique).",
         "Frais de développement : traitement selon le plan comptable (activation possible sous conditions).")),
    "IFRS_AU": ZoneProfile(
        "IFRS_AU", "Australie", "Normes comptables australiennes (AASB, alignées sur les IFRS)", "AUD",
        0.30, "fonction", "EBITDA (indicateur non normé)",
        ("Pas de rubrique « éléments extraordinaires » (IAS 1).",
         "Contrats de location : actif de droit d'usage et dette au bilan (IFRS 16) ; loyers retirés de l'EBITDA.",
         "Frais de développement activés si les critères d'IAS 38 sont remplis.",
         "FIFO ou coût moyen pondéré ; LIFO interdit (IAS 2).")),
    "IND_AS": ZoneProfile(
        "IND_AS", "Inde", "Ind AS (convergées avec les IFRS)", "INR", 0.2517, "fonction",
        "EBITDA (indicateur non normé)",
        ("Ind AS 116 : traitement des locations proche d'IFRS 16.",
         "Pas de rubrique « éléments extraordinaires ».",
         "Frais de développement activés si les critères d'Ind AS 38 sont remplis.",
         "LIFO non autorisé.")),
    "CAS_CN": ZoneProfile(
        "CAS_CN", "Chine", "CAS — Chinese Accounting Standards (convergées avec les IFRS)", "CNY",
        0.25, "fonction", "Résultat d'exploitation (营业利润, présentation CAS)",
        ("Présentation par fonction ; le « résultat d'exploitation » CAS intègre notamment les charges "
         "financières et certains produits d'investissement (à vérifier selon le modèle d'états).",
         "Traitement des locations proche d'IFRS 16 (CAS 21).",
         "Reprise de dépréciation des stocks admise, limites strictes sur d'autres actifs.")),
    "US_GAAP": ZoneProfile(
        "US_GAAP", "États-Unis", "US GAAP (ASC)", "USD", 0.21, "fonction",
        "Operating income (EBITDA = mesure non-GAAP)",
        ("LIFO autorisé pour les stocks (réserve LIFO à présenter).",
         "ASC 842 : les loyers d'exploitation restent une charge d'exploitation unique (EBITDA moins élevé qu'en IFRS 16).",
         "Frais de R&D passés en charges (hors logiciels), pas d'activation IAS 38.",
         "Pas d'éléments extraordinaires depuis 2015 (ASU 2015-01).")),
}


def get_zone(cle: str) -> ZoneProfile:
    if cle not in ZONES:
        raise ValueError(f"Zone inconnue « {cle} ». Zones disponibles : {', '.join(ZONES)}.")
    return ZONES[cle]


def _ebitda_base(s: Statement) -> float:
    sig = calculer_sig(s)
    return sig["resultat_exploitation"] + s.dotations_amort_prov


def indicateurs_par_norme(s: Statement) -> dict[str, dict[str, float]]:
    """Indicateurs-clés tels qu'ils ressortiraient sous chaque référentiel (approximation).

    Hypothèses documentées :
    - SYSCOHADA : EBE de la cascade des SIG ; locations en charge d'exploitation.
    - IFRS / Ind AS / CAS : EBITDA + loyers retirés de la charge (IFRS 16) ; frais de développement
      activés (réduction des charges, gain d'EBITDA).
    - US GAAP : loyers d'exploitation conservés en charges ; R&D non activée ; stocks ramenés au coût
      LIFO tel que publié (la réserve LIFO est fournie pour retraitement FIFO).
    """
    sig = calculer_sig(s)
    ebitda_local = _ebitda_base(s)
    ebitda_ifrs = ebitda_local + s.loyers_credit_bail + s.frais_dev_actives
    resultats = {
        "OHADA": {"indicateur_operationnel": sig["excedent_brut_exploitation"],
                  "resultat_exploitation": sig["resultat_exploitation"],
                  "resultat_net": sig["resultat_net"], "stocks": s.stocks},
        "US_GAAP": {"indicateur_operationnel": ebitda_local,
                    "resultat_exploitation": sig["resultat_exploitation"],
                    "resultat_net": sig["resultat_net"], "stocks": s.stocks},
    }
    for cle in ("IFRS_AU", "IND_AS", "CAS_CN"):
        amort_droit_usage_estime = s.loyers_credit_bail * 0.85
        resultat_expl = sig["resultat_exploitation"] + s.loyers_credit_bail - amort_droit_usage_estime \
            + s.frais_dev_actives
        resultats[cle] = {"indicateur_operationnel": ebitda_ifrs,
                          "resultat_exploitation": resultat_expl,
                          "resultat_net": sig["resultat_net"] + (resultat_expl - sig["resultat_exploitation"])
                          * (1 - get_zone(cle).taux_is_indicatif),
                          "stocks": s.stocks}
    # US GAAP : stocks retraités FIFO pour comparaison
    resultats["US_GAAP"]["stocks_fifo"] = s.stocks + s.reserve_lifo
    return resultats


def retraiter_ifrs16(s: Statement, taux_actualisation: float = 0.08, duree_moy: float = 5.0) -> Statement:
    """Capitalise les loyers (approx. IFRS 16) : ajoute actif de droit d'usage et dette locative.

    Dette ≈ valeur actuelle d'une annuité de loyers (loyer annuel × facteur d'annuité sur `duree_moy`
    années au taux `taux_actualisation`). Le droit d'usage est égal à la dette (début de contrat).
    La charge de loyer est remplacée par amortissement + intérêts (dans les mêmes proportions que
    `indicateurs_par_norme`). Approximation de comparaison, non utilisable en reporting.
    """
    if s.loyers_credit_bail <= 0:
        return replace(s)
    r, n = taux_actualisation, duree_moy
    facteur = (1 - (1 + r) ** (-n)) / r if r > 0 else n
    dette = s.loyers_credit_bail * facteur
    return replace(s, immobilisations_nettes=s.immobilisations_nettes + dette,
                   dettes_financieres_lt=s.dettes_financieres_lt + dette,
                   autres_charges=max(0.0, s.autres_charges - s.loyers_credit_bail),
                   dotations_amort_prov=s.dotations_amort_prov + dette / n,
                   charges_financieres=s.charges_financieres + dette * r)
