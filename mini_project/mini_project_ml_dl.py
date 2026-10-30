"""
Mini project - Machine Learning & Deep Learning
Customs inspection-lane prediction (green / orange / red) for import files in Cote d'Ivoire.

Author : Kouassi Kouame Daniel - UID 25MDA10119
Course : MBA Data Science & AI - Chandigarh University, India

What this script does (one command, ~1 minute):
  1. Builds the dataset (SIMULATED customs files - see README for the honest limits).
  2. Supervised learning  : Baseline, KNN, Logistic Regression, Decision Tree, Random Forest, SVM.
  3. Deep learning        : Multi-Layer Perceptron (neural network) with a loss curve.
  4. Unsupervised learning: PCA + K-Means to look for natural groups of files.
  5. Compares all models on a test set that was never used for training, and saves tables + figures.

Run from the project root:   python3 mini_project/mini_project_ml_dl.py
Outputs go to:               mini_project/results/
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")                       # no window needed: figures are saved as PNG files
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score, recall_score,
                             silhouette_score, ConfusionMatrixDisplay)
from sklearn.model_selection import GridSearchCV, StratifiedKFold, train_test_split
from sklearn.neighbors import KNeighborsClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.svm import SVC
from sklearn.tree import DecisionTreeClassifier

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from finai.logistique.douane import (CANAUX, FEATURES_CAT, FEATURES_NUM, _pipe,        # noqa: E402
                                     generer_dossiers, variables)

OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(exist_ok=True)
SEED = 42
ENGLISH = {"vert": "green", "orange": "orange", "rouge": "red"}
LANES = [ENGLISH[c] for c in CANAUX]


def title(text: str) -> None:
    print("\n" + "=" * 70 + f"\n{text}\n" + "=" * 70)


# ── 1. Data ──────────────────────────────────────────────────────────────────
title("1. DATA")
df = generer_dossiers(n=4000, seed=11)
X, y = variables(df), df["canal"].map(ENGLISH)
print(f"{len(df)} simulated customs files, {X.shape[1]} features "
      f"({len(FEATURES_NUM)} numeric + {len(FEATURES_CAT)} categorical)")
print("Class balance :", y.value_counts(normalize=True).round(3).to_dict())

X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.25, random_state=SEED, stratify=y)
print(f"Train = {len(X_tr)} files | Test = {len(X_te)} files (kept aside until the very end)")

fig, ax = plt.subplots(1, 2, figsize=(10, 3.5))
y.value_counts().reindex(LANES).plot.bar(ax=ax[0], color=["#30D158", "#FF9F0A", "#FF453A"], rot=0)
ax[0].set_title("Class distribution (imbalanced)"); ax[0].set_ylabel("files")
ax[1].hist(X["ecart_prix"], bins=40, color="#0A84FF"); ax[1].set_title("Declared price vs usual price (gap)")
plt.tight_layout(); plt.savefig(OUT / "01_data.png", dpi=130); plt.close()

# ── 2. Supervised learning ───────────────────────────────────────────────────
title("2. SUPERVISED LEARNING (5-fold cross-validation on the training set only)")
cv = StratifiedKFold(5, shuffle=True, random_state=SEED)

def tune(name, estimator, grid):
    gs = GridSearchCV(_pipe(estimator), {f"m__{k}": v for k, v in grid.items()},
                      cv=cv, scoring="f1_macro", n_jobs=-1).fit(X_tr, y_tr)
    print(f"{name:<22} best params = { {k[3:]: v for k, v in gs.best_params_.items()} }  CV macro-F1 = {gs.best_score_:.3f}")
    return gs

gs_knn = tune("KNN", KNeighborsClassifier(), {"n_neighbors": [1, 3, 5, 9, 15, 25, 41, 61], "weights": ["uniform", "distance"]})
gs_log = tune("Logistic Regression", LogisticRegression(max_iter=3000, class_weight="balanced", random_state=SEED), {"C": [0.01, 0.1, 1, 10]})
gs_tree = tune("Decision Tree", DecisionTreeClassifier(class_weight="balanced", random_state=SEED), {"max_depth": [2, 3, 4, 6, 8, 12]})
gs_rf = tune("Random Forest", RandomForestClassifier(class_weight="balanced", random_state=SEED, n_jobs=-1),
             {"n_estimators": [100, 300], "max_depth": [4, 8, None]})
gs_svm = tune("SVM (RBF)", SVC(class_weight="balanced", random_state=SEED), {"C": [0.5, 1, 5], "gamma": ["scale", 0.05]})

# KNN: how does k change the result?  (classic bias/variance picture)
ks = [1, 3, 5, 9, 15, 25, 41, 61, 101]
scores = []
for k in ks:
    s = GridSearchCV(_pipe(KNeighborsClassifier(n_neighbors=k)), {}, cv=cv, scoring="f1_macro").fit(X_tr, y_tr)
    scores.append(s.best_score_)
plt.figure(figsize=(6, 3.6)); plt.plot(ks, scores, "o-", color="#0A84FF"); plt.xscale("log")
plt.xlabel("k (number of neighbours)"); plt.ylabel("CV macro-F1"); plt.title("KNN: choosing k"); plt.grid(alpha=.3)
plt.tight_layout(); plt.savefig(OUT / "02_knn_k.png", dpi=130); plt.close()

# ── 3. Deep learning ─────────────────────────────────────────────────────────
title("3. DEEP LEARNING - Multi-Layer Perceptron (neural network)")
mlp = _pipe(MLPClassifier(hidden_layer_sizes=(64, 32), activation="relu", alpha=1e-3, learning_rate_init=1e-3,
                          max_iter=400, early_stopping=True, validation_fraction=0.15, n_iter_no_change=20,
                          random_state=SEED))
mlp.fit(X_tr, y_tr)
net = mlp.named_steps["m"]
print(f"Architecture: input -> Dense(64, ReLU) -> Dense(32, ReLU) -> Softmax(3)   | epochs run: {net.n_iter_}")
print(f"Trainable weights: {sum(w.size for w in net.coefs_) + sum(b.size for b in net.intercepts_)}")
plt.figure(figsize=(6.5, 3.8))
plt.plot(net.loss_curve_, label="training loss", color="#0A84FF")
plt.plot(1 - np.array(net.validation_scores_), label="validation error (1 - accuracy)", color="#FF9F0A")
plt.xlabel("epoch"); plt.title("Neural network learning curves"); plt.legend(); plt.grid(alpha=.3)
plt.tight_layout(); plt.savefig(OUT / "03_mlp_learning_curve.png", dpi=130); plt.close()

# ── 4. Test-set comparison ───────────────────────────────────────────────────
title("4. FINAL COMPARISON ON THE UNSEEN TEST SET")
models = {"Baseline (always green)": None, "KNN": gs_knn.best_estimator_, "Logistic Regression": gs_log.best_estimator_,
          "Decision Tree": gs_tree.best_estimator_, "Random Forest": gs_rf.best_estimator_,
          "SVM (RBF)": gs_svm.best_estimator_, "Neural network (MLP)": mlp}
rows, preds = [], {}
for name, m in models.items():
    p = np.full(len(y_te), y_tr.value_counts().idxmax()) if m is None else m.predict(X_te)
    preds[name] = p
    rows.append({"model": name, "accuracy": accuracy_score(y_te, p), "macro_F1": f1_score(y_te, p, average="macro"),
                 "red_recall": recall_score(y_te, p, labels=["red"], average="macro", zero_division=0)})
res = pd.DataFrame(rows).set_index("model").round(3).sort_values("macro_F1", ascending=False)
print(res.to_string())
res.to_csv(OUT / "results.csv")

ax = res[["accuracy", "macro_F1", "red_recall"]].plot.barh(figsize=(8, 4.6), color=["#8E8E93", "#0A84FF", "#FF453A"])
ax.invert_yaxis(); ax.set_title("Models compared on the test set"); ax.grid(axis="x", alpha=.3)
plt.tight_layout(); plt.savefig(OUT / "04_comparison.png", dpi=130); plt.close()

best = res.index[res.index != "Baseline (always green)"][0]
fig, ax = plt.subplots(figsize=(4.6, 4))
ConfusionMatrixDisplay(confusion_matrix(y_te, preds[best], labels=LANES), display_labels=LANES).plot(ax=ax, cmap="Blues", colorbar=False)
ax.set_title(f"Confusion matrix - {best}"); plt.tight_layout(); plt.savefig(OUT / "05_confusion_matrix.png", dpi=130); plt.close()

# ── 5. Unsupervised learning ─────────────────────────────────────────────────
title("5. UNSUPERVISED LEARNING - PCA + K-Means (labels NOT used to build the groups)")
Z = _pipe(DecisionTreeClassifier()).named_steps["p"].fit_transform(X_tr)
Z2 = PCA(n_components=2, random_state=SEED).fit_transform(Z)
best_k, best_s = 2, -1
for k in range(2, 7):
    s = silhouette_score(Z, KMeans(k, n_init=10, random_state=SEED).fit_predict(Z), sample_size=1500, random_state=SEED)
    print(f"K-Means k={k}: silhouette = {s:.3f}")
    if s > best_s:
        best_k, best_s = k, s
groups = KMeans(best_k, n_init=10, random_state=SEED).fit_predict(Z)
print(f"-> best k = {best_k}. Share of red files per group:",
      pd.Series((y_tr.values == "red").astype(int)).groupby(groups).mean().round(3).to_dict())
fig, ax = plt.subplots(1, 2, figsize=(10, 4))
ax[0].scatter(Z2[:, 0], Z2[:, 1], c=groups, s=6, cmap="tab10"); ax[0].set_title(f"K-Means groups (k={best_k}) on 2 PCA axes")
ax[1].scatter(Z2[:, 0], Z2[:, 1], c=pd.Series(y_tr.values).map({"green": "#30D158", "orange": "#FF9F0A", "red": "#FF453A"}), s=6)
ax[1].set_title("Same points coloured by true lane")
plt.tight_layout(); plt.savefig(OUT / "06_pca_kmeans.png", dpi=130); plt.close()

title("DONE")
print(f"Best model on the test set: {best}  (macro-F1 = {res.loc[best, 'macro_F1']:.3f}, "
      f"baseline = {res.loc['Baseline (always green)', 'macro_F1']:.3f})")
print(f"Tables and figures saved in: {OUT}")
