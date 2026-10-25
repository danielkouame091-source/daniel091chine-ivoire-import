"""Vision par ordinateur / OCR de pièces comptables (factures, reçus).

Chaîne : prétraitement OpenCV (débruitage, redressement, binarisation) → moteur OCR (EasyOCR si
installé, sinon Tesseract) → extraction de champs par règles + validations comptables (HT + TVA = TTC).
Option avancée : LayoutLM (document question answering) via `transformers` — voir `extraire_layoutlm`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

import cv2
import numpy as np

try:
    import easyocr as _easyocr
    EASYOCR_OK = True
except Exception:                                      # pragma: no cover
    _easyocr, EASYOCR_OK = None, False
try:
    import pytesseract as _pt
    _pt.get_tesseract_version()
    TESSERACT_OK = True
except Exception:                                      # pragma: no cover
    _pt, TESSERACT_OK = None, False

_LECTEUR_EASY = None


def pretraiter_image(img: np.ndarray, echelle_min: int = 1400) -> np.ndarray:
    """Niveaux de gris → agrandissement → débruitage → redressement (deskew) → binarisation d'Otsu."""
    gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img.copy()
    h, w = gris.shape
    if w < echelle_min:
        f = echelle_min / w
        gris = cv2.resize(gris, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    gris = cv2.fastNlMeansDenoising(gris, None, h=12, templateWindowSize=7, searchWindowSize=21)
    _, bw = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    coords = np.column_stack(np.where(bw > 0))
    angle = 0.0
    if len(coords) > 200:
        a = cv2.minAreaRect(coords.astype(np.float32))[-1]
        angle = -(90 + a) if a < -45 else -a
        if a > 45:
            angle = 90 - a
        if abs(angle) > 15:                              # redressement plausible seulement pour de petits angles
            angle = 0.0
    if abs(angle) > 0.3:
        M = cv2.getRotationMatrix2D((gris.shape[1] / 2, gris.shape[0] / 2), angle, 1.0)
        gris = cv2.warpAffine(gris, M, (gris.shape[1], gris.shape[0]), flags=cv2.INTER_CUBIC,
                              borderMode=cv2.BORDER_REPLICATE)
    _, final = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return final


def moteur_disponible() -> str | None:
    if EASYOCR_OK:
        return "easyocr"
    if TESSERACT_OK:
        return "tesseract"
    return None


def lire_texte(img: np.ndarray, langues: tuple[str, ...] = ("fr", "en")) -> tuple[str, str]:
    """Retourne (texte, moteur). Lève RuntimeError si aucun moteur OCR n'est disponible."""
    global _LECTEUR_EASY
    pre = pretraiter_image(img)
    moteur = moteur_disponible()
    if moteur == "easyocr":
        if _LECTEUR_EASY is None:
            _LECTEUR_EASY = _easyocr.Reader(list(langues), gpu=False)
        lignes = _LECTEUR_EASY.readtext(pre, detail=0, paragraph=False)
        return "\n".join(lignes), "easyocr"
    if moteur == "tesseract":
        dispo = set(_pt.get_languages())
        lang = "+".join(l for l in ("fra", "eng") if l in dispo) or "eng"
        return _pt.image_to_string(pre, lang=lang, config="--psm 6"), "tesseract"
    raise RuntimeError("Aucun moteur OCR : installez easyocr (pip install easyocr) ou Tesseract.")


def _nombre(txt: str) -> float | None:
    t = txt.strip().replace(" ", " ").replace(" ", "")
    t = re.sub(r"[^\d,.\-]", "", t)
    if not t:
        return None
    if "," in t and "." in t:
        t = t.replace(",", "") if t.rfind(".") > t.rfind(",") else t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".") if len(t.split(",")[-1]) <= 2 else t.replace(",", "")
    elif t.count(".") > 1 or (t.count(".") == 1 and len(t.split(".")[-1]) == 3):
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return None


_MONTANT = r"([0-9][0-9\s .,]*[0-9])"
_DEVISES = {"FCFA": "XOF", "XOF": "XOF", "CFA": "XOF", "EUR": "EUR", "€": "EUR", "USD": "USD", "$": "USD",
            "INR": "INR", "₹": "INR", "RS": "INR", "CNY": "CNY", "RMB": "CNY", "¥": "CNY", "AUD": "AUD"}


@dataclass
class ExtractionFacture:
    champs: dict = field(default_factory=dict)
    confiance: dict = field(default_factory=dict)
    alertes: list[str] = field(default_factory=list)


def _date(txt: str) -> str | None:
    for m in re.finditer(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b|\b(\d{4})-(\d{2})-(\d{2})\b", txt):
        try:
            if m.group(4):
                d = datetime(int(m.group(4)), int(m.group(5)), int(m.group(6)))
            else:
                d = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            return d.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def extraire_champs(texte: str) -> ExtractionFacture:
    """Extrait fournisseur, n° de facture, date, devise, HT, TVA, TTC puis contrôle la cohérence."""
    ex = ExtractionFacture()
    t = texte or ""
    lignes = [l.strip() for l in t.splitlines() if l.strip()]
    m = re.search(r"(?:facture|invoice|re[cç]u|receipt)\s*(?:n[°o]?|no\.?|number|#)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/]{3,})", t, re.I)
    if m and re.search(r"\d", m.group(1)):
        ex.champs["numero_facture"], ex.confiance["numero_facture"] = m.group(1), 0.85
    d = _date(t)
    if d:
        ex.champs["date"], ex.confiance["date"] = d, 0.85
    m = re.search(r"(?:fournisseur|vendeur|[ée]metteur|seller|supplier|from)\s*[:\-]\s*(.+)", t, re.I)
    if m:
        ex.champs["fournisseur"], ex.confiance["fournisseur"] = m.group(1).strip()[:80], 0.8
    else:
        candidates = [l for l in lignes if not re.search(r"facture|invoice|date|n[°o]|\d{4}|total|\bht\b|\bttc\b|tva|vat", l, re.I)
                      and sum(c.isalpha() for c in l) >= 0.6 * len(l)]
        if candidates:
            ex.champs["fournisseur"], ex.confiance["fournisseur"] = candidates[0][:80], 0.4
    regles = (("ttc", r"total\s*t\.?t\.?c|\bt\.?t\.?c\b|net\s*[àa]\s*payer|total\s*due|grand\s*total|amount\s*due|^\s*total\b", r"\bh\.?t\b|hors\s*taxe|\btva\b|\bvat\b"),
              ("ht", r"total\s*h\.?t\b|montant\s*h\.?t\b|\bh\.?t\b|sub\s*total|net\s*amount|hors\s*taxes?", r"\bt\.?t\.?c\b"),
              ("tva", r"\bt\.?v\.?a\b|\bvat\b|\bgst\b", r"\bt\.?t\.?c\b|\bh\.?t\b"))
    for cle, motif, exclure in regles:
        for l in lignes:
            if re.search(motif, l, re.I) and not re.search(exclure, l, re.I):
                sans_pct = re.sub(r"\d+(?:[.,]\d+)?\s*%", " ", l)
                valeurs = [v for v in (_nombre(n) for n in re.findall(_MONTANT, sans_pct)) if v is not None]
                if valeurs:
                    ex.champs[cle], ex.confiance[cle] = valeurs[-1], 0.8
                    break
    m = re.search(r"(?:t\.?v\.?a|vat|gst)\.?[^0-9\n]{0,15}(\d{1,2}(?:[.,]\d+)?)\s*%", t, re.I)
    if m:
        ex.champs["taux_tva"] = float(m.group(1).replace(",", "."))
    for sym, code in _DEVISES.items():
        if re.search(rf"(?<![A-Za-z]){re.escape(sym)}(?![A-Za-z])", t, re.I if sym.isalpha() else 0):
            ex.champs["devise"], ex.confiance["devise"] = code, 0.7
            break
    c = ex.champs
    if {"ht", "tva", "ttc"} <= set(c):
        ecart = abs(c["ht"] + c["tva"] - c["ttc"])
        if ecart > max(1.0, 0.005 * c["ttc"]):
            ex.alertes.append(f"Incohérence : HT + TVA = {c['ht'] + c['tva']:,.0f} ≠ TTC = {c['ttc']:,.0f}.")
        else:
            ex.confiance["coherence_montants"] = 0.95
    if {"ht", "ttc"} <= set(c) and "tva" not in c and c["ttc"] > c["ht"]:
        c["tva"] = round(c["ttc"] - c["ht"], 2)
    if "taux_tva" in c and {"ht", "tva"} <= set(c) and c["ht"] > 0:
        attendu = c["ht"] * c["taux_tva"] / 100
        if abs(attendu - c["tva"]) > max(1.0, 0.01 * attendu):
            ex.alertes.append(f"TVA déclarée à {c['taux_tva']:g} % : montant attendu {attendu:,.0f}, lu {c['tva']:,.0f}.")
    for requis in ("numero_facture", "date", "ttc"):
        if requis not in c:
            ex.alertes.append(f"Champ non détecté : {requis}.")
    return ex


def classifier_document(texte: str) -> str:
    t = (texte or "").lower()
    regles = {"facture": ["facture", "invoice", "tva", "vat"], "recu": ["reçu", "recu", "receipt", "quittance"],
              "releve_bancaire": ["relevé", "releve", "solde", "statement", "iban"],
              "etat_financier": ["bilan", "compte de résultat", "balance sheet", "income statement"]}
    scores = {k: sum(t.count(mot) for mot in mots) for k, mots in regles.items()}
    meilleur = max(scores, key=scores.get)
    return meilleur if scores[meilleur] > 0 else "inconnu"


def traiter_document(img: np.ndarray) -> dict:
    """OCR + classification + extraction + validations (point d'entrée de l'API)."""
    texte, moteur = lire_texte(img)
    ex = extraire_champs(texte)
    return {"moteur": moteur, "type_document": classifier_document(texte), "champs": ex.champs,
            "confiance": ex.confiance, "alertes": ex.alertes, "texte": texte}


def extraire_layoutlm(chemin_image: str, questions: dict[str, str] | None = None,
                      modele: str = "impira/layoutlm-document-qa") -> dict:
    """Extraction par LayoutLM (document question answering). NÉCESSITE `transformers`, `torch`,
    `pytesseract` et un accès réseau au premier appel (téléchargement du modèle). Non exécuté dans les
    tests automatiques de ce dépôt (dépendances lourdes)."""
    try:
        from transformers import pipeline
    except Exception as exc:                           # pragma: no cover
        raise RuntimeError("Installez : pip install transformers torch pillow pytesseract") from exc
    qa = pipeline("document-question-answering", model=modele)
    questions = questions or {"numero_facture": "What is the invoice number?", "date": "What is the invoice date?",
                              "ttc": "What is the total amount?", "fournisseur": "What is the supplier name?"}
    return {k: qa(image=chemin_image, question=q)[0] for k, q in questions.items()}
