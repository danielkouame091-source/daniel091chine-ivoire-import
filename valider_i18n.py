"""Contrôles de la traduction English / Français (moteur + dictionnaire + branchement sur Streamlit simulé)."""
import re, sys, types
import pandas as pd

# ── faux Streamlit qui enregistre ce qu'on lui envoie ──
rec = []
st = types.ModuleType("streamlit"); st.session_state = {"langue": "en"}
dg_mod = types.ModuleType("streamlit.delta_generator")
class DeltaGenerator:                               # même rôle que la vraie classe : colonnes, barre latérale…
    def markdown(self, body, unsafe_allow_html=False, help=None): rec.append(("dg.markdown", body))
    def button(self, label, key=None, help=None, **k): rec.append(("dg.button", label, help)); return False
    def selectbox(self, label, options, index=0, format_func=str, key=None, **k):
        rec.append(("dg.selectbox", label, [format_func(o) for o in options])); return options[index]
    def metric(self, label, value, delta=None, **k): rec.append(("dg.metric", label, value, delta))
    def dataframe(self, data, **k): rec.append(("dg.dataframe", data))
    def tabs(self, tabs): rec.append(("dg.tabs", list(tabs))); return tabs
    def plotly_chart(self, fig, **k): rec.append(("dg.plotly", fig))
dg_mod.DeltaGenerator = DeltaGenerator
_main = DeltaGenerator()
for n in ("markdown", "button", "selectbox", "metric", "dataframe", "tabs", "plotly_chart"):
    setattr(st, n, getattr(_main, n))                # comme dans streamlit/__init__.py : méthodes liées
for n in ("caption", "text", "header", "subheader", "title", "info", "warning", "error", "success"):
    setattr(st, n, (lambda nom: lambda body, **k: rec.append((nom, body)))(n))
st.delta_generator = dg_mod
sys.modules["streamlit"] = st; sys.modules["streamlit.delta_generator"] = dg_mod
sys.path.insert(0, ".")
import sndgir_i18n as I
import i18n_en

I.installer(); I.installer()                         # idempotent

def dernier(): return rec[-1]
# 1. traductions de base
st.subheader("📊 Tableau de bord financier");           assert dernier()[1] == "📊 Financial dashboard", dernier()
st.error("Aucun dossier enregistré.");                 assert dernier()[1] == "No file recorded."
st.markdown("Tableau\nde bord");                       assert dernier()[1] == "Dashboard", dernier()
# 2. f-strings : motif + valeurs conservées + groupes traduits
st.success("Dossier IMP-1 créé — total facture 1 000 FCFA.")
assert "created" in dernier()[1] and "IMP-1" in dernier()[1] and "1 000" in dernier()[1], dernier()
st.info("3 dossier(s) · 2 en cours");                   assert dernier()[1] == "3 file(s) · 2 in progress", dernier()
# 3. langue française : rien ne change
st.session_state["langue"] = "fr"; st.subheader("📊 Tableau de bord financier"); assert dernier()[1] == "📊 Tableau de bord financier"
st.session_state["langue"] = "en"
# 4. une chaîne inconnue reste intacte, jamais d'erreur
st.markdown("Texte que personne n'a traduit xyz 123"); assert dernier()[1] == "Texte que personne n'a traduit xyz 123"
# 5. HTML préservé (balises et valeurs)
st.markdown('<div class="sb-profil"><div class="sb-ligne"><div class="sb-avatar">AD</div><div><div class="sb-utilisateur">admin</div><div class="sb-role">Administrateur Système</div></div></div><div class="sb-sep"></div><div class="sb-etiquette">Entreprise</div><div class="sb-entreprise">Cabinet X</div></div>')
h = dernier()[1]; assert "Company" in h and "System Administrator" in h and "AD" in h and "Cabinet X" in h and 'class="sb-avatar"' in h, h
# 6. widgets : libellé + aide traduits
_main.button("Créer le dossier", help="Mode léger (connexion lente)")
assert dernier()[1] == "Create the file" and dernier()[2] == "Light mode (slow connection)"
# 7. listes : on traduit l'AFFICHAGE, la valeur choisie reste française
choix = _main.selectbox("Régime", ["En cours", "Livré au Client"])
assert choix == "En cours" and dernier()[1] == "Regime" and dernier()[2] == ["In progress", "Delivered to client"], dernier()
choix = st.selectbox("x", [1, 2, 3], format_func=lambda n: f"n°{n}"); assert dernier()[2] == ["n°1", "n°2", "n°3"]
# 8. tableaux : en-têtes de la base + valeurs ; l'original n'est pas modifié
df = pd.DataFrame({"reference": ["IMP-1"], "valeur_caf_xof": [100.0], "statut": ["En cours"], "canal_risque": ["ROUGE"], "client": ["SARL Truc"]})
st.dataframe(df)
out = dernier()[1]
assert list(out.columns) == ["Reference", "CIF value XOF", "Status", "Risk lane", "Client"], list(out.columns)
assert out["Status"][0] == "In progress" and out["Risk lane"][0] == "RED" and out["Client"][0] == "SARL Truc"
assert list(df.columns)[0] == "reference" and df["statut"][0] == "En cours"
# 9. métriques, onglets
_main.metric("Résultat net", "1 000", delta="bénéfice"); assert dernier()[1:] == ("Net result", "1 000", "profit"), dernier()
_main.tabs(["Dossiers", "Balance générale"]); assert dernier()[1] == ["Files", "Trial balance"], dernier()
# 10. graphique Plotly simulé
class Obj:
    def __init__(s, **k): s.__dict__.update(k)
class Fig:
    def __init__(s): s.layout = Obj(title=Obj(text="Montant par statut"), xaxis=Obj(title=Obj(text="statut")), yaxis=Obj(title=Obj(text="montant")), legend=Obj(title=Obj(text=None))); s.data = [Obj(name="Montant", x=["En cours", "Livré au Client"])]
    def update_layout(s, **k):
        if "title_text" in k: s.layout.title.text = k["title_text"]
f = Fig(); st.plotly_chart(f)
assert f.layout.title.text == "Amount by status" and f.layout.xaxis.title.text == "Status" and f.data[0].x == ["In progress", "Delivered to client"], (f.layout.title.text, f.data[0].x)
# 10b. graphiques simples
g = I.trad_graphique(pd.Series({"Transit & Douanes": 2, "Comptabilité": 1}, name="avis"))
assert list(g.index) == ["Transit & Customs", "Accounting"] and list(g.columns) == ["avis"] or list(g.columns) == [I.nom_colonne("avis")], (list(g.index), list(g.columns))
# 11. dictionnaire : cohérence interne
for cle, modele in i18n_en.PATTERNS:
    assert sorted(set(re.findall(r"\{(\d+)\}", cle))) == sorted(set(re.findall(r"\{(\d+)\}", modele))), cle[:50]
assert len(i18n_en.EXACT) > 900 and len(i18n_en.PATTERNS) > 100
# 12. aucune traduction ne doit laisser de lettres accentuées françaises évidentes dans les libellés courts
rest = [(k, v) for k, v in i18n_en.EXACT.items() if re.search(r"[àâéèêëîïôûùçœ]", v) and len(v) < 60 and "Côte" not in v and "Bâtir" not in v and "Pédro" not in v and "Néerl" not in v]
assert not rest, rest[:5]
# 13. PDF : Paragraph est traduit
try:
    from reportlab.platypus import Paragraph
    from reportlab.lib.styles import getSampleStyleSheet
    p = Paragraph("<b>Date d'émission :</b> 01/01/2026", getSampleStyleSheet()["Normal"])
    assert "Issue date" in p.text, p.text
except ImportError:
    pass
print("I18N OK")
