"""Interprétabilité : SHAP (si installé), importance par permutation, explication locale type LIME.

- Global : importance par permutation (baisse d'AUC quand une variable est mélangée) ; SHAP si dispo.
- Local : SHAP (arbres) si dispo ; sinon un substitut local pondéré à la LIME : on perturbe le point
  autour de sa valeur, on pondère par un noyau exponentiel de la distance, puis on ajuste une
  régression Ridge sur les probabilités du modèle ; les coefficients × écarts mesurent la contribution.
  Si le paquet `lime` est installé, `expliquer_lime` l'utilise directement.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance
from sklearn.linear_model import Ridge

try:
    import shap as _shap
    SHAP_OK = True
except Exception:                                      # pragma: no cover
    _shap, SHAP_OK = None, False
try:
    from lime.lime_tabular import LimeTabularExplainer as _Lime
    LIME_OK = True
except Exception:                                      # pragma: no cover
    _Lime, LIME_OK = None, False

LIBELLES = {
    "ratio_liquidite_generale": "liquidité générale", "ratio_liquidite_reduite": "liquidité réduite",
    "ratio_liquidite_immediate": "liquidité immédiate", "marge_nette": "marge nette", "marge_ebe": "marge d'EBE",
    "marge_exploitation": "marge d'exploitation", "roa": "rentabilité des actifs (ROA)",
    "roe": "rentabilité des capitaux propres (ROE)", "roce": "rentabilité des capitaux investis",
    "rotation_actif": "rotation de l'actif", "autonomie_financiere": "autonomie financière",
    "endettement_cp": "endettement / capitaux propres", "couverture_interets": "couverture des intérêts",
    "poids_dettes_totales": "poids des dettes totales", "marge_valeur_ajoutee": "taux de valeur ajoutée",
    "dso_jours": "délai clients (jours)", "dio_jours": "durée de stockage (jours)",
    "dpo_jours": "délai fournisseurs (jours)", "bfr_jours_ca": "BFR en jours de CA",
    "fr_sur_actif": "fonds de roulement / actif", "tn_sur_actif": "trésorerie nette / actif",
    "altman_x1": "fonds de roulement / actif (Altman)", "altman_x2": "réserves / actif (Altman)",
    "altman_x3": "résultat d'exploitation / actif (Altman)", "altman_x4": "capitaux propres / dettes (Altman)",
    "log_total_actif": "taille (log de l'actif)", "croissance_ca": "croissance du chiffre d'affaires",
    "dsri": "indice créances (Beneish)", "gmi": "indice marge brute (Beneish)", "aqi": "indice qualité des actifs (Beneish)",
    "sgi": "indice de croissance (Beneish)", "tata": "accruals totaux / actif (Beneish)",
}


def libelle(nom: str) -> str:
    return LIBELLES.get(nom, nom.replace("_", " "))


def importance_permutation(modele, X_transforme: pd.DataFrame, y, n_repetitions: int = 10, seed: int = 0) -> pd.DataFrame:
    r = permutation_importance(modele, X_transforme, y, scoring="roc_auc", n_repeats=n_repetitions,
                               random_state=seed, n_jobs=1)
    out = pd.DataFrame({"variable": X_transforme.columns, "baisse_auc": r.importances_mean,
                        "ecart_type": r.importances_std}).sort_values("baisse_auc", ascending=False)
    out["libelle"] = out["variable"].map(libelle)
    return out.reset_index(drop=True)


def explication_locale(modele, x: pd.Series, fond: pd.DataFrame, n_perturbations: int = 1500,
                       seed: int = 0, top: int = 8) -> pd.DataFrame:
    """Explication locale type LIME d'une prédiction (x : ligne déjà transformée par le préprocesseur).

    Retourne les `top` variables avec contribution = coefficient local × (x − moyenne du fond) :
    contribution > 0 augmente la probabilité de défaut estimée.
    """
    rng = np.random.default_rng(seed)
    sigma = fond.std().replace(0, 1.0).to_numpy()
    mu = fond.mean().to_numpy()
    x0 = x.to_numpy(float)
    Z = x0 + rng.normal(0, 1, (n_perturbations, len(x0))) * sigma * 0.6
    Z[0] = x0
    probas = modele.predict_proba(pd.DataFrame(Z, columns=fond.columns))[:, 1]
    dist = np.sqrt((((Z - x0) / sigma) ** 2).sum(axis=1))
    poids = np.exp(-(dist ** 2) / (2 * (0.75 * np.sqrt(len(x0))) ** 2))
    reg = Ridge(alpha=1.0).fit((Z - mu) / sigma, probas, sample_weight=poids)
    contrib = reg.coef_ * ((x0 - mu) / sigma)
    df = pd.DataFrame({"variable": fond.columns, "valeur": x0, "contribution": contrib,
                       "ecart_moyenne": x0 - mu})
    df["libelle"] = df["variable"].map(libelle)
    df["poids_abs"] = df["contribution"].abs()
    return df.sort_values("poids_abs", ascending=False).head(top).drop(columns="poids_abs").reset_index(drop=True)


def expliquer_shap(modele, X: pd.DataFrame, fond: pd.DataFrame | None = None, max_lignes: int = 200):
    """Valeurs SHAP (classe « défaut »). Nécessite `pip install shap`. Arbres : TreeExplainer exact ;
    autres modèles : KernelExplainer sur un fond de 50 points (lent)."""
    if not SHAP_OK:
        raise RuntimeError("Le paquet `shap` n'est pas installé : pip install shap")
    Xs = X.head(max_lignes)
    try:
        explainer = _shap.TreeExplainer(modele)
        vals = explainer.shap_values(Xs)
    except Exception:
        fond = (fond if fond is not None else X).sample(min(50, len(X)), random_state=0)
        explainer = _shap.KernelExplainer(lambda d: modele.predict_proba(pd.DataFrame(d, columns=X.columns))[:, 1], fond)
        vals = explainer.shap_values(Xs, nsamples=100)
    if isinstance(vals, list):
        vals = vals[1]
    vals = np.asarray(vals)
    if vals.ndim == 3:
        vals = vals[:, :, 1]
    return pd.DataFrame(vals, columns=X.columns, index=Xs.index)


def expliquer_lime(modele, X_fond: pd.DataFrame, x: pd.Series, top: int = 8):
    """LIME officiel (si installé)."""
    if not LIME_OK:
        raise RuntimeError("Le paquet `lime` n'est pas installé : pip install lime")
    e = _Lime(X_fond.to_numpy(), feature_names=list(X_fond.columns), class_names=["sain", "défaut"], mode="classification")
    ex = e.explain_instance(x.to_numpy(), lambda d: modele.predict_proba(pd.DataFrame(d, columns=X_fond.columns)), num_features=top)
    return ex.as_list()


def phrase_management(explication: pd.DataFrame, proba: float, seuil: float) -> list[str]:
    """Traduit une explication locale en phrases pour le management."""
    niveau = "ÉLEVÉ" if proba >= seuil else "modéré ou faible"
    msgs = [f"Risque de défaut estimé à {proba:.0%} (niveau {niveau}, seuil de décision {seuil:.0%})."]
    for _, r in explication.head(5).iterrows():
        sens = "aggrave" if r["contribution"] > 0 else "réduit"
        pos = "plus élevée" if r.get("ecart_moyenne", 0) > 0 else "plus basse"
        msgs.append(f"{r['libelle'].capitalize()}, {pos} que la moyenne du portefeuille, {sens} le risque "
                    f"(effet {abs(r['contribution']):.3f}).")
    return msgs
