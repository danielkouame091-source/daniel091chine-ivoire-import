import sys
from datetime import date
from unittest.mock import MagicMock
st = MagicMock(); st.session_state = {}; st.secrets = {}; st.context.headers = {}
def cols(spec,*a,**k):
    out=[MagicMock() for _ in range(spec if isinstance(spec,int) else len(spec))]
    for c in out:
        for nom in ("selectbox","text_input","number_input","slider","date_input","text_area","checkbox","form_submit_button","time_input"):
            setattr(c,nom,getattr(st,nom))
        c.button=MagicMock(return_value=False); c.columns=st.columns
    return out
st.columns.side_effect=cols
st.tabs.side_effect=lambda l:[MagicMock() for _ in l]
st.selectbox.side_effect=lambda label,options=(),*a,**k:(list(options) or [None])[k.get("index",0) if k.get("index",0)<len(list(options)) else 0] if list(options) else None
st.text_input.side_effect=lambda *a,**k:k.get("value","")
st.number_input.side_effect=lambda *a,**k:k.get("value",0) if k.get("value") is not None else 0
st.slider.side_effect=lambda *a,**k:(a[3] if len(a)>3 else k.get("value",0))
st.date_input.side_effect=lambda *a,**k:date.today()
st.text_area.side_effect=lambda *a,**k:(a[1] if len(a)>1 else "")
st.time_input.side_effect=lambda *a,**k:__import__("datetime").datetime.now().time(); st.button.return_value=False; st.form_submit_button.return_value=False; st.checkbox.return_value=False
sys.modules["streamlit"]=st
sys.path.insert(0,".")
import sndgir_erp as erp
erp.init_db(); st.session_state.update({"tenant_id":1,"username":"admin","user_role":"Administrateur Système"})
plan=[("onglet_comptabilite","compta",5),("onglet_transit","transit",11),("onglet_ia","ia",3),("onglet_administration","admin",4),("onglet_finai_ia","finai",7)]
for nom,cle,n in plan:
    for i in range(n):
        st.session_state[f"sm_actif_{cle}"]=i
        st.session_state["sm_actif_suivi"]=i%4; st.session_state["sm_actif_ial"]=i%2
        getattr(erp,nom)()
    print("OK",nom,n,"sections")
# suivi (4) et ial (2) à l'intérieur du transit
for j in range(4):
    st.session_state.update({"sm_actif_transit":7,"sm_actif_suivi":j}); erp.onglet_transit()
for j in range(2):
    st.session_state.update({"sm_actif_transit":10,"sm_actif_ial":j}); erp.onglet_transit()
for j in range(11):
    st.session_state["sm_actif_transit"]=j
print("OK suivi/ial")
errs=[c for c in st.error.call_args_list]; print("appels st.error:",[str(c)[:140] for c in errs][:5])
print([str(c)[:300] for c in st.code.call_args_list][:2])
import traceback, sndgir_logistique as L
st.session_state["sm_actif_ial"]=0
try: L.render_ia_logistique(erp.lire_df,1)
except Exception: traceback.print_exc()
