"""Accès SQLite : connexion, création du schéma, paramètres.

Principe clé : les données issues des sources (entreprises, offres) et les données
de suivi saisies par l'utilisateur (table `cibles` : statut, notes, favori…) sont
dans des tables séparées. Une actualisation ne modifie jamais les colonnes de suivi.
"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app import config

# Incrémenter à chaque évolution du schéma et ajouter l'étape dans MIGRATIONS.
SCHEMA_VERSION = 1

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS entreprises (
    id                   INTEGER PRIMARY KEY,
    siret                TEXT UNIQUE,              -- clé de dédoublonnage (NULL si saisie manuelle sans SIRET)
    siren                TEXT,
    nom                  TEXT NOT NULL,
    nom_normalise        TEXT NOT NULL,            -- minuscules sans accents, pour la détection de doublons
    naf                  TEXT,
    secteur              TEXT,
    tranche_effectif     TEXT,
    date_creation        TEXT,
    adresse              TEXT,
    code_postal          TEXT,
    ville                TEXT,
    lat                  REAL,
    lon                  REAL,
    distance_km          REAL,
    site_web             TEXT,
    page_contact         TEXT,
    page_recrutement     TEXT,
    email_public         TEXT,
    tel_public           TEXT,
    description_activite TEXT,
    categorie            TEXT NOT NULL DEFAULT 'standard' CHECK (categorie IN ('standard', 'dsi_interne')),
    saisie_manuelle      INTEGER NOT NULL DEFAULT 0,
    created_at           TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at           TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_entreprises_nom ON entreprises(nom_normalise, ville);

CREATE TABLE IF NOT EXISTS offres (
    id               INTEGER PRIMARY KEY,
    entreprise_id    INTEGER REFERENCES entreprises(id),
    source           TEXT NOT NULL,
    source_ref       TEXT NOT NULL,
    titre            TEXT NOT NULL,
    description      TEXT,
    type_contrat     TEXT CHECK (type_contrat IN ('stage', 'alternance', 'autre')),
    lieu             TEXT,
    lat              REAL,
    lon              REAL,
    distance_km      REAL,
    url              TEXT,
    date_publication TEXT,
    active           INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (source, source_ref)
);

-- Traçabilité : quelle source a remonté quoi, et quand.
CREATE TABLE IF NOT EXISTS provenances (
    id            INTEGER PRIMARY KEY,
    entreprise_id INTEGER REFERENCES entreprises(id),
    offre_id      INTEGER REFERENCES offres(id),
    source        TEXT NOT NULL,
    fetched_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    payload_json  TEXT
);
CREATE INDEX IF NOT EXISTS idx_provenances_ent ON provenances(entreprise_id);

-- Une cible = une ligne du dashboard (une carte du Kanban).
CREATE TABLE IF NOT EXISTS cibles (
    id                       INTEGER PRIMARY KEY,
    entreprise_id            INTEGER NOT NULL REFERENCES entreprises(id),
    offre_id                 INTEGER REFERENCES offres(id),
    type                     TEXT NOT NULL CHECK (type IN ('offre', 'spontanee', 'dsi_interne')),
    -- Calculé par l'application (recalculable à chaque actualisation)
    technos_json             TEXT NOT NULL DEFAULT '[]',
    score                    INTEGER NOT NULL DEFAULT 0,
    score_detail_json        TEXT NOT NULL DEFAULT '[]',
    -- Données de suivi de l'utilisateur : JAMAIS écrasées par une actualisation
    statut                   TEXT NOT NULL DEFAULT 'nouveau' CHECK (statut IN (
                                 'nouveau', 'vu', 'retenu', 'envoyee', 'a_relancer',
                                 'entretien', 'accepte', 'refuse', 'supprime')),
    statut_avant_suppression TEXT,
    favori                   INTEGER NOT NULL DEFAULT 0,
    priorite                 INTEGER NOT NULL DEFAULT 0 CHECK (priorite BETWEEN 0 AND 5),
    notes                    TEXT NOT NULL DEFAULT '',
    date_envoi               TEXT,
    entretien_at             TEXT,
    vu_at                    TEXT,
    created_at               TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at               TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
-- Une seule cible par offre, et une seule cible « sans offre » par entreprise.
CREATE UNIQUE INDEX IF NOT EXISTS uq_cibles_offre ON cibles(offre_id) WHERE offre_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_cibles_entreprise ON cibles(entreprise_id) WHERE offre_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_cibles_statut ON cibles(statut);

CREATE TABLE IF NOT EXISTS historique (
    id              INTEGER PRIMARY KEY,
    cible_id        INTEGER NOT NULL REFERENCES cibles(id),
    ancien_statut   TEXT,
    nouveau_statut  TEXT NOT NULL,
    commentaire     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_historique_cible ON historique(cible_id);

CREATE TABLE IF NOT EXISTS parametres (
    cle    TEXT PRIMARY KEY,
    valeur TEXT NOT NULL            -- JSON
);

CREATE TABLE IF NOT EXISTS http_cache (
    cle_hash   TEXT PRIMARY KEY,
    url        TEXT NOT NULL,
    reponse    TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    ttl_heures INTEGER NOT NULL DEFAULT 24
);

CREATE TABLE IF NOT EXISTS refresh_runs (
    id           INTEGER PRIMARY KEY,
    debut        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    fin          TEXT,
    resume_json  TEXT,
    erreurs_json TEXT
);
"""

MIGRATIONS = {1: SCHEMA_V1}


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    """Ouvre une connexion SQLite configurée (lignes accessibles par nom, clés étrangères actives)."""
    path = Path(db_path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")  # lectures possibles pendant une actualisation
    return conn


@contextmanager
def get_conn(db_path: Path | None = None):
    """Connexion à usage court : commit si tout va bien, rollback sinon."""
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    """Crée ou met à jour le schéma, puis insère les paramètres par défaut manquants.

    Idempotent : peut être appelé à chaque démarrage sans rien perdre.
    """
    with get_conn(db_path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        for v in range(version + 1, SCHEMA_VERSION + 1):
            conn.executescript(MIGRATIONS[v])
            conn.execute(f"PRAGMA user_version = {v}")
        # N'ajoute que les clés absentes : les réglages déjà modifiés sont conservés.
        for cle, valeur in config.DEFAULT_PARAMETRES.items():
            conn.execute(
                "INSERT OR IGNORE INTO parametres (cle, valeur) VALUES (?, ?)",
                (cle, json.dumps(valeur, ensure_ascii=False)),
            )


def get_parametres(conn: sqlite3.Connection) -> dict:
    """Retourne tous les paramètres sous forme de dict Python."""
    rows = conn.execute("SELECT cle, valeur FROM parametres").fetchall()
    return {r["cle"]: json.loads(r["valeur"]) for r in rows}


def set_parametre(conn: sqlite3.Connection, cle: str, valeur) -> None:
    conn.execute(
        "INSERT INTO parametres (cle, valeur) VALUES (?, ?) "
        "ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur",
        (cle, json.dumps(valeur, ensure_ascii=False)),
    )
