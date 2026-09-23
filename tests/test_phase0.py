"""Phase 0 : démarrage, schéma, paramètres par défaut."""

from app import db

TABLES = {"entreprises", "offres", "provenances", "cibles", "historique",
          "parametres", "http_cache", "refresh_runs"}


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["schema_version"] == db.SCHEMA_VERSION
    assert "france_travail_offres" in data["sources"]


def test_index_servi(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Stage SISR" in r.text


def test_schema_cree(db_path):
    db.init_db(db_path)
    with db.get_conn(db_path) as conn:
        noms = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert TABLES <= noms


def test_parametres_par_defaut(client):
    p = client.get("/api/parametres").json()
    assert p["ville_depart"]["nom"] == "Brest"
    assert p["rayon_km"] == 50
    assert "62.02A" in p["naf_sisr"]
    assert p["delai_relance_jours"] == 7
    assert p["stage_debut"] == "2027-01-04"


def test_init_idempotent_conserve_reglages(db_path):
    """Relancer init_db ne doit pas écraser un réglage modifié par l'utilisateur."""
    db.init_db(db_path)
    with db.get_conn(db_path) as conn:
        db.set_parametre(conn, "rayon_km", 30)
    db.init_db(db_path)
    with db.get_conn(db_path) as conn:
        assert db.get_parametres(conn)["rayon_km"] == 30


def test_contraintes_statut(db_path):
    """Un statut inconnu est refusé par la BDD."""
    import sqlite3
    import pytest
    db.init_db(db_path)
    with db.get_conn(db_path) as conn:
        conn.execute("INSERT INTO entreprises (nom, nom_normalise) VALUES ('Test', 'test')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO cibles (entreprise_id, type, statut) VALUES (1, 'spontanee', 'bidon')")
