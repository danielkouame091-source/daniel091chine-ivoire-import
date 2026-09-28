"""Licences SaaS : clé, expiration (1 an), limite de postes SIMULTANÉS.

Vérification 100 % côté serveur. Les clés ne sont stockées que sous forme de
hash SHA-256 : la clé n'est affichée qu'une fois, à la création.

Pourquoi « postes simultanés » et pas « Hardware ID » : Streamlit s'exécute
sur le serveur, il ne peut pas lire l'identifiant matériel du PC du client.
Chaque session navigateur reçoit un jeton ; on limite le nombre de jetons
actifs (activité < INACTIVITY_MIN minutes) par licence.
"""
import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

import bv_audit
from bv_core import INACTIVITY_MIN, iso, parse_ts, utcnow

ALERT_DAYS = 15
MAX_SEATS_ALLOWED = 2


@dataclass
class Access:
    ok: bool
    message: str = ""
    client: str = ""
    days_left: int = 0
    licence_id: int = 0


def hash_key(key: str) -> str:
    return hashlib.sha256(key.strip().upper().encode("utf-8")).hexdigest()


def new_key() -> str:
    return "BV-" + "-".join(secrets.token_hex(3).upper() for _ in range(4))


def create_licence(con, client: str, max_seats: int = 2, days: int = 365,
                   user: str = "admin") -> str:
    max_seats = max(1, min(int(max_seats), MAX_SEATS_ALLOWED))
    key, now = new_key(), utcnow()
    con.execute(
        "INSERT INTO saas_licences(client,key_hash,max_seats,issued_at,"
        "expires_at,status) VALUES (?,?,?,?,?, 'active')",
        (client.strip(), hash_key(key), max_seats, iso(now),
         iso(now + timedelta(days=int(days)))))
    con.commit()
    bv_audit.log_action(con, user, "LICENCE_CREEE",
                        f"client={client.strip()} postes={max_seats} "
                        f"durée={days}j")
    return key


def check_access(con, key: str, token: str) -> Access:
    row = con.execute("SELECT * FROM saas_licences WHERE key_hash=?",
                      (hash_key(key),)).fetchone()
    if not row:
        return Access(False, "Clé de licence invalide.")
    if row["status"] != "active":
        return Access(False, "Licence suspendue. Contactez le support.")
    now, exp = utcnow(), parse_ts(row["expires_at"])
    if exp <= now:
        return Access(False, f"Licence expirée le {exp:%d/%m/%Y}. "
                             "Renouvelez votre abonnement.")
    try:
        con.execute("BEGIN IMMEDIATE")  # évite deux connexions simultanées
        con.execute("DELETE FROM saas_sessions WHERE licence_id=? "
                    "AND last_seen<?",
                    (row["id"], iso(now - timedelta(minutes=INACTIVITY_MIN))))
        mine = con.execute("SELECT 1 FROM saas_sessions WHERE licence_id=? "
                           "AND token=?", (row["id"], token)).fetchone()
        if mine:
            con.execute("UPDATE saas_sessions SET last_seen=? "
                        "WHERE licence_id=? AND token=?",
                        (iso(now), row["id"], token))
        else:
            used = con.execute("SELECT COUNT(*) FROM saas_sessions "
                               "WHERE licence_id=?", (row["id"],)).fetchone()[0]
            if used >= row["max_seats"]:
                con.rollback()
                return Access(False, f"Limite de {row['max_seats']} poste(s) "
                                     "simultané(s) atteinte. Fermez une autre "
                                     f"session ou patientez {INACTIVITY_MIN} min.")
            con.execute("INSERT INTO saas_sessions VALUES (?,?,?,?)",
                        (row["id"], token, iso(now), iso(now)))
        con.commit()
    except Exception:
        con.rollback()
        raise
    return Access(True, "", row["client"], (exp - now).days, row["id"])


def _set_status(con, licence_id, status, user, action):
    con.execute("UPDATE saas_licences SET status=? WHERE id=?",
                (status, licence_id))
    if status != "active":
        con.execute("DELETE FROM saas_sessions WHERE licence_id=?",
                    (licence_id,))
    con.commit()
    bv_audit.log_action(con, user, action, f"licence_id={licence_id}")


def suspend(con, licence_id, user="admin"):
    _set_status(con, licence_id, "suspended", user, "LICENCE_SUSPENDUE")


def reactivate(con, licence_id, user="admin"):
    _set_status(con, licence_id, "active", user, "LICENCE_REACTIVEE")


def renew(con, licence_id, days=365, user="admin"):
    row = con.execute("SELECT expires_at FROM saas_licences WHERE id=?",
                      (licence_id,)).fetchone()
    base = max(parse_ts(row["expires_at"]), utcnow())
    con.execute("UPDATE saas_licences SET expires_at=? WHERE id=?",
                (iso(base + timedelta(days=int(days))), licence_id))
    con.commit()
    bv_audit.log_action(con, user, "LICENCE_RENOUVELEE",
                        f"licence_id={licence_id} +{days}j")


def list_licences(con) -> list:
    now = utcnow()
    cutoff = iso(now - timedelta(minutes=INACTIVITY_MIN))
    out = []
    for r in con.execute("SELECT * FROM saas_licences ORDER BY id DESC"):
        used = con.execute("SELECT COUNT(*) FROM saas_sessions WHERE "
                           "licence_id=? AND last_seen>=?",
                           (r["id"], cutoff)).fetchone()[0]
        left = (parse_ts(r["expires_at"]) - now).days
        state = ("suspendue" if r["status"] != "active"
                 else "expirée" if left < 0
                 else "à renouveler" if left <= ALERT_DAYS else "active")
        out.append({"id": r["id"], "Client": r["client"], "Statut": state,
                    "Expire le": r["expires_at"][:10],
                    "Jours restants": left,
                    "Postes": f"{used}/{r['max_seats']}"})
    return out


# ------------------------------ Interface Streamlit ---------------------------
def licence_gate(con) -> Access:
    """Espace CLIENT : à appeler avant d'afficher l'app. Bloque si invalide."""
    import streamlit as st
    token = st.session_state.setdefault("bv_token", secrets.token_hex(16))
    key = st.session_state.get("bv_licence_key")
    if key:
        acc = check_access(con, key, token)
        if acc.ok:
            if acc.days_left <= ALERT_DAYS:
                st.warning(f"⏳ Votre licence expire dans {acc.days_left} "
                           "jour(s). Pensez à la renouveler.")
            return acc
        st.session_state.pop("bv_licence_key", None)
        st.error(acc.message)

    st.markdown("### 🔐 Activation de la licence")
    entered = st.text_input("Clé de licence", placeholder="BV-XXXXXX-...")
    if st.button("Activer", type="primary"):
        acc = check_access(con, entered, token) if entered.strip() \
            else Access(False, "Saisissez votre clé.")
        if acc.ok:
            st.session_state["bv_licence_key"] = entered
            st.rerun()
        st.error(acc.message)
    st.stop()


def render_admin(con, user="admin"):
    """Espace ADMIN : création, renouvellement, suspension des licences."""
    import pandas as pd
    import streamlit as st
    st.subheader("🔑 Gestion des licences")

    with st.form("bv_new_licence"):
        client = st.text_input("Client / entreprise")
        c1, c2 = st.columns(2)
        seats = c1.number_input("Postes simultanés", 1, MAX_SEATS_ALLOWED,
                                MAX_SEATS_ALLOWED)
        days = c2.number_input("Durée (jours)", 30, 730, 365)
        if st.form_submit_button("Générer la licence") and client.strip():
            st.session_state["bv_new_key"] = create_licence(
                con, client, seats, days, user)

    if new := st.session_state.pop("bv_new_key", None):
        st.success("Licence créée. Copiez la clé maintenant : elle ne sera "
                   "plus jamais affichée.")
        st.code(new)

    rows = list_licences(con)
    if not rows:
        st.info("Aucune licence pour le moment.")
        return
    st.dataframe(pd.DataFrame(rows), use_container_width=True,
                 hide_index=True)
    ids = {f"#{r['id']} — {r['Client']}": r["id"] for r in rows}
    pick = ids[st.selectbox("Licence", list(ids))]
    a, b, c = st.columns(3)
    if a.button("Renouveler +1 an"):
        renew(con, pick, 365, user)
        st.rerun()
    if b.button("Suspendre"):
        suspend(con, pick, user)
        st.rerun()
    if c.button("Réactiver"):
        reactivate(con, pick, user)
        st.rerun()
