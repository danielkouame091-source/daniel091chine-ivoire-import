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
  --tc:#0A84FF;aspect-ratio:1/1;width:100%;min-height:150px;border-radius:26px!important;
  display:flex;align-items:center;justify-content:center;text-align:center;padding:8px!important;
  background:var(--glass)!important;border:1px solid var(--edge)!important;
  box-shadow:0 1px 0 rgba(255,255,255,.16) inset,0 14px 26px -12px rgba(0,0,0,.8),0 8px 20px -14px var(--tc)!important;
  backdrop-filter:blur(16px);transition:transform .22s cubic-bezier(.2,.8,.2,1),box-shadow .22s ease!important;}
[class*="st-key-sm_"] div[data-testid="stButton"] button p,[class*="st-key-sm_"] div[data-testid="stButton"] button div[data-testid="stMarkdownContainer"] p{
  display:block!important;white-space:pre-line;line-height:1.35!important;font-size:1.12rem!important;
  font-weight:800!important;color:#f5f7fa;margin:0;}
[class*="st-key-sm_"] div[data-testid="stButton"] button p::first-line{font-size:3.2rem!important;line-height:1.5!important;}
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
@media (max-width:760px){[class*="st-key-sm_"] div[data-testid="stButton"] button{min-height:110px}
  [class*="st-key-sm_"] div[data-testid="stButton"] button p{font-size:.85rem!important}
  [class*="st-key-sm_"] div[data-testid="stButton"] button p::first-line{font-size:2.2rem!important}}
"""

PAR_LIGNE = 4


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


# ───────────────────────── Barre latérale : carte de profil en relief ─────────────────────────
import html as _html

CSS_BARRE = """
/* ---------- Barre latérale professionnelle ---------- */
.sb-marque{display:flex;align-items:center;gap:12px;margin:2px 0 18px;}
.sb-logo{width:46px;height:46px;border-radius:15px;display:flex;align-items:center;justify-content:center;font-size:1.5rem;
  background:linear-gradient(145deg,#2f8cff,#5E5CE6);border:1px solid rgba(255,255,255,.35);
  box-shadow:0 1px 0 rgba(255,255,255,.5) inset,0 -3px 0 rgba(0,0,0,.22) inset,0 14px 24px -10px #0A84FF;}
.sb-nom{font-weight:800;font-size:1.02rem;line-height:1.15;color:#F5F7FA;}
.sb-version{font-size:.7rem;color:#8B95A7;letter-spacing:.06em;text-transform:uppercase;margin-top:2px;}
.sb-profil{background:var(--glass);border:1px solid var(--edge);border-radius:22px;padding:16px;margin-bottom:14px;
  box-shadow:0 1px 0 rgba(255,255,255,.14) inset,0 18px 30px -16px rgba(0,0,0,.85);backdrop-filter:blur(16px);}
.sb-ligne{display:flex;align-items:center;gap:12px;}
.sb-avatar{flex:0 0 auto;width:48px;height:48px;border-radius:50%;display:flex;align-items:center;justify-content:center;
  font-weight:800;font-size:1.05rem;color:#fff;background:linear-gradient(145deg,#30D158,#0A84FF);
  border:2px solid rgba(255,255,255,.4);box-shadow:0 10px 20px -8px #30D158;}
.sb-utilisateur{font-weight:700;font-size:.98rem;color:#F5F7FA;overflow-wrap:anywhere;}
.sb-role{display:inline-block;margin-top:4px;font-size:.68rem;font-weight:700;padding:3px 10px;border-radius:999px;
  background:rgba(94,92,230,.22);border:1px solid rgba(94,92,230,.55);color:#cfcdff;}
.sb-sep{height:1px;background:rgba(255,255,255,.08);margin:14px 0 12px;}
.sb-etiquette{font-size:.64rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:#8B95A7;margin-bottom:3px;}
.sb-entreprise{font-size:.88rem;font-weight:600;color:#e8edf6;overflow-wrap:anywhere;}
.sb-etat{display:flex;align-items:center;gap:10px;background:var(--glass);border:1px solid var(--edge);border-radius:16px;
  padding:11px 13px;margin-bottom:10px;font-size:.8rem;color:#e8edf6;}
.sb-point{flex:0 0 auto;width:10px;height:10px;border-radius:50%;}
.sb-ok{background:#30D158;box-shadow:0 0 10px #30D158;} .sb-ko{background:#FF453A;box-shadow:0 0 10px #FF453A;}
.sb-etat small{display:block;color:#8B95A7;font-size:.7rem;margin-top:1px;}
.sb-alerte{background:linear-gradient(145deg,rgba(255,159,10,.20),rgba(255,159,10,.07));border:1px solid rgba(255,159,10,.5);
  border-radius:16px;padding:11px 13px;margin-bottom:12px;font-size:.78rem;color:#ffe2b0;line-height:1.45;}
.sb-alerte b{color:#ffcf7a;} .sb-alerte span{display:inline-block;margin:4px 4px 0 0;padding:2px 9px;border-radius:999px;
  background:rgba(255,159,10,.18);border:1px solid rgba(255,159,10,.4);font-size:.7rem;}
"""


def _initiales(nom: str) -> str:
    morceaux = [m for m in str(nom).replace("_", " ").replace(".", " ").split() if m]
    if not morceaux:
        return "?"
    return (morceaux[0][0] + (morceaux[1][0] if len(morceaux) > 1 else morceaux[0][1:2])).upper()


def html_marque(nom_app: str, version: str) -> str:
    return (f'<div class="sb-marque"><div class="sb-logo">🏦</div><div><div class="sb-nom">{_html.escape(nom_app)}</div>'
            f'<div class="sb-version">Version {_html.escape(version)}</div></div></div>')


def html_profil(utilisateur: str, role: str, entreprise: str) -> str:
    return (f'<div class="sb-profil"><div class="sb-ligne"><div class="sb-avatar">{_html.escape(_initiales(utilisateur))}</div>'
            f'<div><div class="sb-utilisateur">{_html.escape(str(utilisateur))}</div>'
            f'<div class="sb-role">{_html.escape(str(role))}</div></div></div><div class="sb-sep"></div>'
            f'<div class="sb-etiquette">Entreprise</div><div class="sb-entreprise">{_html.escape(str(entreprise))}</div></div>')


def html_audit(integre: bool, nb_lignes: int) -> str:
    etat = "Piste d'audit intègre" if integre else "Piste d'audit à vérifier"
    return (f'<div class="sb-etat"><span class="sb-point {"sb-ok" if integre else "sb-ko"}"></span>'
            f'<div>{etat}<small>{int(nb_lignes)} événements enregistrés</small></div></div>')


def html_alerte_demo(comptes: list[str]) -> str:
    pastilles = "".join(f"<span>{_html.escape(str(c))}</span>" for c in comptes)
    return ('<div class="sb-alerte"><b>⚠️ Comptes de démonstration actifs</b><br>'
            f'{pastilles}<br>Changez ces mots de passe avant toute présentation : Administration → Utilisateurs.</div>')


# ───────────────────────── Mode léger (connexion lente) ─────────────────────────
CSS_LEGER = """
/* Mode léger : plus aucun effet coûteux (flou, ombres, animations) */
*,*::before,*::after{backdrop-filter:none!important;-webkit-backdrop-filter:none!important;box-shadow:none!important;
  text-shadow:none!important;transition:none!important;animation:none!important;}
"""


def mode_leger() -> bool:
    """Vrai si l'utilisateur a activé le mode léger (moins d'effets, pas de carte ni de graphiques lourds)."""
    return bool(st.session_state.get("mode_leger", False))
