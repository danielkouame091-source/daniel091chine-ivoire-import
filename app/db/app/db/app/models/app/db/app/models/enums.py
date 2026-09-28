"""
Enums Python — miroir EXACT des types PostgreSQL créés en migration 0001.
⚠️ Toute modification ici DOIT être répercutée dans une nouvelle migration Alembic.
"""
from __future__ import annotations

from enum import Enum


class UserRole(str, Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN_TENANT = "ADMIN_TENANT"
    COMPTABLE = "COMPTABLE"
    LECTEUR = "LECTEUR"
    AUDITEUR = "AUDITEUR"


class TenantStatut(str, Enum):
    ACTIF = "actif"
    SUSPENDU = "suspendu"
    GELE = "gele"
    ARCHIVE = "archive"


class UserStatut(str, Enum):
    ACTIF = "actif"
    GELE = "gele"
    REVOQUE = "revoque"
    INVITE = "invite"


class SubStatut(str, Enum):
    TRIAL = "trial"
    ACTIF = "actif"
    IMPAYE = "impaye"
    EXPIRE = "expire"
    SUSPENDU = "suspendu"
    RESILIE = "resilie"


class SubPlan(str, Enum):
    STARTER = "starter"
    PRO = "pro"
    BUSINESS = "business"
    ENTERPRISE = "enterprise"


class CompteType(str, Enum):
    ACTIF = "actif"
    PASSIF = "passif"
    CHARGE = "charge"
    PRODUIT = "produit"
    TRESORERIE = "tresorerie"
    ANALYTIQUE = "analytique"
    ENGAGEMENT = "engagement"


class JournalType(str, Enum):
    VENTE = "vente"
    ACHAT = "achat"
    BANQUE = "banque"
    CAISSE = "caisse"
    OD = "od"
    AN = "an"
    MOBILE_MONEY = "mobile_money"
    PAIE = "paie"
    IMPOT = "impot"


class EcritureSource(str, Enum):
    MANUEL = "manuel"
    IMPORT = "import"
    MOBILE_MONEY = "mobile_money"
    IA_NLP = "ia_nlp"
    API = "api"
    SYSTEME = "systeme"


class EcritureStatut(str, Enum):
    BROUILLON = "brouillon"
    VALIDEE = "validee"
    GELEE = "gelee"
    ANNULEE = "annulee"
    EXTOURNEE = "extournee"


class MMProvider(str, Enum):
    WAVE = "wave"
    ORANGE_MONEY = "orange_money"
    MTN_MOMO = "mtn_momo"
    MOOV_MONEY = "moov_money"


class MMSens(str, Enum):
    CREDIT = "credit"
    DEBIT = "debit"


class MMStatut(str, Enum):
    NON_RAPPROCHE = "non_rapproche"
    RAPPROCHE = "rapproche"
    ECART = "ecart"
    GELE = "gele"


class FreezeCible(str, Enum):
    TENANT = "tenant"
    USER = "user"
    COMPTE = "compte"
    JOURNAL = "journal"
    ECRITURE = "ecriture"
    MM_TRANSACTION = "mm_transaction"
    EXERCICE = "exercice"


class FreezeStatut(str, Enum):
    ACTIF = "actif"
    LEVE = "leve"
    PARTIEL = "partiel"
