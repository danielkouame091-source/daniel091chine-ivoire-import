"""Valide le mode léger (python3 valider_leger.py)."""
import sys
from unittest.mock import MagicMock
import pandas as pd
st = MagicMock(); st.session_state = {}
sys.modules["streamlit"] = st
sys.path.insert(0, ".")
import sndgir_erp as erp, sndgir_menu as m
df = pd.DataFrame({"x": ["a", "b"], "y": [1, 2]})
assert m.mode_leger() is False
erp.PLOTLY_OK = True; erp.px = MagicMock()
erp.graphique_barres(df, "x", "y", "t"); assert st.plotly_chart.call_count == 1
st.plotly_chart.reset_mock(); st.session_state["mode_leger"] = True
assert m.mode_leger() is True
erp.graphique_barres(df, "x", "y", "t"); erp.graphique_camembert(df, "x", "y", "t")
assert st.plotly_chart.call_count == 0 and st.bar_chart.call_count == 1      # repli léger, sans Plotly
st.markdown.reset_mock(); erp.injecter_theme()
css = " ".join(str(c) for c in st.markdown.call_args_list)
assert "Mode léger" in css and "backdrop-filter:none" in css
st.session_state["mode_leger"] = False; st.markdown.reset_mock(); erp.injecter_theme()
assert "backdrop-filter:none" not in " ".join(str(c) for c in st.markdown.call_args_list)
print("LEGER OK")
