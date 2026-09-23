"""Orchestration de l'actualisation des données.

Lancée en tâche de fond (thread) : l'interface interroge `etat()` chaque seconde
pour afficher la barre de progression puis le résumé final.
Chaque source est isolée : si l'une échoue ou n'est pas configurée, les autres continuent.
"""

import json
import threading
import traceback
from datetime import datetime

from app import db
from app.services import merge
from app.services.http_cache import CachedHttp
from app.sources import toutes_les_sources
from app.sources.base import FetchContext, SourceResult
from app.sources.geocodage_adresse import geocoder

# Délai minimal entre requêtes par hôte (quotas des API)
INTERVALLES = {
    "recherche-entreprises.api.gouv.fr": 0.16,   # 7 req/s max
    "api-adresse.data.gouv.fr": 0.05,            # 50 req/s max
    "api.francetravail.io": 0.35,                # ~3 req/s
    "entreprise.francetravail.fr": 0.5,
}


class RefreshManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._etat = self._etat_initial()

    @staticmethod
    def _etat_initial():
        return {"en_cours": False, "progression": 0.0, "etape": "", "debut": None, "fin": None,
                "sources": {}, "resume": None, "avertissements": []}

    def etat(self) -> dict:
        with self._lock:
            return json.loads(json.dumps(self._etat))

    def _maj(self, **kw):
        with self._lock:
            self._etat.update(kw)

    def lancer(self, sources: list[str] | None = None, force: bool = False) -> bool:
        """Démarre une actualisation en arrière-plan. Faux si une est déjà en cours."""
        with self._lock:
            if self._etat["en_cours"]:
                return False
            self._etat = self._etat_initial()
            self._etat.update(en_cours=True, debut=datetime.now().isoformat(timespec="seconds"),
                              etape="Démarrage…")
        self._thread = threading.Thread(target=self._run, args=(sources, force), daemon=True)
        self._thread.start()
        return True

    def attendre(self, timeout: float | None = None):
        if self._thread:
            self._thread.join(timeout)

    # ------------------------------------------------------------------
    def _run(self, noms: list[str] | None, force: bool):
        http = CachedHttp(INTERVALLES)
        resume = {"nouvelles_entreprises": 0, "nouvelles_dsi": 0, "nouvelles_offres": 0,
                  "entreprises_maj": 0, "offres_maj": 0, "exclues_distance": 0,
                  "offres_desactivees": 0, "requetes_http": 0, "reponses_cache": 0}
        avertissements: list[str] = []
        run_id = None
        try:
            with db.get_conn() as conn:
                run_id = conn.execute("INSERT INTO refresh_runs DEFAULT VALUES").lastrowid
                parametres = db.get_parametres(conn)

            # Sans liste explicite : toutes les sources « par défaut » (l'enrichissement web est à part)
            sources = [s for s in toutes_les_sources() if (s.name in noms if noms else s.par_defaut)]
            n = max(len(sources), 1)
            # 90 % de la barre pour les sources, 10 % pour le géocodage / score
            for i, src in enumerate(sources):
                base, part = 0.9 * i / n, 0.9 / n
                etat_src = {"label": src.label, "statut": "en_cours", "message": "", "nb": 0}
                self._set_source(src.name, etat_src)

                if not src.is_configured():
                    etat_src.update(statut="ignoree", message=src.missing_config_message or "non configurée")
                    self._set_source(src.name, etat_src)
                    continue

                def progress(msg, frac, _base=base, _part=part, _label=src.label):
                    self._maj(etape=f"{_label} : {msg}",
                              progression=round(_base + _part * max(0.0, min(1.0, frac)), 3))

                ctx = FetchContext(parametres=parametres, http=http, progress=progress, use_cache=not force)
                try:
                    result = src.fetch(ctx)
                    progress("enregistrement…", 0.99)
                    nb = self._integrer(src.name, result, parametres, http, resume)
                    etat_src.update(statut="ok", nb=nb, message="; ".join(ctx.avertissements))
                    avertissements += [f"{src.label} : {a}" for a in ctx.avertissements]
                except Exception as exc:  # une source en panne ne bloque pas les autres
                    traceback.print_exc()
                    etat_src.update(statut="erreur", message=f"{type(exc).__name__} : {exc}"[:300])
                    avertissements.append(f"{src.label} indisponible : {exc}"[:300])
                self._set_source(src.name, etat_src)

            self._maj(etape="Calcul des scores…", progression=0.95)
            with db.get_conn() as conn:
                from app.services.tracking import appliquer_relances_auto
                merge.recalculer_scores(conn, db.get_parametres(conn))
                appliquer_relances_auto(conn)

            resume["requetes_http"], resume["reponses_cache"] = http.nb_requetes, http.nb_cache
            resume["texte"] = self._texte_resume(resume)
        except Exception as exc:
            traceback.print_exc()
            avertissements.append(f"Erreur inattendue : {exc}")
        finally:
            http.close()
            fin = datetime.now().isoformat(timespec="seconds")
            with self._lock:
                sources_etat = dict(self._etat["sources"])
            if run_id:
                with db.get_conn() as conn:
                    conn.execute("UPDATE refresh_runs SET fin = datetime('now','localtime'), resume_json = ?, "
                                 "erreurs_json = ? WHERE id = ?",
                                 (json.dumps({**resume, "sources": sources_etat}, ensure_ascii=False),
                                  json.dumps(avertissements, ensure_ascii=False), run_id))
            self._maj(en_cours=False, progression=1.0, etape="Terminé", fin=fin, resume=resume,
                      avertissements=avertissements)

    def _set_source(self, name, etat_src):
        with self._lock:
            self._etat["sources"][name] = dict(etat_src)

    @staticmethod
    def _texte_resume(r: dict) -> str:
        morceaux = [f"{r['nouvelles_entreprises']} nouvelle(s) entreprise(s)",
                    f"{r['nouvelles_offres']} nouvelle(s) offre(s)"]
        if r["nouvelles_dsi"]:
            morceaux.insert(1, f"{r['nouvelles_dsi']} nouvelle(s) DSI interne(s)")
        if r["exclues_distance"]:
            morceaux.append(f"{r['exclues_distance']} hors rayon ignorée(s)")
        return ", ".join(morceaux)

    def _integrer(self, source: str, result: SourceResult, parametres: dict, http: CachedHttp,
                  resume: dict) -> int:
        """Écrit en BDD le résultat d'une source. Retourne le nombre d'éléments conservés."""
        nb = 0
        with db.get_conn() as conn:
            for rec in result.entreprises:
                if rec.lat is None or rec.lon is None:
                    coords = geocoder(http, rec.adresse, rec.code_postal, rec.ville)
                    if coords:
                        rec.lat, rec.lon = coords
                dist = merge.calculer_distance(parametres, rec.lat, rec.lon)
                if not merge.dans_rayon(parametres, dist):
                    resume["exclues_distance"] += 1
                    continue
                ent_id, cree = merge.upsert_entreprise(conn, rec, source, dist)
                if merge.assurer_cible_entreprise(conn, ent_id, rec.categorie):
                    resume["nouvelles_dsi" if rec.categorie == "dsi_interne" else "nouvelles_entreprises"] += 1
                elif not cree:
                    resume["entreprises_maj"] += 1
                nb += 1

            refs_vues = set()
            for off in result.offres:
                if off.lat is None or off.lon is None:
                    coords = geocoder(http, off.lieu, None, None)
                    if coords:
                        off.lat, off.lon = coords
                dist = merge.calculer_distance(parametres, off.lat, off.lon)
                refs_vues.add(off.source_ref)
                if not merge.dans_rayon(parametres, dist):
                    resume["exclues_distance"] += 1
                    continue
                e = off.entreprise
                if e.lat is None and e.adresse:
                    coords = geocoder(http, e.adresse, e.code_postal, e.ville)
                    if coords:
                        e.lat, e.lon = coords
                if e.lat is None:
                    e.lat, e.lon = off.lat, off.lon
                e_dist = merge.calculer_distance(parametres, e.lat, e.lon)
                ent_id, _ = merge.upsert_entreprise(conn, e, source, e_dist)
                _, cree = merge.upsert_offre(conn, off, source, ent_id, dist)
                resume["nouvelles_offres" if cree else "offres_maj"] += 1
                nb += 1
            if result.offres or result.offres_complet:
                resume["offres_desactivees"] += merge.desactiver_offres_absentes(conn, source, refs_vues)
        return nb


manager = RefreshManager()
