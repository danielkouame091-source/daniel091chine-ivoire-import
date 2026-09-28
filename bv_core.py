"""Socle commun BaobabVault : accès SQLite, monnaie FCFA, tables SaaS.

Toutes les nouvelles tables sont préfixées `saas_` pour ne JAMAIS entrer en
collision avec vos tables existantes.
"""
import os
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

DB_PATH = os.environ.get("BAOBAB_DB", "baobabvault.db")
CURRENCY = {"code": "XOF", "symbol": "FCFA", "decimals": 0}
INACTIVITY_MIN = 15  # aligné sur la déconnexion automatique de l'app
TS_FMT = "%Y-%m-%d %H:%M:%S"


def set_db_path(path: str):
    global DB_PATH
    DB_PATH = path


def connect(readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        con = sqlite3.connect(f"file:{os.path.abspath(DB_PATH)}?mode=ro",
                              uri=True)
    else:
        con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.strftime(TS_FMT)


def parse_ts(s: str) -> datetime:
    return datetime.strptime(s, TS_FMT).replace(tzinfo=timezone.utc)


def fmt_money(value, currency: dict = CURRENCY) -> str:
    """1234567.5 -> '1 234 568 FCFA' (arrondi commercial, séparateur fin)."""
    try:
        d = Decimal(str(value)).quantize(
            Decimal(1).scaleb(-currency["decimals"]), rounding=ROUND_HALF_UP)
        s = f"{d:,.{currency['decimals']}f}"
    except Exception:
        return "—"
    s = s.replace(",", "\u202f").replace(".", ",")
    return f"{s}\u00a0{currency['symbol']}"


SCHEMA = """
CREATE TABLE IF NOT EXISTS saas_licences(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    max_seats INTEGER NOT NULL DEFAULT 2,
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
);
CREATE TABLE IF NOT EXISTS saas_sessions(
    licence_id INTEGER NOT NULL,
    token TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    PRIMARY KEY (licence_id, token)
);
CREATE TABLE IF NOT EXISTS saas_company_profile(
    id INTEGER PRIMARY KEY CHECK (id = 1),
    raison_sociale TEXT, activite TEXT, forme_juridique TEXT,
    adresse TEXT, ville TEXT, region TEXT, pays TEXT,
    rccm TEXT, nif TEXT, devise TEXT, debut_exercice TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS saas_audit_log(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    user TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS saas_audit_no_update
BEFORE UPDATE ON saas_audit_log
BEGIN SELECT RAISE(ABORT, 'journal d''audit immuable'); END;
CREATE TRIGGER IF NOT EXISTS saas_audit_no_delete
BEFORE DELETE ON saas_audit_log
BEGIN SELECT RAISE(ABORT, 'journal d''audit immuable'); END;
"""


def init_schema(con: sqlite3.Connection):
    con.executescript(SCHEMA)
    con.commit()
