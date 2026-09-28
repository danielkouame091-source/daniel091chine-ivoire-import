"""
assistant_ia.py — BaobabVault ERP
Assistant IA (Claude) capable d'analyser les données financières en direct
et de retrouver instantanément un document dans le système ("archiviste").

Deux capacités distinctes, combinées à chaque question :
 1. ANALYSE : agrège des chiffres réels de la base (trésorerie, transactions,
    dossiers import, notations crédit...) et les transmet en contexte à Claude.
 2. RECHERCHE DOCUMENTAIRE : recherche SQL full-text (LIKE) sur les tables
    contenant des références/documents, plutôt qu'une base vectorielle —
    largement suffisant au volume d'un ERP PME, et 100% auditable.
"""

import sqlite3

import pandas as pd
import streamlit as st
from anthropic import Anthropic

import theme

SYSTEM_PROMPT = """Tu es l'assistant financier intégré de BaobabVault ERP, un
système de gestion comptable et bancaire pour PME et institutions africaines
(normes SYSCOHADA révisé / OHADA). Tu réponds de façon précise, chiffrée et
professionnelle en français. Tu t'appuies UNIQUEMENT sur les données de
contexte fournies ci-dessous — si une information n'y figure pas, dis
clairement que tu ne l'as pas plutôt que d'inventer un chiffre. Formate les
montants en FCFA avec séparateurs de milliers."""


def _get_client() -> Anthropic:
    api_key = st.secrets.get("ANTHROPIC_API_KEY") if hasattr(st, "secrets") else None
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY absente des secrets Streamlit.")
    return Anthropic(api_key=api_key)


def _contexte_financier(db_name: str) -> str:
    """Agrège les chiffres clés réels de la base — jamais de données inventées."""
    conn = sqlite3.connect(db_name)
    blocs = []

    try:
        tresorerie = conn.execute("SELECT COALESCE(SUM(montant),0) FROM transactions").fetchone()[0]
        blocs.append(f"Trésorerie cumulée (transactions enregistrées) : {tresorerie:,.0f} FCFA")
    except sqlite3.OperationalError:
        pass

    try:
        df_geles = pd.read_sql_query("SELECT compte, motif FROM comptes_geles", conn)
        if not df_geles.empty:
            blocs.append(f"Comptes gelés (AML) : {len(df_geles)} — " + "; ".join(
                f"{r.compte} ({r.motif})" for r in df_geles.itertuples()))
    except sqlite3.OperationalError:
        pass

    try:
        df_import = pd.read_sql_query(
            "SELECT reference, fournisseur, prix_revient_total FROM dossiers_import ORDER BY id DESC LIMIT 5", conn)
        if not df_import.empty:
            blocs.append("5 derniers dossiers d'import : " + "; ".join(
                f"{r.reference} ({r.fournisseur}) = {r.prix_revient_total:,.0f} FCFA" for r in df_import.itertuples()))
    except sqlite3.OperationalError:
        pass

    try:
        df_scoring = pd.read_sql_query(
            "SELECT raison_sociale, score, classe FROM tiers_notation ORDER BY id DESC LIMIT 5", conn)
        if not df_scoring.empty:
            blocs.append("5 dernières notations crédit : " + "; ".join(
                f"{r.raison_sociale} = {r.score}/100 (classe {r.classe})" for r in df_scoring.itertuples()))
    except sqlite3.OperationalError:
        pass

    conn.close()
    return "\n".join(blocs) if blocs else "Aucune donnée financière disponible pour l'instant."


# Tables candidates pour la recherche documentaire "archiviste".
# (colonne_recherche, colonnes_affichees, libellé humain)
TABLES_RECHERCHABLES = [
    ("dossiers_import", "reference", ["reference", "fournisseur", "prix_revient_total", "created_at"], "Dossier d'import"),
    ("tiers_notation", "raison_sociale", ["raison_sociale", "secteur", "score", "classe", "evalue_le"], "Notation crédit"),
    ("validations_sensibles", "reference", ["id", "type_operation", "reference", "montant", "statut"], "Validation 4 yeux"),
    ("documents_emis", "reference", ["reference", "type_document", "client", "montant", "created_at"], "Document PDF émis"),
]


def rechercher_document(db_name: str, terme: str) -> list[dict]:
    """Recherche full-text simple (LIKE) à travers toutes les tables pertinentes.
    Retourne une liste de résultats structurés — c'est la fonction 'archiviste'."""
    if not terme or len(terme.strip()) < 2:
        return []

    resultats = []
    conn = sqlite3.connect(db_name)
    for table, colonne_cle, colonnes, libelle in TABLES_RECHERCHABLES:
        try:
            cols_sql = ", ".join(colonnes)
            rows = conn.execute(
                f"SELECT {cols_sql} FROM {table} WHERE {colonne_cle} LIKE ? LIMIT 20",
                (f"%{terme}%",),
            ).fetchall()
            for r in rows:
                resultats.append({"type": libelle, "table": table, "valeurs": dict(zip(colonnes, r))})
        except sqlite3.OperationalError:
            continue  # table pas encore créée sur ce déploiement — normal, on ignore
    conn.close()
    return resultats


def poser_question(db_name: str, question: str) -> str:
    contexte = _contexte_financier(db_name)
    resultats_recherche = rechercher_document(db_name, question)

    contexte_complet = f"DONNÉES FINANCIÈRES ACTUELLES :\n{contexte}"
    if resultats_recherche:
        lignes = "\n".join(f"- {r['type']} : {r['valeurs']}" for r in resultats_recherche[:15])
        contexte_complet += f"\n\nDOCUMENTS TROUVÉS EN LIEN AVEC LA QUESTION :\n{lignes}"

    client = _get_client()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        system=SYSTEM_PROMPT + f"\n\n{contexte_complet}",
        messages=[{"role": "user", "content": question}],
    )
    return "\n".join(b.text for b in response.content if b.type == "text")


def render_assistant_ia(db_name: str):
    theme.inject_apple_theme()
    st.subheader("🧠 Assistant IA — Analyse & Archiviste")
    st.caption("Pose une question financière ou retrouve un document (référence, client, dossier...).")

    if "historique_assistant" not in st.session_state:
        st.session_state.historique_assistant = []

    for role, contenu in st.session_state.historique_assistant:
        with st.chat_message(role):
            st.markdown(contenu)

    question = st.chat_input("Ex : « Quel est le score de crédit de la SARL Koffi ? » ou « Retrouve le dossier IMP-2026-014 »")
    if question:
        st.session_state.historique_assistant.append(("user", question))
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            with st.spinner("Analyse en cours..."):
                try:
                    reponse = poser_question(db_name, question)
                except RuntimeError as e:
                    reponse = f"⚠️ {e} — configure `ANTHROPIC_API_KEY` dans les secrets Streamlit pour activer l'assistant."
                except Exception as e:
                    reponse = f"⚠️ Erreur lors de l'appel à l'assistant : {e}"
                st.markdown(reponse)
        st.session_state.historique_assistant.append(("assistant", reponse))
