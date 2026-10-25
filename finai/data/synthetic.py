"""Générateurs de DONNÉES SYNTHÉTIQUES (aucune donnée réelle).

Pourquoi synthétique : les états financiers réels d'entreprises africaines / indiennes sont rarement
publics au niveau détaillé requis. Le générateur reproduit des mécanismes économiques plausibles
(santé latente → marges, délais, endettement → défaut) avec du bruit, des valeurs manquantes et des
valeurs aberrantes, afin de valider la CHAÎNE de traitement. Les performances obtenues sur ces
données démontrent la méthode, pas la performance sur le monde réel : voir `loaders.py` pour brancher
des jeux publics (p. ex. UCI « Polish companies bankruptcy », « Taiwanese bankruptcy »).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..accounting.sig import calculer_sig
from ..accounting.statement import Statement
from ..accounting.standards import ZONES

SECTEURS = {
    # marge brute, part matières, services ext., personnel, intensité capitalistique, jours stock
    "Commerce":   dict(mode="march", gm=(0.14, 0.32), mat=0.0, se=(0.04, 0.09), pers=(0.05, 0.12), immo=(0.10, 0.35), dio=(20, 80)),
    "Industrie":  dict(mode="prod", gm=None, mat=(0.35, 0.55), se=(0.05, 0.10), pers=(0.12, 0.22), immo=(0.35, 0.90), dio=(40, 120)),
    "Services":   dict(mode="prod", gm=None, mat=(0.03, 0.10), se=(0.08, 0.18), pers=(0.25, 0.45), immo=(0.10, 0.40), dio=(0, 10)),
    "BTP":        dict(mode="prod", gm=None, mat=(0.30, 0.45), se=(0.06, 0.12), pers=(0.15, 0.28), immo=(0.25, 0.60), dio=(20, 70)),
    "Agro":       dict(mode="prod", gm=None, mat=(0.40, 0.60), se=(0.04, 0.09), pers=(0.08, 0.18), immo=(0.30, 0.80), dio=(30, 110)),
}
ECHELLE_ZONE = {"OHADA": 1.0, "IFRS_AU": 3.0, "IND_AS": 1.8, "CAS_CN": 2.4, "US_GAAP": 4.0}  # millions (unité locale)
FLOTTANTS_MANQUANTS = ["creances_clients", "stocks", "autres_creances", "dettes_fournisseurs",
                       "charges_financieres", "charges_personnel", "dettes_fiscales_sociales"]


def _u(rng: np.random.Generator, bornes: tuple[float, float]) -> float:
    return float(rng.uniform(*bornes))


def _construire(rng: np.random.Generator, secteur: str, ca: float, sante: float, p: dict) -> Statement:
    cfg = SECTEURS[secteur]
    s = Statement()
    marge_adj = 0.035 * sante                                    # une meilleure santé → meilleures marges
    if cfg["mode"] == "march":
        s.ventes_marchandises = ca
        gm = float(np.clip(p["gm"] + marge_adj, 0.04, 0.45))
        s.achats_marchandises = ca * (1 - gm)
    else:
        s.production_vendue = ca
        s.achats_matieres = ca * float(np.clip(p["mat"] - 0.5 * marge_adj, 0.02, 0.8))
    s.services_exterieurs = ca * p["se"]
    s.transports = ca * float(rng.uniform(0.005, 0.03))
    s.impots_taxes = ca * float(rng.uniform(0.005, 0.025))
    s.charges_personnel = ca * p["pers"] * float(np.clip(1 - 0.05 * sante, 0.7, 1.3))
    s.autres_charges = ca * float(rng.uniform(0.003, 0.02))
    s.autres_produits = ca * float(rng.uniform(0.0, 0.01))
    immo = ca * p["immo"]
    s.immobilisations_nettes = immo
    s.dotations_amort_prov = immo * float(rng.uniform(0.06, 0.14))
    # structure financière : plus de dette quand la santé est faible
    levier = float(np.clip(p["levier"] - 0.18 * sante, 0.0, 1.6))
    dette = immo * levier
    s.dettes_financieres_lt = dette * 0.7
    s.dettes_financieres_ct = dette * 0.3
    s.tresorerie_passif = ca * float(rng.uniform(0.0, 0.02)) * max(0.0, 1 - sante / 2)
    taux = float(rng.uniform(0.05, 0.13))
    s.charges_financieres = (dette + s.tresorerie_passif) * taux
    s.produits_financiers = ca * float(rng.uniform(0.0, 0.004))
    achats = s.achats_marchandises + s.achats_matieres
    dso = float(np.clip(p["dso"] - 8 * sante, 10, 200))
    s.creances_clients = ca * dso / 365
    s.stocks = achats * p["dio"] / 365
    s.autres_creances = ca * float(rng.uniform(0.005, 0.04))
    base_four = achats + s.services_exterieurs + s.transports
    s.dettes_fournisseurs = base_four * float(np.clip(p["dpo"] + 6 * max(0.0, -sante), 10, 220)) / 365
    s.dettes_fiscales_sociales = s.charges_personnel * float(rng.uniform(0.05, 0.2)) + s.impots_taxes * 0.3
    s.autres_dettes_ct = ca * float(rng.uniform(0.005, 0.03))
    s.tresorerie_actif = ca * float(np.clip(0.06 + 0.02 * sante + rng.normal(0, 0.015), 0.0, 0.3))
    s.capital_social = immo * float(rng.uniform(0.1, 0.5))
    s.loyers_credit_bail = ca * float(rng.uniform(0.0, 0.03))
    s.frais_dev_actives = ca * float(rng.uniform(0.0, 0.01)) if secteur in ("Industrie", "Services") else 0.0
    s.reserve_lifo = achats * float(rng.uniform(0.0, 0.02))
    s.nb_employes = int(max(3, round(ca / 1e6 * 12)))
    sig = calculer_sig(s)
    avant_impot = sig["resultat_exploitation"] + sig["resultat_financier"] + sig["resultat_hao"]
    s.impot_resultat = max(0.0, avant_impot * 0.25)
    # capitaux propres = variable d'équilibrage (peuvent être négatifs pour les entreprises en difficulté)
    s.capitaux_propres = (s.immobilisations_nettes + s.stocks + s.creances_clients + s.autres_creances
                          + s.tresorerie_actif - s.dettes_financieres_lt - s.dettes_financieres_ct
                          - s.dettes_fournisseurs - s.dettes_fiscales_sociales - s.autres_dettes_ct
                          - s.tresorerie_passif)
    return s


def generer_entreprises(n: int = 2000, seed: int = 42, prevalence: float = 0.11,
                        taux_manquants: float = 0.04) -> pd.DataFrame:
    """DataFrame d'entreprises (exercice N et N-1 préfixé `prev_`), avec cibles synthétiques.

    Cibles : `defaut_12m` (1 = difficulté / défaut dans les 12 mois) et `manipulation` (1 = résultats
    embellis). Le défaut dépend de la santé latente + bruit non observé (donc jamais parfaitement
    prévisible). Les valeurs manquantes sont de type MAR (plus fréquentes pour les petites entreprises).
    """
    rng = np.random.default_rng(seed)
    zones = list(ZONES)
    lignes = []
    sante = rng.normal(0, 1, n)
    bruit = rng.normal(0, 1.0, n)                                  # facteurs non observés
    score_latent = -sante + 0.8 * bruit
    seuil = np.quantile(score_latent, 1 - prevalence)
    for i in range(n):
        zone = zones[int(rng.choice(len(zones), p=[0.30, 0.15, 0.20, 0.20, 0.15]))]
        secteur = list(SECTEURS)[int(rng.integers(len(SECTEURS)))]
        cfg = SECTEURS[secteur]
        taille = float(rng.lognormal(mean=1.2, sigma=0.8)) * ECHELLE_ZONE[zone]   # CA en millions
        ca = max(0.2, taille) * 1e6
        p = {"gm": _u(rng, cfg["gm"]) if cfg["gm"] else 0.0,
             "mat": _u(rng, cfg["mat"]) if cfg["mat"] else 0.0,
             "se": _u(rng, cfg["se"]), "pers": _u(rng, cfg["pers"]), "immo": _u(rng, cfg["immo"]),
             "levier": float(rng.uniform(0.15, 0.75)), "dso": float(rng.uniform(25, 90)),
             "dio": _u(rng, cfg["dio"]), "dpo": float(rng.uniform(25, 90))}
        manip = int(rng.random() < 0.06)
        croissance = float(np.clip(rng.normal(0.06, 0.12), -0.3, 0.5))
        prec = _construire(rng, secteur, ca / (1 + croissance), sante[i], p)
        ca_cour = ca * (1.08 if manip else 1.0)
        p_cour = dict(p, dso=p["dso"] * (1.45 if manip else 1.0))
        cour = _construire(rng, secteur, ca_cour, sante[i], p_cour)
        ligne = {"id": f"E{i:05d}", "zone": zone, "secteur": secteur,
                 "defaut_12m": int(score_latent[i] > seuil), "manipulation": manip}
        for cle, val in cour.to_dict().items():
            ligne[cle] = val
        for cle, val in prec.to_dict().items():
            ligne[f"prev_{cle}"] = val
        lignes.append(ligne)
    df = pd.DataFrame(lignes)
    # valeurs manquantes MAR : probabilité plus forte pour les petites entreprises
    ca = df["ventes_marchandises"] + df["production_vendue"]
    petit = (ca < ca.median()).to_numpy()
    for col in FLOTTANTS_MANQUANTS:
        p_manq = np.where(petit, taux_manquants * 1.6, taux_manquants * 0.4)
        masque = rng.random(n) < p_manq
        df.loc[masque, col] = np.nan
    # quelques valeurs aberrantes (erreurs de saisie ×10)
    idx = rng.choice(n, size=max(1, n // 200), replace=False)
    df.loc[idx, "creances_clients"] = df.loc[idx, "creances_clients"] * 10
    return df


def generer_transactions(n: int = 20000, seed: int = 7, taux_fraude: float = 0.03,
                         seuil_approbation: float = 500_000.0) -> pd.DataFrame:
    """Écritures comptables synthétiques avec fraudes injectées (cibles : `fraude`).

    Schémas de fraude : montants juste sous le seuil d'approbation (fractionnement), montants ronds,
    saisies de nuit/week-end, factures en double, fournisseur rare + compte atypique.
    """
    rng = np.random.default_rng(seed)
    nb_fournisseurs = 80
    fournisseurs = np.array([f"F{i:03d}" for i in range(nb_fournisseurs)])
    poids = rng.dirichlet(np.ones(nb_fournisseurs) * 0.6)
    comptes = np.array(["601", "604", "605", "613", "622", "624", "628", "631", "661", "671"])
    df = pd.DataFrame({
        "fournisseur": rng.choice(fournisseurs, n, p=poids),
        "compte": rng.choice(comptes, n, p=rng.dirichlet(np.ones(len(comptes)) * 2)),
        "montant": rng.lognormal(mean=10.5, sigma=1.15, size=n).round(0),
        "heure": np.clip(rng.normal(11, 3.2, n), 0, 23.9).astype(int),
        "jour_semaine": rng.choice(7, n, p=[0.18, 0.19, 0.19, 0.19, 0.18, 0.05, 0.02]),
        "utilisateur": rng.choice([f"U{i}" for i in range(12)], n),
    })
    df["fraude"] = 0
    nb_f = int(n * taux_fraude)
    idx = rng.choice(n, nb_f, replace=False)
    types = rng.choice(["sous_seuil", "rond", "nuit_we", "doublon", "rare"], nb_f)
    for k, i in enumerate(idx):
        t = types[k]
        if t == "sous_seuil":
            df.loc[i, "montant"] = round(seuil_approbation * rng.uniform(0.94, 0.999))
        elif t == "rond":
            df.loc[i, "montant"] = float(rng.choice([1, 2, 5]) * 10 ** int(rng.integers(5, 8)))
        elif t == "nuit_we":
            df.loc[i, "heure"], df.loc[i, "jour_semaine"] = int(rng.choice([0, 1, 2, 3, 23])), int(rng.choice([5, 6]))
        elif t == "doublon":
            j = int(rng.integers(n))
            df.loc[i, ["fournisseur", "compte", "montant"]] = df.loc[j, ["fournisseur", "compte", "montant"]].to_numpy()
        else:
            df.loc[i, "fournisseur"] = f"X{int(rng.integers(900, 999))}"
            df.loc[i, "compte"] = "671"
            df.loc[i, "montant"] = float(df["montant"].quantile(0.97) * rng.uniform(0.8, 1.5))
        df.loc[i, "fraude"] = 1
    df["seuil_approbation"] = seuil_approbation
    return df


def generer_flux_tresorerie(semaines: int = 260, seed: int = 11) -> pd.DataFrame:
    """Flux net hebdomadaire : tendance + saisonnalité (paie en fin de mois, TVA trimestrielle) + chocs."""
    rng = np.random.default_rng(seed)
    t = np.arange(semaines)
    tendance = 40_000 + 120 * t
    annuelle = 25_000 * np.sin(2 * np.pi * t / 52 + 0.6)
    fin_mois = -60_000 * ((t % 4) == 3)
    tva = -90_000 * ((t % 13) == 12)
    chocs = np.zeros(semaines)
    for i in rng.choice(np.arange(20, semaines), 6, replace=False):
        chocs[i:i + 3] += rng.choice([-1, 1]) * rng.uniform(50_000, 130_000)
    bruit = rng.normal(0, 18_000, semaines)
    flux = tendance + annuelle + fin_mois + tva + chocs + bruit
    dates = pd.date_range("2020-01-06", periods=semaines, freq="W-MON")
    return pd.DataFrame({"date": dates, "flux_net": flux})


_LIBELLES = {
    "60": ["achat de marchandises {x}", "purchase of goods invoice {x}", "achat matieres premieres {x}", "approvisionnement stock {x}"],
    "61": ["frais de transport {x}", "transport de marchandises camion {x}", "freight charges {x}", "fret maritime conteneur {x}"],
    "62": ["loyer bureaux {x}", "entretien et reparation {x}", "prime d'assurance {x}", "rent payment office {x}"],
    "63": ["honoraires comptable {x}", "frais bancaires commission {x}", "publicite et communication {x}", "bank fees {x}"],
    "64": ["paiement tva {x}", "impots et taxes {x}", "patente taxe {x}", "tax payment {x}"],
    "66": ["salaires du mois {x}", "paie du personnel {x}", "cotisations cnps {x}", "payroll {x}"],
    "67": ["interets emprunt bancaire {x}", "frais financiers agios {x}", "loan interest {x}", "charges d'interets {x}"],
    "70": ["vente de marchandises client {x}", "facture client {x}", "sales invoice customer {x}", "prestation de services {x}"],
}
NOMS_COMPTES = {"60": "Achats", "61": "Transports", "62": "Services extérieurs A", "63": "Services extérieurs B",
                "64": "Impôts et taxes", "66": "Charges de personnel", "67": "Frais financiers", "70": "Ventes"}


def generer_libelles(n: int = 3000, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    classes = list(_LIBELLES)
    lignes = []
    for _ in range(n):
        c = classes[int(rng.integers(len(classes)))]
        g = int(rng.integers(len(_LIBELLES[c])))
        base = _LIBELLES[c][g].format(x=int(rng.integers(100, 9999)))
        if rng.random() < 0.25:                      # fautes de frappe / bruit
            i = int(rng.integers(len(base)))
            base = base[:i] + base[i + 1:]
        if rng.random() < 0.15:
            base = base.upper()
        lignes.append({"libelle": base, "compte": c, "gabarit": g})
    return pd.DataFrame(lignes)


_OPINIONS = {
    "sans_reserve": ["Les comptes annuels sont réguliers et sincères et donnent une image fidèle de la situation financière.",
                     "In our opinion the financial statements present fairly in all material respects the financial position.",
                     "Nous certifions sans réserve que les états financiers sont conformes au référentiel comptable."],
    "avec_reserve": ["Sous réserve de l'incidence du point décrit ci-dessus, les comptes sont réguliers et sincères.",
                     "Except for the effects of the matter described, the financial statements present fairly the position.",
                     "Nous avons relevé une limitation dans l'inventaire physique des stocks qui motive une réserve."],
    "continuite": ["Il existe une incertitude significative sur la continuité d'exploitation de l'entité.",
                   "Material uncertainty related to going concern exists that may cast doubt on the entity's ability to continue.",
                   "Les capitaux propres sont inférieurs à la moitié du capital social, ce qui remet en cause la continuité."],
    "refus": ["Nous n'avons pas pu obtenir d'éléments suffisants et nous ne sommes pas en mesure d'exprimer une opinion.",
              "We do not express an opinion on the financial statements due to the significance of the limitation.",
              "Impossibilité de certifier les comptes en raison de limitations multiples."],
}


def generer_phrases_audit(n: int = 1200, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    lignes = []
    cles = list(_OPINIONS)
    for _ in range(n):
        c = cles[int(rng.integers(len(cles)))]
        g = int(rng.integers(len(_OPINIONS[c])))
        phrase = _OPINIONS[c][g]
        if rng.random() < 0.3:
            phrase += " " + str(rng.choice(["Exercice clos le 31 décembre.", "Rapport du commissaire aux comptes.", "Audit report."]))
        lignes.append({"texte": phrase, "opinion": c, "gabarit": g})
    return pd.DataFrame(lignes)
