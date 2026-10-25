"""Project Showcase (English) — landing page for examiners.

Everything numeric on this page is computed live (model metrics, line counts, file counts):
nothing is hard-coded, so the page cannot drift from the code.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from sndgir_menu import AUTEUR, PROGRAMME, html_grille, html_kpi, sous_menu

RACINE = Path(__file__).resolve().parent
TITRE = "SNDGIR & Transit ERP"
SOUS_TITRE = ("An AI-assisted ERP for customs brokers and accountants in Côte d'Ivoire — "
              "accounting (SYSCOHADA), import/export tracking and honest machine learning.")


@st.cache_data(show_spinner=False)
def statistiques_code() -> dict:
    fichiers = [f for f in list(RACINE.glob("*.py")) + list((RACINE / "finai").rglob("*.py")) if "__pycache__" not in str(f)]
    lignes = 0
    for f in fichiers:
        try:
            lignes += sum(1 for _ in f.open(encoding="utf-8", errors="ignore"))
        except OSError:
            pass
    return {"lignes": lignes, "modules": len(fichiers), "validations": len(list(RACINE.glob("valider_*.py")))}


def _titre(texte: str) -> None:
    st.markdown(f"### {texte}")


def _flux(etapes: list[tuple[str, str]]) -> str:
    cases = "".join(
        f'<div style="flex:1 1 150px;padding:14px 16px;border-radius:18px;border:1px solid rgba(255,255,255,.16);'
        f'background:rgba(255,255,255,.05)"><div style="font-weight:800;font-size:1.02rem">{t}</div>'
        f'<div style="font-size:.88rem;color:#aeb8cc;margin-top:4px">{d}</div></div>'
        + ('<div style="align-self:center;font-size:1.6rem;color:#64D2FF">→</div>' if i < len(etapes) - 1 else "")
        for i, (t, d) in enumerate(etapes))
    return f'<div style="display:flex;flex-wrap:wrap;gap:10px;margin:8px 0 18px">{cases}</div>'


def render_showcase(modele_retard, modele_controle, lire_df, tenant_id: int) -> None:
    stats = statistiques_code()
    st.markdown(
        f'<div class="tb-bandeau"><div class="tb-salut">🎓 {TITRE}</div>'
        f'<div class="tb-sous">{SOUS_TITRE}</div>'
        f'<div class="tb-sous" style="margin-top:10px">✍️ <b>{AUTEUR}</b> · {PROGRAMME}</div></div>',
        unsafe_allow_html=True)
    vue_ensemble, architecture, ia, rigueur, visite, suite = sous_menu(
        "vit", ["🎯 Overview", "🏗️ Architecture", "🧠 AI & ML", "✅ Rigor & ethics", "🧭 5-minute tour", "🚀 Roadmap"])

    if vue_ensemble:
        st.markdown(html_grille([
            html_kpi("🧩", "Python modules", f"{stats['modules']}", "", "ERP + AI package", "bleu"),
            html_kpi("⌨️", "Lines of code", f"{stats['lignes']:,}".replace(",", " "), "", "counted live", "violet"),
            html_kpi("🧪", "Validation scripts", f"{stats['validations']}", "", "run with python3 valider_*.py", "vert"),
            html_kpi("🌍", "Market", "UEMOA", "", "Côte d'Ivoire first", "orange"),
        ]), unsafe_allow_html=True)
        _titre("Problem")
        st.write("Customs brokers and accounting firms in Côte d'Ivoire juggle spreadsheets, paper files and several portals. "
                 "Delays at the port create demurrage costs, customs inspections surprise importers, and accounting must "
                 "follow the SYSCOHADA standard. Few affordable tools combine all three.")
        _titre("Solution")
        st.markdown("- **Accounting** under SYSCOHADA with strict double entry, tamper-evident audit log and financial statements.\n"
                    "- **Transit & customs**: files, duty calculator, manifests, demurrage, goods tracking to Abidjan, letter-of-credit release, landed cost.\n"
                    "- **Control tower**: one screen listing which shipments need action today (rule-based alerts).\n"
                    "- **AI**: vessel-delay forecast, customs-inspection risk pre-assessment, accounting anomaly detection, cash-flow forecasting, explainability.\n"
                    "- **Trust**: role-based access, 2FA, backups, personal-data export/erasure.")
        _titre("What makes this project different")
        st.info("Every model is compared with a naive baseline, evaluated on held-out data, and its limits are written in the interface. "
                "**The training data for the logistics models is simulated and clearly labelled as such** — "
                "the method is proven, the real-world accuracy is not claimed.")

    if architecture:
        _titre("System architecture")
        st.markdown(_flux([("Streamlit UI", "tiles, sub-menus, light mode, 3D theme"),
                           ("ERP core", "RBAC, multi-tenant, audit chain"),
                           ("SQLite", "WAL, tenant isolation, migrations"),
                           ("AI package finai/", "ML, deep-learning paths, XAI")]), unsafe_allow_html=True)
        st.markdown("| Layer | Modules | Notes |\n|---|---|---|\n"
                    "| Interface | `sndgir_erp.py`, `sndgir_menu.py` | phone-style square sub-menus, dashboard, light mode for slow connections |\n"
                    "| Business | `sndgir_suivi.py`, `sndgir_tour.py`, `sndgir_export.py` | tracking, control tower, Excel/PDF export |\n"
                    "| AI | `finai/ml`, `finai/dl`, `finai/logistique` | models + honest evaluation |\n"
                    "| Trust | `sndgir_securite.py`, `sndgir_donnees.py` | TOTP 2FA (RFC 6238), backups, GDPR-style rights |\n"
                    "| Quality | `valider_*.py` | executable checks (RFC test vectors, isolation, audit chain) |")
        st.caption("Design choices: modules receive ERP functions as parameters (no circular imports); migrations are idempotent; "
                   "multi-tenant isolation is tested explicitly.")

    if ia:
        _titre("Machine learning — live results")
        st.caption("Computed now from the deployed code (held-out test sets, fixed random seeds).")
        mv, mc = modele_retard().metriques, modele_controle().metriques
        ref_r, ridge, gb = (mv["Référence (retard moyen)"]["mae_jours"], mv["Régression Ridge"]["mae_jours"],
                            mv["Gradient boosting"]["mae_jours"])
        best = min(ridge, gb)
        log, gbc, ref_c = mc["Régression logistique"], mc["Gradient boosting"], mc["Référence (toujours « vert »)"]
        st.markdown(html_grille([
            html_kpi("🚢", "Vessel delay — error", f"{best:.2f}", "days", f"vs {ref_r:.2f} for the naive baseline", "vert"),
            html_kpi("📉", "Error reduction", f"{100 * (1 - best / ref_r):.0f}", "%", "against predicting the average", "bleu"),
            html_kpi("🛃", "Inspection risk — F1", f"{log['f1_macro']:.2f}", "", f"vs {ref_c['f1_macro']:.2f} for “always green”", "violet"),
            html_kpi("🔴", "Red-lane recall", f"{log['rappel_rouge'] * 100:.0f}", "%", f"boosting only {gbc['rappel_rouge'] * 100:.0f} %", "orange"),
        ]), unsafe_allow_html=True)
        st.markdown("**Take-aways an examiner may like**")
        st.markdown(f"- Accuracy alone is misleading: the naive “always green” baseline already scores {ref_c['exactitude'] * 100:.0f} %; "
                    "that is why macro-F1 and recall on the rare red lane are reported.\n"
                    f"- Gradient boosting has higher accuracy ({gbc['exactitude']:.2f} vs {log['exactitude']:.2f}) but finds fewer red-lane files: "
                    "for a *risk* tool the simpler model is the better choice.\n"
                    "- On the simulated delay data, Ridge ≈ boosting because the simulation rules are almost linear — stated openly.")
        _titre("Full AI toolbox (module `finai/`)")
        st.markdown("| Task | Methods | Status in this demo |\n|---|---|---|\n"
                    "| Fraud / anomaly detection | Isolation Forest, One-Class SVM, Benford's law, supervised | active |\n"
                    "| Explainability | permutation importance, LIME-style local surrogate, SHAP (if installed) | active |\n"
                    "| Cash-flow forecasting | seasonal-naïve & moving-average baselines, gradient boosting, MLP; rolling-origin validation | active |\n"
                    "| Deep learning | LSTM / GRU (PyTorch), transformer fine-tuning for accounting text | code provided, **optional** (needs `torch`, not run in this lightweight demo) |\n"
                    "| Document vision | OpenCV pre-processing + Tesseract/EasyOCR + accounting checks (HT + VAT = TTC) | active when OCR engine installed |\n"
                    "| Solvency scoring | ratio-based features; several classifiers compared (logistic, forests, calibrated SVM…) | active |")

    if rigueur:
        _titre("Scientific rigor")
        st.markdown("1. **Baselines first** — no model is shown without a naive reference.\n"
                    "2. **Held-out test sets** never used for tuning; prediction intervals computed on a separate validation split.\n"
                    "3. **Leakage awareness** — a near-zero error on a target-derived ratio was flagged as leakage, not celebrated.\n"
                    "4. **Rules are not AI** — control-tower alerts are explicit rules (free-storage period, delay, letter of credit) and are labelled so.\n"
                    "5. **Simulated data is labelled** in the interface, the README and the report.")
        _titre("Responsible AI")
        st.markdown("- Customs selection criteria are confidential: the tool **helps prepare a file**, it never claims to predict an official decision.\n"
                    "- The tariff table in the demo is sample data: real rates must be checked against the official customs tariff.\n"
                    "- Personal data: export of everything held on a client, and irreversible anonymisation that keeps accounting records.\n"
                    "- Security: salted password hashing, login throttling, hash-chained audit log, TOTP 2FA, database backup.")
        _titre("Known limitations")
        st.warning("Simulated training data · SQLite on a temporary cloud disk (demo only) · no live GUCE connection "
                   "(requires an official request) · French user interface (English project documentation).")

    if visite:
        _titre("A 5-minute guided tour")
        st.markdown("1. **Dashboard** tile → big KPIs and items to watch.\n"
                    "2. **Transit & Customs → 🗼 Control tower** → pick a shipment: step reached, days at port, alerts, ready-to-send client message.\n"
                    "3. **Transit & Customs → 📍 Goods tracking & credit** → map of the sea route to Abidjan; letter-of-credit release.\n"
                    "4. **Transit & Customs → 🤖 Logistics AI** → change the port or congestion and watch the delay forecast move.\n"
                    "5. **AI & OCR → 📘 Methodology & results** → the scientific write-up with live numbers.\n"
                    "6. **Financial analysis AI** → anomaly detection, scenarios (“what if?”), solvency.\n"
                    "7. **Administration → 🛡️ Security** → 2FA, backups; **👤 Personal data** → client export/erasure.")
        st.caption("The interface of the business modules is in French (the target users are Ivorian); this page and the project documents are in English.")

    if suite:
        _titre("Roadmap")
        st.markdown("1. One-week pilot with a real customs broker (protocol in `docs/GUIDE_ESSAI.md`).\n"
                    "2. Retrain the two logistics models on real anonymised data (`donnees_reelles/`) and report honestly whether they beat the baseline.\n"
                    "3. Official request for GUCE / PCS integration (`docs/LETTRE_GUCE.md`).\n"
                    "4. Durable hosting (PostgreSQL) for real customers; full English interface option.")
        st.caption(f"✍️ {AUTEUR} — {PROGRAMME}")
