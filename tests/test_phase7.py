"""Phase 7 : enrichissement web (analyse de page, filtrage RGPD des contacts, domaines candidats)."""

from app import db
from app.services import enrichissement
from app.services.enrichissement import Enrichisseur

HTML = """<html><head><title>Breizh Réseaux – infogérance à Brest</title>
<meta name="description" content="Breizh Réseaux installe et maintient vos réseaux et serveurs."></head>
<body><nav><a href="/contact">Nous contacter</a> <a href="/carrieres">Rejoignez-nous</a>
<a href="https://linkedin.com/company/x">LinkedIn</a></nav>
<p>Écrivez à jean.dupont@breizh-reseaux.fr ou contact@breizh-reseaux.fr</p>
<a href="tel:+33298000000">02 98 00 00 00</a></body></html>"""


class FakeHttp:
    min_interval = {}
    def close(self): pass


def test_analyse_site():
    out = Enrichisseur(FakeHttp()).analyser_site("https://breizh-reseaux.fr/", HTML)
    assert out["description_activite"].startswith("Breizh Réseaux installe")
    assert out["page_contact"] == "https://breizh-reseaux.fr/contact"
    assert out["page_recrutement"] == "https://breizh-reseaux.fr/carrieres"
    assert out["email_public"] == "contact@breizh-reseaux.fr"   # l'adresse nominative est ignorée
    assert out["tel_public"].replace(" ", "") == "+33298000000"


def test_emails_generiques_seulement():
    g = Enrichisseur._email_generique
    assert g("RH@acme.fr") == "rh@acme.fr"
    assert g("recrutement@acme.fr") == "recrutement@acme.fr"
    assert g("jean.dupont@acme.fr") is None
    assert g(None) is None


def test_domaines_candidats():
    d = Enrichisseur(FakeHttp()).domaines_candidats("BREIZH RESEAUX SAS (BREIZH RESEAUX)")
    assert "https://breizh.fr" in d and "https://breizhreseaux.fr" in d and len(d) <= 6
    assert Enrichisseur(FakeHttp()).domaines_candidats("SAS") == []


def test_appliquer_ne_remplace_pas(db_path):
    db.init_db(db_path)
    with db.get_conn() as conn:
        eid = conn.execute("INSERT INTO entreprises (nom, nom_normalise, site_web) VALUES "
                           "('X', 'x', 'https://deja.fr')").lastrowid
        conn.execute("INSERT INTO cibles (entreprise_id, type) VALUES (?, 'spontanee')", (eid,))
        ajoutes = enrichissement.appliquer(conn, eid, {"site_web": "https://autre.fr",
                                                       "email_public": "contact@deja.fr"})
        e = conn.execute("SELECT * FROM entreprises").fetchone()
    assert ajoutes == ["email_public"] and e["site_web"] == "https://deja.fr"


def test_enrichissement_hors_actualisation_normale():
    from app.sources import toutes_les_sources
    parts = {s.name: s.par_defaut for s in toutes_les_sources()}
    assert parts["enrichissement_web"] is False and parts["recherche_entreprises"] is True
