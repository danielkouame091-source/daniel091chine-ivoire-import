import sys; sys.path.insert(0,'.')
from unittest.mock import MagicMock
sys.modules["streamlit"]=MagicMock()
import sndgir_menu as m
h=m.html_profil('<script>x</script>','Administrateur Système','Cabinet "A" & Co'); assert '<script>' not in h and '&lt;script&gt;' in h and '&amp;' in h
assert m._initiales('admin')=='AD' and m._initiales('jean.kouame')=='JK' and m._initiales('')=='?'
assert 'sb-ok' in m.html_audit(True,76) and 'sb-ko' in m.html_audit(False,3) and '76' in m.html_audit(True,76)
a=m.html_alerte_demo(['admin','<b>x</b>']); assert '&lt;b&gt;' in a and 'admin' in a
assert 'Version 1.0.0' in m.html_marque('SNDGIR','1.0.0')
for f in (m.html_marque('a','1'),h,m.html_audit(True,1),a): assert '\n    ' not in f   # pas de bloc de code Markdown
print("BARRE OK")
