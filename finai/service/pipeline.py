"""Couche service : entraînement, persistance, scoring et diagnostics (utilisée par l'API et l'app)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from ..accounting.ratios import diagnostic_complet, lecture_management
from ..accounting.standards import ZONES, get_zone, indicateurs_par_norme
from ..accounting.statement import Statement
from ..data.synthetic import generer_entreprises, generer_transactions
from ..features.engineering import FEATURES_CAT, FEATURES_NUM, caracteristiques_transactions, construire_table
from ..ml.anomaly import DetecteurFraude
from ..ml.explain import explication_locale, importance_permutation, phrase_management
from ..ml.train import ResultatEntrainement, evaluer_modeles, fabrique_modeles

DOSSIER_MODELES = Path(__file__).resolve().parents[3] / "models"


@dataclass
class ModeleSolvabilite:
    nom: str
    modele: object
    preprocesseur: object
    seuil: float
    fond: pd.DataFrame
    metriques: dict


def entrainer_solvabilite(n: int = 4000, seed: int = 42, dossier: Path | None = None,
                          cv_plis: int = 5) -> tuple[ModeleSolvabilite, ResultatEntrainement]:
    """Entraîne tous les modèles, retient celui au meilleur AUC de validation croisée, sauvegarde."""
    df = generer_entreprises(n, seed)
    X, y = construire_table(df), df["defaut_12m"].to_numpy()
    res = evaluer_modeles(X, y, cv_plis=cv_plis, seed=seed)
    meilleur = res.cv["auc_cv_moyen"].idxmax()
    fond = res.preprocesseur.transform(res.X_test).sample(min(200, len(res.X_test)), random_state=seed)
    ms = ModeleSolvabilite(meilleur, res.modeles[meilleur], res.preprocesseur, float(res.seuils[meilleur]), fond,
                           res.tableau.loc[meilleur, ["auc_roc", "auc_pr", "f1", "precision", "rappel"]].to_dict())
    dossier = Path(dossier) if dossier else DOSSIER_MODELES
    dossier.mkdir(parents=True, exist_ok=True)
    joblib.dump(ms, dossier / "solvabilite.joblib")
    (dossier / "solvabilite_metriques.json").write_text(json.dumps(
        {"modele": meilleur, "seuil": ms.seuil, "test": ms.metriques,
         "cv": res.cv.round(4).to_dict(orient="index")}, indent=2, ensure_ascii=False), encoding="utf-8")
    return ms, res


def charger_solvabilite(dossier: Path | None = None) -> ModeleSolvabilite | None:
    f = (Path(dossier) if dossier else DOSSIER_MODELES) / "solvabilite.joblib"
    return joblib.load(f) if f.exists() else None


def _ligne_entreprise(statement: Statement, precedent: Statement | None, zone: str, secteur: str) -> pd.DataFrame:
    ligne = {"zone": zone, "secteur": secteur, **statement.to_dict()}
    if precedent is not None:
        ligne.update({f"prev_{k}": v for k, v in precedent.to_dict().items()})
    return pd.DataFrame([ligne])


def scorer_solvabilite(ms: ModeleSolvabilite, statement: Statement, zone: str = "OHADA", secteur: str = "Commerce",
                       precedent: Statement | None = None) -> dict:
    """Probabilité de défaut à 12 mois + explication locale (type LIME) en langage de gestion."""
    get_zone(zone)
    X = construire_table(_ligne_entreprise(statement, precedent, zone, secteur))
    A = ms.preprocesseur.transform(X)
    proba = float(ms.modele.predict_proba(A)[:, 1][0])
    ex = explication_locale(ms.modele, A.iloc[0], ms.fond)
    niveau = "élevé" if proba >= ms.seuil else ("modéré" if proba >= ms.seuil / 2 else "faible")
    return {"probabilite_defaut": proba, "seuil_decision": ms.seuil, "niveau_risque": niveau, "modele": ms.nom,
            "facteurs": ex[["libelle", "contribution", "ecart_moyenne"]].round(4).to_dict(orient="records"),
            "lecture": phrase_management(ex, proba, ms.seuil)}


def diagnostic_entreprise(statement: Statement, zone: str = "OHADA", precedent: Statement | None = None) -> dict:
    z = get_zone(zone)
    diag = diagnostic_complet(statement, precedent)
    return {"zone": {"cle": z.cle, "zone": z.zone, "referentiel": z.referentiel, "devise": z.devise,
                     "indicateur_operationnel": z.indicateur_operationnel, "differences": list(z.differences)},
            "diagnostic": diag, "lecture": lecture_management(diag),
            "comparaison_normes": indicateurs_par_norme(statement)}


def scorer_transactions(df: pd.DataFrame, detecteur: DetecteurFraude | None = None) -> pd.DataFrame:
    """Score d'anomalie [0,1] + motifs lisibles pour chaque écriture."""
    X = caracteristiques_transactions(df)
    if detecteur is None:
        detecteur = DetecteurFraude().fit(X)
    out = df.copy()
    out["score_anomalie"] = detecteur.score(X)
    out["motifs"] = [", ".join(DetecteurFraude.motifs(r)) for _, r in X.iterrows()]
    return out.sort_values("score_anomalie", ascending=False)
