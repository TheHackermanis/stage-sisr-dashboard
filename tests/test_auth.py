"""Protection par mot de passe."""

import pytest

from app import auth, config


@pytest.fixture
def protege(monkeypatch, client):
    monkeypatch.setattr(config, "APP_PASSWORD_HASH", auth.hasher("un-mot-de-passe-solide"))
    monkeypatch.setattr(config, "SECRET_KEY", "x" * 48)
    auth._echecs.clear()
    client.cookies.clear()
    return client


def test_sans_mot_de_passe_tout_est_ouvert(client):
    assert client.get("/api/cibles").status_code == 200


def test_tout_est_protege(protege):
    assert protege.get("/api/cibles").status_code == 401
    assert protege.get("/api/export").status_code == 401
    r = protege.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert protege.get("/login").status_code == 200
    assert protege.get("/static/style.css").status_code == 200


def test_connexion_et_deconnexion(protege):
    assert protege.post("/api/login", json={"mot_de_passe": "faux"}).status_code == 401
    r = protege.post("/api/login", json={"mot_de_passe": "un-mot-de-passe-solide"})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert protege.get("/api/cibles").status_code == 200
    protege.post("/api/logout")
    protege.cookies.clear()
    assert protege.get("/api/cibles").status_code == 401


def test_cookie_falsifie_refuse(protege):
    protege.cookies.set(auth.COOKIE, "9999999999.abc.deadbeef")
    assert protege.get("/api/cibles").status_code == 401


def test_changement_mot_de_passe_invalide_sessions(protege, monkeypatch):
    protege.post("/api/login", json={"mot_de_passe": "un-mot-de-passe-solide"})
    assert protege.get("/api/cibles").status_code == 200
    monkeypatch.setattr(config, "APP_PASSWORD_HASH", auth.hasher("nouveau-mot-de-passe"))
    assert protege.get("/api/cibles").status_code == 401


def test_anti_force_brute(protege):
    for _ in range(5):
        assert protege.post("/api/login", json={"mot_de_passe": "faux"}).status_code == 401
    # Même le bon mot de passe est refusé pendant le blocage
    assert protege.post("/api/login", json={"mot_de_passe": "un-mot-de-passe-solide"}).status_code == 429


def test_ip_reelle_derriere_cloudflare():
    """L'en-tête CF-Connecting-IP n'est cru que si la requête vient du tunnel local (127.0.0.1)."""
    from types import SimpleNamespace as NS
    via_tunnel = NS(client=NS(host="127.0.0.1"), headers={"cf-connecting-ip": "1.2.3.4"})
    usurpation = NS(client=NS(host="8.8.8.8"), headers={"cf-connecting-ip": "1.2.3.4"})
    assert auth.ip_client(via_tunnel) == "1.2.3.4"
    assert auth.ip_client(usurpation) == "8.8.8.8"
    auth._echecs.clear()
    for _ in range(5):
        auth.noter_echec("1.2.3.4")
    assert auth.bloque("1.2.3.4") and not auth.bloque("5.6.7.8")


def test_hash_verification():
    h = auth.hasher("abc123456789")
    assert h.startswith("scrypt$") and "abc123456789" not in h
    assert auth.verifier("abc123456789", h) and not auth.verifier("abc12345678", h)
    assert not auth.verifier("x", "n'importe quoi")
