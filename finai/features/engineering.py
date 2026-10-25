"""Ingénierie des variables : états financiers → table de caractéristiques pour le ML."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from ..accounting.ratios import altman_z2, beneish_m, cycle_exploitation, equilibre_financier, ratios_financiers
from ..accounting.sig import calculer_sig
from ..accounting.statement import Statement

CHAMPS = list(Statement.__dataclass_fields__)

FEATURES_NUM = [
    "ratio_liquidite_generale", "ratio_liquidite_reduite", "ratio_liquidite_immediate", "marge_nette",
    "marge_ebe", "marge_exploitation", "roa", "roe", "roce", "rotation_actif", "autonomie_financiere",
    "endettement_cp", "couverture_interets", "poids_dettes_totales", "marge_valeur_ajoutee",
    "dso_jours", "dio_jours", "dpo_jours", "bfr_jours_ca", "fr_sur_actif", "tn_sur_actif",
    "altman_x1", "altman_x2", "altman_x3", "altman_x4", "log_total_actif", "croissance_ca",
    "dsri", "gmi", "aqi", "sgi", "tata",
]
FEATURES_CAT = ["zone", "secteur"]


def _statement(ligne: pd.Series, prefixe: str = "") -> Statement:
    d = {c: ligne.get(f"{prefixe}{c}", np.nan) for c in CHAMPS}
    return Statement.from_dict({c: (v if v == v else float("nan")) for c, v in d.items()})


def _winsor(x: float, borne: float = 50.0) -> float:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return float("nan")
    return float(max(-borne, min(borne, x)))


def caracteristiques_entreprise(ligne: pd.Series) -> dict[str, float]:
    s = _statement(ligne)
    p = _statement(ligne, "prev_") if "prev_ventes_marchandises" in ligne.index else None
    r, c, alt = ratios_financiers(s), cycle_exploitation(s), altman_z2(s)
    eq = equilibre_financier(s)
    ta = s.total_actif
    f = {k: _winsor(r[k]) for k in r if k in FEATURES_NUM}
    f.update({"dso_jours": _winsor(c["dso_jours"], 400), "dio_jours": _winsor(c["dio_jours"], 400),
              "dpo_jours": _winsor(c["dpo_jours"], 400), "bfr_jours_ca": _winsor(c["bfr_jours_ca"], 400)})
    f["fr_sur_actif"] = _winsor(eq["fonds_roulement"] / ta) if ta and ta == ta else float("nan")
    f["tn_sur_actif"] = _winsor(eq["tresorerie_nette"] / ta) if ta and ta == ta else float("nan")
    for k in ("x1", "x2", "x3", "x4"):
        f[f"altman_{k}"] = _winsor(alt.get(k, float("nan")))
    f["log_total_actif"] = math.log(ta) if ta and ta == ta and ta > 0 else float("nan")
    f.update({"croissance_ca": float("nan"), "dsri": float("nan"), "gmi": float("nan"),
              "aqi": float("nan"), "sgi": float("nan"), "tata": float("nan")})
    if p is not None:
        ca_p = p.chiffre_affaires
        if ca_p and ca_p == ca_p:
            f["croissance_ca"] = _winsor((s.chiffre_affaires - ca_p) / ca_p)
        b = beneish_m(s, p)
        if b:
            for k in ("dsri", "gmi", "aqi", "sgi", "tata"):
                f[k] = _winsor(b[k])
    return f


def construire_table(df: pd.DataFrame) -> pd.DataFrame:
    """Table de caractéristiques (une ligne par entreprise). Les NaN sont conservés."""
    lignes = [caracteristiques_entreprise(row) for _, row in df.iterrows()]
    X = pd.DataFrame(lignes, index=df.index)
    for c in FEATURES_NUM:
        if c not in X.columns:
            X[c] = np.nan
    X = X[FEATURES_NUM].replace([np.inf, -np.inf], np.nan)
    for c in FEATURES_CAT:
        X[c] = df[c].values
    return X


def caracteristiques_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """Variables pour la détection de fraude comptable (montants, temps, fréquence, Benford)."""
    X = pd.DataFrame(index=df.index)
    X["log_montant"] = np.log1p(df["montant"])
    X["ratio_seuil"] = df["montant"] / df["seuil_approbation"]
    X["proche_seuil"] = ((X["ratio_seuil"] > 0.9) & (X["ratio_seuil"] < 1.0)).astype(int)
    X["montant_rond"] = ((df["montant"] % 10_000) == 0).astype(int)
    X["heure"] = df["heure"]
    X["nuit"] = ((df["heure"] < 6) | (df["heure"] >= 21)).astype(int)
    X["week_end"] = (df["jour_semaine"] >= 5).astype(int)
    cle = df["fournisseur"] + "|" + df["compte"] + "|" + df["montant"].astype(str)
    X["doublon"] = (cle.map(cle.value_counts()) > 1).astype(int)
    X["freq_fournisseur"] = df["fournisseur"].map(df["fournisseur"].value_counts(normalize=True))
    paire = df["fournisseur"] + "|" + df["compte"]
    X["freq_paire"] = paire.map(paire.value_counts(normalize=True))
    moy = df.groupby("fournisseur")["montant"].transform("mean")
    std = df.groupby("fournisseur")["montant"].transform("std").replace(0, np.nan)
    X["z_montant_fournisseur"] = ((df["montant"] - moy) / std).fillna(0.0).clip(-10, 10)
    return X
