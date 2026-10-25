"""Contrôles de l'étape 6 (protection des données)."""
import io, os, tempfile
import pandas as pd
import sndgir_erp as erp, sndgir_donnees as D

erp.DB_PATH = os.path.join(tempfile.mkdtemp(), "d.db"); erp.init_db()
with erp.connexion() as c:
    d = c.execute("SELECT id, reference FROM dossiers WHERE client='SARL IvoirTech'").fetchone()
    c.execute("UPDATE dossiers SET email='a@ivoirtech.ci', telephone='0102030405', observation='Contact: M. Koné' WHERE id=?", (d["id"],))
    c.execute("INSERT INTO communications (tenant_id,type,destinataire,email_destinataire,objet,corps) VALUES (1,'Mail','SARL IvoirTech','a@ivoirtech.ci','Votre dossier','Bonjour M. Koné')")
    c.execute("INSERT INTO connaissements (tenant_id,bl,client) VALUES (1,'BL1','sarl ivoirtech')")
    c.execute("INSERT INTO fne_factures (tenant_id,dossier_id,ncc_client) VALUES (1,?, '123456X')", (d["id"],))
    c.execute("INSERT INTO expeditions (tenant_id,dossier_ref,origine,destination,dest_lat,dest_lon) VALUES (1,?, 'Shanghai','Abidjan',5.3,-4.0)", (d["reference"],))
    c.execute("INSERT INTO communications (tenant_id,type,destinataire,objet,corps) VALUES (1,'Mail','Groupe Bâtir SA','x','y')")
total_avant = erp.lire_df("SELECT SUM(total_facture) s FROM dossiers").iloc[0]["s"]

assert "SARL IvoirTech" in D.lister_clients(erp.lire_df, 1)
dn = D.donnees_client(erp.lire_df, 1, "SARL IvoirTech")
assert len(dn["dossiers"]) == 1 and len(dn["connaissements"]) == 1 and len(dn["communications"]) == 1
assert len(dn["factures_fne"]) == 1 and len(dn["expeditions"]) == 1
x = pd.ExcelFile(io.BytesIO(D.export_excel(dn)))
assert "dossiers" in x.sheet_names and len(x.sheet_names) == 5
assert len(D.donnees_client(erp.lire_df, 2, "SARL IvoirTech")["dossiers"]) == 0          # isolation entreprises

t = D.anonymiser_client(erp.connexion, erp.journaliser, 1, "SARL IvoirTech", "demande écrite")
assert t == {"dossiers": 1, "connaissements": 1, "communications": 1, "factures_fne": 1}, t
alias = D.pseudonyme(1, "SARL IvoirTech")
r = erp.lire_df("SELECT * FROM dossiers WHERE id=?", (d["id"],)).iloc[0]
assert r["client"] == alias and r["email"] is None and r["telephone"] is None and r["observation"] is None
cm = erp.lire_df("SELECT * FROM communications WHERE destinataire=?", (alias,)).iloc[0]
assert cm["corps"] == D.EFFACE and cm["email_destinataire"] is None
assert erp.lire_df("SELECT ncc_client FROM fne_factures").iloc[0]["ncc_client"] is None
assert erp.lire_df("SELECT SUM(total_facture) s FROM dossiers").iloc[0]["s"] == total_avant      # montants gardés
assert len(erp.lire_df("SELECT * FROM communications WHERE destinataire='Groupe Bâtir SA'")) == 1  # autre client intact
assert "SARL IvoirTech" not in D.lister_clients(erp.lire_df, 1)
journal = erp.lire_df("SELECT * FROM audit_logs WHERE action='client_anonymise'")
assert len(journal) == 1 and "IvoirTech" not in " ".join(map(str, journal.iloc[0].values))       # pas de nom dans le journal
assert erp.verifier_audit()[0]
try: D.anonymiser_client(erp.connexion, erp.journaliser, 1, "  "); raise SystemExit("KO")
except ValueError: pass
print("DONNEES OK")
