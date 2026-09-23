"""Authentification OAuth2 France Travail (client credentials), partagée par les sources FT.

Un jeton par « scope » : si La Bonne Boîte n'est pas activée sur l'application
francetravail.io, les offres d'emploi fonctionnent quand même (et inversement).
"""

import json
import threading
import time

from app import config
from app.services.http_cache import CachedHttp, HttpError

TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token"

_cache: dict[str, tuple[str, float]] = {}
_lock = threading.Lock()


class FranceTravailAuthError(Exception):
    pass


def get_token(http: CachedHttp, scope: str) -> str:
    """Renvoie un jeton valide pour le scope demandé (mis en cache jusqu'à expiration)."""
    with _lock:
        tok = _cache.get(scope)
        if tok and tok[1] > time.time() + 30:
            return tok[0]
    try:
        status, text = http.request_text(
            "POST", TOKEN_URL, params={"realm": "/partenaire"},
            data={"grant_type": "client_credentials", "client_id": config.FT_CLIENT_ID,
                  "client_secret": config.FT_CLIENT_SECRET, "scope": scope},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            use_cache=False, retries=2, ok_statuses=(200,))
    except HttpError as exc:
        raise FranceTravailAuthError(f"Serveur d'authentification France Travail injoignable ({exc})") from exc
    if status != 200:
        detail = ""
        try:
            detail = json.loads(text).get("error_description") or json.loads(text).get("error") or ""
        except ValueError:
            pass
        if status in (400, 401):
            raise FranceTravailAuthError(
                f"Authentification refusée ({detail or status}). Vérifie FT_CLIENT_ID / FT_CLIENT_SECRET "
                f"et que l'API ({scope.split()[0]}) est bien ajoutée à ton application sur francetravail.io")
        raise FranceTravailAuthError(f"Authentification France Travail : HTTP {status} {detail}")
    data = json.loads(text)
    with _lock:
        _cache[scope] = (data["access_token"], time.time() + int(data.get("expires_in", 1400)))
    return data["access_token"]
