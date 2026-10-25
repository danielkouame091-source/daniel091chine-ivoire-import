"""Valide les modèles d'IA logistique et l'onglet qui les affiche (python3 valider_logistique.py)."""
import os, sys, tempfile, types
import numpy as np, pandas as pd
sys.path.insert(0, ".")
from finai.logistique import voyages as v, douane as d

# ── Voyages ──
df = v.generer_voyages(); assert len(df) == 3000 and df.retard_jours.min() >= -2
assert 0.2 < (df.retard_jours > 3).mean() < 0.5
assert (df.delai_prevu_jours > 0).all()
m = v.entrainer(df)
base, ridge, gb = (m.metriques[k]["mae_jours"] for k in ("Référence (retard moyen)", "Régression Ridge", "Gradient boosting"))
assert ridge < base * 0.85 and gb < base * 0.85, (base, ridge, gb)
assert m.metriques["_classification"]["auc_retard_plus_3j"] > 0.7
lent = m.predire("Shanghai (Chine)", "Ligne E", 1, 2, 0.9); sur = m.predire("Rotterdam (Pays-Bas)", "Ligne D", 6, 0, 0.1)
assert lent["retard_jours"] > sur["retard_jours"] + 3
assert lent["intervalle"][0] < lent["retard_jours"] < lent["intervalle"][1]
for mauvais in [("Atlantide", "Ligne A", 1, 0, .5), ("Shanghai (Chine)", "Ligne A", 13, 0, .5), ("Shanghai (Chine)", "Ligne A", 1, 0, 1.5)]:
    try: m.predire(*mauvais); raise SystemExit("KO validation")
    except ValueError: pass
assert v.haversine_km(v.ORIGINES["Shanghai (Chine)"], v.DESTINATION) > 12000

# ── Douane ──
dd = d.generer_dossiers(); fr = dd.canal.value_counts(normalize=True)
assert abs(fr["vert"] - 0.62) < 0.02 and abs(fr["rouge"] - 0.10) < 0.02
mc = d.entrainer(dd)
ref = mc.metriques["Référence (toujours « vert »)"]; lg = mc.metriques["Régression logistique"]
assert lg["f1_macro"] > ref["f1_macro"] + 0.15 and lg["rappel_rouge"] > 0.4 and ref["rappel_rouge"] == 0
risque = mc.predire(dict(chapitre="87", valeur_caf=9e7, ecart_prix=-0.6, nb_dossiers_importateur=0, taux_anomalies=0, origine="Chine", regime="C100"))
sain = mc.predire(dict(chapitre="39", valeur_caf=2e6, ecart_prix=0.05, nb_dossiers_importateur=40, taux_anomalies=0, origine="Union européenne", regime="C100"))
assert risque["probabilites"]["rouge"] > 0.5 > sain["probabilites"]["rouge"] and sain["canal_probable"] == "vert"
assert abs(sum(risque["probabilites"].values()) - 1) < 1e-6 and risque["raisons"] and not sain["raisons"]
try: mc.predire(dict(chapitre="87", valeur_caf=-1, ecart_prix=0, nb_dossiers_importateur=0, taux_anomalies=0, origine="Chine", regime="C100")); raise SystemExit("KO")
except ValueError: pass
assert mc.predire(dict(chapitre="ZZ", valeur_caf=1e6, ecart_prix=0, nb_dossiers_importateur=3, taux_anomalies=0, origine="Autre", regime="C200"))["canal_probable"] in d.CANAUX

# ── Onglet avec un faux Streamlit (valeurs par défaut) ──
class Faux:
    def __getattr__(self, nom): return lambda *a, **k: None
def cols(n, *a, **k): return [FauxSt() for _ in range(n if isinstance(n, int) else len(n))]
class FauxSt:
    journal = []
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def columns(self, n, *a, **k): return cols(n)
    def tabs(self, noms): return [FauxSt() for _ in noms]
    def selectbox(self, label, options, index=0, **k): return options[index]
    def slider(self, label, a, b, value=None, *x, **k): return value
    def number_input(self, label, a=None, b=None, value=None, **k): return value if value is not None else (b if b is not None and a is not None and not isinstance(b, (int,float)) else a)
    def text_input(self, label, value="", **k): return value
    def cache_resource(self, *a, **k): return (lambda f: f) if not (a and callable(a[0])) else a[0]
    def metric(self, label, value, delta=None, **k): FauxSt.journal.append((label, value))
    def __getattr__(self, nom):
        return lambda *a, **k: FauxSt.journal.append((nom, a[0] if a else None))
fs = FauxSt(); mod = types.ModuleType("streamlit")
mod.__dict__.update({n: getattr(fs, n) for n in ("columns", "tabs", "selectbox", "slider", "number_input", "text_input", "cache_resource", "metric")})
mod.__getattr__ = lambda nom: (lambda *a, **k: FauxSt.journal.append((nom, a[0] if a else None)))
sys.modules["streamlit"] = mod
import sndgir_logistique as L
import sndgir_suivi
for nom, coord in v.ORIGINES.items():
    assert sndgir_suivi.PORTS[nom] == coord, nom          # cohérence avec l'ERP
import sndgir_erp as erp
erp.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db"); erp.init_db()
with erp.connexion() as c:
    c.execute("INSERT INTO expeditions (tenant_id, dossier_ref, origine, destination, dest_lat, dest_lon) VALUES (1,'IMP-1','Shanghai (Chine)','Abidjan',5.26,-4.0)")
    c.execute("INSERT INTO dossiers (tenant_id, reference, date, client, code_sh, valeur_caf_xof, quantite, article) VALUES (1,'IMP-1','2026-01-01','Client A','8517',9000000,100,'Téléphones')")
FauxSt.journal.clear()
L.render_ia_logistique(erp.lire_df, 1)
etiq = [x[0] for x in FauxSt.journal]
assert any("Durée annoncée" in str(e) for e in etiq) and any("Voie" in str(e) for e in etiq), etiq
assert not any(e == "error" for e in etiq), FauxSt.journal
print("IA LOGISTIQUE OK")
