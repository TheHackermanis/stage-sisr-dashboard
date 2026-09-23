"""Phase 1 : collecte, rayon strict, dédoublonnage, score, robustesse des sources."""

import json

import pytest

from app import db
from app.services import refresh as refresh_mod
from app.services import referentiels as ref
from app.services.scoring import calculer_score
from app.services.technos import detecter_technos
from app.sources.base import EntrepriseRecord, OffreRecord, Source, SourceResult
from app.sources.recherche_entreprises import RechercheEntreprisesSource

BREST = (48.390394, -4.486076)


def ent(nom, siret, lat=48.39, lon=-4.48, **kw):
    return EntrepriseRecord(nom=nom, siret=siret, lat=lat, lon=lon, ville="Brest", naf="62.02A",
                            tranche_effectif="11", **kw)


class FakeSource(Source):
    def __init__(self, name, result=None, exc=None, configured=True):
        self.name, self.label = name, name
        self._result, self._exc, self._configured = result, exc, configured
        self.missing_config_message = "clé absente"

    def is_configured(self):
        return self._configured

    def fetch(self, ctx):
        ctx.progress("test", 0.5)
        if self._exc:
            raise self._exc
        return self._result


def lancer(monkeypatch, sources):
    monkeypatch.setattr(refresh_mod, "toutes_les_sources", lambda: sources)
    monkeypatch.setattr(refresh_mod, "geocoder", lambda *a, **k: None)  # pas de réseau
    m = refresh_mod.RefreshManager()
    assert m.lancer()
    m.attendre(30)
    return m.etat()


@pytest.fixture
def base(db_path):
    db.init_db(db_path)
    return db_path


def test_distance_haversine():
    # Brest -> Quimper ≈ 57 km à vol d'oiseau
    assert 50 < ref.distance_km(*BREST, 47.996, -4.102) < 60
    assert ref.distance_km(*BREST, *BREST) == 0


def test_rayon_strict_50km(base, monkeypatch):
    res = SourceResult(entreprises=[
        ent("Proche", "11111111100011"),                         # Brest
        ent("Loin", "22222222200022", lat=47.996, lon=-4.102),   # Quimper, > 50 km
        ent("Sans coordonnées", "33333333300033", lat=None, lon=None),
    ])
    etat = lancer(monkeypatch, [FakeSource("s1", res)])
    with db.get_conn() as conn:
        noms = [r[0] for r in conn.execute("SELECT nom FROM entreprises")]
    assert noms == ["Proche"]
    assert etat["resume"]["exclues_distance"] == 2


def test_dedoublonnage_siret_et_suivi_preserve(base, monkeypatch):
    lancer(monkeypatch, [FakeSource("s1", SourceResult(entreprises=[ent("ACME", "44444444400044")]))])
    with db.get_conn() as conn:
        cid = conn.execute("SELECT id FROM cibles").fetchone()[0]
        conn.execute("UPDATE cibles SET statut='retenu', notes='Appelé M. X', favori=1, priorite=4 WHERE id=?",
                     (cid,))
        conn.execute("UPDATE entreprises SET site_web='https://acme.fr'")
    # Deuxième actualisation : même SIRET, nom modifié, site web différent
    etat = lancer(monkeypatch, [FakeSource("s1", SourceResult(entreprises=[
        ent("ACME INFORMATIQUE", "44444444400044", site_web="https://autre.fr")]))])
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM entreprises").fetchone()[0] == 1
        e = conn.execute("SELECT * FROM entreprises").fetchone()
        c = conn.execute("SELECT * FROM cibles").fetchone()
    assert e["nom"] == "ACME INFORMATIQUE"             # donnée source mise à jour
    assert e["site_web"] == "https://acme.fr"          # donnée enrichie non écrasée
    assert (c["statut"], c["notes"], c["favori"], c["priorite"]) == ("retenu", "Appelé M. X", 1, 4)
    assert etat["resume"]["nouvelles_entreprises"] == 0


def test_doublon_nom_ville_sans_siret(base, monkeypatch):
    offre = OffreRecord(source_ref="FT1", titre="Stage technicien réseau", type_contrat="stage",
                        lat=48.39, lon=-4.48, entreprise=EntrepriseRecord(nom="Acme SAS", ville="Brest"))
    lancer(monkeypatch, [FakeSource("s1", SourceResult(entreprises=[ent("ACME", "44444444400044")])),
                         FakeSource("s2", SourceResult(offres=[offre]))])
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM entreprises").fetchone()[0] == 1
        types = sorted(r[0] for r in conn.execute("SELECT type FROM cibles"))
    assert types == ["offre", "spontanee"]


def test_source_en_erreur_ou_non_configuree_nbloque_pas(base, monkeypatch):
    etat = lancer(monkeypatch, [
        FakeSource("cassee", exc=RuntimeError("API down")),
        FakeSource("sans_cle", configured=False),
        FakeSource("ok", SourceResult(entreprises=[ent("OK", "55555555500055")])),
    ])
    assert etat["sources"]["cassee"]["statut"] == "erreur"
    assert "API down" in etat["sources"]["cassee"]["message"]
    assert etat["sources"]["sans_cle"]["statut"] == "ignoree"
    assert etat["sources"]["ok"]["statut"] == "ok"
    assert etat["resume"]["nouvelles_entreprises"] == 1


def test_score_et_explication():
    p = {"rayon_km": 50, "mots_cles": {"active directory": 8, "linux": 6, "développeur": -5},
         "naf_poids": {"62.03Z": 18}}
    s_offre, detail = calculer_score(type_cible="offre", texte="Stage admin Active Directory et Linux",
                                     naf="62.03Z", distance_km=3, tranche="12", parametres=p,
                                     type_contrat="stage")
    s_loin, _ = calculer_score(type_cible="spontanee", texte="Développeur", naf=None,
                               distance_km=48, tranche="NN", parametres=p)
    assert 0 <= s_loin < s_offre <= 100
    assert s_offre == sum(d["points"] for d in detail)
    assert any("active directory" in d["raison"] for d in detail)


def test_detection_technos():
    t = detecter_technos("Admin Windows Server / AD, switchs Cisco, VMware ESXi, support N2 GLPI")
    for attendu in ["Windows Server", "Cisco", "VMware", "Support N1/N2", "GLPI / ITSM", "Réseau"]:
        assert attendu in t


def test_nom_etablissement():
    ul = {"nom_raison_sociale": "SURAVENIR", "nom_complet": "SURAVENIR (SURAVENIR)"}
    assert RechercheEntreprisesSource._nom(ul, {"liste_enseignes": ["SURAVENIR"]}) == "SURAVENIR"
    assert RechercheEntreprisesSource._nom(ul, {"nom_commercial": "Arkea Info"}) == "Arkea Info (SURAVENIR)"


def test_parsing_reponse_api(base):
    """Réponse réelle simplifiée de /near_point -> un enregistrement exploitable."""
    ul = {"siren": "479766842", "nom_raison_sociale": "CAPGEMINI", "section_activite_principale": "J"}
    etab = {"siret": "47976684200203", "etat_administratif": "A", "activite_principale": "62.02A",
            "adresse": "10 QUAI COMMANDANT MALBERT 29200 BREST", "code_postal": "29200",
            "libelle_commune": "BREST", "latitude": "48.379", "longitude": "-4.486",
            "tranche_effectif_salarie": "22"}
    rec = RechercheEntreprisesSource._to_record(ul, etab, "standard")
    assert rec.siret == "47976684200203" and rec.ville == "Brest" and rec.lat == 48.379
    assert rec.secteur.startswith("Conseil")
    etab_ferme = dict(etab, etat_administratif="F")
    assert RechercheEntreprisesSource._to_record(ul, etab_ferme, "standard") is None
