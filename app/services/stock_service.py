"""
Service de gestion des stocks — moteur CUMP/FIFO + écritures SYSCOHADA.

Règles SYSCOHADA révisé :
- Méthode par défaut : CUMP (Coût Unitaire Moyen Pondéré)
- Méthode alternative : FIFO (First In, First Out)
- CUMP recalculé APRÈS chaque entrée (méthode permanente)
  Formule : CUMP = (valeur_stock_avant + valeur_entrée) / (qté_avant + qté_entrée)
- Sorties valorisées au CUMP courant (avant la sortie)
- FIFO : sortie consomme les couches les plus anciennes

Écritures générées :
- Entrée achat : Débit 3xx (stock) / Crédit 401 (fournisseur) [si achat direct]
- Sortie vente : Débit 603x (variation de stock) / Crédit 3xx (stock)
- Inventaire : constatation du stock final + annulation du stock théorique
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.stock_syscohada import (
    COMPTES_STOCK,
    JOURNAL_STOCK,
    METHODES_ADMISES,
    SENS_MOUVEMENT,
    TypeMouvement,
)
from app.models.enums import EcritureSource
from app.models.item_stock_placeholder import None  # placeholder, retiré
from app.models.stock import (
    FifoLayer,
    Item,
    StockInventory,
    StockInventoryLine,
    StockLevel,
    StockMovement,
    Warehouse,
)
from app.schemas.ecriture import EcritureCreate, LigneIn
from app.schemas.stock import (
    InventaireCreate,
    InventaireValiderRequest,
    MouvementEntreeCreate,
    MouvementSortieCreate,
    TransfertCreate,
)
from app.services.audit_service import AuditService
from app.services.journal_service import JournalService
from app.services.syscohada_service import SyscohadaService

logger = logging.getLogger(__name__)


class StockService:
    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.audit = AuditService(db)

    # ═════════════════════════════════════════════════════════════════════
    # ENTRÉE DE STOCK
    # ═════════════════════════════════════════════════════════════════════
    async def entree_stock(
        self, data: MouvementEntreeCreate, comptabiliser: bool = True
    ) -> StockMovement:
        """
        Enregistre une entrée de stock.
        - Recalcule le CUMP (si méthode CUMP)
        - Crée une couche FIFO (si méthode FIFO)
        - Met à jour StockLevel
        - Génère l'écriture comptable si demandé
        """
        item = await self._get_item(data.item_id)
        await self._get_warehouse(data.warehouse_id)

        if data.quantite <= 0:
            raise HTTPException(400, "Quantité doit être > 0")
        if data.prix_unitaire <= 0:
            raise HTTPException(400, "Prix unitaire doit être > 0")

        montant_ht = int(Decimal(str(data.quantite)) * Decimal(data.prix_unitaire))

        # Numéro unique
        numero = await self._generer_numero("ENT", data.date_mouvement)

        mouvement = StockMovement(
            tenant_id=self.tenant_id,
            numero=numero,
            date_mouvement=data.date_mouvement,
            type_mouvement=data.type_mouvement,
            item_id=item.id,
            warehouse_id=data.warehouse_id,
            quantite=Decimal(str(data.quantite)),
            prix_unitaire=data.prix_unitaire,
            montant_ht=montant_ht,
            libelle=data.libelle,
            reference_piece=data.reference_piece,
            created_by=self.user_id,
        )
        self.db.add(mouvement)
        await self.db.flush()

        # Mise à jour StockLevel
        level = await self._get_or_create_level(item.id, data.warehouse_id)

        # Recalcul selon méthode
        if item.methode_valorisation == "cump":
            await self._recalculer_cump(level, Decimal(str(data.quantite)), data.prix_unitaire)
        elif item.methode_valorisation in ("fifo", "peps"):
            await self._creer_couche_fifo(
                item.id, data.warehouse_id, mouvement.id,
                data.date_mouvement, Decimal(str(data.quantite)), data.prix_unitaire,
            )
            # Pour FIFO : valeur_stock = somme des couches restantes
            level.quantite = Decimal(str(level.quantite)) + Decimal(str(data.quantite))
            await self._recalculer_valeur_fifo(level)
        else:
            raise HTTPException(400, f"Méthode inconnue : {item.methode_valorisation}")

        level.dernier_mouvement_at = datetime.now(timezone.utc)

        # Écriture comptable
        if comptabiliser:
            ecriture_id = await self._generer_ecriture_entree(mouvement, item)
            mouvement.ecriture_id = ecriture_id

        await self.db.flush()
        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="STOCK_ENTREE",
            ressource="stock_movement",
            ressource_id=mouvement.id,
            payload={
                "item": item.code,
                "quantite": float(data.quantite),
                "montant": montant_ht,
                "methode": item.methode_valorisation,
            },
        )
        return mouvement

    # ═════════════════════════════════════════════════════════════════════
    # SORTIE DE STOCK
    # ═════════════════════════════════════════════════════════════════════
    async def sortie_stock(
        self, data: MouvementSortieCreate, comptabiliser: bool = True
    ) -> StockMovement:
        """
        Enregistre une sortie de stock.
        - Valorise la sortie selon méthode (CUMP courant ou FIFO)
        - Vérifie disponibilité
        - Met à jour StockLevel
        - Génère écriture comptable
        """
        item = await self._get_item(data.item_id)
        await self._get_warehouse(data.warehouse_id)

        if data.quantite <= 0:
            raise HTTPException(400, "Quantité doit être > 0")

        level = await self._get_or_create_level(item.id, data.warehouse_id)
        qte_dispo = Decimal(str(level.quantite))
        qte_demandee = Decimal(str(data.quantite))

        if qte_dispo < qte_demandee:
            raise HTTPException(
                400,
                f"Stock insuffisant pour {item.code} : "
                f"disponible={float(qte_dispo)}, demandé={float(qte_demandee)}",
            )

        # Valorisation selon méthode
        if item.methode_valorisation == "cump":
            cout_unitaire = int(Decimal(str(level.cump)).quantize(Decimal("1")))
            montant_ht = int(qte_demandee * Decimal(cout_unitaire))
            nouveau_cump = level.cump  # inchangé
            nouvelles_couches: list[tuple[UUID, Decimal]] = []

        elif item.methode_valorisation in ("fifo", "peps"):
            cout_unitaire, montant_ht, nouvelles_couches = await self._consommer_fifo(
                item.id, data.warehouse_id, qte_demandee
            )
            nouveau_cump = level.cump  # sera recalculé

        else:
            raise HTTPException(400, f"Méthode inconnue : {item.methode_valorisation}")

        numero = await self._generer_numero("SOR", data.date_mouvement)

        mouvement = StockMovement(
            tenant_id=self.tenant_id,
            numero=numero,
            date_mouvement=data.date_mouvement,
            type_mouvement=data.type_mouvement,
            item_id=item.id,
            warehouse_id=data.warehouse_id,
            quantite=qte_demandee,
            prix_unitaire=cout_unitaire,
            montant_ht=montant_ht,
            cump_au_moment=level.cump,
            cout_unitaire_sortie=cout_unitaire,
            libelle=data.libelle,
            reference_piece=data.reference_piece,
            created_by=self.user_id,
        )
        self.db.add(mouvement)
        await self.db.flush()

        # Mise à jour StockLevel
        level.quantite = qte_dispo - qte_demandee
        if item.methode_valorisation == "cump":
            level.valeur_stock = int(Decimal(str(level.quantite)) * Decimal(str(level.cump)))
        else:
            # FIFO : recalculer via les couches restantes
            await self._recalculer_valeur_fifo(level, nouvelles_couches)

        level.dernier_mouvement_at = datetime.now(timezone.utc)

        # Écriture comptable
        if comptabiliser:
            ecriture_id = await self._generer_ecriture_sortie(mouvement, item)
            mouvement.ecriture_id = ecriture_id

        await self.db.flush()
        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="STOCK_SORTIE",
            ressource="stock_movement",
            ressource_id=mouvement.id,
            payload={
                "item": item.code,
                "quantite": float(data.quantite),
                "cout_unitaire": cout_unitaire,
                "montant": montant_ht,
                "methode": item.methode_valorisation,
            },
        )
        return mouvement

    # ═════════════════════════════════════════════════════════════════════
    # TRANSFERT
    # ═════════════════════════════════════════════════════════════════════
    async def transferer(self, data: TransfertCreate) -> tuple[StockMovement, StockMovement]:
        """Transfert entre entrepôts : sortie + entrée liées."""
        item = await self._get_item(data.item_id)
        await self._get_warehouse(data.warehouse_source_id)
        await self._get_warehouse(data.warehouse_destination_id)

        # Sortie
        sortie = await self.sortie_stock(
            MouvementSortieCreate(
                item_id=data.item_id,
                warehouse_id=data.warehouse_source_id,
                date_mouvement=data.date_mouvement,
                quantite=data.quantite,
                libelle=f"Transfert → {data.libelle}",
                type_mouvement="sortie_ajustement",
            ),
            comptabiliser=False,
        )
        sortie.type_mouvement = TypeMouvement.TRANSFERT_SORTIE
        sortie.warehouse_destination_id = data.warehouse_destination_id

        # Entrée au prix de sortie (le coût ne change pas dans un transfert)
        entree = await self.entree_stock(
            MouvementEntreeCreate(
                item_id=data.item_id,
                warehouse_id=data.warehouse_destination_id,
                date_mouvement=data.date_mouvement,
                quantite=data.quantite,
                prix_unitaire=sortie.cout_unitaire_sortie or sortie.prix_unitaire,
                libelle=f"Transfert ← {data.libelle}",
                type_mouvement="entree_ajustement",
            ),
            comptabiliser=False,
        )
        entree.type_mouvement = TypeMouvement.TRANSFERT_ENTREE
        entree.warehouse_destination_id = data.warehouse_source_id

        await self.db.flush()
        return sortie, entree

    # ═════════════════════════════════════════════════════════════════════
    # INVENTAIRE
    # ═════════════════════════════════════════════════════════════════════
    async def creer_inventaire(self, data: InventaireCreate) -> StockInventory:
        await self._get_warehouse(data.warehouse_id)
        reference = data.reference or await self._generer_numero("INV", data.date_inventaire)

        inv = StockInventory(
            tenant_id=self.tenant_id,
            warehouse_id=data.warehouse_id,
            reference=reference,
            date_inventaire=data.date_inventaire,
            libelle=data.libelle,
            statut="en_cours",
            created_by=self.user_id,
        )
        self.db.add(inv)
        await self.db.flush()
        return inv

    async def valider_inventaire(
        self, inventory_id: UUID, data: InventaireValiderRequest
    ) -> StockInventory:
        """
        Valide l'inventaire :
        - Enregistre les quantités physiques
        - Calcule les écarts
        - Si comptabiliser=True : génère des mouvements d'ajustement + écriture SYSCOHADA
        """
        inv = await self.db.scalar(
            select(StockInventory).where(
                StockInventory.id == inventory_id,
                StockInventory.tenant_id == self.tenant_id,
            )
        )
        if inv is None:
            raise HTTPException(404, "Inventaire introuvable")
        if inv.statut == "comptabilise":
            raise HTTPException(400, "Inventaire déjà comptabilisé")

        total_theorique = 0
        total_physique = 0
        ecart_total = 0
        mouvements_ajustement: list[StockMovement] = []

        for ligne in data.lignes:
            item = await self._get_item(ligne.item_id)
            level = await self._get_or_create_level(item.id, inv.warehouse_id)
            qte_theorique = Decimal(str(level.quantite))
            qte_physique = Decimal(str(ligne.quantite_physique))
            ecart = qte_physique - qte_theorique
            cump = Decimal(str(level.cump))
            ecart_valeur = int(ecart * cump)

            inv_line = StockInventoryLine(
                inventory_id=inv.id,
                tenant_id=self.tenant_id,
                item_id=item.id,
                quantite_theorique=qte_theorique,
                quantite_physique=qte_physique,
                ecart_quantite=ecart,
                cump_au_moment=cump,
                ecart_valeur=ecart_valeur,
                motif_ecart=ligne.motif_ecart,
            )
            self.db.add(inv_line)

            total_theorique += int(qte_theorique * cump)
            total_physique += int(qte_physique * cump)
            ecart_total += ecart_valeur

            # Ajustement automatique si écart non nul
            if ecart != 0 and data.comptabiliser:
                if ecart > 0:
                    mv = await self.entree_stock(
                        MouvementEntreeCreate(
                            item_id=item.id,
                            warehouse_id=inv.warehouse_id,
                            date_mouvement=inv.date_inventaire,
                            quantite=float(ecart),
                            prix_unitaire=int(cump),
                            libelle=f"Inventaire {inv.reference} — écart positif",
                            reference_piece=inv.reference,
                            type_mouvement="entree_ajustement",
                        ),
                        comptabiliser=False,
                    )
                else:
                    mv = await self.sortie_stock(
                        MouvementSortieCreate(
                            item_id=item.id,
                            warehouse_id=inv.warehouse_id,
                            date_mouvement=inv.date_inventaire,
                            quantite=float(-ecart),
                            libelle=f"Inventaire {inv.reference} — écart négatif",
                            reference_piece=inv.reference,
                            type_mouvement="sortie_ajustement",
                        ),
                        comptabiliser=False,
                    )
                inv_line.comptabilise = True
                mouvements_ajustement.append(mv)

        inv.nb_articles = len(data.lignes)
        inv.valeur_theorique = total_theorique
        inv.valeur_physique = total_physique
        inv.ecart_valeur = ecart_total
        inv.statut = "valide"
        inv.valide_at = datetime.now(timezone.utc)

        # Écriture globale d'ajustement si demandé
        if data.comptabiliser and mouvements_ajustement:
            ecriture_id = await self._generer_ecriture_inventaire(inv, mouvements_ajustement)
            inv.ecriture_id = ecriture_id
            inv.statut = "comptabilise"

        await self.db.flush()
        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="STOCK_INVENTAIRE_VALIDE",
            ressource="stock_inventory",
            ressource_id=inv.id,
            payload={
                "reference": inv.reference,
                "nb_articles": inv.nb_articles,
                "ecart_valeur": inv.ecart_valeur,
                "comptabilise": data.comptabiliser,
            },
        )
        return inv

    # ═════════════════════════════════════════════════════════════════════
    # MOTEUR CUMP
    # ═════════════════════════════════════════════════════════════════════
    async def _recalculer_cump(
        self, level: StockLevel, qte_entree: Decimal, prix_entree: int
    ) -> None:
        """
        CUMP permanent : recalculé après chaque entrée.
        Formule : (valeur_avant + valeur_entrée) / (qté_avant + qté_entrée)
        """
        qte_avant = Decimal(str(level.quantite))
        valeur_avant = Decimal(str(level.valeur_stock))
        valeur_entree = qte_entree * Decimal(prix_entree)

        nouvelle_qte = qte_avant + qte_entree
        nouvelle_valeur = valeur_avant + valeur_entree

        if nouvelle_qte > 0:
            nouveau_cump = nouvelle_valeur / nouvelle_qte
        else:
            nouveau_cump = Decimal(prix_entree)

        level.quantite = nouvelle_qte
        level.cump = nouveau_cump
        level.valeur_stock = int(nouvelle_valeur)

    # ═════════════════════════════════════════════════════════════════════
    # MOTEUR FIFO
    # ═════════════════════════════════════════════════════════════════════
    async def _creer_couche_fifo(
        self,
        item_id: UUID,
        warehouse_id: UUID,
        mouvement_id: UUID,
        date_entree: date,
        qte: Decimal,
        prix_unitaire: int,
    ) -> FifoLayer:
        couche = FifoLayer(
            tenant_id=self.tenant_id,
            item_id=item_id,
            warehouse_id=warehouse_id,
            mouvement_entree_id=mouvement_id,
            date_entree=date_entree,
            quantite_initiale=qte,
            quantite_restante=qte,
            prix_unitaire=prix_unitaire,
        )
        self.db.add(couche)
        await self.db.flush()
        return couche

    async def _consommer_fifo(
        self, item_id: UUID, warehouse_id: UUID, qte_demandee: Decimal
    ) -> tuple[int, int, list[tuple[UUID, Decimal]]]:
        """
        Consomme les couches FIFO les plus anciennes.
        Retourne : (cout_unitaire_moyen_pondéré, montant_total, [(layer_id, qte_restante), ...])
        """
        couches = (
            await self.db.execute(
                select(FifoLayer)
                .where(
                    FifoLayer.item_id == item_id,
                    FifoLayer.warehouse_id == warehouse_id,
                    FifoLayer.quantite_restante > 0,
                )
                .order_by(FifoLayer.date_entree.asc(), FifoLayer.created_at.asc())
            )
        ).scalars().all()

        if not couches:
            raise HTTPException(400, "Aucune couche FIFO disponible")

        qte_restante_a_consommer = qte_demandee
        montant_total = Decimal(0)
        mises_a_jour: list[tuple[UUID, Decimal]] = []

        for couche in couches:
            if qte_restante_a_consommer <= 0:
                break
            dispo = Decimal(str(couche.quantite_restante))
            a_prendre = min(dispo, qte_restante_a_consommer)
            montant_total += a_prendre * Decimal(couche.prix_unitaire)
            nouvelle_qte = dispo - a_prendre
            couche.quantite_restante = nouvelle_qte
            mises_a_jour.append((couche.id, nouvelle_qte))
            qte_restante_a_consommer -= a_prendre

        if qte_restante_a_consommer > 0:
            raise HTTPException(400, "Couches FIFO insuffisantes")

        cout_unitaire_moyen = int(montant_total / qte_demandee) if qte_demandee > 0 else 0
        return cout_unitaire_moyen, int(montant_total), mises_a_jour

    async def _recalculer_valeur_fifo(
        self, level: StockLevel, modifs: list[tuple[UUID, Decimal]] | None = None
    ) -> None:
        """Recalcule la valeur du stock FIFO à partir des couches restantes."""
        couches = (
            await self.db.execute(
                select(FifoLayer).where(
                    FifoLayer.item_id == level.item_id,
                    FifoLayer.warehouse_id == level.warehouse_id,
                    FifoLayer.quantite_restante > 0,
                )
            )
        ).scalars().all()

        valeur = sum(
            int(Decimal(str(c.quantite_restante)) * Decimal(c.prix_unitaire))
            for c in couches
        )
        qte = sum((Decimal(str(c.quantite_restante)) for c in couches), Decimal(0))

        level.valeur_stock = valeur
        level.quantite = qte
        # CUMP moyen pour affichage (approximation FIFO)
        level.cump = (Decimal(valeur) / qte) if qte > 0 else Decimal(0)

    # ═════════════════════════════════════════════════════════════════════
    # Écritures SYSCOHADA
    # ═════════════════════════════════════════════════════════════════════
    async def _generer_ecriture_entree(
        self, mouvement: StockMovement, item: Item
    ) -> UUID | None:
        """
        Écriture d'entrée de stock.

        Cas 1 — Achat direct (facture fournisseur) : NE PAS passer par ici (c'est le module Achats qui gère).
        Cas 2 — Entrée ajustement (production, correction) : écriture stock uniquement.

        Dans cette méthode on enregistre uniquement l'entrée en stock :
          Débit 3xx Stock
          Crédit 603x Variation des stocks
        """
        compte_info = COMPTES_STOCK.get(item.famille_stock)
        if compte_info is None:
            logger.warning(f"[stock] Famille inconnue : {item.famille_stock}")
            return None

        # Vérifier que le journal ST existe, sinon OD
        try:
            await JournalService(self.db, self.tenant_id).get_by_code(JOURNAL_STOCK)
            journal_code = JOURNAL_STOCK
        except Exception:
            journal_code = "OD"

        lignes = [
            LigneIn(
                compte=compte_info.compte,
                libelle=f"Entrée {item.code} — {mouvement.libelle}",
                debit=mouvement.montant_ht,
            ),
            LigneIn(
                compte=compte_info.compte_variation,
                libelle="Variation de stock (entrée)",
                credit=mouvement.montant_ht,
            ),
        ]

        syscohada = SyscohadaService(self.db, self.tenant_id, self.user_id)
        ecriture = await syscohada.create(EcritureCreate(
            numero_piece=mouvement.numero,
            date_ecriture=mouvement.date_mouvement,
            code_journal=journal_code,
            libelle=f"Stock — {mouvement.libelle}",
            reference_ext=mouvement.reference_piece,
            source=EcritureSource.SYSTEME,
            lignes=lignes,
        ))
        return ecriture.id

    async def _generer_ecriture_sortie(
        self, mouvement: StockMovement, item: Item
    ) -> UUID | None:
        """
        Écriture de sortie de stock.
          Débit 603x Variation des stocks
          Crédit 3xx Stock
        """
        compte_info = COMPTES_STOCK.get(item.famille_stock)
        if compte_info is None:
            return None

        try:
            await JournalService(self.db, self.tenant_id).get_by_code(JOURNAL_STOCK)
            journal_code = JOURNAL_STOCK
        except Exception:
            journal_code = "OD"

        lignes = [
            LigneIn(
                compte=compte_info.compte_variation,
                libelle=f"Variation de stock (sortie) — {mouvement.libelle}",
                debit=mouvement.montant_ht,
            ),
            LigneIn(
                compte=compte_info.compte,
                libelle=f"Sortie {item.code} — {mouvement.libelle}",
                credit=mouvement.montant_ht,
            ),
        ]

        syscohada = SyscohadaService(self.db, self.tenant_id, self.user_id)
        ecriture = await syscohada.create(EcritureCreate(
            numero_piece=mouvement.numero,
            date_ecriture=mouvement.date_mouvement,
            code_journal=journal_code,
            libelle=f"Stock — {mouvement.libelle}",
            reference_ext=mouvement.reference_piece,
            source=EcritureSource.SYSTEME,
            lignes=lignes,
        ))
        return ecriture.id

    async def _generer_ecriture_inventaire(
        self, inv: StockInventory, mouvements: list[StockMovement]
    ) -> UUID | None:
        """
        Écriture globale d'inventaire : une seule écriture pour tous les ajustements.
        Regroupe par famille de stock.
        """
        # Agréger les ajustements par famille
        ajustements: dict[str, int] = {}
        for mv in mouvements:
            item = await self._get_item(mv.item_id)
            compte_info = COMPTES_STOCK.get(item.famille_stock)
            if compte_info is None:
                continue
            # Signe : entrée (+) ou sortie (-)
            signe = 1 if SENS_MOUVEMENT[mv.type_mouvement] == "entree" else -1
            montant = mv.montant_ht * signe
            ajustements[item.famille_stock] = ajustements.get(item.famille_stock, 0) + montant

        if not ajustements:
            return None

        lignes: list[LigneIn] = []
        for famille, montant_net in ajustements.items():
            if montant_net == 0:
                continue
            compte_info = COMPTES_STOCK[famille]
            if montant_net > 0:
                # Stock augmente : Débit 3xx / Crédit 603x
                lignes.append(LigneIn(
                    compte=compte_info.compte,
                    libelle=f"Inventaire {inv.reference} — {famille}",
                    debit=montant_net,
                ))
                lignes.append(LigneIn(
                    compte=compte_info.compte_variation,
                    libelle=f"Inventaire {inv.reference} — {famille}",
                    credit=montant_net,
                ))
            else:
                # Stock diminue : Débit 603x / Crédit 3xx
                lignes.append(LigneIn(
                    compte=compte_info.compte_variation,
                    libelle=f"Inventaire {inv.reference} — {famille}",
                    debit=-montant_net,
                ))
                lignes.append(LigneIn(
                    compte=compte_info.compte,
                    libelle=f"Inventaire {inv.reference} — {famille}",
                    credit=-montant_net,
                ))

        if not lignes:
            return None

        try:
            await JournalService(self.db, self.tenant_id).get_by_code(JOURNAL_STOCK)
            journal_code = JOURNAL_STOCK
        except Exception:
            journal_code = "OD"

        syscohada = SyscohadaService(self.db, self.tenant_id, self.user_id)
        ecriture = await syscohada.create(EcritureCreate(
            numero_piece=f"INV-{inv.reference}",
            date_ecriture=inv.date_inventaire,
            code_journal=journal_code,
            libelle=f"Régularisation inventaire {inv.reference}",
            source=EcritureSource.SYSTEME,
            lignes=lignes,
        ))
        return ecriture.id

    # ═════════════════════════════════════════════════════════════════════
    # Helpers
    # ═════════════════════════════════════════════════════════════════════
    async def _get_item(self, item_id: UUID) -> Item:
        item = await self.db.scalar(
            select(Item).where(
                Item.id == item_id,
                Item.tenant_id == self.tenant_id,
                Item.actif.is_(True),
            )
        )
        if item is None:
            raise HTTPException(404, "Article introuvable ou inactif")
        return item

    async def _get_warehouse(self, warehouse_id: UUID) -> Warehouse:
        wh = await self.db.scalar(
            select(Warehouse).where(
                Warehouse.id == warehouse_id,
                Warehouse.tenant_id == self.tenant_id,
                Warehouse.actif.is_(True),
            )
        )
        if wh is None:
            raise HTTPException(404, "Entrepôt introuvable ou inactif")
        return wh

    async def _get_or_create_level(
        self, item_id: UUID, warehouse_id: UUID
    ) -> StockLevel:
        level = await self.db.scalar(
            select(StockLevel).where(
                StockLevel.tenant_id == self.tenant_id,
                StockLevel.item_id == item_id,
                StockLevel.warehouse_id == warehouse_id,
            )
        )
        if level is None:
            level = StockLevel(
                tenant_id=self.tenant_id,
                item_id=item_id,
                warehouse_id=warehouse_id,
                quantite=Decimal(0),
                cump=Decimal(0),
                valeur_stock=0,
            )
            self.db.add(level)
            await self.db.flush()
        return level

    async def _generer_numero(self, prefixe: str, d: date) -> str:
        annee = d.year
        pattern = f"{prefixe}-{annee}-%"
        last = await self.db.scalar(
            select(func.max(StockMovement.numero)).where(
                StockMovement.tenant_id == self.tenant_id,
                StockMovement.numero.like(pattern),
            )
        )
        if last is None:
            seq = 1
        else:
            try:
                seq = int(last.split("-")[-1]) + 1
            except (ValueError, IndexError):
                seq = 1
        return f"{prefixe}-{annee}-{seq:05d}"
