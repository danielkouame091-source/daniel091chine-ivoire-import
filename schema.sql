-- schema.sql — Kelanewin Transit SYDAM Pro Ultra
-- Base de données SQLite : transit_enterprise.db
-- Ce fichier est la référence DDL. Le schéma est aussi créé automatiquement
-- par init_db() dans app.py au premier démarrage.

PRAGMA foreign_keys = ON;

-- ─── Articles & Codes SH ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS articles (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    nom       TEXT UNIQUE NOT NULL,
    sh        TEXT        NOT NULL,
    dd        REAL        NOT NULL,   -- Droit de Douane en %
    categorie TEXT        NOT NULL
);

-- ─── Dossiers CRM ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dossiers (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    date                  TEXT    NOT NULL,
    client                TEXT    NOT NULL,
    article               TEXT    NOT NULL,
    regime                TEXT    NOT NULL DEFAULT 'C100 - Mise à la consommation',
    fob_xof               REAL    NOT NULL DEFAULT 0,
    total_facture         REAL    NOT NULL DEFAULT 0,
    solde_du              REAL    NOT NULL DEFAULT 0,
    statut                TEXT    NOT NULL DEFAULT 'En cours',
    bl_number             TEXT,
    container_number      TEXT,
    date_arrivee          TEXT,                         -- format YYYY-MM-DD
    jours_franchise       INTEGER DEFAULT 14,
    frais_surestarie_jour REAL    DEFAULT 25000,
    document_path         TEXT,
    email                 TEXT,
    telephone             TEXT,
    devise                TEXT    DEFAULT 'CNY',
    observation           TEXT
);

-- ─── Utilisateurs & RBAC ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT        NOT NULL,   -- SHA-256 (remplacer par argon2 en prod)
    role          TEXT        NOT NULL,   -- Administrateur | Commercial / Déclarant | Comptable / Trésorerie
    statut        TEXT        NOT NULL DEFAULT 'Actif'
);

-- ─── Audit Logs ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,   -- format YYYY-MM-DD HH:MM:SS
    utilisateur TEXT NOT NULL,
    action      TEXT NOT NULL,
    details     TEXT
);

-- ─── Index de performance ────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_dossiers_client   ON dossiers(client);
CREATE INDEX IF NOT EXISTS idx_dossiers_statut   ON dossiers(statut);
CREATE INDEX IF NOT EXISTS idx_dossiers_date_arr ON dossiers(date_arrivee);
CREATE INDEX IF NOT EXISTS idx_audit_user        ON audit_logs(utilisateur);
CREATE INDEX IF NOT EXISTS idx_audit_action      ON audit_logs(action);
