"""Figures et tableaux pour le rapport académique (matplotlib, sans interface graphique)."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import ConfusionMatrixDisplay, precision_recall_curve, roc_curve


def courbes_roc_pr(y, probas: dict, chemin: Path) -> None:
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.2))
    for nom, p in probas.items():
        fpr, tpr, _ = roc_curve(y, p)
        pr, rc, _ = precision_recall_curve(y, p)
        ax[0].plot(fpr, tpr, label=nom)
        ax[1].plot(rc, pr, label=nom)
    ax[0].plot([0, 1], [0, 1], "k--", lw=0.8)
    ax[0].set(xlabel="Taux de faux positifs", ylabel="Taux de vrais positifs", title="Courbes ROC")
    ax[1].axhline(np.mean(y), color="k", ls="--", lw=0.8)
    ax[1].set(xlabel="Rappel", ylabel="Précision", title="Courbes précision-rappel")
    ax[0].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(chemin, dpi=150)
    plt.close(fig)


def matrice_confusion(y, proba, seuil: float, titre: str, chemin: Path) -> None:
    fig, ax = plt.subplots(figsize=(3.8, 3.6))
    ConfusionMatrixDisplay.from_predictions(y, (np.asarray(proba) >= seuil).astype(int), ax=ax, colorbar=False,
                                            display_labels=["sain", "défaut"], cmap="Blues")
    ax.set_title(titre, fontsize=9)
    fig.tight_layout()
    fig.savefig(chemin, dpi=150)
    plt.close(fig)


def barres_importance(df: pd.DataFrame, chemin: Path, titre: str = "Importance par permutation (baisse d'AUC)", top: int = 12) -> None:
    d = df.head(top).iloc[::-1]
    fig, ax = plt.subplots(figsize=(7, 4.4))
    ax.barh(d["libelle"], d["baisse_auc"], xerr=d["ecart_type"], color="#2E86C1")
    ax.set(title=titre, xlabel="Baisse d'AUC")
    fig.tight_layout()
    fig.savefig(chemin, dpi=150)
    plt.close(fig)


def prevision(hist: pd.Series, prev: pd.DataFrame, chemin: Path, reel: pd.Series | None = None) -> None:
    fig, ax = plt.subplots(figsize=(9, 3.8))
    ax.plot(hist.index, hist.values, label="historique", color="#555")
    ax.plot(prev.index, prev["prevision"], label="prévision", color="#C0392B")
    ax.fill_between(prev.index, prev["bas"], prev["haut"], alpha=0.2, color="#C0392B", label="intervalle 90 %")
    if reel is not None:
        ax.plot(reel.index, reel.values, label="réel", color="#1E8449")
    ax.set(title="Prévision du flux net de trésorerie (hebdomadaire)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(chemin, dpi=150)
    plt.close(fig)


def benford(observe, chemin: Path) -> None:
    from .ml.anomaly import BENFORD
    fig, ax = plt.subplots(figsize=(5.5, 3.5))
    ax.bar(range(1, 10), observe, alpha=0.7, label="observé")
    ax.plot(range(1, 10), BENFORD, "ro-", label="Benford")
    ax.set(xlabel="Premier chiffre", ylabel="Fréquence", title="Loi de Benford")
    ax.legend()
    fig.tight_layout()
    fig.savefig(chemin, dpi=150)
    plt.close(fig)
