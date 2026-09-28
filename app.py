# --- en tête de fichier, avec les autres imports ---
import theme
import direction
import credit_scoring
import negoce_international
import assistant_ia
import documents_pdf

# --- juste après st.set_page_config(...) ---
theme.inject_apple_theme()

# --- dans page_options, ajouter les nouvelles entrées ---
page_options += [
    "🏛️ Bureau du Directeur",
    "📈 Credit Scoring",
    "🌐 Trésorerie FX & Import",
    "🧠 Assistant IA",
    "🧾 Documents & Envoi",
]

# --- dans le routeur de pages, ajouter les branches ---
elif page == "🏛️ Bureau du Directeur":
    direction.render_bureau_directeur(DB_NAME, st.session_state.username, st.session_state.user_role)

elif page == "📈 Credit Scoring":
    credit_scoring.render_credit_scoring(DB_NAME, st.session_state.username)

elif page == "🌐 Trésorerie FX & Import":
    negoce_international.render_negoce_international(DB_NAME, st.session_state.username)

elif page == "🧠 Assistant IA":
    assistant_ia.render_assistant_ia(DB_NAME)

elif page == "🧾 Documents & Envoi":
    documents_pdf.render_documents(DB_NAME, st.session_state.username, "https://tonapp.streamlit.app/?verifier=1")
