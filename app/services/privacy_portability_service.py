"""
Service de portabilité — Export des données personnelles d'un utilisateur.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.privacy import DataSubjectRequest
from app.models.sale import Customer, CustomerInvoice, CustomerPayment
from app.models.user import User
from app.schemas.privacy import PortabilityExportIn, PortabilityExportOut
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)


class PortabilityService:
    """
    Génère un export des données personnelles au format JSON/CSV.
    Utilisé pour répondre aux demandes de portabilité (Art. 20 RGPD).
    """

    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.storage = StorageService()

    async def exporter(
        self, data: PortabilityExportIn
    ) -> PortabilityExportOut:
        """
        Génère un export complet des données personnelles liées à un email.
        """
        # Collecter les données
        export_data = await self._collecter_donnees(data.email, data.inclure_donnees)

        # Sérialiser selon le format
        if data.format == "json":
            contenu = json.dumps(export_data, indent=2, default=str, ensure_ascii=False).encode("utf-8")
            mime = "application/json"
            ext = "json"
        elif data.format == "csv":
            contenu = self._vers_csv(export_data).encode("utf-8")
            mime = "text/csv"
            ext = "csv"
        elif data.format == "xlsx":
            contenu = self._vers_xlsx(export_data)
            mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ext = "xlsx"
        else:
            raise HTTPException(400, f"Format non supporté : {data.format}")

        # Upload vers S3
        ref = f"export-{uuid4().hex[:12]}"
        storage_key = f"tenant_{self.tenant_id}/exports/{ref}.{ext}"
        try:
            await self.storage.upload(storage_key, contenu, mime)
        except Exception as exc:
            logger.exception("[portability] Échec upload S3")
            raise HTTPException(500, f"Erreur de stockage : {exc}")

        # URL signée
        url = await self.storage.get_signed_url(storage_key, expiration_minutes=60 * 24)

        expire_at = datetime.now(timezone.utc) + timedelta(days=7)

        return PortabilityExportOut(
            reference=ref,
            format=data.format,
            statut="termine",
            fichier_url=url,
            expire_at=expire_at,
            created_at=datetime.now(timezone.utc),
        )

    async def _collecter_donnees(
        self, email: str, inclure: list[str]
    ) -> dict[str, Any]:
        """Collecte toutes les données liées à un email."""
        if not inclure:
            inclure = ["profil", "factures", "paiements"]

        export: dict[str, Any] = {
            "metadata": {
                "email": email,
                "tenant_id": str(self.tenant_id),
                "date_export": datetime.now(timezone.utc).isoformat(),
                "categories_incluses": inclure,
                "reference_rgpd": "Art. 20 RGPD / Art. 44 Loi 2013-450",
            },
        }

        # Profil utilisateur
        if "profil" in inclure:
            user = await self.db.scalar(
                select(User).where(User.email == email)
            )
            if user:
                export["profil"] = {
                    "id": str(user.id),
                    "email": user.email,
                    "nom_complet": user.nom_complet,
                    "telephone": user.telephone,
                    "role": user.role.value if hasattr(user.role, "value") else str(user.role),
                    "derniere_connexion": user.derniere_connexion.isoformat() if user.derniere_connexion else None,
                    "created_at": user.created_at.isoformat(),
                }

        # Factures clients
        if "factures" in inclure:
            customer = await self.db.scalar(
                select(Customer).where(
                    Customer.tenant_id == self.tenant_id,
                    Customer.email == email,
                )
            )
            if customer:
                invoices = (
                    await self.db.execute(
                        select(CustomerInvoice).where(
                            CustomerInvoice.tenant_id == self.tenant_id,
                            CustomerInvoice.customer_id == customer.id,
                        ).limit(500)
                    )
                ).scalars().all()
                export["factures"] = [
                    {
                        "numero": inv.numero,
                        "date_facture": inv.date_facture.isoformat(),
                        "total_ttc": inv.total_ttc,
                        "solde_du": inv.solde_du,
                        "statut": inv.statut,
                    }
                    for inv in invoices
                ]

        # Paiements
        if "paiements" in inclure:
            customer = await self.db.scalar(
                select(Customer).where(
                    Customer.tenant_id == self.tenant_id,
                    Customer.email == email,
                )
            )
            if customer:
                payments = (
                    await self.db.execute(
                        select(CustomerPayment).where(
                            CustomerPayment.tenant_id == self.tenant_id,
                            CustomerPayment.customer_id == customer.id,
                        ).limit(500)
                    )
                ).scalars().all()
                export["paiements"] = [
                    {
                        "numero": p.numero,
                        "date_encaissement": p.date_encaissement.isoformat(),
                        "montant": p.montant,
                        "mode": p.mode_encaissement,
                    }
                    for p in payments
                ]

        return export

    @staticmethod
    def _vers_csv(data: dict[str, Any]) -> str:
        """Convertit en CSV basique (sections séparées)."""
        lines: list[str] = []
        for section, contenu in data.items():
            lines.append(f"=== {section.upper()} ===")
            if isinstance(contenu, list) and contenu and isinstance(contenu[0], dict):
                # Header
                headers = list(contenu[0].keys())
                lines.append(",".join(headers))
                for row in contenu:
                    lines.append(",".join(
                        f'"{row.get(h, "")}"' for h in headers
                    ))
            elif isinstance(contenu, dict):
                for k, v in contenu.items():
                    lines.append(f"{k},{v}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _vers_xlsx(data: dict[str, Any]) -> bytes:
        """Convertit en Excel multi-feuilles."""
        try:
            from openpyxl import Workbook
        except ImportError:
            raise HTTPException(500, "openpyxl non installé")

        wb = Workbook()
        wb.remove(wb.active)

        for section, contenu in data.items():
            ws = wb.create_sheet(title=section[:31])
            if isinstance(contenu, list) and contenu and isinstance(contenu[0], dict):
                headers = list(contenu[0].keys())
                ws.append(headers)
                for row in contenu:
                    ws.append([row.get(h) for h in headers])
            elif isinstance(contenu, dict):
                for k, v in contenu.items():
                    ws.append([k, str(v)])

        buffer = BytesIO()
        wb.save(buffer)
        return buffer.getvalue()
