"""« Source » d'enrichissement : complète les entreprises existantes (site, contact, description).

Lancée seulement à la demande (bouton « Trouver les sites web » dans Réglages), pas lors
d'une actualisation normale : elle visite des sites web et prend donc du temps.
Traite en priorité les cibles les mieux notées, jamais deux fois dans le mois.
"""

from app import db
from app.services import enrichissement
from app.sources.base import FetchContext, Source, SourceResult


class EnrichissementWebSource(Source):
    name = "enrichissement_web"
    label = "Enrichissement (sites web)"
    par_defaut = False  # exclue de l'actualisation normale

    def fetch(self, ctx: FetchContext) -> SourceResult:
        limite = int(ctx.parametres.get("enrichissement_max", 30))
        with db.get_conn() as conn:
            rows = conn.execute("""
                SELECT e.*, MAX(c.score) AS best FROM entreprises e JOIN cibles c ON c.entreprise_id = e.id
                WHERE c.statut NOT IN ('supprime', 'refuse')
                  AND (e.site_web IS NULL OR e.email_public IS NULL OR e.description_activite IS NULL)
                  AND e.nom NOT LIKE 'Employeur non communiqué%'
                  AND NOT EXISTS (SELECT 1 FROM provenances p WHERE p.entreprise_id = e.id
                                  AND p.source = 'enrichissement_web'
                                  AND p.fetched_at >= datetime('now', 'localtime', '-30 days'))
                GROUP BY e.id ORDER BY best DESC LIMIT ?""", (limite,)).fetchall()
        e = enrichissement.Enrichisseur()
        complete = 0
        try:
            for i, ent in enumerate(rows):
                ctx.progress(f"{ent['nom'][:40]} ({i + 1}/{len(rows)})", i / max(len(rows), 1))
                try:
                    trouve = e.enrichir(ent)
                except Exception:  # un site en erreur ne bloque pas les autres
                    trouve = {}
                with db.get_conn() as conn:
                    if enrichissement.appliquer(conn, ent["id"], trouve):
                        complete += 1
        finally:
            e.close()
        ctx.avertissements.append(f"{complete} entreprise(s) complétée(s) sur {len(rows)} analysée(s)")
        return SourceResult()
