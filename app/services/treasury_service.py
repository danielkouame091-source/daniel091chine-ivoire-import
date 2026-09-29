"""
Service Trésorerie & Rapprochement bancaire.

Fonctionnalités :
- CRUD comptes de trésorerie
- Import relevés (CSV, OFX, MT940)
- Rapprochement automatique (matching flou date + montant + libellé)
- Rapprochement manuel (pointeur)
- Génération automatique des écritures pour frais/interets bancaires
- État de rapprochement formel SYSCOHADA
- Tableau de bord 13 semaines (prévisions)
"""
from __future__ import annotations

import csv
import hashlib
import io
import logging
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException, UploadFile
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.treasury_syscohada import (
    COMPTE_ATTENTE_RAPPROCHEMENT,
    COMPTE_FRAIS_BANCAIRES,
    COMPTE_INTERETS_BANCAIRES,
    COMPTE_PRODUITS_BANCAIRES,
    ETAT_RAPPROCHEMENT_OK if False else None,  # placeholder
    EtatRapprochement,
    JOURNAL_BANQUE,
    JOURNAL_OD,
    MATCHING_DATE_TOLERANCE_JOURS,
    MATCHING_LIBELLE_SEUIL,
    MATCHING_MONTANT_TOLERANCE_PCT,
    StatutLigneReleve,
    StatutRapprochement,
    TypeLigneReleve,
)
from app.models.ecriture import Ecriture, EcritureLigne
from app.models.enums import EcritureSource
from app.models.treasury import (
    BankStatement,
    BankStatementLine,
    CashForecastWeek,
    CashPositionSnapshot,
    ReconciliationSession,
    TreasuryAccount,
)
from app.schemas.ecriture import EcritureCreate, LigneIn
from app.schemas.treasury import (
    BankStatementDetailOut,
    BankStatementLineOut,
    BankStatementOut,
    CandidatRapprochement,
    CashDashboard13WeeksOut,
    CashForecastWeekOut,
    CashPositionOut,
    EtatRapprochementOut,
    RapprochementAutoRequest,
    RapprochementAutoResultOut,
    ReconciliationSessionOut,
    TreasuryAccountCreate,
    TreasuryAccountUpdate,
)
from app.services.audit_service import AuditService
from app.services.journal_service import JournalService
from app.services.syscohada_service import SyscohadaService

logger = logging.getLogger(__name__)


class TreasuryService:
    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.audit = AuditService(db)

    # ═════════════════════════════════════════════════════════════════════
    # COMPTES DE TRÉSORERIE
    # ═════════════════════════════════════════════════════════════════════
    async def creer_compte(self, data: TreasuryAccountCreate) -> TreasuryAccount:
        existing = await self.db.scalar(
            select(TreasuryAccount.id).where(
                TreasuryAccount.tenant_id == self.tenant_id,
                or_(
                    TreasuryAccount.code == data.code,
                    TreasuryAccount.compte_comptable == data.compte_comptable,
                ),
            )
        )
        if existing:
            raise HTTPException(409, f"Code {data.code} ou compte {data.compte_comptable} déjà utilisé")

        # Si compte_principal=True, retirer le flag des autres
        if data.compte_principal:
            await self.db.execute(
                TreasuryAccount.__table__.update()
                .where(TreasuryAccount.tenant_id == self.tenant_id)
                .values(compte_principal=False)
            )

        acc = TreasuryAccount(tenant_id=self.tenant_id, **data.model_dump())
        self.db.add(acc)
        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="TREASURY_ACCOUNT_CREATE",
            ressource="treasury_account",
            ressource_id=acc.id,
            payload={"code": acc.code, "type": acc.type_compte},
        )
        return acc

    async def modifier_compte(self, acc_id: UUID, data: TreasuryAccountUpdate) -> TreasuryAccount:
        acc = await self._get_compte(acc_id)
        if data.compte_principal is True:
            await self.db.execute(
                TreasuryAccount.__table__.update()
                .where(TreasuryAccount.tenant_id == self.tenant_id, TreasuryAccount.id != acc_id)
                .values(compte_principal=False)
            )
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(acc, k, v)
        await self.db.flush()
        return acc

    async def recalculer_solde(self, acc_id: UUID) -> int:
        """
        Recalcule le solde comptable d'un compte depuis les écritures.
        Utile après un import initial ou en cas d'écart.
        """
        acc = await self._get_compte(acc_id)
        # Solde = somme(débits) - somme(crédits) des lignes sur ce compte
        stmt = (
            select(
                func.coalesce(func.sum(EcritureLigne.debit_xof), 0),
                func.coalesce(func.sum(EcritureLigne.credit_xof), 0),
            )
            .join(Ecriture, Ecriture.id == EcritureLigne.ecriture_id)
            .join(
                # Lien vers plan comptable par le code
                TreasuryAccount.__table__,  # dummy — corrigé plus bas
            )
        )
        # Requête propre : joindre plan_comptable par compte
        from app.models.plan_comptable import PlanComptable
        stmt = (
            select(
                func.coalesce(func.sum(EcritureLigne.debit_xof), 0),
                func.coalesce(func.sum(EcritureLigne.credit_xof), 0),
            )
            .join(PlanComptable, PlanComptable.id == EcritureLigne.compte_id)
            .join(Ecriture, Ecriture.id == EcritureLigne.ecriture_id)
            .where(
                EcritureLigne.tenant_id == self.tenant_id,
                PlanComptable.compte == acc.compte_comptable,
                Ecriture.statut.in_(["validee"]),
            )
        )
        result = (await self.db.execute(stmt)).one()
        solde = int(result[0] or 0) - int(result[1] or 0)

        acc.solde_comptable = solde
        await self.db.flush()
        return solde

    # ═════════════════════════════════════════════════════════════════════
    # IMPORT DE RELEVÉ
    # ═════════════════════════════════════════════════════════════════════
    async def importer_releve(
        self,
        treasury_account_id: UUID,
        file: UploadFile,
        format_source: str = "csv",
        reference: str | None = None,
    ) -> BankStatement:
        """
        Importe un relevé bancaire.
        Formats supportés : CSV (générique), OFX, MT940.
        """
        acc = await self._get_compte(treasury_account_id)

        content_bytes = await file.read()
        content_text = content_bytes.decode("utf-8", errors="replace")
        fichier_hash = hashlib.sha256(content_bytes).hexdigest()

        # Détection du doublon
        existing = await self.db.scalar(
            select(BankStatement.id).where(
                BankStatement.tenant_id == self.tenant_id,
                BankStatement.fichier_hash == fichier_hash,
            )
        )
        if existing:
            raise HTTPException(409, "Ce relevé a déjà été importé (hash identique)")

        # Parsing
        if format_source == "csv":
            lignes, solde_ouverture, solde_cloture, date_debut, date_fin = self._parse_csv(content_text)
        elif format_source == "ofx":
            lignes, solde_ouverture, solde_cloture, date_debut, date_fin = self._parse_ofx(content_text)
        elif format_source == "mt940":
            lignes, solde_ouverture, solde_cloture, date_debut, date_fin = self._parse_mt940(content_text)
        else:
            raise HTTPException(400, f"Format non supporté : {format_source}")

        if not lignes:
            raise HTTPException(400, "Aucune ligne valide dans le fichier")

        ref = reference or f"REL-{acc.code}-{date_debut.strftime('%Y%m')}"

        # Créer l'entête
        stmt = BankStatement(
            tenant_id=self.tenant_id,
            treasury_account_id=acc.id,
            reference=ref,
            date_debut=date_debut,
            date_fin=date_fin,
            format_source=format_source,
            fichier_nom=file.filename,
            fichier_hash=fichier_hash,
            solde_ouverture=solde_ouverture,
            solde_cloture=solde_cloture,
            nb_lignes=len(lignes),
            statut="importe",
            raw_content=content_text[:50_000],   # tronqué pour audit
            imported_by=self.user_id,
        )
        self.db.add(stmt)
        await self.db.flush()

        # Créer les lignes
        for l in lignes:
            line = BankStatementLine(
                tenant_id=self.tenant_id,
                statement_id=stmt.id,
                treasury_account_id=acc.id,
                date_operation=l["date_operation"],
                date_valeur=l.get("date_valeur"),
                libelle=l["libelle"],
                reference_banque=l.get("reference"),
                type_mouvement=l["type_mouvement"],
                montant=l["montant"],
                code_banque=l.get("code_banque"),
                categorie=self._categoriser(l["libelle"], l.get("code_banque")),
                statut_rapprochement=StatutLigneReleve.NON_RAPPROCHEE,
                raw_data=l.get("raw"),
            )
            self.db.add(line)

        # Mettre à jour le compte
        acc.solde_dernier_releve = solde_cloture
        acc.date_dernier_releve = date_fin

        await self.db.flush()
        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="BANK_STATEMENT_IMPORT",
            ressource="bank_statement",
            ressource_id=stmt.id,
            payload={
                "reference": ref,
                "nb_lignes": len(lignes),
                "format": format_source,
                "periode": f"{date_debut}→{date_fin}",
            },
        )
        return stmt

    # ═════════════════════════════════════════════════════════════════════
    # RAPPROCHEMENT AUTOMATIQUE
    # ═════════════════════════════════════════════════════════════════════
    async def rapprocher_automatique(
        self, data: RapprochementAutoRequest
    ) -> RapprochementAutoResultOut:
        """
        Rapprochement automatique par matching flou.

        Étapes :
        1. Lignes bancaires non rapprochées du relevé
        2. Pour chaque ligne, calcul du score de matching avec les lignes comptables
           candidates (compte de trésorerie, statut validée, non déjà rapprochée)
        3. Si score ≥ seuil → rapprochement automatique
        4. Si libellé = FRAIS/AGIOS/INTERETS → catégorisation + écriture auto
        5. Lignes restantes → ECART
        """
        stmt = await self._get_statement(data.statement_id)

        # Récupérer les lignes bancaires non rapprochées
        bank_lines = (
            await self.db.execute(
                select(BankStatementLine).where(
                    BankStatementLine.statement_id == stmt.id,
                    BankStatementLine.statut_rapprochement == StatutLigneReleve.NON_RAPPROCHEE,
                )
            )
        ).scalars().all()

        # Récupérer les lignes comptables candidates
        from app.models.plan_comptable import PlanComptable
        account = await self._get_compte(stmt.treasury_account_id)

        ecriture_lignes = (
            await self.db.execute(
                select(
                    EcritureLigne.id, EcritureLigne.ecriture_id,
                    Ecriture.date_ecriture, Ecriture.libelle,
                    EcritureLigne.debit_xof, EcritureLigne.credit_xof,
                )
                .join(PlanComptable, PlanComptable.id == EcritureLigne.compte_id)
                .join(Ecriture, Ecriture.id == EcritureLigne.ecriture_id)
                .where(
                    EcritureLigne.tenant_id == self.tenant_id,
                    PlanComptable.compte == account.compte_comptable,
                    Ecriture.statut == "validee",
                    EcritureLigne.lettrage_code.is_(None),  # non lettrée
                )
            )
        ).all()

        nb_auto = 0
        nb_exact = 0
        nb_ecarts = 0
        nb_frais = 0
        nb_interets = 0
        detail: list[dict[str, Any]] = []

        used_ecriture_lignes: set[UUID] = set()

        for bl in bank_lines:
            # Cas 1 : détection automatique frais/interets
            categorie = self._detecter_frais_interets(bl.libelle, bl.code_banque or "")
            if categorie in ("frais_bancaire", "interet_debiteur", "interet_crediteur"):
                ecriture_id = await self._generer_ecriture_frais(
                    stmt, bl, categorie, data.comptabiliser_frais
                )
                bl.statut_rapprochement = (
                    StatutLigneReleve.FRAIS_BANCAIRE if "frais" in categorie
                    else StatutLigneReleve.INTERET
                )
                bl.ecriture_id = ecriture_id
                bl.rapproche_at = datetime.now(timezone.utc)
                if "frais" in categorie:
                    nb_frais += 1
                else:
                    nb_interets += 1
                detail.append({"line_id": str(bl.id), "type": categorie, "montant": bl.montant})
                continue

            # Cas 2 : matching flou avec écritures
            candidats = self._trouver_candidats(
                bl, ecriture_lignes, used_ecriture_lignes,
                data.tolerance_jours, data.tolerance_montant_pct, data.seuil_libelle,
            )
            if candidats:
                best = candidats[0]
                # Rapprochement
                bl.ecriture_id = best["ecriture_id"]
                bl.ecriture_ligne_id = best["ecriture_ligne_id"]
                bl.score_matching = Decimal(str(round(best["score"], 2)))
                bl.statut_rapprochement = StatutLigneReleve.RAPPROCHEE_AUTO
                bl.rapproche_at = datetime.now(timezone.utc)
                used_ecriture_lignes.add(best["ecriture_ligne_id"])

                # Lettrage automatique
                await self._lettrer_ligne_comptable(best["ecriture_ligne_id"], bl.id)

                nb_auto += 1
                if best["score_montant"] >= 0.99 and best["score_date"] >= 0.9:
                    nb_exact += 1
                detail.append({
                    "line_id": str(bl.id),
                    "matched_to": str(best["ecriture_ligne_id"]),
                    "score": best["score"],
                })
            else:
                bl.statut_rapprochement = StatutLigneReleve.ECART
                nb_ecarts += 1

        stmt.nb_lignes_rapprochees = nb_auto + nb_frais + nb_interets
        stmt.statut = "rapproche"
        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="RAPPROCHEMENT_AUTO",
            ressource="bank_statement",
            ressource_id=stmt.id,
            payload={
                "nb_lignes": len(bank_lines),
                "nb_auto": nb_auto,
                "nb_frais": nb_frais,
                "nb_interets": nb_interets,
                "nb_ecarts": nb_ecarts,
            },
        )
        return RapprochementAutoResultOut(
            statement_id=stmt.id,
            nb_lignes_total=len(bank_lines),
            nb_rapprochees_auto=nb_auto,
            nb_rapprochees_montant_exact=nb_exact,
            nb_ecarts=nb_ecarts,
            nb_frais_bancaires=nb_frais,
            nb_interets=nb_interets,
            detail=detail,
        )

    async def rapprocher_manuel(
        self, statement_line_id: UUID, ecriture_ligne_id: UUID, creer_ecriture: bool = False
    ) -> BankStatementLine:
        """Rapprochement manuel d'une ligne bancaire avec une ligne comptable."""
        bl = await self.db.scalar(
            select(BankStatementLine).where(
                BankStatementLine.id == statement_line_id,
                BankStatementLine.tenant_id == self.tenant_id,
            )
        )
        if bl is None:
            raise HTTPException(404, "Ligne bancaire introuvable")
        if bl.statut_rapprochement == StatutLigneReveAUTO if False else bl.statut_rapprochement in (
            StatutLigneReleve.RAPPROCHEE_AUTO, StatutLigneReleve.RAPPROCHEE_MANUELLE
        ):
            raise HTTPException(400, "Ligne déjà rapprochée")

        el = await self.db.scalar(
            select(EcritureLigne).where(
                EcritureLigne.id == ecriture_ligne_id,
                EcritureLigne.tenant_id == self.tenant_id,
            )
        )
        if el is None:
            raise HTTPException(404, "Ligne comptable introuvable")

        # Vérifier que les montants correspondent (tolérance stricte en manuel)
        montant_compta = int(el.debit_xof) - int(el.credit_xof)
        montant_banque = bl.montant if bl.type_mouvement == "credit" else -bl.montant
        if abs(montant_compta - montant_banque) > 100:   # tolérance 100 FCFA
            raise HTTPException(
                400,
                f"Écart de montant trop important : compta={montant_compta} banque={montant_banque}",
            )

        bl.ecriture_id = el.ecriture_id
        bl.ecriture_ligne_id = el.id
        bl.statut_rapprochement = StatutLigneReleve.RAPPROCHEE_MANUELLE
        bl.rapproche_at = datetime.now(timezone.utc)
        bl.rapproche_par = self.user_id

        await self._lettrer_ligne_comptable(el.id, bl.id)
        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="RAPPROCHEMENT_MANUEL",
            ressource="bank_statement_line",
            ressource_id=bl.id,
            payload={"ecriture_ligne_id": str(el.id)},
        )
        return bl

    # ═════════════════════════════════════════════════════════════════════
    # SESSION DE RAPPROCHEMENT + ÉTAT FORMEL
    # ═════════════════════════════════════════════════════════════════════
    async def generer_etat_rapprochement(
        self, statement_id: UUID
    ) -> EtatRapprochementOut:
        """
        Génère l'état de rapprochement bancaire formel SYSCOHADA.
        Document que le comptable présente à l'auditeur.
        """
        stmt = await self._get_statement(statement_id)
        account = await self._get_compte(stmt.treasury_account_id)

        # Recalculer le solde comptable à la date de fin du relevé
        solde_comptable = await self._calculer_solde_comptable_a_date(
            account.compte_comptable, stmt.date_fin
        )

        # Lignes bancaires
        bank_lines = (
            await self.db.execute(
                select(BankStatementLine).where(BankStatementLine.statement_id == stmt.id)
            )
        ).scalars().all()

        # Lignes comptables non lettrées sur la période
        from app.models.plan_comptable import PlanComptable
        ecriture_lignes = (
            await self.db.execute(
                select(EcritureLigne, Ecriture)
                .join(Ecriture, Ecriture.id == EcritureLigne.ecriture_id)
                .join(PlanComptable, PlanComptable.id == EcritureLigne.compte_id)
                .where(
                    EcritureLigne.tenant_id == self.tenant_id,
                    PlanComptable.compte == account.compte_comptable,
                    Ecriture.date_ecriture <= stmt.date_fin,
                    Ecriture.statut == "validee",
                    EcritureLigne.lettrage_code.is_(None),
                )
            )
        ).all()

        # Calcul des ajustements
        credits_bancaires_non_compta = sum(
            bl.montant for bl in bank_lines
            if bl.type_mouvement == "credit"
            and bl.statut_rapprochement == StatutLigneReleve.ECART
        )
        debits_bancaires_non_compta = sum(
            bl.montant for bl in bank_lines
            if bl.type_mouvement == "debit"
            and bl.statut_rapprochement == StatutLigneReleve.ECART
        )
        frais_bancaires = sum(
            bl.montant for bl in bank_lines
            if bl.statut_rapprochement == StatutLigneReleve.FRAIS_BANCAIRE
        )
        interets_debiteurs = sum(
            bl.montant for bl in bank_lines
            if bl.statut_rapprochement == StatutLigneReleve.INTERET
            and bl.type_mouvement == "debit"
        )
        interets_crediteurs = sum(
            bl.montant for bl in bank_lines
            if bl.statut_rapprochement == StatutLigneReleve.INTERET
            and bl.type_mouvement == "credit"
        )

        # Formule : solde ajusté = solde compta
        #   - crédits bancaires non comptabilisés (à ajouter à la compta)
        #   + débits bancaires non comptabilisés (à déduire de la compta)
        #   - frais + interets débiteurs + interets créditeurs
        solde_comptable_ajuste = (
            solde_comptable
            + credits_bancaires_non_compta
            - debits_bancaires_non_compta
            - frais_bancaires
            - interets_debiteurs
            + interets_crediteurs
        )

        ecart = solde_comptable_ajuste - stmt.solde_cloture

        return EtatRapprochementOut(
            reference=stmt.reference,
            date_debut=stmt.date_debut,
            date_fin=stmt.date_fin,
            treasury_account_code=account.code,
            treasury_account_libelle=account.libelle,
            solde_comptable=solde_comptable,
            moins_credits_bancaires_non_comptabilises=credits_bancaires_non_compta,
            plus_debits_bancaires_non_comptabilises=debits_bancaires_non_compta,
            moins_frais_bancaires=frais_bancaires,
            moins_interets_debiteurs=interets_debiteurs,
            plus_interets_crediteurs=interets_crediteurs,
            solde_comptable_ajuste=solde_comptable_ajuste,
            solde_bancaire=stmt.solde_cloture,
            ecart=ecart,
            equilibre=abs(ecart) < 1,
            lignes_comptables_non_rapprochees=[
                {
                    "ecriture_id": str(el.ecriture_id),
                    "date": el_ecr.date_ecriture.isoformat(),
                    "libelle": el_ecr.libelle,
                    "montant": int(el.debit_xof) - int(el.credit_xof),
                }
                for el, el_ecr in ecriture_lignes
            ],
            lignes_bancaires_non_rapprochees=[
                {
                    "line_id": str(bl.id),
                    "date": bl.date_operation.isoformat(),
                    "libelle": bl.libelle,
                    "montant": bl.montant,
                    "type": bl.type_mouvement,
                }
                for bl in bank_lines
                if bl.statut_rapprochement == StatutLigneReleve.ECART
            ],
        )

    async def creer_session_rapprochement(
        self, statement_id: UUID
    ) -> ReconciliationSession:
        """Crée une session persistée + génère l'écriture de régularisation."""
        stmt = await self._get_statement(statement_id)
        account = await self._get_compte(stmt.treasury_account_id)
        etat = await self.generer_etat_rapprochement(statement_id)

        # Compter
        nb_total = stmt.nb_lignes
        nb_rappro = stmt.nb_lignes_rapprochees
        nb_ecarts = nb_total - nb_rappro

        reference = f"REC-{account.code}-{stmt.date_fin.strftime('%Y%m%d')}"

        session = ReconciliationSession(
            tenant_id=self.tenant_id,
            treasury_account_id=account.id,
            statement_id=stmt.id,
            reference=reference,
            date_debut=stmt.date_debut,
            date_fin=stmt.date_fin,
            solde_comptable=etat.solde_comptable,
            solde_bancaire=etat.solde_bancaire,
            total_credits_non_comptabilises=etat.moins_credits_bancaires_non_comptabilises,
            total_debits_non_comptabilises=etat.plus_debits_bancaires_non_comptabilises,
            total_frais_bancaires=etat.moins_frais_bancaires,
            total_interets=etat.moins_interets_debiteurs - etat.plus_interets_crediteurs,
            ecart=etat.ecart,
            etat=EtatRapprochement.OK if etat.equilibre else (
                EtatRapprochement.ECART_POSITIF if etat.ecart > 0
                else EtatRapprochement.ECART_NEGATIF
            ),
            statut=StatutRapprochement.EQUILIBRE if etat.equilibre else StatutRapprochement.ECART,
            nb_lignes_total=nb_total,
            nb_lignes_rapprochees=nb_rappro,
            nb_ecarts=nb_ecarts,
            ecarts_detail=etat.lignes_bancaires_non_rapprochees,
            created_by=self.user_id,
        )
        self.db.add(session)
        await self.db.flush()

        # Écriture de régularisation si frais/interets non comptabilisés
        if etat.moins_frais_bancaires > 0 or etat.moins_interets_debiteurs > 0:
            ecriture_id = await self._generer_ecriture_regularisation(
                stmt, account, etat
            )
            session.ecriture_regularisation_id = ecriture_id

        if etat.equilibre:
            session.valide_at = datetime.now(timezone.utc)
            session.valide_par = self.user_id
            session.statut = StatutRapprochement.VALIDE
            stmt.statut = "cloture"
            stmt.date_cloture = datetime.now(timezone.utc)

        await self.db.flush()
        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="RECONCILIATION_SESSION_CREATE",
            ressource="reconciliation_session",
            ressource_id=session.id,
            payload={"reference": reference, "ecart": etat.ecart, "equilibre": etat.equilibre},
        )
        return session

    # ═════════════════════════════════════════════════════════════════════
    # TABLEAU DE BORD 13 SEMAINES
    # ═════════════════════════════════════════════════════════════════════
    async def calculer_position_actuelle(self) -> CashPositionOut:
        """Position de trésorerie consolidée à l'instant T."""
        accounts = (
            await self.db.execute(
                select(TreasuryAccount).where(
                    TreasuryAccount.tenant_id == self.tenant_id,
                    TreasuryAccount.actif.is_(True),
                )
            )
        ).scalars().all()

        detail = []
        solde_banques = 0
        solde_caisses = 0
        solde_mm = 0
        solde_placements = 0
        today = date.today()

        for acc in accounts:
            solde = await self._calculer_solde_comptable_a_date(acc.compte_comptable, today)
            detail.append({
                "code": acc.code,
                "libelle": acc.libelle,
                "type": acc.type_compte,
                "solde": solde,
            })
            if acc.type_compte == "banque":
                solde_banques += solde
            elif acc.type_compte == "caisse":
                solde_caisses += solde
            elif acc.type_compte == "mobile_money":
                solde_mm += solde
            elif acc.type_compte == "placement":
                solde_placements += solde

        solde_total = solde_banques + solde_caisses + solde_mm + solde_placements

        # Variations (comparer avec J-1, S-1, M-1)
        var_j1 = await self._calculer_variation(today - timedelta(days=1))
        var_s1 = await self._calculer_variation(today - timedelta(days=7))
        var_m1 = await self._calculer_variation(today - timedelta(days=30))

        # Snapshot
        snapshot = CashPositionSnapshot(
            tenant_id=self.tenant_id,
            date_snapshot=today,
            solde_total=solde_total,
            solde_banques=solde_banques,
            solde_caisses=solde_caisses,
            solde_mobile_money=solde_mm,
            solde_placements=solde_placements,
            detail_comptes=detail,
            variation_j1=var_j1,
            variation_s1=var_s1,
            variation_m1=var_m1,
            created_at=datetime.now(timezone.utc),
        )
        # Upsert (si un snapshot existe déjà pour aujourd'hui, on le met à jour)
        existing = await self.db.scalar(
            select(CashPositionSnapshot).where(
                CashPositionSnapshot.tenant_id == self.tenant_id,
                CashPositionSnapshot.date_snapshot == today,
            )
        )
        if existing:
            existing.solde_total = solde_total
            existing.solde_banques = solde_banques
            existing.solde_caisses = solde_caisses
            existing.solde_mobile_money = solde_mm
            existing.solde_placements = solde_placements
            existing.detail_comptes = detail
            existing.variation_j1 = var_j1
            existing.variation_s1 = var_s1
            existing.variation_m1 = var_m1
        else:
            self.db.add(snapshot)
        await self.db.flush()

        return CashPositionOut(
            date_snapshot=today,
            solde_total=solde_total,
            solde_banques=solde_banques,
            solde_caisses=solde_caisses,
            solde_mobile_money=solde_mm,
            solde_placements=solde_placements,
            variation_j1=var_j1,
            variation_s1=var_s1,
            variation_m1=var_m1,
            detail_comptes=detail,
        )

    async def calculer_previsions_13_semaines(self) -> CashDashboard13WeeksOut:
        """
        Tableau de bord DAF : position actuelle + 13 semaines de prévisions.
        Sources de prévision :
        - Factures clients non payées (échéances futures)
        - Factures fournisseurs non payées (échéances futures)
        - Salaires (brique 14 — bulletins prévisionnels)
        - Impôts (brique 14 — échéances DGI/CNPS)
        """
        today = date.today()
        position = await self.calculer_position_actuelle()
        solde_courant = position.solde_total

        # Calculer les 13 semaines
        semaines: list[CashForecastWeekOut] = []
        total_entrees = 0
        total_sorties = 0
        premiere_negative: str | None = None
        creux_max = solde_courant

        # Charger les données sources
        from app.models.sale import CustomerInvoice
        from app.models.purchase import SupplierInvoice

        # Factures clients non payées (à encaisser)
        client_invoices = (
            await self.db.execute(
                select(CustomerInvoice).where(
                    CustomerInvoice.tenant_id == self.tenant_id,
                    CustomerInvoice.solde_du > 0,
                    CustomerInvoice.statut.in_(["validee", "partiellement_payee", "en_retard"]),
                    CustomerInvoice.date_echeance >= today,
                )
            )
        ).scalars().all()

        # Factures fournisseurs non payées (à payer)
        supplier_invoices = (
            await self.db.execute(
                select(SupplierInvoice).where(
                    SupplierInvoice.tenant_id == self.tenant_id,
                    SupplierInvoice.solde_du > 0,
                    SupplierInvoice.statut.in_(["validee", "partiellement_payee"]),
                    SupplierInvoice.date_echeance >= today,
                )
            )
        ).scalars().all()

        # Salaires prévisionnels : moyenne des 3 derniers mois
        from app.models.payroll import Payslip
        trois_mois = today - timedelta(days=90)
        salaires_total = int(await self.db.scalar(
            select(func.coalesce(func.sum(Payslip.net_a_payer), 0)).where(
                Payslip.tenant_id == self.tenant_id,
                Payslip.date_paie >= trois_mois,
            )
        ) or 0)
        salaire_mensuel = salaires_total // 3 if salaires_total else 0

        # Impôts : estimation moyenne
        from app.models.payroll import DgiDeclaration
        impots_total = int(await self.db.scalar(
            select(func.coalesce(func.sum(DgiDeclaration.montant_net), 0)).where(
                DgiDeclaration.tenant_id == self.tenant_id,
                DgiDeclaration.created_at >= trois_mois,
            )
        ) or 0)
        impots_mensuel = impots_total // 3 if impots_total else 0

        # Boucle sur 13 semaines
        for i in range(13):
            debut = today + timedelta(days=i * 7)
            fin = debut + timedelta(days=6)
            semaine_iso = f"{debut.isocalendar()[0]}-W{debut.isocalendar()[1]:02d}"

            # Encaissements clients de la semaine
            encaissements = sum(
                inv.solde_du for inv in client_invoices
                if debut <= inv.date_echeance <= fin
            )
            # Paiements fournisseurs
            paiements = sum(
                inv.solde_du for inv in supplier_invoices
                if debut <= inv.date_echeance <= fin
            )
            # Salaires (dernier vendredi du mois)
            salaires_semaine = 0
            for d in [debut + timedelta(days=j) for j in range(7)]:
                if d.day >= 25 and d.weekday() == 4:  # vendredi après le 25
                    salaires_semaine = salaire_mensuel
                    break
            # Impôts (le 10 et le 15 du mois)
            impots_semaine = 0
            for d in [debut + timedelta(days=j) for j in range(7)]:
                if d.day in (10, 15):
                    impots_semaine += impots_mensuel // 2

            entrees = encaissements
            sorties = paiements + salaires_semaine + impots_semaine
            solde_prevu = solde_courant + entrees - sorties

            alerte = solde_prevu < 0
            if alerte and premiere_negative is None:
                premiere_negative = semaine_iso
            if solde_prevu < creux_max:
                creux_max = solde_prevu

            fiabilite = "elevee" if i < 4 else ("moyenne" if i < 8 else "faible")

            semaine = CashForecastWeekOut(
                semaine_iso=semaine_iso,
                date_debut=debut,
                date_fin=fin,
                solde_ouverture=solde_courant,
                entrees_prevues=entrees,
                sorties_prevues=sorties,
                solde_cloture_prevu=solde_prevu,
                encaissements_clients=encaissements,
                paiements_fournisseurs=paiements,
                salaires=salaires_semaine,
                impots_taxes=impots_semaine,
                autres_entrees=0,
                autres_sorties=0,
                fiabilite=fiabilite,
                alerte_negative=alerte,
                detail_previsions=[],
            )
            semaines.append(semaine)

            total_entrees += entrees
            total_sorties += sorties
            solde_courant = solde_prevu

        # Résumé IA (facultatif)
        resume = None
        from app.core.config import settings
        if settings.nlp_enabled:
            try:
                from app.integrations.openai_client import get_openai_client
                client = get_openai_client()
                resume = await client.chat_text(
                    "Tu es un directeur financier africain expérimenté.",
                    f"Position trésorerie actuelle : {position.solde_total:,} FCFA. "
                    f"Prévisions 13 semaines : entrées {total_entrees:,} FCFA, "
                    f"sorties {total_sorties:,} FCFA, solde final {solde_courant:,} FCFA. "
                    f"Première semaine négative : {premiere_negative or 'aucune'}. "
                    f"Rédige un résumé en 3 phrases pour le dirigeant avec recommandation."
                    .replace(",", " "),
                    temperature=0.2, max_tokens=200,
                )
            except Exception:
                logger.exception("[treasury] Résumé IA échoué")

        return CashDashboard13WeeksOut(
            date_arret=today,
            position_actuelle=position,
            semaines=semaines,
            total_entrees_13s=total_entrees,
            total_sorties_13s=total_sorties,
            solde_final_13s=solde_courant,
            premiere_semaine_negative=premiere_negative,
            creux_max=creux_max,
            resume_ia=resume,
        )

    # ═════════════════════════════════════════════════════════════════════
    # HELPERS — Matching flou
    # ═════════════════════════════════════════════════════════════════════
    def _trouver_candidats(
        self,
        bl: BankStatementLine,
        ecriture_lignes: list[Any],
        used: set[UUID],
        tol_jours: int,
        tol_montant_pct: float,
        seuil_libelle: float,
    ) -> list[dict[str, Any]]:
        """Trouve les écritures candidates pour une ligne bancaire."""
        montant_banque_abs = bl.montant
        sens_banque = "credit" if bl.type_mouvement == "credit" else "debit"
        libelle_bank_norm = self._normaliser_libelle(bl.libelle)

        candidats: list[dict[str, Any]] = []
        tol_montant = int(montant_banque_abs * tol_montant_pct) + 1

        for el_id, ecr_id, ecr_date, ecr_libelle, debit, credit in ecriture_lignes:
            if el_id in used:
                continue

            # Sens : débit compta = sortie banque, crédit compta = entrée banque
            montant_compta = int(debit) - int(credit)
            if montant_compta == 0:
                continue

            # Sens opposé : débit compta → crédit banque (sortie)
            sens_compta = "debit" if montant_compta > 0 else "credit"
            # Pour un rapprochement, le sens doit correspondre :
            # ligne banque "credit" (entrée) ↔ ligne compta "credit" (trésorerie créditée)
            # ligne banque "debit" (sortie) ↔ ligne compta "debit" (trésorerie débitée)
            if sens_banque != sens_compta:
                # Tolérer la confusion
                pass

            # Montant
            ecart_montant = abs(abs(montant_compta) - montant_banque_abs)
            if ecart_montant > tol_montant:
                continue

            score_montant = 1.0 - (ecart_montant / max(abs(montant_compta), 1))

            # Date
            ecart_jours = abs((ecr_date - bl.date_operation).days)
            if ecart_jours > tol_jours:
                continue
            score_date = 1.0 - (ecart_jours / max(tol_jours, 1))

            # Libellé
            score_libelle = SequenceMatcher(
                None, libelle_bank_norm, self._normaliser_libelle(ecr_libelle)
            ).ratio()

            # Score global pondéré
            # Priorité au montant exact
            if score_montant >= 0.999:
                score = 0.5 + 0.25 * score_date + 0.25 * score_libelle
            else:
                score = 0.5 * score_montant + 0.25 * score_date + 0.25 * score_libelle

            if score >= 0.6 or (score_montant >= 0.99 and score_date >= 0.5):
                candidats.append({
                    "ecriture_ligne_id": el_id,
                    "ecriture_id": ecr_id,
                    "date_ecriture": ecr_date,
                    "libelle": ecr_libelle,
                    "montant": abs(montant_compta),
                    "sens": sens_compta,
                    "score": score,
                    "score_date": score_date,
                    "score_montant": score_montant,
                    "score_libelle": score_libelle,
                })

        # Tri par score décroissant
        candidats.sort(key=lambda c: c["score"], reverse=True)
        return candidats[:3]  # top 3

    def _normaliser_libelle(self, s: str) -> str:
        """Normalise un libellé pour la comparaison textuelle."""
        s = s.lower()
        s = unicodedata.normalize("NFD", s)
        s = "".join(c for c in s if unicodedata.category(c) != "Mn")
        s = re.sub(r"[^a-z0-9\s]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def _detecter_frais_interets(self, libelle: str, code: str) -> str:
        """Détecte si une ligne est un frais ou un intérêt bancaire."""
        l = self._normaliser_libelle(libelle)
        c = (code or "").upper()
        if any(k in l for k in ("frais", "commission", "tenue", "agios")) or c in ("FRAIS", "COM", "TENUE", "AGIOS"):
            return "frais_bancaire"
        if any(k in l for k in ("interets debiteurs", "interet debiteur")) or c == "INTERETS":
            # À affiner selon le sens
            return "interet_debiteur"
        if any(k in l for k in ("interets crediteurs", "interet crediteur")):
            return "interet_crediteur"
        return ""

    def _categoriser(self, libelle: str, code: str | None) -> str:
        """Catégorise une ligne pour les statistiques."""
        l = self._normaliser_libelle(libelle)
        if "wave" in l or "OM" in (code or "") or "orange" in l:
            return "mobile_money"
        if "virement" in l or "vir" in (code or "").lower():
            return "virement"
        if "cheque" in l or "chq" in (code or "").lower():
            return "cheque"
        if "frais" in l or "commission" in l:
            return "frais"
        if "salaire" in l or "paie" in l:
            return "salaire"
        if "impot" in l or "dgi" in l or "cnps" in l:
            return "impot"
        return "autre"

    # ═════════════════════════════════════════════════════════════════════
    # HELPERS — Parsers
    # ═════════════════════════════════════════════════════════════════════
    def _parse_csv(self, content: str) -> tuple[list[dict[str, Any]], int, int, date, date]:
        """
        Parse un CSV bancaire.
        Format attendu (colonnes) : date, libelle, debit, credit, [reference]
        """
        reader = csv.DictReader(io.StringIO(content), delimiter=";")
        if not reader.fieldnames:
            reader = csv.DictReader(io.StringIO(content), delimiter=",")

        lignes: list[dict[str, Any]] = []
        for row in reader:
            row_lower = {k.lower().strip(): v for k, v in row.items() if k}
            date_str = row_lower.get("date") or row_lower.get("date_operation")
            if not date_str:
                continue
            try:
                date_op = self._parse_date(date_str)
            except ValueError:
                continue

            debit = self._parse_montant(row_lower.get("debit", "0"))
            credit = self._parse_montant(row_lower.get("credit", "0"))
            if debit > 0:
                type_mv = "debit"
                montant = debit
            elif credit > 0:
                type_mv = "credit"
                montant = credit
            else:
                continue

            lignes.append({
                "date_operation": date_op,
                "date_valeur": None,
                "libelle": row_lower.get("libelle", row_lower.get("description", "")),
                "reference": row_lower.get("reference"),
                "type_mouvement": type_mv,
                "montant": montant,
                "code_banque": None,
                "raw": row_lower,
            })

        if not lignes:
            raise HTTPException(400, "Aucune ligne valide dans le CSV")

        # Trier par date
        lignes.sort(key=lambda x: x["date_operation"])
        date_debut = lignes[0]["date_operation"]
        date_fin = lignes[-1]["date_operation"]

        # Solde ouverture / clôture : calculés ou extraits
        solde_ouverture = 0
        solde_cloture = 0
        for l in lignes:
            if l["type_mouvement"] == "credit":
                solde_cloture += l["montant"]
            else:
                solde_cloture -= l["montant"]

        return lignes, solde_ouverture, solde_cloture, date_debut, date_fin

    def _parse_ofx(self, content: str) -> tuple[list[dict[str, Any]], int, int, date, date]:
        """Parse un fichier OFX (format international)."""
        lignes: list[dict[str, Any]] = []
        # Regex simplifiée pour extraire STMTTRN
        pattern = re.compile(
            r"<STMTTRN>(.*?)</STMTTRN>", re.DOTALL | re.IGNORECASE
        )
        for match in pattern.finditer(content):
            block = match.group(1)
            dtposted = re.search(r"<DTPOSTED>(\d{8})", block, re.IGNORECASE)
            trnamt = re.search(r"<TRNAMT>(-?[\d.]+)", block, re.IGNORECASE)
            memo = re.search(r"<MEMO>([^<\n]+)", block, re.IGNORECASE)
            name = re.search(r"<NAME>([^<\n]+)", block, re.IGNORECASE)
            fitid = re.search(r"<FITID>([^<\n]+)", block, re.IGNORECASE)

            if not (dtposted and trnamt):
                continue

            date_str = dtposted.group(1)
            date_op = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
            montant_float = float(trnamt.group(1))

            type_mv = "credit" if montant_float > 0 else "debit"
            montant = int(abs(montant_float))

            libelle = (memo.group(1) if memo else "") or (name.group(1) if name else "")

            lignes.append({
                "date_operation": date_op,
                "date_valeur": None,
                "libelle": libelle.strip(),
                "reference": fitid.group(1) if fitid else None,
                "type_mouvement": type_mv,
                "montant": montant,
                "code_banque": None,
                "raw": {"raw": block[:500]},
            })

        if not lignes:
            raise HTTPException(400, "Aucune transaction OFX valide")

        lignes.sort(key=lambda x: x["date_operation"])
        return lignes, 0, 0, lignes[0]["date_operation"], lignes[-1]["date_operation"]

    def _parse_mt940(self, content: str) -> tuple[list[dict[str, Any]], int, int, date, date]:
        """Parse un fichier MT940 (format SWIFT utilisé par les banques CI)."""
        lignes: list[dict[str, Any]] = []
        current_date: date | None = None
        current_montant: int = 0
        current_libelle: str = ""
        current_type = "debit"

        for line in content.split("\n"):
            line = line.strip()
            if line.startswith(":61:"):
                # :61:YYMMDD[MMDD]C/D[amount],...
                # Format simplifié
                try:
                    date_str = line[4:10]  # YYMMDD
                    yy = int(date_str[:2])
                    annee = 2000 + yy if yy < 50 else 1900 + yy
                    date_op = date(annee, int(date_str[2:4]), int(date_str[4:6]))

                    type_char = line[10] if len(line) > 10 else "D"
                    current_type = "credit" if type_char == "C" else "debit"

                    # Montant : après le C/D
                    montant_str = line[11:26].replace(",", ".").strip()
                    current_montant = int(float(montant_str) * 100) if "." in montant_str else int(montant_str)

                    current_date = date_op
                except (ValueError, IndexError):
                    continue
            elif line.startswith(":86:") and current_date:
                current_libelle = line[4:].strip()
                lignes.append({
                    "date_operation": current_date,
                    "date_valeur": None,
                    "libelle": current_libelle or "Opération bancaire",
                    "reference": None,
                    "type_mouvement": current_type,
                    "montant": current_montant,
                    "code_banque": None,
                    "raw": {"source": "mt940"},
                })
                current_date = None
                current_libelle = ""

        if not lignes:
            raise HTTPException(400, "Aucune transaction MT940 valide")

        lignes.sort(key=lambda x: x["date_operation"])
        return lignes, 0, 0, lignes[0]["date_operation"], lignes[-1]["date_operation"]

    @staticmethod
    def _parse_date(s: str) -> date:
        s = s.strip()
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y%m%d", "%d.%m.%Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        raise ValueError(f"Date invalide : {s}")

    @staticmethod
    def _parse_montant(s: Any) -> int:
        if s is None or s == "":
            return 0
        s = str(s).strip().replace(" ", "").replace(",", ".")
        try:
            return int(abs(float(s)))
        except (ValueError, TypeError):
            return 0

    # ═════════════════════════════════════════════════════════════════════
    # HELPERS — Lettrage & écritures
    # ═════════════════════════════════════════════════════════════════════
    async def _lettrer_ligne_comptable(self, ecriture_ligne_id: UUID, bl_id: UUID) -> None:
        """Marque une ligne comptable comme lettrée (rapprochée)."""
        await self.db.execute(
            EcritureLigne.__table__.update()
            .where(EcritureLigne.id == ecriture_ligne_id)
            .values(
                lettrage_code=f"BQ-{str(bl_id)[:8]}",
                lettrage_at=datetime.now(timezone.utc),
            )
        )

    async def _generer_ecriture_frais(
        self,
        stmt: BankStatement,
        bl: BankStatementLine,
        categorie: str,
        comptabiliser: bool,
    ) -> UUID | None:
        """
        Génère l'écriture automatique pour frais ou intérêts bancaires.

        Frais : Débit 631800 / Crédit 521xxx
        Intérêts débiteurs : Débit 671000 / Crédit 521xxx
        Intérêts créditeurs : Débit 521xxx / Crédit 771000
        """
        if not comptabiliser:
            return None

        account = await self._get_compte(stmt.treasury_account_id)

        if categorie == "frais_bancaire":
            lignes = [
                LigneIn(compte=COMPTE_FRAIS_BANCAIRES, libelle=f"Frais bancaires — {bl.libelle}", debit=bl.montant),
                LigneIn(compte=account.compte_comptable, libelle=f"Frais bancaires — {bl.libelle}", credit=bl.montant),
            ]
        elif categorie == "interet_debiteur":
            lignes = [
                LigneIn(compte=COMPTE_INTERETS_BANCAIRES, libelle=f"Intérêts débiteurs — {bl.libelle}", debit=bl.montant),
                LigneIn(compte=account.compte_comptable, libelle=f"Intérêts débiteurs", credit=bl.montant),
            ]
        elif categorie == "interet_crediteur":
            lignes = [
                LigneIn(compte=account.compte_comptable, libelle=f"Intérêts créditeurs", debit=bl.montant),
                LigneIn(compte=COMPTE_PRODUITS_BANCAIRES, libelle=f"Intérêts créditeurs — {bl.libelle}", credit=bl.montant),
            ]
        else:
            return None

        try:
            await JournalService(self.db, self.tenant_id).get_by_code(JOURNAL_BANQUE)
            journal_code = JOURNAL_BANQUE
        except Exception:
            journal_code = JOURNAL_OD

        syscohada = SyscohadaService(self.db, self.tenant_id, self.user_id)
        e = await syscohada.create(EcritureCreate(
            numero_piece=f"BQ-{stmt.reference}-{str(bl.id)[:6]}",
            date_ecriture=bl.date_operation,
            code_journal=journal_code,
            libelle=f"{bl.libelle}",
            reference_ext=stmt.reference,
            source=EcritureSource.SYSTEME,
            lignes=lignes,
        ))
        return e.id

    async def _generer_ecriture_regularisation(
        self,
        stmt: BankStatement,
        account: TreasuryAccount,
        etat: EtatRapprochementOut,
    ) -> UUID | None:
        """Écriture globale de régularisation des frais/interets non comptabilisés."""
        lignes: list[LigneIn] = []

        if etat.moins_frais_bancaires > 0:
            lignes.append(LigneIn(
                compte=COMPTE_FRAIS_BANCAIRES,
                libelle=f"Frais bancaires {stmt.reference}",
                debit=etat.moins_frais_bancaires,
            ))
            lignes.append(LigneIn(
                compte=account.compte_comptable,
                libelle=f"Frais bancaires {stmt.reference}",
                credit=etat.moins_frais_bancaires,
            ))

        if etat.moins_interets_debiteurs > 0:
            lignes.append(LigneIn(
                compte=COMPTE_INTERETS_BANCAIRES,
                libelle=f"Intérêts débiteurs {stmt.reference}",
                debit=etat.moins_interets_debiteurs,
            ))
            lignes.append(LigneIn(
                compte=account.compte_comptable,
                libelle="Intérêts débiteurs",
                credit=etat.moins_interets_debiteurs,
            ))

        if etat.plus_interets_crediteurs > 0:
            lignes.append(LigneIn(
                compte=account.compte_comptable,
                libelle="Intérêts créditeurs",
                debit=etat.plus_interets_crediteurs,
            ))
            lignes.append(LigneIn(
                compte=COMPTE_PRODUITS_BANCAIRES,
                libelle=f"Intérêts créditeurs {stmt.reference}",
                credit=etat.plus_interets_crediteurs,
            ))

        if not lignes:
            return None

        try:
            await JournalService(self.db, self.tenant_id).get_by_code(JOURNAL_BANQUE)
            journal_code = JOURNAL_BANQUE
        except Exception:
            journal_code = JOURNAL_OD

        syscohada = SyscohadaService(self.db, self.tenant_id, self.user_id)
        e = await syscohada.create(EcritureCreate(
            numero_piece=f"REG-{stmt.reference}",
            date_ecriture=stmt.date_fin,
            code_journal=journal_code,
            libelle=f"Régularisation rapprochement {stmt.reference}",
            source=EcritureSource.SYSTEME,
            lignes=lignes,
        ))
        return e.id

    async def _calculer_solde_comptable_a_date(
        self, compte_comptable: str, date_arret: date
    ) -> int:
        """Calcule le solde comptable d'un compte à une date donnée."""
        from app.models.plan_comptable import PlanComptable
        stmt = (
            select(
                func.coalesce(func.sum(EcritureLigne.debit_xof), 0),
                func.coalesce(func.sum(EcritureLigne.credit_xof), 0),
            )
            .join(PlanComptable, PlanComptable.id == EcritureLigne.compte_id)
            .join(Ecriture, Ecriture.id == EcritureLigne.ecriture_id)
            .where(
                EcritureLigne.tenant_id == self.tenant_id,
                PlanComptable.compte == compte_comptable,
                Ecriture.date_ecriture <= date_arret,
                Ecriture.statut == "validee",
            )
        )
        result = (await self.db.execute(stmt)).one()
        return int(result[0] or 0) - int(result[1] or 0)

    async def _calculer_variation(self, date_ref: date) -> int:
        """Variation entre aujourd'hui et une date de référence."""
        today_total = 0
        ref_total = 0
        accounts = (
            await self.db.execute(
                select(TreasuryAccount).where(
                    TreasuryAccount.tenant_id == self.tenant_id,
                    TreasuryAccount.actif.is_(True),
                )
            )
        ).scalars().all()
        for acc in accounts:
            today_total += await self._calculer_solde_comptable_a_date(
                acc.compte_comptable, date.today()
            )
            ref_total += await self._calculer_solde_comptable_a_date(
                acc.compte_comptable, date_ref
            )
        return today_total - ref_total

    # ═════════════════════════════════════════════════════════════════════
    # GETTERS
    # ═════════════════════════════════════════════════════════════════════
    async def _get_compte(self, acc_id: UUID) -> TreasuryAccount:
        acc = await self.db.scalar(
            select(TreasuryAccount).where(
                TreasuryAccount.id == acc_id,
                TreasuryAccount.tenant_id == self.tenant_id,
            )
        )
        if acc is None:
            raise HTTPException(404, "Compte de trésorerie introuvable")
        return acc

    async def _get_statement(self, stmt_id: UUID) -> BankStatement:
        stmt = await self.db.scalar(
            select(BankStatement).where(
                BankStatement.id == stmt_id,
                BankStatement.tenant_id == self.tenant_id,
            )
        )
        if stmt is None:
            raise HTTPException(404, "Relevé bancaire introuvable")
        return stmt
