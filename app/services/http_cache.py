"""Client HTTP commun à toutes les sources.

- Cache des réponses JSON/texte en BDD (table http_cache) avec durée de validité :
  on ne relance pas toutes les requêtes à chaque actualisation.
- Délai minimal entre deux requêtes vers un même hôte (respect des quotas des API).
- Nouvelles tentatives automatiques sur 429 / 5xx / erreur réseau.
"""

import hashlib
import json
import threading
import time
from urllib.parse import urlencode, urlparse

import httpx

from app import config, db

DEFAULT_UA = f"StageSISR-Dashboard/{config.APP_VERSION} (usage personnel, recherche de stage)"


class HttpError(Exception):
    """Erreur HTTP définitive (après les nouvelles tentatives)."""


class CachedHttp:
    def __init__(self, min_interval: dict[str, float] | None = None, timeout: float = 20.0):
        # Délai minimal (s) entre deux requêtes par nom d'hôte ; 0.2 s par défaut.
        self.min_interval = min_interval or {}
        self._last_call: dict[str, float] = {}
        self._lock = threading.Lock()
        ua = DEFAULT_UA + (f" contact: {config.USER_AGENT_CONTACT}" if config.USER_AGENT_CONTACT else "")
        self.client = httpx.Client(timeout=timeout, headers={"User-Agent": ua}, follow_redirects=True)
        self.nb_requetes = 0
        self.nb_cache = 0

    # --- cache -----------------------------------------------------------
    @staticmethod
    def _key(method: str, url: str, params: dict | None, body: str | None) -> tuple[str, str]:
        full = url + ("?" + urlencode(sorted((params or {}).items())) if params else "")
        raw = f"{method} {full} {body or ''}"
        return hashlib.sha256(raw.encode()).hexdigest(), full

    def _cache_get(self, key: str, ttl_heures: float):
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT reponse FROM http_cache WHERE cle_hash = ? "
                "AND fetched_at >= datetime('now', 'localtime', ?)",
                (key, f"-{int(ttl_heures * 60)} minutes"),
            ).fetchone()
        return row["reponse"] if row else None

    def _cache_set(self, key: str, url: str, text: str, ttl_heures: float):
        with db.get_conn() as conn:
            conn.execute(
                "INSERT INTO http_cache (cle_hash, url, reponse, ttl_heures, fetched_at) "
                "VALUES (?, ?, ?, ?, datetime('now', 'localtime')) "
                "ON CONFLICT(cle_hash) DO UPDATE SET reponse = excluded.reponse, "
                "fetched_at = excluded.fetched_at, ttl_heures = excluded.ttl_heures",
                (key, url, text, int(ttl_heures)),
            )

    # --- limitation de débit ---------------------------------------------
    def _throttle(self, url: str):
        host = urlparse(url).hostname or ""
        interval = self.min_interval.get(host, 0.2)
        with self._lock:
            wait = self._last_call.get(host, 0) + interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_call[host] = time.monotonic()

    # --- requêtes --------------------------------------------------------
    def request_text(self, method: str, url: str, *, params=None, data=None, headers=None,
                     ttl_heures: float = 24, use_cache: bool = True, retries: int = 3,
                     ok_statuses=(200,)) -> tuple[int, str]:
        """Renvoie (code HTTP, texte). Les réponses en `ok_statuses` sont mises en cache."""
        body = urlencode(data) if isinstance(data, dict) else data
        key, full = self._key(method, url, params, body)
        if use_cache and ttl_heures > 0:
            cached = self._cache_get(key, ttl_heures)
            if cached is not None:
                self.nb_cache += 1
                return 200, cached

        last_exc: Exception | None = None
        for attempt in range(retries):
            self._throttle(url)
            try:
                self.nb_requetes += 1
                r = self.client.request(method, url, params=params, data=data, headers=headers)
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt < retries - 1:  # pas d'attente inutile après la dernière tentative
                    time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code == 429 or r.status_code >= 500:
                # Quota dépassé ou serveur en difficulté : on attend puis on réessaie.
                retry_after = r.headers.get("Retry-After", "")
                if attempt < retries - 1:
                    time.sleep(min(float(retry_after), 30) if retry_after.isdigit() else 2.0 * (attempt + 1))
                last_exc = HttpError(f"HTTP {r.status_code} sur {urlparse(url).hostname}")
                continue
            if r.status_code in ok_statuses and use_cache and ttl_heures > 0:
                self._cache_set(key, full, r.text, ttl_heures)
            return r.status_code, r.text
        raise HttpError(f"Échec après {retries} tentatives : {last_exc}")

    def get_json(self, url: str, params=None, *, headers=None, ttl_heures: float = 24,
                 use_cache: bool = True, ok_statuses=(200,)):
        status, text = self.request_text("GET", url, params=params, headers=headers,
                                         ttl_heures=ttl_heures, use_cache=use_cache,
                                         ok_statuses=ok_statuses)
        if status == 204 or not text.strip():
            return None
        if status not in ok_statuses:
            raise HttpError(f"HTTP {status} : {text[:200]}")
        return json.loads(text)

    def close(self):
        self.client.close()
