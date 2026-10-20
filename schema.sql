-- schema.sql — Kelanewin Transit SYDAM Pro Ultra (Enterprise Ultimate Edition)
CREATE TABLE IF NOT EXISTS articles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nom         TEXT UNIQUE NOT NULL,
    sh          TEXT NOT NULL,
    dd          REAL NOT NULL,
    categorie   TEXT NOT NULL
);

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

CREATE TABLE IF NOT EXISTS fournisseurs_chine (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nom_usine   TEXT NOT NULL,
    ville       TEXT NOT NULL,
    contact     TEXT,
    produits    TEXT
);

CREATE TABLE IF NOT EXISTS paiements_fournisseurs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            TEXT NOT NULL,
    fournisseur     TEXT NOT NULL,
    montant_devise  REAL NOT NULL,
    devise          TEXT NOT NULL,
    taux_applique   REAL NOT NULL,
    montant_xof     REAL NOT NULL,
    statut_paiement TEXT NOT NULL DEFAULT 'Payé'
);

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL,
    statut          TEXT NOT NULL DEFAULT 'Actif'
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    utilisateur TEXT NOT NULL,
    action      TEXT NOT NULL,
    details     TEXT
);

CREATE INDEX IF NOT EXISTS idx_dossiers_client ON dossiers(client);
CREATE INDEX IF NOT EXISTS idx_dossiers_statut ON dossiers(statut);
