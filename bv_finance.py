"""États SYSCOHADA simplifiés, trésorerie prédictive, détection d'anomalies.

Lecture seule. Le grand livre est détecté automatiquement (table avec colonnes
date / compte / débit / crédit). Sinon, choisissez-le à la main dans l'interface.
États SIMPLIFIÉS : à faire valider par un expert-comptable avant dépôt.
"""
import io

import numpy as np
import pandas as pd

from bv_core import fmt_money

TREASURY_PREFIXES = ("52", "53", "56", "57")
CANDIDATES = {
    "date": ["date", "date_ecriture", "date_piece", "date_operation", "jour"],
    "account": ["compte", "numero_compte", "num_compte", "compte_general",
                "account"],
    "label": ["libelle", "libellé", "designation", "description", "label"],
    "debit": ["debit", "débit"],
    "credit": ["credit", "crédit"],
}
LABELS = {
    "10": "Capital", "11": "Réserves", "12": "Report à nouveau",
    "13": "Résultat", "16": "Emprunts", "21": "Immob. incorporelles",
    "22": "Terrains", "23": "Bâtiments", "24": "Matériel", "31": "Marchandises",
    "40": "Fournisseurs", "41": "Clients", "42": "Personnel",
    "43": "Organismes sociaux", "44": "État et collectivités",
    "46": "Associés", "47": "Débiteurs/créditeurs divers", "52": "Banques",
    "53": "Établissements financiers", "56": "Banques crédits de trésorerie",
    "57": "Caisse", "60": "Achats", "61": "Transports",
    "62": "Services extérieurs A", "63": "Services extérieurs B",
    "64": "Impôts et taxes", "65": "Autres charges", "66": "Personnel",
    "67": "Frais financiers", "68": "Dotations amortissements",
    "69": "Dotations provisions", "70": "Ventes",
    "71": "Subventions d'exploitation", "72": "Production immobilisée",
    "73": "Variation de stocks", "75": "Autres produits",
    "77": "Revenus financiers", "78": "Transferts de charges",
    "79": "Reprises de provisions",
}


# ------------------------------ Détection / chargement ------------------------
def detect_ledger(con):
    best, best_score = None, 0
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'saas_%'")]
    for t in tables:
        cols = {c[1].lower(): c[1] for c in con.execute(
            f'PRAGMA table_info("{t}")')}
        spec = {"table": t}
        for field, names in CANDIDATES.items():
            spec[field] = next((cols[n] for n in names if n in cols), None)
        if all(spec[f] for f in ("date", "account", "debit", "credit")):
            score = 1 + sum(k in t.lower() for k in
                            ("ecriture", "écriture", "journal", "ledger",
                             "grand_livre"))
            if score > best_score:
                best, best_score = spec, score
    return best


def load_ledger(con, spec: dict) -> pd.DataFrame:
    fields = [k for k in ("date", "account", "label", "debit", "credit")
              if spec.get(k)]
    q = "SELECT " + ", ".join(f'"{spec[k]}"' for k in fields) + \
        f' FROM "{spec["table"]}"'
    df = pd.DataFrame([tuple(r) for r in con.execute(q).fetchall()],
                      columns=fields)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["account"] = (df["account"].astype(str).str.strip()
                     .str.replace(r"\.0$", "", regex=True))
    for c in ("debit", "credit"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    if "label" not in df:
        df["label"] = ""
    return df.dropna(subset=["date"]).reset_index(drop=True)


# ------------------------------ États financiers -----------------------------
def _by_prefix(df, classes, sign):
    sub = df[df["account"].str[:1].isin(classes)].copy()
    sub["p"] = sub["account"].str[:2]
    net = (sub["debit"] - sub["credit"]).groupby(sub["p"]).sum() * sign
    return pd.DataFrame({"Compte": net.index,
                         "Libellé": [LABELS.get(p, f"Comptes {p}")
                                     for p in net.index],
                         "Montant": net.values})


def compte_resultat(df):
    charges = _by_prefix(df, ["6"], 1)
    produits = _by_prefix(df, ["7"], -1)
    hao = float(-(df[df["account"].str[:1] == "8"]["debit"].sum()
                  - df[df["account"].str[:1] == "8"]["credit"].sum()))
    resultat = produits["Montant"].sum() - charges["Montant"].sum() + hao
    return charges, produits, hao, float(resultat)


def bilan(df):
    _, _, _, resultat = compte_resultat(df)
    sub = df[df["account"].str[:1].isin(list("12345"))].copy()
    sub["p"] = sub["account"].str[:2]
    solde = (sub["debit"] - sub["credit"]).groupby(sub["p"]).sum()
    actif, passif = [], []
    for p, s in solde.items():
        lab = LABELS.get(p, f"Comptes {p}")
        if p[0] == "1":
            passif.append((p, lab, -s))
        elif s >= 0:
            actif.append((p, lab, s))
        else:
            passif.append((p, lab, -s))
    passif.append(("13", "Résultat de l'exercice", resultat))
    mk = lambda rows: pd.DataFrame(rows, columns=["Compte", "Libellé",
                                                  "Montant"])
    return mk(actif), mk(passif)


def flux_tresorerie(df) -> pd.DataFrame:
    t = df[df["account"].str.startswith(TREASURY_PREFIXES)]
    if t.empty:
        return pd.DataFrame(columns=["Mois", "Encaissements",
                                     "Décaissements", "Net", "Solde cumulé"])
    m = t.groupby(t["date"].dt.to_period("M")).agg(
        Encaissements=("debit", "sum"), Décaissements=("credit", "sum"))
    m["Net"] = m["Encaissements"] - m["Décaissements"]
    m["Solde cumulé"] = m["Net"].cumsum()
    m.index.name = "Mois"
    return m.reset_index()


# ------------------------------ Prédictif & anomalies ------------------------
def project_cash(flux: pd.DataFrame, months: int = 3) -> pd.DataFrame:
    """Projection linéaire du flux net mensuel (30 j = 1 mois, 90 j = 3)."""
    if len(flux) < 2:
        return pd.DataFrame(columns=["Mois", "Net", "Solde cumulé"])
    y = flux["Net"].to_numpy(dtype=float)
    x = np.arange(len(y))
    slope, intercept = np.polyfit(x, y, 1) if len(y) >= 3 else (0.0, y.mean())
    last, cum = flux["Mois"].iloc[-1], float(flux["Solde cumulé"].iloc[-1])
    rows = []
    for i in range(1, months + 1):
        net = float(intercept + slope * (len(y) - 1 + i))
        cum += net
        rows.append((last + i, net, cum))
    return pd.DataFrame(rows, columns=["Mois", "Net", "Solde cumulé"])


def detect_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    amt = df[["debit", "credit"]].max(axis=1)
    live = df[amt > 0]
    dups = live[live.duplicated(["date", "account", "label", "debit",
                                 "credit"], keep=False)]
    for _, r in dups.drop_duplicates(["date", "account", "label", "debit",
                                      "credit"]).iterrows():
        out.append(("Doublon possible", "Élevée", r["date"].date(),
                    r["account"], str(r["label"])[:60],
                    max(r["debit"], r["credit"])))
    work = df.assign(amount=amt, p=df["account"].str[:2])
    for p, g in work.groupby("p"):
        g = g[g["amount"] > 0]
        if len(g) < 8:
            continue
        med = g["amount"].median()
        mad = (g["amount"] - med).abs().median()
        if mad == 0:
            continue
        z = 0.6745 * (g["amount"] - med) / mad
        for _, r in g[z > 3.5].iterrows():
            out.append(("Montant atypique", "Moyenne", r["date"].date(),
                        r["account"], f"{str(r['label'])[:50]} "
                        f"(médiane {fmt_money(med)})", r["amount"]))
    flux = flux_tresorerie(df)
    for _, r in flux[flux["Solde cumulé"] < 0].iterrows():
        out.append(("Trésorerie négative", "Élevée", str(r["Mois"]), "5x",
                    "Solde cumulé négatif", r["Solde cumulé"]))
    return pd.DataFrame(out, columns=["Type", "Gravité", "Date", "Compte",
                                      "Détail", "Montant"])


# ------------------------------ Export PDF -----------------------------------
def to_pdf(title: str, sections: list):
    """sections = [(titre, DataFrame)] -> bytes PDF, ou None si reportlab absent."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer,
                                        Table, TableStyle)
    except ImportError:
        return None
    buf, styles = io.BytesIO(), getSampleStyleSheet()
    story = [Paragraph(title, styles["Title"]), Spacer(1, 12)]
    for head, df in sections:
        story.append(Paragraph(head, styles["Heading2"]))
        rows = [list(df.columns)] + [[str(v) for v in r]
                                     for r in df.itertuples(index=False)]
        t = Table(rows, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B1F3A")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 8)]))
        story += [t, Spacer(1, 14)]
    SimpleDocTemplate(buf, pagesize=A4).build(story)
    return buf.getvalue()


# ------------------------------ Interface Streamlit --------------------------
def _get_ledger(con):
    import streamlit as st
    spec = st.session_state.get("bv_ledger_spec") or detect_ledger(con)
    if spec:
        return load_ledger(con, spec)
    st.warning("Grand livre non détecté automatiquement. Indiquez où sont "
               "vos écritures comptables :")
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'saas_%'")]
    t = st.selectbox("Table des écritures", tables)
    cols = [c[1] for c in con.execute(f'PRAGMA table_info("{t}")')]
    spec = {"table": t,
            "date": st.selectbox("Colonne date", cols),
            "account": st.selectbox("Colonne n° de compte", cols),
            "debit": st.selectbox("Colonne débit", cols),
            "credit": st.selectbox("Colonne crédit", cols),
            "label": st.selectbox("Colonne libellé (optionnel)",
                                  [None] + cols)}
    if st.button("Utiliser cette table"):
        st.session_state["bv_ledger_spec"] = spec
        st.rerun()
    st.stop()


def _money_table(df):
    d = df.copy()
    d["Montant"] = d["Montant"].map(fmt_money)
    return d


def render_etats(con):
    import streamlit as st

    import bv_ui
    st.subheader("📊 États financiers SYSCOHADA (simplifiés)")
    df = _get_ledger(con)
    if df.empty:
        st.info("Aucune écriture trouvée.")
        return
    years = sorted(df["date"].dt.year.unique(), reverse=True)
    year = st.selectbox("Exercice", years)
    df = df[df["date"].dt.year == year]

    charges, produits, hao, resultat = compte_resultat(df)
    a, b, c = st.columns(3)
    with a:
        bv_ui.card("Produits", fmt_money(produits["Montant"].sum()),
                   f"Exercice {year}", "green")
    with b:
        bv_ui.card("Charges", fmt_money(charges["Montant"].sum()),
                   f"Exercice {year}", "amber")
    with c:
        bv_ui.card("Résultat net", fmt_money(resultat),
                   "Bénéfice" if resultat >= 0 else "Perte",
                   "green" if resultat >= 0 else "red")

    actif, passif = bilan(df)
    ecart = actif["Montant"].sum() - passif["Montant"].sum()
    flux = flux_tresorerie(df)
    t1, t2, t3 = st.tabs(["Bilan", "Compte de résultat", "Flux de trésorerie"])
    with t1:
        c1, c2 = st.columns(2)
        c1.markdown("**Actif**")
        c1.dataframe(_money_table(actif), hide_index=True)
        c2.markdown("**Passif**")
        c2.dataframe(_money_table(passif), hide_index=True)
        if abs(ecart) > 1:
            st.error(f"Bilan déséquilibré de {fmt_money(ecart)} : vérifiez "
                     "les écritures (débit ≠ crédit).")
        else:
            bv_ui.badge("Bilan équilibré", "green")
    with t2:
        st.markdown("**Charges**")
        st.dataframe(_money_table(charges), hide_index=True)
        st.markdown("**Produits**")
        st.dataframe(_money_table(produits), hide_index=True)
    with t3:
        show = flux.copy()
        for col in ("Encaissements", "Décaissements", "Net", "Solde cumulé"):
            show[col] = show[col].map(fmt_money)
        show["Mois"] = show["Mois"].astype(str)
        st.dataframe(show, hide_index=True)

    pdf = to_pdf(f"États financiers {year}", [
        ("Actif", _money_table(actif)), ("Passif", _money_table(passif)),
        ("Charges", _money_table(charges)),
        ("Produits", _money_table(produits))])
    if pdf:
        st.download_button("⬇️ Exporter en PDF", pdf,
                           f"etats_{year}.pdf", "application/pdf")
    else:
        st.caption("Export PDF : ajoutez `reportlab` à requirements.txt.")


def render_dashboard(con):
    import altair as alt
    import streamlit as st

    import bv_ui
    st.subheader("📈 Trésorerie prédictive & alertes")
    df = _get_ledger(con)
    flux = flux_tresorerie(df)
    if flux.empty:
        st.info("Aucun compte de trésorerie (52, 53, 56, 57) trouvé.")
        return
    horizon = st.radio("Horizon de projection", [1, 3],
                       format_func=lambda m: f"{m * 30} jours", horizontal=True)
    proj = project_cash(flux, horizon)
    anomalies = detect_anomalies(df)

    a, b, c = st.columns(3)
    with a:
        bv_ui.card("Trésorerie actuelle",
                   fmt_money(flux["Solde cumulé"].iloc[-1]), "", "blue")
    with b:
        end = proj["Solde cumulé"].iloc[-1] if len(proj) else None
        bv_ui.card(f"Projection à {horizon * 30} j",
                   fmt_money(end) if end is not None else "—",
                   "Tendance linéaire",
                   "red" if end is not None and end < 0 else "green")
    with c:
        bv_ui.card("Alertes", len(anomalies),
                   "à examiner" if len(anomalies) else "aucune anomalie",
                   "red" if len(anomalies) else "green")

    hist = flux[["Mois", "Solde cumulé"]].assign(Série="Réel")
    fut = proj[["Mois", "Solde cumulé"]].assign(Série="Projection")
    plot = pd.concat([hist, fut])
    plot["Mois"] = plot["Mois"].dt.to_timestamp()
    chart = alt.Chart(plot).mark_line(point=True, strokeWidth=3).encode(
        x=alt.X("Mois:T", title=None), y=alt.Y("Solde cumulé:Q", title=None),
        color=alt.Color("Série:N", scale=alt.Scale(
            domain=["Réel", "Projection"], range=["#3B82F6", "#F5A524"])),
        strokeDash=alt.StrokeDash("Série:N")).properties(height=320)
    st.altair_chart(chart, use_container_width=True)

    st.markdown("#### 🚨 Alertes")
    if anomalies.empty:
        st.success("Aucune anomalie détectée.")
    else:
        show = anomalies.copy()
        show["Montant"] = show["Montant"].map(fmt_money)
        st.dataframe(show, hide_index=True, use_container_width=True)
