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

import sndgir_erp as erp


def _verifier(condition: bool, libelle: str) -> None:
    symbole = "✅" if condition else "❌"
    print(f"{symbole} {libelle}")
    if not condition:
        raise AssertionError(libelle)


def preparer_environnement() -> None:
    """Initialise la base et pose un tenant/utilisateur de test cohérent."""
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
        conn.execute("UPDATE audit_logs SET details='falsifié' WHERE id=1")
    valide_apres, _, message_apres = erp.verifier_audit()
    _verifier(not valide_apres, "Une falsification est bien détectée")
    _verifier("Rupture" in message_apres or "incohérent" in message_apres,
              "Le message signale la rupture")


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
    attendu_tva = round((10_000_000 + 2_000_000 + 80_000 + 50_000) * 0.18, 2)
    _verifier(calcul["tva"] == attendu_tva, f"TVA 18 % = {attendu_tva:,.0f}")

    exonere = erp.calculer_droits(10_000_000, 20.0, "E100")
    _verifier(exonere["droits_douane"] == 0, "Régime E100 : droits de douane exonérés")

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
    if dossiers.empty:
        _verifier(True, "Aucun dossier — test PDF ignoré")
        return
    dossier = dossiers.iloc[0].to_dict()
    contenu, empreinte = erp.generer_bae(dossier)
    _verifier(len(contenu) > 1000, f"BAE PDF généré ({len(contenu)} octets)")
    _verifier(contenu[:4] == b"%PDF", "Signature PDF valide")
    _verifier(len(empreinte) == 64, "Empreinte SHA-256 de 64 caractères")
    facture = erp.generer_facture_transitaire(dossier, 500_000, 300_000, 100_000)
    _verifier(facture[:4] == b"%PDF", f"Facture PDF générée ({len(facture)} octets)")


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
    tester_tenant()
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