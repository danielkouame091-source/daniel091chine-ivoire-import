"""
Référentiel Business Intelligence & Reporting.

Ce module fournit un moteur de dashboards configurables permettant aux DAF,
dirigeants et experts-comptables de construire leurs propres tableaux de bord
sans écrire de SQL.

Sources de données disponibles :
- Tables pré-agrégées (pour la performance)
- Écritures comptables (brique 2)
- Tiers clients/fournisseurs (briques 17, 18)
- Trésorerie (brique 19)
- Projets (brique 24)
- RH (brique 27)
"""
from __future__ import annotations

from typing import NamedTuple


# ─────────────────────────────────────────────────────────────────────────────
# Types de widgets
# ─────────────────────────────────────────────────────────────────────────────
class TypeWidget:
    KPI_CARD = "kpi_card"                    # Carte KPI simple
    LINE_CHART = "line_chart"                # Courbe (séries temporelles)
    BAR_CHART = "bar_chart"                  # Barres (comparaisons)
    PIE_CHART = "pie_chart"                  # Camembert (répartition)
    DONUT_CHART = "donut_chart"              # Anneau
    AREA_CHART = "area_chart"                # Aire empilée
    TABLE = "table"                          # Tableau de données
    HEATMAP = "heatmap"                      # Carte de chaleur
    GAUGE = "gauge"                          # Jauge de progression
    FUNNEL = "funnel"                        # Entonnoir
    SCATTER = "scatter"                      # Nuage de points
    TREEMAP = "treemap"                      # Treemap hiérarchique
    WATERFALL = "waterfall"                  # Cascade (analyse d'écarts)
    SPARKLINE = "sparkline"                  # Micro-courbe
    CALENDAR_HEATMAP = "calendar_heatmap"    # Heatmap calendaire


TYPES_WIDGETS = {
    TypeWidget.KPI_CARD, TypeWidget.LINE_CHART, TypeWidget.BAR_CHART,
    TypeWidget.PIE_CHART, TypeWidget.DONUT_CHART, TypeWidget.AREA_CHART,
    TypeWidget.TABLE, TypeWidget.HEATMAP, TypeWidget.GAUGE, TypeWidget.FUNNEL,
    TypeWidget.SCATTER, TypeWidget.TREEMAP, TypeWidget.WATERFALL,
    TypeWidget.SPARKLINE, TypeWidget.CALENDAR_HEATMAP,
}


# ─────────────────────────────────────────────────────────────────────────────
# Sources de données
# ─────────────────────────────────────────────────────────────────────────────
class SourceDonnees:
    ECRITURES = "ecritures"
    BALANCE = "balance"
    GRAND_LIVRE = "grand_livre"
    COMPTE_RESULTAT = "compte_resultat"
    BILAN = "bilan"
    CLIENTS = "clients"
    FOURNISSEURS = "fournisseurs"
    FACTURES_CLIENTS = "factures_clients"
    FACTURES_FOURNISSEURS = "factures_fournisseurs"
    TRESORERIE = "tresorerie"
    RAPPROCHEMENT = "rapprochement"
    STOCKS = "stocks"
    IMMOBILISATIONS = "immobilisations"
    PROJETS = "projets"
    SITUATIONS_TRAVAUX = "situations_travaux"
    PAIE = "paie"
    EMPLOYES = "employes"
    CONGES = "conges"
    BUDGETS = "budgets"
    ANALYTIQUE = "analytique"
    FNE = "fne"
    AUDIT = "audit"
    ABONNEMENTS = "abonnements"


# ─────────────────────────────────────────────────────────────────────────────
# Périodes prédéfinies
# ─────────────────────────────────────────────────────────────────────────────
class PeriodePredefinie:
    AUJOURD_HUI = "today"
    HIER = "yesterday"
    CETTE_SEMAINE = "this_week"
    SEMAINE_DERNIERE = "last_week"
    CE_MOIS = "this_month"
    MOIS_DERNIER = "last_month"
    CE_TRIMESTRE = "this_quarter"
    TRIMESTRE_DERNIER = "last_quarter"
    CETTE_ANNEE = "this_year"
    ANNEE_DERNIERE = "last_year"
    EXERCICE_COURANT = "current_fiscal_year"
    EXERCICE_PRECEDENT = "previous_fiscal_year"
    DOUZE_DERNIERS_MOIS = "last_12_months"
    PERSONNALISE = "custom"


# ─────────────────────────────────────────────────────────────────────────────
# Agrégations
# ─────────────────────────────────────────────────────────────────────────────
class Agregation:
    SUM = "sum"
    COUNT = "count"
    AVG = "avg"
    MIN = "min"
    MAX = "max"
    DISTINCT_COUNT = "distinct_count"
    MEDIAN = "median"
    STDDEV = "stddev"


# ─────────────────────────────────────────────────────────────────────────────
# Formats d'affichage
# ─────────────────────────────────────────────────────────────────────────────
class FormatAffichage:
    NOMBRE = "number"                # 1 234 567
    MONTANT = "montant"              # 1 234 567 FCFA
    MONTANT_COMPACT = "montant_compact"  # 1,23 M FCFA
    POURCENTAGE = "pourcentage"      # 12,5%
    DATE = "date"
    DUREE = "duree"
    BOOLEAN = "boolean"


# ─────────────────────────────────────────────────────────────────────────────
# Opérateurs de comparaison
# ─────────────────────────────────────────────────────────────────────────────
class Operateur:
    EQ = "eq"
    NEQ = "neq"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    NOT_IN = "not_in"
    BETWEEN = "between"
    LIKE = "like"
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"


# ─────────────────────────────────────────────────────────────────────────────
# KPIs prédéfinis (formules standard)
# ─────────────────────────────────────────────────────────────────────────────
class KPIStandard(NamedTuple):
    code: str
    libelle: str
    description: str
    source: str
    formule: str
    format_affichage: str
    unite: str | None


KPIS_STANDARD: list[KPIStandard] = [
    # ─── Comptabilité ───────────────────────────────────────────────
    KPIStandard("CA_MENSUEL", "Chiffre d'affaires mensuel", "Total des ventes (compte 70x) sur le mois", "balance", "SUM(70*)", "montant_compact", "FCFA"),
    KPIStandard("CA_YTD", "CA cumulé annuel", "CA depuis le 1er janvier", "balance", "SUM(70*) WHERE date>=YEAR_START", "montant_compact", "FCFA"),
    KPIStandard("MARGE_BRUTE", "Marge brute", "CA - achats consommés", "compte_resultat", "CA - ACHATS", "montant", "FCFA"),
    KPIStandard("TAUX_MARGE", "Taux de marge", "(Marge / CA) × 100", "compte_resultat", "(MARGE/CA)*100", "pourcentage", "%"),
    KPIStandard("EBE", "Excédent brut d'exploitation", "SIG intermédiaire", "compte_resultat", "VA - CHARGES_PERSONNEL - IMPOTS", "montant", "FCFA"),
    KPIStandard("RESULTAT_NET", "Résultat net", "Résultat de l'exercice", "compte_resultat", "RESULTAT_NET", "montant", "FCFA"),
    KPIStandard("TRESORERIE", "Trésorerie disponible", "Solde des comptes 5x", "tresorerie", "SUM(5*)", "montant", "FCFA"),
    KPIStandard("BFR", "Besoin en fonds de roulement", "Stocks + Créances - Dettes", "balance", "STOCKS + CREANCES - DETTES", "montant", "FCFA"),

    # ─── Ventes / Clients ───────────────────────────────────────────
    KPIStandard("NB_FACTURES_MOIS", "Factures émises ce mois", "Nombre de factures clients validées", "factures_clients", "COUNT WHERE month=current", "nombre", None),
    KPIStandard("CA_TOP_CLIENT", "CA top client", "Meilleur client du mois", "factures_clients", "SUM BY CLIENT ORDER DESC LIMIT 1", "montant", "FCFA"),
    KPIStandard("DSO", "DSO (Days Sales Outstanding)", "Délai moyen d'encaissement", "factures_clients", "AVG(date_paiement - date_facture)", "duree", "jours"),
    KPIStandard("CREANCES_TOTAL", "Créances clients totales", "Encours clients", "factures_clients", "SUM(solde_du)", "montant", "FCFA"),
    KPIStandard("FACTURES_RETARD", "Factures en retard", "Nombre de factures échues impayées", "factures_clients", "COUNT WHERE due_date < today AND solde_du > 0", "nombre", None),
    KPIStandard("TICKET_MOYEN", "Ticket moyen", "CA / nombre de factures", "factures_clients", "AVG(total_ttc)", "montant", "FCFA"),

    # ─── Achats / Fournisseurs ─────────────────────────────────────
    KPIStandard("ACHATS_MOIS", "Achats du mois", "Total factures fournisseurs", "factures_fournisseurs", "SUM WHERE month=current", "montant", "FCFA"),
    KPIStandard("DPO", "DPO (Days Payable Outstanding)", "Délai moyen de paiement fournisseurs", "factures_fournisseurs", "AVG(date_paiement - date_facture)", "duree", "jours"),
    KPIStandard("DETTES_TOTAL", "Dettes fournisseurs", "Encours fournisseurs", "factures_fournisseurs", "SUM(solde_du)", "montant", "FCFA"),
    KPIStandard("TOP_FOURNISSEUR", "Top fournisseur", "Fournisseur le plus facturé", "factures_fournisseurs", "SUM BY SUPPLIER ORDER DESC LIMIT 1", "montant", "FCFA"),

    # ─── Trésorerie ─────────────────────────────────────────────────
    KPIStandard("SOLDE_BANQUE", "Solde bancaire consolidé", "Somme des comptes banques", "tresorerie", "SUM WHERE type='banque'", "montant", "FCFA"),
    KPIStandard("SOLDE_MM", "Solde Mobile Money", "Somme des comptes MM", "tresorerie", "SUM WHERE type='mobile_money'", "montant", "FCFA"),
    KPIStandard("ENCAISSEMENTS_MOIS", "Encaissements du mois", "Total encaissé", "tresorerie", "SUM(customer_payments WHERE month=current)", "montant", "FCFA"),
    KPIStandard("DECAISSEMENTS_MOIS", "Décaissements du mois", "Total payé", "tresorerie", "SUM(supplier_payments WHERE month=current)", "montant", "FCFA"),
    KPIStandard("RUNWAY", "Runway", "Trésorerie / burn mensuel", "tresorerie", "TRESORERIE / BURN_MENSUEL", "duree", "mois"),

    # ─── Stocks ─────────────────────────────────────────────────────
    KPIStandard("VALEUR_STOCK", "Valeur du stock", "Valeur totale CUMP", "stocks", "SUM(valeur_stock)", "montant", "FCFA"),
    KPIStandard("NB_ARTICLES_STOCK", "Nombre d'articles", "Articles actifs", "stocks", "COUNT", "nombre", None),
    KPIStandard("ARTICLES_ALERTE", "Articles en alerte", "Sous le seuil", "stocks", "COUNT WHERE quantite < seuil", "nombre", None),
    KPIStandard("ROTATION_STOCK", "Rotation du stock", "CA / stock moyen", "stocks", "CA / STOCK_MOYEN", "nombre", "x/an"),

    # ─── Immobilisations ────────────────────────────────────────────
    KPIStandard("VALEUR_IMMO_BRUTE", "Immobilisations brutes", "Valeur d'origine", "immobilisations", "SUM(valeur_origine)", "montant", "FCFA"),
    KPIStandard("VNC_TOTALE", "VNC totale", "Valeur nette comptable", "immobilisations", "SUM(vnc)", "montant", "FCFA"),
    KPIStandard("DOTATIONS_ANNEE", "Dotations de l'année", "Amortissements de l'exercice", "immobilisations", "SUM WHERE exercice=current", "montant", "FCFA"),

    # ─── Projets ────────────────────────────────────────────────────
    KPIStandard("NB_PROJETS_ACTIFS", "Projets actifs", "Projets en cours", "projets", "COUNT WHERE statut='en_cours'", "nombre", None),
    KPIStandard("MARGE_PROJETS", "Marge projets", "Marge moyenne des projets", "projets", "AVG((CA - COUTS)/CA)*100", "pourcentage", "%"),
    KPIStandard("PROJETS_RETARD", "Projets en retard", "Échéance dépassée", "projets", "COUNT WHERE fin_prevue < today", "nombre", None),

    # ─── RH ─────────────────────────────────────────────────────────
    KPIStandard("EFFECTIF_ACTIF", "Effectif actif", "Employés en poste", "employes", "COUNT WHERE actif=true", "nombre", None),
    KPIStandard("MASSE_SALARIALE", "Masse salariale mensuelle", "Total salaires bruts", "paie", "SUM(salaire_brut) WHERE month=current", "montant", "FCFA"),
    KPIStandard("TURNOVER_12M", "Turnover 12 mois", "Taux de rotation", "employes", "DEPARTS/EFECTIF_MOYEN*100", "pourcentage", "%"),

    # ─── FNE / Fiscal ──────────────────────────────────────────────
    KPIStandard("FACTURES_FNE_MOIS", "Factures certifiées FNE", "Total FNE du mois", "fne", "COUNT WHERE statut='certifiee'", "nombre", None),
    KPIStandard("STICKERS_RESTANTS", "Stickers restants", "Solde de stickers FNE", "fne", "balance_total", "nombre", None),
    KPIStandard("TVA_DUE", "TVA à payer", "TVA collectée - déductible", "balance", "TVA_COLLECTEE - TVA_DEDUCTIBLE", "montant", "FCFA"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Templates de dashboards prédéfinis
# ─────────────────────────────────────────────────────────────────────────────
DASHBOARDS_SEED: list[dict] = [
    {
        "code": "DIRIGEANT",
        "nom": "Tableau de bord Dirigeant",
        "description": "Vue synthétique pour le dirigeant",
        "categorie": "direction",
        "ordre": 1,
        "widgets": [
            {"type": "kpi_card", "titre": "CA du mois", "kpi_code": "CA_MENSUEL", "position": {"x": 0, "y": 0, "w": 3, "h": 2}},
            {"type": "kpi_card", "titre": "Résultat net", "kpi_code": "RESULTAT_NET", "position": {"x": 3, "y": 0, "w": 3, "h": 2}},
            {"type": "kpi_card", "titre": "Trésorerie", "kpi_code": "TRESORERIE", "position": {"x": 6, "y": 0, "w": 3, "h": 2}},
            {"type": "kpi_card", "titre": "Créances", "kpi_code": "CREANCES_TOTAL", "position": {"x": 9, "y": 0, "w": 3, "h": 2}},
            {"type": "line_chart", "titre": "Évolution CA 12 mois", "kpi_code": "CA_MENSUEL", "position": {"x": 0, "y": 2, "w": 8, "h": 6}},
            {"type": "pie_chart", "titre": "Répartition CA par client", "kpi_code": "CA_TOP_CLIENT", "position": {"x": 8, "y": 2, "w": 4, "h": 6}},
            {"type": "table", "titre": "Top 10 clients", "kpi_code": None, "position": {"x": 0, "y": 8, "w": 6, "h": 6}},
            {"type": "table", "titre": "Factures en retard", "kpi_code": "FACTURES_RETARD", "position": {"x": 6, "y": 8, "w": 6, "h": 6}},
        ],
    },
    {
        "code": "DAF",
        "nom": "Tableau de bord DAF",
        "description": "Vue financière détaillée",
        "categorie": "finance",
        "ordre": 2,
        "widgets": [
            {"type": "kpi_card", "titre": "CA YTD", "kpi_code": "CA_YTD", "position": {"x": 0, "y": 0, "w": 3, "h": 2}},
            {"type": "kpi_card", "titre": "Marge brute", "kpi_code": "MARGE_BRUTE", "position": {"x": 3, "y": 0, "w": 3, "h": 2}},
            {"type": "kpi_card", "titre": "EBE", "kpi_code": "EBE", "position": {"x": 6, "y": 0, "w": 3, "h": 2}},
            {"type": "kpi_card", "titre": "BFR", "kpi_code": "BFR", "position": {"x": 9, "y": 0, "w": 3, "h": 2}},
            {"type": "kpi_card", "titre": "DSO", "kpi_code": "DSO", "position": {"x": 0, "y": 2, "w": 3, "h": 2}},
            {"type": "kpi_card", "titre": "DPO", "kpi_code": "DPO", "position": {"x": 3, "y": 2, "w": 3, "h": 2}},
            {"type": "kpi_card", "titre": "Runway", "kpi_code": "RUNWAY", "position": {"x": 6, "y": 2, "w": 3, "h": 2}},
            {"type": "kpi_card", "titre": "TVA due", "kpi_code": "TVA_DUE", "position": {"x": 9, "y": 2, "w": 3, "h": 2}},
            {"type": "line_chart", "titre": "Évolution trésorerie", "kpi_code": "TRESORERIE", "position": {"x": 0, "y": 4, "w": 12, "h": 5}},
            {"type": "waterfall", "titre": "Cascade du résultat", "kpi_code": None, "position": {"x": 0, "y": 9, "w": 6, "h": 5}},
            {"type": "bar_chart", "titre": "Top 10 fournisseurs", "kpi_code": "TOP_FOURNISSEUR", "position": {"x": 6, "y": 9, "w": 6, "h": 5}},
        ],
    },
    {
        "code": "COMMERCIAL",
        "nom": "Tableau de bord Commercial",
        "description": "Suivi de l'activité commerciale",
        "categorie": "ventes",
        "ordre": 3,
        "widgets": [
            {"type": "kpi_card", "titre": "Factures du mois", "kpi_code": "NB_FACTURES_MOIS", "position": {"x": 0, "y": 0, "w": 3, "h": 2}},
            {"type": "kpi_card", "titre": "Ticket moyen", "kpi_code": "TICKET_MOYEN", "position": {"x": 3, "y": 0, "w": 3, "h": 2}},
            {"type": "kpi_card", "titre": "Factures retard", "kpi_code": "FACTURES_RETARD", "position": {"x": 6, "y": 0, "w": 3, "h": 2}},
            {"type": "kpi_card", "titre": "Top client", "kpi_code": "CA_TOP_CLIENT", "position": {"x": 9, "y": 0, "w": 3, "h": 2}},
            {"type": "bar_chart", "titre": "CA par mois", "kpi_code": "CA_MENSUEL", "position": {"x": 0, "y": 2, "w": 12, "h": 6}},
            {"type": "table", "titre": "Top 20 clients", "kpi_code": None, "position": {"x": 0, "y": 8, "w": 12, "h": 6}},
        ],
    },
    {
        "code": "TRESORERIE",
        "nom": "Tableau de bord Trésorerie",
        "description": "Suivi de la trésorerie et du cash-flow",
        "categorie": "finance",
        "ordre": 4,
        "widgets": [
            {"type": "kpi_card", "titre": "Solde banque", "kpi_code": "SOLDE_BANQUE", "position": {"x": 0, "y": 0, "w": 3, "h": 2}},
            {"type": "kpi_card", "titre": "Solde Mobile Money", "kpi_code": "SOLDE_MM", "position": {"x": 3, "y": 0, "w": 3, "h": 2}},
            {"type": "kpi_card", "titre": "Encaissements", "kpi_code": "ENCAISSEMENTS_MOIS", "position": {"x": 6, "y": 0, "w": 3, "h": 2}},
            {"type": "kpi_card", "titre": "Décaissements", "kpi_code": "DECAISSEMENTS_MOIS", "position": {"x": 9, "y": 0, "w": 3, "h": 2}},
            {"type": "area_chart", "titre": "Évolution trésorerie 90 jours", "kpi_code": "TRESORERIE", "position": {"x": 0, "y": 2, "w": 12, "h": 6}},
            {"type": "line_chart", "titre": "Encaissements vs Décaissements", "kpi_code": None, "position": {"x": 0, "y": 8, "w": 12, "h": 6}},
        ],
    },
    {
        "code": "AUDIT",
        "nom": "Tableau de bord Audit & Conformité",
        "description": "Contrôle interne et conformité",
        "categorie": "audit",
        "ordre": 5,
        "widgets": [
            {"type": "gauge", "titre": "Score de conformité", "kpi_code": None, "position": {"x": 0, "y": 0, "w": 4, "h": 4}},
            {"type": "kpi_card", "titre": "Findings critiques", "kpi_code": None, "position": {"x": 4, "y": 0, "w": 4, "h": 2}},
            {"type": "kpi_card", "titre": "Findings hauts", "kpi_code": None, "position": {"x": 8, "y": 0, "w": 4, "h": 2}},
            {"type": "kpi_card", "titre": "Factures certifiées FNE", "kpi_code": "FACTURES_FNE_MOIS", "position": {"x": 4, "y": 2, "w": 4, "h": 2}},
            {"type": "kpi_card", "titre": "Stickers restants", "kpi_code": "STICKERS_RESTANTS", "position": {"x": 8, "y": 2, "w": 4, "h": 2}},
            {"type": "bar_chart", "titre": "Anomalies par type", "kpi_code": None, "position": {"x": 0, "y": 4, "w": 12, "h": 5}},
        ],
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Palette de couleurs par défaut
# ─────────────────────────────────────────────────────────────────────────────
PALETTE_DEFAUT = [
    "#3B82F6",  # Bleu
    "#10B981",  # Vert
    "#F59E0B",  # Ambre
    "#EF4444",  # Rouge
    "#8B5CF6",  # Violet
    "#EC4899",  # Rose
    "#14B8A6",  # Teal
    "#F97316",  # Orange
    "#6366F1",  # Indigo
    "#84CC16",  # Lime
]


# ─────────────────────────────────────────────────────────────────────────────
# Limites et quotas
# ─────────────────────────────────────────────────────────────────────────────
class LimitesBI:
    MAX_DASHBOARDS_PAR_TENANT = 50
    MAX_WIDGETS_PAR_DASHBOARD = 30
    MAX_LIGNES_TABLEAU = 1000
    MAX_POINTS_SERIE_TEMPORELLE = 365
    CACHE_DUREE_MIN = 5          # Cache KPI : 5 minutes
    TIMEOUT_REQUETE_S = 30       # Timeout d'une requête BI
    MAX_EXPORT_LIGNES = 100_000
