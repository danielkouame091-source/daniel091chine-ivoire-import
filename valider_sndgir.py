"""
valider_sndgir.py — Validation fonctionnelle du cœur métier de SNDGIR & Transit ERP.

Ce script n'utilise PAS Streamlit pour l'affichage : il importe `sndgir_erp`
dans un contexte simulé (st.session_state factice) et vérifie les calculs
critiques : sécurité/chiffrement, chaîne d'audit, comptabilité en partie
double, droits de douane, sélectivité des risques, surestaries, OCR/IDP,
transit et isolation multi-tenant.

Usage :  python3 valider_sndgir.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import sndgir_erp as erp


def _verifier(condition: bool, libelle: str) -> None:
    symbole = "✅" if condition else "❌"
    print(f"{symbole} {libelle}")
    if not condition:
        raise AssertionError(libelle)


def preparer_environnement() -> None:
    """Initialise la base et pose un tenant/utilisateur de test cohérent."""
    # Base temporaire : la validation ne touche jamais à votre vraie base de données.
    dossier_temp = Path(tempfile.mkdtemp(prefix="sndgir_valid_"))
    erp.DB_PATH = dossier_temp / "validation.db"
    erp.st.session_state.clear()
    erp.init_db()
    locataires = erp.lister_tenants()
    erp.st.session_state["tenant_id"] = int(locataires.iloc[0]["id"])
    erp.st.session_state["username"] = "testeur"
    erp.st.session_state["user_role"] = "Administrateur Système"


def tester_securite() -> None:
    print("\n── Sécurité ─────────────────────────────────────────────")
    clair = "gsk_secret_api_key_123456"
    chiffre = erp.chiffrer(clair)
    _verifier(chiffre != clair, "Le chiffrement produit une charge différente du clair")
    _verifier(erp.dechiffrer(chiffre) == clair, "Le déchiffrement restitue la valeur d'origine")
    _verifier(erp.dechiffrer(chiffre[:-4] + "AAAA") == "", "Une charge altérée est rejetée (MAC)")

    empreinte, sel = erp.hash_mot_de_passe("MotDePasse!2025")
    _verifier(erp.verifier_mot_de_passe("MotDePasse!2025", empreinte, sel), "Mot de passe valide")
    _verifier(not erp.verifier_mot_de_passe("mauvais", empreinte, sel),
              "Mot de passe invalide rejeté")
    _verifier(erp.empreinte_sha256("a", 1) == erp.empreinte_sha256("a", 1),
              "SHA-256 déterministe")
    _verifier("***" in erp.rediger("api_key=sk-abcdef123456"),
              "Les secrets sont masqués dans l'audit")


def tester_audit() -> None:
    print("\n── Piste d'audit immuable ──────────────────────────────")
    erp.journaliser("test_action", "tests", "1", "événement de test")
    valide, nb_lignes, message = erp.verifier_audit()
    _verifier(valide, f"Chaîne d'audit intègre ({nb_lignes} entrées)")
    _verifier("intègre" in message, "Message d'intégrité conforme")

    with erp.connexion() as conn:
        ligne = conn.execute("SELECT details FROM audit_logs WHERE id=1").fetchone()
        details_origine = ligne["details"]
        conn.execute("UPDATE audit_logs SET details='falsifié' WHERE id=1")
    valide_apres, _, message_apres = erp.verifier_audit()
    _verifier(not valide_apres, "Une falsification est bien détectée")
    _verifier("Rupture" in message_apres or "incohérent" in message_apres,
              "Le message signale la rupture")

    # Le test ne doit pas laisser la base corrompue : on remet la ligne d'origine.
    with erp.connexion() as conn:
        conn.execute("UPDATE audit_logs SET details=? WHERE id=1", (details_origine,))
    restaure, _, _ = erp.verifier_audit()
    _verifier(restaure, "Chaîne d'audit rétablie après le test de falsification")


def tester_comptabilite() -> None:
    print("\n── Comptabilité SYSCOHADA (partie double) ──────────────")
    with erp.connexion() as conn:
        conn.execute("DELETE FROM ecritures WHERE tenant_id=?", (erp.tenant_courant(),))

    erp.ecrire_piece("TEST-001", "BAN", [
        ("521000", "Apport banque", 1_000_000, 0.0),
        ("101000", "Capital social", 0.0, 1_000_000),
    ])
    _verifier(erp.solde_compte("521000") == 1_000_000, "Solde banque = 1 000 000 (débit)")

    try:
        erp.ecrire_piece("TEST-KO", "OD", [("521000", "Déséquilibre", 500, 0.0)])
        _verifier(False, "Une écriture déséquilibrée doit être refusée")
    except erp.ErreurComptable:
        _verifier(True, "Écriture déséquilibrée refusée (ErreurComptable)")

    try:
        erp.ecrire_piece("TEST-KO2", "OD", [("999999", "Compte inconnu", 100, 0.0),
                                            ("521000", "Contrepartie", 0.0, 100)])
        _verifier(False, "Un compte hors plan comptable doit être refusé")
    except erp.ErreurComptable:
        _verifier(True, "Compte inconnu refusé")

    erp.ecritures_frais_transit("VAL-01", honoraires_ht=500_000, debours_douaniers=2_000_000,
                                fret=300_000, surestaries=100_000, client="Client Test")
    _verifier(round(abs(erp.solde_compte("445200"))) == 90_000,
              "TVA collectée = 18 % des honoraires (90 000)")
    _verifier(round(abs(erp.solde_compte("411000"))) == 2_990_000,
              "Créance client = total TTC (2 990 000)")

    balance = erp.balance_generale()
    ecart = round(float(balance["debit"].sum() - balance["credit"].sum()), 2)
    _verifier(ecart == 0, "Balance générale équilibrée")

    etats = erp.etats_financiers()
    _verifier(etats["resultat"] > 0, f"Résultat de l'exercice positif ({etats['resultat']:,.0f})")


def tester_douanes() -> None:
    print("\n── Droits de douane & sélectivité ──────────────────────")
    calcul = erp.calculer_droits(10_000_000, 20.0, "C100")
    _verifier(calcul["droits_douane"] == 2_000_000, "DD = 20 % de la CAF (2 000 000)")
    _verifier(calcul["pc_uemoa"] == 80_000, "Prélèvement UEMOA = 0,8 % (80 000)")
    _verifier(calcul["pcc_cedeao"] == 50_000, "Prélèvement CEDEAO = 0,5 % (50 000)")
    _verifier(calcul["redevance_statistique"] == 100_000, "Redevance statistique = 1 % (100 000)")
    attendu_tva = round((10_000_000 + 2_000_000 + 100_000 + 80_000 + 50_000) * 0.18, 2)
    _verifier(calcul["tva"] == attendu_tva, f"TVA 18 % sur CAF + droits et taxes = {attendu_tva:,.0f}")
    _verifier(calcul["total_droits_taxes"] == 2_000_000 + 100_000 + 80_000 + 50_000 + attendu_tva,
              "Total droits et taxes = somme des rubriques")

    for regime in ("E100", "AT", "TR"):
        suspendu = erp.calculer_droits(10_000_000, 20.0, regime)
        _verifier(suspendu["total_droits_taxes"] == 0 and suspendu["tva"] == 0
                  and suspendu["suspendu"],
                  f"Régime {regime} : aucun droit ni TVA à payer")
    _verifier(not calcul["suspendu"], "Régime C100 : droits exigibles")

    vert = erp.scorer_risque(1_000_000, 5.0, 5.0, fournisseur_nouveau=False)
    rouge = erp.scorer_risque(80_000_000, 20.0, 5.0, ecart_prix_pct=35.0,
                              marchandise_sensible=True)
    _verifier(vert["canal"] == "VERT", f"Dossier conforme → canal VERT (score {vert['score']})")
    _verifier(rouge["canal"] == "ROUGE",
              f"Dossier à risque → canal ROUGE (score {rouge['score']})")


def tester_surestaries() -> None:
    print("\n── Surestaries portuaires ──────────────────────────────")
    resultat = erp.calculer_surestaries("2025-03-01", "2025-03-11", 250.0, 600.0)
    _verifier(resultat["jours_retard"] == 10, "10 jours de retard détectés")
    _verifier(resultat["montant_usd"] == 2500.0, "Montant USD = 2 500")
    _verifier(resultat["montant_xof"] == 1_500_000, "Conversion FCFA au taux 600 → 1 500 000")
    sans_retard = erp.calculer_surestaries("2025-03-01", "2025-03-01", 250.0, 600.0)
    _verifier(sans_retard["jours_retard"] == 0, "Aucun retard → surestaries nulles")


def tester_ocr() -> None:
    print("\n── OCR / IDP & cross-checking ──────────────────────────")
    texte = ("Fournisseur: Shenzhen Electronics Ltd\nFacture N°: INV-2025-8891\n"
             "Date: 12/03/2025\nDésignation: Ordinateurs portables\nTotal: 12 500 000")
    extraction = erp.extraire_facture_heuristique(texte)
    _verifier(extraction["fournisseur"].startswith("Shenzhen"), "Fournisseur extrait")
    _verifier(extraction["numero_facture"] == "INV-2025-8891", "N° de facture extrait")
    _verifier(extraction["montant_extrait"] == 12_500_000, "Montant extrait = 12 500 000")

    controle = erp.cross_check_facture(9_000_000, 12_500_000, 14_000_000, "Shenzhen")
    _verifier(controle["discordance"], "Sous-évaluation détectée")
    _verifier(any("Sous-évaluation" in anomalie for anomalie in controle["anomalies"]),
              "Anomalie de sous-évaluation signalée")
    sain = erp.cross_check_facture(12_400_000, 12_500_000, 12_500_000)
    _verifier(not sain["discordance"], "Facture conforme → aucune discordance")


def tester_transit() -> None:
    print("\n── Dossiers, manifestes et B/L ─────────────────────────")
    reference = f"IMP-VAL-{erp.datetime.now():%H%M%S}"
    dossier = erp.creer_dossier(reference, "Client Validation", "BL-VAL-001",
                                "Ordinateurs portables & tablettes", "C100",
                                5_000_000, 500_000, 100_000, 5.0)
    _verifier(dossier["total_facture"] > 5_600_000, "Total facture cohérent (CAF + droits)")
    _verifier(dossier["risque"]["canal"] in erp.CANAUX, "Canal de risque attribué")

    manifeste_id = erp.creer_manifeste("MAN-VAL-1", "Navire Test", "CMA CGM", "2025-03-05")
    bl_id = erp.enregistrer_connaissement(manifeste_id, "BL-VAL-001", "Client Validation",
                                          120, 4500.0, 80_000.0, "2025-03-05")
    _verifier(not erp.lister_connaissements().empty, "Connaissement enregistré")
    erp.apurer_connaissement(bl_id)
    apure = erp.lister_connaissements()
    _verifier(int(apure.loc[apure["id"] == bl_id, "apure"].iloc[0]) == 1, "B/L apuré")

    erp.apurer_manifeste(manifeste_id)
    manifestes = erp.lister_manifestes()
    _verifier(manifestes.loc[manifestes["id"] == manifeste_id, "statut"].iloc[0] == "Apuré",
              "Manifeste apuré automatiquement")


def tester_tenant() -> None:
    print("\n── Multi-tenant & RBAC ─────────────────────────────────")
    slug = f"test-{erp.datetime.now():%H%M%S}"
    nouveau = erp.creer_tenant(slug, "Cabinet Test SARL", "Côte d'Ivoire", "Réel simplifié")
    _verifier(nouveau > 0, f"Tenant créé (id={nouveau})")
    erp.creer_utilisateur(nouveau, "chef", "Chef!2025", "Expert-Comptable signataire",
                          "chef@test.ci")
    fiche = erp.authentifier(nouveau, "chef", "Chef!2025")
    _verifier(fiche is not None, "Authentification réussie")
    _verifier(erp.authentifier(nouveau, "chef", "mauvais") is None, "Mauvais mot de passe refusé")
    _verifier(erp.a_permission("Auditeur externe", "compta.view"),
              "RBAC : auditeur peut consulter")
    _verifier(not erp.a_permission("Auditeur externe", "compta.saisie"),
              "RBAC : auditeur ne peut pas saisir")
    _verifier(erp.a_permission("Administrateur Système", "n'importe.quoi"),
              "RBAC : admin = joker")


def tester_rbac_isolation() -> None:
    print("\n── Isolation des données par tenant ────────────────────")
    locataires = erp.lister_tenants()
    premier = int(locataires.iloc[0]["id"])
    erp.st.session_state["tenant_id"] = premier
    dossiers_premier = len(erp.lister_dossiers())
    erp.st.session_state["tenant_id"] = int(locataires.iloc[-1]["id"])
    dossiers_dernier = len(erp.lister_dossiers())
    erp.st.session_state["tenant_id"] = premier
    _verifier(dossiers_dernier != dossiers_premier,
              f"Isolation active (tenant A={dossiers_premier}, tenant B={dossiers_dernier})")


def tester_generation_pdf() -> None:
    print("\n── Documents PDF (BAE scellé SHA-256) ──────────────────")
    if not erp.REPORTLAB_OK:
        _verifier(True, "ReportLab absent — test PDF ignoré")
        return
    dossiers = erp.lister_dossiers()
    dossiers = dossiers[dossiers["statut"] == erp.STATUT_BAE]
    if dossiers.empty:
        _verifier(True, "Aucun dossier au statut BAE — test PDF ignoré")
        return
    dossier = dossiers.iloc[0].to_dict()
    contenu, empreinte = erp.generer_bae(dossier)
    _verifier(len(contenu) > 1000, f"BAE PDF généré ({len(contenu)} octets)")
    _verifier(contenu[:4] == b"%PDF", "Signature PDF valide")
    _verifier(len(empreinte) == 64, "Empreinte SHA-256 de 64 caractères")
    facture = erp.generer_facture_transitaire(dossier, 500_000, 300_000, 100_000)
    _verifier(facture[:4] == b"%PDF", f"Facture PDF générée ({len(facture)} octets)")


def _refus(fonction, *args, **kwargs) -> str | None:
    """Message du ValueError levé par fonction(...), ou None si aucun refus."""
    try:
        fonction(*args, **kwargs)
    except ValueError as erreur:
        return str(erreur)
    return None


def tester_conformite_dossier() -> None:
    print("\n── Conformité documentaire & cycle de vie du dossier ───")
    suffixe = f"{erp.datetime.now():%H%M%S}"
    article = "Ordinateurs portables & tablettes"  # DD de référence : 5 %
    _verifier("CDC" in erp.documents_requis("C100", 5_000_000),
              "CdC exigé à partir de 1 000 000 FCFA de FOB")
    _verifier("CDC" not in erp.documents_requis("C100", 500_000), "CdC non exigé sous le seuil")

    resultat = erp.creer_dossier(f"IMP-CONF-{suffixe}", "Client Conformité", "BL-CONF-1",
                                 article, "C100", 5_000_000, 500_000, 100_000, 5.0)
    did = resultat["dossier_id"]
    _verifier(not resultat["droits"]["suspendu"], "Dossier C100 créé avec droits exigibles")

    _verifier("Étape sautée" in (_refus(erp.maj_statut_dossier, did, erp.STATUT_BAE) or ""),
              "On ne peut pas sauter d'étape (En cours → BAE refusé)")
    erp.maj_statut_dossier(did, erp.STATUTS_DOSSIER[1])
    erp.maj_statut_dossier(did, erp.STATUTS_DOSSIER[2])
    _verifier("pièces manquantes" in (_refus(erp.maj_statut_dossier, did, erp.STATUT_BAE) or ""),
              "BAE refusé tant que les pièces obligatoires manquent")
    ligne = erp.lister_dossiers()
    dossier = ligne.loc[ligne["id"] == did].iloc[0].to_dict()
    if erp.REPORTLAB_OK:
        _verifier("BAE refusé" in (_refus(erp.generer_bae, dossier) or ""),
                  "PDF du BAE refusé tant que le dossier n'est pas conforme")

    _verifier("exempté" in (_refus(erp.enregistrer_document_dossier, did, "FDI", "x", "Exempté") or ""),
              "Seul le CdC peut être déclaré exempté")
    _verifier(_refus(erp.enregistrer_document_dossier, did, "FDI", "  ") is not None,
              "Pièce sans référence refusée")
    _verifier(_refus(erp.enregistrer_document_dossier, did, "INCONNU", "x") is not None,
              "Pièce inconnue refusée")
    for code in erp.documents_requis("C100", 5_000_000):
        if code == "CDC":
            erp.enregistrer_document_dossier(did, code, "Produit exempté (motif de test)", "Exempté")
        else:
            erp.enregistrer_document_dossier(did, code, f"{code}-{suffixe}")
    controle = erp.controle_conformite(did)
    _verifier(controle["complet"] and not controle["manquants"], "Dossier conforme : aucune pièce manquante")

    if erp.REPORTLAB_OK:
        contenu, empreinte_1 = erp.generer_bae(dossier)
        _verifier(contenu[:4] == b"%PDF", "BAE émis une fois le dossier conforme")
        erp.enregistrer_document_dossier(did, "FDI", f"FDI-MODIFIEE-{suffixe}")
        _, empreinte_2 = erp.generer_bae(dossier)
        _verifier(empreinte_1 != empreinte_2, "Le sceau du BAE change si une pièce change")
    erp.maj_statut_dossier(did, erp.STATUT_BAE)
    erp.maj_statut_dossier(did, erp.STATUTS_DOSSIER[4])
    erp.maj_statut_dossier(did, erp.STATUT_BAE)
    statut = erp.lister_dossiers().loc[lambda d: d["id"] == did, "statut"].iloc[0]
    _verifier(statut == erp.STATUT_BAE, "Retour d'une étape autorisé pour corriger une erreur")

    _verifier("existe déjà" in (_refus(erp.creer_dossier, f"IMP-CONF-{suffixe}", "Autre", "",
                                       article, "C100", 1, 1, 1, 5.0) or ""),
              "Référence de dossier en double refusée")
    _verifier(_refus(erp.creer_dossier, f"IMP-NEG-{suffixe}", "Client", "", article, "C100",
                     -1, 0, 0, 5.0) is not None, "Montant négatif refusé")
    _verifier(_refus(erp.creer_dossier, f"IMP-REG-{suffixe}", "Client", "", article, "ZZZ",
                     1, 0, 0, 5.0) is not None, "Régime douanier inconnu refusé")

    ecart = erp.creer_dossier(f"IMP-DD-{suffixe}", "Client Écart", "", article, "C100",
                              5_000_000, 0, 0, 20.0)["risque"]
    _verifier(any("Écart de taux DD" in motif for motif in ecart["motifs"]),
              "Le taux de DD déclaré est comparé au tarif de référence (écart signalé)")

    autre = erp.creer_tenant(f"conf-{suffixe}", "Cabinet Conformité", "Côte d'Ivoire",
                             "Réel simplifié")
    precedent = erp.st.session_state.get("tenant_id")
    erp.st.session_state["tenant_id"] = autre
    _verifier(erp.lister_documents_dossier(did).empty,
              "Isolation : les pièces d'un tenant sont invisibles pour un autre")
    _verifier(_refus(erp.controle_conformite, did) is not None,
              "Isolation : le contrôle d'un dossier d'un autre tenant est refusé")
    erp.st.session_state["tenant_id"] = precedent


def tester_comptes() -> None:
    print("\n── Comptes : mots de passe & blocage des tentatives ────")
    _verifier("admin" in erp.comptes_mot_de_passe_demo(),
              "Les mots de passe de démonstration encore actifs sont détectés")
    _verifier(_refus(erp.valider_mot_de_passe, "court1") is not None, "Mot de passe trop court refusé")
    _verifier(_refus(erp.valider_mot_de_passe, "uniquementlettres") is not None,
              "Mot de passe sans chiffre refusé")
    _verifier(_refus(erp.valider_mot_de_passe, "admin123") is not None,
              "Mot de passe de démonstration refusé")
    _verifier(_refus(erp.valider_mot_de_passe, "Solide2025xy") is None, "Mot de passe solide accepté")

    suffixe = f"{erp.datetime.now():%H%M%S}"
    tenant = erp.creer_tenant(f"cpt-{suffixe}", "Cabinet Comptes", "Côte d'Ivoire", "Réel simplifié")
    erp.creer_utilisateur(tenant, "agent", "Ancien2025xyz", "Collaborateur", "a@test.ci")
    erp.definir_mot_de_passe(tenant, "agent", "Nouveau2025xyz")
    _verifier(erp.authentifier(tenant, "agent", "Nouveau2025xyz") is not None,
              "Mot de passe réinitialisé par l'administrateur : accepté")
    _verifier(erp.authentifier(tenant, "agent", "Ancien2025xyz") is None,
              "Ancien mot de passe refusé après réinitialisation")

    session = erp.st.session_state
    precedent = (session.get("tenant_id"), session.get("username"))
    session["tenant_id"], session["username"] = tenant, "agent"
    _verifier(_refus(erp.changer_mon_mot_de_passe, "faux", "Autre2025xyzz") is not None,
              "Changement refusé si l'ancien mot de passe est faux")
    erp.changer_mon_mot_de_passe("Nouveau2025xyz", "Autre2025xyzz")
    _verifier(erp.authentifier(tenant, "agent", "Autre2025xyzz") is not None,
              "Changement de mot de passe par l'utilisateur effectif")
    session["tenant_id"], session["username"] = precedent

    erp.creer_utilisateur(tenant, "cible", "Cible2025xyzz", "Collaborateur", "c@test.ci")
    for _ in range(erp.CONNEXIONS_ECHECS_MAX):
        erp.authentifier(tenant, "cible", "mauvais")
    _verifier(erp.connexion_bloquee(tenant, "cible"), "Compte bloqué après trop d'échecs")
    _verifier(erp.authentifier(tenant, "cible", "Cible2025xyzz") is None,
              "Compte bloqué : même le bon mot de passe est refusé")
    _verifier(not erp.connexion_bloquee(tenant, "agent"), "Les autres comptes ne sont pas bloqués")
    valide, nb_lignes, _ = erp.verifier_audit()
    _verifier(valide, f"Chaîne d'audit toujours intègre ({nb_lignes} entrées)")


def tester_tarif_et_taxes() -> None:
    print("\n— Tarif douanier & taxes spécifiques —")
    csv = ("code_sh;designation;dd;unite\n"
           "2203.00.00.00;TEST Bière;20;litre\n"
           "8471.30.00.00;TEST Ordinateurs;5,0;unité\n"
           "abc;ligne invalide;5;kg\n"
           "9999.99.00.00;TEST DD hors tranche;12;kg\n")
    bilan = erp.importer_tarif_csv(csv.encode("utf-8"))
    _verifier(bilan["importees"] == 3 and bilan["ignorees"] == 1,
              f"Import CSV : 3 lignes importées, 1 ignorée ({bilan['importees']}/{bilan['ignorees']})")
    _verifier(bilan["hors_tranches"] == 1, "DD hors tranches signalé")
    tarif = erp.chercher_tarif("2203.00.00.00")
    _verifier(tarif is not None and float(tarif["dd"]) == 20.0, "Recherche tarif exacte (DD 20 %)")
    _verifier(erp.chercher_tarif("2203.00") is not None, "Recherche par code partiel")
    erp.importer_tarif_csv("code_sh;designation;dd;unite\n2203.00.00.00;TEST Biere;10;litre\n")
    _verifier(float(erp.chercher_tarif("2203.00.00.00")["dd"]) == 10.0, "Ré-import = mise à jour")
    try:
        erp.normaliser_sh("12")
        _verifier(False, "Code SH trop court refusé")
    except ValueError:
        _verifier(True, "Code SH trop court refusé")

    erp.ajouter_taxe_specifique("2203", "TEST Droit d'accise", "MONTANT_PAR_UNITE", 100.0, "litre")
    erp.ajouter_taxe_specifique("22", "TEST Taxe boissons", "POURCENT_CAF", 2.0)
    taxes = erp.calculer_taxes_specifiques("2203.00.00.00", 1_000_000, 500)
    _verifier(taxes["total"] == 50_000 + 20_000, f"Taxes : 500 × 100 + 2 % = {taxes['total']:,.0f}")
    try:
        erp.calculer_taxes_specifiques("2203.00.00.00", 1_000_000, 0)
        _verifier(False, "Taxe par unité sans quantité refusée")
    except ValueError:
        _verifier(True, "Taxe par unité sans quantité refusée")
    _verifier(erp.calculer_taxes_specifiques("8471.30.00.00", 1_000_000)["total"] == 0,
              "Aucune taxe hors préfixe")

    sans = erp.calculer_droits(1_000_000, 10.0)
    avec = erp.calculer_droits(1_000_000, 10.0, autres_taxes=70_000)
    _verifier(avec["tva"] > sans["tva"] and avec["total_droits_taxes"] > sans["total_droits_taxes"] + 70_000,
              "Taxes spécifiques incluses dans la base de TVA")
    susp = erp.calculer_droits(1_000_000, 10.0, regime="TR", autres_taxes=70_000)
    _verifier(susp["total_droits_taxes"] == 0, "Régime suspendu : aucune taxe spécifique à payer")

    for _, ligne in erp.lister_taxes_specifiques().iterrows():
        if str(ligne["libelle"]).startswith("TEST"):
            erp.supprimer_taxe_specifique(int(ligne["id"]))
    _verifier(erp.lister_taxes_specifiques().empty or
              not erp.lister_taxes_specifiques()["libelle"].astype(str).str.startswith("TEST").any(),
              "Suppression des taxes de test")


def tester_parcours_dus_fne() -> None:
    print("\n— Parcours officiel, droit de sortie, FNE —")
    erp.ajouter_droit_sortie("1801", "TEST DUS cacao", "POURCENT_PRIX_REF", 10.0, "kg", 1500.0, "TEST")
    erp.ajouter_droit_sortie("0801", "TEST DUS noix", "MONTANT_PAR_UNITE", 10.0, "kg")
    dus = erp.calculer_dus("1801.00.00.00", 1000)
    _verifier(dus["total"] == 150_000, f"DUS : 1000 kg × 1500 × 10 % = {dus['total']:,.0f}")
    _verifier(erp.calculer_dus("0801.31.00.00", 200)["total"] == 2_000, "DUS par unité : 200 kg × 10")
    _verifier(erp.calculer_dus("8471.30.00.00", 5)["total"] == 0, "Aucun DUS hors préfixe")
    try:
        erp.calculer_dus("1801.00.00.00", 0)
        _verifier(False, "DUS sans quantité refusé")
    except ValueError:
        _verifier(True, "DUS sans quantité refusé")
    try:
        erp.ajouter_droit_sortie("1801", "x", "POURCENT_PRIX_REF", 10.0, "kg", 0.0)
        _verifier(False, "Prix de référence obligatoire refusé")
    except ValueError:
        _verifier(True, "Prix de référence obligatoire refusé")

    export = erp.creer_dossier("TEST-EXP-001", "Client Export", "", "Cacao", "E100",
                               1_500_000, 0, 0, 0.0, code_sh="1801.00.00.00", quantite=1000)
    _verifier(export["droits"]["total_droits_taxes"] == 150_000 and export["total_facture"] ==
              1_500_000 + 150_000, "Dossier export : DUS ajouté au total, aucun DD ni TVA")

    imp = erp.creer_dossier("TEST-PAR-001", "Client Import", "BL1", "Pièces", "C100",
                            2_000_000, 100_000, 20_000, 10.0)
    did = imp["dossier_id"]
    etapes = erp.etapes_parcours(did)
    _verifier(not any(e["fait"] for e in etapes), "Parcours : aucune étape faite au départ")
    erp.enregistrer_parcours(did, "CC123", "CI456", True, "DEC789", "LIQ1", "QUIT1", "COMPTANT")
    fait = {e["code"]: e["fait"] for e in erp.etapes_parcours(did)}
    _verifier(fait["STATUT"] and fait["DECLARATION"] and fait["PAIEMENT"] and not fait["BAE"],
              "Parcours : statut, déclaration et paiement validés, BAE pas encore")
    erp.enregistrer_document_dossier(did, "RFCV", "RFCV-001")
    _verifier({e["code"]: e["fait"] for e in erp.etapes_parcours(did)}["RFCV"], "Parcours : RFCV pris en compte")
    try:
        erp.enregistrer_parcours(did, "CC123", numero_quittance="Q2")
        _verifier(False, "Quittance sans avis de liquidation refusée")
    except ValueError:
        _verifier(True, "Quittance sans avis de liquidation refusée")
    _verifier("RFCV" in erp.documents_requis("C100", 2_000_000), "Le RFCV fait partie des pièces d'un import")

    try:
        erp.enregistrer_fne(did, "", "A_CERTIFIER")
        _verifier(False, "FNE sans NCC client refusée")
    except ValueError:
        _verifier(True, "FNE sans NCC client refusée")
    try:
        erp.enregistrer_fne(did, "NCC1", "CERTIFIEE")
        _verifier(False, "FNE certifiée sans numéro refusée")
    except ValueError:
        _verifier(True, "FNE certifiée sans numéro refusée")
    erp.enregistrer_fne(did, "NCC1", "CERTIFIEE", "FNE-0001", "VERIF")
    _verifier(erp.lire_fne(did)["numero_fne"] == "FNE-0001", "Suivi FNE enregistré")

    ancien = erp.st.session_state["tenant_id"]
    autre = [int(t) for t in erp.lister_tenants()["id"] if int(t) != ancien]
    if autre:
        erp.st.session_state["tenant_id"] = autre[0]
        try:
            erp.etapes_parcours(did)
            _verifier(False, "Isolation : parcours d'un autre tenant refusé")
        except ValueError:
            _verifier(True, "Isolation : parcours d'un autre tenant refusé")
        erp.st.session_state["tenant_id"] = ancien
    for _, ligne in erp.lister_droits_sortie().iterrows():
        if str(ligne["libelle"]).startswith("TEST"):
            erp.supprimer_droit_sortie(int(ligne["id"]))


def tester_assistant_expert() -> None:
    print("\n— Assistant IA expert : base de connaissances et garde-fous —")
    r = erp.rechercher_connaissances("Quel est le droit unique de sortie pour le cacao ?")
    _verifier(bool(r) and "Droit Unique de Sortie" in r[0]["titre"], "Recherche : le DUS arrive en premier")
    r = erp.rechercher_connaissances("quand la facture normalisée électronique est-elle obligatoire")
    _verifier(bool(r) and "FNE" in r[0]["titre"], "Recherche : la FNE est trouvée (accents et pluriels ignorés)")
    r = erp.rechercher_connaissances("documents pour importer en C100")
    _verifier(any("Pièces" in x["titre"] or "Procédure" in x["titre"] for x in r), "Recherche : pièces d'un import")
    _verifier(erp.rechercher_connaissances("recette de cuisine du poulet braisé") == [],
              "Recherche : question hors sujet sans extrait")
    passages = erp.decouper_passages("Phrase un. " * 400, taille=300)
    _verifier(len(passages) > 3 and all(len(p) <= 320 for p in passages), "Découpage en passages courts")

    n = erp.ajouter_connaissance("TEST Arrêté fictif sur les conteneurs", "TEST", "Douane",
                                 "Le zorglub de conteneur est limité à quarante jours de franchise.")
    _verifier(n >= 1, "Document ajouté à la base du cabinet")
    r = erp.rechercher_connaissances("zorglub franchise conteneur")
    _verifier(bool(r) and r[0]["origine"] == "Base du cabinet", "Le texte ajouté est retrouvé")
    ancien = erp.st.session_state["tenant_id"]
    autres = [int(t) for t in erp.lister_tenants()["id"] if int(t) != ancien]
    if autres:
        erp.st.session_state["tenant_id"] = autres[0]
        r2 = erp.rechercher_connaissances("zorglub franchise conteneur")
        _verifier(not any(x["origine"] == "Base du cabinet" for x in r2), "Isolation : base d'un autre cabinet invisible")
        erp.st.session_state["tenant_id"] = ancien
    for _, l in erp.lister_connaissances().iterrows():
        if str(l["titre"]).startswith("TEST"):
            erp.supprimer_connaissance(int(l["id"]))
    _verifier(not erp.rechercher_connaissances("zorglub franchise conteneur")
              or erp.rechercher_connaissances("zorglub franchise conteneur")[0]["origine"] != "Base du cabinet",
              "Suppression du document de test")

    messages, sources = erp.construire_messages_ia("Droit unique de sortie du cacao 1801.00.00.00")
    systeme = messages[0]["content"]
    _verifier("N'invente JAMAIS" in systeme and "[S1]" in systeme, "Prompt : règle anti-invention et sources numérotées")
    _verifier("hors de ces domaines" in systeme, "Prompt : refus hors domaine")
    messages_vides, _ = erp.construire_messages_ia("zxqv wxyz")
    _verifier("AUCUNE SOURCE PERTINENTE" in messages_vides[0]["content"], "Prompt : absence de source signalée")

    dossiers = erp.lister_dossiers()
    contexte = erp.contexte_dossier_ia(int(dossiers.iloc[0]["id"]))
    _verifier(str(dossiers.iloc[0]["reference"]) in contexte and "Pièces manquantes" in contexte, "Contexte du dossier injecté")
    msgs, _ = erp.construire_messages_ia("Où en est ce dossier ?", int(dossiers.iloc[0]["id"]))
    _verifier("DONNÉES DU DOSSIER" in msgs[0]["content"], "Prompt : données du dossier jointes")

    erp.st.session_state["groq_api_key"] = ""
    res = erp.poser_question_expert("Que faire pour le dédouanement à l'importation ?")
    _verifier(res["mode"] in ("extraits", "ia") and res["reponse"], "Réponse même sans clé IA (mode extraits)")
    try:
        erp.poser_question_expert("   ")
        _verifier(False, "Question vide refusée")
    except ValueError:
        _verifier(True, "Question vide refusée")


def main() -> int:
    print("═" * 62)
    print(f" VALIDATION FONCTIONNELLE — {erp.APP_NAME} v{erp.APP_VERSION}")
    print("═" * 62)
    preparer_environnement()
    tester_securite()
    tester_audit()
    tester_comptabilite()
    tester_douanes()
    tester_surestaries()
    tester_ocr()
    tester_transit()
    tester_conformite_dossier()
    tester_tarif_et_taxes()
    tester_parcours_dus_fne()
    tester_assistant_expert()
    tester_tenant()
    tester_comptes()
    tester_rbac_isolation()
    tester_generation_pdf()
    print("\n" + "═" * 62)
    print(" ✅ TOUTES LES VALIDATIONS SONT PASSÉES")
    print("═" * 62)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as erreur:
        print(f"\n❌ ÉCHEC DE VALIDATION : {erreur}")
        sys.exit(1)