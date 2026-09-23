"""Phase 5 : sources France Travail (offres) et La Bonne Boîte, avec réponses simulées."""

import pytest

from app import config, db
from app.services import refresh as refresh_mod
from app.sources import france_travail_auth
from app.sources.base import FetchContext
from app.sources.france_travail_offres import FranceTravailOffresSource, classer_contrat
from app.sources.la_bonne_boite import LaBonneBoiteSource, _tranche_depuis_effectif

OFFRE_STAGE = {
    "id": "190XYZ", "intitule": "Stage Technicien systèmes et réseaux H/F",
    "description": "Au sein de la DSI : Active Directory, Windows Server, switchs Cisco, support N1/N2.",
    "dateCreation": "2026-09-20T10:00:00.000Z", "romeCode": "M1801", "typeContrat": "CDD",
    "typeContratLibelle": "Contrat à durée déterminée - 2 Mois",
    "lieuTravail": {"libelle": "29 - BREST", "latitude": 48.39, "longitude": -4.48, "codePostal": "29200"},
    "entreprise": {"nom": "ACME INFOGERANCE", "description": "Infogérance PME"},
}
OFFRE_ALTERNANCE = {**OFFRE_STAGE, "id": "190ALT", "intitule": "Administrateur systèmes (H/F)", "alternance": True}
OFFRE_CDI = {**OFFRE_STAGE, "id": "190CDI", "intitule": "Administrateur systèmes (H/F)", "description": "CDI",
             "typeContratLibelle": "CDI", "entreprise": {}}
OFFRE_LOIN = {**OFFRE_STAGE, "id": "190QMP", "lieuTravail": {"libelle": "29 - QUIMPER", "latitude": 47.99,
                                                              "longitude": -4.10}}
OFFRE_HORS_IT = {**OFFRE_STAGE, "id": "190BOUL", "intitule": "Stage vendeur boulangerie", "romeCode": "D1102",
                 "description": "Vente et accueil clientèle"}


class FakeHttp:
    """Remplace CachedHttp : renvoie des réponses préparées selon l'URL."""
    def __init__(self, reponses):
        self.reponses, self.appels = reponses, []
        self.nb_requetes = self.nb_cache = 0

    def get_json(self, url, params=None, **kw):
        self.appels.append((url, params))
        for cle, rep in self.reponses.items():
            if cle in url:
                return rep(params) if callable(rep) else rep
        return None

    def close(self):
        pass


def ctx(http, parametres):
    return FetchContext(parametres=parametres, http=http, progress=lambda *a: None)


@pytest.fixture
def params(db_path):
    db.init_db(db_path)
    with db.get_conn() as conn:
        return db.get_parametres(conn)


@pytest.fixture(autouse=True)
def cles_ft(monkeypatch):
    monkeypatch.setattr(config, "FT_CLIENT_ID", "id")
    monkeypatch.setattr(config, "FT_CLIENT_SECRET", "secret")
    monkeypatch.setattr(france_travail_auth, "get_token", lambda http, scope: "TOKEN")
    import app.sources.france_travail_offres as fto
    import app.sources.la_bonne_boite as lbb
    monkeypatch.setattr(fto, "get_token", lambda http, scope: "TOKEN")
    monkeypatch.setattr(lbb, "get_token", lambda http, scope: "TOKEN")
    monkeypatch.setattr(fto, "code_insee", lambda *a, **k: "29019")


def test_classement_contrat():
    assert classer_contrat(OFFRE_STAGE) == "stage"
    assert classer_contrat(OFFRE_ALTERNANCE) == "alternance"
    assert classer_contrat(OFFRE_CDI) == "autre"
    assert classer_contrat({"intitule": "Technicien support en apprentissage"}) == "alternance"


def test_ft_offres_parsing_et_filtrage(params):
    toutes = [OFFRE_STAGE, OFFRE_ALTERNANCE, OFFRE_CDI, OFFRE_HORS_IT]
    http = FakeHttp({"offresdemploi": lambda p: {"resultats": toutes if p["range"].startswith("0-") else []}})
    c = ctx(http, params)
    res = FranceTravailOffresSource().fetch(c)
    ids = sorted(o.source_ref for o in res.offres)
    assert ids == ["190ALT", "190XYZ"]            # CDI et hors informatique ignorés
    stage = next(o for o in res.offres if o.source_ref == "190XYZ")
    assert stage.type_contrat == "stage" and stage.entreprise.nom == "ACME INFOGERANCE"
    assert stage.entreprise.ville == "Brest" and stage.date_publication == "2026-09-20"
    assert http.appels[0][1]["commune"] == "29019" and http.appels[0][1]["distance"] == 50
    assert res.offres_complet and any("ignorée" in a for a in c.avertissements)


def test_ft_integration_rayon_expiration(params, monkeypatch):
    """Intégration complète : rayon 50 km strict, offres disparues marquées expirées."""
    lot = {"offres": [OFFRE_STAGE, OFFRE_LOIN]}
    http = FakeHttp({"offresdemploi": lambda p: {"resultats": lot["offres"] if p["range"].startswith("0-") else []}})
    monkeypatch.setattr(refresh_mod, "CachedHttp", lambda *a, **k: http)
    monkeypatch.setattr(refresh_mod, "geocoder", lambda *a, **k: None)
    monkeypatch.setattr(refresh_mod, "toutes_les_sources", lambda: [FranceTravailOffresSource()])

    m = refresh_mod.RefreshManager()
    m.lancer(); m.attendre(30)
    etat = m.etat()
    assert etat["resume"]["nouvelles_offres"] == 1 and etat["resume"]["exclues_distance"] == 1
    with db.get_conn() as conn:
        o = conn.execute("SELECT * FROM offres").fetchone()
        c = conn.execute("SELECT * FROM cibles WHERE offre_id = ?", (o["id"],)).fetchone()
    assert o["active"] == 1 and c["type"] == "offre" and c["score"] > 60
    assert "Active Directory" in c["technos_json"]

    lot["offres"] = []  # l'offre a disparu de France Travail
    m.lancer(); m.attendre(30)
    with db.get_conn() as conn:
        assert conn.execute("SELECT active FROM offres").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM cibles").fetchone()[0] == 1  # rien de supprimé


def test_lbb_parsing(params):
    items = [{"siret": "12345678900011", "company_name": "RESEAU PLUS", "naf": "6202A", "naf_label": "Conseil",
              "city": "BREST", "postcode": "29200", "location": {"lat": 48.4, "lon": -4.5},
              "headcount_min": 20, "hiring_potential": 2.5, "website": "https://reseauplus.fr"}]
    http = FakeHttp({"labonneboite": {"hits": 1, "items": items}})
    res = LaBonneBoiteSource().fetch(ctx(http, params))
    assert len(res.entreprises) == 1
    e = res.entreprises[0]
    assert (e.siret, e.naf, e.ville, e.tranche_effectif, e.site_web) == \
        ("12345678900011", "62.02A", "Brest", "12", "https://reseauplus.fr")
    assert e.raw["hiring_potential"] == 2.5


def test_tranche_depuis_effectif():
    assert _tranche_depuis_effectif(0) == "00"
    assert _tranche_depuis_effectif(12) == "11"
    assert _tranche_depuis_effectif(250) == "32"
    assert _tranche_depuis_effectif(None) is None


def test_sans_cle_source_ignoree(monkeypatch):
    monkeypatch.setattr(config, "FT_CLIENT_ID", "")
    assert not FranceTravailOffresSource().is_configured()
    assert not LaBonneBoiteSource().is_configured()


def test_auth_message_clair(monkeypatch):
    """Une clé invalide produit un message compréhensible."""
    import importlib
    auth = importlib.reload(france_travail_auth)

    class H:
        def request_text(self, *a, **k):
            return 401, '{"error": "invalid_client"}'
    with pytest.raises(auth.FranceTravailAuthError, match="FT_CLIENT_ID"):
        auth.get_token(H(), "api_test")
