"""Ratios financiers, BFR/FR/Trésorerie nette, Altman Z'' et Beneish M-score.

Références :
- Altman, E. (1968, 1983, 1995) — Z-score ; ici la version Z'' (entreprises non cotées / non
  industrielles) : Z'' = 6,56·X1 + 3,26·X2 + 6,72·X3 + 1,05·X4 ; zones : >2,6 saine ; 1,1–2,6 grise ;
  <1,1 détresse.
- Beneish, M. (1999) — M-score à 8 variables ; seuil usuel −1,78 (au-dessus : risque de manipulation).
Les seuils sont des repères usuels de la littérature, pas des normes réglementaires.
"""
from __future__ import annotations

import math
from typing import Optional

from .sig import calculer_sig
from .statement import Statement


def _div(a: float, b: float, defaut: float = float("nan")) -> float:
    return a / b if b not in (0, 0.0) and not math.isnan(b) else defaut


def equilibre_financier(s: Statement) -> dict[str, float]:
    """FR, BFR et trésorerie nette (logique SYSCOHADA) avec l'identité TN = FR − BFR.

    FR  = capitaux stables (capitaux propres + dettes financières LT) − immobilisations nettes
    BFR = (stocks + créances clients + autres créances) − dettes d'exploitation CT
    TN  = trésorerie actif − (trésorerie passif + dettes financières CT)
    """
    fr = s.capitaux_propres + s.dettes_financieres_lt - s.immobilisations_nettes
    bfr = s.stocks + s.creances_clients + s.autres_creances - s.dettes_exploitation_ct
    tn = s.tresorerie_actif - s.tresorerie_passif - s.dettes_financieres_ct
    return {"fonds_roulement": fr, "bfr": bfr, "tresorerie_nette": tn,
            "controle_fr_moins_bfr": fr - bfr - tn}


def cycle_exploitation(s: Statement) -> dict[str, float]:
    """DSO, DIO, DPO, cycle de conversion de trésorerie et BFR en jours de CA."""
    ca = s.chiffre_affaires
    achats = s.achats_marchandises + s.achats_matieres + s.autres_achats
    dso = _div(s.creances_clients, ca) * 365
    dio = _div(s.stocks, max(achats, 1e-9)) * 365 if achats > 0 else float("nan")
    dpo = _div(s.dettes_fournisseurs, achats + s.services_exterieurs + s.transports) * 365
    bfr = equilibre_financier(s)["bfr"]
    return {"dso_jours": dso, "dio_jours": dio, "dpo_jours": dpo,
            "ccc_jours": (0 if math.isnan(dio) else dio) + dso - dpo,
            "bfr_jours_ca": _div(bfr, ca) * 365}


def ratios_financiers(s: Statement) -> dict[str, float]:
    sig = calculer_sig(s)
    ca, ta, cp = s.chiffre_affaires, s.total_actif, s.capitaux_propres
    pc = s.passif_courant
    ebe = sig["excedent_brut_exploitation"]
    capitaux_investis = cp + s.dettes_financieres_lt
    return {
        # liquidité
        "ratio_liquidite_generale": _div(s.actif_courant, pc),
        "ratio_liquidite_reduite": _div(s.creances_clients + s.autres_creances + s.tresorerie_actif, pc),
        "ratio_liquidite_immediate": _div(s.tresorerie_actif, pc),
        # rentabilité
        "marge_nette": _div(sig["resultat_net"], ca),
        "marge_ebe": _div(ebe, ca),
        "marge_exploitation": _div(sig["resultat_exploitation"], ca),
        "roa": _div(sig["resultat_net"], ta),
        "roe": _div(sig["resultat_net"], cp),
        "roce": _div(sig["resultat_exploitation"], capitaux_investis),
        "rotation_actif": _div(ca, ta),
        # solvabilité / structure
        "autonomie_financiere": _div(cp, ta),
        "endettement_cp": _div(s.dettes_financieres, cp),
        "dettes_nettes_sur_ebe": _div(s.dettes_financieres - s.tresorerie_actif, ebe),
        "couverture_interets": _div(sig["resultat_exploitation"], s.charges_financieres),
        "capacite_remboursement_ans": _div(s.dettes_financieres, sig["cafg"]),
        "poids_dettes_totales": _div(ta - cp, ta),
        "marge_valeur_ajoutee": _div(sig["valeur_ajoutee"], ca),
    }


def altman_z2(s: Statement) -> dict[str, float | str]:
    ta = s.total_actif
    if ta <= 0:
        return {"z": float("nan"), "zone": "indéterminée"}
    sig = calculer_sig(s)
    wc = s.actif_courant - s.passif_courant
    reserves = s.capitaux_propres - s.capital_social
    dettes_totales = max(ta - s.capitaux_propres, 1e-9)
    x1, x2 = wc / ta, reserves / ta
    x3, x4 = sig["resultat_exploitation"] / ta, s.capitaux_propres / dettes_totales
    z = 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4
    zone = "saine" if z > 2.6 else ("grise" if z >= 1.1 else "détresse")
    return {"z": z, "zone": zone, "x1": x1, "x2": x2, "x3": x3, "x4": x4}


def beneish_m(courant: Statement, precedent: Statement) -> Optional[dict[str, float | str]]:
    """M-score de Beneish (8 variables) — approximation à partir du schéma interne.

    Approximations : COGS = achats consommés ; SGA = services extérieurs + autres charges ;
    CFO ≈ résultat net + dotations − Δ(BFR). Retourne None si une variable est indéfinie.
    """
    def cogs(s: Statement) -> float:
        return (s.achats_marchandises - s.var_stock_marchandises + s.achats_matieres
                - s.var_stock_matieres + s.autres_achats)

    def sga(s: Statement) -> float:
        return s.services_exterieurs + s.autres_charges

    def ppe_ratio(s: Statement) -> float:
        return _div(s.immobilisations_nettes, s.immobilisations_nettes + s.dotations_amort_prov)

    def depi(s: Statement) -> float:
        return _div(s.dotations_amort_prov, s.dotations_amort_prov + s.immobilisations_nettes)

    c, p = courant, precedent
    try:
        dsri = _div(_div(c.creances_clients, c.chiffre_affaires), _div(p.creances_clients, p.chiffre_affaires))
        gm_c, gm_p = _div(c.chiffre_affaires - cogs(c), c.chiffre_affaires), \
            _div(p.chiffre_affaires - cogs(p), p.chiffre_affaires)
        gmi = _div(gm_p, gm_c)
        aq_c = 1 - _div(c.actif_courant + c.immobilisations_nettes, c.total_actif)
        aq_p = 1 - _div(p.actif_courant + p.immobilisations_nettes, p.total_actif)
        # Le schéma interne n'a qu'une catégorie d'immobilisations : si aucun actif « autre » n'existe
        # aux deux dates, l'indice de qualité des actifs est neutre (1,0).
        aqi = 1.0 if abs(aq_c) < 1e-9 and abs(aq_p) < 1e-9 else _div(aq_c, aq_p)
        sgi = _div(c.chiffre_affaires, p.chiffre_affaires)
        depi_v = _div(depi(p), depi(c))
        sgai = _div(_div(sga(c), c.chiffre_affaires), _div(sga(p), p.chiffre_affaires))
        bfr_c, bfr_p = equilibre_financier(c)["bfr"], equilibre_financier(p)["bfr"]
        rn_c = calculer_sig(c)["resultat_net"]
        cfo = rn_c + c.dotations_amort_prov - (bfr_c - bfr_p)
        tata = _div(rn_c - cfo, c.total_actif)
        lev_c = _div(c.passif_courant + c.dettes_financieres_lt, c.total_actif)
        lev_p = _div(p.passif_courant + p.dettes_financieres_lt, p.total_actif)
        lvgi = _div(lev_c, lev_p)
    except Exception:
        return None
    variables = [dsri, gmi, aqi, sgi, depi_v, sgai, tata, lvgi]
    if any(math.isnan(v) or math.isinf(v) for v in variables):
        return None
    m = (-4.84 + 0.920 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi + 0.115 * depi_v
         - 0.172 * sgai + 4.679 * tata - 0.327 * lvgi)
    return {"m_score": m, "alerte": "risque de manipulation" if m > -1.78 else "pas d'alerte",
            "dsri": dsri, "gmi": gmi, "aqi": aqi, "sgi": sgi, "depi": depi_v, "sgai": sgai,
            "tata": tata, "lvgi": lvgi}


def diagnostic_complet(s: Statement, precedent: Optional[Statement] = None) -> dict:
    """Diagnostic financier complet d'une entreprise (SIG, ratios, équilibre, scores)."""
    res = {"sig": calculer_sig(s), "ratios": ratios_financiers(s),
           "equilibre": equilibre_financier(s), "cycle": cycle_exploitation(s),
           "altman": altman_z2(s), "bilan_equilibre": s.equilibre()}
    if precedent is not None:
        res["beneish"] = beneish_m(s, precedent)
        ca_p = precedent.chiffre_affaires
        res["croissance_ca"] = _div(s.chiffre_affaires - ca_p, ca_p)
    return res


def lecture_management(diag: dict) -> list[str]:
    """Phrases de synthèse en français simple pour le management (règles de lecture usuelles)."""
    r, eq, alt = diag["ratios"], diag["equilibre"], diag["altman"]
    msgs: list[str] = []
    lg = r["ratio_liquidite_generale"]
    if not math.isnan(lg):
        msgs.append(("Liquidité confortable" if lg >= 1.5 else "Liquidité correcte" if lg >= 1.0
                     else "Liquidité tendue") + f" : ratio de liquidité générale de {lg:.2f}.")
    if eq["tresorerie_nette"] < 0:
        msgs.append("Trésorerie nette négative : l'entreprise finance son cycle par des crédits à court terme.")
    if eq["fonds_roulement"] < eq["bfr"]:
        msgs.append("Le fonds de roulement ne couvre pas le BFR : prévoir un financement du cycle d'exploitation.")
    ci = r["couverture_interets"]
    if not math.isnan(ci) and ci < 1.5:
        msgs.append(f"Couverture des intérêts faible ({ci:.1f}×) : la charge d'emprunt consomme le résultat.")
    if r["autonomie_financiere"] < 0.25:
        msgs.append("Autonomie financière faible (< 25 %) : dépendance forte aux dettes.")
    msgs.append(f"Score Altman Z'' : {alt['z']:.2f} → zone {alt['zone']}.")
    if diag.get("beneish") and diag["beneish"]["alerte"] != "pas d'alerte":
        msgs.append("M-score de Beneish au-dessus du seuil : examiner la qualité des résultats (créances, charges, actifs).")
    return msgs
