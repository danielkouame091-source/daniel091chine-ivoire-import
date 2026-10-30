# Mini Project — Machine Learning & Deep Learning
### Predicting the customs inspection lane (green / orange / red) of import files

**Author:** Kouassi Kouame Daniel · **UID:** 25MDA10119
**Programme:** MBA Data Science & AI · Chandigarh University, India

---

## 1. Problem
When goods are imported into Côte d'Ivoire, customs assigns each file a **lane**: *green* (release), *orange* (documents checked) or *red* (full physical inspection). A customs broker would like to know **before filing** whether a file looks risky, in order to prepare its documents. This is a **3-class classification** problem with **imbalanced classes** (≈ 62 % green, 28 % orange, 10 % red).

## 2. Data — and its main limit
The real selection criteria of customs are confidential and no real data is available to me. The dataset is therefore **simulated** (4 000 files) by the generator `finai/logistique/douane.py`, with 8 features: value, gap between declared price and usual price, importer history, past anomaly rate, new-importer flag, product sensitivity, origin country, customs regime.
The labels come from risk rules **written by me** plus random noise. Consequence: the models can only *rediscover those rules*; the results prove that the **method works**, not that it predicts real customs decisions. This is stated clearly in the application too.

## 3. Methods (what was covered in class)
| Type of learning | Algorithm | Role in the project |
|---|---|---|
| Baseline | "always predict green" | Minimum to beat |
| Supervised | **KNN** | k and distance weighting tuned by cross-validation (figure 02) |
| Supervised | Logistic Regression | Simple, explainable model |
| Supervised | Decision Tree | Readable rules, depth tuned |
| Supervised | Random Forest | Ensemble of trees |
| Supervised | SVM (RBF kernel) | Non-linear boundary |
| **Deep learning** | **Multi-Layer Perceptron** (64 → 32 → 3, ReLU, softmax, early stopping) | Neural network; learning curves in figure 03 |
| Unsupervised | **PCA + K-Means** | Look for natural groups without using the labels (figure 06) |

**Protocol (to avoid cheating):** 75 % / 25 % stratified split → all tuning by **5-fold cross-validation on the training set only** → the test set is used **once**, at the end. Preprocessing (scaling, one-hot) is inside a pipeline so that nothing leaks from the test set.
**Metrics:** accuracy is misleading with imbalanced classes (always-green already gets 62 %), so the main metric is **macro-F1**, together with **recall on red files** (a missed red file is the costly mistake).

## 4. Results (test set, 1 000 files)
| Model | Accuracy | Macro-F1 | Red recall |
|---|---|---|---|
| Neural network (MLP) | 0.706 | **0.606** | 0.46 |
| SVM (RBF) | 0.658 | 0.596 | **0.76** |
| Random Forest | 0.655 | 0.579 | 0.56 |
| Logistic Regression | 0.644 | 0.574 | 0.71 |
| Decision Tree | 0.600 | 0.571 | 0.55 |
| KNN | 0.650 | 0.537 | 0.39 |
| Baseline (always green) | 0.620 | 0.255 | 0.00 |

Figures are in `results/` (`04_comparison.png`, `05_confusion_matrix.png`, …) and the table in `results/results.csv`.

## 5. Discussion
1. **Every model clearly beats the baseline** (macro-F1 0.54–0.61 vs 0.26): the features carry real information.
2. **The neural network has the best macro-F1 and accuracy, but the gap with SVM and Random Forest is small** (0.606 vs 0.596) and comes from a single test split of 1 000 files, so I do **not** claim it is significantly better. Repeating the split with several seeds would be needed to confirm.
3. **The best metric depends on the goal.** The MLP finds only 46 % of red files, the SVM 76 % and Logistic Regression 71 %. For a risk check, where missing a red file is costly, **SVM or Logistic Regression is the better choice** even though the MLP wins on macro-F1. The MLP has no class-weight option here, which explains part of this.
4. **KNN is the weakest.** With 8 features (some one-hot encoded) distances become less informative, and KNN is sensitive to noise; best k = 5 with distance weighting (figure 02 shows the bias/variance trade-off).
5. **Deep learning is not magic on tabular data.** With 3 000 training rows and 8 features, a small network performs about like classical models; its advantage appears with images, text or very large datasets. A **CNN** (as seen in class for traffic / congestion images) is designed for images or sequences, so it does not fit this tabular problem; it would fit, for example, port-congestion satellite or camera images.
6. **Unsupervised result:** K-Means finds 2 groups (best silhouette 0.40). One group has 27 % red files and the other 7 %, so the structure of the data matches risk **without ever seeing the labels**.

## 6. Limits and honest remarks
- Simulated data: no claim about real customs behaviour.
- One random split; differences between the top models are within the noise.
- The MLP comes from scikit-learn (small network). A PyTorch/TensorFlow version, a CNN on port images, or an LSTM on delay time series are natural extensions.
- Customs lanes are decisions by officers; this tool only helps to *prepare* a file.

## 7. How to run
```bash
cd ~/daniel091chine-ivoire-import
python3 mini_project/mini_project_ml_dl.py      # about 35 seconds
```
Needs: `numpy pandas scikit-learn matplotlib` (already in `requirements.txt`). The same models are used inside the ERP: tile **AI → Methodology & results**.

## 8. Files
```
mini_project/
├── README.md                  ← this report
├── mini_project_ml_dl.py      ← the whole experiment (one script)
└── results/
    ├── results.csv
    ├── 01_data.png  02_knn_k.png  03_mlp_learning_curve.png
    └── 04_comparison.png  05_confusion_matrix.png  06_pca_kmeans.png
```
