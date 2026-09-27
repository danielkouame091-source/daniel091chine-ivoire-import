"""
rbac.py — Contrôle d'accès basé sur les rôles (RBAC) pour le SNDGIR ERP.

Usage dans app.py :

    from rbac import require_permission, has_permission, ROLES_PERMISSIONS

    with tab_compta:
        if require_permission("compta.view"):
            afficher_module_comptabilite(...)

`require_permission` retourne False (et affiche un message) au lieu de
planter toute l'appli — chaque onglet reste responsable d'arrêter son
propre rendu.
"""

import sqlite3
from datetime import datetime

import streamlit as st

# ---------------------------------------------------------------------
# Table des permissions par rôle métier.
# Convention : "<module>.<action>" — view / create / edit / validate / delete
# ---------------------------------------------------------------------
ROLES_PERMISSIONS = {
    "Administrateur Système": {"*"},  # accès total

    "Vérificateur Douanier": {
        "manifeste.view", "manifeste.create",
        "sad.view", "sad.create", "sad.validate",
        "selectivite.view", "selectivite.override",
        "ocr.view", "ocr.validate",
        "edi.view",
        "dashboard.view",
    },

    "Agent de Caisse": {
        "dashboard.view",
        "sad.view",
        "caisse.view", "caisse.encaisser", "caisse.bae",
        "compta.view",  # lecture seule, écritures générées automatiquement par la caisse
    },

    "Commissionnaire Agréé": {
        "dashboard.view",
        "manifeste.view",
        "sad.view", "sad.create",
        "transit.view", "transit.create", "transit.facturer",
        "compta.view",
        "fiscal.view",
    },

    "Banquier": {
        "dashboard.view",
        "compta.view", "compta.rapprochement",
        "fiscal.view",
    },
}

# Ajout automatique de "compta.saisie_manuelle" uniquement aux rôles
# comptables/admin pour éviter les écritures sauvages.
ROLES_PERMISSIONS["Commissionnaire Agréé"] |= {"compta.saisie_manuelle"}


def has_permission(role: str, permission: str) -> bool:
    perms = ROLES_PERMISSIONS.get(role, set())
    if "*" in perms:
        return True
    return permission in perms


def require_permission(permission: str, db_name: str | None = None) -> bool:
    """
    Vérifie la permission pour l'utilisateur en session.
    Affiche un message d'erreur et journalise le refus si non autorisé.
    Retourne True/False — à l'appelant de faire `return` / ne pas
    afficher le contenu si False.
    """
    role = st.session_state.get("user_role", "")
    username = st.session_state.get("username", "inconnu")

    if has_permission(role, permission):
        return True

    st.error(f"⛔ Accès refusé : votre rôle « {role} » n'a pas la permission `{permission}`.")

    if db_name:
        try:
            conn = sqlite3.connect(db_name)
            conn.execute(
                "INSERT INTO audit_logs (timestamp, username, action, details) VALUES (?, ?, ?, ?)",
                (
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    username,
                    "Accès refusé (RBAC)",
                    f"Permission requise : {permission}",
                ),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass  # ne jamais bloquer l'UI pour un échec de log

    return False


def liste_permissions_role(role: str) -> list[str]:
    perms = ROLES_PERMISSIONS.get(role, set())
    return ["TOUTES (admin)"] if "*" in perms else sorted(perms)
