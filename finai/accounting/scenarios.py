"""Simulation « What-If » : applique des chocs à un exercice et recalcule tout.

Le bilan reste équilibré : le résultat additionnel va aux capitaux propres, le BFR est
recalculé à partir des délais (DSO/DIO/DPO) et la trésorerie sert de variable d'ajustement
(si elle devient négative, l'excédent passe en concours bancaires).
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from .ratios import cycle_exploitation, diagnostic_complet
from .sig import calculer_sig
from .statement import Statement


@dataclass
class Choc:
    ventes_pct: float = 0.0          # variation du chiffre d'affaires (ex. −0.10 pour −10 %)
    prix_achats_pct: float = 0.0     # inflation des prix d'achat (en plus du volume)
    personnel_pct: float = 0.0
    dso_delta: float = 0.0           # jours de délai clients en plus (+) ou en moins (−)
    dio_delta: float = 0.0
    dpo_delta: float = 0.0
    taux_dette_delta: float = 0.0    # points de taux d'intérêt (0.02 = +2 pts)
    dette_supplementaire: float = 0.0

    def valider(self) -> None:
        if self.ventes_pct <= -1 or self.prix_achats_pct <= -1 or self.personnel_pct <= -1:
            raise ValueError("Un choc ne peut pas être inférieur ou égal à −100 %.")


def appliquer_choc(s: Statement, choc: Choc, taux_is: float = 0.25) -> Statement:
    choc.valider()
    base = cycle_exploitation(s)
    v = 1 + choc.ventes_pct
    achats_f = v * (1 + choc.prix_achats_pct)
    n = replace(s)
    for champ in ("ventes_marchandises", "production_vendue", "production_stockee", "production_immobilisee",
                  "subventions_exploitation", "autres_produits"):
        setattr(n, champ, getattr(s, champ) * v)
    for champ in ("achats_marchandises", "achats_matieres", "autres_achats", "transports",
                  "services_exterieurs"):
        setattr(n, champ, getattr(s, champ) * achats_f)
    n.charges_personnel = s.charges_personnel * (1 + choc.personnel_pct)
    n.dettes_financieres_lt = s.dettes_financieres_lt + choc.dette_supplementaire
    dette_base = s.dettes_financieres_lt + s.dettes_financieres_ct + s.tresorerie_passif
    taux_ref = s.charges_financieres / dette_base if dette_base > 0 else 0.0
    n.charges_financieres = ((n.dettes_financieres_lt + s.dettes_financieres_ct + s.tresorerie_passif)
                             * (taux_ref + choc.taux_dette_delta))
    # BFR recalculé à partir des délais
    ca_n = n.chiffre_affaires
    achats_n = n.achats_marchandises + n.achats_matieres + n.autres_achats
    base_four_n = achats_n + n.services_exterieurs + n.transports
    n.creances_clients = ca_n * ((base["dso_jours"] if base["dso_jours"] == base["dso_jours"] else 0)
                                 + choc.dso_delta) / 365
    if achats_n > 0 and base["dio_jours"] == base["dio_jours"]:
        n.stocks = achats_n * (base["dio_jours"] + choc.dio_delta) / 365
    n.dettes_fournisseurs = base_four_n * max(0.0, (base["dpo_jours"] if base["dpo_jours"] == base["dpo_jours"] else 0)
                                              + choc.dpo_delta) / 365
    # impôt : taux effectif d'origine appliqué au nouveau résultat avant impôt
    sig_o, sig_n = calculer_sig(s), calculer_sig(n)
    avant_impot_o = sig_o["resultat_net"] + s.impot_resultat
    taux = (s.impot_resultat / avant_impot_o) if avant_impot_o > 0 else taux_is
    avant_impot_n = sig_n["resultat_net"] + n.impot_resultat
    n.impot_resultat = max(0.0, avant_impot_n * taux)
    rn_n = avant_impot_n - n.impot_resultat
    n.capitaux_propres = s.capitaux_propres - sig_o["resultat_net"] + rn_n
    # trésorerie = variable d'ajustement
    passif_hors_tr = (n.capitaux_propres + n.dettes_financieres_lt + n.dettes_financieres_ct
                      + n.dettes_fournisseurs + n.dettes_fiscales_sociales + n.autres_dettes_ct)
    actif_hors_tr = n.immobilisations_nettes + n.stocks + n.creances_clients + n.autres_creances
    tr_nette = passif_hors_tr - actif_hors_tr          # trésorerie_actif − trésorerie_passif
    n.tresorerie_actif, n.tresorerie_passif = (tr_nette, 0.0) if tr_nette >= 0 else (0.0, -tr_nette)
    return n


def comparer_scenarios(s: Statement, chocs: dict[str, Choc]) -> list[dict]:
    """Tableau de comparaison : base + scénarios (CA, EBE, résultat net, BFR, trésorerie, Z'')."""
    lignes = []
    for nom, ch in {"Base": Choc(), **chocs}.items():
        n = appliquer_choc(s, ch)
        d = diagnostic_complet(n)
        lignes.append({"scenario": nom, "chiffre_affaires": d["sig"]["chiffre_affaires"],
                       "ebe": d["sig"]["excedent_brut_exploitation"],
                       "resultat_net": d["sig"]["resultat_net"], "bfr": d["equilibre"]["bfr"],
                       "tresorerie_nette": d["equilibre"]["tresorerie_nette"],
                       "liquidite_generale": d["ratios"]["ratio_liquidite_generale"],
                       "altman_z": d["altman"]["z"], "zone": d["altman"]["zone"]})
    return lignes


def sensibilite_tornado(s: Statement, amplitude: float = 0.10) -> list[dict]:
    """Impact sur le résultat net d'un choc ±amplitude de chaque facteur (diagramme tornado)."""
    facteurs = {
        "Chiffre d'affaires": lambda a: Choc(ventes_pct=a),
        "Prix d'achat": lambda a: Choc(prix_achats_pct=a),
        "Charges de personnel": lambda a: Choc(personnel_pct=a),
        "Taux d'intérêt (±pts ×0.1)": lambda a: Choc(taux_dette_delta=a * 0.1),
    }
    base = calculer_sig(s)["resultat_net"]
    res = []
    for nom, f in facteurs.items():
        haut = calculer_sig(appliquer_choc(s, f(amplitude)))["resultat_net"] - base
        bas = calculer_sig(appliquer_choc(s, f(-amplitude)))["resultat_net"] - base
        res.append({"facteur": nom, "impact_hausse": haut, "impact_baisse": bas,
                    "amplitude": abs(haut - bas)})
    return sorted(res, key=lambda r: -r["amplitude"])
