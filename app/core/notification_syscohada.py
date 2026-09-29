"""
Référentiel Notifications & Communications — Multi-canal.

Providers supportés :
- Email : SendGrid, Postmark, SMTP générique
- SMS : Orange SMS API CI, MTN, Twilio, Africa's Talking
- WhatsApp : Meta Cloud API (déjà brique 12)
- Push : Firebase Cloud Messaging (FCM)
- In-app : notifications stockées en DB

Fallback intelligent :
Si le canal préféré échoue (ou est indisponible), on bascule sur le canal
suivant selon la hiérarchie définie par l'utilisateur et la criticité.
"""
from __future__ import annotations

from typing import NamedTuple


# ─────────────────────────────────────────────────────────────────────────────
# Canaux disponibles
# ─────────────────────────────────────────────────────────────────────────────
class Canal:
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    PUSH = "push"
    IN_APP = "in_app"


CANAUX = {Canal.EMAIL, Canal.SMS, Canal.WHATSAPP, Canal.PUSH, Canal.IN_APP}


# ─────────────────────────────────────────────────────────────────────────────
# Providers par canal
# ─────────────────────────────────────────────────────────────────────────────
class ProviderEmail:
    SENDGRID = "sendgrid"
    POSTMARK = "postmark"
    SMTP = "smtp"
    MAILGUN = "mailgun"


class ProviderSMS:
    ORANGE_CI = "orange_ci"
    MTN_CI = "mtn_ci"
    TWILIO = "twilio"
    AFRICASTALKING = "africastalking"


class ProviderPush:
    FCM = "fcm"
    APNS = "apns"           # iOS natif
    WEB_PUSH = "web_push"


class ProviderWhatsApp:
    META = "meta"
    TWILIO = "twilio"


# ─────────────────────────────────────────────────────────────────────────────
# Types de notification (par domaine métier)
# ─────────────────────────────────────────────────────────────────────────────
class TypeNotification:
    # Auth & compte
    INVITATION_USER = "invitation_user"
    WELCOME = "welcome"
    PASSWORD_RESET = "password_reset"
    MFA_ENABLED = "mfa_enabled"
    SECURITY_ALERT = "security_alert"
    LOGIN_NEW_DEVICE = "login_new_device"

    # Abonnement
    SUBSCRIPTION_ACTIVATED = "subscription_activated"
    SUBSCRIPTION_EXPIRING = "subscription_expiring"
    SUBSCRIPTION_EXPIRED = "subscription_expired"
    SUBSCRIPTION_RENEWED = "subscription_renewed"
    INVOICE_AVAILABLE = "invoice_available"

    # Comptabilité
    ECRITURE_VALIDATED = "ecriture_validated"
    ECRITURE_REJECTED = "ecriture_rejected"
    EXERCICE_CLOTURE = "exercice_cloture"
    FNE_CERTIFIED = "fne_certified"
    FNE_REJECTED = "fne_rejected"
    STICKER_LOW = "sticker_low"

    # Ventes
    NEW_ORDER = "new_order"
    ORDER_CONFIRMED = "order_confirmed"
    INVOICE_CREATED = "invoice_created"
    INVOICE_DUE_SOON = "invoice_due_soon"
    INVOICE_OVERDUE = "invoice_overdue"
    PAYMENT_RECEIVED = "payment_received"
    PAYMENT_LATE = "payment_late"

    # Achats
    PO_CREATED = "po_created"
    PO_RECEIVED = "po_received"
    SUPPLIER_INVOICE_SUBMITTED = "supplier_invoice_submitted"
    SUPPLIER_INVOICE_VALIDATED = "supplier_invoice_validated"

    # Stocks
    STOCK_LOW = "stock_low"
    STOCK_OUT = "stock_out"
    INVENTORY_DONE = "inventory_done"

    # Trésorerie
    CASH_FLOW_ALERT = "cash_flow_alert"
    BANK_RECONCILIATION_DONE = "bank_reconciliation_done"

    # RH
    LEAVE_REQUEST_SUBMITTED = "leave_request_submitted"
    LEAVE_REQUEST_APPROVED = "leave_request_approved"
    LEAVE_REQUEST_REJECTED = "leave_request_rejected"
    PAYSLIP_AVAILABLE = "payslip_available"
    CONTRACT_EXPIRING = "contract_expiring"
    REVIEW_SCHEDULED = "review_scheduled"

    # Projets
    PROJECT_MILESTONE = "project_milestone"
    PROJECT_BUDGET_ALERT = "project_budget_alert"
    PROGRESS_BILLING_DUE = "progress_billing_due"

    # Audit
    AUDIT_FINDING = "audit_finding"
    AUDIT_CRITICAL = "audit_critical"
    COMPLIANCE_REPORT = "compliance_report"

    # Support
    TICKET_CREATED = "ticket_created"
    TICKET_UPDATED = "ticket_updated"
    TICKET_RESOLVED = "ticket_resolved"
    CHATBOT_ESCALATION = "chatbot_escalation"

    # Portail
    PORTAL_INVITATION = "portal_invitation"
    PORTAL_PAYMENT_LINK = "portal_payment_link"
    PORTAL_PAYMENT_CONFIRMED = "portal_payment_confirmed"

    # Marketing
    NEWSLETTER = "newsletter"
    PRODUCT_UPDATE = "product_update"
    PROMOTION = "promotion"
    TIPS = "tips"
    WEBINAR_INVITE = "webinar_invite"

    # Système
    SYSTEM_MAINTENANCE = "system_maintenance"
    BULK_OPERATION_DONE = "bulk_operation_done"


# ─────────────────────────────────────────────────────────────────────────────
# Criticité (détermine le fallback et la priorité)
# ─────────────────────────────────────────────────────────────────────────────
class Criticite:
    INFO = "info"                 # Pas de fallback, opt-in requis
    NORMALE = "normale"           # Fallback léger
    HAUTE = "haute"               # Fallback agressif
    CRITIQUE = "critique"         # Ignore les préférences, tous canaux


# ─────────────────────────────────────────────────────────────────────────────
# Statuts de livraison
# ─────────────────────────────────────────────────────────────────────────────
class StatutNotification:
    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    CLICKED = "clicked"
    FAILED = "failed"
    BOUNCED = "bounced"
    SUPPRESSED = "suppressed"     # Utilisateur a opt-out
    RETRYING = "retrying"


# ─────────────────────────────────────────────────────────────────────────────
# Statuts de campagne
# ─────────────────────────────────────────────────────────────────────────────
class StatutCampagne:
    BROUILLON = "brouillon"
    PLANIFIEE = "planifiee"
    EN_COURS = "en_cours"
    PAUSE = "pause"
    TERMINEE = "terminee"
    ANNULEE = "annulee"


# ─────────────────────────────────────────────────────────────────────────────
# Statuts de template
# ─────────────────────────────────────────────────────────────────────────────
class StatutTemplate:
    BROUILLON = "brouillon"
    EN_REVISION = "en_revision"
    PUBLIE = "publie"
    DEPRECIE = "deprecie"
    ARCHIVE = "archive"


# ─────────────────────────────────────────────────────────────────────────────
# Types de templates
# ─────────────────────────────────────────────────────────────────────────────
class TypeTemplate:
    TRANSACTIONNEL = "transactionnel"   # Facture, paiement, etc.
    MARKETING = "marketing"             # Newsletter, promo
    SYSTEME = "systeme"                 # Maintenance, incident
    SECURITE = "securite"               # Login, reset, alerte


# ─────────────────────────────────────────────────────────────────────────────
# Priorités de la file
# ─────────────────────────────────────────────────────────────────────────────
class PrioriteEnvoi:
    CRITIQUE = 1         # Envoi immédiat
    HAUTE = 2            # < 1 min
    NORMALE = 3          # < 5 min
    BASSE = 4            # < 1h
    BULK = 5             # Best effort


# ─────────────────────────────────────────────────────────────────────────────
# Quotas et limites
# ─────────────────────────────────────────────────────────────────────────────
class Quotas:
    EMAIL_PAR_JOUR_PAR_TENANT = 50_000
    SMS_PAR_JOUR_PAR_TENANT = 5_000
    WHATSAPP_PAR_JOUR_PAR_TENANT = 2_000
    PUSH_PAR_JOUR_PAR_TENANT = 100_000

    EMAIL_PAR_MINUTE_PAR_PROVIDER = 500
    SMS_PAR_MINUTE_PAR_PROVIDER = 60
    WHATSAPP_PAR_MINUTE_PAR_PROVIDER = 80

    # Anti-spam : max N notifications du même type / heure / user
    MAX_MEME_TYPE_PAR_HEURE = 5
    MAX_MARKETING_PAR_JOUR = 3
    MAX_MARKETING_PAR_SEMAINE = 10


# ─────────────────────────────────────────────────────────────────────────────
# Coût approximatif par canal (FCFA)
# ─────────────────────────────────────────────────────────────────────────────
class CoutUnitaire:
    EMAIL = 1          # ~0.001 USD
    SMS = 25           # 25 FCFA par SMS CI
    WHATSAPP = 12      # ~0.02 USD (template utility)
    PUSH = 0
    IN_APP = 0


# ─────────────────────────────────────────────────────────────────────────────
# Hiérarchie de fallback par criticité
# ─────────────────────────────────────────────────────────────────────────────
HIERARCHIE_FALLBACK: dict[str, list[str]] = {
    Criticite.INFO: [Canal.EMAIL, Canal.IN_APP],
    Criticite.NORMALE: [Canal.EMAIL, Canal.IN_APP, Canal.PUSH],
    Criticite.HAUTE: [Canal.EMAIL, Canal.WHATSAPP, Canal.SMS, Canal.PUSH],
    Criticite.CRITIQUE: [Canal.SMS, Canal.WHATSAPP, Canal.EMAIL, Canal.PUSH],
}


# ─────────────────────────────────────────────────────────────────────────────
# Types d'événements analytics
# ─────────────────────────────────────────────────────────────────────────────
class EventTracking:
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    OPENED = "opened"
    CLICKED = "clicked"
    BOUNCED = "bounced"
    COMPLAINED = "complained"
    UNSUBSCRIBED = "unsubscribed"
    FAILED = "failed"


# ─────────────────────────────────────────────────────────────────────────────
# Variables de template autorisées par contexte
# ─────────────────────────────────────────────────────────────────────────────
VARIABLES_CONTEXTE: dict[str, list[str]] = {
    "user": ["prenom", "nom", "email", "role", "tenant_nom"],
    "invoice": ["numero", "date_facture", "date_echeance", "total_ttc", "solde_du", "lien_pdf"],
    "payment": ["numero", "montant", "date_paiement", "mode_paiement"],
    "subscription": ["plan", "periode_fin", "jours_restants", "montant"],
    "leave": ["reference", "date_debut", "date_fin", "nb_jours", "statut"],
    "project": ["code", "libelle", "avancement_pct", "budget"],
    "fne": ["numero_facture", "fne_reference", "qr_code_url"],
    "link": ["url", "label", "expires_at"],
}


# ─────────────────────────────────────────────────────────────────────────────
# Providers par défaut (config fallback)
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_PROVIDERS: dict[str, str] = {
    Canal.EMAIL: ProviderEmail.SENDGRID,
    Canal.SMS: ProviderSMS.ORANGE_CI,
    Canal.WHATSAPP: ProviderWhatsApp.META,
    Canal.PUSH: ProviderPush.FCM,
    Canal.IN_APP: "internal",
}


# ─────────────────────────────────────────────────────────────────────────────
# Templates par défaut (à seed)
# ─────────────────────────────────────────────────────────────────────────────
TEMPLATES_SEED: list[dict[str, str]] = [
    {
        "code": "WELCOME_USER",
        "canal": Canal.EMAIL,
        "type_template": TypeTemplate.TRANSACTIONNEL,
        "type_notification": TypeNotification.WELCOME,
        "sujet": "Bienvenue sur {{ tenant_nom }}",
        "contenu_html": """
            <h1>Bonjour {{ prenom }},</h1>
            <p>Bienvenue sur {{ tenant_nom }} ! Votre compte est maintenant actif.</p>
            <p><a href="{{ lien_app }}">Accéder à mon espace</a></p>
            <p>Cordialement,<br>L'équipe {{ tenant_nom }}</p>
        """,
    },
    {
        "code": "INVITATION_USER",
        "canal": Canal.EMAIL,
        "type_template": TypeTemplate.TRANSACTIONNEL,
        "type_notification": TypeNotification.INVITATION_USER,
        "sujet": "Vous êtes invité(e) à rejoindre {{ tenant_nom }}",
        "contenu_html": """
            <h1>Bonjour,</h1>
            <p>{{ inviteur_nom }} vous invite à rejoindre <strong>{{ tenant_nom }}</strong>
               en tant que <strong>{{ role }}</strong>.</p>
            <p><a href="{{ lien_invitation }}">Accepter l'invitation</a></p>
            <p>Ce lien expire dans {{ expire_h }} heures.</p>
        """,
    },
    {
        "code": "PASSWORD_RESET",
        "canal": Canal.EMAIL,
        "type_template": TypeTemplate.SECURITE,
        "type_notification": TypeNotification.PASSWORD_RESET,
        "sujet": "Réinitialisation de votre mot de passe",
        "contenu_html": """
            <h1>Bonjour {{ prenom }},</h1>
            <p>Vous avez demandé la réinitialisation de votre mot de passe.</p>
            <p><a href="{{ lien_reset }}">Réinitialiser mon mot de passe</a></p>
            <p>Ce lien expire dans {{ expire_h }} heures. Si vous n'êtes pas à l'origine
               de cette demande, ignorez cet email.</p>
        """,
    },
    {
        "code": "INVOICE_DUE_SOON_SMS",
        "canal": Canal.SMS,
        "type_template": TypeTemplate.TRANSACTIONNEL,
        "type_notification": TypeNotification.INVOICE_DUE_SOON,
        "sujet": None,
        "contenu_html": "Rappel : facture {{ numero }} de {{ total_ttc }} FCFA à régler avant le {{ date_echeance }}. {{ tenant_nom }}",
    },
    {
        "code": "INVOICE_OVERDUE_WHATSAPP",
        "canal": Canal.WHATSAPP,
        "type_template": TypeTemplate.TRANSACTIONNEL,
        "type_notification": TypeNotification.INVOICE_OVERDUE,
        "sujet": None,
        "contenu_html": (
            "Bonjour {{ prenom }},\n\n"
            "La facture *{{ numero }}* de *{{ total_ttc }} FCFA* est en retard "
            "de paiement depuis le {{ date_echeance }}.\n\n"
            "Merci de régulariser rapidement. Contactez-nous pour toute question.\n\n"
            "— {{ tenant_nom }}"
        ),
    },
    {
        "code": "SUBSCRIPTION_EXPIRING",
        "canal": Canal.EMAIL,
        "type_template": TypeTemplate.TRANSACTIONNEL,
        "type_notification": TypeNotification.SUBSCRIPTION_EXPIRING,
        "sujet": "Votre abonnement expire dans {{ jours_restants }} jours",
        "contenu_html": """
            <h1>Bonjour {{ prenom }},</h1>
            <p>Votre abonnement <strong>{{ plan }}</strong> arrive à échéance le
               <strong>{{ periode_fin }}</strong>.</p>
            <p>Renouvelez pour continuer à utiliser {{ tenant_nom }}.</p>
            <p><a href="{{ lien_renouvellement }}">Renouveler mon abonnement</a></p>
        """,
    },
    {
        "code": "SECURITY_ALERT_NEW_DEVICE",
        "canal": Canal.EMAIL,
        "type_template": TypeTemplate.SECURITE,
        "type_notification": TypeNotification.LOGIN_NEW_DEVICE,
        "sujet": "Nouvelle connexion depuis un appareil inconnu",
        "contenu_html": """
            <h1>Bonjour {{ prenom }},</h1>
            <p>Une connexion à votre compte a été détectée depuis un nouvel appareil :</p>
            <ul>
              <li>IP : {{ ip }}</li>
              <li>Appareil : {{ user_agent }}</li>
              <li>Date : {{ date_connexion }}</li>
            </ul>
            <p>Si ce n'est pas vous, changez immédiatement votre mot de passe.</p>
        """,
    },
    {
        "code": "LEAVE_APPROVED",
        "canal": Canal.EMAIL,
        "type_template": TypeTemplate.TRANSACTIONNEL,
        "type_notification": TypeNotification.LEAVE_REQUEST_APPROVED,
        "sujet": "Votre demande de congé a été validée",
        "contenu_html": """
            <h1>Bonjour {{ prenom }},</h1>
            <p>Votre demande de congé du <strong>{{ date_debut }}</strong>
               au <strong>{{ date_fin }}</strong> ({{ nb_jours }} jours) a été validée.</p>
            <p>Bon repos !</p>
        """,
    },
    {
        "code": "STOCK_LOW_ALERT",
        "canal": Canal.IN_APP,
        "type_template": TypeTemplate.TRANSACTIONNEL,
        "type_notification": TypeNotification.STOCK_LOW,
        "sujet": "Stock faible : {{ designation }}",
        "contenu_html": "Stock actuel de {{ designation }} : {{ quantite }} (seuil : {{ seuil }}). Pensez à réapprovisionner.",
    },
    {
        "code": "AUDIT_CRITICAL_FINDING",
        "canal": Canal.EMAIL,
        "type_template": TypeTemplate.SYSTEME,
        "type_notification": TypeNotification.AUDIT_CRITICAL,
        "sujet": "⚠️ Anomalie critique détectée : {{ titre }}",
        "contenu_html": """
            <h1>Anomalie critique détectée</h1>
            <p><strong>{{ titre }}</strong></p>
            <p>{{ description }}</p>
            <p><a href="{{ lien_finding }}">Voir le détail et traiter</a></p>
        """,
    },
]
