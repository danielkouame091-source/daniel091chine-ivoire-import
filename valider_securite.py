"""Contrôles de l'étape 5 (sécurité) : 2FA, sauvegarde, mode production."""
import hashlib, os, sqlite3, sys, tempfile, importlib
from pathlib import Path
import sndgir_securite as S

n = 0
def ok(c, m):
    global n
    n += 1
    if not c:
        print("ÉCHEC :", m); sys.exit(1)

# Vecteurs officiels RFC 6238 (secret ASCII "12345678901234567890", 8 chiffres, SHA-1)
import base64
sec = base64.b32encode(b"12345678901234567890").decode()
for t, att in [(59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"),
               (1234567890, "89005924"), (2000000000, "69279037")]:
    ok(S._hotp(sec, t // 30, 8) == att, f"RFC6238 t={t}")
ok(S.verifier_totp(sec, S.code_totp(sec, 1000), instant=1000), "code courant accepté")
ok(S.verifier_totp(sec, S.code_totp(sec, 1000), instant=1030), "décalage +1 toléré")
ok(not S.verifier_totp(sec, S.code_totp(sec, 1000), instant=1100), "code périmé refusé")
ok(not S.verifier_totp(sec, "abcdef") and not S.verifier_totp(sec, "") and not S.verifier_totp("", "123456"), "entrées invalides")
ok(len(S.generer_secret()) == 32 and S.generer_secret() != S.generer_secret(), "secret aléatoire")
ok(S.uri_otpauth("ABC", "a@1").startswith("otpauth://totp/"), "URI otpauth")

with tempfile.TemporaryDirectory() as d:
    db = Path(d) / "x.db"
    c = sqlite3.connect(db); c.execute("create table t(a)"); c.executemany("insert into t values(?)", [(i,) for i in range(50)]); c.commit(); c.close()
    for _ in range(4): S.sauvegarder_base(db, Path(d) / "sv", garder=2)
    ok(len(list((Path(d) / "sv").glob("*.db"))) == 2, "rotation des sauvegardes")
    octets = S.sauvegarde_en_octets(db)
    ok(S.base_valide(octets), "sauvegarde valide")
    ok(not S.base_valide(b"pas une base" * 100), "faux fichier refusé")
    p = Path(d) / "copie.db"; p.write_bytes(octets)
    ok(sqlite3.connect(p).execute("select count(*) from t").fetchone()[0] == 50, "données restaurables")

# Mode production
os.environ.pop("SNDGIR_PRODUCTION", None)
ok(not S.mode_production(), "production off par défaut")
os.environ["SNDGIR_PRODUCTION"] = "1"; os.environ["SNDGIR_ADMIN_MDP"] = "court"
try: S.mot_de_passe_admin_initial(); ok(False, "mot de passe court accepté")
except RuntimeError: ok(True, "")
os.environ["SNDGIR_ADMIN_MDP"] = "UnMotDePasseSolide1"
ok(S.mot_de_passe_admin_initial() == "UnMotDePasseSolide1", "mot de passe lu")
print(f"{n} contrôles OK (module)")

# ── Intégration avec l'ERP ──
sys.path.insert(0, ".")
import sndgir_erp as erp
for v in ("SNDGIR_PRODUCTION", "SNDGIR_ADMIN_MDP"): os.environ.pop(v, None)

# Mode normal : 4 comptes démo
erp.DB_PATH = os.path.join(tempfile.mkdtemp(), "demo.db"); erp.init_db()
ok(len(erp.lire_df("SELECT * FROM utilisateurs")) == 4, "démo : 4 comptes")

# Production sans mot de passe → refus clair
os.environ["SNDGIR_PRODUCTION"] = "1"
erp.DB_PATH = os.path.join(tempfile.mkdtemp(), "prod0.db")
try: erp.init_db(); ok(False, "production sans mot de passe accepté")
except RuntimeError as e: ok("SNDGIR_ADMIN_MDP" in str(e), "message clair")

# Production avec mot de passe : 1 admin, pas de dossiers fictifs
os.environ["SNDGIR_ADMIN_MDP"] = "UnMotDePasseSolide1"
erp.DB_PATH = os.path.join(tempfile.mkdtemp(), "prod.db"); erp.init_db()
us = erp.lire_df("SELECT username FROM utilisateurs")
ok(list(us["username"]) == ["admin"], "production : seulement admin")
ok(len(erp.lire_df("SELECT * FROM dossiers")) == 0, "production : aucun dossier fictif")
ok(erp.authentifier(1, "admin", "admin123") is None, "admin123 refusé en production")
fiche = erp.authentifier(1, "admin", "UnMotDePasseSolide1")
ok(fiche is not None and not fiche["totp_actif"], "connexion sans 2FA")

# Activation 2FA
sec = S.generer_secret()
ok(not erp.activer_totp(1, "admin", sec, "000000") or S.verifier_totp(sec, "000000"), "mauvais code refusé")
ok(erp.activer_totp(1, "admin", sec, S.code_totp(sec)), "activation avec bon code")
fiche = erp.authentifier(1, "admin", "UnMotDePasseSolide1")
ok(fiche["totp_actif"] == 1 and fiche["totp_secret"] == sec, "2FA exigée ensuite")
ok(erp.verifier_second_facteur(fiche, S.code_totp(sec)), "bon code accepté")
ok(not erp.verifier_second_facteur(fiche, "123456") or S.verifier_totp(sec, "123456"), "mauvais code refusé")
erp.desactiver_totp(1, "admin", "admin")
ok(not erp.authentifier(1, "admin", "UnMotDePasseSolide1")["totp_actif"], "désactivation")
ok(erp.verifier_audit()[0], "chaîne d'audit intacte")
print(f"{n} contrôles OK (total)")
