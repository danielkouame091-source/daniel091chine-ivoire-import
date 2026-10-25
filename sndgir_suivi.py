"""Suivi de la marchandise jusqu'à Abidjan, crédit documentaire et prix de revient d'import.

Repris et adapté de l'ancien module `tracabilite.py` / `negoce_international.py` du dépôt, mais relié
aux dossiers de l'ERP SNDGIR : chaque donnée appartient à une entreprise (tenant_id), chaque
action sensible est journalisée dans la piste d'audit.

Limites assumées : les positions sont SAISIES à la main (ou collées depuis un suivi AIS / le site de
l'armateur) ; il n'y a pas de flux GPS automatique. La distance est à vol d'oiseau : la route maritime est
plus longue, donc la date d'arrivée estimée est indicative. Les coordonnées des ports sont approximatives.
"""
from __future__ import annotations

import math
from datetime import datetime

import pandas as pd
import streamlit as st

SCHEMA_SUIVI = """
CREATE TABLE IF NOT EXISTS expeditions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    dossier_ref TEXT NOT NULL,
    origine TEXT NOT NULL,
    origine_lat REAL, origine_lon REAL,
    destination TEXT NOT NULL,
    dest_lat REAL NOT NULL, dest_lon REAL NOT NULL,
    navire TEXT, numero_conteneur TEXT,
    statut TEXT DEFAULT 'En transit',
    created_by TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS positions_expedition (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    expedition_id INTEGER NOT NULL,
    lat REAL NOT NULL, lon REAL NOT NULL,
    lieu TEXT, note TEXT,
    date_position TEXT NOT NULL,
    saisi_par TEXT
);
CREATE TABLE IF NOT EXISTS credits_documentaires (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    dossier_ref TEXT NOT NULL,
    expedition_id INTEGER NOT NULL,
    banque TEXT, montant REAL NOT NULL,
    statut TEXT DEFAULT 'Bloqué',
    date_deblocage TEXT, debloque_par TEXT,
    UNIQUE(tenant_id, dossier_ref)
);
"""

# Coordonnées APPROXIMATIVES (à ajuster si besoin) : (latitude, longitude)
PORTS = {
    "Abidjan (Port autonome)": (5.264, -4.009),
    "San-Pédro": (4.735, -6.600),
    "Shanghai (Chine)": (31.23, 121.47),
    "Guangzhou / Nansha (Chine)": (22.75, 113.60),
    "Ningbo (Chine)": (29.87, 121.55),
    "Mumbai / Nhava Sheva (Inde)": (18.95, 72.95),
    "Dubaï / Jebel Ali": (25.01, 55.06),
    "Rotterdam (Pays-Bas)": (51.95, 4.14),
    "Anvers (Belgique)": (51.27, 4.33),
    "Le Havre (France)": (49.48, 0.11),
    "Istanbul (Turquie)": (41.0, 28.98),
    "Santos (Brésil)": (-23.98, -46.30),
    "Autre (saisir à la main)": (0.0, 0.0),
}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance à vol d'oiseau entre deux points, en km."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlam = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def valider_coordonnees(lat: float, lon: float) -> None:
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Coordonnées impossibles : latitude entre -90 et 90, longitude entre -180 et 180.")


def etat_expedition(exp: dict, positions: pd.DataFrame, rayon_km: float = 5.0) -> dict:
    """Distance restante, progression, vitesse moyenne et date d'arrivée estimée."""
    d_total = None
    if exp.get("origine_lat") is not None and exp.get("origine_lon") is not None and (exp["origine_lat"] or exp["origine_lon"]):
        d_total = haversine_km(exp["origine_lat"], exp["origine_lon"], exp["dest_lat"], exp["dest_lon"])
    if positions.empty:
        return {"position": False, "message": "Aucune position enregistrée pour le moment.", "distance_totale_km": d_total}
    pos = positions.sort_values("date_position").reset_index(drop=True)
    der = pos.iloc[-1]
    reste = haversine_km(der["lat"], der["lon"], exp["dest_lat"], exp["dest_lon"])
    progression = None
    if d_total and d_total > 0:
        progression = max(0.0, min(100.0, (1 - reste / d_total) * 100))
    vitesse = eta_jours = None
    if len(pos) >= 2:
        dist = sum(haversine_km(pos.loc[i, "lat"], pos.loc[i, "lon"], pos.loc[i + 1, "lat"], pos.loc[i + 1, "lon"])
                   for i in range(len(pos) - 1))
        t0, t1 = pd.to_datetime(pos.iloc[0]["date_position"]), pd.to_datetime(pos.iloc[-1]["date_position"])
        heures = (t1 - t0).total_seconds() / 3600
        if heures > 0 and dist > 0:
            vitesse = dist / heures
            eta_jours = reste / (vitesse * 24)
    arrive = reste <= rayon_km
    return {"position": True, "distance_restante_km": reste, "distance_totale_km": d_total,
            "progression_pct": progression, "vitesse_kmh": vitesse, "eta_jours": eta_jours,
            "arrive": arrive, "derniere_position": f"{der['lat']:.3f}, {der['lon']:.3f}",
            "derniere_date": der["date_position"], "dernier_lieu": der.get("lieu") or ""}


def prix_de_revient(caf: float, droits: float, taxes_specifiques: float, tva: float, autres_frais: float,
                    quantite: float, tva_recuperable: bool = True) -> dict:
    """Prix de revient = CAF + droits + taxes spécifiques + autres frais (+ TVA si non récupérable)."""
    if min(caf, droits, taxes_specifiques, tva, autres_frais) < 0:
        raise ValueError("Aucun montant ne peut être négatif.")
    total = caf + droits + taxes_specifiques + autres_frais + (0.0 if tva_recuperable else tva)
    unitaire = total / quantite if quantite and quantite > 0 else None
    return {"total": total, "unitaire": unitaire}


def render_suivi(lire_df, connexion, journaliser, exiger, tenant_id: int, username: str) -> None:
    st.caption("Positions saisies à la main (ou copiées du suivi du navire). Distance à vol d'oiseau : "
               "la date d'arrivée est une estimation.")
    dossiers = lire_df("SELECT reference, client FROM dossiers WHERE tenant_id=? ORDER BY id DESC", (tenant_id,))
    expeditions = lire_df("SELECT * FROM expeditions WHERE tenant_id=? ORDER BY id DESC", (tenant_id,))
    t_new, t_pos, t_suivi, t_lc = st.tabs(["Nouvelle expédition", "Ajouter une position", "Suivi jusqu'à Abidjan",
                                          "Crédit documentaire"])

    with t_new:
        if exiger("transit.creer"):
            with st.form("form_expedition"):
                c = st.columns(2)
                refs = dossiers["reference"].tolist()
                ref = c[0].selectbox("Dossier d'importation", refs) if refs else c[0].text_input("Référence du dossier")
                navire = c[1].text_input("Navire (facultatif)")
                conteneur = c[0].text_input("N° de conteneur (facultatif)")
                po = c[0].selectbox("Port de départ", list(PORTS), index=2)
                pd_ = c[1].selectbox("Port d'arrivée", list(PORTS), index=0)
                st.caption("Choisissez « Autre » pour saisir vos propres coordonnées ci-dessous.")
                x = st.columns(4)
                olat = x[0].number_input("Départ : latitude", value=float(PORTS[po][0]), format="%.4f")
                olon = x[1].number_input("Départ : longitude", value=float(PORTS[po][1]), format="%.4f")
                dlat = x[2].number_input("Arrivée : latitude", value=float(PORTS[pd_][0]), format="%.4f")
                dlon = x[3].number_input("Arrivée : longitude", value=float(PORTS[pd_][1]), format="%.4f")
                if st.form_submit_button("Créer l'expédition"):
                    try:
                        if not ref:
                            raise ValueError("Indiquez le dossier.")
                        valider_coordonnees(olat, olon)
                        valider_coordonnees(dlat, dlon)
                        with connexion() as conn:
                            cur = conn.execute(
                                "INSERT INTO expeditions (tenant_id, dossier_ref, origine, origine_lat, origine_lon, destination,"
                                " dest_lat, dest_lon, navire, numero_conteneur, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                                (tenant_id, ref, po, olat, olon, pd_, dlat, dlon, navire, conteneur, username,
                                 datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                            eid = cur.lastrowid
                        journaliser("expedition_creee", "expeditions", str(eid), f"dossier={ref} {po}->{pd_}")
                        st.success(f"Expédition n°{eid} créée pour le dossier {ref}.")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

    def choisir(cle: str):
        if expeditions.empty:
            st.info("Aucune expédition. Créez-en une dans l'onglet « Nouvelle expédition ».")
            return None
        eid = st.selectbox("Expédition", expeditions["id"].tolist(), key=cle,
                           format_func=lambda i: f"n°{i} — {expeditions.loc[expeditions['id'] == i, 'dossier_ref'].iloc[0]}"
                                                 f" ({expeditions.loc[expeditions['id'] == i, 'origine'].iloc[0]})")
        return expeditions[expeditions["id"] == eid].iloc[0].to_dict()

    with t_pos:
        exp = choisir("sel_pos")
        if exp and exiger("transit.creer"):
            with st.form("form_position"):
                c = st.columns(4)
                lat = c[0].number_input("Latitude", value=0.0, format="%.4f")
                lon = c[1].number_input("Longitude", value=0.0, format="%.4f")
                jour = c[2].date_input("Date", value=datetime.now().date())
                heure = c[3].time_input("Heure", value=datetime.now().time().replace(microsecond=0))
                lieu = st.text_input("Lieu ou escale (facultatif)", placeholder="ex. Canal de Suez, Tanger Med…")
                note = st.text_input("Note (facultatif)")
                if st.form_submit_button("Enregistrer la position"):
                    try:
                        valider_coordonnees(lat, lon)
                        with connexion() as conn:
                            conn.execute(
                                "INSERT INTO positions_expedition (tenant_id, expedition_id, lat, lon, lieu, note, date_position, saisi_par)"
                                " VALUES (?,?,?,?,?,?,?,?)",
                                (tenant_id, int(exp["id"]), lat, lon, lieu, note, f"{jour} {heure}", username))
                        journaliser("position_expedition", "expeditions", str(exp["id"]), f"{lat},{lon} {lieu}")
                        st.success("Position enregistrée.")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

    with t_suivi:
        exp = choisir("sel_suivi")
        if exp:
            pos = lire_df("SELECT * FROM positions_expedition WHERE tenant_id=? AND expedition_id=? ORDER BY date_position",
                          (tenant_id, int(exp["id"])))
            rayon = st.number_input("Distance considérée comme « arrivé » (km)", 1.0, 100.0, 5.0, key="rayon_arrivee")
            e = etat_expedition(exp, pos, rayon)
            if not e["position"]:
                st.info(e["message"])
            else:
                k = st.columns(4)
                k[0].metric("Reste à parcourir", f"{e['distance_restante_km']:,.0f} km".replace(",", " "))
                k[1].metric("Progression", f"{e['progression_pct']:.0f} %" if e["progression_pct"] is not None else "n/d")
                k[2].metric("Vitesse moyenne", f"{e['vitesse_kmh']:.0f} km/h" if e["vitesse_kmh"] else "n/d")
                k[3].metric("Arrivée estimée", f"dans {e['eta_jours']:.0f} jours" if e["eta_jours"] else "n/d")
                if e["progression_pct"] is not None:
                    st.progress(int(e["progression_pct"]))
                if e["arrive"]:
                    st.success("✅ La marchandise est arrivée dans la zone du port de destination.")
                else:
                    st.info(f"Dernière position : {e['derniere_position']} le {e['derniere_date']} {e['dernier_lieu']}")
                carte = pd.DataFrame({"lat": pos["lat"], "lon": pos["lon"]})
                carte.loc[len(carte)] = [exp["dest_lat"], exp["dest_lon"]]
                st.map(carte)
                st.dataframe(pos[["date_position", "lat", "lon", "lieu", "note", "saisi_par"]], hide_index=True,
                             use_container_width=True)
                st.caption("Estimation à vol d'oiseau : la route maritime réelle est plus longue.")

    with t_lc:
        exp = choisir("sel_lc")
        lcs = lire_df("SELECT * FROM credits_documentaires WHERE tenant_id=? ORDER BY id DESC", (tenant_id,))
        if exp and exiger("transit.creer"):
            with st.form("form_lc"):
                c = st.columns(3)
                banque = c[0].text_input("Banque émettrice")
                montant = c[1].number_input("Montant (FCFA)", 0.0, step=500000.0)
                if c[2].form_submit_button("Lier un crédit documentaire à cette expédition"):
                    if montant <= 0:
                        st.error("Le montant doit être supérieur à zéro.")
                    else:
                        try:
                            with connexion() as conn:
                                conn.execute(
                                    "INSERT INTO credits_documentaires (tenant_id, dossier_ref, expedition_id, banque, montant)"
                                    " VALUES (?,?,?,?,?)", (tenant_id, exp["dossier_ref"], int(exp["id"]), banque, montant))
                            journaliser("lc_cree", "credits_documentaires", exp["dossier_ref"], f"montant={montant}")
                            st.success("Crédit documentaire enregistré (bloqué).")
                            st.rerun()
                        except Exception:
                            st.error("Un crédit documentaire existe déjà pour ce dossier.")
        if not lcs.empty:
            st.dataframe(lcs, hide_index=True, use_container_width=True)
            if exiger("transit.valider"):
                cible = st.selectbox("Crédit à débloquer", lcs[lcs["statut"] == "Bloqué"]["dossier_ref"].tolist() or ["—"],
                                     key="lc_cible")
                if st.button("Vérifier l'arrivée et débloquer", key="btn_lc") and cible != "—":
                    ligne = lcs[lcs["dossier_ref"] == cible].iloc[0]
                    ex = expeditions[expeditions["id"] == ligne["expedition_id"]]
                    pos = lire_df("SELECT * FROM positions_expedition WHERE tenant_id=? AND expedition_id=?",
                                  (tenant_id, int(ligne["expedition_id"])))
                    etat = etat_expedition(ex.iloc[0].to_dict(), pos, st.session_state.get("rayon_arrivee", 5.0)) if not ex.empty else {"position": False}
                    if not etat.get("position") or not etat.get("arrive"):
                        st.error("Refusé : la marchandise n'est pas encore confirmée à destination.")
                        journaliser("lc_refuse", "credits_documentaires", cible, "arrivée non confirmée")
                    else:
                        with connexion() as conn:
                            conn.execute("UPDATE credits_documentaires SET statut='Débloqué', date_deblocage=?, debloque_par=?"
                                         " WHERE tenant_id=? AND dossier_ref=?",
                                         (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), username, tenant_id, cible))
                        journaliser("lc_debloque", "credits_documentaires", cible, f"montant={ligne['montant']}")
                        st.success("Crédit documentaire débloqué : arrivée confirmée par la dernière position.")
                        st.rerun()
                st.caption("Le déblocage n'est qu'un enregistrement dans l'ERP : le vrai paiement reste fait par la banque.")


def render_prix_revient(lire_df, tenant_id: int) -> None:
    st.caption("Combien coûte vraiment chaque unité importée, tout compris.")
    d = lire_df("SELECT * FROM dossiers WHERE tenant_id=? ORDER BY id DESC", (tenant_id,))
    if d.empty:
        st.info("Aucun dossier d'importation.")
        return
    ref = st.selectbox("Dossier", d["reference"].tolist(), key="pr_ref")
    r = d[d["reference"] == ref].iloc[0]
    caf, droits = float(r["valeur_caf_xof"] or 0), float(r["droits_douane"] or 0)
    taxes = float(r.get("taxes_specifiques") or 0)
    tva = float(r["tva"] or 0)
    q = float(r.get("quantite") or 0)
    c = st.columns(4)
    c[0].metric("Valeur CAF", f"{caf:,.0f}".replace(",", " "))
    c[1].metric("Droits de douane", f"{droits:,.0f}".replace(",", " "))
    c[2].metric("Taxes spécifiques", f"{taxes:,.0f}".replace(",", " "))
    c[3].metric("TVA", f"{tva:,.0f}".replace(",", " "))
    x = st.columns(3)
    frais = x[0].number_input("Autres frais (transit, transport local, manutention, magasinage)", 0.0, step=50000.0, key="pr_frais")
    quantite = x[1].number_input("Quantité", 0.0, value=q, key="pr_q")
    rec = x[2].checkbox("TVA récupérable", value=True, key="pr_rec")
    res = prix_de_revient(caf, droits, taxes, tva, frais, quantite, rec)
    st.metric("Prix de revient total", f"{res['total']:,.0f} FCFA".replace(",", " "))
    if res["unitaire"] is not None:
        st.metric("Prix de revient par unité", f"{res['unitaire']:,.0f} FCFA".replace(",", " "))
    else:
        st.warning("Indiquez la quantité pour obtenir le prix par unité.")
