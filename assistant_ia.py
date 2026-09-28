"""
BaobabVault ERP - Assistant IA (Text-to-SQL) pour Streamlit + SQLite.

Utilisation dans votre app principale, dans la branche "Assistant IA" :
    from assistant_ia import render_assistant
    render_assistant(show_sql=(role == "Administrateur"))

Ce fichier REMPLACE totalement l'ancienne fonction de l'assistant.
"""
import os
import re
import sqlite3
import unicodedata
from pathlib import Path

import streamlit as st

# ----------------------------- CONFIG ----------------------------------------
DB_PATH = "baobabvault.db"          # <- chemin de votre fichier SQLite
MAX_RETRIES = 3                     # tentatives de correction par le modèle
MAX_ROWS = 200
SAMPLE_ROWS = 0                     # >0 = envoie N lignes d'exemple au modèle
ANTHROPIC_MODEL = "claude-sonnet-5"
GEMINI_MODEL = "gemini-2.0-flash"   # <- adaptez si besoin

# Routage : si un mot-clé apparaît dans la question, on ne montre au modèle que
# les tables dont le NOM contient un des fragments. Aucun nom de table exact
# n'est requis : ça marche par fragments ("credit", "score"...).
ROUTES = [
    {
        "keywords": ["credit", "score", "scoring", "solvabilite", "cote"],
        "table_fragments": ["credit", "scor", "client"],
        "hint": "Questions de crédit / score / solvabilité : utilise "
                "UNIQUEMENT les tables fournies. N'utilise JAMAIS "
                "comptes_geles pour une question de crédit.",
    },
    {
        "keywords": ["gele", "geles", "bloque", "freeze", "gel "],
        "table_fragments": ["gele"],
        "hint": "Comptes gelés / bloqués uniquement.",
    },
    # Ajoutez d'autres routes : tresorerie, fiscalite, documents, dossier...
]


# ----------------------------- SCHÉMA ----------------------------------------
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def connect_readonly() -> sqlite3.Connection:
    """Lecture seule : le modèle ne peut rien modifier."""
    con = sqlite3.connect(f"file:{Path(DB_PATH).resolve()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def load_schema(con) -> dict:
    """{table: [(colonne, type), ...]} lu en direct dans la base."""
    tables = [r["name"] for r in con.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return {
        t: [(c["name"], c["type"])
            for c in con.execute(f'PRAGMA table_info("{t}")')]
        for t in tables
    }


def select_tables(question: str, schema: dict):
    """Retourne (tables_choisies, indices_de_routage)."""
    q = _norm(question)
    chosen, hints = [], []

    for r in ROUTES:
        if any(k in q for k in r["keywords"]):
            hints.append(r["hint"])
            chosen += [t for t in schema
                       if any(f in _norm(t) for f in r["table_fragments"])]

    if not chosen:  # sinon : score par mots communs (noms de tables/colonnes)
        words = set(re.findall(r"[a-z0-9]{4,}", q))
        scored = []
        for t, cols in schema.items():
            tokens = set(re.findall(
                r"[a-z0-9]{3,}",
                _norm(t) + " " + " ".join(_norm(c) for c, _ in cols)))
            s = sum(1 for w in words
                    if any(w in tk or tk in w for tk in tokens))
            if s:
                scored.append((s, t))
        chosen = [t for _, t in sorted(scored, reverse=True)[:4]]

    chosen = list(dict.fromkeys(chosen)) or list(schema)  # repli : tout
    return chosen, hints


def build_system_prompt(con, schema, tables, hints) -> str:
    lines = []
    for t in tables:
        cols = ", ".join(f"{c} {ty}" for c, ty in schema[t])
        lines.append(f"- {t}({cols})")
        if SAMPLE_ROWS:
            for row in con.execute(f'SELECT * FROM "{t}" LIMIT {SAMPLE_ROWS}'):
                lines.append(f"    exemple: {dict(row)}")
    hint_txt = "\n".join(f"* {h}" for h in hints) or "(aucune)"
    return (
        "Tu es un assistant SQL pour un ERP financier (SQLite).\n"
        "Réponds avec UNE SEULE requête SELECT dans un bloc ```sql, sans "
        "explication.\n"
        "RÈGLES STRICTES :\n"
        "- Utilise UNIQUEMENT les tables et colonnes du schéma ci-dessous. "
        "N'invente JAMAIS de colonne (ex. : n'écris pas 'motif' si elle "
        "n'est pas listée).\n"
        "- Pour chercher un nom (client, société), utilise "
        "LIKE '%...%' COLLATE NOCASE.\n"
        f"- Limite les résultats à {MAX_ROWS} lignes.\n"
        "- Si le schéma ne permet pas de répondre, réponds exactement : "
        "IMPOSSIBLE\n\n"
        f"SCHÉMA :\n" + "\n".join(lines) + f"\n\nCONSIGNES :\n{hint_txt}"
    )


# ----------------------------- SÉCURITÉ SQL ----------------------------------
def extract_sql(text: str) -> str:
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    return (m.group(1) if m else text).strip().rstrip(";").strip()


def validate_sql(sql: str, allowed: list):
    if not sql.lower().startswith("select"):
        raise ValueError("Seules les requêtes SELECT sont autorisées.")
    if ";" in sql:
        raise ValueError("Une seule requête est autorisée.")
    used = re.findall(r'(?:from|join)\s+"?(\w+)"?', sql, re.I)
    allowed_l = {a.lower() for a in allowed}
    bad = [t for t in used if t.lower() not in allowed_l]
    if bad:
        raise ValueError(
            f"Table non autorisée : {', '.join(bad)}. "
            f"Tables disponibles : {', '.join(allowed)}.")


# ----------------------------- APPEL AU MODÈLE -------------------------------
def _secret(name):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name)


def call_llm(system_prompt: str, messages: list) -> str:
    """Si vous avez déjà votre propre appel, remplacez le corps ici."""
    key = _secret("ANTHROPIC_API_KEY")
    if key:
        import anthropic
        r = anthropic.Anthropic(api_key=key).messages.create(
            model=ANTHROPIC_MODEL, max_tokens=800, temperature=0,
            system=system_prompt, messages=messages)
        return r.content[0].text

    key = _secret("GEMINI_API_KEY") or _secret("GOOGLE_API_KEY")
    if key:
        from google import genai
        from google.genai import types
        contents = [
            types.Content(role="user" if m["role"] == "user" else "model",
                          parts=[types.Part(text=m["content"])])
            for m in messages]
        r = genai.Client(api_key=key).models.generate_content(
            model=GEMINI_MODEL, contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt, temperature=0))
        return r.text

    raise RuntimeError("Aucune clé API trouvée (ANTHROPIC_API_KEY ou "
                       "GEMINI_API_KEY dans .streamlit/secrets.toml).")


# ----------------------------- BOUCLE + RETRY --------------------------------
def ask(question: str) -> dict:
    """Ne lève jamais d'exception : retourne toujours un dict."""
    try:
        con = connect_readonly()
    except Exception as e:
        print(f"[assistant] connexion DB impossible : {e}")
        return {"error": "Base de données inaccessible."}

    try:
        schema = load_schema(con)
        scope, hints = select_tables(question, schema)
        system_prompt = build_system_prompt(con, schema, scope, hints)
        messages = [{"role": "user", "content": question}]

        for attempt in range(1, MAX_RETRIES + 1):
            # Dernière chance : on montre tout le schéma au modèle
            if attempt == MAX_RETRIES and set(scope) != set(schema):
                scope = list(schema)
                system_prompt = build_system_prompt(con, schema, scope, hints)

            reply = call_llm(system_prompt, messages)
            if "IMPOSSIBLE" in reply.upper() and "SELECT" not in reply.upper():
                return {"info": "Je ne trouve pas cette information dans "
                                "la base."}

            sql = extract_sql(reply)
            try:
                validate_sql(sql, scope)
                rows = [dict(r) for r in
                        con.execute(sql).fetchmany(MAX_ROWS)]
                return {"sql": sql, "rows": rows, "attempts": attempt}
            except (sqlite3.Error, ValueError) as e:
                print(f"[assistant] tentative {attempt} échouée : {e} | {sql}")
                cols_help = "\n".join(
                    f"- {t}({', '.join(c for c, _ in schema[t])})"
                    for t in scope)
                messages += [
                    {"role": "assistant", "content": reply},
                    {"role": "user", "content":
                        f"La requête a échoué : {e}\n"
                        f"Colonnes réellement disponibles :\n{cols_help}\n"
                        "Corrige-la en utilisant UNIQUEMENT ces colonnes. "
                        "Réponds avec une seule requête SELECT."},
                ]
        return {"error": "Je n'ai pas réussi à formuler une requête valide. "
                         "Essayez de reformuler votre question."}
    except Exception as e:
        print(f"[assistant] erreur inattendue : {e}")
        return {"error": "Une erreur est survenue. Réessayez plus tard."}
    finally:
        con.close()


# ----------------------------- INTERFACE STREAMLIT ---------------------------
def render_assistant(show_sql: bool = True):
    st.markdown("## 🧠 Assistant IA — Analyse & Archiviste")
    st.caption("Pose une question financière ou retrouve un document "
               "(référence, client, dossier...).")

    if not Path(DB_PATH).exists():
        st.error(f"Base introuvable : {DB_PATH}. Vérifiez DB_PATH.")
        return

    history = st.session_state.setdefault("assistant_history", [])

    for item in history:
        with st.chat_message("user"):
            st.write(item["question"])
        with st.chat_message("assistant"):
            _show_result(item["result"], show_sql)

    if question := st.chat_input(
            "Ex : « Quel est le score de crédit de la SARL Koffi ? »"):
        with st.chat_message("user"):
            st.write(question)
        with st.chat_message("assistant"):
            with st.spinner("Analyse en cours..."):
                result = ask(question)
            _show_result(result, show_sql)
        history.append({"question": question, "result": result})


def _show_result(result: dict, show_sql: bool):
    if "error" in result:
        st.warning(result["error"])
    elif "info" in result:
        st.info(result["info"])
    else:
        if result["rows"]:
            st.dataframe(result["rows"], use_container_width=True)
        else:
            st.info("Aucun résultat pour cette question.")
        if show_sql:
            with st.expander("Requête exécutée"):
                st.code(result["sql"], language="sql")
