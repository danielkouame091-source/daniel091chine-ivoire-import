"""Fait défiler TOUS les écrans de l'ERP avec un Streamlit simulé, en anglais, et signale :
  - toute erreur (exception) dans un écran ;
  - tout texte resté en français (hors données de l'utilisateur).
Usage : python3 valider_ecrans.py [--rapport]"""
import datetime, os, re, sys, tempfile, types
import pandas as pd

TEXTES, ERREURS = [], []
class Arret(Exception): pass

class Etat(dict):
    pass

def _texte(nom, valeur):
    if isinstance(valeur, str) and valeur.strip(): TEXTES.append((nom, valeur))

class DG:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def __getattr__(self, nom):                     # tout le reste : sans effet
        if nom.startswith("__"): raise AttributeError(nom)
        return lambda *a, **k: None
    # --- textes
    def _t(nom):
        def f(self, body="", *a, **k): _texte(nom, body); return None
        return f
    markdown = _t("markdown"); caption = _t("caption"); text = _t("text"); header = _t("header"); subheader = _t("subheader")
    title = _t("title"); info = _t("info"); warning = _t("warning"); error = _t("error"); success = _t("success"); toast = _t("toast")
    def write(self, *args, **k):
        for a in args:
            if isinstance(a, str): _texte("write", a)
            elif isinstance(a, pd.DataFrame): self.dataframe(a)
    def code(self, body="", *a, **k): return None
    # --- boutons
    def button(self, label, *a, **k): _texte("button", label); _texte("help", k.get("help")); return False
    def form_submit_button(self, label="Submit", *a, **k): _texte("button", label); return False
    def download_button(self, label, *a, **k): _texte("button", label); return False
    def link_button(self, label, *a, **k): _texte("button", label); return False
    # --- saisies
    def text_input(self, label, value="", *a, **k): _texte("label", label); _texte("help", k.get("help")); _texte("placeholder", k.get("placeholder")); return value
    text_area = text_input
    def number_input(self, label, min_value=None, max_value=None, value=None, *a, **k):
        _texte("label", label); _texte("help", k.get("help"))
        return value if value is not None else (min_value if min_value is not None else 0.0)
    def selectbox(self, label, options, index=0, format_func=str, *a, **k):
        _texte("label", label); opts = list(options)
        for o in opts: _texte("option", format_func(o))
        return opts[index] if opts and index is not None else None
    def radio(self, label, options, index=0, format_func=str, *a, **k): return self.selectbox(label, options, index, format_func)
    def multiselect(self, label, options, default=None, format_func=str, *a, **k):
        _texte("label", label)
        for o in list(options): _texte("option", format_func(o))
        return list(default or [])
    def checkbox(self, label, value=False, *a, **k): _texte("label", label); _texte("help", k.get("help")); return value
    toggle = checkbox
    def slider(self, label, min_value=None, max_value=None, value=None, *a, **k): _texte("label", label); _texte("help", k.get("help")); return value if value is not None else min_value
    def select_slider(self, label, options=(), value=None, format_func=str, *a, **k): _texte("label", label); return value if value is not None else list(options)[0]
    def date_input(self, label, value=None, *a, **k): _texte("label", label); return value or datetime.date.today()
    def time_input(self, label, *a, **k): _texte("label", label); return datetime.time(12, 0)
    def file_uploader(self, label, *a, **k): _texte("label", label); return None
    # --- données
    def metric(self, label, value=None, delta=None, *a, **k): _texte("metric", label); _texte("metric_delta", delta)
    def dataframe(self, data=None, *a, **k):
        if isinstance(data, pd.DataFrame):
            for c in data.columns: _texte("colonne", c)
            for c in data.columns:
                if data[c].dtype == object or pd.api.types.is_string_dtype(data[c]):
                    for v in list(data[c].dropna().unique())[:200]: _texte("cellule", v)
    table = dataframe
    def data_editor(self, data=None, *a, **k): self.dataframe(data); return data
    def plotly_chart(self, fig, *a, **k):
        try:
            _texte("graphique", fig.layout.title.text); _texte("axe", fig.layout.xaxis.title.text); _texte("axe", fig.layout.yaxis.title.text)
        except Exception: pass
    def _graph(self, data=None, *a, **k):
        if isinstance(data, pd.DataFrame):
            for c in data.columns: _texte("serie", c)
    bar_chart = line_chart = area_chart = _graph
    # --- structure
    def columns(self, spec, *a, **k): return [DG() for _ in range(spec if isinstance(spec, int) else len(spec))]
    def container(self, *a, **k): return DG()
    def expander(self, label="", *a, **k): _texte("expander", label); return DG()
    def popover(self, label="", *a, **k): _texte("expander", label); return DG()
    def form(self, *a, **k): return DG()
    def spinner(self, text="", *a, **k): _texte("spinner", text); return DG()
    def status(self, label="", *a, **k): _texte("spinner", label); return DG()
    def tabs(self, tabs): 
        for t in tabs: _texte("onglet", t)
        return [DG() for _ in tabs]
    def progress(self, *a, **k): return DG()
    def empty(self, *a, **k): return DG()

dg = types.ModuleType("streamlit.delta_generator"); dg.DeltaGenerator = DG
st = types.ModuleType("streamlit"); st.delta_generator = dg
_main = DG()
for nom in dir(DG):
    if not nom.startswith("_"): setattr(st, nom, getattr(_main, nom))
st.sidebar = DG(); st.session_state = Etat(); st.secrets = {}; st.query_params = {}
st.context = types.SimpleNamespace(headers={})
def _cache(*a, **k):
    if len(a) == 1 and callable(a[0]) and not k: return a[0]
    return lambda f: f
st.cache_resource = st.cache_data = st.fragment = _cache
def _rerun(*a, **k): return None
st.rerun = _rerun
def _stop(): raise Arret()
st.stop = _stop
st.set_page_config = lambda *a, **k: None
sys.modules["streamlit"] = st; sys.modules["streamlit.delta_generator"] = dg
sys.path.insert(0, ".")

import sndgir_menu, sndgir_erp as erp
REGISTRE = {}
_orig = sndgir_menu.sous_menu
def _suivi(cle, entrees):
    REGISTRE[cle] = list(entrees); return _orig(cle, entrees)
sndgir_menu.sous_menu = _suivi
for mod in list(sys.modules.values()):
    if getattr(mod, "sous_menu", None) is _orig: mod.sous_menu = _suivi
erp.DB_PATH = os.path.join(tempfile.mkdtemp(), "ecrans.db")

def lancer(titre):
    try:
        erp.main()
    except Arret:
        pass
    except Exception as exc:
        import traceback
        ERREURS.append((titre, "".join(traceback.format_exception_only(type(exc), exc)).strip() + " @ " + traceback.format_tb(exc.__traceback__)[-1].strip().splitlines()[0]))

FR = re.compile(r"[àâçéèêëîïôûùüÿœÉÈÀ]|\b(le|la|les|des|du|pour|sur|avec|dans|votre|vous|dossier|dossiers|aucun|aucune|créer|enregistrer|client|montant|statut|ajouter|supprimer|télécharger)\b", re.I)
AUTORISES = re.compile(r"Côte d'Ivoire|Cabinet|SARL|IvoirTech|Groupe|Bâtir|Abidjan|Kouassi|Kouame|Éléments|BAE|SYSCOHADA|DGI|UEMOA", re.I)

def passer(langue):
    st.session_state.clear(); st.session_state["langue"] = langue
    TEXTES.clear(); ERREURS.clear(); REGISTRE.clear()
    lancer("accueil")
    pages = 9
    for p in range(pages):
        st.session_state["page_active"] = p
        REGISTRE.clear(); lancer(f"page {p}")
        for cle, entrees in list(REGISTRE.items()):
            for i in range(1, len(entrees)):
                st.session_state[f"sm_actif_{cle}"] = i
                lancer(f"page {p} / {cle} / {entrees[i]}")
            st.session_state[f"sm_actif_{cle}"] = 0
    return list(TEXTES), list(ERREURS)

if __name__ == "__main__":
    textes, erreurs = passer("en")
    uniques = {}
    for nom, t in textes:
        if FR.search(t) and not AUTORISES.search(t):
            uniques.setdefault(t, nom)
    rapport = "--rapport" in sys.argv
    print(f"{len(textes)} textes affichés, {len(uniques)} encore en français, {len(erreurs)} erreur(s)")
    for t, n in sorted(uniques.items()):
        if rapport: print(f"  [{n}] {t[:140]!r}")
    for e in erreurs: print("  ERREUR", e)
    if erreurs: sys.exit(1)
