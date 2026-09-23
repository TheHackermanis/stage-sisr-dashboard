"""Phase 6-7 : réglages, saisie manuelle, édition, modèle de mail, doublons."""

import pytest

from app import db
from app.services import gestion, merge
from app.sources.base import EntrepriseRecord


@pytest.fixture(autouse=True)
def pas_de_reseau(monkeypatch):
    """Géocodage simulé : Landerneau connue, le reste introuvable."""
    def fake(adresse, cp, ville):
        if (ville or "").lower().startswith("landerneau") or "landerneau" in (adresse or "").lower():
            return 48.4506, -4.2503
        if (ville or "").lower() == "quimper":
            return 47.996, -4.102
        return None
    monkeypatch.setattr(gestion, "_geocoder", fake)


def test_parametres_validation(client):
    assert client.put("/api/parametres", json={"rayon_km": 500}).status_code == 400
    assert client.put("/api/parametres", json={"inconnu": 1}).status_code == 400
    assert client.put("/api/parametres", json={"delai_relance_jours": 0}).status_code == 400
    p = client.put("/api/parametres", json={"rayon_km": 30, "delai_relance_jours": 10}).json()
    assert p["rayon_km"] == 30 and p["delai_relance_jours"] == 10


def test_changement_ville_recalcule_distances(client):
    client.post("/api/manuel", json={"nom": "Test Landerneau", "ville": "Landerneau"})
    avant = client.get("/api/cibles").json()[0]["distance_km"]
    p = client.put("/api/parametres", json={"ville_depart": {"nom": "Landerneau", "code_postal": "29800"}}).json()
    assert p["ville_depart"]["lat"] == 48.4506
    apres = client.get("/api/cibles").json()[0]["distance_km"]
    assert avant > 15 and apres == 0
    assert client.put("/api/parametres", json={"ville_depart": {"nom": "Atlantide"}}).status_code == 400


def test_saisie_manuelle_offre_et_spontanee(client):
    f = client.post("/api/manuel", json={
        "type": "offre", "nom": "Mairie de Landerneau", "ville": "Landerneau", "titre": "Stage technicien SISR",
        "description": "Parc Windows, Active Directory, GLPI", "url": "https://exemple.fr/offre", "notes": "Vu sur le site"}).json()
    assert f["type"] == "offre" and f["type_contrat"] == "stage" and f["notes"] == "Vu sur le site"
    assert "Active Directory" in f["technos"] and f["distance_km"] > 15
    assert "manuel" in f["sources"]
    s = client.post("/api/manuel", json={"nom": "Mairie de Landerneau", "ville": "Landerneau"}).json()
    assert s["type"] == "spontanee" and s["entreprise_id"] == f["entreprise_id"]  # même entreprise
    assert client.post("/api/manuel", json={"nom": ""}).status_code == 400


def test_edition_non_ecrasee_par_actualisation(client):
    f = client.post("/api/manuel", json={"nom": "ACME", "siret": "44444444400044", "ville": "Landerneau"}).json()
    client.patch(f"/api/entreprises/{f['entreprise_id']}",
                 json={"site_web": "https://acme.bzh", "email_public": "contact@acme.bzh", "nom": "ACME Réseaux"})
    # Une source renvoie ensuite la même entreprise avec d'autres valeurs
    with db.get_conn() as conn:
        rec = EntrepriseRecord(nom="ACME SAS", siret="44444444400044", ville="Landerneau",
                               site_web="https://autre.fr", lat=48.45, lon=-4.25)
        merge.upsert_entreprise(conn, rec, "recherche_entreprises", 20.0)
    d = client.get(f"/api/cibles/{f['id']}").json()
    assert d["nom"] == "ACME Réseaux" and d["site_web"] == "https://acme.bzh" and d["email_public"] == "contact@acme.bzh"


def test_modele_mail(client):
    client.put("/api/parametres", json={"profil": {"prenom_nom": "Gabriel Test", "email": "g@test.fr",
                                                   "telephone": "0600000000", "ecole": "", "ville": "Brest"}})
    f = client.post("/api/manuel", json={"nom": "RESEAUX DU PONANT", "ville": "Landerneau",
                                         "email_public": "rh@ponant.fr"}).json()
    m = client.get(f"/api/cibles/{f['id']}/mail").json()
    assert "Reseaux Du Ponant" in m["corps"] and "4 janvier 2027" in m["corps"]
    assert "7 à 8 semaines" in m["objet"] and "Gabriel Test" in m["corps"]
    assert m["destinataire"] == "rh@ponant.fr" and "{" not in m["corps"]


def test_doublons_et_fusion(client):
    a = client.post("/api/manuel", json={"nom": "Breizh Informatique", "ville": "Landerneau", "notes": "note A"}).json()
    with db.get_conn() as conn:  # doublon créé par une autre source (orthographe différente, sans SIRET)
        eid = conn.execute("INSERT INTO entreprises (nom, nom_normalise, ville) VALUES "
                           "('BREIZH INFORMATIQUE SARL', 'breizh informatique', 'Landerneau')").lastrowid
        cid = conn.execute("INSERT INTO cibles (entreprise_id, type, statut, notes) VALUES (?, 'spontanee', 'envoyee', 'note B')",
                           (eid,)).lastrowid
    paires = client.get("/api/doublons").json()
    assert len(paires) == 1
    client.post("/api/doublons/fusionner", json={"garder_id": a["entreprise_id"], "fusion_id": eid})
    d = client.get(f"/api/cibles/{a['id']}").json()
    assert d["statut"] == "envoyee"                   # statut le plus avancé conservé
    assert "note A" in d["notes"] and "note B" in d["notes"]
    assert client.get("/api/doublons").json() == []
    assert client.get(f"/api/cibles/{cid}").status_code == 404


def test_detection_doublon_a_l_import(client):
    """Une entreprise sans SIRET au nom quasi identique est rattachée à l'existante."""
    client.post("/api/manuel", json={"nom": "Ouest Réseaux Télécom", "ville": "Landerneau"})
    with db.get_conn() as conn:
        rec = EntrepriseRecord(nom="OUEST RESEAUX TELECOM", ville="Landerneau", lat=48.45, lon=-4.25)
        _, cree = merge.upsert_entreprise(conn, rec, "france_travail_offres", 20.0)
    assert cree is False
