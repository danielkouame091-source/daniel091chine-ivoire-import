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

# ── Tour de contrôle ──
import sndgir_tour as t
from datetime import date
with erp.connexion() as c:
    cols=[r[1] for r in c.execute("pragma table_info(expeditions)")]
    assert {"franchise_jours","penalite_jour_xof","date_arrivee_prevue"} <= set(cols), cols
    assert c.execute("select count(*) from jalons_expedition").fetchone()[0]==0
auj=date(2026,3,20)
vide=pd.DataFrame(columns=["date_position","lat","lon"])
# franchise dépassée : déchargé le 5 mars, 7 jours de franchise, pénalité 50 000/jour -> 8 jours de retard ?
a=t.analyser({"franchise_jours":7,"penalite_jour_xof":50000},{"ARRIVEE":"2026-03-05","DECHARGEMENT":"2026-03-05"},vide,aujourdhui=auj)
assert a["jours_port"]==15 and a["franchise_restante"]==-8 and a["surestaries"]==400000 and a["niveau"]=="rouge", a
# franchise presque épuisée
a=t.analyser({"franchise_jours":7},{"DECHARGEMENT":"2026-03-14"},vide,aujourdhui=auj)
assert a["franchise_restante"]==1 and a["niveau"]=="orange"
# sorti du port : plus de surestaries
a=t.analyser({"franchise_jours":7,"penalite_jour_xof":50000},{"DECHARGEMENT":"2026-03-01","SORTIE":"2026-03-06"},vide,aujourdhui=auj)
assert a["surestaries"]==0 and a["niveau"]=="vert"
# navire en retard
a=t.analyser({"date_arrivee_prevue":"2026-03-10"},{"DEPART":"2026-02-01"},vide,aujourdhui=auj)
assert a["niveau"]=="orange" and any("retard" in x[1] for x in a["alertes"])
# navire silencieux
pp=pd.DataFrame({"date_position":["2026-03-01"],"lat":[1],"lon":[1]})
a=t.analyser({},{"DEPART":"2026-02-01"},pp,aujourdhui=auj); assert any("Aucune position" in x[1] for x in a["alertes"])
# LC bloqué + solde impayé
a=t.analyser({},{"ARRIVEE":"2026-03-19","DECHARGEMENT":"2026-03-19","BAE":"2026-03-20"},vide,5_000_000,200_000,aujourdhui=auj); assert a["score"]==20
# rien du tout
a=t.analyser({},{},vide,aujourdhui=auj); assert a["score"]==0 and a["prochaine"]=="BOOKING" and a["actuelle"] is None
m=t.message_client("IMP-1","M. Koné",t.analyser({},{"DEPART":"2026-02-01"},vide,aujourdhui=auj),12.4); assert "12 jours" in m and "IMP-1" in m
l=t.lien_whatsapp("+225 07 00 00 00 00","Bonjour é"); assert l.startswith("https://wa.me/2250700000000?text=") and "%C3%A9" in l
print("TOUR OK")
