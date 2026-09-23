"""Protection par mot de passe (utile quand le dashboard est accessible en ligne).

- Le mot de passe n'est jamais stocké : seul son empreinte scrypt est dans .env (APP_PASSWORD_HASH).
- Une fois connecté, le navigateur reçoit un cookie de session signé (HMAC-SHA256),
  HttpOnly, SameSite=Strict, Secure en HTTPS, valable 30 jours.
- Changer le mot de passe invalide toutes les sessions existantes.
- Anti force brute : 5 échecs max par adresse IP sur 15 minutes.
- Si APP_PASSWORD_HASH est vide, l'authentification est désactivée (usage purement local).
"""

import hashlib
import hmac
import secrets
import threading
import time

from app import config

COOKIE = "stage_session"
DUREE_SESSION = 30 * 24 * 3600
MAX_ECHECS, FENETRE = 5, 15 * 60

# Chemins accessibles sans être connecté
PUBLICS = ("/login", "/api/login", "/static/")


# ------------------------------------------------------------------ mot de passe
def hasher(mot_de_passe: str) -> str:
    """Empreinte scrypt au format scrypt$n$r$p$sel$hash (utilisé par set_password)."""
    sel = secrets.token_bytes(16)
    n, r, p = 2 ** 15, 8, 1
    h = hashlib.scrypt(mot_de_passe.encode(), salt=sel, n=n, r=r, p=p, maxmem=64 * 1024 * 1024)
    return f"scrypt${n}${r}${p}${sel.hex()}${h.hex()}"


def verifier(mot_de_passe: str, empreinte: str) -> bool:
    try:
        algo, n, r, p, sel, h = empreinte.split("$")
        calc = hashlib.scrypt(mot_de_passe.encode(), salt=bytes.fromhex(sel), n=int(n), r=int(r), p=int(p),
                              maxmem=64 * 1024 * 1024)
    except (ValueError, TypeError):
        return False
    return algo == "scrypt" and hmac.compare_digest(calc.hex(), h)


def actif() -> bool:
    return bool(config.APP_PASSWORD_HASH)


# ------------------------------------------------------------------ sessions
def _cle() -> bytes:
    # L'empreinte du mot de passe fait partie de la clé : le changer déconnecte tout le monde.
    return hashlib.sha256((config.SECRET_KEY + "|" + config.APP_PASSWORD_HASH).encode()).digest()


def creer_session() -> str:
    exp = str(int(time.time()) + DUREE_SESSION)
    nonce = secrets.token_urlsafe(12)
    sig = hmac.new(_cle(), f"{exp}.{nonce}".encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{nonce}.{sig}"


def session_valide(jeton: str | None) -> bool:
    if not jeton:
        return False
    try:
        exp, nonce, sig = jeton.split(".")
        attendu = hmac.new(_cle(), f"{exp}.{nonce}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, attendu) and int(exp) > time.time()
    except ValueError:
        return False


# ------------------------------------------------------------------ anti force brute
_echecs: dict[str, list[float]] = {}
_lock = threading.Lock()


def bloque(ip: str) -> bool:
    with _lock:
        recents = [t for t in _echecs.get(ip, []) if t > time.time() - FENETRE]
        _echecs[ip] = recents
        return len(recents) >= MAX_ECHECS


def noter_echec(ip: str) -> None:
    with _lock:
        _echecs.setdefault(ip, []).append(time.time())


def reinitialiser(ip: str) -> None:
    with _lock:
        _echecs.pop(ip, None)


def ip_client(request) -> str:
    """Vraie IP du visiteur. Derrière Cloudflare Tunnel, la requête arrive de 127.0.0.1
    et l'IP réelle est dans l'en-tête CF-Connecting-IP (on ne lui fait confiance que dans ce cas)."""
    hote = request.client.host if request.client else ""
    if hote in ("127.0.0.1", "::1") and request.headers.get("cf-connecting-ip"):
        return request.headers["cf-connecting-ip"]
    return hote


def est_https(request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https" \
        or bool(request.headers.get("cf-connecting-ip"))
