"""NLP : classification des libellés comptables (→ classe SYSCOHADA) et des opinions d'audit.

Niveaux :
1. Référence rapide et robuste : TF-IDF (mots + caractères) + régression logistique — toujours disponible.
2. Transformers (BERT / XLM-RoBERTa) : `finetuner_transformer` (nécessite torch + transformers ; non
   exécuté dans les tests automatiques de ce dépôt car ces paquets sont lourds).
3. Ton du rapport : lexique pondéré multilingue (FR/EN) pour un score de risque textuel explicable.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd
from scipy.sparse import hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from sklearn.model_selection import train_test_split


def _nettoyer(t: str) -> str:
    return re.sub(r"\d+", " ", str(t).lower())


class ClassifieurTexte:
    """TF-IDF mots (1–2) + caractères (2–5) → régression logistique multiclasse."""

    def __init__(self, C: float = 8.0, seed: int = 0):
        self.vm = TfidfVectorizer(preprocessor=_nettoyer, ngram_range=(1, 2), sublinear_tf=True, min_df=1)
        self.vc = TfidfVectorizer(preprocessor=_nettoyer, analyzer="char_wb", ngram_range=(2, 5),
                                  sublinear_tf=True, min_df=2)
        self.clf = LogisticRegression(C=C, max_iter=3000, random_state=seed)

    def _x(self, textes, fit=False):
        if fit:
            return hstack([self.vm.fit_transform(textes), self.vc.fit_transform(textes)]).tocsr()
        return hstack([self.vm.transform(textes), self.vc.transform(textes)]).tocsr()

    def fit(self, textes, labels) -> "ClassifieurTexte":
        self.clf.fit(self._x(list(textes), fit=True), list(labels))
        return self

    def predict(self, textes) -> list:
        return list(self.clf.predict(self._x(list(textes))))

    def predict_proba(self, textes) -> pd.DataFrame:
        return pd.DataFrame(self.clf.predict_proba(self._x(list(textes))), columns=self.clf.classes_)

    def termes_influents(self, classe: str, top: int = 8) -> list[tuple[str, float]]:
        """Mots les plus déterminants pour une classe (explicabilité du modèle linéaire)."""
        noms = np.array(list(self.vm.get_feature_names_out()) + list(self.vc.get_feature_names_out()))
        i = list(self.clf.classes_).index(classe)
        idx = np.argsort(-self.clf.coef_[i])[:top]
        return [(str(noms[j]), float(self.clf.coef_[i][j])) for j in idx]


def evaluer_classifieur(df: pd.DataFrame, col_texte: str, col_cible: str, seed: int = 0) -> dict:
    Xtr, Xte, ytr, yte = train_test_split(df[col_texte], df[col_cible], test_size=0.25, stratify=df[col_cible], random_state=seed)
    m = ClassifieurTexte(seed=seed).fit(Xtr, ytr)
    pred = m.predict(Xte)
    classes = sorted(df[col_cible].unique())
    return {"accuracy": float(accuracy_score(yte, pred)), "f1_macro": float(f1_score(yte, pred, average="macro")),
            "classes": classes, "matrice_confusion": confusion_matrix(yte, pred, labels=classes).tolist(),
            "modele": m, "n_test": int(len(yte))}


def evaluer_generalisation(df: pd.DataFrame, col_texte: str, col_cible: str, col_gabarit: str = "gabarit") -> dict:
    """Test plus exigeant : l'entraînement exclut TOUT un gabarit de formulation par classe (le dernier) ;
    le test ne contient que ces formulations jamais vues → mesure la généralisation, pas la mémorisation."""
    dernier = df.groupby(col_cible)[col_gabarit].transform("max")
    test = df[df[col_gabarit] == dernier]
    train = df[df[col_gabarit] != dernier]
    m = ClassifieurTexte().fit(train[col_texte], train[col_cible])
    pred = m.predict(test[col_texte])
    return {"accuracy": float(accuracy_score(test[col_cible], pred)),
            "f1_macro": float(f1_score(test[col_cible], pred, average="macro")), "n_test": int(len(test))}


LEXIQUE_RISQUE = {
    # terme : poids (plus le poids est élevé, plus le signal d'alerte est fort)
    "continuité d'exploitation": 3.0, "going concern": 3.0, "incertitude significative": 2.5, "material uncertainty": 2.5,
    "refus de certifier": 4.0, "impossibilité de certifier": 4.0, "n'exprimons pas d'opinion": 4.0,
    "do not express an opinion": 4.0, "adverse opinion": 4.0, "opinion défavorable": 4.0,
    "réserve": 1.5, "except for": 1.5, "limitation": 1.5, "insuffisants": 1.0, "irrégularité": 2.5,
    "fraude": 3.0, "fraud": 3.0, "capitaux propres inférieurs": 2.5, "cessation de paiement": 3.5,
}
LEXIQUE_POSITIF = {"réguliers et sincères": -2.0, "image fidèle": -2.0, "present fairly": -2.0, "sans réserve": -2.0,
                   "conformes": -1.0}


def score_ton_audit(texte: str) -> dict:
    """Score de risque textuel (somme de poids de termes) et niveau : faible / modéré / élevé."""
    t = str(texte).lower()
    trouves = {k: w for k, w in {**LEXIQUE_RISQUE, **LEXIQUE_POSITIF}.items() if k in t}
    score = float(sum(trouves.values()))
    niveau = "élevé" if score >= 3 else ("modéré" if score > 0 else "faible")
    return {"score": score, "niveau": niveau, "termes": trouves}


def finetuner_transformer(textes: list[str], labels: list[int], modele: str = "xlm-roberta-base",
                          epochs: int = 3, batch: int = 16, lr: float = 2e-5, seed: int = 0, sortie: str = "models/bert_texte"):
    """Fine-tuning BERT/XLM-R pour la classification de textes comptables.

    Nécessite : pip install torch transformers. Utilise un jeu de validation (10 %) pour sélectionner
    la meilleure époque. NON exécuté dans l'environnement de rédaction (aucun accès à PyTorch)."""
    try:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer, Trainer, TrainingArguments, set_seed
    except Exception as exc:                           # pragma: no cover
        raise RuntimeError("Installez : pip install torch transformers") from exc
    set_seed(seed)
    tr_x, va_x, tr_y, va_y = train_test_split(textes, labels, test_size=0.1, stratify=labels, random_state=seed)
    tok = AutoTokenizer.from_pretrained(modele)
    net = AutoModelForSequenceClassification.from_pretrained(modele, num_labels=len(set(labels)))

    class _DS(torch.utils.data.Dataset):
        def __init__(self, x, y):
            self.enc, self.y = tok(list(x), truncation=True, padding=True, max_length=128), list(y)

        def __len__(self):
            return len(self.y)

        def __getitem__(self, i):
            d = {k: torch.tensor(v[i]) for k, v in self.enc.items()}
            d["labels"] = torch.tensor(self.y[i])
            return d

    def metriques(p):
        pred = p.predictions.argmax(-1)
        return {"accuracy": accuracy_score(p.label_ids, pred), "f1_macro": f1_score(p.label_ids, pred, average="macro")}

    args = TrainingArguments(output_dir=sortie, num_train_epochs=epochs, per_device_train_batch_size=batch,
                             learning_rate=lr, eval_strategy="epoch", save_strategy="epoch", load_best_model_at_end=True,
                             metric_for_best_model="f1_macro", seed=seed, report_to=[])
    tr = Trainer(model=net, args=args, train_dataset=_DS(tr_x, tr_y), eval_dataset=_DS(va_x, va_y), compute_metrics=metriques)
    tr.train()
    return tr
