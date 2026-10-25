"""Module « Analyse financière & IA » de l'ERP SNDGIR.

Relie le grand livre de l'ERP (table `ecritures`) au paquet `finai` : SIG, ratios, comparaison de normes,
scénarios « Et si ? », détection d'anomalies (Benford + Isolation Forest), prévision de trésorerie,
NLP comptable et score de solvabilité (machine learning).

Aucune dépendance vers sndgir_erp.py : les fonctions de l'ERP sont passées en paramètres.
Les montants sont en FCFA. La reconstitution du bilan à partir du grand livre est une APPROXIMATION
(voir `statement_depuis_ecritures`) à vérifier par l'expert-comptable.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from sndgir_menu import sous_menu

try:
    from finai.accounting.scenarios import Choc, comparer_scenarios, sensibilite_tornado
    from finai.accounting.standards import ZONES, indicateurs_par_norme
    from finai.accounting.statement import Statement
    from finai.data.synthetic import generer_flux_tresorerie, generer_libelles, generer_phrases_audit
    from finai.dl import nlp
    from finai.dl.forecast import PrevisionneurDirect
    from finai.features.engineering import caracteristiques_transactions
    from finai.ml.anomaly import DetecteurFraude, test_benford
    from finai.service import pipeline
    FINAI_OK, FINAI_ERREUR = True, ""
except Exception as exc:  # paquet scikit-learn/scipy absent, etc.
    FINAI_OK, FINAI_ERREUR = False, str(exc)


def _net(df: pd.DataFrame, prefixes: tuple, sens: str) -> float:
    """Solde net des comptes commençant par un des préfixes. sens='cr' → crédit − débit ; 'dr' → débit − crédit."""
    m = df["compte"].astype(str).str.startswith(prefixes)
    d, c = float(df.loc[m, "debit"].sum()), float(df.loc[m, "credit"].sum())
    return (c - d) if sens == "cr" else (d - c)


def statement_depuis_ecritures(ec: pd.DataFrame) -> "Statement":
    """Reconstitue un Statement (schéma par nature SYSCOHADA) depuis des écritures (compte, debit, credit).

    Approximations assumées : les stocks finals sont ceux du solde des comptes 3 ; les variations de
    stocks (603/73) sont lues dans les comptes tels quels ; l'écart d'équilibre éventuel est mis dans
    « autres dettes » pour que le bilan tienne ; les provisions (29, 39, 49) sont traitées dans les soldes nets.
    """
    s = Statement()
    s.ventes_marchandises = _net(ec, ("701",), "cr")
    s.production_vendue = _net(ec, ("702", "703", "704", "705", "706"), "cr")
    s.production_stockee = _net(ec, ("73",), "cr")
    s.production_immobilisee = _net(ec, ("72",), "cr")
    s.subventions_exploitation = _net(ec, ("71",), "cr")
    s.autres_produits = _net(ec, ("75",), "cr")
    s.reprises_transferts = _net(ec, ("78",), "cr")
    s.produits_financiers = _net(ec, ("77",), "cr")
    s.produits_hao = _net(ec, ("82", "84", "86", "88"), "cr")
    s.achats_marchandises = _net(ec, ("601",), "dr")
    s.var_stock_marchandises = -_net(ec, ("6031",), "dr")
    s.achats_matieres = _net(ec, ("602",), "dr")
    s.var_stock_matieres = -_net(ec, ("6032", "6033"), "dr")
    s.autres_achats = _net(ec, ("604", "605", "608"), "dr")
    s.transports = _net(ec, ("61",), "dr")
    s.services_exterieurs = _net(ec, ("62", "63"), "dr")
    s.impots_taxes = _net(ec, ("64",), "dr")
    s.autres_charges = _net(ec, ("65",), "dr")
    s.charges_personnel = _net(ec, ("66",), "dr")
    s.charges_financieres = _net(ec, ("67",), "dr")
    s.dotations_amort_prov = _net(ec, ("68", "69"), "dr")
    s.charges_hao = _net(ec, ("81", "83", "85", "87"), "dr")
    s.impot_resultat = _net(ec, ("89",), "dr")

    s.immobilisations_nettes = max(_net(ec, ("2",), "dr"), 0.0)
    s.stocks = max(_net(ec, ("3",), "dr"), 0.0)
    s.creances_clients = max(_net(ec, ("41",), "dr"), 0.0)
    s.autres_creances = max(_net(ec, ("42", "43", "44", "45", "46", "47", "48"), "dr"), 0.0)
    treso = _net(ec, ("50", "51", "52", "53", "54", "55", "57", "58"), "dr")
    s.tresorerie_actif = max(treso, 0.0)
    s.tresorerie_passif = max(-treso, 0.0) + max(_net(ec, ("56",), "cr"), 0.0)
    s.dettes_financieres_lt = max(_net(ec, ("16", "17"), "cr"), 0.0)
    s.dettes_financieres_ct = 0.0
    s.dettes_fournisseurs = max(_net(ec, ("40",), "cr"), 0.0)
    s.dettes_fiscales_sociales = max(_net(ec, ("42", "43", "44"), "cr"), 0.0)
    s.capital_social = max(_net(ec, ("10",), "cr"), 0.0)

    produits = (s.ventes_marchandises + s.production_vendue + s.production_stockee + s.production_immobilisee
                + s.subventions_exploitation + s.autres_produits + s.reprises_transferts
                + s.produits_financiers + s.produits_hao)
    charges = (s.achats_marchandises + s.var_stock_marchandises + s.achats_matieres + s.var_stock_matieres
               + s.autres_achats + s.transports + s.services_exterieurs + s.impots_taxes + s.autres_charges
               + s.charges_personnel + s.charges_financieres + s.dotations_amort_prov + s.charges_hao
               + s.impot_resultat)
    resultat = produits - charges
    s.capitaux_propres = _net(ec, ("10", "11", "12", "13", "14", "15"), "cr") + resultat
    # écart d'équilibre (comptes non classés) placé en autres dettes pour que le bilan tienne
    ecart = s.total_actif - s.total_passif
    s.autres_dettes_ct = max(ecart, 0.0)
    if ecart < 0:
        s.autres_creances += -ecart
    return s


def _fmt(x) -> str:
    try:
        return f"{float(x):,.0f}".replace(",", " ")
    except Exception:
        return "n/d"


def _grand_livre(lire_df, tenant_id: int, annee: str | None) -> pd.DataFrame:
    sql = "SELECT piece, date_ecriture, journal, compte, libelle, debit, credit, created_by, created_at FROM ecritures WHERE tenant_id=?"
    params: tuple = (tenant_id,)
    if annee and annee != "Toutes":
        sql += " AND substr(date_ecriture,1,4)=?"
        params += (annee,)
    return lire_df(sql, params)


def _montants_transactions(ec: pd.DataFrame) -> pd.DataFrame:
    """Prépare les écritures pour le détecteur de fraude (colonnes attendues par finai)."""
    d = ec.copy()
    d["montant"] = (d["debit"].fillna(0) + d["credit"].fillna(0)).astype(float)
    d = d[d["montant"] > 0].reset_index(drop=True)
    dt = pd.to_datetime(d["date_ecriture"], errors="coerce")
    heure = pd.to_datetime(d["created_at"], errors="coerce").dt.hour.fillna(12)
    out = pd.DataFrame({
        "fournisseur": d["libelle"].fillna("sans libellé").astype(str).str.slice(0, 20),
        "compte": d["compte"].astype(str),
        "montant": d["montant"],
        "heure": heure.astype(int),
        "jour_semaine": dt.dt.dayofweek.fillna(0).astype(int),
        "utilisateur": d["created_by"].fillna("?"),
        "seuil_approbation": 500_000.0,
        "piece": d["piece"], "date": d["date_ecriture"],
    })
    return out


@st.cache_resource(show_spinner="Entraînement du modèle de solvabilité (1 à 2 minutes la première fois)…")
def _modele_solvabilite():
    ms = pipeline.charger_solvabilite()
    return ms if ms is not None else pipeline.entrainer_solvabilite(3000, 42, cv_plis=3)[0]


@st.cache_resource(show_spinner="Apprentissage du classifieur de libellés…")
def _classifieur_libelles():
    df = generer_libelles(3000, 3)
    return nlp.ClassifieurTexte().fit(df["libelle"], df["compte"].astype(str))


def onglet_finai(lire_df, tenant_id: int, exiger) -> None:
    st.subheader("🧠 Analyse financière & IA")
    if not exiger("compta.view"):
        return
    if not FINAI_OK:
        st.error("Le module d'analyse n'a pas pu démarrer : il manque des paquets "
                 "(numpy, scipy, scikit-learn, matplotlib, joblib).")
        st.code(FINAI_ERREUR)
        return

    ec_tout = _grand_livre(lire_df, tenant_id, None)
    annees = sorted({str(d)[:4] for d in ec_tout["date_ecriture"].dropna()}, reverse=True) if not ec_tout.empty else []
    c1, c2 = st.columns([1, 2])
    annee = c1.selectbox("Exercice", ["Toutes"] + annees, key="finai_annee")
    zone = c2.selectbox("Référentiel comptable", list(ZONES), index=list(ZONES).index("OHADA"),
                        format_func=lambda k: f"{ZONES[k].zone} — {ZONES[k].referentiel}", key="finai_zone")
    ec = _grand_livre(lire_df, tenant_id, annee)
    st.caption("Les chiffres viennent de votre grand livre. Le bilan est reconstitué par approximation : "
               "à faire valider par l'expert-comptable. Les modèles d'IA apprennent sur des données SIMULÉES.")

    onglets = sous_menu("finai", ["📊 Diagnostic", "🌍 Normes", "🔮 Et si ?", "🕵️ Anomalies", "💵 Trésorerie", "📝 Textes", "🎯 Solvabilité"])

    if ec.empty:
        if any(onglets[:4]):
            st.info("Aucune écriture comptable pour cette période. Saisissez des écritures dans « Comptabilité ».")
        s = None
    else:
        s = statement_depuis_ecritures(ec)

    # ── 1. Diagnostic ──
    if onglets[0]:
        if s is not None:
            res = pipeline.diagnostic_entreprise(s, zone)
            d = res["diagnostic"]
            k = st.columns(4)
            k[0].metric("Chiffre d'affaires", _fmt(d["sig"]["chiffre_affaires"]))
            k[1].metric("EBE", _fmt(d["sig"]["excedent_brut_exploitation"]))
            k[2].metric("Résultat net", _fmt(d["sig"]["resultat_net"]))
            k[3].metric("Trésorerie nette", _fmt(d["equilibre"]["tresorerie_nette"]))
            if not d.get("bilan_equilibre", True):
                st.warning("Le bilan reconstitué n'est pas parfaitement équilibré : vérifiez les comptes utilisés.")
            st.markdown("**Soldes intermédiaires de gestion**")
            sig = pd.DataFrame({"SIG": list(d["sig"]), "Montant": [float(v) for v in d["sig"].values()]})
            st.bar_chart(sig.set_index("SIG"))
            a, b = st.columns(2)
            with a:
                st.markdown("**Ratios**")
                st.dataframe(pd.DataFrame({"Ratio": list(d["ratios"]), "Valeur": [round(float(v), 3) for v in d["ratios"].values()]}),
                             hide_index=True, use_container_width=True)
            with b:
                st.markdown("**Lecture pour la direction**")
                for ligne in res["lecture"]:
                    st.markdown(f"• {ligne}")
                st.caption(f"Altman Z'' : {d['altman']['z']:.2f} → zone {d['altman']['zone']}")

    # ── 2. Normes ──
    if onglets[1]:
        if s is not None:
            comp = indicateurs_par_norme(s)
            tab = pd.DataFrame(comp).T.round(3)
            st.dataframe(tab, use_container_width=True)
            st.caption("Retraitements IFRS 16 / US GAAP approximatifs : indicatifs, pas des comptes audités.")

    # ── 3. Et si ? ──
    if onglets[2]:
        if s is not None:
            x = st.columns(3)
            ventes = x[0].slider("Ventes (%)", -50, 50, -10, key="finai_v")
            achats = x[1].slider("Prix d'achat (%)", -20, 50, 5, key="finai_a")
            dso = x[2].slider("Délai clients (jours en plus)", -30, 60, 15, key="finai_d")
            lignes = comparer_scenarios(s, {"Votre scénario": Choc(ventes_pct=ventes / 100, prix_achats_pct=achats / 100, dso_delta=dso)})
            st.dataframe(pd.DataFrame(lignes).round(2), hide_index=True, use_container_width=True)
            st.markdown("**Quel poste pèse le plus sur le résultat ?** (variation de ±10 %)")
            torn = pd.DataFrame(sensibilite_tornado(s))
            st.dataframe(torn.round(2), hide_index=True, use_container_width=True)

    # ── 4. Anomalies ──
    if onglets[3]:
        if s is not None:
            tx = _montants_transactions(ec)
            if len(tx) < 30:
                st.info("Il faut au moins 30 écritures pour une analyse fiable. Il y en a "
                        f"{len(tx)} pour l'instant.")
            else:
                b = test_benford(tx["montant"])
                st.markdown(f"**Test de Benford** (premiers chiffres des montants) : écart moyen {b['mad']:.4f} → "
                            f"{'conforme' if b['conforme'] else '⚠️ à examiner'}")
                X = caracteristiques_transactions(tx)
                det = DetecteurFraude().fit(X)
                tx["score_anomalie"] = det.score(X)
                tx["motifs"] = [", ".join(DetecteurFraude.motifs(r)) for _, r in X.iterrows()]
                top = tx.sort_values("score_anomalie", ascending=False).head(15)
                st.markdown("**Écritures les plus atypiques** (à vérifier, ce n'est pas une preuve de fraude)")
                st.dataframe(top[["piece", "date", "compte", "montant", "utilisateur", "score_anomalie", "motifs"]].round(3),
                             hide_index=True, use_container_width=True)

    # ── 5. Trésorerie ──
    if onglets[4]:
        treso = ec[ec["compte"].astype(str).str.match(r"^5[0-8]")].copy() if not ec.empty else pd.DataFrame()
        serie = None
        if not treso.empty:
            treso["d"] = pd.to_datetime(treso["date_ecriture"], errors="coerce")
            flux = (treso["debit"].fillna(0) - treso["credit"].fillna(0)).groupby(treso["d"].dt.to_period("W-SUN").dt.start_time).sum()
            flux = flux.asfreq("W-MON", fill_value=0.0) if len(flux) > 1 else flux
            if len(flux) >= 80:
                serie = flux
        if serie is None:
            st.info("Pas assez d'historique de trésorerie (il faut environ 80 semaines) : la prévision ci-dessous "
                    "utilise une série SIMULÉE pour montrer le principe.")
            df = generer_flux_tresorerie(200, 11)
            serie = pd.Series(df.iloc[:, -1].to_numpy(float), index=pd.date_range("2022-01-03", periods=len(df), freq="W-MON"))
        if st.button("Calculer la prévision à 13 semaines", key="finai_prev"):
            prev = PrevisionneurDirect(horizon=13, modele="gb").fit(serie).predict()
            st.line_chart(pd.concat([serie.tail(52).rename("historique"), prev["prevision"].rename("prévision")], axis=1))
            st.dataframe(prev.round(0), use_container_width=True)
            st.caption("L'intervalle est une estimation prudente mais probablement trop étroite.")

    # ── 6. Textes ──
    if onglets[5]:
        st.markdown("**Classer un libellé d'écriture dans un compte SYSCOHADA**")
        lib = st.text_input("Libellé", "Facture vente client Abidjan marchandises", key="finai_lib")
        if st.button("Classer", key="finai_cl"):
            clf = _classifieur_libelles()
            proba = clf.predict_proba([lib]).iloc[0].sort_values(ascending=False).head(3)
            st.dataframe(proba.rename("probabilité").round(3).to_frame(), use_container_width=True)
            st.caption("Entraîné sur des libellés simulés : fiable seulement si vos libellés ressemblent à ces modèles.")
        st.markdown("**Ton d'un texte d'audit**")
        txt = st.text_area("Texte", "Il existe une incertitude significative sur la continuité d'exploitation.", key="finai_txt")
        if st.button("Analyser le ton", key="finai_ton"):
            r = nlp.score_ton_audit(txt)
            st.write(f"Niveau de risque du texte : **{r['niveau']}** (score {r['score']:.1f})")
            if r["termes"]:
                st.write("Termes repérés : " + ", ".join(r["termes"]))

    # ── 7. Solvabilité ──
    if onglets[6]:
        if s is None:
            st.info("Aucune écriture pour cette période.")
        else:
            st.write("Estimation de la probabilité de défaut à 12 mois, par un modèle appris sur des entreprises simulées.")
            secteur = st.selectbox("Secteur", ["Commerce", "Industrie", "Services"], key="finai_sect")
            if st.button("Calculer le score", key="finai_score"):
                ms = _modele_solvabilite()
                r = pipeline.scorer_solvabilite(ms, s, zone, secteur)
                st.metric("Probabilité de défaut", f"{r['probabilite_defaut']*100:.1f} %", f"risque {r['niveau_risque']}")
                st.write(r["lecture"])
                st.dataframe(pd.DataFrame(r["facteurs"]), hide_index=True, use_container_width=True)
                st.caption("Indicatif seulement : le modèle n'a jamais vu de vraies entreprises ivoiriennes.")
