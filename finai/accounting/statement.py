"""Modèle de données commun : états financiers « par nature » (logique SYSCOHADA).

Toutes les normes (SYSCOHADA, IFRS, US GAAP, CAS chinoises, Ind AS, normes australiennes) sont
ramenées à ce schéma interne unique ; les différences de présentation et de traitement sont
gérées dans `standards.py`. Les montants sont en unités monétaires locales (même unité partout).

Conventions de signe : toutes les charges et tous les produits sont saisis POSITIFS ; les
variations de stocks sont « stock final − stock initial » (positif = stock en hausse).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Optional


@dataclass
class Statement:
    # ── Compte de résultat par nature ──
    ventes_marchandises: float = 0.0
    achats_marchandises: float = 0.0
    var_stock_marchandises: float = 0.0
    production_vendue: float = 0.0          # biens et services produits et vendus
    production_stockee: float = 0.0         # variation des stocks de produits (final - initial)
    production_immobilisee: float = 0.0
    achats_matieres: float = 0.0
    var_stock_matieres: float = 0.0
    autres_achats: float = 0.0
    transports: float = 0.0
    services_exterieurs: float = 0.0
    impots_taxes: float = 0.0
    charges_personnel: float = 0.0
    subventions_exploitation: float = 0.0
    autres_produits: float = 0.0
    autres_charges: float = 0.0
    reprises_transferts: float = 0.0
    dotations_amort_prov: float = 0.0
    produits_financiers: float = 0.0
    charges_financieres: float = 0.0
    produits_hao: float = 0.0               # hors activités ordinaires (SYSCOHADA)
    charges_hao: float = 0.0
    impot_resultat: float = 0.0
    # ── Bilan ──
    immobilisations_nettes: float = 0.0
    stocks: float = 0.0
    creances_clients: float = 0.0
    autres_creances: float = 0.0
    tresorerie_actif: float = 0.0
    capital_social: float = 0.0
    capitaux_propres: float = 0.0
    dettes_financieres_lt: float = 0.0
    dettes_financieres_ct: float = 0.0
    dettes_fournisseurs: float = 0.0
    dettes_fiscales_sociales: float = 0.0
    autres_dettes_ct: float = 0.0
    tresorerie_passif: float = 0.0
    # ── Informations complémentaires (retraitements multi-normes) ──
    loyers_credit_bail: float = 0.0         # charges de location (IFRS 16 / ASC 842)
    frais_dev_actives: float = 0.0          # frais de développement activables (IAS 38)
    reserve_lifo: float = 0.0               # écart LIFO → FIFO (US GAAP)
    nb_employes: int = 0

    # ── agrégats de base ──
    @property
    def chiffre_affaires(self) -> float:
        return self.ventes_marchandises + self.production_vendue

    @property
    def total_actif(self) -> float:
        return (self.immobilisations_nettes + self.stocks + self.creances_clients
                + self.autres_creances + self.tresorerie_actif)

    @property
    def total_passif(self) -> float:
        return (self.capitaux_propres + self.dettes_financieres_lt + self.dettes_financieres_ct
                + self.dettes_fournisseurs + self.dettes_fiscales_sociales + self.autres_dettes_ct
                + self.tresorerie_passif)

    @property
    def dettes_exploitation_ct(self) -> float:
        return self.dettes_fournisseurs + self.dettes_fiscales_sociales + self.autres_dettes_ct

    @property
    def passif_courant(self) -> float:
        return self.dettes_exploitation_ct + self.dettes_financieres_ct + self.tresorerie_passif

    @property
    def actif_courant(self) -> float:
        return self.stocks + self.creances_clients + self.autres_creances + self.tresorerie_actif

    @property
    def dettes_financieres(self) -> float:
        return self.dettes_financieres_lt + self.dettes_financieres_ct + self.tresorerie_passif

    def equilibre(self, tolerance: float = 1.0) -> bool:
        """Le bilan est équilibré (actif = passif) à `tolerance` près."""
        return abs(self.total_actif - self.total_passif) <= tolerance

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Statement":
        noms = {f.name for f in fields(cls)}
        inconnus = set(data) - noms
        if inconnus:
            raise ValueError(f"Champs inconnus : {sorted(inconnus)}")
        valeurs = {}
        for cle, valeur in data.items():
            valeurs[cle] = int(valeur) if cle == "nb_employes" else float(valeur or 0.0)
        return cls(**valeurs)


@dataclass
class Company:
    """Entreprise = identité + zone comptable + exercice courant (+ précédent facultatif)."""
    nom: str
    zone: str                      # clé de `standards.ZONES`
    secteur: str = "Commerce"
    courant: Statement = field(default_factory=Statement)
    precedent: Optional[Statement] = None
