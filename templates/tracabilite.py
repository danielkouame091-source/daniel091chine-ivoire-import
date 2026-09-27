"""
tracabilite.py — BaobabVault ERP
Suivi GPS des expéditions import-export + liaison au déblocage d'un
Crédit Documentaire (LC) : les fonds ne se débloquent que si la
marchandise est confirmée arrivée dans le rayon de la destination.
"""

import math
import sqlite3
from datetime import datetime

import pandas as pd
import streamlit as st


def init_tracabilite_tables(db_name: str):
    conn = sqlite3.connect(db_name)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS expeditions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dossier_id TEXT, origine TEXT, destination TEXT,
            destination_lat REAL, destination_lon REAL,
            derniere_lat REAL, derniere_lon REAL, derniere_maj TEXT,
            statut TEXT DEFAULT 'En transit'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS credits_documentaires (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dossier_id TEXT UNIQUE, expedition_id INTEGER,
            montant REAL, statut TEXT DEFAULT 'Bloqué', date_deblocage TEXT
        )
    """)
    conn.commit(); conn.close()


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def creer_expedition(db_name: str, dossier_id: str, origine: str, destination: str, dest_lat: float, dest_lon: float) -> int:
    init_tracabilite_tables(db_name)
    conn = sqlite3.connect(db_name); cur = conn.cursor()
    cur.execute(
        "INSERT INTO expeditions (dossier_id, origine, destination, destination_lat, destination_lon) VALUES (?,?,?,?,?)",
        (dossier_id, origine, destination, dest_lat, dest_lon),
    )
    conn.commit(); expedition_id = cur.lastrowid; conn.close()
    return expedition_id


def enregistrer_position_gps(db_name: str, expedition_id: int, lat: float, lon: float):
    conn = sqlite3.connect(db_name)
    conn.execute(
        "UPDATE expeditions SET derniere_lat=?, derniere_lon=?, derniere_maj=? WHERE id=?",
        (lat, lon, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), expedition_id),
    )
    conn.commit(); conn.close()


def verifier_arrivee(db_name: str, expedition_id: int, rayon_km: float = 5.0) -> dict:
    conn = sqlite3.connect(db_name)
    row = conn.execute(
        "SELECT destination_lat, destination_lon, derniere_lat, derniere_lon FROM expeditions WHERE id=?",
        (expedition_id,),
    ).fetchone()
    conn.close()
    if not row or row[2] is None:
        return {"arrive": False, "distance_km": None, "message": "Aucune position GPS reçue pour cette expédition."}
    dest_lat, dest_lon, lat, lon = row
    distance = _haversine_km(dest_lat, dest_lon, lat, lon)
    arrive = distance <= rayon_km
    if arrive:
        conn = sqlite3.connect(db_name)
        conn.execute("UPDATE expeditions SET statut='Arrivé' WHERE id=?", (expedition_id,))
        conn.commit(); conn.close()
    return {"arrive": arrive, "distance_km": round(distance, 2), "message": "Destination atteinte." if arrive else f"À {distance:.1f} km de la destination."}


def lier_credit_documentaire(db_name: str, dossier_id: str, expedition_id: int, montant: float):
    init_tracabilite_tables(db_name)
    conn = sqlite3.connect(db_name)
    conn.execute(
        "INSERT OR REPLACE INTO credits_documentaires (dossier_id, expedition_id, montant, statut) VALUES (?,?,?,'Bloqué')",
        (dossier_id, expedition_id, montant),
    )
    conn.commit(); conn.close()


def debloquer_credit_documentaire(db_name: str, dossier_id: str, rayon_km: float = 5.0) -> dict:
    """Ne débloque QUE si la vérification GPS confirme l'arrivée à destination."""
    conn = sqlite3.connect(db_name)
    row = conn.execute("SELECT expedition_id, montant, statut FROM credits_documentaires WHERE dossier_id=?", (dossier_id,)).fetchone()
    conn.close()
    if not row:
        return {"debloque": False, "message": "Aucun crédit documentaire trouvé pour ce dossier."}
    expedition_id, montant, statut = row
    if statut == "Débloqué":
        return {"debloque": True, "message": "Déjà débloqué précédemment."}

    verif = verifier_arrivee(db_name, expedition_id, rayon_km)
    if not verif["arrive"]:
        return {"debloque": False, "message": f"Refusé — {verif['message']}"}

    conn = sqlite3.connect(db_name)
    conn.execute(
        "UPDATE credits_documentaires SET statut='Débloqué', date_deblocage=? WHERE dossier_id=?",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), dossier_id),
    )
    conn.commit(); conn.close()
    return {"debloque": True, "message": f"Crédit documentaire de {montant:,.0f} débloqué — livraison confirmée par GPS."}


def render_module_tracabilite(db_name: str):
    st.subheader("🌍 Traçabilité Logistique & Crédit Documentaire")
    init_tracabilite_tables(db_name)

    sous_tabs = st.tabs(["➕ Nouvelle Expédition", "📍 Mise à jour GPS", "💰 Déblocage LC", "🗺️ Suivi"])

    with sous_tabs[0]:
        with st.form("form_expedition"):
            dossier_id = st.text_input("N° Dossier", value="DOS-2026-001")
            origine = st.text_input("Origine", value="Mumbai, Inde")
            destination = st.text_input("Destination", value="Abidjan, Côte d'Ivoire")
            c1, c2 = st.columns(2)
            with c1: dest_lat = st.number_input("Latitude destination", value=5.3600, format="%.4f")
            with c2: dest_lon = st.number_input("Longitude destination", value=-4.0083, format="%.4f")
            montant_lc = st.number_input("Montant du Crédit Documentaire (FCFA)", value=0.0, step=500000.0)
            if st.form_submit_button("Créer l'expédition + lier le LC"):
                exp_id = creer_expedition(db_name, dossier_id, origine, destination, dest_lat, dest_lon)
                lier_credit_documentaire(db_name, dossier_id, exp_id, montant_lc)
                st.success(f"Expédition #{exp_id} créée et liée au dossier {dossier_id}.")

    with sous_tabs[1]:
        conn = sqlite3.connect(db_name)
        df_exp = pd.read_sql_query("SELECT id, dossier_id, origine, destination, statut FROM expeditions", conn)
        conn.close()
        if df_exp.empty:
            st.info("Aucune expédition enregistrée.")
        else:
            exp_id = st.selectbox("Expédition", df_exp["id"].tolist(), format_func=lambda i: f"#{i} — {df_exp[df_exp['id']==i]['dossier_id'].values[0]}")
            c1, c2 = st.columns(2)
            with c1: lat = st.number_input("Latitude actuelle", value=0.0, format="%.4f")
            with c2: lon = st.number_input("Longitude actuelle", value=0.0, format="%.4f")
            if st.button("📡 Enregistrer la position GPS"):
                enregistrer_position_gps(db_name, exp_id, lat, lon)
                st.success("Position mise à jour.")

    with sous_tabs[2]:
        conn = sqlite3.connect(db_name)
        df_lc = pd.read_sql_query("SELECT * FROM credits_documentaires", conn)
        conn.close()
        if df_lc.empty:
            st.info("Aucun crédit documentaire enregistré.")
        else:
            st.dataframe(df_lc, use_container_width=True)
            dossier_sel = st.selectbox("Dossier à débloquer", df_lc["dossier_id"].tolist())
            if st.button("🔓 Vérifier GPS & Débloquer le Crédit Documentaire"):
                res = debloquer_credit_documentaire(db_name, dossier_sel)
                (st.success if res["debloque"] else st.error)(res["message"])

    with sous_tabs[3]:
        conn = sqlite3.connect(db_name)
        df_exp = pd.read_sql_query("SELECT * FROM expeditions", conn)
        conn.close()
        st.dataframe(df_exp, use_container_width=True)
