-- =====================================================================
-- SCHEMA SQL - KELANEWIN TRANSIT SYDAM PRO ULTRA
-- Moteur : SQLite 3 (Compatible PostgreSQL / MySQL Enterprise)
-- =====================================================================

-- Table de référence des articles et du Tarif Extérieur Commun (TEC UEMOA)
CREATE TABLE IF NOT EXISTS articles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nom         TEXT UNIQUE NOT NULL,
    sh          TEXT NOT NULL,
    dd          REAL NOT NULL,
    categorie   TEXT NOT NULL
);

-- Table principale des dossiers d'importation (Chine → Côte d'Ivoire)
CREATE TABLE IF NOT EXISTS dossiers (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    date                    TEXT NOT NULL,
    client                  TEXT NOT NULL,
    article                 TEXT NOT NULL,
    regime                  TEXT NOT NULL DEFAULT 'C100 - Mise à la consommation',
    fob_xof                 REAL NOT NULL DEFAULT 0,
    total_facture           REAL NOT NULL DEFAULT 0,
    solde_du                REAL NOT NULL DEFAULT 0,
    statut                  TEXT NOT NULL DEFAULT 'En cours',
    bl_number               TEXT,
    container_number        TEXT,
    date_arrivee            TEXT,
    jours_franchise         INTEGER DEFAULT 14,
    frais_surestarie_jour   REAL    DEFAULT 25000,
    document_path           TEXT,
    email                   TEXT,
    telephone               TEXT,
    devise                  TEXT    DEFAULT 'CNY',
    observation             TEXT
);

-- Table de gestion des utilisateurs et des rôles (RBAC)
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL,
    statut          TEXT NOT NULL DEFAULT 'Actif'
);

-- Table des journaux d'audit et de sécurité (Audit Trail & Traçabilité)
CREATE TABLE IF NOT EXISTS audit_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    utilisateur TEXT NOT NULL,
    action      TEXT NOT NULL,
    details     TEXT
);

-- Index pour optimiser les recherches dans le CRM et le suivi des dossiers
CREATE INDEX IF NOT EXISTS idx_dossiers_client ON dossiers(client);
CREATE INDEX IF NOT EXISTS idx_dossiers_statut ON dossiers(statut);
CREATE INDEX IF NOT EXISTS idx_articles_sh ON articles(sh);
