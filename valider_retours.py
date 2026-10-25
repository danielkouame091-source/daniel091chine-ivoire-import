"""Valide les retours d'essai (python3 valider_retours.py)."""
import os, sys, tempfile
from unittest.mock import MagicMock
import pandas as pd
sys.modules.setdefault("streamlit", MagicMock())
sys.path.insert(0, ".")
import sndgir_erp as erp, sndgir_retours as r
erp.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db"); erp.init_db()
ok = lambda **k: r.enregistrer_retour(erp.connexion, 1, "admin", "Administrateur Système", **{"section": "Transit & Douanes",
    "type_retour": r.TYPES[0], "note": 4, "message": "Le bouton ne répond pas", **k})
ok(); ok(type_retour=r.TYPES[3], note=5, message="Très clair, merci"); ok(section="Comptabilité", type_retour=r.TYPES[1], note=2, message="Je ne comprends pas la balance")
for mauvais in [dict(note=0), dict(note=6), dict(message="  "), dict(message="x" * 1001), dict(section="Inconnue"), dict(type_retour="?")]:
    try: ok(**mauvais); raise SystemExit(f"KO {mauvais}")
    except ValueError: pass
df = erp.lire_df("SELECT * FROM retours_essai WHERE tenant_id=1")
assert len(df) == 3
s = r.synthese(df)
assert s["nombre"] == 3 and abs(s["note_moyenne"] - 11 / 3) < 1e-9 and s["a_traiter"] == 2
assert s["par_section"] == {"Transit & Douanes": 1, "Comptabilité": 1}
assert r.synthese(pd.DataFrame(columns=df.columns))["nombre"] == 0
assert len(erp.lire_df("SELECT * FROM retours_essai WHERE tenant_id=2")) == 0     # isolation entre entreprises
print("RETOURS OK")
