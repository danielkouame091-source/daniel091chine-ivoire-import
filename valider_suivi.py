import sys, tempfile, os, pandas as pd
sys.path.insert(0,'.')
import sndgir_erp as erp, sndgir_suivi as s
erp.DB_PATH = os.path.join(tempfile.mkdtemp(),'t.db')
erp.init_db()
with erp.connexion() as c:
    t=[r[0] for r in c.execute("select name from sqlite_master where type='table'")]
assert all(x in t for x in ("expeditions","positions_expedition","credits_documentaires")), t
# distance Shanghai -> Abidjan
d=s.haversine_km(*s.PORTS["Shanghai (Chine)"],*s.PORTS["Abidjan (Port autonome)"]); print("Shanghai-Abidjan km",round(d))
assert 12000<d<14000
assert s.haversine_km(1,1,1,1)==0
exp={"origine_lat":31.23,"origine_lon":121.47,"dest_lat":5.264,"dest_lon":-4.009}
pos=pd.DataFrame({"date_position":["2026-01-01 00:00:00","2026-01-11 00:00:00"],"lat":[31.23,12.0],"lon":[121.47,60.0],"lieu":["",""]})
e=s.etat_expedition(exp,pos); print({k:(round(v,1) if isinstance(v,float) else v) for k,v in e.items()})
assert e["position"] and not e["arrive"] and 0<e["progression_pct"]<100 and e["eta_jours"]>0
pos2=pd.DataFrame({"date_position":["2026-01-01"],"lat":[5.27],"lon":[-4.01],"lieu":["x"]})
assert s.etat_expedition(exp,pos2)["arrive"]
assert not s.etat_expedition(exp,pd.DataFrame())["position"]
try: s.valider_coordonnees(95,0); raise SystemExit("KO")
except ValueError: pass
r=s.prix_de_revient(1_000_000,200_000,0,180_000,100_000,100,True); assert r["total"]==1_300_000 and r["unitaire"]==13000
r=s.prix_de_revient(1_000_000,200_000,0,180_000,100_000,100,False); assert r["total"]==1_480_000
assert s.prix_de_revient(1,1,1,1,1,0)["unitaire"] is None
print("OK")
