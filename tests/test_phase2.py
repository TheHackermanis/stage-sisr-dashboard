"""Phase 2 : suivi (statuts, historique, auto-Vu, relances, corbeille, lot, favoris, notes)."""

from datetime import datetime, timedelta

import pytest

from app import db
from app.services import tracking


@pytest.fixture
def ids(client):
    """Trois cibles de test insérées directement en BDD."""
    out = []
    with db.get_conn() as conn:
        for i, (nom, ville, dist) in enumerate([("Alpha Réseaux", "Brest", 2.0),
                                                ("Beta Info", "Landerneau", 20.0),
                                                ("Gamma Cloud", "Morlaix", 45.0)]):
            e = conn.execute("INSERT INTO entreprises (nom, nom_normalise, ville, distance_km, secteur, "
                             "tranche_effectif) VALUES (?, ?, ?, ?, 'Informatique', '11')",
                             (nom, nom.lower(), ville, dist)).lastrowid
            c = conn.execute("INSERT INTO cibles (entreprise_id, type, score, technos_json) VALUES (?, ?, ?, ?)",
                             (e, "spontanee" if i else "dsi_interne", 80 - i * 20,
                              '["Linux", "Cisco"]' if i == 0 else '["Linux"]')).lastrowid
            out.append(c)
    return out


def test_liste_et_filtres(client, ids):
    assert len(client.get("/api/cibles").json()) == 3
    assert [c["nom"] for c in client.get("/api/cibles?distance_max=25").json()] == ["Alpha Réseaux", "Beta Info"]
    assert len(client.get("/api/cibles?score_min=60").json()) == 2
    assert len(client.get("/api/cibles?technos=Linux&technos=Cisco").json()) == 1
    assert len(client.get("/api/cibles?type=spontanee").json()) == 2
    assert client.get("/api/cibles?q=reseaux").json()[0]["nom"] == "Alpha Réseaux"  # sans accent
    assert [c["nom"] for c in client.get("/api/cibles?tri=nom&ordre=desc").json()][0] == "Gamma Cloud"


def test_ouverture_fiche_passe_en_vu(client, ids):
    d = client.get(f"/api/cibles/{ids[0]}?marquer_vu=true").json()
    assert d["statut"] == "vu"
    assert d["historique"][0]["nouveau_statut"] == "vu"
    # Un second passage ne recrée pas d'historique
    d = client.get(f"/api/cibles/{ids[0]}?marquer_vu=true").json()
    assert len([h for h in d["historique"] if h["nouveau_statut"] == "vu"]) == 1


def test_envoi_enregistre_date_et_historique(client, ids):
    d = client.post(f"/api/cibles/{ids[0]}/statut", json={"statut": "envoyee"}).json()
    assert d["statut"] == "envoyee" and d["date_envoi"].startswith(datetime.now().strftime("%Y-%m-%d"))
    assert d["historique"][0]["ancien_statut"] == "nouveau"


def test_relance_automatique(client, ids):
    with db.get_conn() as conn:
        tracking.changer_statut(conn, ids[0], "envoyee")
        tracking.changer_statut(conn, ids[1], "envoyee")
        vieux = (datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE cibles SET date_envoi = ? WHERE id = ?", (vieux, ids[0]))
        db.set_parametre(conn, "delai_relance_jours", 7)
    dash = client.get("/api/dashboard").json()
    assert [r["id"] for r in dash["a_relancer"]] == [ids[0]]
    assert dash["compteurs"]["envoyee"] == 1
    assert dash["envoyees_semaine"] == 2
    # Délai paramétrable : à 10 jours, rien de plus ne bascule
    with db.get_conn() as conn:
        db.set_parametre(conn, "delai_relance_jours", 10)
        assert tracking.appliquer_relances_auto(conn) == 0


def test_entretien_avec_date(client, ids):
    d = client.post(f"/api/cibles/{ids[1]}/statut",
                    json={"statut": "entretien", "entretien_at": "2099-01-10T14:30"}).json()
    assert d["entretien_at"] == "2099-01-10T14:30"
    assert client.get("/api/dashboard").json()["entretiens"][0]["id"] == ids[1]


def test_corbeille_et_restauration(client, ids):
    client.post(f"/api/cibles/{ids[0]}/statut", json={"statut": "retenu"})
    client.post(f"/api/cibles/{ids[0]}/statut", json={"statut": "supprime"})
    assert ids[0] not in [c["id"] for c in client.get("/api/cibles").json()]
    assert [c["id"] for c in client.get("/api/cibles?corbeille=1").json()] == [ids[0]]
    d = client.post(f"/api/cibles/{ids[0]}/restaurer").json()
    assert d["statut"] == "retenu"
    with db.get_conn() as conn:  # rien n'est supprimé définitivement
        assert conn.execute("SELECT COUNT(*) FROM cibles").fetchone()[0] == 3


def test_modification_en_lot(client, ids):
    r = client.post("/api/lot/statut", json={"ids": ids[:2], "statut": "retenu"}).json()
    assert r["modifiees"] == 2
    statuts = {c["id"]: c["statut"] for c in client.get("/api/cibles").json()}
    assert statuts[ids[0]] == statuts[ids[1]] == "retenu" and statuts[ids[2]] == "nouveau"


def test_favori_priorite_notes(client, ids):
    d = client.patch(f"/api/cibles/{ids[2]}", json={"favori": True, "priorite": 5,
                                                    "notes": "Appelé le standard"}).json()
    assert d["favori"] is True and d["priorite"] == 5 and d["notes"] == "Appelé le standard"
    assert client.patch(f"/api/cibles/{ids[2]}", json={"priorite": 9}).status_code == 400
    assert [c["id"] for c in client.get("/api/cibles?favoris=1").json()] == [ids[2]]


def test_statut_invalide(client, ids):
    assert client.post(f"/api/cibles/{ids[0]}/statut", json={"statut": "nimporte"}).status_code == 400
    assert client.get("/api/cibles/99999").status_code == 404
