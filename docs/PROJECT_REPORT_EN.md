# SNDGIR & Transit ERP — Project Report

**Author:** Kouassi Kouame Daniel · UID 25MDA10119 · MBA Data Science & AI, Chandigarh University, India
*(Replace names/dates/course code as required by your submission template.)*

## Abstract
Customs brokers and accounting firms in Côte d'Ivoire work with fragmented tools while delays, inspections and SYSCOHADA compliance drive cost and risk. This project delivers a multi-tenant web ERP that integrates accounting, transit and customs workflows with machine-learning decision support. Two logistics models (vessel delay, customs-inspection risk) are trained on simulated data and always compared with naive baselines; an anomaly-detection and forecasting toolbox supports financial analysis. The contribution is a complete, tested, honestly evaluated prototype and a documented path to real-data validation.

## 1. Introduction and motivation
- Delays at port create demurrage/storage costs; shippers want visibility from origin to Abidjan.
- Côte d'Ivoire already has a national Port Community System operated by GUCE (modules such as e-Voyage, e-Manifest, e-Movement, e-Release at different stages of roll-out — see CIO Mag, March 2026). The project therefore does **not** claim that tracking is absent; it targets the broker's own back office and decision support, and documents an official route for integration.
- Accounting must follow the SYSCOHADA (OHADA) chart and double-entry rules.

## 2. System design
Streamlit interface; SQLite with WAL, tenant isolation and idempotent migrations; role-based access; hash-chained audit log; modular code where business modules receive ERP functions as parameters (avoids circular imports). Security: salted password hashing, login throttling, TOTP two-factor authentication (RFC 6238, verified with the official test vectors), database backup, production mode without demo accounts. Data protection: client data export and irreversible anonymisation preserving accounting records.

## 3. Machine-learning methods
**3.1 Vessel delay.** Features: great-circle distance to Abidjan, transshipments, port congestion, month (cyclic encoding), Chinese-New-Year indicator, carrier. Models: Ridge, histogram gradient boosting; baseline: mean delay. 80/20 split; prediction interval from residual quantiles on a separate validation split; classifier for “more than 3 days late”.

**3.2 Customs-inspection risk.** Three lanes (green/orange/red). Features: log value, price deviation versus the importer’s usual price, importer history, past anomaly rate, product sensitivity, origin, regime. Models: logistic regression (class-balanced), gradient boosting; baseline: always “green”. Metrics: accuracy, macro-F1, red-lane recall — accuracy alone is misleading because the baseline already reaches ~62 %.

**3.3 Financial toolbox.** Isolation Forest, One-Class SVM, Benford’s law and supervised classifiers for anomalies; permutation importance and a LIME-style surrogate (SHAP when installed) for explanation; seasonal-naïve, gradient boosting and MLP for cash-flow forecasting with rolling-origin validation. LSTM/GRU and transformer code paths exist but require PyTorch and are not part of the lightweight deployed demo.

## 4. Results
Live figures are recomputed in the application (*AI & OCR → Methodology & results* and the Showcase page). At the time of writing: delay error ≈ 1.2 days versus ≈ 1.7 for the baseline; customs model macro-F1 ≈ 0.55 versus ≈ 0.26 for “always green”; red-lane recall ≈ 62 % (logistic) versus ≈ 31 % (boosting, despite higher accuracy). Ridge ≈ boosting on delays because the simulated rules are almost linear.

## 5. Discussion and limitations
- **Simulated data:** the models recover rules the author wrote; this validates the pipeline, not real-world accuracy.
- Customs criteria are confidential; the tool prepares files and never predicts official decisions.
- Control-tower alerts are explicit rules, not AI.
- Leakage check: a near-zero error on a ratio derived from the target was identified and not reported as success.
- Hosting on a temporary disk is acceptable for a demo only.

## 6. Conclusion and future work
Pilot with a real broker; retrain on anonymised real data using the provided script and report whether models beat the baselines; request official PCS/GUCE integration; durable hosting; full English interface.

## References
- Pedregosa et al. (2011). *Scikit-learn: Machine Learning in Python.* JMLR 12.
- Liu, Ting, Zhou (2008). *Isolation Forest.* IEEE ICDM.
- Lundberg & Lee (2017). *A Unified Approach to Interpreting Model Predictions (SHAP).* NeurIPS.
- Ribeiro, Singh, Guestrin (2016). *“Why Should I Trust You?” (LIME).* KDD.
- M’Raihi et al. (2011). *TOTP: Time-Based One-Time Password Algorithm.* RFC 6238.
- CIO Mag (March 2026), reporting on the GUCE Côte d’Ivoire Port Community System roll-out.
