"""Réentraîne les deux modèles sur VOS vraies données anonymisées (fichiers CSV de ce dossier).

Utilisation (Terminal, depuis le dossier du projet) :
    python3 donnees_reelles/entrainer_donnees_reelles.py voyages  donnees_reelles/mes_voyages.csv
    python3 donnees_reelles/entrainer_donnees_reelles.py dossiers donnees_reelles/mes_dossiers.csv

Le script ne change rien dans l'ERP : il affiche seulement si le modèle bat la méthode simple de référence.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from finai.logistique import douane, voyages  # noqa: E402

MINIMUM = 30          # en dessous, les résultats ne veulent rien dire
CONFORTABLE = 200


def preparer_voyages(brut: pd.DataFrame) -> pd.DataFrame:
    manque = {"origine", "compagnie", "date_depart", "transbordements", "date_arrivee_prevue",
              "date_arrivee_reelle"} - set(brut.columns)
    if manque:
        raise ValueError(f"Colonnes manquantes : {sorted(manque)}")
    d = brut.copy()
    inconnus = sorted(set(d["origine"]) - set(voyages.ORIGINES))
    if inconnus:
        raise ValueError(f"Ports inconnus {inconnus}. Ports acceptés : {list(voyages.ORIGINES)}")
    for c in ("date_depart", "date_arrivee_prevue", "date_arrivee_reelle"):
        d[c] = pd.to_datetime(d[c], errors="raise")
    out = pd.DataFrame({
        "origine": d["origine"], "ligne": d["compagnie"].astype(str),
        "mois": d["date_depart"].dt.month, "transbordements": d["transbordements"].astype(int),
        "congestion": d["congestion"].astype(float) if "congestion" in d else 0.5,
        "distance_km": [voyages.haversine_km(voyages.ORIGINES[o], voyages.DESTINATION) for o in d["origine"]],
        "delai_prevu_jours": (d["date_arrivee_prevue"] - d["date_depart"]).dt.days.astype(float),
        "retard_jours": (d["date_arrivee_reelle"] - d["date_arrivee_prevue"]).dt.days.astype(float)})
    return out


def preparer_dossiers(brut: pd.DataFrame) -> pd.DataFrame:
    manque = {"importateur", "date_dossier", "chapitre_sh", "valeur_caf_xof", "pays_origine", "regime",
              "voie_douane"} - set(brut.columns)
    if manque:
        raise ValueError(f"Colonnes manquantes : {sorted(manque)}")
    d = brut.copy()
    d["date_dossier"] = pd.to_datetime(d["date_dossier"], errors="raise")
    d["canal"] = d["voie_douane"].astype(str).str.strip().str.lower()
    mauvais = sorted(set(d["canal"]) - set(douane.CANAUX))
    if mauvais:
        raise ValueError(f"Voies inconnues {mauvais} (attendu : vert, orange, rouge)")
    d = d.sort_values("date_dossier").reset_index(drop=True)
    avant = d.groupby("importateur").cumcount()                              # dossiers PASSÉS seulement
    anomalies_passees = (d["canal"] != "vert").astype(int).groupby(d["importateur"]).cumsum() - (d["canal"] != "vert").astype(int)
    return pd.DataFrame({
        "chapitre": d["chapitre_sh"].astype(str).str.zfill(2).str[:2], "valeur_caf": d["valeur_caf_xof"].astype(float),
        "ecart_prix": d["ecart_prix"].astype(float) if "ecart_prix" in d else 0.0,
        "nb_dossiers_importateur": avant, "taux_anomalies": (anomalies_passees / avant.where(avant > 0, 1)).astype(float),
        "origine": d["pays_origine"].where(d["pays_origine"].isin(douane.ORIGINES), "Autre"),
        "regime": d["regime"], "canal": d["canal"]})


def main(type_, fichier):
    brut = pd.read_csv(fichier)
    brut = brut[~brut.iloc[:, 0].astype(str).str.contains("EXEMPLE", na=False)]
    if len(brut) < MINIMUM:
        sys.exit(f"Seulement {len(brut)} lignes : il en faut au moins {MINIMUM} (idéalement {CONFORTABLE}+).")
    if len(brut) < CONFORTABLE:
        print(f"⚠️ {len(brut)} lignes : résultats fragiles, à prendre avec prudence.")
    if type_ == "voyages":
        m = voyages.entrainer(preparer_voyages(brut))
        for nom, v in m.metriques.items():
            print(nom, {k: round(x, 3) for k, x in v.items()})
        ref, best = m.metriques["Référence (retard moyen)"]["mae_jours"], min(
            m.metriques[k]["mae_jours"] for k in ("Régression Ridge", "Gradient boosting"))
    else:
        m = douane.entrainer(preparer_dossiers(brut))
        for nom, v in m.metriques.items():
            if not nom.startswith("_"):
                print(nom, {k: round(x, 3) for k, x in v.items()})
        ref, best = -m.metriques["Référence (toujours « vert »)"]["f1_macro"], -max(
            m.metriques[k]["f1_macro"] for k in ("Régression logistique", "Gradient boosting"))
    print("\nVERDICT :", "le modèle fait mieux que la méthode simple." if best < ref
          else "le modèle ne fait PAS mieux que la méthode simple : ne pas s'y fier.")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("voyages", "dossiers"):
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
