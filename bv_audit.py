"""Piste d'audit chaînée (qui / quoi / quand) + vérification d'intégrité.

Chaque ligne contient le hash de la précédente : modifier ou supprimer une
ligne casse la chaîne. Des triggers SQLite interdisent aussi UPDATE/DELETE.
"""
import hashlib

from bv_core import iso, utcnow


def _hash(prev, ts, user, action, detail) -> str:
    raw = f"{prev}|{ts}|{user}|{action}|{detail}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def log_action(con, user: str, action: str, detail: str = ""):
    if not con.in_transaction:
        con.execute("BEGIN IMMEDIATE")
    row = con.execute(
        "SELECT hash FROM saas_audit_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    prev = row["hash"] if row else "GENESIS"
    ts = iso(utcnow())
    con.execute(
        "INSERT INTO saas_audit_log(ts,user,action,detail,prev_hash,hash) "
        "VALUES (?,?,?,?,?,?)",
        (ts, user, action, detail, prev,
         _hash(prev, ts, user, action, detail)))
    con.commit()


def verify_chain(con):
    """Retourne (True, nb_lignes) ou (False, id_première_ligne_altérée)."""
    prev, n = "GENESIS", 0
    for r in con.execute("SELECT * FROM saas_audit_log ORDER BY id"):
        expected = _hash(r["prev_hash"], r["ts"], r["user"],
                         r["action"], r["detail"])
        if r["prev_hash"] != prev or r["hash"] != expected:
            return False, r["id"]
        prev, n = r["hash"], n + 1
    return True, n


def render_audit(con):
    import pandas as pd
    import streamlit as st
    st.subheader("🔗 Piste d'audit")
    ok, info = verify_chain(con)
    if ok:
        st.success(f"Chaîne intègre — {info} événement(s) vérifié(s).")
    else:
        st.error(f"⚠️ Intégrité rompue à partir de l'événement n° {info}.")
    rows = con.execute(
        "SELECT id, ts, user, action, detail FROM saas_audit_log "
        "ORDER BY id DESC LIMIT 300").fetchall()
    df = pd.DataFrame([tuple(r) for r in rows],
                      columns=["N°", "Date (UTC)", "Utilisateur",
                               "Action", "Détail"])
    st.dataframe(df, use_container_width=True, hide_index=True)
