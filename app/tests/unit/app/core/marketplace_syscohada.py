"""
Référentiel Marketplace & Extensions — Écosystème MTech.

Objectifs :
- Permettre à des développeurs tiers d'étendre MTech
- Exposer un catalogue de plugins/integrations certifiés
- Isoler strictement l'exécution (sandbox)
- Permettre la monétisation (revenue share 70/30)

Inspirations : Shopify App Store, Stripe Apps, Slack Apps, WordPress Plugin.
"""
from __future__ import annotations

from typing import NamedTuple


# ─────────────────────────────────────────────────────────────────────────────
# Types d'extensions
# ─────────────────────────────────────────────────────────────────────────────
class TypeExtension:
    PLUGIN = "plugin"                       # Extension générique
    INTEGRATION = "integration"             # Connecteur externe (banque, ERP)
    DASHBOARD_WIDGET = "dashboard_widget"   # Widget pour dashboard BI
    REPORT_TEMPLATE = "report_template"     # Template de rapport
    PAYMENT_GATEWAY = "payment_gateway"     # Passerelle de paiement
    ACCOUNTING_BRIDGE = "accounting_bridge" # Pont avec autre logiciel comptable
    TAX_PROVIDER = "tax_provider"           # Fournisseur de calcul fiscal
    HR_CONNECTOR = "hr_connector"           # Connecteur SIRH
    ECOMMERCE_CONNECTOR = "ecommerce_connector"
    WHATSAPP_BOT = "whatsapp_bot"
    THEME = "theme"                         # Thème personnalisé (portail)


TYPES_EXTENSION = {
    TypeExtension.PLUGIN, TypeExtension.INTEGRATION, TypeExtension.DASHBOARD_WIDGET,
    TypeExtension.REPORT_TEMPLATE, TypeExtension.PAYMENT_GATEWAY,
    TypeExtension.ACCOUNTING_BRIDGE, TypeExtension.TAX_PROVIDER,
    TypeExtension.HR_CONNECTOR, TypeExtension.ECOMMERCE_CONNECTOR,
    TypeExtension.WHATSAPP_BOT, TypeExtension.THEME,
}


# ─────────────────────────────────────────────────────────────────────────────
# Catégories du catalogue
# ─────────────────────────────────────────────────────────────────────────────
class CategorieMarketplace:
    COMPTABILITE = "comptabilite"
    FISCALITE = "fiscalite"
    TRESORERIE = "tresorerie"
    VENTES = "ventes"
    ACHATS = "achats"
    STOCKS = "stocks"
    RH = "rh"
    ANALYTIQUE = "analytique"
    CONSOLIDATION = "consolidation"
    BANQUE = "banque"
    PAIEMENT = "paiement"
    DATA = "data"
    IA = "ia"
    SECURITE = "securite"
    PRODUCTIVITE = "productivite"
    COMMUNICATION = "communication"
    ECOMMERCE = "ecommerce"
    AUTRE = "autre"


# ─────────────────────────────────────────────────────────────────────────────
# Statuts d'une extension
# ─────────────────────────────────────────────────────────────────────────────
class StatutExtension:
    BROUILLON = "brouillon"
    EN_REVISION = "en_revision"        # En cours de validation MTech
    APPROUVEE = "approuvee"            # Publiée dans le catalogue
    REJETEE = "rejetee"                # Refusée par MTech
    SUSPENDUE = "suspendue"            # Retirée temporairement
    DEPRECIEE = "depreciee"            # Obsolète
    ARCHIVEE = "archivee"


# ─────────────────────────────────────────────────────────────────────────────
# Modèle de tarification
# ─────────────────────────────────────────────────────────────────────────────
class ModeleTarification:
    GRATUIT = "gratuit"
    ONE_TIME = "one_time"              # Achat unique
    ABONNEMENT = "abonnement"          # Abonnement mensuel/annuel
    FREEMIUM = "freemium"              # Version gratuite + version payante
    USAGE_BASED = "usage_based"        # Paiement à l'usage
    REVENUE_SHARE = "revenue_share"    # Partage de revenus


# Revenue share MTech (standard du marché)
REVENUE_SHARE_MTECH_PCT = 30.0         # MTech prend 30%
REVENUE_SHARE_PUBLISHER_PCT = 70.0     # Le publisher garde 70%


# ─────────────────────────────────────────────────────────────────────────────
# Permissions granulaires (déclarées dans le manifest)
# ─────────────────────────────────────────────────────────────────────────────
class PermissionExtension:
    # Lecture
    READ_ECRITURES = "read:ecritures"
    READ_CLIENTS = "read:clients"
    READ_FOURNISSEURS = "read:fournisseurs"
    READ_FACTURES = "read:factures"
    READ_TRESORERIE = "read:tresorerie"
    READ_STOCKS = "read:stocks"
    READ_RH = "read:rh"
    READ_ANALYTIQUE = "read:analytique"
    READ_RAPPORTS = "read:rapports"

    # Écriture
    WRITE_ECRITURES = "write:ecritures"
    WRITE_CLIENTS = "write:clients"
    WRITE_FACTURES = "write:factures"
    WRITE_TRESORERIE = "write:tresorerie"
    WRITE_STOCKS = "write:stocks"

    # Accès étendus (validation MTech renforcée)
    ACCESS_WEBHOOKS = "access:webhooks"          # Recevoir des webhooks
    ACCESS_SCHEDULED = "access:scheduled"        # Exécuter des tâches planifiées
    ACCESS_UI_EXTENSIONS = "access:ui_extensions" # Ajouter des éléments UI
    ACCESS_STORAGE = "access:storage"            # Stocker des fichiers
    ACCESS_EMAIL = "access:email"                # Envoyer des emails
    ACCESS_WHATSAPP = "access:whatsapp"          # Envoyer WhatsApp


# Permissions sensibles → validation manuelle obligatoire
PERMISSIONS_SENSIBLES = {
    PermissionExtension.WRITE_ECRITURES,
    PermissionExtension.WRITE_FACTURES,
    PermissionExtension.WRITE_TRESORERIE,
    PermissionExtension.ACCESS_WEBHOOKS,
    PermissionExtension.ACCESS_EMAIL,
    PermissionExtension.ACCESS_WHATSAPP,
}


# ─────────────────────────────────────────────────────────────────────────────
# Hooks (events auxquels un plugin peut s'abonner)
# ─────────────────────────────────────────────────────────────────────────────
class HookEvent:
    # Cycle de vie
    APP_INSTALLED = "app.installed"
    APP_UNINSTALLED = "app.uninstalled"
    APP_ENABLED = "app.enabled"
    APP_DISABLED = "app.disabled"

    # Comptabilité
    ECRITURE_CREATED = "ecriture.created"
    ECRITURE_VALIDATED = "ecriture.validated"
    ECRITURE_DELETED = "ecriture.deleted"

    # Ventes
    INVOICE_CREATED = "invoice.created"
    INVOICE_VALIDATED = "invoice.validated"
    INVOICE_PAID = "invoice.paid"
    PAYMENT_RECEIVED = "payment.received"

    # Achats
    PO_CREATED = "po.created"
    SUPPLIER_INVOICE_CREATED = "supplier_invoice.created"

    # Trésorerie
    BANK_TRANSACTION_RECEIVED = "bank.transaction_received"
    RECONCILIATION_DONE = "reconciliation.done"

    # Stocks
    STOCK_MOVEMENT = "stock.movement"
    STOCK_LOW = "stock.low"

    # RH
    EMPLOYEE_CREATED = "employee.created"
    PAYSLIP_GENERATED = "payslip.generated"

    # FNE
    FNE_CERTIFIED = "fne.certified"

    # Menu / UI
    UI_MENU_RENDER = "ui.menu_render"      # Plugin ajoute un item de menu
    UI_DASHBOARD_WIDGETS = "ui.dashboard_widgets"
    UI_INVOICE_ACTIONS = "ui.invoice_actions"  # Bouton custom sur factures


HOOKS_DISPONIBLES = {
    v for k, v in HookEvent.__dict__.items()
    if not k.startswith("_") and isinstance(v, str)
}


# ─────────────────────────────────────────────────────────────────────────────
# Types de déclencheurs (triggers)
# ─────────────────────────────────────────────────────────────────────────────
class TypeTrigger:
    WEBHOOK = "webhook"                # POST HTTP vers URL externe
    SCHEDULED = "scheduled"            # Cron (équivalent ARQ)
    MANUAL = "manual"                  # Déclenché par l'utilisateur
    EVENT = "event"                    # Event bus interne


# ─────────────────────────────────────────────────────────────────────────────
# Statuts d'installation
# ─────────────────────────────────────────────────────────────────────────────
class StatutInstallation:
    EN_COURS = "en_cours"
    ACTIVE = "active"
    DESACTIVEE = "desactivee"
    ERREUR = "erreur"
    DESINSTALLEE = "desinstallee"
    EXPIREE = "expiree"                # Abonnement plugin expiré


# ─────────────────────────────────────────────────────────────────────────────
# Statuts de publisher
# ─────────────────────────────────────────────────────────────────────────────
class StatutPublisher:
    EN_ATTENTE = "en_attente"          # En cours de validation
    VERIFIE = "verifie"
    PARTENAIRE = "partenaire"           # Publisher certifié
    SUSPENDU = "suspendu"
    BANNI = "banni"


# ─────────────────────────────────────────────────────────────────────────────
# Niveaux de certification
# ─────────────────────────────────────────────────────────────────────────────
class Certification:
    NON_CERTIFIE = "non_certifie"
    VERIFIE = "verifie"                 # Code review basique
    CERTIFIE = "certifie"               # Audit de sécurité complet
    PARTENAIRE_OFFICIEL = "partenaire_officiel"


# ─────────────────────────────────────────────────────────────────────────────
# Types de licenses
# ─────────────────────────────────────────────────────────────────────────────
class TypeLicense:
    PROPRIETAIRE = "proprietaire"       # Code fermé
    OPEN_SOURCE = "open_source"         # MIT, Apache, GPL
    FREEMIUM = "freemium"


# ─────────────────────────────────────────────────────────────────────────────
# Environnements d'exécution
# ─────────────────────────────────────────────────────────────────────────────
class EnvironnementPlugin:
    SANDBOX = "sandbox"                 # Isolation totale
    TRUSTED = "trusted"                 # Accès étendu (partenaires certifiés)


# ─────────────────────────────────────────────────────────────────────────────
# Limites d'exécution
# ─────────────────────────────────────────────────────────────────────────────
class LimitesExecution:
    TIMEOUT_HOOK_S = 10                 # Timeout d'un hook
    MAX_PAYLOAD_KB = 512                # Payload max
    MAX_RETRIES = 3                     # Retries sur échec
    MAX_CALLS_PER_MINUTE = 60           # Rate limit plugin
    MAX_CALLS_PER_DAY = 10_000          # Quota journalier
    MAX_STORAGE_MB = 100                # Stockage plugin
    MEMORY_LIMIT_MB = 256               # Limite mémoire


# ─────────────────────────────────────────────────────────────────────────────
# Templates de manifest (format plugin.yaml)
# ─────────────────────────────────────────────────────────────────────────────
MANIFEST_EXEMPLE = {
    "slug": "wave-bank-sync",
    "nom": "Wave Bank Synchronisation",
    "version": "1.2.3",
    "description": "Synchronise automatiquement les transactions Wave Bank vers MTech",
    "auteur": "MTech Labs",
    "email": "dev@mtech.ci",
    "site_web": "https://mtech.ci",
    "licence": "proprietaire",
    "type_extension": "integration",
    "categorie": "banque",
    "tarification": {
        "modele": "abonnement",
        "prix_mensuel_xof": 5000,
        "prix_annuel_xof": 50000,
        "essai_gratuit_jours": 14,
    },
    "permissions": [
        "read:clients",
        "read:tresorerie",
        "write:tresorerie",
        "access:webhooks",
    ],
    "hooks": [
        "invoice.created",
        "payment.received",
    ],
    "webhooks_entrants": [
        {"event": "wave.transaction.created", "url": "/webhooks/wave"}
    ],
    "taches_planifiees": [
        {"nom": "sync_transactions", "cron": "0 */2 * * *"},
    ],
    "ui_extensions": {
        "menu": [
            {"label": "Wave Bank", "icon": "landmark", "path": "/apps/wave-bank"}
        ],
        "dashboard_widgets": [
            {"id": "wave-balance", "label": "Solde Wave", "component": "WaveBalanceWidget"}
        ],
    },
    "config_schema": {
        "wave_api_key": {"type": "string", "required": True, "encrypted": True},
        "wave_merchant_id": {"type": "string", "required": True},
        "auto_sync": {"type": "boolean", "default": True},
    },
    "cgu_url": "https://mtech.ci/apps/wave-bank/cgu",
    "politique_confidentialite_url": "https://mtech.ci/apps/wave-bank/privacy",
    "support_url": "https://support.mtech.ci",
}


# ─────────────────────────────────────────────────────────────────────────────
# Catégories de transactions financières (marketplace)
# ─────────────────────────────────────────────────────────────────────────────
class TypeTransactionMarketplace:
    ACHAT_PLUGIN = "achat_plugin"
    ABONNEMENT_PLUGIN = "abonnement_plugin"
    REVERSEMENT_PUBLISHER = "reversement_publisher"
    COMMISSION_MTECH = "commission_mtech"
    REMBOURSEMENT = "remboursement"


# ─────────────────────────────────────────────────────────────────────────────
# Délais de remboursement
# ─────────────────────────────────────────────────────────────────────────────
DELAI_REMBOURSEMENT_JOURS = 14         # Droit de rétractation
DELAI_REVERSEMENT_PUBLISHER_JOURS = 30  # MTech verse le publisher 30j après


# ─────────────────────────────────────────────────────────────────────────────
# Seuils de sécurité
# ─────────────────────────────────────────────────────────────────────────────
SEUIL_SIGNALEMENTS_SUSPENSION = 5      # 5 signalements → review auto
SEUIL_ERREURS_SUSPENSION = 50          # 50 erreurs/heure → suspension auto
