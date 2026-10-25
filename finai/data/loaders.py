"""Chargement et validation de données : CSV d'états financiers, jeux publics externes."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..accounting.statement import Statement

CHAMPS_STATEMENT = list(Statement.__dataclass_fields__)


def valider_schema(df: pd.DataFrame, colonnes_requises: list[str]) -> list[str]:
    """Retourne la liste des problèmes détectés (vide si le schéma est valide)."""
    problemes = []
    manquantes = [c for c in colonnes_requises if c not in df.columns]
    if manquantes:
        problemes.append(f"Colonnes manquantes : {manquantes}")
    if df.empty:
        problemes.append("Le fichier ne contient aucune ligne.")
    dupl = df["id"].duplicated().sum() if "id" in df.columns else 0
    if dupl:
        problemes.append(f"{dupl} identifiants en double.")
    return problemes


def charger_etats_csv(chemin: str | Path) -> pd.DataFrame:
    """Charge un CSV d'états financiers (colonnes = champs de `Statement` + id, zone, secteur)."""
    df = pd.read_csv(chemin)
    problemes = valider_schema(df, ["id", "zone", "secteur"])
    if problemes:
        raise ValueError(" ; ".join(problemes))
    for col in CHAMPS_STATEMENT:
        if col not in df.columns:
            df[col] = np.nan
    return df


def charger_jeu_externe(chemin: str | Path, cible: str) -> tuple[pd.DataFrame, pd.Series]:
    """Charge un jeu tabulaire public (ex. UCI Polish / Taiwanese bankruptcy) : X numérique + y binaire.

    Les colonnes non numériques sont supprimées ; la cible est convertie en 0/1. Le jeu peut ensuite
    passer par `finai.ml.train.evaluer_modeles` exactement comme les données synthétiques.
    """
    df = pd.read_csv(chemin)
    if cible not in df.columns:
        raise ValueError(f"Colonne cible « {cible} » introuvable.")
    y = pd.to_numeric(df[cible], errors="coerce")
    if y.isna().any() or not set(y.unique()) <= {0, 1}:
        y = (y > 0).astype(int)
    X = df.drop(columns=[cible]).select_dtypes(include=[np.number]).replace([np.inf, -np.inf], np.nan)
    return X, y.astype(int)


def nettoyer_etats(df: pd.DataFrame) -> pd.DataFrame:
    """Nettoyage non destructif : types numériques, ±inf → NaN, négatifs aberrants signalés.

    Les valeurs manquantes sont CONSERVÉES (l'imputation se fait dans le pipeline ML, ajusté sur
    l'ensemble d'entraînement uniquement pour éviter toute fuite de données).
    """
    out = df.copy()
    num = [c for c in out.columns if c in CHAMPS_STATEMENT or c.startswith("prev_")]
    for c in num:
        out[c] = pd.to_numeric(out[c], errors="coerce").replace([np.inf, -np.inf], np.nan)
    positifs = [c for c in ("ventes_marchandises", "production_vendue", "immobilisations_nettes",
                            "stocks", "creances_clients", "dettes_fournisseurs") if c in out.columns]
    for c in positifs:
        out[f"anomalie_{c}_negatif"] = (out[c] < 0).astype(int)
        out.loc[out[c] < 0, c] = np.nan
    return out
