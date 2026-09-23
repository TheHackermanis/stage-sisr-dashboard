"""Géocodage via l'API Adresse (api-adresse.data.gouv.fr), sans clé.

Ce n'est pas une source d'entreprises : c'est un service utilisé par l'orchestrateur
pour compléter les coordonnées GPS manquantes (offres, saisies manuelles, etc.).
"""

from app.services.http_cache import CachedHttp, HttpError

API_URL = "https://api-adresse.data.gouv.fr/search/"


def geocoder(http: CachedHttp, adresse: str | None, code_postal: str | None = None,
             ville: str | None = None) -> tuple[float, float] | None:
    """Renvoie (lat, lon) ou None si l'adresse est introuvable ou l'API indisponible."""
    q = " ".join(x for x in (adresse, code_postal if adresse and code_postal and code_postal not in adresse else None,
                             ville if not adresse else None) if x)
    if not q or len(q) < 3:
        return None
    params = {"q": q[:200], "limit": 1}
    if code_postal:
        params["postcode"] = code_postal
    try:
        data = http.get_json(API_URL, params=params, ttl_heures=24 * 30)
    except (HttpError, ValueError):
        return None
    feats = (data or {}).get("features") or []
    if not feats and "postcode" in params:
        # Réessayer sans contrainte de code postal (codes CEDEX, etc.)
        params.pop("postcode")
        try:
            feats = (http.get_json(API_URL, params=params, ttl_heures=24 * 30) or {}).get("features") or []
        except (HttpError, ValueError):
            return None
    if not feats or feats[0]["properties"].get("score", 0) < 0.4:
        return None
    lon, lat = feats[0]["geometry"]["coordinates"]
    return lat, lon
