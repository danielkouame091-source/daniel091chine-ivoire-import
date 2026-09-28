"""
Text-to-SQL sécurisé pour BaobabVault ERP (SQLite).

1. Schéma injecté dynamiquement dans le prompt système
2. Routage : indices par sujet -> seules les tables pertinentes sont montrées
3. Retry : l'erreur SQL est renvoyée au modèle pour qu'il corrige sa requête

À ADAPTER : DB_PATH, ROUTES (noms de tables réels) et call_llm (votre fournisseur).
"""
import re
import sqlite3

DB_PATH = "baobabvault.db"  # <- votre fichier SQLite
MAX_RETRIES = 3
MAX_ROWS = 200

# --- 2. Routage : mots-clés -> tables (remplacez par vos vraies tables) ------
ROUTES = {
    "credit": {
        "keywords": ["crédit", "credit", "score", "scoring", "solvabilité"],
        "tables": ["credit_scoring"],  # <- votre table de scoring
        "hint": "Questions de crédit/score client : utiliser UNIQUEMENT ces "
                "tables. Ne PAS utiliser comptes_geles.",
    },
    "gel": {
        "keywords": ["gelé", "gele", "gel ", "bloqué", "bloque", "freeze"],
        "tables": ["comptes_geles"],
        "hint": "Comptes gelés/bloqués uniquement.",
    },
    # ajoutez : tresorerie, fiscalite, documents, ...
}


# --- 1. Schéma dynamique ------------------------------------------------------
def connect_readonly(path=DB_PATH):
    """Connexion en lecture seule : le LLM ne peut rien modifier."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def list_tables(con):
    rows = con.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return [r["name"] for r in rows]


def describe_table(con, table):
    cols = con.execute(f'PRAGMA table_info("{table}")').fetchall()
    col_txt = ", ".join(f'{c["name"]} {c["type"]}' for c in cols)
    return f"- {table}({col_txt})"


def pick_tables(question, all_tables):
    """Retourne (tables_à_montrer, indices). Si aucun sujet reconnu : tout."""
    q = question.lower()
    tables, hints = [], []
    for route in ROUTES.values():
        if any(k in q for k in route["keywords"]):
            tables += [t for t in route["tables"] if t in all_tables]
            hints.append(route["hint"])
    return (list(dict.fromkeys(tables)) or all_tables), hints


def build_system_prompt(con, question):
    all_tables = list_tables(con)
    tables, hints = pick_tables(question, all_tables)
    schema = "\n".join(describe_table(con, t) for t in tables)
    hint_txt = "\n".join(f"* {h}" for h in hints)
    return (
        "Tu es un assistant SQL pour un ERP financier (SQLite).\n"
        "Réponds avec UNE SEULE requête SELECT, sans explication, "
        "dans un bloc ```sql.\n"
        "Utilise UNIQUEMENT les tables et colonnes listées ci-dessous. "
        "N'invente jamais de colonne.\n"
        "Si la question ne peut pas être traitée avec ce schéma, réponds "
        "exactement : IMPOSSIBLE\n\n"
        f"SCHÉMA :\n{schema}\n\n"
        f"CONSIGNES DE ROUTAGE :\n{hint_txt or '(aucune)'}"
    ), tables


# --- Sécurité : validation de la requête --------------------------------------
def extract_sql(text):
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    return (m.group(1) if m else text).strip().rstrip(";")


def validate_sql(sql, allowed_tables):
    low = sql.lower()
    if not low.startswith("select"):
        raise ValueError("Seules les requêtes SELECT sont autorisées.")
    if ";" in sql:
        raise ValueError("Une seule requête est autorisée.")
    used = re.findall(r"(?:from|join)\s+\"?([a-zA-Z_][\w]*)\"?", low)
    bad = [t for t in used if t not in {a.lower() for a in allowed_tables}]
    if bad:
        raise ValueError(f"Table non autorisée : {', '.join(bad)}")


# --- 3. Boucle avec retry -----------------------------------------------------
def call_llm(system_prompt, messages):
    """
    <- À REMPLACER par votre appel actuel (Claude, Gemini, OpenAI...).
    Doit retourner le texte de la réponse du modèle.
    messages = [{"role": "user"|"assistant", "content": "..."}]
    """
    raise NotImplementedError("Branchez ici votre appel au modèle.")


def ask(question, path=DB_PATH):
    """Retourne (sql, lignes) ou lève une erreur propre."""
    con = connect_readonly(path)
    try:
        system_prompt, tables = build_system_prompt(con, question)
        messages = [{"role": "user", "content": question}]
        last_error = None

        for attempt in range(1, MAX_RETRIES + 1):
            reply = call_llm(system_prompt, messages)
            if "IMPOSSIBLE" in reply.upper() and "SELECT" not in reply.upper():
                raise LookupError("Je ne trouve pas cette information.")

            sql = extract_sql(reply)
            try:
                validate_sql(sql, tables)
                rows = con.execute(sql).fetchmany(MAX_ROWS)
                return sql, [dict(r) for r in rows]
            except (sqlite3.Error, ValueError) as e:
                last_error = e
                print(f"[assistant_sql] tentative {attempt} échouée : {e}")  # log serveur
                messages += [
                    {"role": "assistant", "content": reply},
                    {"role": "user", "content":
                        f"Cette requête a échoué : {e}\n"
                        "Corrige-la en respectant strictement le schéma. "
                        "Réponds avec une seule requête SELECT."},
                ]
        raise RuntimeError(f"Échec après {MAX_RETRIES} tentatives : {last_error}")
    finally:
        con.close()


# --- Utilisation dans Streamlit ---------------------------------------------
# import streamlit as st
# from assistant_sql import ask
#
# if q := st.chat_input("Pose une question..."):
#     try:
#         sql, rows = ask(q)
#         st.dataframe(rows)
#         with st.expander("Requête exécutée"):   # réservé à l'admin
#             st.code(sql, language="sql")
#     except LookupError as e:
#         st.info(str(e))
#     except Exception:
#         st.warning("Je n'ai pas pu répondre. Reformulez votre question.")
