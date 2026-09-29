"""
Référentiel API publique & Webhooks sortants.

Objectifs :
- Exposer les données MTech à des partenaires (banques, experts-comptables, ERP tiers)
- Recevoir des événements métier en temps réel via webhooks signés
- Tracer tous les accès pour audit et facturation
- Rate limiter par client et par endpoint

Inspiration : Stripe API, GitHub API, Twilio.
"""
from __future__ import annotations

from typing import NamedTuple


# ─────────────────────────────────────────────────────────────────────────────
# Types de clients API
# ─────────────────────────────────────────────────────────────────────────────
class TypeClientAPI:
    PARTENAIRE = "partenaire"                   # Banque, fintech, ERP
    EXPERT_COMPTABLE = "expert_comptable"       # Cabinet externe
    INTEGRATION_INTERNE = "integration_interne" # Microservice MTech
    DEVELOPPEUR = "developpeur"                 # Test/dev
    AUDITEUR = "auditeur"                       # Commissaire aux comptes


TYPES_CLIENT_API = {
    TypeClientAPI.PARTENAIRE,
    TypeClientAPI.EXPERT_COMPTABLE,
    TypeClientAPI.INTEGRATION_INTERNE,
    TypeClientAPI.DEVELOPPEUR,
    TypeClientAPI.AUDITEUR,
}


# ─────────────────────────────────────────────────────────────────────────────
# Statuts de clé API
# ─────────────────────────────────────────────────────────────────────────────
class StatutCleAPI:
    ACTIVE = "active"
    SUSPENDUE = "suspendue"
    EXPIREE = "expiree"
    REVOQUEE = "revoquee"


# ─────────────────────────────────────────────────────────────────────────────
# Environnements
# ─────────────────────────────────────────────────────────────────────────────
class EnvironnementAPI:
    SANDBOX = "sandbox"        # Clé commence par mtech_test_
    PRODUCTION = "production"  # Clé commence par mtech_live_


# ─────────────────────────────────────────────────────────────────────────────
# Scopes granulaires (RBAC de l'API publique)
# ─────────────────────────────────────────────────────────────────────────────
class Scope:
    # Lecture
    READ_COMPTES = "read:comptes"
    READ_ECRITURES = "read:ecritures"
    READ_CLIENTS = "read:clients"
    READ_FOURNISSEURS = "read:fournisseurs"
    READ_FACTURES_CLIENTS = "read:factures_clients"
    READ_FACTURES_FOURNISSEURS = "read:factures_fournisseurs"
    READ_TRESORERIE = "read:tresorerie"
    READ_STOCKS = "read:stocks"
    READ_IMMOBILISATIONS = "read:immobilisations"
    READ_PROJETS = "read:projets"
    READ_EMPLOYES = "read:employes"
    READ_PAIE = "read:paie"
    READ_BUDGETS = "read:budgets"
    READ_FNE = "read:fne"
    READ_AUDIT = "read:audit"
    READ_RAPPORTS = "read:rapports"

    # Écriture
    WRITE_ECRITURES = "write:ecritures"
    WRITE_CLIENTS = "write:clients"
    WRITE_FOURNISSEURS = "write:fournisseurs"
    WRITE_FACTURES_CLIENTS = "write:factures_clients"
    WRITE_FACTURES_FOURNISSEURS = "write:factures_fournisseurs"
    WRITE_PAIEMENTS = "write:paiements"
    WRITE_STOCKS = "write:stocks"
    WRITE_PROJETS = "write:projets"

    # Administration
    ADMIN_WEBHOOKS = "admin:webhooks"
    ADMIN_API_KEYS = "admin:api_keys"
    ADMIN_USERS = "admin:users"

    # Comptabilité analytique
    READ_ANALYTIQUE = "read:analytique"
    WRITE_ANALYTIQUE = "write:analytique"


SCOPES_LECTURE = {
    Scope.READ_COMPTES, Scope.READ_ECRITURES, Scope.READ_CLIENTS,
    Scope.READ_FOURNISSEURS, Scope.READ_FACTURES_CLIENTS,
    Scope.READ_FACTURES_FOURNISSEURS, Scope.READ_TRESORERIE,
    Scope.READ_STOCKS, Scope.READ_IMMOBILISATIONS, Scope.READ_PROJETS,
    Scope.READ_EMPLOYES, Scope.READ_PAIE, Scope.READ_BUDGETS,
    Scope.READ_FNE, Scope.READ_AUDIT, Scope.READ_RAPPORTS,
    Scope.READ_ANALYTIQUE,
}

SCOPES_ECRITURE = {
    Scope.WRITE_ECRITURES, Scope.WRITE_CLIENTS, Scope.WRITE_FOURNISSEURS,
    Scope.WRITE_FACTURES_CLIENTS, Scope.WRITE_FACTURES_FOURNISSEURS,
    Scope.WRITE_PAIEMENTS, Scope.WRITE_STOCKS, Scope.WRITE_PROJETS,
    Scope.WRITE_ANALYTIQUE,
}

SCOPES_ADMIN = {
    Scope.ADMIN_WEBHOOKS, Scope.ADMIN_API_KEYS, Scope.ADMIN_USERS,
}

TOUS_SCOPES = SCOPES_LECTURE | SCOPES_ECRITURE | SCOPES_ADMIN


# ─────────────────────────────────────────────────────────────────────────────
# Types d'événements webhook (sortants)
# ─────────────────────────────────────────────────────────────────────────────
class WebhookEvent:
    # Écritures comptables
    ECRITURE_CREATED = "ecriture.created"
    ECRITURE_VALIDATED = "ecriture.validated"
    ECRITURE_DELETED = "ecriture.deleted"

    # Ventes
    INVOICE_CREATED = "invoice.created"
    INVOICE_VALIDATED = "invoice.validated"
    INVOICE_PAID = "invoice.paid"
    INVOICE_OVERDUE = "invoice.overdue"
    INVOICE_CANCELLED = "invoice.cancelled"
    CREDIT_NOTE_CREATED = "credit_note.created"

    # Achats
    PO_CREATED = "purchase_order.created"
    PO_VALIDATED = "purchase_order.validated"
    SUPPLIER_INVOICE_CREATED = "supplier_invoice.created"
    SUPPLIER_INVOICE_PAID = "supplier_invoice.paid"

    # Paiements
    PAYMENT_RECEIVED = "payment.received"
    PAYMENT_SENT = "payment.sent"

    # Trésorerie
    BANK_RECONCILED = "bank.reconciled"
    CASH_FLOW_ALERT = "cash_flow.alert"

    # Clients / Fournisseurs
    CUSTOMER_CREATED = "customer.created"
    CUSTOMER_UPDATED = "customer.updated"
    SUPPLIER_CREATED = "supplier.created"

    # FNE
    FNE_CERTIFIED = "fne.certified"
    FNE_REJECTED = "fne.rejected"
    FNE_CANCELLED = "fne.cancelled"

    # Stocks
    STOCK_LOW = "stock.low"
    STOCK_OUT = "stock.out"
    INVENTORY_COMPLETED = "inventory.completed"

    # Immobilisations
    ASSET_CREATED = "asset.created"
    ASSET_DISPOSED = "asset.disposed"

    # Projets
    PROJECT_CREATED = "project.created"
    PROJECT_COMPLETED = "project.completed"
    MILESTONE_REACHED = "milestone.reached"

    # RH
    EMPLOYEE_CREATED = "employee.created"
    LEAVE_REQUESTED = "leave.requested"
    LEAVE_APPROVED = "leave.approved"
    PAYSLIP_AVAILABLE = "payslip.available"

    # Abonnement
    SUBSCRIPTION_RENEWED = "subscription.renewed"
    SUBSCRIPTION_EXPIRED = "subscription.expired"

    # Audit
    AUDIT_FINDING = "audit.finding"
    AUDIT_CRITICAL = "audit.critical"

    # Portail
    PORTAL_PAYMENT_RECEIVED = "portal.payment_received"


TOUS_WEBHOOK_EVENTS = {
    v for k, v in WebhookEvent.__dict__.items()
    if not k.startswith("_") and isinstance(v, str)
}


# ─────────────────────────────────────────────────────────────────────────────
# Statuts de livraison webhook
# ─────────────────────────────────────────────────────────────────────────────
class StatutWebhookDelivery:
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    EXHAUSTED = "exhausted"      # Toutes les tentatives épuisées
    DLQ = "dlq"                  # Dead Letter Queue


# ─────────────────────────────────────────────────────────────────────────────
# Politique de retry webhook
# ─────────────────────────────────────────────────────────────────────────────
WEBHOOK_RETRY_DELAYS_S = [
    10,      # 10 secondes
    60,      # 1 minute
    300,     # 5 minutes
    1800,    # 30 minutes
    7200,    # 2 heures
    43200,   # 12 heures
    86400,   # 24 heures
]

WEBHOOK_TIMEOUT_S = 30
WEBHOOK_MAX_BODY_SIZE_KB = 256
WEBHOOK_SIGNATURE_HEADER = "X-MTech-Signature"
WEBHOOK_TIMESTAMP_HEADER = "X-MTech-Timestamp"
WEBHOOK_ID_HEADER = "X-MTech-Delivery-Id"
WEBHOOK_EVENT_HEADER = "X-MTech-Event"
WEBHOOK_TOLERANCE_S = 300        # Tolérance timestamp anti-replay


# ─────────────────────────────────────────────────────────────────────────────
# Rate limiting
# ─────────────────────────────────────────────────────────────────────────────
class RateLimits:
    # Par défaut : 1000 requêtes / minute
    DEFAULT_PER_MINUTE = 1000
    DEFAULT_PER_HOUR = 30_000
    DEFAULT_PER_DAY = 500_000

    # Par type de client
    PARTENAIRE_PER_MINUTE = 5000
    EXPERT_COMPTABLE_PER_MINUTE = 500
    DEVELOPPEUR_PER_MINUTE = 100
    INTEGRATION_INTERNE_PER_MINUTE = 10_000
    AUDITEUR_PER_MINUTE = 200

    # Burst
    BURST_MULTIPLIER = 2.0       # Autorise un burst de 2x


# ─────────────────────────────────────────────────────────────────────────────
# Formats d'authentification
# ─────────────────────────────────────────────────────────────────────────────
class AuthMethod:
    API_KEY_BEARER = "api_key_bearer"        # Authorization: Bearer mtech_live_...
    API_KEY_HEADER = "api_key_header"        # X-API-Key: mtech_live_...
    OAUTH2 = "oauth2"                        # OAuth 2.0 client_credentials


# ─────────────────────────────────────────────────────────────────────────────
# Versioning API
# ─────────────────────────────────────────────────────────────────────────────
class APIVersion:
    V1 = "v1"
    V2 = "v2"     # future

VERSIONS_SUPPORTEES = {APIVersion.V1}
VERSION_DEFAUT = APIVersion.V1
VERSION_HEADER = "X-API-Version"


# ─────────────────────────────────────────────────────────────────────────────
# Codes d'erreur normalisés
# ─────────────────────────────────────────────────────────────────────────────
class APIErrorCode:
    UNAUTHORIZED = "unauthorized"
    INVALID_API_KEY = "invalid_api_key"
    EXPIRED_API_KEY = "expired_api_key"
    SUSPENDED_API_KEY = "suspended_api_key"
    INSUFFICIENT_SCOPE = "insufficient_scope"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    RESOURCE_NOT_FOUND = "resource_not_found"
    VALIDATION_ERROR = "validation_error"
    CONFLICT = "conflict"
    INTERNAL_ERROR = "internal_error"
    SERVICE_UNAVAILABLE = "service_unavailable"
    TIMEOUT = "timeout"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"


# ─────────────────────────────────────────────────────────────────────────────
# Quotas d'usage (facturation)
# ─────────────────────────────────────────────────────────────────────────────
class QuotasAPI:
    FREE_REQUESTS_PER_MONTH = 10_000
    PARTENAIRE_REQUESTS_PER_MONTH = 1_000_000
    EXPERT_REQUESTS_PER_MONTH = 100_000
    INTEGRATION_REQUESTS_PER_MONTH = 10_000_000


# ─────────────────────────────────────────────────────────────────────────────
# Configuration du sandbox
# ─────────────────────────────────────────────────────────────────────────────
class SandboxConfig:
    MAX_REQUESTS_PER_DAY = 1000
    DATA_RESET_HOURS = 168       # Reset toutes les semaines
    ENABLED = True


# ─────────────────────────────────────────────────────────────────────────────
# Statistiques
# ─────────────────────────────────────────────────────────────────────────────
class GranulariteUsage:
    MINUTE = "minute"
    HEURE = "heure"
    JOUR = "jour"
    MOIS = "mois"
