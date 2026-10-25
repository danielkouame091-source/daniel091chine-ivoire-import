"""Entraînement supervisé : RF, Gradient Boosting (XGBoost/LightGBM si dispo), SVM, régularisée.

Protocole : (1) séparation train / validation / test stratifiée ; (2) validation croisée stratifiée
sur le train avec SMOTE dans chaque pli d'entraînement ; (3) choix du seuil sur la validation ;
(4) évaluation finale UNIQUE sur le test, avec intervalle de confiance bootstrap.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.svm import SVC

from .metrics import intervalle_bootstrap, metriques_classification, seuil_optimal_f1
from .preprocessing import construire_preprocesseur, reequilibrer

try:
    from xgboost import XGBClassifier
    XGB_OK = True
except Exception:                                      # pragma: no cover
    XGBClassifier, XGB_OK = None, False
try:
    from lightgbm import LGBMClassifier
    LGBM_OK = True
except Exception:                                      # pragma: no cover
    LGBMClassifier, LGBM_OK = None, False


def fabrique_modeles(seed: int = 0) -> dict:
    """Modèles candidats. `HistGradientBoosting` est l'équivalent scikit-learn de LightGBM (histogrammes)."""
    modeles = {
        "Régression logistique (référence)": LogisticRegression(max_iter=2000, C=0.5, random_state=seed),
        "Random Forest": RandomForestClassifier(n_estimators=300, min_samples_leaf=3, n_jobs=-1,
                                                random_state=seed),
        "Gradient Boosting (HistGB)": HistGradientBoostingClassifier(max_depth=4, learning_rate=0.06,
                                                                      max_iter=300, random_state=seed),
        "SVM (RBF)": CalibratedClassifierCV(SVC(C=2.0, kernel="rbf"), method="sigmoid", cv=3,
                                            ensemble=False),
    }
    if XGB_OK:
        modeles["XGBoost"] = XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.05,
                                           subsample=0.9, colsample_bytree=0.9, eval_metric="logloss",
                                           random_state=seed, n_jobs=2)
    if LGBM_OK:
        modeles["LightGBM"] = LGBMClassifier(n_estimators=300, max_depth=-1, num_leaves=15,
                                             learning_rate=0.05, random_state=seed, verbose=-1)
    return modeles


@dataclass
class ResultatEntrainement:
    tableau: pd.DataFrame            # métriques de test par modèle
    cv: pd.DataFrame                 # AUC moyen/écart-type en validation croisée
    modeles: dict                    # modèles ajustés
    preprocesseur: object
    seuils: dict
    X_test: pd.DataFrame
    y_test: np.ndarray
    probas_test: dict
    noms_variables: list[str]
    ic_auc: dict


def validation_croisee(modele_fab, X: pd.DataFrame, y: np.ndarray, methode_equilibrage: str = "smote",
                       k: int = 5, seed: int = 0) -> np.ndarray:
    """AUC par pli ; imputation/échelle/SMOTE ajustés dans chaque pli d'entraînement (aucune fuite)."""
    from sklearn.base import clone
    skf = StratifiedKFold(n_splits=k, shuffle=True, random_state=seed)
    scores = []
    for tr, va in skf.split(X, y):
        prep = construire_preprocesseur()
        Xtr = prep.fit_transform(X.iloc[tr])
        Xva = prep.transform(X.iloc[va])
        Xr, yr = reequilibrer(Xtr, y[tr], methode_equilibrage, seed=seed)
        m = clone(modele_fab)
        m.fit(Xr, yr)
        scores.append(roc_auc_score(y[va], m.predict_proba(Xva)[:, 1]))
    return np.asarray(scores)


def evaluer_modeles(X: pd.DataFrame, y, equilibrage: str = "smote", seed: int = 0,
                    modeles: dict | None = None, cv_plis: int = 5) -> ResultatEntrainement:
    y = np.asarray(y).astype(int)
    X_tmp, X_test, y_tmp, y_test = train_test_split(X, y, test_size=0.2, stratify=y, random_state=seed)
    X_tr, X_val, y_tr, y_val = train_test_split(X_tmp, y_tmp, test_size=0.25, stratify=y_tmp, random_state=seed)
    modeles = modeles or fabrique_modeles(seed)
    prep = construire_preprocesseur()
    A_tr = prep.fit_transform(X_tr)
    A_val, A_test = prep.transform(X_val), prep.transform(X_test)
    Ar, yr = reequilibrer(A_tr, y_tr, equilibrage, seed=seed)
    lignes, cv_lignes, ajustes, seuils, probas, ic = [], [], {}, {}, {}, {}
    X_cv, y_cv = pd.concat([X_tr, X_val]), np.concatenate([y_tr, y_val])
    from sklearn.base import clone
    for nom, m in modeles.items():
        scores = validation_croisee(m, X_cv.reset_index(drop=True), y_cv, equilibrage, cv_plis, seed)
        cv_lignes.append({"modele": nom, "auc_cv_moyen": scores.mean(), "auc_cv_ecart_type": scores.std()})
        mf = clone(m).fit(Ar, yr)
        seuil = seuil_optimal_f1(y_val, mf.predict_proba(A_val)[:, 1])
        p_test = mf.predict_proba(A_test)[:, 1]
        met = metriques_classification(y_test, p_test, seuil)
        met["modele"] = nom
        lo, hi = intervalle_bootstrap(y_test, p_test, roc_auc_score, n=300, seed=seed)
        met["auc_ic95_bas"], met["auc_ic95_haut"] = lo, hi
        lignes.append(met)
        ajustes[nom], seuils[nom], probas[nom], ic[nom] = mf, seuil, p_test, (lo, hi)
    tableau = pd.DataFrame(lignes).set_index("modele")
    tableau["tn"] = tableau["matrice_confusion"].map(lambda d: d["tn"])
    tableau["fp"] = tableau["matrice_confusion"].map(lambda d: d["fp"])
    tableau["fn"] = tableau["matrice_confusion"].map(lambda d: d["fn"])
    tableau["tp"] = tableau["matrice_confusion"].map(lambda d: d["tp"])
    tableau = tableau.drop(columns=["matrice_confusion"])
    return ResultatEntrainement(tableau, pd.DataFrame(cv_lignes).set_index("modele"), ajustes, prep, seuils,
                                X_test.reset_index(drop=True), y_test, probas, list(A_tr.columns), ic)


def regression_score_risque(X: pd.DataFrame, cible: np.ndarray, seed: int = 0) -> dict:
    """Régression (MAE/RMSE) : prédit une cible continue (ici le résultat net / actif, ROA) pour
    illustrer la partie régression du cahier des charges (Random Forest vs Gradient Boosting)."""
    from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
    from .metrics import metriques_regression
    ok = ~np.isnan(cible)
    Xr, yr = X.loc[ok].reset_index(drop=True), cible[ok]
    Xa, Xb, ya, yb = train_test_split(Xr, yr, test_size=0.25, random_state=seed)
    prep = construire_preprocesseur()
    Aa, Ab = prep.fit_transform(Xa), prep.transform(Xb)
    res = {}
    for nom, m in {"Random Forest": RandomForestRegressor(n_estimators=250, min_samples_leaf=3, n_jobs=-1, random_state=seed),
                   "Gradient Boosting (HistGB)": HistGradientBoostingRegressor(max_depth=4, learning_rate=0.06, max_iter=250, random_state=seed)}.items():
        m.fit(Aa, ya)
        res[nom] = metriques_regression(yb, m.predict(Ab), ya)
    res["Référence (moyenne)"] = metriques_regression(yb, np.full_like(yb, ya.mean()), ya)
    return res
