"""
theme.py — BaobabVault ERP
Design system centralisé, inspiré iOS/macOS : dark mode sophistiqué,
cartes en glassmorphism, typographie SF-Pro-like, micro-animations.
UNE SEULE fonction à appeler en tête de chaque page : inject_apple_theme().
"""

import streamlit as st

PALETTE = {
    "bg_base": "#05070D",
    "bg_gradient": "radial-gradient(circle at 15% -10%, #14213D 0%, #05070D 55%)",
    "card": "rgba(255,255,255,0.045)",
    "card_border": "rgba(255,255,255,0.10)",
    "text_primary": "#F5F7FA",
    "text_secondary": "#8B95A7",
    "accent": "#0A84FF",       # bleu iOS
    "success": "#30D158",      # vert iOS
    "warning": "#FF9F0A",      # orange iOS
    "danger": "#FF453A",       # rouge iOS
}


def inject_apple_theme():
    st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

    html, body, [class*="css"] {{
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'SF Pro Display', sans-serif;
    }}

    .stApp {{
        background: {PALETTE['bg_gradient']};
        color: {PALETTE['text_primary']};
    }}

    /* Cartes glassmorphism réutilisables — classe .bv-card */
    .bv-card {{
        background: {PALETTE['card']};
        backdrop-filter: blur(20px) saturate(160%);
        -webkit-backdrop-filter: blur(20px) saturate(160%);
        border: 1px solid {PALETTE['card_border']};
        border-radius: 22px;
        padding: 22px 24px;
        box-shadow: 0 8px 28px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.05);
        transition: transform .22s cubic-bezier(.2,.8,.2,1), box-shadow .22s ease;
        margin-bottom: 14px;
    }}
    .bv-card:hover {{ transform: translateY(-3px); box-shadow: 0 16px 40px rgba(0,0,0,0.55); }}

    .bv-badge {{
        display:inline-block; padding:3px 12px; border-radius:999px;
        font-size:0.72rem; font-weight:600; letter-spacing:.02em;
    }}
    .bv-badge-success {{ background: rgba(48,209,88,0.15); color:{PALETTE['success']}; }}
    .bv-badge-warning {{ background: rgba(255,159,10,0.15); color:{PALETTE['warning']}; }}
    .bv-badge-danger  {{ background: rgba(255,69,58,0.15); color:{PALETTE['danger']}; }}
    .bv-badge-neutral {{ background: rgba(139,149,167,0.15); color:{PALETTE['text_secondary']}; }}

    /* Boutons — relief doux, jamais criard */
    div[data-testid="stButton"] > button {{
        border-radius: 14px !important;
        background: linear-gradient(160deg, #182647, #0E1830) !important;
        border: 1px solid rgba(255,255,255,0.09) !important;
        color: {PALETTE['text_primary']} !important;
        font-weight: 600 !important;
        transition: transform .15s ease, background .2s ease !important;
    }}
    div[data-testid="stButton"] > button:hover {{ transform: translateY(-1px) scale(1.01); }}
    div[data-testid="stButton"] > button[kind="primary"] {{
        background: linear-gradient(160deg, {PALETTE['accent']}, #0060DB) !important;
        border: none !important;
    }}

    div[data-testid="stMetric"] {{
        background: {PALETTE['card']};
        border: 1px solid {PALETTE['card_border']};
        border-radius: 18px;
        padding: 16px;
    }}

    section[data-testid="stSidebar"] {{
        background: rgba(5,7,13,0.85);
        border-right: 1px solid rgba(255,255,255,0.06);
    }}

    #MainMenu, footer {{visibility: hidden;}}
    </style>
    """, unsafe_allow_html=True)


def badge(texte: str, niveau: str = "neutral") -> str:
    """niveau: success | warning | danger | neutral — à insérer via st.markdown(..., unsafe_allow_html=True)"""
    return f'<span class="bv-badge bv-badge-{niveau}">{texte}</span>'


def carte_kpi_html(titre: str, valeur: str, sous_texte: str = "", niveau: str = "neutral") -> str:
    return f"""
    <div class="bv-card">
        <div style="color:{PALETTE['text_secondary']};font-size:0.8rem;font-weight:600;">{titre}</div>
        <div style="font-size:1.9rem;font-weight:800;margin:4px 0;">{valeur}</div>
        <div style="font-size:0.78rem;">{badge(sous_texte, niveau) if sous_texte else ""}</div>
    </div>
    """
