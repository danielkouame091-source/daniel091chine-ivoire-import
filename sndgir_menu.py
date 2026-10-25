"""Sous-menus en tuiles carrées (style écran d'accueil de téléphone) pour remplacer les onglets.

`sous_menu("cle", ["📁 Dossiers", "🧮 Calculateur"])` affiche une rangée de tuiles et renvoie une liste de
booléens (un par entrée, un seul vrai). Utilisation :  `a, b = sous_menu(...)`  puis  `if a: ...`  `if b: ...`.
Seule la section choisie est calculée et affichée.
"""
from __future__ import annotations

import streamlit as st

CSS_SOUS_MENU = """
/* ---------- Sous-menus : tuiles carrées plus petites ---------- */
[class*="st-key-sm_"]{margin:4px 0 18px;}
[class*="st-key-sm_"] [data-testid="stHorizontalBlock"]{gap:14px;}
[class*="st-key-sm_"] [data-testid="stColumn"]{min-width:0;}
[class*="st-key-sm_"] div[data-testid="stButton"] button{
  --tc:#0A84FF;aspect-ratio:1/1;width:100%;min-height:96px;border-radius:22px!important;
  display:flex;align-items:center;justify-content:center;text-align:center;padding:8px!important;
  background:var(--glass)!important;border:1px solid var(--edge)!important;
  box-shadow:0 1px 0 rgba(255,255,255,.16) inset,0 14px 26px -12px rgba(0,0,0,.8),0 8px 20px -14px var(--tc)!important;
  backdrop-filter:blur(16px);transition:transform .22s cubic-bezier(.2,.8,.2,1),box-shadow .22s ease!important;}
[class*="st-key-sm_"] div[data-testid="stButton"] button p{white-space:pre-line;line-height:1.3;font-size:.74rem;
  font-weight:700;color:#e8edf6;margin:0;}
[class*="st-key-sm_"] div[data-testid="stButton"] button p::first-line{font-size:1.9rem;line-height:1.5;}
[class*="st-key-sm_"] div[data-testid="stButton"] button:hover{transform:translateY(-4px) scale(1.04);
  box-shadow:0 1px 0 rgba(255,255,255,.22) inset,0 20px 34px -12px rgba(0,0,0,.85),0 0 26px -6px var(--tc)!important;}
[class*="st-key-sm_"] div[data-testid="stButton"] button[kind="primary"],
[class*="st-key-sm_"] div[data-testid="stButton"] button[data-testid="stBaseButton-primary"]{
  background:linear-gradient(150deg,var(--tc),color-mix(in srgb,var(--tc) 55%,#000))!important;
  border-color:rgba(255,255,255,.4)!important;
  box-shadow:0 1px 0 rgba(255,255,255,.5) inset,0 -3px 0 rgba(0,0,0,.2) inset,0 18px 32px -12px var(--tc)!important;}
[class*="st-key-sm_"] div[data-testid="stButton"] button[data-testid="stBaseButton-primary"] p{color:#fff;}
[class*="st-key-sm_"] [data-testid="stColumn"]:nth-child(6n+1) button{--tc:#0A84FF}
[class*="st-key-sm_"] [data-testid="stColumn"]:nth-child(6n+2) button{--tc:#30D158}
[class*="st-key-sm_"] [data-testid="stColumn"]:nth-child(6n+3) button{--tc:#FF9F0A}
[class*="st-key-sm_"] [data-testid="stColumn"]:nth-child(6n+4) button{--tc:#BF5AF2}
[class*="st-key-sm_"] [data-testid="stColumn"]:nth-child(6n+5) button{--tc:#64D2FF}
[class*="st-key-sm_"] [data-testid="stColumn"]:nth-child(6n+6) button{--tc:#FF453A}
@media (max-width:760px){[class*="st-key-sm_"] div[data-testid="stButton"] button{min-height:78px}
  [class*="st-key-sm_"] div[data-testid="stButton"] button p{font-size:.62rem}
  [class*="st-key-sm_"] div[data-testid="stButton"] button p::first-line{font-size:1.5rem}}
"""

PAR_LIGNE = 6


def _mise_en_forme(entree: str) -> str:
    """« 📁 Dossiers » → « 📁\\nDossiers » (l'icône sur la première ligne)."""
    icone, _, texte = entree.partition(" ")
    return f"{icone}\n{texte}" if texte else entree


def sous_menu(cle: str, entrees: list[str]) -> list[bool]:
    etat = f"sm_actif_{cle}"
    actif = st.session_state.get(etat, 0)
    if not isinstance(actif, int) or not 0 <= actif < len(entrees):
        actif = 0
    try:
        conteneur = st.container(key=f"sm_{cle}")
    except TypeError:                      # anciennes versions de Streamlit : menu sans style carré
        conteneur = st.container()
    with conteneur:
        for debut in range(0, len(entrees), PAR_LIGNE):
            groupe = entrees[debut:debut + PAR_LIGNE]
            colonnes = st.columns(PAR_LIGNE)          # même largeur de tuile sur toutes les lignes
            for k, (col, texte) in enumerate(zip(colonnes, groupe)):
                i = debut + k
                if col.button(_mise_en_forme(texte), key=f"sm_{cle}_{i}", use_container_width=True,
                              type="primary" if i == actif else "secondary"):
                    st.session_state[etat] = i
                    st.rerun()
    return [i == actif for i in range(len(entrees))]
