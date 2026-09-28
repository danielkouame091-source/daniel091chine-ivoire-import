"""Assistant de paramétrage du dossier (étape par étape, inspiré de Sage)."""
import bv_audit
from bv_core import fmt_money, iso, utcnow

PAYS_DEVISE = {
    "Bénin": "XOF", "Burkina Faso": "XOF", "Côte d'Ivoire": "XOF",
    "Guinée-Bissau": "XOF", "Mali": "XOF", "Niger": "XOF",
    "Sénégal": "XOF", "Togo": "XOF",
    "Cameroun": "XAF", "Centrafrique": "XAF", "Congo": "XAF",
    "Gabon": "XAF", "Guinée équatoriale": "XAF", "Tchad": "XAF",
    "Comores": "KMF", "Guinée": "GNF", "RD Congo": "CDF",
}
FORMES = ["Entreprise individuelle", "SARL", "SA", "SAS", "SNC", "GIE",
          "Association", "Autre"]
STEPS = ["Identité", "Adresse", "Identification légale",
         "Devise & exercice", "Récapitulatif"]
FIELDS = ["raison_sociale", "activite", "forme_juridique", "adresse", "ville",
          "region", "pays", "rccm", "nif", "devise", "debut_exercice"]
REQUIRED = {0: ["raison_sociale", "activite"], 1: ["adresse", "ville", "pays"]}


def currency_for(pays: str) -> dict:
    code = PAYS_DEVISE.get(pays, "XOF")
    franc_cfa = code in ("XOF", "XAF")
    return {"code": code, "symbol": "FCFA" if franc_cfa else code,
            "decimals": 0 if franc_cfa or code in ("KMF", "GNF") else 2}


def missing_fields(step: int, data: dict) -> list:
    if step == 2:
        return [] if (data.get("rccm") or data.get("nif")) \
            else ["N° RCCM ou N° d'identification fiscale"]
    return [f for f in REQUIRED.get(step, [])
            if not str(data.get(f, "")).strip()]


def load_profile(con) -> dict:
    row = con.execute("SELECT * FROM saas_company_profile WHERE id=1"
                      ).fetchone()
    return {f: (row[f] or "") for f in FIELDS} if row else {}


def save_profile(con, data: dict, user: str = "admin"):
    for step in (0, 1, 2):
        if missing_fields(step, data):
            raise ValueError(f"Champs manquants (étape {STEPS[step]}).")
    values = [str(data.get(f, "")).strip() for f in FIELDS]
    con.execute(
        "INSERT INTO saas_company_profile(id," + ",".join(FIELDS) +
        ",updated_at) VALUES (1," + ",".join("?" * len(FIELDS)) + ",?) "
        "ON CONFLICT(id) DO UPDATE SET " +
        ",".join(f"{f}=excluded.{f}" for f in FIELDS) +
        ",updated_at=excluded.updated_at",
        values + [iso(utcnow())])
    con.commit()
    bv_audit.log_action(con, user, "DOSSIER_PARAMETRE",
                        f"{data.get('raison_sociale')} ({data.get('pays')})")


def render_setup_wizard(con, user: str = "admin"):
    import datetime as dt
    import streamlit as st

    wiz = st.session_state.setdefault(
        "bv_wiz", {"step": 0, "data": load_profile(con)})
    step, data = wiz["step"], wiz["data"]

    st.subheader("🏢 Paramétrage du dossier")
    st.progress((step + 1) / len(STEPS),
                text=f"Étape {step + 1}/{len(STEPS)} — {STEPS[step]}")

    def field(kind, name, label, **kw):
        k = f"wiz_{name}"
        st.session_state.setdefault(k, data.get(name, kw.pop("default", "")))
        widget = {"text": st.text_input, "select": st.selectbox}[kind]
        data[name] = widget(label, key=k, **kw)

    if step == 0:
        field("text", "raison_sociale", "Raison sociale *")
        field("text", "activite", "Activité principale *")
        field("select", "forme_juridique", "Forme juridique",
              options=FORMES, default=FORMES[1])
    elif step == 1:
        field("text", "adresse", "Adresse *")
        c1, c2 = st.columns(2)
        with c1:
            field("text", "ville", "Ville *")
        with c2:
            field("text", "region", "Région")
        field("select", "pays", "Pays *", options=list(PAYS_DEVISE),
              default="Côte d'Ivoire")
    elif step == 2:
        st.caption("Renseignez au moins un des deux identifiants.")
        field("text", "rccm", "N° RCCM (registre du commerce)")
        field("text", "nif", "N° d'identification fiscale (NIF / N° CC)")
    elif step == 3:
        cur = currency_for(data.get("pays", ""))
        data["devise"] = cur["code"]
        st.info(f"Monnaie de tenue de compte : **{cur['symbol']}** "
                f"(code ISO {cur['code']}, {cur['decimals']} décimale(s)).")
        st.write("Exemple d'affichage :", fmt_money(1234567.5, cur))
        default_date = dt.date(dt.date.today().year, 1, 1)
        raw = data.get("debut_exercice") or default_date.isoformat()
        picked = st.date_input("Début de l'exercice comptable",
                               value=dt.date.fromisoformat(raw))
        data["debut_exercice"] = picked.isoformat()
    else:
        labels = {"raison_sociale": "Raison sociale", "activite": "Activité",
                  "forme_juridique": "Forme juridique", "adresse": "Adresse",
                  "ville": "Ville", "region": "Région", "pays": "Pays",
                  "rccm": "N° RCCM", "nif": "NIF / N° CC",
                  "devise": "Devise", "debut_exercice": "Début d'exercice"}
        for f, lab in labels.items():
            st.write(f"**{lab}** : {data.get(f) or '—'}")

    err = None
    left, right = st.columns(2)
    if step > 0 and left.button("← Précédent"):
        wiz["step"] -= 1
        st.rerun()
    if step < len(STEPS) - 1:
        if right.button("Suivant →", type="primary"):
            miss = missing_fields(step, data)
            if miss:
                err = "Champs obligatoires manquants : " + ", ".join(miss)
            else:
                wiz["step"] += 1
                st.rerun()
    elif right.button("✅ Enregistrer le dossier", type="primary"):
        try:
            save_profile(con, data, user)
            st.success("Dossier enregistré.")
        except ValueError as e:
            err = str(e)
    if err:
        st.error(err)
