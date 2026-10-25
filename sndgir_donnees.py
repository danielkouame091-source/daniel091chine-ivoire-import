"""Protection des données personnelles des clients (étape 6).

Deux outils pour l'administrateur :
  - EXPORT : tout ce que l'on détient sur un client (droit d'accès).
  - ANONYMISATION : efface nom, e-mail, téléphone et messages d'un client (droit à l'effacement),
    en gardant les montants et références, car les pièces comptables doivent être conservées.

⚠️ Outil technique, pas un avis juridique : les durées de conservation et la procédure
doivent être validées par un juriste (loi ivoirienne n°2013-450, ARTCI).
"""
from __future__ import annotations

import hashlib
import io

import pandas as pd

from sndgir_export import _neutraliser, _nom_feuille

EFFACE = "[effacé – demande de la personne]"

# table → colonnes qui contiennent le nom du client
_TABLES_NOM = {
    "dossiers": "client",
    "connaissements": "client",
    "communications": "destinataire",
}


def pseudonyme(tenant_id: int, nom: str) -> str:
    """Nom de remplacement stable (même client → même code), sans pouvoir retrouver le nom."""
    h = hashlib.sha256(f"{tenant_id}|{nom.strip().lower()}".encode()).hexdigest()[:8].upper()
    return f"CLIENT-ANONYME-{h}"


def lister_clients(lire_df, tenant_id: int) -> list[str]:
    noms: set[str] = set()
    for table, col in _TABLES_NOM.items():
        df = lire_df(f"SELECT DISTINCT {col} AS n FROM {table} WHERE tenant_id=? AND {col} IS NOT NULL", (tenant_id,))
        noms |= {str(n).strip() for n in df["n"] if str(n).strip() and not str(n).startswith("CLIENT-ANONYME-")}
    return sorted(noms, key=str.lower)


def donnees_client(lire_df, tenant_id: int, nom: str) -> dict[str, pd.DataFrame]:
    """Tout ce qui concerne ce client, table par table (recherche exacte, sans tenir compte des majuscules)."""
    p = (tenant_id, nom.strip())
    dossiers = lire_df("SELECT * FROM dossiers WHERE tenant_id=? AND lower(client)=lower(?)", p)
    refs = list(dossiers["reference"]) if "reference" in dossiers else []
    ids = [int(i) for i in dossiers["id"]] if "id" in dossiers else []
    out = {
        "dossiers": dossiers,
        "connaissements": lire_df("SELECT * FROM connaissements WHERE tenant_id=? AND lower(client)=lower(?)", p),
        "communications": lire_df("SELECT * FROM communications WHERE tenant_id=? AND lower(destinataire)=lower(?)", p),
    }
    if ids:
        marques = ",".join("?" * len(ids))
        out["factures_fne"] = lire_df(f"SELECT * FROM fne_factures WHERE tenant_id=? AND dossier_id IN ({marques})",
                                      (tenant_id, *ids))
    if refs:
        marques = ",".join("?" * len(refs))
        out["expeditions"] = lire_df(f"SELECT * FROM expeditions WHERE tenant_id=? AND dossier_ref IN ({marques})",
                                     (tenant_id, *refs))
    return out


def export_excel(donnees: dict[str, pd.DataFrame]) -> bytes:
    """Un classeur Excel, une feuille par table (cellules protégées contre l'injection de formules)."""
    tampon = io.BytesIO()
    with pd.ExcelWriter(tampon, engine="openpyxl") as w:
        for nom, df in donnees.items():
            d = df.copy()
            for c in d.columns:
                if not (pd.api.types.is_numeric_dtype(d[c]) or pd.api.types.is_datetime64_any_dtype(d[c])):
                    d[c] = d[c].map(_neutraliser)
            d.to_excel(w, sheet_name=_nom_feuille(nom), index=False)
        if not donnees:
            pd.DataFrame({"info": ["Aucune donnée"]}).to_excel(w, sheet_name="Vide", index=False)
    return tampon.getvalue()


def anonymiser_client(connexion, journaliser, tenant_id: int, nom: str, motif: str = "") -> dict[str, int]:
    """Efface les données personnelles d'un client. Retourne le nombre de lignes touchées par table.

    Gardé : références, dates, montants (obligation de conservation comptable).
    Effacé : nom, e-mail, téléphone, observations, contenu des messages, NCC du client sur la facture FNE.
    """
    nom = nom.strip()
    if not nom:
        raise ValueError("Nom du client manquant.")
    alias = pseudonyme(tenant_id, nom)
    touches = {"dossiers": 0, "connaissements": 0, "communications": 0, "factures_fne": 0}
    with connexion() as conn:
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM dossiers WHERE tenant_id=? AND lower(client)=lower(?)", (tenant_id, nom))]
        touches["dossiers"] = conn.execute(
            "UPDATE dossiers SET client=?, email=NULL, telephone=NULL, observation=NULL"
            " WHERE tenant_id=? AND lower(client)=lower(?)", (alias, tenant_id, nom)).rowcount
        touches["connaissements"] = conn.execute(
            "UPDATE connaissements SET client=? WHERE tenant_id=? AND lower(client)=lower(?)",
            (alias, tenant_id, nom)).rowcount
        touches["communications"] = conn.execute(
            "UPDATE communications SET destinataire=?, email_destinataire=NULL, objet=?, corps=?"
            " WHERE tenant_id=? AND lower(destinataire)=lower(?)",
            (alias, EFFACE, EFFACE, tenant_id, nom)).rowcount
        if ids:
            marques = ",".join("?" * len(ids))
            touches["factures_fne"] = conn.execute(
                f"UPDATE fne_factures SET ncc_client=NULL WHERE tenant_id=? AND dossier_id IN ({marques})",
                (tenant_id, *ids)).rowcount
    # Le journal ne contient PAS le nom effacé : seulement le code de remplacement.
    journaliser("client_anonymise", "clients", alias,
                f"lignes={sum(touches.values())} motif={motif[:80]}", tenant_id=tenant_id)
    return touches


def render_donnees(lire_df, connexion, journaliser, tenant_id: int, st) -> None:
    """Écran « Données personnelles » de l'administration."""
    st.markdown("##### 👤 Droits des personnes (accès et effacement)")
    st.caption("Une personne peut demander ce que vous savez sur elle, ou demander l'effacement. "
               "Les montants et références comptables sont gardés (obligation légale) ; seuls les éléments "
               "qui identifient la personne sont effacés. Faites valider la procédure par un juriste.")
    clients = lister_clients(lire_df, tenant_id)
    if not clients:
        st.info("Aucun client enregistré.")
        return
    choix = st.selectbox("Client concerné", clients)
    donnees = donnees_client(lire_df, tenant_id, choix)
    st.write(" · ".join(f"{k} : {len(v)}" for k, v in donnees.items()))
    st.download_button("⬇️ Exporter tout ce que nous savons (Excel)", export_excel(donnees),
                       file_name="donnees_client.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    with st.form("form_anonymiser"):
        st.warning("L'anonymisation est DÉFINITIVE : faites d'abord l'export ci-dessus si besoin.")
        motif = st.text_input("Motif (ex. : demande écrite du client du …)")
        confirme = st.text_input("Pour confirmer, retapez le nom exact du client")
        if st.form_submit_button("Anonymiser ce client"):
            if confirme.strip().lower() != choix.strip().lower():
                st.error("Le nom retapé ne correspond pas.")
            else:
                t = anonymiser_client(connexion, journaliser, tenant_id, choix, motif)
                st.success("Client anonymisé : " + ", ".join(f"{k} {v}" for k, v in t.items()))
                st.rerun()
