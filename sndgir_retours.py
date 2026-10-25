"""Retours d'essai : formulaire d'avis (barre latérale) et synthèse pour l'administrateur.

Objectif : qu'un transitaire ou un comptable qui teste le logiciel une semaine puisse noter, sur le moment,
ce qui le gêne, et que vous puissiez en tirer une liste claire de corrections.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

SCHEMA_RETOURS = """
CREATE TABLE IF NOT EXISTS retours_essai (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    role TEXT,
    section TEXT NOT NULL,
    type_retour TEXT NOT NULL,
    note INTEGER NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""
SECTIONS = ["Tableau de bord", "Comptabilité", "Transit & Douanes", "IA & OCR", "Analyse financière IA",
            "Portail client", "Administration", "Autre"]
TYPES = ["Quelque chose ne marche pas", "C'est difficile à comprendre", "Il manque une fonction", "J'aime beaucoup"]
MESSAGE_MAX = 1000


def enregistrer_retour(connexion, tenant_id: int, username: str, role: str, section: str, type_retour: str,
                       note: int, message: str) -> None:
    message = (message or "").strip()
    if section not in SECTIONS or type_retour not in TYPES:
        raise ValueError("Section ou type de retour inconnu.")
    if not 1 <= int(note) <= 5:
        raise ValueError("La note doit être comprise entre 1 et 5.")
    if len(message) < 5:
        raise ValueError("Décrivez en quelques mots (5 caractères au minimum).")
    if len(message) > MESSAGE_MAX:
        raise ValueError(f"Message trop long ({MESSAGE_MAX} caractères au maximum).")
    with connexion() as conn:
        conn.execute("INSERT INTO retours_essai (tenant_id, username, role, section, type_retour, note, message, created_at)"
                     " VALUES (?,?,?,?,?,?,?,?)",
                     (tenant_id, username, role, section, type_retour, int(note), message,
                      datetime.now().strftime("%Y-%m-%d %H:%M:%S")))


def synthese(df: pd.DataFrame) -> dict:
    """Chiffres clés : nombre d'avis, note moyenne, répartition par type et par section, points à traiter."""
    if df.empty:
        return {"nombre": 0, "note_moyenne": None, "par_type": {}, "par_section": {}, "a_traiter": 0}
    a_traiter = df[df["type_retour"].isin(TYPES[:3])]
    return {"nombre": int(len(df)), "note_moyenne": float(df["note"].mean()),
            "par_type": df["type_retour"].value_counts().to_dict(),
            "par_section": a_traiter["section"].value_counts().to_dict(), "a_traiter": int(len(a_traiter))}


def render_formulaire(connexion, journaliser, tenant_id: int, username: str, role: str) -> None:
    st.caption("Votre avis nous aide à corriger. Une phrase suffit.")
    with st.form("form_retour", clear_on_submit=True):
        section = st.selectbox("Où ?", SECTIONS, key="retour_section")
        type_retour = st.selectbox("Que se passe-t-il ?", TYPES, key="retour_type")
        note = st.slider("Votre satisfaction (1 = mauvais, 5 = excellent)", 1, 5, 3, key="retour_note")
        message = st.text_area("Expliquez en quelques mots", max_chars=MESSAGE_MAX, key="retour_msg")
        if st.form_submit_button("Envoyer mon avis", use_container_width=True):
            try:
                enregistrer_retour(connexion, tenant_id, username, role, section, type_retour, note, message)
                journaliser("retour_essai", "retours_essai", section, type_retour)
                st.success("Merci, votre avis est enregistré.")
            except ValueError as exc:
                st.error(str(exc))


def render_synthese(lire_df, tenant_id: int, bouton_export=None) -> None:
    df = lire_df("SELECT created_at, username, role, section, type_retour, note, message FROM retours_essai "
                 "WHERE tenant_id=? ORDER BY id DESC", (tenant_id,))
    s = synthese(df)
    if not s["nombre"]:
        st.info("Aucun avis pour le moment. Demandez aux testeurs d'ouvrir « ⚙️ Mon avis » dans la barre de gauche.")
        return
    k = st.columns(3)
    k[0].metric("Avis reçus", s["nombre"])
    k[1].metric("Note moyenne", f"{s['note_moyenne']:.1f} / 5")
    k[2].metric("Points à traiter", s["a_traiter"])
    if s["par_section"]:
        st.markdown("**Sections qui posent le plus de problèmes**")
        st.bar_chart(pd.Series(s["par_section"], name="avis"))
    st.dataframe(df, hide_index=True, use_container_width=True)
    if bouton_export:
        bouton_export(df, "retours_essai", "Retours d'essai")
