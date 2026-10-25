"""Soldes Intermédiaires de Gestion (SIG) — cascade du SYSCOHADA révisé.

Cascade (logique « par nature ») :
  Marge commerciale      = ventes de marchandises − achats de marchandises ± variation de stock
  Production exercice    = production vendue ± stockée + immobilisée
  Consommations tiers    = achats matières ± var. stock + autres achats + transports + services ext.
  Valeur ajoutée (VA)    = Marge commerciale + Production − Consommations de tiers
  EBE                    = VA + subventions d'exploitation − impôts et taxes − charges de personnel
  Résultat d'exploitation= EBE + reprises/transferts + autres produits − autres charges − dotations
  Résultat financier     = produits financiers − charges financières
  RAO                    = Résultat d'exploitation + Résultat financier
  Résultat HAO           = produits HAO − charges HAO
  Résultat net           = RAO + Résultat HAO − impôt sur le résultat
  CAFG (approx.)         = Résultat net + dotations − reprises   (sans retraiter les cessions)
"""
from __future__ import annotations

from .statement import Statement


def calculer_sig(s: Statement) -> dict[str, float]:
    marge_commerciale = s.ventes_marchandises - s.achats_marchandises + s.var_stock_marchandises
    production = s.production_vendue + s.production_stockee + s.production_immobilisee
    consommations = (s.achats_matieres - s.var_stock_matieres + s.autres_achats + s.transports
                     + s.services_exterieurs)
    # NB : une hausse de stock de matières réduit la consommation : consommation = achats − Δstock.
    valeur_ajoutee = marge_commerciale + production - consommations
    ebe = valeur_ajoutee + s.subventions_exploitation - s.impots_taxes - s.charges_personnel
    resultat_exploitation = (ebe + s.reprises_transferts + s.autres_produits - s.autres_charges
                             - s.dotations_amort_prov)
    resultat_financier = s.produits_financiers - s.charges_financieres
    rao = resultat_exploitation + resultat_financier
    resultat_hao = s.produits_hao - s.charges_hao
    resultat_net = rao + resultat_hao - s.impot_resultat
    cafg = resultat_net + s.dotations_amort_prov - s.reprises_transferts
    return {
        "chiffre_affaires": s.chiffre_affaires,
        "marge_commerciale": marge_commerciale,
        "production_exercice": production,
        "consommations_tiers": consommations,
        "valeur_ajoutee": valeur_ajoutee,
        "excedent_brut_exploitation": ebe,
        "resultat_exploitation": resultat_exploitation,
        "resultat_financier": resultat_financier,
        "resultat_activites_ordinaires": rao,
        "resultat_hao": resultat_hao,
        "resultat_net": resultat_net,
        "cafg": cafg,
    }
