"""Métriques d'évaluation rigoureuses : classification (AUC-ROC, F1, PR, matrice) et régression."""
from __future__ import annotations

import numpy as np
from sklearn.metrics import (average_precision_score, brier_score_loss, confusion_matrix, f1_score,
                             mean_absolute_error, mean_squared_error, precision_recall_curve,
                             precision_score, recall_score, roc_auc_score, roc_curve)


def seuil_optimal_f1(y_true, proba) -> float:
    """Seuil maximisant le F1 sur la courbe précision-rappel (à choisir sur la VALIDATION, jamais sur le test)."""
    p, r, t = precision_recall_curve(y_true, proba)
    f1 = 2 * p[:-1] * r[:-1] / np.clip(p[:-1] + r[:-1], 1e-12, None)
    return float(t[int(np.nanargmax(f1))]) if len(t) else 0.5


def metriques_classification(y_true, proba, seuil: float = 0.5) -> dict:
    y_true = np.asarray(y_true)
    proba = np.asarray(proba, dtype=float)
    pred = (proba >= seuil).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, pred, labels=[0, 1]).ravel()
    return {
        "auc_roc": float(roc_auc_score(y_true, proba)),
        "auc_pr": float(average_precision_score(y_true, proba)),
        "f1": float(f1_score(y_true, pred, zero_division=0)),
        "precision": float(precision_score(y_true, pred, zero_division=0)),
        "rappel": float(recall_score(y_true, pred, zero_division=0)),
        "brier": float(brier_score_loss(y_true, proba)),
        "seuil": float(seuil),
        "matrice_confusion": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "prevalence": float(y_true.mean()),
    }


def courbes(y_true, proba) -> dict:
    fpr, tpr, _ = roc_curve(y_true, proba)
    p, r, _ = precision_recall_curve(y_true, proba)
    return {"roc": (fpr, tpr), "pr": (r, p)}


def metriques_regression(y_true, y_pred, y_train_naif=None) -> dict:
    y_true, y_pred = np.asarray(y_true, float), np.asarray(y_pred, float)
    out = {"mae": float(mean_absolute_error(y_true, y_pred)),
           "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred)))}
    if y_train_naif is not None and len(y_train_naif) > 1:
        echelle = float(np.mean(np.abs(np.diff(np.asarray(y_train_naif, float)))))
        out["mase"] = out["mae"] / echelle if echelle > 0 else float("nan")
    return out


def intervalle_bootstrap(y_true, proba, fonction, n: int = 500, seed: int = 0, alpha: float = 0.05) -> tuple[float, float]:
    """Intervalle de confiance bootstrap (percentiles) d'une métrique `fonction(y, p)`."""
    rng = np.random.default_rng(seed)
    y_true, proba = np.asarray(y_true), np.asarray(proba)
    vals = []
    for _ in range(n):
        idx = rng.integers(0, len(y_true), len(y_true))
        if len(np.unique(y_true[idx])) < 2:
            continue
        vals.append(fonction(y_true[idx], proba[idx]))
    return float(np.quantile(vals, alpha / 2)), float(np.quantile(vals, 1 - alpha / 2))
