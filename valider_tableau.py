import sndgir_menu as m, os, tempfile
import sndgir_erp as erp
h = m.html_kpi("💰", "<b>CA</b>", "1 000", "FCFA", "x", "vert")
assert "&lt;b&gt;" in h and "#30D158" in h and "FCFA" in h
assert "&lt;script&gt;" in m.html_bandeau("<script>", "E", "r")
assert 'class="tb-pastille vert"' in m.html_surveiller([("a", 0, "rouge")]) and 'rouge"' in m.html_surveiller([("a", 2, "rouge")])
assert m.html_grille(["<i>a</i>"]).count("tb-grille") == 1
assert "tb-kpi" in m.CSS_TABLEAU and "CSS_TABLEAU" in open("sndgir_erp.py").read()
erp.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db"); erp.init_db()
erp.st.session_state.update({"tenant_id": 1, "username": "admin", "user_role": "Administrateur Système"})
from unittest.mock import MagicMock
erp.st.columns = lambda n, *a, **k: [MagicMock() for _ in range(n if isinstance(n, int) else len(n))]
rendus = []
erp.st.markdown = lambda t, *a, **k: rendus.append(t)
erp.onglet_tableau_de_bord()
tout = " ".join(rendus)
assert "Bonjour admin" in tout and tout.count('class="tb-kpi"') == 4 and "À surveiller" in tout
print("TABLEAU OK")
