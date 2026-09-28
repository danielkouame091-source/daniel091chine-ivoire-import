"""
direction.py — BaobabVault ERP
Tableau de Bord Exécutif + Contrôle à 4 Yeux (double validation obligatoire
pour toute opération financière sensible). Pas de black-box : le workflow
est explicite et auditable, condition sine qua non pour une banque partenaire.

Règle des 4 yeux appliquée ici, au sens bancaire strict :
  - Le DEMANDEUR ne peut jamais être son propre validateur.
  - Il faut DEUX validateurs DISTINCTS entre eux.
  - L'opération n'est exécutée qu'après la 2e validation — jamais avant.
"""

import sqlite3
from datetime import datetime

import pandas as pd
import streamlit as st

import theme
import securite_bancaire as sec

SEUIL_4_YEUX_DEFAUT = 1_000_000  # FCFA — au-delà, double validation obligatoire


def init_direction_tables(db_name: str):
    conn = sqlite3.connect(db_name)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS validations_sensibles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type_operation TEXT,
            reference TEXT,
            montant REAL,
            details TEXT,
            demandeur TEXT,
            statut TEXT DEFAULT 'En attente',        -- En attente / Validé niveau 1 / Exécuté / Rejeté
            validateur_1 TEXT,
            validateur_1_le TEXT,
            validateur_2 TEXT,
            validateur_2_le TEXT,
            executee INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def demander_validation(db_name: str, type_operation: str, reference: str, montant: float,
                         demandeur: str, details: str = "") -> int:
    """Toute opération financière sensible (paiement fournisseur, déblocage
    de crédit documentaire, dégel de compte, virement > seuil...) doit
    passer par ici plutôt que d'être exécutée directement."""
    init_direction_tables(db_name)
    conn = sqlite3.connect(db_name)
    cur = conn.execute(
        """INSERT INTO validations_sensibles
           (type_operation, reference, montant, details, demandeur, created_at)
           VALUES (?,?,?,?,?,?)""",
        (type_operation, reference, montant, details, demandeur,
         datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit()
    id_demande = cur.lastrowid
    conn.close()
    sec.log_action_immuable(db_name, demandeur, "Demande validation 4 yeux",
                             f"#{id_demande} — {type_operation} {reference} — {montant:,.0f} FCFA")
    return id_demande


def valider_operation(db_name: str, id_demande: int, validateur: str) -> dict:
    """Applique une validation. Refuse toute tentative de contourner la
    règle des 4 yeux (demandeur = validateur, ou même validateur deux fois)."""
    conn = sqlite3.connect(db_name)
    row = conn.execute(
        "SELECT demandeur, statut, validateur_1 FROM validations_sensibles WHERE id=?",
        (id_demande,),
    ).fetchone()
    if not row:
        conn.close()
        return {"ok": False, "message": "Demande introuvable."}

    demandeur, statut, validateur_1 = row

    if validateur == demandeur:
        conn.close()
        return {"ok": False, "message": "🚫 Le demandeur ne peut pas valider sa propre opération."}

    if statut == "Exécuté":
        conn.close()
        return {"ok": False, "message": "Cette opération a déjà été exécutée."}
    if statut == "Rejeté":
        conn.close()
        return {"ok": False, "message": "Cette demande a été rejetée."}

    horodatage = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if statut == "En attente":
        conn.execute(
            "UPDATE validations_sensibles SET validateur_1=?, validateur_1_le=?, statut='Validé niveau 1' WHERE id=?",
            (validateur, horodatage, id_demande),
        )
        conn.commit()
        conn.close()
        sec.log_action_immuable(db_name, validateur, "Validation 4 yeux (1/2)", f"#{id_demande}")
        return {"ok": True, "message": "✅ Première validation enregistrée. Une seconde personne distincte doit valider.", "executee": False}

    if statut == "Validé niveau 1":
        if validateur == validateur_1:
            conn.close()
            return {"ok": False, "message": "🚫 Le second validateur doit être une personne différente du premier."}
        conn.execute(
            "UPDATE validations_sensibles SET validateur_2=?, validateur_2_le=?, statut='Exécuté', executee=1 WHERE id=?",
            (validateur, horodatage, id_demande),
        )
        conn.commit()
        conn.close()
        sec.log_action_immuable(db_name, validateur, "Validation 4 yeux (2/2) — EXÉCUTÉ", f"#{id_demande}")
        return {"ok": True, "message": "✅ Double validation complète — opération exécutée.", "executee": True}

    conn.close()
    return {"ok": False, "message": "État de la demande incohérent."}


def rejeter_operation(db_name: str, id_demande: int, validateur: str, motif: str):
    conn = sqlite3.connect(db_name)
    conn.execute("UPDATE validations_sensibles SET statut='Rejeté' WHERE id=?", (id_demande,))
    conn.commit()
    conn.close()
    sec.log_action_immuable(db_name, validateur, "Rejet validation 4 yeux", f"#{id_demande} — motif: {motif}")


# ======================================================================
# TABLEAU DE BORD EXÉCUTIF
# ======================================================================
def _kpis_executifs(db_name: str) -> dict:
    conn = sqlite3.connect(db_name)
    try:
        tresorerie_totale = conn.execute(
            "SELECT COALESCE(SUM(montant),0) FROM transactions"
        ).fetchone()[0] or 0
    except sqlite3.OperationalError:
        tresorerie_totale = 0
    try:
        comptes_geles = conn.execute("SELECT COUNT(*) FROM comptes_geles").fetchone()[0]
    except sqlite3.OperationalError:
        comptes_geles = 0
    conn.close()
    return {"tresorerie_totale": tresorerie_totale, "comptes_geles": comptes_geles}


def render_bureau_directeur(db_name: str, utilisateur_courant: str, role_courant: str):
    init_direction_tables(db_name)
    theme.inject_apple_theme()

    st.subheader("🏛️ Bureau du Directeur")
    st.caption("Vue exécutive temps réel — accès restreint à la direction.")

    if role_courant not in ("Administrateur", "Directeur"):
        st.error("🔒 Accès réservé aux profils Direction / Administrateur.")
        st.stop()

    kpis = _kpis_executifs(db_name)
    conn = sqlite3.connect(db_name)
    en_attente = conn.execute(
        "SELECT COUNT(*) FROM validations_sensibles WHERE statut != 'Exécuté' AND statut != 'Rejeté'"
    ).fetchone()[0]
    conn.close()

    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(theme.carte_kpi_html("Trésorerie suivie", f"{kpis['tresorerie_totale']:,.0f} FCFA", "Cumul transactions", "success"), unsafe_allow_html=True)
    c2.markdown(theme.carte_kpi_html("Comptes gelés (AML)", str(kpis['comptes_geles']), "Sécurité active" if kpis['comptes_geles'] else "Aucune alerte", "danger" if kpis['comptes_geles'] else "success"), unsafe_allow_html=True)
    c3.markdown(theme.carte_kpi_html("Validations en attente", str(en_attente), "Contrôle 4 yeux", "warning" if en_attente else "neutral"), unsafe_allow_html=True)
    c4.markdown(theme.carte_kpi_html("Seuil double validation", f"{SEUIL_4_YEUX_DEFAUT:,.0f} FCFA", "Configurable", "neutral"), unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 🔏 File d'attente — Contrôle à 4 Yeux")
    st.caption("Une opération sensible nécessite deux validations de personnes distinctes, différentes du demandeur.")

    conn = sqlite3.connect(db_name)
    df = pd.read_sql_query(
        "SELECT * FROM validations_sensibles WHERE statut != 'Exécuté' AND statut != 'Rejeté' ORDER BY id DESC",
        conn,
    )
    conn.close()

    if df.empty:
        st.info("Aucune opération en attente de validation.")
    else:
        for _, ligne in df.iterrows():
            with st.container():
                st.markdown(f"""<div class="bv-card">
                    <b>#{ligne['id']} — {ligne['type_operation']}</b> ({ligne['reference']})<br>
                    <span style="color:#8B95A7;">Montant : {ligne['montant']:,.0f} FCFA — Demandé par {ligne['demandeur']}</span><br>
                    <span style="color:#8B95A7;">{ligne['details']}</span><br>
                    {theme.badge(ligne['statut'], 'warning' if ligne['statut']=='En attente' else 'success')}
                    {(' — 1ère validation par ' + ligne['validateur_1']) if ligne['validateur_1'] else ''}
                    </div>""", unsafe_allow_html=True)
                cbtn1, cbtn2 = st.columns(2)
                with cbtn1:
                    if st.button(f"✅ Valider #{ligne['id']}", key=f"valider_{ligne['id']}", use_container_width=True):
                        res = valider_operation(db_name, int(ligne['id']), utilisateur_courant)
                        (st.success if res["ok"] else st.error)(res["message"])
                        if res["ok"]:
                            st.rerun()
                with cbtn2:
                    motif = st.text_input("Motif de rejet", key=f"motif_{ligne['id']}", label_visibility="collapsed", placeholder="Motif de rejet (optionnel)")
                    if st.button(f"❌ Rejeter #{ligne['id']}", key=f"rejeter_{ligne['id']}", use_container_width=True):
                        rejeter_operation(db_name, int(ligne['id']), utilisateur_courant, motif or "non précisé")
                        st.warning("Demande rejetée.")
                        st.rerun()

    st.markdown("---")
    st.markdown("### 📜 Historique des opérations validées")
    conn = sqlite3.connect(db_name)
    df_hist = pd.read_sql_query(
        "SELECT id, type_operation, reference, montant, demandeur, validateur_1, validateur_2, statut FROM validations_sensibles WHERE statut IN ('Exécuté','Rejeté') ORDER BY id DESC LIMIT 100",
        conn,
    )
    conn.close()
    st.dataframe(df_hist, use_container_width=True)
