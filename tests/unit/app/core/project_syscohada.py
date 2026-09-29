"""
Référentiel SYSCOHADA révisé — Gestion de projet & Chantiers.

Sources :
- SYSCOHADA révisé (Acte uniforme OHADA, 2017) — comptes 23x et 34x
- Norme IAS 11 / IFRS 15 (méthode à l'avancement) — inspirée pour PME
- Code des marchés publics CI (BTP) — retenue de garantie 5%
- Réglementation fiscale CI sur les retenues de garantie (TVA différée)
"""
from __future__ import annotations

from typing import NamedTuple


# ─────────────────────────────────────────────────────────────────────────────
# Types de projet
# ─────────────────────────────────────────────────────────────────────────────
class TypeProjet:
    CHANTIER_BTP = "chantier_btp"                # Construction, BTP
    PROJET_INVESTISSEMENT = "projet_investissement"  # Immo en cours
    PROJET_INTERNE = "projet_interne"            # Interne (R&D, IT)
    MISSION_SERVICE = "mission_service"          # Prestation de service
    PROJET_PRODUCTION = "projet_production"      # Production à la commande
    MAINTENANCE = "maintenance"                  # Contrats de maintenance
    FORMATION = "formation"                      # Sessions de formation
    AUTRE = "autre"


TYPES_PROJET = {
    TypeProjet.CHANTIER_BTP,
    TypeProjet.PROJET_INVESTISSEMENT,
    TypeProjet.PROJET_INTERNE,
    TypeProjet.MISSION_SERVICE,
    TypeProjet.PROJET_PRODUCTION,
    TypeProjet.MAINTENANCE,
    TypeProjet.FORMATION,
    TypeProjet.AUTRE,
}


# ─────────────────────────────────────────────────────────────────────────────
# Statuts de projet
# ─────────────────────────────────────────────────────────────────────────────
class StatutProjet:
    BROUILLON = "brouillon"
    EN_PREPARATION = "en_preparation"
    EN_COURS = "en_cours"
    EN_PAUSE = "en_pause"
    TERMINE = "termine"
    ANNULE = "annule"
    EN_LITIGE = "en_litige"
    CLOTURE = "cloture"


# ─────────────────────────────────────────────────────────────────────────────
# Méthodes de reconnaissance du revenu
# ─────────────────────────────────────────────────────────────────────────────
class MethodeReconnaissance:
    A_L_AVANCEMENT = "a_l_avancement"            # SYSCOHADA / IFRS 15 (recommandé)
    A_TERMINAISON = "a_terminaison"              # Reconnaissance à la livraison
    A_L_ENCAISSEMENT = "a_l_encaissement"        # Reconnaissance à l'encaissement
    POURCENTAGE_AVANCEMENT = "pourcentage_avancement"  # % d'avancement physique


METHODES_ADMISES = {
    MethodeReconnaissance.A_L_AVANCEMENT,
    MethodeReconnaissance.A_TERMINAISON,
    MethodeReconnaissance.A_L_ENCAISSEMENT,
    MethodeReconnaissance.POURCENTAGE_AVANCEMENT,
}


# ─────────────────────────────────────────────────────────────────────────────
# Types de jalons / étapes
# ─────────────────────────────────────────────────────────────────────────────
class TypePhase:
    ETUDE = "etude"                              # Études préliminaires
    CONCEPTION = "conception"                    # Conception / design
    APPROVISIONNEMENT = "approvisionnement"      # Achats / logistique
    EXECUTION = "execution"                      # Travaux principaux
    CONTROLE = "controle"                        # Contrôle qualité
    RECEPTION = "reception"                      # Réception client
    GARANTIE = "garantie"                        # Période de garantie
    LIVRAISON = "livraison"                      # Livraison finale


# ─────────────────────────────────────────────────────────────────────────────
# Comptes SYSCOHADA — Projets & Chantiers
# ─────────────────────────────────────────────────────────────────────────────
class CompteProjet(NamedTuple):
    compte: str
    libelle: str
    categorie: str


COMPTES_PROJET: dict[str, CompteProjet] = {
    # ─── Immobilisations en cours (investissement) ─────────────────
    "immo_en_cours_incorporelles": CompteProjet("211000", "Immobilisations en cours — incorporelles", "actif_immo"),
    "immo_en_cours_corporelles":   CompteProjet("231000", "Immobilisations en cours — corporelles",   "actif_immo"),
    "immo_en_cours_terrains":      CompteProjet("232000", "Terrains en cours d'aménagement",          "actif_immo"),
    "immo_en_cours_constructions": CompteProjet("233000", "Constructions en cours",                   "actif_immo"),
    # ─── Stocks de production (projets de fabrication) ────────────
    "produits_en_cours":           CompteProjet("341000", "Produits en cours",                        "actif_stock"),
    "services_en_cours":           CompteProjet("342000", "Services en cours",                        "actif_stock"),
    "travaux_en_cours":            CompteProjet("345000", "Travaux en cours",                         "actif_stock"),
    # ─── Clients — retenue de garantie ────────────────────────────
    "clients_retenue_garantie":    CompteProjet("419400", "Clients — retenues de garantie",          "actif_tiers"),
    "clients_factures_a_etablir":  CompteProjet("418100", "Clients — factures à établir",            "actif_tiers"),
    "clients_produits_a_recevoir": CompteProjet("418100", "Clients — produits à recevoir",           "actif_tiers"),
    # ─── Fournisseurs — retenue de garantie ───────────────────────
    "fournisseurs_retenue":        CompteProjet("401800", "Fournisseurs — retenues de garantie",     "passif_tiers"),
    # ─── Produits ──────────────────────────────────────────────────
    "travaux_factures":            CompteProjet("705000", "Travaux facturés",                         "produit"),
    "services_factures":           CompteProjet("706000", "Services vendus",                          "produit"),
    "production_stockee":          CompteProjet("736000", "Production stockée",                       "produit"),
    "production_immobilisee":      CompteProjet("722000", "Production immobilisée",                   "produit"),
    # ─── Charges spécifiques aux projets ──────────────────────────
    "achats_projet":               CompteProjet("604000", "Achats de matières pour projets",         "charge"),
    "sous_traitance":              CompteProjet("604500", "Sous-traitance de chantier",               "charge"),
    "locations_chantier":          CompteProjet("613000", "Locations de matériel de chantier",       "charge"),
    "personnel_chantier":          CompteProjet("661000", "Personnel affecté aux chantiers",         "charge"),
}


# ─────────────────────────────────────────────────────────────────────────────
# Retenue de garantie (normes BTP Côte d'Ivoire)
# ─────────────────────────────────────────────────────────────────────────────
RETENUE_GARANTIE_TAUX_DEFAUT = 0.05              # 5% par défaut
RETENUE_GARANTIE_TAUX_MAX = 0.10                 # 10% maximum légal
RETENUE_GARANTIE_DUREE_MOIS = 12                 # 12 mois de garantie standard


# ─────────────────────────────────────────────────────────────────────────────
# Méthodes d'avancement
# ─────────────────────────────────────────────────────────────────────────────
class MethodeAvancement:
    PHYSIQUE = "physique"                        # % physique mesuré
    COUTS_ENGA_GES = "couts_engages"             # Coûts engagés / coût total estimé
    HEURES_TRAVAILLEES = "heures_travaillees"    # Heures / heures totales
    UNITES_PRODUITES = "unites_produites"        # Unités / unités totales
    JALONS_ATTEINTS = "jalons_atteints"          # Jalons / jalons totaux


# ─────────────────────────────────────────────────────────────────────────────
# États de situation de travaux
# ─────────────────────────────────────────────────────────────────────────────
class StatutSituation:
    BROUILLON = "brouillon"
    SOUMISE = "soumise"                          # Soumise au client
    VALIDEE = "validee"                          # Validée par le client
    FACTUREE = "facturee"                        # Facturée
    PAYEE = "payee"
    CONTESTEE = "contestee"
    ANNULEE = "annulee"


# ─────────────────────────────────────────────────────────────────────────────
# Journaux SYSCOHADA
# ─────────────────────────────────────────────────────────────────────────────
JOURNAL_VENTE = "VE"
JOURNAL_PROJET = "PR"                            # Journal des projets (à créer)
JOURNAL_OD = "OD"


# ─────────────────────────────────────────────────────────────────────────────
# Alertes de gestion
# ─────────────────────────────────────────────────────────────────────────────
class NiveauAlerteProjet:
    OK = "ok"                                    # < 80% budget consommé
    VIGILANCE = "vigilance"                      # 80-95% budget
    ALERTE = "alerte"                            # 95-100% budget
    CRITIQUE = "critique"                        # > 100% budget (dépassement)
    RETARD_PLANNING = "retard_planning"          # Retard > 15 jours
    MARGE_NEGATIVE = "marge_negative"            # Marge < 0%


SEUILS_ALERTE_PROJET = {
    "vigilance": 0.80,
    "alerte": 0.95,
    "critique": 1.00,
}
