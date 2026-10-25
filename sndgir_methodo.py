"""Page « Méthodologie & résultats » : explique honnêtement ce que fait l'IA, avec les chiffres réels du jour."""
from __future__ import annotations

import pandas as pd
import streamlit as st
import sndgir_i18n


def _tableau(metriques: dict, noms: dict) -> pd.DataFrame:
    return pd.DataFrame([{"Modèle": k, **{noms[c]: round(v, 3) for c, v in m.items()}}
                         for k, m in metriques.items() if not k.startswith("_")])


def _phrases_bilan_en(ridge, gb, ref, mc) -> list[str]:
    meilleur = min(ridge, gb)
    p = [f"Ship delay: mean error of {meilleur:.2f} day(s) versus {ref:.2f} for the simple method "
         f"(always guessing the average delay), i.e. {100 * (1 - meilleur / ref):.0f}% less error."]
    if abs(ridge - gb) / max(ridge, gb) < 0.05:
        p.append("Simple regression and gradient boosting perform almost the same: we keep the simplest explanation.")
    ref_f1 = mc["Référence (toujours « vert »)"]["f1_macro"]
    log, gbc = mc["Régression logistique"], mc["Gradient boosting"]
    p.append(f"Customs risk: macro-F1 {log['f1_macro']:.2f} (regression) versus {ref_f1:.2f} for \"always green\". "
             f"Red files found: {log['rappel_rouge'] * 100:.0f}% (regression) and {gbc['rappel_rouge'] * 100:.0f}% (boosting).")
    if gbc["exactitude"] > log["exactitude"] and gbc["rappel_rouge"] < log["rappel_rouge"]:
        p.append("Boosting has better accuracy but misses more red files: for a risk check we prefer regression here, which finds more of them.")
    return p


def phrases_bilan(mv: dict, mc: dict) -> list[str]:
    """Conclusions écrites À PARTIR des chiffres (jamais figées) : elles changent si les modèles changent."""
    ref = mv["Référence (retard moyen)"]["mae_jours"]
    ridge, gb = mv["Régression Ridge"]["mae_jours"], mv["Gradient boosting"]["mae_jours"]
    meilleur = min(ridge, gb)
    if sndgir_i18n.langue() == "en":
        return _phrases_bilan_en(ridge, gb, ref, mc)
    p = [f"Retard du navire : erreur moyenne de {meilleur:.2f} jour(s) contre {ref:.2f} pour la méthode simple "
         f"(retard moyen toujours deviné), soit {100 * (1 - meilleur / ref):.0f} % d'erreur en moins."]
    if abs(ridge - gb) / max(ridge, gb) < 0.05:
        p.append("La régression simple et le gradient boosting font presque pareil : on garde l'explication la plus simple.")
    ref_f1 = mc["Référence (toujours « vert »)"]["f1_macro"]
    log, gbc = mc["Régression logistique"], mc["Gradient boosting"]
    p.append(f"Risque de contrôle : F1 moyen {log['f1_macro']:.2f} (régression) contre {ref_f1:.2f} pour « toujours vert ». "
             f"Rouges retrouvés : {log['rappel_rouge'] * 100:.0f} % (régression) et {gbc['rappel_rouge'] * 100:.0f} % (boosting).")
    if gbc["exactitude"] > log["exactitude"] and gbc["rappel_rouge"] < log["rappel_rouge"]:
        p.append("Le boosting a une meilleure exactitude mais rate plus de dossiers rouges : pour un contrôle de risque, "
                 "on préfère ici la régression, qui en retrouve plus.")
    return p


def render_methodologie(modele_retard, modele_controle) -> None:
    st.caption("Page pensée pour le jury : ce qui est fait, avec quelles données, quels résultats, et surtout quelles limites.")
    st.markdown("#### 1. Le problème")
    st.write("Un importateur ivoirien veut savoir (a) quand sa marchandise arrivera vraiment à Abidjan et (b) si son dossier "
             "ressemble à un dossier que la douane contrôle davantage. Les retards coûtent des surestaries ; un contrôle "
             "inattendu coûte du temps.")
    st.markdown("#### 2. Les données — et leur limite principale")
    st.warning("Les deux modèles apprennent sur des données **SIMULÉES** par des règles écrites par l'auteur. "
               "Ils retrouvent donc ces règles : cela prouve que la méthode fonctionne, **pas** qu'elle prédit la réalité. "
               "Avec de vraies données, il suffit de les remplacer (voir `docs/DONNEES_REELLES.md`).")
    st.markdown("#### 3. La méthode")
    st.markdown("- **Retard** : régression (Ridge, boosting) sur distance, transbordements, saison, encombrement, compagnie.\n"
                "- **Risque de contrôle** : classification en 3 voies (vert, orange, rouge) par régression logistique et boosting.\n"
                "- **Évaluation** : 20–25 % des données sont mises de côté, jamais utilisées pour apprendre.\n"
                "- **Toujours une référence simple** : un modèle n'a de valeur que s'il bat une méthode naïve.")
    mv, mc = modele_retard.metriques, modele_controle.metriques
    st.markdown("#### 4. Résultats (recalculés à l'instant)")
    st.markdown("**Retard du navire**")
    st.dataframe(_tableau(mv, {"mae_jours": "Erreur moyenne (jours)", "rmse_jours": "Erreur quadratique (jours)"}),
                 hide_index=True, use_container_width=True)
    cl = mv["_classification"]
    st.caption(f"Repérer un retard de plus de 3 jours : AUC {cl['auc_retard_plus_3j']:.2f} sur {cl['n_test']} voyages test.")
    st.markdown("**Risque de contrôle douanier**")
    st.dataframe(_tableau(mc, {"exactitude": "Exactitude", "f1_macro": "F1 moyen", "rappel_rouge": "Rouges retrouvés"}),
                 hide_index=True, use_container_width=True)
    st.markdown("#### 5. Ce que disent les chiffres")
    for ligne in phrases_bilan(mv, mc):
        st.markdown(f"- {ligne}")
    st.markdown("#### 6. Limites et honnêteté")
    st.markdown("- Données simulées : aucune valeur prédictive réelle tant qu'elles ne sont pas remplacées.\n"
                "- Les critères réels de la douane sont confidentiels : l'outil **prépare** un dossier, il ne prédit pas une décision.\n"
                "- L'exactitude seule trompe (la référence « toujours vert » a déjà 62 %) : d'où le F1 moyen et les rouges retrouvés.\n"
                "- Les alertes de la Tour de contrôle sont des **règles** (franchise, retard, crédit documentaire), pas de l'IA.\n"
                "- Aucun test à grande échelle sur de vrais utilisateurs à ce jour.")
    st.markdown("#### 7. Suite prévue")
    st.markdown("1. Essai d'une semaine avec un transitaire (`docs/GUIDE_ESSAI.md`).  \n"
                "2. Réentraînement sur ses données anonymisées (`donnees_reelles/`).  \n"
                "3. Demande officielle d'accès au GUCE (`docs/LETTRE_GUCE.md`).")
