"""Pré-évaluation du risque de contrôle douanier (apprentissage automatique) sur des dossiers SIMULÉS.

IMPORTANT : les critères réels de sélection de la douane sont confidentiels. Ce modèle n'essaie pas de les
deviner : il apprend des règles de risque que J'AI ÉCRITES (produit sensible, sous-évaluation, nouvel importateur,
historique, origine). Il sert à PRÉPARER ses documents (« mon dossier ressemble-t-il à un dossier à risque ? »),
jamais à prédire une décision officielle. Les étiquettes simulées ne reflètent aucune statistique réelle.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, recall_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

CANAUX = ["vert", "orange", "rouge"]
# sensibilité SUPPOSÉE par chapitre du Système Harmonisé (hypothèse de simulation, pas une règle douanière)
SENSIBILITE = {"87": 2.0, "24": 2.0, "22": 1.5, "93": 3.0, "71": 2.0, "30": 1.0, "85": 1.0, "61": 0.8, "62": 0.8, "64": 0.8}
ORIGINES = ["Chine", "Inde", "Turquie", "Union européenne", "Brésil", "Émirats", "Autre"]
ORIGINE_RISQUE = {"Chine": 0.4, "Inde": 0.2, "Turquie": 0.2, "Union européenne": 0.0, "Brésil": 0.1, "Émirats": 0.5, "Autre": 0.4}
REGIMES = ["C100", "C200", "C300"]
FEATURES_NUM = ["log_valeur", "ecart_prix", "log_historique", "taux_anomalies", "nouvel_importateur", "sensibilite"]
FEATURES_CAT = ["origine", "regime"]
PHRASES = {
    "log_valeur": "valeur du dossier élevée", "ecart_prix": "prix déclaré inférieur au prix habituel du produit",
    "log_historique": "peu d'historique de l'importateur", "taux_anomalies": "anomalies passées de l'importateur",
    "nouvel_importateur": "importateur nouveau", "sensibilite": "produit considéré comme sensible",
}


_P_CH = np.array([2, 1, 2, .2, .5, 2, 5, 5, 4, 3, 6, 6, 5, 7, 4, 4], dtype=float)


def generer_dossiers(n: int = 4000, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    chapitres = rng.choice(["87", "24", "22", "93", "71", "30", "85", "61", "62", "64", "10", "39", "73", "84", "94", "25"],
                           n, p=_P_CH / _P_CH.sum())
    valeur = rng.lognormal(16.0, 1.3, n)                       # FCFA
    ecart = np.clip(rng.normal(0.0, 0.25, n), -0.9, 1.0)       # prix déclaré / prix habituel − 1
    nb = rng.poisson(8, n) * rng.choice([0, 1], n, p=[0.15, 0.85])
    anomalies = np.where(nb > 0, np.clip(rng.beta(1.2, 12, n), 0, 1), 0.0)
    nouvel = (nb == 0).astype(int)
    origine = rng.choice(ORIGINES, n, p=[.35, .12, .08, .22, .06, .07, .10])
    regime = rng.choice(REGIMES, n, p=[.8, .12, .08])
    sens = np.array([SENSIBILITE.get(c, 0.0) for c in chapitres])
    latent = (0.9 * sens + 1.8 * np.maximum(-ecart - 0.2, 0) * 3 + 0.9 * nouvel + 3.5 * anomalies
              - 0.25 * np.log1p(nb) + np.array([ORIGINE_RISQUE[o] for o in origine])
              + 0.12 * (np.log(valeur) - 16) + rng.normal(0, 0.8, n))
    q1, q2 = np.quantile(latent, [0.62, 0.90])                  # ≈ 62 % vert, 28 % orange, 10 % rouge (hypothèse)
    canal = np.where(latent < q1, "vert", np.where(latent < q2, "orange", "rouge"))
    return pd.DataFrame({"chapitre": chapitres, "valeur_caf": valeur.round(0), "ecart_prix": ecart.round(3),
                         "nb_dossiers_importateur": nb, "taux_anomalies": anomalies.round(3),
                         "origine": origine, "regime": regime, "canal": canal})


def variables(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "log_valeur": np.log(np.maximum(df["valeur_caf"].astype(float), 1.0)),
        "ecart_prix": df["ecart_prix"].astype(float),
        "log_historique": np.log1p(df["nb_dossiers_importateur"].astype(float)),
        "taux_anomalies": df["taux_anomalies"].astype(float),
        "nouvel_importateur": (df["nb_dossiers_importateur"] == 0).astype(int),
        "sensibilite": df["chapitre"].astype(str).str[:2].map(SENSIBILITE).fillna(0.0),
        "origine": df["origine"], "regime": df["regime"]})


def _pipe(modele) -> Pipeline:
    pre = ColumnTransformer([("num", StandardScaler(), FEATURES_NUM),
                             ("cat", OneHotEncoder(handle_unknown="ignore"), FEATURES_CAT)])
    return Pipeline([("p", pre), ("m", modele)])


class ModeleControle:
    def __init__(self, logistique: Pipeline, boosting: Pipeline, metriques: dict, fond: pd.Series):
        self.logistique, self.boosting, self.metriques, self.fond = logistique, boosting, metriques, fond

    def predire(self, dossier: dict) -> dict:
        """Probabilités par canal + 3 raisons principales (contributions du modèle logistique, en mots)."""
        d = pd.DataFrame([{"chapitre": str(dossier["chapitre"]), "valeur_caf": float(dossier["valeur_caf"]),
                           "ecart_prix": float(dossier["ecart_prix"]),
                           "nb_dossiers_importateur": int(dossier["nb_dossiers_importateur"]),
                           "taux_anomalies": float(dossier["taux_anomalies"]),
                           "origine": dossier["origine"], "regime": dossier["regime"]}])
        if d.loc[0, "valeur_caf"] < 0:
            raise ValueError("La valeur ne peut pas être négative.")
        x = variables(d)
        proba = self.logistique.predict_proba(x)[0]
        classes = list(self.logistique.named_steps["m"].classes_)
        p = {c: float(proba[classes.index(c)]) for c in CANAUX}
        z = self.logistique.named_steps["p"].transform(x)[0]
        coef = self.logistique.named_steps["m"].coef_[classes.index("rouge")]
        noms = self.logistique.named_steps["p"].get_feature_names_out()
        contrib = {n.split("__", 1)[1]: float(c * v) for n, c, v in zip(noms, coef, z)}
        raisons = [(PHRASES[k], v) for k, v in sorted(contrib.items(), key=lambda t: -t[1]) if k in PHRASES and v > 0.05][:3]
        return {"probabilites": p, "canal_probable": max(p, key=p.get), "raisons": [r for r, _ in raisons]}


def entrainer(df: pd.DataFrame | None = None, seed: int = 0) -> ModeleControle:
    df = generer_dossiers() if df is None else df
    X, y = variables(df), df["canal"]
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.25, random_state=seed, stratify=y)
    log = _pipe(LogisticRegression(max_iter=2000, class_weight="balanced", random_state=seed)).fit(X_tr, y_tr)
    gb = _pipe(HistGradientBoostingClassifier(max_depth=3, learning_rate=0.06, max_iter=200, random_state=seed)).fit(X_tr, y_tr)
    majo = y_tr.value_counts().idxmax()
    def ev(pred):
        return {"exactitude": float(accuracy_score(y_te, pred)),
                "f1_macro": float(f1_score(y_te, pred, average="macro")),
                "rappel_rouge": float(recall_score(y_te, pred, labels=["rouge"], average="macro", zero_division=0))}
    m = {"Référence (toujours « vert »)": ev(np.full(len(y_te), majo)),
         "Régression logistique": ev(log.predict(X_te)), "Gradient boosting": ev(gb.predict(X_te))}
    m["_matrice_logistique"] = confusion_matrix(y_te, log.predict(X_te), labels=CANAUX).tolist()
    m["_n_test"] = int(len(y_te))
    return ModeleControle(log, gb, m, X_tr[FEATURES_NUM].mean())
