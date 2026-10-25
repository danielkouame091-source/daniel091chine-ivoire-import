"""Onglet « IA logistique » : retard probable d'un navire et pré-évaluation du risque de contrôle douanier.

Les deux modèles apprennent sur des données SIMULÉES (voir finai/logistique/*.py). Ils servent à montrer la
méthode et à préparer ses dossiers ; ils ne remplacent ni le suivi réel du navire, ni les décisions de la douane.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from sndgir_menu import sous_menu

try:
    from finai.logistique import douane, voyages
    LOG_OK, LOG_ERREUR = True, ""
except Exception as exc:
    LOG_OK, LOG_ERREUR = False, str(exc)


@st.cache_resource(show_spinner="Apprentissage du modèle de retard…")
def _modele_retard():
    return voyages.entrainer()


@st.cache_resource(show_spinner="Apprentissage du modèle de risque douanier…")
def _modele_controle():
    return douane.entrainer()


def _tableau(metriques: dict, noms: dict) -> pd.DataFrame:
    lignes = [{"Modèle": k, **{noms[c]: round(v, 3) for c, v in m.items()}}
              for k, m in metriques.items() if not k.startswith("_")]
    return pd.DataFrame(lignes)


def render_ia_logistique(lire_df, tenant_id: int) -> None:
    if not LOG_OK:
        st.error("Le module d'IA logistique n'a pas pu démarrer (scikit-learn manquant ?).")
        st.code(LOG_ERREUR)
        return
    st.caption("Les modèles ont appris sur des données SIMULÉES : ils montrent la méthode, pas la réalité. "
               "Avec de vrais voyages et de vrais dossiers, on remplace les données et le reste ne change pas.")
    t_retard, t_ctrl = sous_menu("ial", ["⏳ Retard du navire", "🛃 Risque de contrôle"])

    if t_retard:
        exps = lire_df("SELECT id, dossier_ref, origine FROM expeditions WHERE tenant_id=? ORDER BY id DESC", (tenant_id,))
        origines = list(voyages.ORIGINES)
        defaut_o, ref_exp = 0, None
        if not exps.empty:
            choix = st.selectbox("Expédition (facultatif)", [0] + exps["id"].tolist(), key="ial_exp",
                                 format_func=lambda i: "— saisie libre —" if i == 0 else
                                 f"{exps.loc[exps['id'] == i, 'dossier_ref'].iloc[0]} ({exps.loc[exps['id'] == i, 'origine'].iloc[0]})")
            if choix:
                ref_exp = exps[exps["id"] == choix].iloc[0]
                if ref_exp["origine"] in origines:
                    defaut_o = origines.index(ref_exp["origine"])
        c = st.columns(5)
        origine = c[0].selectbox("Port de départ", origines, index=defaut_o, key="ial_o")
        ligne = c[1].selectbox("Compagnie", voyages.LIGNES, key="ial_l")
        mois = c[2].selectbox("Mois de départ", list(range(1, 13)), index=date.today().month - 1, key="ial_m")
        transb = c[3].selectbox("Transbordements", [0, 1, 2, 3], index=1, key="ial_t")
        cong = c[4].slider("Encombrement du port", 0.0, 1.0, 0.45, 0.05, key="ial_c",
                           help="0 = fluide, 1 = saturé (à estimer d'après les nouvelles du port)")
        m = _modele_retard()
        r = m.predire(origine, ligne, mois, transb, cong)
        k = st.columns(4)
        k[0].metric("Durée annoncée", f"{r['delai_prevu_jours']:.0f} jours")
        k[1].metric("Retard estimé", f"{r['retard_jours']:+.1f} jours",
                    f"entre {r['intervalle'][0]:+.1f} et {r['intervalle'][1]:+.1f}", delta_color="off")
        k[2].metric("Durée estimée", f"{r['delai_estime_jours']:.0f} jours")
        k[3].metric("Risque de plus de 3 jours de retard", f"{min(max(r['proba_retard_3j'], 0.01), 0.99) * 100:.0f} %")
        if ref_exp is not None:
            dep = lire_df("SELECT date_jalon FROM jalons_expedition WHERE tenant_id=? AND expedition_id=? AND code='DEPART'",
                          (tenant_id, int(ref_exp["id"])))
            if not dep.empty:
                d0 = pd.to_datetime(dep["date_jalon"].iloc[0]).date()
                st.info(f"Arrivée estimée à Abidjan : environ le {d0 + timedelta(days=round(r['delai_estime_jours'])):%d/%m/%Y} "
                        f"(départ le {d0:%d/%m/%Y}).")
        st.markdown("**Ce modèle est-il meilleur qu'une méthode simple ?** (jeu de test mis de côté)")
        st.dataframe(_tableau(m.metriques, {"mae_jours": "Erreur moyenne (jours)", "rmse_jours": "Erreur quadratique (jours)"}),
                     hide_index=True, use_container_width=True)
        cl = m.metriques["_classification"]
        st.caption(f"Capacité à repérer les retards de plus de 3 jours : AUC {cl['auc_retard_plus_3j']:.2f} "
                   f"sur {cl['n_test']} voyages. Sur ces données simulées, la régression simple fait aussi bien que le "
                   f"boosting, parce que les règles de simulation sont presque linéaires.")

    if t_ctrl:
        dos = lire_df("SELECT reference, client, code_sh, valeur_caf_xof, regime, quantite, article FROM dossiers "
                      "WHERE tenant_id=? ORDER BY id DESC", (tenant_id,))
        sel = None
        if not dos.empty:
            ref = st.selectbox("Dossier (facultatif)", [""] + dos["reference"].tolist(), key="ial_dos")
            if ref:
                sel = dos[dos["reference"] == ref].iloc[0]
        c = st.columns(4)
        chap = c[0].text_input("Chapitre SH (2 chiffres)", value=str(sel["code_sh"] or "")[:2] if sel is not None else "85", key="ial_ch")
        valeur = c[1].number_input("Valeur CAF (FCFA)", 0.0, value=float(sel["valeur_caf_xof"] or 0) if sel is not None else 5_000_000.0,
                                   step=500_000.0, key="ial_v")
        origine_d = c[2].selectbox("Pays d'origine", douane.ORIGINES, key="ial_po")
        regime = c[3].selectbox("Régime", douane.REGIMES, index=douane.REGIMES.index(sel["regime"]) if sel is not None and sel["regime"] in douane.REGIMES else 0, key="ial_rg")
        nb_hist, ecart_auto = 0, None
        if sel is not None and not dos.empty:
            nb_hist = int((dos["client"] == sel["client"]).sum()) - 1
            memes = dos[(dos["article"] == sel["article"]) & (dos["reference"] != sel["reference"]) & (dos["quantite"] > 0)]
            if sel["quantite"] and sel["quantite"] > 0 and len(memes) >= 3:
                ref_prix = (memes["valeur_caf_xof"] / memes["quantite"]).median()
                if ref_prix > 0:
                    ecart_auto = float((sel["valeur_caf_xof"] / sel["quantite"]) / ref_prix - 1)
        x = st.columns(3)
        nb = x[0].number_input("Dossiers déjà traités pour cet importateur", 0, value=max(nb_hist, 0), key="ial_nb")
        ecart = x[1].slider("Prix déclaré par rapport au prix habituel", -0.9, 1.0, float(max(-0.9, min(1.0, ecart_auto))) if ecart_auto is not None else 0.0,
                            0.05, key="ial_ec", help="−0,3 = 30 % moins cher que d'habitude")
        anom = x[2].slider("Part d'anciens dossiers avec anomalie", 0.0, 1.0, 0.0, 0.01, key="ial_an")
        if ecart_auto is not None:
            st.caption("Le prix habituel est calculé à partir de vos anciens dossiers du même article.")
        mc = _modele_controle()
        try:
            r = mc.predire({"chapitre": chap or "00", "valeur_caf": valeur, "ecart_prix": ecart, "nb_dossiers_importateur": nb,
                            "taux_anomalies": anom, "origine": origine_d, "regime": regime})
        except ValueError as exc:
            st.error(str(exc))
            return
        p = r["probabilites"]
        k = st.columns(3)
        for col, canal, ic in zip(k, douane.CANAUX, ["🟢", "🟠", "🔴"]):
            col.metric(f"{ic} Voie {canal}", f"{p[canal] * 100:.0f} %")
        st.write(f"Profil le plus proche : **voie {r['canal_probable']}**.")
        if r["raisons"]:
            st.markdown("**Ce qui pèse le plus :** " + " ; ".join(r["raisons"]) + ".")
            st.info("Pour limiter le risque : documents complets, facture cohérente avec les prix du marché, "
                    "description précise de la marchandise.")
        st.markdown("**Résultats du modèle** (jeu de test mis de côté)")
        st.dataframe(_tableau(mc.metriques, {"exactitude": "Exactitude", "f1_macro": "F1 moyen", "rappel_rouge": "Rouges retrouvés"}),
                     hide_index=True, use_container_width=True)
        st.caption("Attention : les vrais critères de la douane sont confidentiels. Cette pré-évaluation sert à préparer "
                   "son dossier, jamais à prédire une décision officielle. L'exactitude seule trompe : la référence "
                   "« toujours vert » a 62 %, d'où l'intérêt du F1 moyen et des rouges retrouvés.")
