"""Prévision du retard d'un navire (apprentissage automatique) sur des voyages SIMULÉS.

Honnêteté : sans historique réel, on apprend sur des voyages générés par des règles que j'ai posées
(distance, transbordements, saison, congestion, fiabilité de la ligne). Le modèle retrouve donc ces règles :
cela prouve que la méthode fonctionne, pas qu'elle prédit les vrais retards. Avec de vrais voyages, il suffit
de remplacer `generer_voyages` par vos données (mêmes colonnes) : tout le reste ne change pas.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

DESTINATION = (5.264, -4.009)  # Abidjan (approximatif)
ORIGINES = {  # mêmes noms que sndgir_suivi.PORTS
    "Shanghai (Chine)": (31.23, 121.47), "Guangzhou / Nansha (Chine)": (22.75, 113.60),
    "Ningbo (Chine)": (29.87, 121.55), "Mumbai / Nhava Sheva (Inde)": (18.95, 72.95),
    "Dubaï / Jebel Ali": (25.01, 55.06), "Rotterdam (Pays-Bas)": (51.95, 4.14),
    "Anvers (Belgique)": (51.27, 4.33), "Le Havre (France)": (49.48, 0.11),
    "Istanbul (Turquie)": (41.0, 28.98), "Santos (Brésil)": (-23.98, -46.30),
}
LIGNES = ["Ligne A", "Ligne B", "Ligne C", "Ligne D", "Ligne E"]
_FIABILITE = {"Ligne A": 0.0, "Ligne B": 0.8, "Ligne C": 1.6, "Ligne D": -0.5, "Ligne E": 2.5}  # jours de retard moyens
VITESSE_KM_JOUR = 750.0  # navigation économique
SEUIL_RETARD = 3.0       # « retard » = plus de 3 jours
FEATURES_NUM = ["distance_km", "transbordements", "congestion", "mois_sin", "mois_cos", "nouvel_an_chinois"]
FEATURES_CAT = ["origine", "ligne"]


def haversine_km(a, b) -> float:
    r = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dphi, dlam = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def delai_prevu(distance_km: float, transbordements: int) -> float:
    """Durée annoncée (jours) : route plus longue que le vol d'oiseau (×1,35) + 3 jours par transbordement."""
    return distance_km * 1.35 / VITESSE_KM_JOUR + 3.0 * transbordements


def _ajouter_variables(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["mois_sin"] = np.sin(2 * np.pi * d["mois"] / 12)
    d["mois_cos"] = np.cos(2 * np.pi * d["mois"] / 12)
    d["nouvel_an_chinois"] = (d["origine"].str.contains("Chine") & d["mois"].isin([1, 2])).astype(int)
    return d


def generer_voyages(n: int = 3000, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    noms = list(ORIGINES)
    poids = np.array([3, 2, 2, 2, 1.5, 1.5, 1, 1, 1, 0.7]); poids = poids / poids.sum()
    origine = rng.choice(noms, n, p=poids)
    mois = rng.integers(1, 13, n)
    ligne = rng.choice(LIGNES, n)
    europe = np.array([("Pays-Bas" in o) or ("Belgique" in o) or ("France" in o) for o in origine])
    transb = np.where(europe, rng.choice([0, 1], n, p=[0.8, 0.2]), rng.choice([0, 1, 2], n, p=[0.45, 0.38, 0.17]))
    congestion = np.clip(rng.normal(0.45, 0.18, n) + 0.15 * np.isin(mois, [10, 11, 12]), 0, 1)
    dist = np.array([haversine_km(ORIGINES[o], DESTINATION) for o in origine])
    nouvel_an = (np.array(["Chine" in o for o in origine]) & np.isin(mois, [1, 2])).astype(float)
    moyenne = (-1.2 + 1.2 * transb + 2.5 * congestion + 0.8 * np.array([_FIABILITE[l] for l in ligne])
               + 2.5 * nouvel_an + 0.00008 * dist)
    bruit = rng.gamma(2.0, 1.1, n) - 2.2          # asymétrique : les gros retards sont plus fréquents que les avances
    retard = np.round(np.maximum(moyenne + bruit, -2.0), 1)
    df = pd.DataFrame({"origine": origine, "ligne": ligne, "mois": mois, "transbordements": transb,
                       "congestion": congestion.round(3), "distance_km": dist.round(0)})
    df["delai_prevu_jours"] = [delai_prevu(d, t) for d, t in zip(df["distance_km"], df["transbordements"])]
    df["retard_jours"] = retard
    return df


def _preprocesseur() -> ColumnTransformer:
    return ColumnTransformer([("num", StandardScaler(), FEATURES_NUM),
                              ("cat", OneHotEncoder(handle_unknown="ignore"), FEATURES_CAT)])


@dataclass
class ModeleRetard:
    regresseur: Pipeline
    classifieur: Pipeline
    ridge: Pipeline
    moyenne_train: float
    residus: np.ndarray
    metriques: dict = field(default_factory=dict)

    def predire(self, origine: str, ligne: str, mois: int, transbordements: int, congestion: float,
                distance_km: float | None = None) -> dict:
        if origine not in ORIGINES:
            raise ValueError("Port d'origine inconnu pour ce modèle.")
        if not 1 <= int(mois) <= 12 or not 0 <= congestion <= 1 or transbordements < 0:
            raise ValueError("Valeurs hors limites (mois 1-12, congestion 0-1, transbordements ≥ 0).")
        dist = distance_km if distance_km else haversine_km(ORIGINES[origine], DESTINATION)
        ligne_ = ligne if ligne in LIGNES else LIGNES[0]
        x = _ajouter_variables(pd.DataFrame([{"origine": origine, "ligne": ligne_, "mois": int(mois),
                                              "transbordements": int(transbordements), "congestion": float(congestion),
                                              "distance_km": float(dist)}]))
        r = float(self.regresseur.predict(x)[0])
        bas, haut = np.quantile(self.residus, [0.1, 0.9])
        prevu = delai_prevu(dist, int(transbordements))
        return {"retard_jours": r, "intervalle": (r + float(bas), r + float(haut)),
                "proba_retard_3j": float(self.classifieur.predict_proba(x)[0, 1]),
                "delai_prevu_jours": prevu, "delai_estime_jours": prevu + r}


def entrainer(df: pd.DataFrame | None = None, seed: int = 0) -> ModeleRetard:
    """Entraîne trois modèles et les compare sur un jeu de test tenu à l'écart (jamais utilisé pour régler)."""
    df = generer_voyages() if df is None else df
    d = _ajouter_variables(df)
    X, y = d[FEATURES_NUM + FEATURES_CAT], d["retard_jours"]
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=seed)
    X_fit, X_val, y_fit, y_val = train_test_split(X_tr, y_tr, test_size=0.2, random_state=seed)

    ridge = Pipeline([("p", _preprocesseur()), ("m", Ridge(alpha=1.0))]).fit(X_tr, y_tr)
    gb = Pipeline([("p", _preprocesseur()), ("m", HistGradientBoostingRegressor(max_depth=3, learning_rate=0.06,
                                                                              max_iter=250, random_state=seed))])
    gb_val = gb.fit(X_fit, y_fit)
    residus = (y_val - gb_val.predict(X_val)).to_numpy()   # intervalle calculé hors échantillon d'entraînement
    gb.fit(X_tr, y_tr)
    clf = Pipeline([("p", _preprocesseur()), ("m", HistGradientBoostingClassifier(max_depth=3, learning_rate=0.06,
                                                                                   max_iter=200, random_state=seed))])
    clf.fit(X_tr, (y_tr > SEUIL_RETARD).astype(int))

    moy = float(y_tr.mean())
    def ev(pred):
        return {"mae_jours": float(mean_absolute_error(y_te, pred)),
                "rmse_jours": float(math.sqrt(mean_squared_error(y_te, pred)))}
    metriques = {"Référence (retard moyen)": ev(np.full(len(y_te), moy)),
                 "Régression Ridge": ev(ridge.predict(X_te)),
                 "Gradient boosting": ev(gb.predict(X_te))}
    y_bin = (y_te > SEUIL_RETARD).astype(int)
    metriques["_classification"] = {"auc_retard_plus_3j": float(roc_auc_score(y_bin, clf.predict_proba(X_te)[:, 1])),
                                    "part_retards_test": float(y_bin.mean()), "n_test": int(len(y_te))}
    return ModeleRetard(gb, clf, ridge, moy, residus, metriques)
