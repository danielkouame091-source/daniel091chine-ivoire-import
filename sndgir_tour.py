"""Tour de contrôle des expéditions : une vue unique au-dessus du suivi du port.

Le GUCE de Côte d'Ivoire fournit déjà le système officiel du port (PCS : e-Voyage, e-Manifest, e-Movement…).
Ce module n'essaie pas de le remplacer : il aide l'IMPORTATEUR ou le TRANSITAIRE à suivre TOUTES ses
expéditions au même endroit, avec les jalons (vocabulaire du PCS), l'argent en jeu (franchise, surestaries,
crédit documentaire, solde client) et des alertes, puis à prévenir le client par WhatsApp.

Honnêteté : les alertes viennent de RÈGLES de gestion écrites ci-dessous (pas d'intelligence artificielle).
Il n'y a pas de connexion automatique au PCS/GUCE : les jalons sont saisis à la main. La franchise et la
pénalité par jour dépendent du contrat de transport : les valeurs par défaut sont à adapter.
"""
from __future__ import annotations

from datetime import date, datetime
from urllib.parse import quote

import pandas as pd
import streamlit as st

SCHEMA_TOUR = """
CREATE TABLE IF NOT EXISTS jalons_expedition (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    expedition_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    date_jalon TEXT NOT NULL,
    note TEXT,
    saisi_par TEXT,
    UNIQUE(tenant_id, expedition_id, code)
);
"""

MIGRATIONS_TOUR = {"expeditions": [("date_arrivee_prevue", "TEXT"), ("franchise_jours", "INTEGER DEFAULT 7"),
                                   ("penalite_jour_xof", "REAL DEFAULT 0")]}

# (code, libellé, repère PCS si existant)
JALONS = [
    ("BOOKING", "Réservation confirmée", ""),
    ("CHARGEMENT", "Chargé à bord", ""),
    ("DEPART", "Navire parti", ""),
    ("E_VOYAGE", "Escale annoncée", "e-Voyage"),
    ("ARRIVEE", "Navire arrivé au port", ""),
    ("E_MANIFEST", "Manifeste déposé", "e-Manifest"),
    ("DECHARGEMENT", "Conteneur déchargé au terminal", "e-Movement"),
    ("DECLARATION", "Déclaration en douane déposée", ""),
    ("QUITTANCE", "Droits et taxes payés (quittance)", ""),
    ("BAE", "Bon à enlever obtenu", "e-Release"),
    ("SORTIE", "Sorti du port", ""),
    ("LIVRE", "Livré chez le client", ""),
]
CODES = [j[0] for j in JALONS]
LIBELLE = {c: l for c, l, _ in JALONS}


def _jour(x) -> date | None:
    if x is None or (not isinstance(x, (str, date, datetime)) and pd.isna(x)):
        return None
    try:
        t = pd.to_datetime(x)
        return None if pd.isna(t) else t.date()
    except Exception:
        return None


def analyser(exp: dict, jalons: dict, positions: pd.DataFrame, lc_bloque: float = 0.0,
             solde_client: float = 0.0, aujourdhui: date | None = None) -> dict:
    """Étape actuelle, jours au port, franchise, surestaries estimées, alertes et score de risque (0-100).

    `jalons` : {code: date_iso}. Règles (additives, plafonnées à 100) :
      +40 franchise épuisée ; +25 franchise presque épuisée (≤ 2 jours) ; +20 navire en retard sur la date
      prévue ; +15 aucune nouvelle position depuis plus de 7 jours en mer ; +10 crédit documentaire encore
      bloqué alors que la marchandise est arrivée ; +10 solde client impayé avant la sortie du port.
    """
    auj = aujourdhui or date.today()
    faits = [c for c in CODES if c in jalons]
    actuelle = faits[-1] if faits else None
    prochaine = next((c for c in CODES if c not in jalons), None)
    alertes: list[tuple[str, str]] = []
    score = 0

    franchise = int(exp.get("franchise_jours") or 7)
    pen = float(exp.get("penalite_jour_xof") or 0)
    jours_port = franchise_restante = None
    surestaries = 0.0
    arrivee = _jour(jalons.get("DECHARGEMENT") or jalons.get("ARRIVEE"))
    sorti = _jour(jalons.get("SORTIE"))
    if arrivee and not sorti:
        jours_port = max(0, (auj - arrivee).days)
        franchise_restante = franchise - jours_port
        if franchise_restante < 0:
            surestaries = -franchise_restante * pen
            score += 40
            alertes.append(("rouge", f"Franchise dépassée de {-franchise_restante} jour(s) : "
                                     f"surestaries estimées {surestaries:,.0f} FCFA.".replace(",", " ")))
        elif franchise_restante <= 2:
            score += 25
            alertes.append(("orange", f"Il reste {franchise_restante} jour(s) de franchise : sortez le conteneur vite."))
    elif "ARRIVEE" not in jalons:
        prevue = _jour(exp.get("date_arrivee_prevue"))
        if prevue and auj > prevue:
            score += 20
            alertes.append(("orange", f"Le navire a {(auj - prevue).days} jour(s) de retard sur la date prévue."))
        if "DEPART" in jalons and positions is not None and not positions.empty:
            der = _jour(positions["date_position"].max())
            if der and (auj - der).days > 7:
                score += 15
                alertes.append(("orange", f"Aucune position depuis {(auj - der).days} jours : demandez des nouvelles du navire."))
    if lc_bloque > 0 and ("ARRIVEE" in jalons or "DECHARGEMENT" in jalons):
        score += 10
        alertes.append(("orange", f"Crédit documentaire de {lc_bloque:,.0f} FCFA encore bloqué alors que la marchandise est arrivée."
                        .replace(",", " ")))
    if solde_client > 0 and "SORTIE" not in jalons and ("BAE" in jalons or "DECHARGEMENT" in jalons):
        score += 10
        alertes.append(("orange", f"Le client doit encore {solde_client:,.0f} FCFA : réglez avant la livraison.".replace(",", " ")))
    score = min(100, score)
    niveau = "rouge" if score >= 60 or any(n == "rouge" for n, _ in alertes) else ("orange" if score >= 25 or alertes else "vert")
    return {"actuelle": actuelle, "prochaine": prochaine, "jours_port": jours_port,
            "franchise_restante": franchise_restante, "surestaries": surestaries,
            "alertes": alertes, "score": score, "niveau": niveau, "avancement": len(faits) / len(CODES)}


def message_client(ref: str, client: str, analyse: dict, eta_jours: float | None = None) -> str:
    etape = LIBELLE.get(analyse["actuelle"], "dossier ouvert")
    suite = LIBELLE.get(analyse["prochaine"], "")
    texte = f"Bonjour {client or ''}, point sur votre marchandise (dossier {ref}) : {etape.lower()}."
    if eta_jours is not None and analyse["actuelle"] in (None, "BOOKING", "CHARGEMENT", "DEPART", "E_VOYAGE"):
        texte += f" Arrivée à Abidjan estimée dans environ {eta_jours:.0f} jours."
    if suite:
        texte += f" Prochaine étape : {suite.lower()}."
    return texte.replace("  ", " ")


def lien_whatsapp(telephone: str | None, texte: str) -> str:
    chiffres = "".join(c for c in str(telephone or "") if c.isdigit())
    base = f"https://wa.me/{chiffres}" if chiffres else "https://wa.me/"
    return f"{base}?text={quote(texte)}"


_ICONE = {"rouge": "🔴", "orange": "🟠", "vert": "🟢"}


def render_tour(lire_df, connexion, journaliser, exiger, tenant_id: int, username: str, etat_expedition,
                bouton_export=None) -> None:
    st.caption("Toutes vos expéditions sur un seul écran. Les alertes viennent de règles de gestion simples, "
               "pas d'une IA. Les jalons sont saisis à la main (aucune connexion automatique au PCS/GUCE).")
    exps = lire_df("SELECT e.*, d.client, d.telephone, d.solde_du FROM expeditions e "
                   "LEFT JOIN dossiers d ON d.tenant_id=e.tenant_id AND d.reference=e.dossier_ref "
                   "WHERE e.tenant_id=? ORDER BY e.id DESC", (tenant_id,))
    if exps.empty:
        st.info("Aucune expédition. Créez-en une dans « Suivi marchandise & crédit documentaire ».")
        return
    jal = lire_df("SELECT expedition_id, code, date_jalon FROM jalons_expedition WHERE tenant_id=?", (tenant_id,))
    pos = lire_df("SELECT expedition_id, date_position, lat, lon FROM positions_expedition WHERE tenant_id=?", (tenant_id,))
    lcs = lire_df("SELECT expedition_id, montant, statut FROM credits_documentaires WHERE tenant_id=?", (tenant_id,))

    lignes, analyses = [], {}
    for _, e in exps.iterrows():
        eid = int(e["id"])
        jd = dict(zip(jal[jal["expedition_id"] == eid]["code"], jal[jal["expedition_id"] == eid]["date_jalon"]))
        p = pos[pos["expedition_id"] == eid]
        lc = float(lcs[(lcs["expedition_id"] == eid) & (lcs["statut"] == "Bloqué")]["montant"].sum())
        a = analyser(e.to_dict(), jd, p, lc, float(e.get("solde_du") or 0))
        analyses[eid] = (a, jd, p)
        lignes.append({"": _ICONE[a["niveau"]], "Dossier": e["dossier_ref"], "Client": e.get("client") or "",
                       "Étape": LIBELLE.get(a["actuelle"], "—"), "Avancement": f"{a['avancement']*100:.0f} %",
                       "Franchise (jours)": a["franchise_restante"] if a["franchise_restante"] is not None else "",
                       "Surestaries (FCFA)": round(a["surestaries"]), "Risque": a["score"], "_id": eid})
    tab = pd.DataFrame(lignes).sort_values("Risque", ascending=False)
    k = st.columns(4)
    k[0].metric("Expéditions suivies", len(tab))
    k[1].metric("En alerte rouge", int((tab[""] == "🔴").sum()))
    k[2].metric("Surestaries estimées", f"{tab['Surestaries (FCFA)'].sum():,.0f}".replace(",", " "))
    k[3].metric("Crédits documentaires bloqués", f"{lcs[lcs['statut']=='Bloqué']['montant'].sum():,.0f}".replace(",", " "))
    st.dataframe(tab.drop(columns="_id"), hide_index=True, use_container_width=True)
    if bouton_export:
        bouton_export(tab.drop(columns=["_id", ""]), "tour_de_controle", "Tour de contrôle des expéditions")

    eid = st.selectbox("Voir le détail d'une expédition", tab["_id"].tolist(), key="tour_sel",
                       format_func=lambda i: f"{tab.loc[tab['_id']==i, 'Dossier'].iloc[0]} — {tab.loc[tab['_id']==i, 'Client'].iloc[0]}")
    e = exps[exps["id"] == eid].iloc[0]
    a, jd, p = analyses[int(eid)]
    st.markdown(f"### {_ICONE[a['niveau']]} Dossier {e['dossier_ref']} — risque {a['score']}/100")
    for niv, txt in a["alertes"]:
        (st.error if niv == "rouge" else st.warning)(txt)
    if not a["alertes"]:
        st.success("Aucune alerte pour le moment.")

    st.progress(int(a["avancement"] * 100))
    cols = st.columns(2)
    for i, (code, lib, pcs) in enumerate(JALONS):
        fait = code in jd
        cols[i % 2].markdown(f"{'✅' if fait else '⬜'} **{lib}**" + (f" · _{pcs}_" if pcs else "") +
                             (f" — {str(jd[code])[:10]}" if fait else ""))

    if exiger("transit.creer"):
        with st.expander("Enregistrer une étape ou régler la franchise"):
            with st.form("form_jalon"):
                c = st.columns(3)
                code = c[0].selectbox("Étape atteinte", CODES, format_func=lambda x: LIBELLE[x],
                                      index=min(CODES.index(a["prochaine"]) if a["prochaine"] else 0, len(CODES) - 1))
                jour = c[1].date_input("Date", value=date.today())
                note = c[2].text_input("Note (facultatif)")
                d = st.columns(3)
                prevue = d[0].date_input("Arrivée prévue au port", value=_jour(e.get("date_arrivee_prevue")) or date.today())
                franchise = d[1].number_input("Jours de franchise (selon contrat)", 0, 60, int(e.get("franchise_jours") or 7))
                pen = d[2].number_input("Pénalité par jour (FCFA)", 0.0, step=10000.0, value=float(e.get("penalite_jour_xof") or 0))
                if st.form_submit_button("Enregistrer"):
                    with connexion() as conn:
                        conn.execute("INSERT INTO jalons_expedition (tenant_id, expedition_id, code, date_jalon, note, saisi_par)"
                                     " VALUES (?,?,?,?,?,?) ON CONFLICT(tenant_id, expedition_id, code) DO UPDATE SET"
                                     " date_jalon=excluded.date_jalon, note=excluded.note, saisi_par=excluded.saisi_par",
                                     (tenant_id, int(eid), code, str(jour), note, username))
                        conn.execute("UPDATE expeditions SET date_arrivee_prevue=?, franchise_jours=?, penalite_jour_xof=?"
                                     " WHERE tenant_id=? AND id=?", (str(prevue), int(franchise), float(pen), tenant_id, int(eid)))
                    journaliser("jalon_expedition", "expeditions", str(eid), f"{code} {jour}")
                    st.success("Enregistré.")
                    st.rerun()

    eta = None
    try:
        ed = etat_expedition(e.to_dict(), p.rename(columns={}), 5.0) if not p.empty else {}
        eta = ed.get("eta_jours")
    except Exception:
        eta = None
    msg = message_client(e["dossier_ref"], e.get("client") or "", a, eta)
    st.markdown("**Prévenir le client**")
    texte = st.text_area("Message (modifiable)", msg, key=f"tour_msg_{eid}")
    st.link_button("Ouvrir dans WhatsApp", lien_whatsapp(e.get("telephone"), texte))
    st.caption("Le lien ouvre WhatsApp avec le message prêt : c'est vous qui appuyez sur « envoyer ».")
