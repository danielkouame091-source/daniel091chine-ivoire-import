"""
Référentiel Portail Client / Fournisseur.

Contexte :
- Le portail est un espace d'accès EXTERNE (hors tenant)
- Les utilisateurs portail ne sont PAS des users internes
- Ils accèdent uniquement aux données qui les concernent
- Isolation stricte : un client ne voit QUE ses factures, un fournisseur QUE ses commandes
"""
from __future__ import annotations

from typing import NamedTuple


# ─────────────────────────────────────────────────────────────────────────────
# Types d'utilisateur portail
# ─────────────────────────────────────────────────────────────────────────────
class TypeUtilisateurPortail:
    CLIENT = "client"
    FOURNISSEUR = "fournisseur"
    PARTENAIRE = "partenaire"           # Banque, expert-comptable externe
    AUDITEUR_EXTERNE = "auditeur_externe"


TYPES_UTILISATEUR_PORTAIL = {
    TypeUtilisateurPortail.CLIENT,
    TypeUtilisateurPortail.FOURNISSEUR,
    TypeUtilisateurPortail.PARTENAIRE,
    TypeUtilisateurPortail.AUDITEUR_EXTERNE,
}


# ─────────────────────────────────────────────────────────────────────────────
# Statuts de compte portail
# ─────────────────────────────────────────────────────────────────────────────
class StatutComptePortail:
    INVITE = "invite"                   # Invitation envoyée, pas encore activé
    ACTIF = "actif"
    SUSPENDU = "suspendu"
    REVOQUE = "revoque"
    EXPIRE = "expire"                   # Accès temporaire expiré


# ─────────────────────────────────────────────────────────────────────────────
# Permissions granulaires (par portail)
# ─────────────────────────────────────────────────────────────────────────────
class PermissionPortail:
    # Client
    VOIR_SES_FACTURES = "voir_ses_factures"
    VOIR_SES_RELEVES = "voir_ses_releves"
    TELECHARGER_FACTURES = "telecharger_factures"
    PAYER_EN_LIGNE = "payer_en_ligne"
    CONTESTER_FACTURE = "contester_facture"
    VOIR_SES_PAIEMENTS = "voir_ses_paiements"
    MESSAGERIE = "messagerie"

    # Fournisseur
    VOIR_SES_COMMANDES = "voir_ses_commandes"
    ACCUSER_RECEPTION_PO = "accuser_reception_po"
    SOUMETTRE_FACTURE = "soumettre_facture"
    VOIR_SES_PAIEMENTS_FOURNISSEUR = "voir_ses_paiements_fournisseur"
    SUIVRE_SES_LIVRAISONS = "suivre_ses_livraisons"

    # Partenaire
    VOIR_RAPPORTS_AGREGES = "voir_rapports_agreges"
    EXPORTER_DONNEES = "exporter_donnees"

    # Auditeur externe
    LIRE_ECRITURES = "lire_ecritures"
    LIRE_ETATS_FINANCIERS = "lire_etats_financiers"
    VERIFIER_PISTE_AUDIT = "verifier_piste_audit"


PERMISSIONS_CLIENT_DEFAUT = {
    PermissionPortail.VOIR_SES_FACTURES,
    PermissionPortail.VOIR_SES_RELEVES,
    PermissionPortail.TELECHARGER_FACTURES,
    PermissionPortail.VOIR_SES_PAIEMENTS,
    PermissionPortail.MESSAGERIE,
}

PERMISSIONS_FOURNISSEUR_DEFAUT = {
    PermissionPortail.VOIR_SES_COMMANDES,
    PermissionPortail.ACCUSER_RECEPTION_PO,
    PermissionPortail.SOUMETTRE_FACTURE,
    PermissionPortail.VOIR_SES_PAIEMENTS_FOURNISSEUR,
    PermissionPortail.MESSAGERIE,
}


# ─────────────────────────────────────────────────────────────────────────────
# Types de documents partagés
# ─────────────────────────────────────────────────────────────────────────────
class TypeDocumentPartage:
    FACTURE = "facture"
    RELEVE = "releve"
    AVOIR = "avoir"
    BON_COMMANDE = "bon_commande"
    BON_LIVRAISON = "bon_livraison"
    SITUATION_TRAVAUX = "situation_travaux"
    CONTRAT = "contrat"
    ATTESTATION = "attestation"
    RIB = "rib"
    AUTRE = "autre"


# ─────────────────────────────────────────────────────────────────────────────
# Statuts de paiement en ligne
# ─────────────────────────────────────────────────────────────────────────────
class StatutPaiementPortail:
    INITIE = "initie"
    EN_COURS = "en_cours"
    CONFIRME = "confirme"
    ECHOUE = "echoue"
    ANNULE = "annule"
    REMBOURSE = "rembourse"


# ─────────────────────────────────────────────────────────────────────────────
# Moyens de paiement en ligne
# ─────────────────────────────────────────────────────────────────────────────
class MoyenPaiementPortail:
    MOBILE_MONEY = "mobile_money"
    CARTE_BANCAIRE = "carte_bancaire"
    VIREMENT = "virement"
    CHEQUE = "cheque"


# ─────────────────────────────────────────────────────────────────────────────
# Statuts de soumission de facture fournisseur
# ─────────────────────────────────────────────────────────────────────────────
class StatutSoumissionFacture:
    BROUILLON = "brouillon"
    SOUMISE = "soumise"
    EN_REVISION = "en_revision"
    ACCEPTEE = "acceptee"
    REJETEE = "rejetee"
    VALIDEE_FOURNISSEUR = "validee_fournisseur"   # Devenue facture officielle
    ANNULEE = "annulee"


# ─────────────────────────────────────────────────────────────────────────────
# Types d'événements de notification
# ─────────────────────────────────────────────────────────────────────────────
class EventNotificationPortail:
    INVITATION = "invitation"
    NOUVELLE_FACTURE = "nouvelle_facture"
    NOUVEAU_RELEVE = "nouveau_releve"
    NOUVELLE_COMMANDE = "nouvelle_commande"
    RELANCE_PAIEMENT = "relance_paiement"
    PAIEMENT_RECU = "paiement_recu"
    FACTURE_CONTESTEE = "facture_contestee"
    FACTURE_SOUMISE = "facture_soumise"
    MESSAGE_RECU = "message_recu"
    DOCUMENT_PARTAGE = "document_partage"


# ─────────────────────────────────────────────────────────────────────────────
# Configuration de sécurité
# ─────────────────────────────────────────────────────────────────────────────
class SecuritePortail:
    TOKEN_INVITATION_TTL_H = 72          # 3 jours
    TOKEN_MAGIC_LINK_TTL_MIN = 15        # 15 minutes
    TOKEN_RESET_PASSWORD_TTL_H = 2
    SESSION_TTL_H = 8                    # Session courte (portail externe)
    MAX_TENTATIVES_CONNEXION = 5
    VERROUILLAGE_MINUTES = 30
    MFA_OBLIGATOIRE = False              # Optionnel sur le portail (recommandé)


# ─────────────────────────────────────────────────────────────────────────────
# Templates de messages
# ─────────────────────────────────────────────────────────────────────────────
MESSAGE_ACCUEIL_CLIENT = """
Bonjour {prenom},

Bienvenue sur votre espace client MTech. Vous pouvez :
- Consulter vos factures en cours
- Régler vos factures en ligne (Wave, Orange Money, CB)
- Télécharger vos relevés mensuels
- Échanger avec votre fournisseur

Cordialement,
L'équipe {tenant_nom}
"""

MESSAGE_ACCUEIL_FOURNISSEUR = """
Bonjour {prenom},

Bienvenue sur votre espace fournisseur MTech. Vous pouvez :
- Consulter les commandes en cours
- Soumettre vos factures en ligne
- Suivre l'état de vos paiements
- Télécharger vos bons de commande

Cordialement,
L'équipe {tenant_nom}
"""


# ─────────────────────────────────────────────────────────────────────────────
# Règles métier
# ─────────────────────────────────────────────────────────────────────────────
SEUIL_MONTANT_PAIEMENT_EN_LIGNE = 100_000          # Minimum 100k FCFA pour paiement en ligne
FRAIS_PAIEMENT_MOBILE_MONEY_PCT = 0.015            # 1.5% frais MM
FRAIS_PAIEMENT_CARTE_PCT = 0.025                   # 2.5% frais CB
DUREE_VALIDITE_LIEN_PAIEMENT_H = 24                # 24h pour payer
