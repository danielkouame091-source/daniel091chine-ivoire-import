"""Thème visuel : cartes en relief, badges, palette corporate."""
import html

TONES = {"blue": "#3B82F6", "green": "#1F9D6B", "red": "#E5484D",
         "amber": "#F5A524", "gray": "#8A93A3"}

CSS = """
<style>
:root { --nuit:#0B1F3A; --vert:#1F9D6B; --anthracite:#2B2F36; }
html, body, [class*="css"] { font-family: 'Inter','Segoe UI',sans-serif; }
h1, h2, h3 { letter-spacing:-0.02em; }
.bv-card {
  background: linear-gradient(145deg, #12294a 0%, #0d1c34 100%);
  border: 1px solid rgba(255,255,255,0.07);
  border-left: 4px solid var(--tone, #3B82F6);
  border-radius: 14px; padding: 18px 20px; margin-bottom: 14px;
  box-shadow: 0 10px 24px rgba(0,0,0,.35), inset 0 1px 0 rgba(255,255,255,.06);
  transition: transform .18s ease, box-shadow .18s ease;
}
.bv-card:hover { transform: translateY(-3px);
  box-shadow: 0 16px 32px rgba(0,0,0,.45), inset 0 1px 0 rgba(255,255,255,.08); }
.bv-card .t { font-size:.78rem; text-transform:uppercase; letter-spacing:.08em;
  color:#9fb0c8; }
.bv-card .v { font-size:1.65rem; font-weight:700; color:#fff; margin-top:4px; }
.bv-card .s { font-size:.82rem; color:#9fb0c8; margin-top:2px; }
.bv-badge { display:inline-block; padding:2px 10px; border-radius:999px;
  font-size:.75rem; font-weight:600; color:#fff; background: var(--tone); }
div[data-testid="stSidebar"] { border-right:1px solid rgba(255,255,255,.06); }
.stButton > button { border-radius:10px; font-weight:600;
  box-shadow:0 4px 12px rgba(0,0,0,.25); }
</style>
"""


def inject_theme():
    import streamlit as st
    st.markdown(CSS, unsafe_allow_html=True)


def card_html(title, value, sub="", tone="blue") -> str:
    e = html.escape
    return (f'<div class="bv-card" style="--tone:{TONES.get(tone, TONES["blue"])}">'
            f'<div class="t">{e(str(title))}</div>'
            f'<div class="v">{e(str(value))}</div>'
            f'<div class="s">{e(str(sub))}</div></div>')


def card(title, value, sub="", tone="blue"):
    import streamlit as st
    st.markdown(card_html(title, value, sub, tone), unsafe_allow_html=True)


def badge_html(text, tone="gray") -> str:
    return (f'<span class="bv-badge" style="--tone:'
            f'{TONES.get(tone, TONES["gray"])}">{html.escape(str(text))}</span>')


def badge(text, tone="gray"):
    import streamlit as st
    st.markdown(badge_html(text, tone), unsafe_allow_html=True)
