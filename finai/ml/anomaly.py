"""Détection d'anomalies / fraudes comptables : Isolation Forest, One-Class SVM, Benford, supervisé.

Les modèles non supervisés sont ajustés SANS étiquettes ; les étiquettes ne servent qu'à mesurer la
performance (AUC-ROC, AUC-PR, précision@k) sur un jeu de test tenu à l'écart.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import RobustScaler
from sklearn.svm import OneClassSVM

from .preprocessing import reequilibrer

BENFORD = np.log10(1 + 1 / np.arange(1, 10))


def premier_chiffre(montants) -> np.ndarray:
    m = np.abs(np.asarray(montants, float))
    m = m[m >= 1]
    return (m / 10 ** np.floor(np.log10(m))).astype(int)


def test_benford(montants) -> dict:
    """Loi de Benford (premier chiffre) : χ² et MAD (Nigrini : MAD > 0,015 → non conformité).

    P(d) = log10(1 + 1/d). Un jeu falsifié (montants fabriqués, seuils contournés) s'écarte de cette loi.
    """
    d = premier_chiffre(montants)
    n = len(d)
    if n < 50:
        return {"n": n, "chi2": float("nan"), "p_value": float("nan"), "mad": float("nan"), "conforme": None}
    obs = np.bincount(d, minlength=10)[1:10]
    attendu = BENFORD * n
    chi2 = float(((obs - attendu) ** 2 / attendu).sum())
    mad = float(np.mean(np.abs(obs / n - BENFORD)))
    return {"n": n, "chi2": chi2, "p_value": float(1 - stats.chi2.cdf(chi2, 8)), "mad": mad,
            "conforme": mad <= 0.015, "observe": (obs / n).tolist()}


def precision_au_rang(y_true, score, k: int) -> float:
    idx = np.argsort(-np.asarray(score))[:k]
    return float(np.asarray(y_true)[idx].mean())


def evaluer_detecteurs(X: pd.DataFrame, y, contamination: float = 0.03, seed: int = 0) -> dict:
    """Compare Isolation Forest, One-Class SVM et un Random Forest supervisé (+SMOTE)."""
    y = np.asarray(y).astype(int)
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.3, stratify=y, random_state=seed)
    sc = RobustScaler().fit(X_tr)
    A_tr, A_te = sc.transform(X_tr), sc.transform(X_te)
    k = int(y_te.sum())
    res = {}
    iso = IsolationForest(n_estimators=300, contamination=contamination, random_state=seed).fit(A_tr)
    s_iso = -iso.score_samples(A_te)
    res["Isolation Forest"] = {"auc_roc": roc_auc_score(y_te, s_iso), "auc_pr": average_precision_score(y_te, s_iso),
                               f"precision@{k}": precision_au_rang(y_te, s_iso, k)}
    n_fit = min(len(A_tr), 4000)                     # OC-SVM : coût O(n²), sous-échantillonnage
    idx = np.random.default_rng(seed).choice(len(A_tr), n_fit, replace=False)
    oc = OneClassSVM(kernel="rbf", gamma="scale", nu=contamination * 2).fit(A_tr[idx])
    s_oc = -oc.score_samples(A_te)
    res["One-Class SVM"] = {"auc_roc": roc_auc_score(y_te, s_oc), "auc_pr": average_precision_score(y_te, s_oc),
                            f"precision@{k}": precision_au_rang(y_te, s_oc, k)}
    Ar, yr = reequilibrer(pd.DataFrame(A_tr, columns=X.columns), y_tr, "smote", seed=seed)
    rf = RandomForestClassifier(n_estimators=300, min_samples_leaf=2, n_jobs=-1, random_state=seed).fit(Ar, yr)
    s_rf = rf.predict_proba(pd.DataFrame(A_te, columns=X.columns))[:, 1]
    res["Random Forest supervisé (+SMOTE)"] = {"auc_roc": roc_auc_score(y_te, s_rf),
                                                "auc_pr": average_precision_score(y_te, s_rf),
                                                f"precision@{k}": precision_au_rang(y_te, s_rf, k)}
    res["_meta"] = {"n_test": len(y_te), "fraudes_test": k, "prevalence": float(y_te.mean())}
    return res


class DetecteurFraude:
    """Détecteur prêt à l'emploi : Isolation Forest ajusté sur des écritures « normales » + règles."""

    def __init__(self, contamination: float = 0.03, seed: int = 0):
        self.scaler = RobustScaler()
        self.modele = IsolationForest(n_estimators=300, contamination=contamination, random_state=seed)
        self.colonnes: list[str] = []

    def fit(self, X: pd.DataFrame) -> "DetecteurFraude":
        self.colonnes = list(X.columns)
        self.modele.fit(self.scaler.fit_transform(X))
        return self

    def score(self, X: pd.DataFrame) -> np.ndarray:
        """Score d'anomalie normalisé dans [0, 1] (1 = très atypique)."""
        brut = -self.modele.score_samples(self.scaler.transform(X[self.colonnes]))
        return np.clip((brut - 0.3) / 0.4, 0, 1)

    @staticmethod
    def motifs(ligne: pd.Series) -> list[str]:
        """Raisons lisibles (règles métier) ajoutées au score pour le contrôleur interne."""
        m = []
        if ligne.get("proche_seuil", 0):
            m.append("montant juste sous le seuil d'approbation (possible fractionnement)")
        if ligne.get("montant_rond", 0):
            m.append("montant anormalement rond")
        if ligne.get("nuit", 0) or ligne.get("week_end", 0):
            m.append("saisie hors horaires normaux (nuit ou week-end)")
        if ligne.get("doublon", 0):
            m.append("écriture identique déjà présente (doublon potentiel)")
        if ligne.get("freq_paire", 1) < 0.0005:
            m.append("couple fournisseur/compte très rare")
        return m
