"""Exceptions métier — réponses HTTP structurées et cohérentes."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException


class DomainError(HTTPException):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            status_code=status_code,
            detail={"code": code, "message": message, "details": details or {}},
        )
        self.code = code
        self.message = message
        self.details = details or {}


class SubscriptionExpiredError(DomainError):
    def __init__(self, message: str = "Abonnement expiré — compte en lecture seule") -> None:
        super().__init__("SUBSCRIPTION_EXPIRED", message, status_code=402)


class TenancyError(DomainError):
    def __init__(self, message: str) -> None:
        super().__init__("TENANCY_ERROR", message, status_code=403)


class NotFoundError(DomainError):
    def __init__(self, resource: str, ident: str | None = None) -> None:
        msg = f"{resource} introuvable" + (f" : {ident}" if ident else "")
        super().__init__("NOT_FOUND", msg, status_code=404)


class ConflictError(DomainError):
    def __init__(self, message: str) -> None:
        super().__init__("CONFLICT", message, status_code=409)
