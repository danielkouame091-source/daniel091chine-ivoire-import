"""
Client OCR unifié — Tesseract, PaddleOCR, Google Vision, AWS Textract.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


class OCRClient:
    """Client OCR unifié."""

    def __init__(self, moteur: str = "tesseract") -> None:
        self.moteur = moteur

    async def extraire_texte(
        self, contenu: bytes, mime_type: str, langues: list[str] | None = None
    ) -> dict[str, Any]:
        """
        Retourne :
        {
            "texte": str,
            "confiance": float,
            "extraction": dict,   # champs structurés
            "moteur": str,
            "langues": [...]
        }
        """
        langues = langues or ["fra", "eng"]

        if self.moteur == "tesseract":
            return await self._tesseract(contenu, mime_type, langues)
        if self.moteur == "paddleocr":
            return await self._paddleocr(contenu, mime_type, langues)
        if self.moteur == "vision_api":
            return await self._vision_api(contenu)
        if self.moteur == "no_ocr":
            return {
                "texte": "",
                "confiance": None,
                "extraction": {},
                "moteur": "no_ocr",
                "langues": langues,
            }
        raise ValueError(f"Moteur OCR inconnu : {self.moteur}")

    async def _tesseract(
        self, contenu: bytes, mime_type: str, langues: list[str]
    ) -> dict[str, Any]:
        """OCR via Tesseract (local)."""
        try:
            import pytesseract
            from PIL import Image
            import io
        except ImportError:
            raise RuntimeError("pytesseract non installé")

        # Si PDF → convertir d'abord en images
        images = []
        if mime_type == "application/pdf":
            try:
                from pdf2image import convert_from_bytes
                images = convert_from_bytes(contenu, dpi=200)
            except Exception:
                logger.exception("[ocr] Conversion PDF échouée")
                return {"texte": "", "confiance": None, "extraction": {}, "moteur": "tesseract", "langues": langues, "erreur": "pdf_conversion_failed"}
        elif mime_type.startswith("image/"):
            images = [Image.open(io.BytesIO(contenu))]
        else:
            return {"texte": "", "confiance": None, "extraction": {}, "moteur": "tesseract", "langues": langues, "erreur": "unsupported_format"}

        # Concaténer
        full_text = []
        confidences = []
        lang_str = "+".join(langues)

        for img in images:
            try:
                text = pytesseract.image_to_string(img, lang=lang_str)
                full_text.append(text)
                data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, lang=lang_str)
                confs = [int(c) for c in data["conf"] if str(c).replace("-", "").isdigit() and int(c) > 0]
                if confs:
                    confidences.append(sum(confs) / len(confs) / 100)
            except Exception:
                logger.exception("[ocr] Échec OCR image")

        texte_final = "\n".join(full_text)
        confiance = sum(confidences) / len(confidences) if confidences else None

        return {
            "texte": texte_final,
            "confiance": round(confiance, 4) if confiance else None,
            "extraction": self._extraire_champs(texte_final),
            "moteur": "tesseract",
            "langues": langues,
        }

    async def _paddleocr(
        self, contenu: bytes, mime_type: str, langues: list[str]
    ) -> dict[str, Any]:
        """OCR via PaddleOCR (meilleur pour le français moderne)."""
        # Implémentation simplifiée — à compléter
        return await self._tesseract(contenu, mime_type, langues)

    async def _vision_api(self, contenu: bytes) -> dict[str, Any]:
        """OCR via Google Cloud Vision."""
        try:
            from google.cloud import vision
            import io
        except ImportError:
            raise RuntimeError("google-cloud-vision non installé")

        client = vision.ImageAnnotatorClient()
        image = vision.Image(content=contenu)
        response = client.document_text_detection(image=image)

        texte = response.full_text_annotation.text if response.full_text_annotation else ""
        confiance = None
        if response.full_text_annotation and response.full_text_annotation.pages:
            page = response.full_text_annotation.pages[0]
            if page.blocks:
                confiance = page.blocks[0].confidence

        return {
            "texte": texte,
            "confiance": round(confiance, 4) if confiance else None,
            "extraction": self._extraire_champs(texte),
            "moteur": "vision_api",
            "langues": ["fr"],
        }

    # ═════════════════════════════════════════════════════════════════════
    # EXTRACTION STRUCTURÉE (regex sur le texte)
    # ═════════════════════════════════════════════════════════════════════
    @staticmethod
    def _extraire_champs(texte: str) -> dict[str, Any]:
        """Extrait les champs structurés via regex."""
        if not texte:
            return {}

        extraction: dict[str, Any] = {}
        t = texte

        # Numéro de facture
        match = re.search(r"(?:facture|invoice|n[°o]\s*)[\s:]*([A-Z0-9\-/]{4,30})", t, re.IGNORECASE)
        if match:
            extraction["num_facture"] = match.group(1).strip()

        # Montants (format FCFA / F / CFA)
        for label, key in [
            (r"(?:total\s+)?TTC", "montant_ttc"),
            (r"(?:total\s+)?HT", "montant_ht"),
            (r"TVA", "montant_tva"),
        ]:
            match = re.search(
                rf"{label}\s*[:\-]?\s*([\d\s.,]+)\s*(?:FCFA|CFA|F\b)",
                t, re.IGNORECASE,
            )
            if match:
                try:
                    montant = int(re.sub(r"[^\d]", "", match.group(1)))
                    extraction[key] = montant
                except ValueError:
                    pass

        # Date (formats FR : dd/mm/yyyy, dd-mm-yyyy, dd.mm.yyyy)
        match = re.search(r"(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2,4})", t)
        if match:
            try:
                d, m, y = int(match.group(1)), int(match.group(2)), int(match.group(3))
                if y < 100:
                    y += 2000
                extraction["date_facture"] = date(y, m, d).isoformat()
            except ValueError:
                pass

        # NCC (numéro compte contribuable)
        match = re.search(r"(?:NCC|CC|N\.?C\.?C\.?)\s*[:\-]?\s*([A-Z0-9]{6,20})", t, re.IGNORECASE)
        if match:
            extraction["numero_contribuable"] = match.group(1).strip()

        # IBAN / RIB
        match = re.search(r"\b([A-Z]{2}\d{2}[\s\d]{10,30})\b", t)
        if match:
            extraction["iban"] = re.sub(r"\s", "", match.group(1))

        return extraction


def get_ocr_client(moteur: str = "tesseract") -> OCRClient:
    return OCRClient(moteur)
