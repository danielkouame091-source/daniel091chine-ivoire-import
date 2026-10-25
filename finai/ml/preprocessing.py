"""Prétraitement : imputation, encodage, normalisation et rééquilibrage (SMOTE).

Règle anti-fuite : l'imputation, la normalisation et le SMOTE sont ajustés UNIQUEMENT sur le jeu
d'entraînement (ou sur chaque pli d'entraînement en validation croisée).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.neighbors import NearestNeighbors
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, RobustScaler

from ..features.engineering import FEATURES_CAT, FEATURES_NUM

try:                                                   # SMOTE de référence si imbalanced-learn est installé
    from imblearn.over_sampling import SMOTE as _SMOTE_IMB
    IMBLEARN_OK = True
except Exception:                                      # pragma: no cover
    _SMOTE_IMB = None
    IMBLEARN_OK = False


def construire_preprocesseur(num: list[str] | None = None, cat: list[str] | None = None,
                             scaler: bool = True) -> ColumnTransformer:
    """Imputation médiane + indicateurs de valeurs manquantes + RobustScaler ; one-hot pour les catégories."""
    num = FEATURES_NUM if num is None else num
    cat = FEATURES_CAT if cat is None else cat
    etapes_num = [("imp", SimpleImputer(strategy="median", add_indicator=False))]
    if scaler:
        etapes_num.append(("sc", RobustScaler(quantile_range=(5, 95))))
    transfo = [("num", Pipeline(etapes_num), num)]
    if cat:
        transfo.append(("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), cat))
    return ColumnTransformer(transfo, remainder="drop", verbose_feature_names_out=False).set_output(transform="pandas")


class SmoteNumpy:
    """SMOTE (Chawla et al., 2002) en NumPy pur : interpolation entre un point minoritaire et l'un de
    ses k plus proches voisins minoritaires. Utilisé si `imbalanced-learn` n'est pas installé.

    x_new = x_i + λ (x_nn − x_i),  λ ~ U(0, 1)
    """

    def __init__(self, k: int = 5, ratio: float = 1.0, seed: int = 0):
        self.k, self.ratio, self.seed = k, ratio, seed

    def fit_resample(self, X, y):
        X = np.asarray(X, float)
        y = np.asarray(y).astype(int)
        rng = np.random.default_rng(self.seed)
        classes, comptes = np.unique(y, return_counts=True)
        if len(classes) != 2:
            raise ValueError("SMOTE attend une cible binaire.")
        mino = classes[np.argmin(comptes)]
        n_maj, n_min = comptes.max(), comptes.min()
        cible = int(self.ratio * n_maj)
        a_creer = max(0, cible - n_min)
        Xm = X[y == mino]
        if a_creer == 0 or len(Xm) < 2:
            return X, y
        k = min(self.k, len(Xm) - 1)
        voisins = NearestNeighbors(n_neighbors=k + 1).fit(Xm).kneighbors(Xm, return_distance=False)[:, 1:]
        base = rng.integers(0, len(Xm), a_creer)
        choix = voisins[base, rng.integers(0, k, a_creer)]
        lam = rng.random((a_creer, 1))
        nouveaux = Xm[base] + lam * (Xm[choix] - Xm[base])
        return np.vstack([X, nouveaux]), np.concatenate([y, np.full(a_creer, mino)])


def reequilibrer(X, y, methode: str = "smote", seed: int = 0, k: int = 5):
    """Rééquilibre le jeu d'ENTRAÎNEMENT. `methode` : « smote » ou « aucune ».

    Les colonnes one-hot synthétisées par SMOTE sont des valeurs continues entre 0 et 1 : acceptable
    pour des arbres/SVM, mais à documenter (variante SMOTE-NC possible avec imbalanced-learn).
    """
    colonnes = list(X.columns) if isinstance(X, pd.DataFrame) else None
    if methode == "aucune":
        Xr, yr = np.asarray(X), np.asarray(y)
    elif methode != "smote":
        raise ValueError("Méthode de rééquilibrage inconnue.")
    elif IMBLEARN_OK:
        kk = max(1, min(k, int(np.sum(np.asarray(y) == 1)) - 1))
        Xr, yr = _SMOTE_IMB(k_neighbors=kk, random_state=seed).fit_resample(X, y)
    else:
        Xr, yr = SmoteNumpy(k=k, seed=seed).fit_resample(X, y)
    if colonnes is not None:                      # on conserve les noms de variables (explicabilité)
        Xr = pd.DataFrame(np.asarray(Xr), columns=colonnes)
    return Xr, np.asarray(yr)
