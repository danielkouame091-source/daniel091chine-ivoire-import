import os, tempfile
from unittest.mock import MagicMock
import sndgir_securite as S
os.environ.pop("SNDGIR_VITRINE", None); os.environ.pop("SNDGIR_PRODUCTION", None)
assert S.mode_vitrine(), "fichier .vitrine présent => vitrine"
os.environ["SNDGIR_PRODUCTION"] = "1"
assert not S.mode_vitrine(), "jamais en production"
os.environ.pop("SNDGIR_PRODUCTION")
import sndgir_erp as erp
assert erp.acces_direct_actif()
erp.DB_PATH = os.path.join(tempfile.mkdtemp(), "v.db"); erp.init_db()
assert erp.ouvrir_session_directe() and erp.st.session_state["acces_direct"]
erp.st.cache_data = lambda *a, **k: (lambda f: f)
import sndgir_vitrine as V
st = V.statistiques_code()
assert st["modules"] > 20 and st["lignes"] > 10000 and st["validations"] >= 8, st
from finai.logistique import voyages, douane
rendus = []
V.st.markdown = lambda t, *a, **k: rendus.append(t)
V.st.caption = V.st.write = V.st.info = V.st.warning = lambda *a, **k: None
V.sous_menu = lambda cle, entrees: [True] * len(entrees)          # affiche toutes les sections
V.render_showcase(voyages.entrainer, douane.entrainer, erp.lire_df, 1)
tout = " ".join(rendus)
for mot in ("Kouassi Kouame Daniel", "Chandigarh", "Error reduction", "Red-lane recall", "System architecture", "Responsible AI", "Roadmap"):
    assert mot in tout, mot
print("VITRINE OK")
