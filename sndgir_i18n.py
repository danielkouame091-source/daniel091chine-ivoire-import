"""Traduction de l'interface (français ↔ anglais), faite à l'affichage uniquement.

Principe : le code et la base de données restent en français (statuts, rôles, requêtes…). Quand la langue est
« en », chaque texte envoyé à Streamlit (titres, boutons, libellés, tableaux, graphiques, PDF) passe d'abord par
`T()`, qui cherche la traduction dans `i18n_en.py`. Rien de ce que l'utilisateur tape ni de ce qui est stocké
n'est modifié : une valeur choisie dans une liste reste la valeur d'origine, seul son affichage change.

Si un texte n'a pas de traduction, il est affiché tel quel (jamais d'erreur).
"""
from __future__ import annotations

import functools
import re

import streamlit as st

try:
    from i18n_en import COLONNES, EXACT, PATTERNS
except Exception:                       # le dictionnaire manque : l'application reste en français
    EXACT, PATTERNS, COLONNES = {}, [], {}

# Compléments : tuiles à plusieurs lignes et libellés ajoutés après la génération du dictionnaire.
EXACT.update({
    "Analyse\nfinancière IA": "AI financial\nanalysis",
    "Portail\nclient": "Client\nportal",
    "États-Unis — US GAAP (ASC)": "United States — US GAAP (ASC)",
})

LANGUES = {"en": "🌐 English", "fr": "🇫🇷 Français"}
_MARQUE = "_sndgir_i18n_installe"

# ── Moteur de traduction ─────────────────────────────────────────────────────
_CHAMP = re.compile(r"\{(\d+)\}")


def _compiler(cle: str, modele: str):
    morceaux = _CHAMP.split(cle)                     # littéral, n°, littéral, n°, …
    expr = "".join(re.escape(p) if i % 2 == 0 else "(.*?)" for i, p in enumerate(morceaux))
    nb_lettres = sum(len(re.findall(r"[A-Za-zÀ-ÿ]", p)) for p in morceaux[::2])
    return nb_lettres, re.compile("^" + expr + "$", re.S), modele


_MOTIFS = sorted((_compiler(c, m) for c, m in PATTERNS), key=lambda x: -x[0])
_MOTIFS = [(r, m) for n, r, m in _MOTIFS if n >= 4]            # pas de motif réduit à « {0} »
_LONGS = sorted((c for c in EXACT if len(c) >= 12 and "\n" not in c), key=len, reverse=True)
_SOUS = re.compile("|".join(re.escape(c) for c in _LONGS)) if _LONGS else None
_cache: dict[str, str] = {}


def langue() -> str:
    try:
        return st.session_state.get("langue", "fr")
    except Exception:
        return "fr"


def _traduire(texte: str, profondeur: int = 0) -> str:
    if texte in EXACT:
        return EXACT[texte]
    coeur = texte.strip()
    if coeur and coeur != texte and coeur in EXACT:                         # espaces autour
        i = texte.index(coeur)
        return texte[:i] + EXACT[coeur] + texte[i + len(coeur):]
    if profondeur < 3:
        for regex, modele in _MOTIFS:
            m = regex.match(texte)
            if m:
                groupes = [_traduire(g, profondeur + 1) if g else g for g in m.groups()]
                return _CHAMP.sub(lambda x: groupes[int(x.group(1))], modele)
        m = re.match(r"^(\S+)\n(.+)$", texte, re.S)                          # tuile « icône\nlibellé » : on cherche « icône libellé »
        if m:
            complet = EXACT.get(f"{m.group(1)} {m.group(2)}")
            if complet:
                icone, _, reste = complet.partition(" ")
                return f"{icone}\n{reste}"
        m2 = re.match(r"^(\S+)\n(.+\n.+)$", texte, re.S)                       # tuile « icône\nmot\nmot »
        if m2 and m2.group(2) in EXACT:
            return f"{m2.group(1)}\n{EXACT[m2.group(2)]}"
        if "\n" in texte:                                                   # listes, textes sur plusieurs lignes
            lignes = [_traduire(l, profondeur + 1) if l.strip() else l for l in texte.split("\n")]
            if lignes != texte.split("\n"):
                return "\n".join(lignes)
    if _SOUS is not None:                                                   # morceaux connus dans une phrase assemblée
        return _SOUS.sub(lambda m: EXACT[m.group(0)], texte)
    return texte


def T(texte):
    """Traduit un texte si la langue est l'anglais ; sinon (ou si inconnu) le renvoie tel quel."""
    if not isinstance(texte, str) or not texte.strip() or langue() != "en":
        return texte
    r = _cache.get(texte)
    if r is None:
        try:
            r = _traduire(texte)
        except Exception:
            r = texte
        if len(_cache) < 30000:
            _cache[texte] = r
    return r


_ACRONYMES = {"xof": "XOF", "cif": "CIF", "fob": "FOB", "hs": "HS", "vat": "VAT", "ncc": "NCC", "fne": "FNE", "usd": "USD",
              "sha256": "SHA-256", "id": "ID", "ip": "IP", "pct": "%", "guce": "GUCE", "dd": "DD", "no": "no.", "ref": "ref."}
_SPECIAL = {"bl": "B/L", "dd": "Duty %", "sh": "HS", "email": "E-mail", "ts": "Time", "ip": "IP"}


def _joli(nom_anglais: str) -> str:
    if nom_anglais in _SPECIAL:
        return _SPECIAL[nom_anglais]
    mots = [_ACRONYMES.get(m, m) for m in nom_anglais.split("_")]
    s = " ".join(mots)
    return s[:1].upper() + s[1:]


def nom_colonne(nom) -> str:
    """Nom de colonne affiché (colonnes de la base ou intitulés français)."""
    if not isinstance(nom, str):
        return nom
    if nom in COLONNES:
        return _joli(COLONNES[nom])
    t = T(nom)
    return t


def trad_df(df):
    """Copie d'un tableau avec en-têtes et textes traduits (pour l'affichage uniquement)."""
    import pandas as pd
    if langue() != "en" or not isinstance(df, pd.DataFrame) or df.shape[1] > 80 or len(df) > 20000:
        return df
    try:
        d = df.copy()
        nouveaux, vus = [], set()
        for c in d.columns:
            n = nom_colonne(c) if isinstance(c, str) else c
            nouveaux.append(n if n not in vus else c)
            vus.add(nouveaux[-1])
        for i, c in enumerate(d.columns):
            col = d.iloc[:, i]
            if col.dtype == object or pd.api.types.is_string_dtype(col):
                uniques = [v for v in col.dropna().unique() if isinstance(v, str)][:3000]
                carte = {v: T(v) for v in uniques}
                if any(k != v for k, v in carte.items()):
                    d.isetitem(i, col.map(lambda v: carte.get(v, v) if isinstance(v, str) else v))
        d.columns = nouveaux
        return d
    except Exception:
        return df


def trad_graphique(donnees):
    """Séries et catégories d'un graphique simple de Streamlit (barres, lignes)."""
    import pandas as pd
    try:
        if isinstance(donnees, pd.Series):
            donnees = donnees.to_frame()
        if isinstance(donnees, pd.DataFrame):
            d = donnees.copy()
            d.columns = [nom_colonne(c) if isinstance(c, str) else c for c in d.columns]
            if d.index.dtype == object:
                d.index = [T(v) if isinstance(v, str) else v for v in d.index]
            return d
    except Exception:
        pass
    return donnees


def trad_fig(fig):
    """Titres, axes, légendes et libellés d'un graphique Plotly."""
    if langue() != "en":
        return fig
    try:
        lay = fig.layout
        if lay.title and lay.title.text:
            fig.update_layout(title_text=T(lay.title.text))
        for ax in ("xaxis", "yaxis"):
            a = getattr(lay, ax, None)
            if a is not None and a.title and a.title.text:
                a.title.text = nom_colonne(a.title.text)
        if lay.legend and lay.legend.title and lay.legend.title.text:
            fig.update_layout(legend_title_text=nom_colonne(lay.legend.title.text))
        for tr in fig.data:
            if getattr(tr, "name", None):
                tr.name = T(tr.name)
            for attr in ("x", "labels"):
                vals = getattr(tr, attr, None)
                if vals is not None and len(vals) and isinstance(vals[0], str):
                    setattr(tr, attr, [T(v) for v in vals])
    except Exception:
        pass
    return fig


# ── Branchement sur Streamlit ────────────────────────────────────────────────
_TEXTE0 = ("markdown", "caption", "text", "header", "subheader", "title", "info", "warning", "error", "success",
           "toast", "spinner", "write", "expander", "popover", "status")
_LABEL0 = ("button", "form_submit_button", "download_button", "link_button", "text_input", "text_area", "number_input",
           "selectbox", "multiselect", "radio", "checkbox", "toggle", "slider", "select_slider", "date_input",
           "time_input", "file_uploader", "metric", "segmented_control", "pills", "camera_input", "color_picker")
_AVEC_OPTIONS = ("selectbox", "multiselect", "radio", "select_slider", "pills", "segmented_control")
_KW_TEXTE = ("label", "body", "help", "placeholder", "caption", "text", "delta", "description")


def _format_func(ff):
    base = ff if callable(ff) else str
    return lambda x: T(str(base(x)))


def _adapter(nom: str, args: tuple, kw: dict):
    args = list(args)
    if nom == "write":
        args = [T(a) if isinstance(a, str) else (trad_df(a) if _est_df(a) else a) for a in args]
        return args, kw
    if nom == "tabs":
        if args and isinstance(args[0], (list, tuple)):
            args[0] = [T(x) for x in args[0]]
        return args, kw
    if nom in ("dataframe", "table"):
        if args and _est_df(args[0]):
            args[0] = trad_df(args[0])
        elif "data" in kw and _est_df(kw["data"]):
            kw["data"] = trad_df(kw["data"])
        return args, kw
    if nom in ("bar_chart", "line_chart", "area_chart"):
        if args:
            args[0] = trad_graphique(args[0])
        return args, kw
    if nom == "plotly_chart":
        if args:
            args[0] = trad_fig(args[0])
        return args, kw
    if args and isinstance(args[0], str):
        args[0] = T(args[0])
    for k in _KW_TEXTE:
        if isinstance(kw.get(k), str):
            kw[k] = T(kw[k])
    if nom == "metric":
        for i in (1, 2):
            if len(args) > i and isinstance(args[i], str):
                args[i] = T(args[i])
        if isinstance(kw.get("value"), str):
            kw["value"] = T(kw["value"])
    if nom in _AVEC_OPTIONS:
        if len(args) > 3 and callable(args[3]):
            args[3] = _format_func(args[3])
        elif len(args) <= 3:
            kw["format_func"] = _format_func(kw.get("format_func"))
    return args, kw


def _est_df(x) -> bool:
    return type(x).__module__.startswith("pandas") and type(x).__name__ == "DataFrame"


def _envelopper(orig, nom: str, methode: bool = False):
    """`methode=True` : fonction de classe (le premier argument est `self`, qu'on ne touche pas)."""
    @functools.wraps(orig)
    def traduit(*args, **kw):
        if langue() == "en":
            try:
                if methode and args:
                    reste, kw = _adapter(nom, args[1:], dict(kw))
                    args = (args[0], *reste)
                elif not methode:
                    args, kw = _adapter(nom, args, dict(kw))
            except Exception:
                pass
        return orig(*args, **kw)
    traduit._sndgir_i18n = True
    return traduit


def installer() -> None:
    """Branche la traduction sur Streamlit (une seule fois par processus)."""
    if getattr(st, _MARQUE, False):
        return
    try:
        from streamlit.delta_generator import DeltaGenerator
    except Exception:
        DeltaGenerator = None
    noms = set(_TEXTE0) | set(_LABEL0) | {"tabs", "dataframe", "table", "plotly_chart", "bar_chart", "line_chart", "area_chart"}
    for nom in noms:
        if DeltaGenerator is not None:
            f = getattr(DeltaGenerator, nom, None)
            if callable(f) and not getattr(f, "_sndgir_i18n", False):
                try:
                    setattr(DeltaGenerator, nom, _envelopper(f, nom, methode=True))
                except Exception:
                    pass
        g = getattr(st, nom, None)
        if callable(g) and not getattr(g, "_sndgir_i18n", False):
            try:
                setattr(st, nom, _envelopper(g, nom))
            except Exception:
                pass
    _installer_pdf()
    try:
        setattr(st, _MARQUE, True)
    except Exception:
        pass


def _installer_pdf() -> None:
    """Les textes des PDF (reportlab) suivent la langue choisie au moment de leur création."""
    try:
        from reportlab.platypus import Paragraph
    except Exception:
        return
    if getattr(Paragraph.__init__, "_sndgir_i18n", False):
        return
    orig = Paragraph.__init__

    @functools.wraps(orig)
    def init(self, text, *a, **k):
        if langue() == "en" and isinstance(text, str):
            text = T(text)
        orig(self, text, *a, **k)
    init._sndgir_i18n = True
    Paragraph.__init__ = init


def selecteur_langue(conteneur=None, cle: str = "langue_choix") -> None:
    """Sélecteur English / Français (le choix est gardé dans st.session_state["langue"])."""
    cible = conteneur if conteneur is not None else st
    actuel = st.session_state.get("langue", "fr")
    options = list(LANGUES)
    choix = cible.radio("🌐", options, index=options.index(actuel) if actuel in options else 0,
                        format_func=lambda c: LANGUES[c], horizontal=True, key=cle, label_visibility="collapsed")
    if choix != actuel:
        st.session_state["langue"] = choix
        st.rerun()
