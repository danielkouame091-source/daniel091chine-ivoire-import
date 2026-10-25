"""API REST FastAPI : `uvicorn finai.api.main:app --reload` (depuis le dossier `src`).

Endpoints : /health, /zones, /diagnostic, /scenario, /solvabilite, /fraude/score, /ocr,
/tresorerie/prevision, /nlp/classer-libelle, /nlp/ton-audit. Documentation interactive : /docs.
Le modèle de solvabilité est chargé depuis `models/solvabilite.joblib` (créé par
`python scripts/run_pipeline.py`) ; s'il manque, /solvabilite répond 503 avec la marche à suivre.
"""
from __future__ import annotations

import functools

import numpy as np
import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile

from ..accounting.scenarios import Choc, comparer_scenarios, sensibilite_tornado
from ..accounting.standards import ZONES
from ..accounting.statement import Statement
from ..dl import nlp, ocr
from ..dl.forecast import PrevisionneurDirect
from ..ml.anomaly import test_benford
from ..data.synthetic import generer_libelles
from ..service import pipeline
from . import schemas

app = FastAPI(title="FinAI — Plateforme d'analyse financière et de détection d'anomalies", version="1.0.0",
              description="Diagnostic SYSCOHADA/IFRS/GAAP, scoring de solvabilité explicable, fraude, OCR, prévision.")


def _statement(e: schemas.EtatFinancier) -> Statement:
    return Statement.from_dict(e.donnees)


@functools.lru_cache(maxsize=1)
def _modele():
    return pipeline.charger_solvabilite()


@functools.lru_cache(maxsize=1)
def _classifieur_libelles():
    return nlp.ClassifieurTexte().fit(*(lambda d: (d["libelle"], d["compte"]))(generer_libelles(4000)))


@app.get("/health")
def health() -> dict:
    return {"statut": "ok", "modele_solvabilite_charge": _modele() is not None, "moteur_ocr": ocr.moteur_disponible()}


@app.get("/zones")
def zones() -> dict:
    return {k: {"zone": z.zone, "referentiel": z.referentiel, "devise": z.devise} for k, z in ZONES.items()}


@app.post("/diagnostic")
def diagnostic(req: schemas.DemandeDiagnostic) -> dict:
    prec = _statement(req.precedent) if req.precedent else None
    return pipeline.diagnostic_entreprise(_statement(req.courant), req.zone, prec)


@app.post("/scenario")
def scenario(req: schemas.DemandeScenario) -> dict:
    s = _statement(req.courant)
    return {"scenarios": comparer_scenarios(s, {"Scénario": Choc(**req.choc.model_dump())}),
            "tornado": sensibilite_tornado(s)}


@app.post("/solvabilite")
def solvabilite(req: schemas.DemandeDiagnostic) -> dict:
    ms = _modele()
    if ms is None:
        raise HTTPException(status_code=503, detail="Modèle absent : exécutez `python scripts/run_pipeline.py`.")
    prec = _statement(req.precedent) if req.precedent else None
    return pipeline.scorer_solvabilite(ms, _statement(req.courant), req.zone, req.secteur, prec)


@app.post("/fraude/score")
def fraude(req: schemas.DemandeFraude) -> dict:
    df = pd.DataFrame([t.model_dump() for t in req.transactions])
    out = pipeline.scorer_transactions(df)
    benford = test_benford(df["montant"])
    return {"benford": {k: benford[k] for k in ("n", "mad", "conforme")},
            "top_anomalies": out.head(20)[["fournisseur", "compte", "montant", "score_anomalie", "motifs"]]
            .to_dict(orient="records")}


@app.post("/ocr")
async def lecture_document(fichier: UploadFile = File(...)) -> dict:
    import cv2
    contenu = await fichier.read()
    if len(contenu) > 10_000_000:
        raise HTTPException(status_code=413, detail="Image trop volumineuse (10 Mo maximum).")
    img = cv2.imdecode(np.frombuffer(contenu, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=422, detail="Fichier image illisible.")
    try:
        return ocr.traiter_document(img)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/tresorerie/prevision")
def prevision(req: schemas.DemandePrevision) -> dict:
    idx = pd.date_range(req.date_debut, periods=len(req.flux_hebdomadaires), freq="W-MON")
    serie = pd.Series(req.flux_hebdomadaires, index=idx)
    p = PrevisionneurDirect(req.horizon, modele=req.modele).fit(serie).predict()
    return {"previsions": [{"date": d.strftime("%Y-%m-%d"), **{k: float(v) for k, v in r.items()}}
                           for d, r in p.iterrows()]}


@app.post("/nlp/classer-libelle")
def classer_libelle(req: schemas.DemandeTexte) -> dict:
    m = _classifieur_libelles()
    proba = m.predict_proba([req.texte]).iloc[0].sort_values(ascending=False)
    return {"classe_syscohada": str(proba.index[0]), "confiance": float(proba.iloc[0]),
            "alternatives": {str(k): float(v) for k, v in proba.head(3).items()}}


@app.post("/nlp/ton-audit")
def ton_audit(req: schemas.DemandeTexte) -> dict:
    return nlp.score_ton_audit(req.texte)
