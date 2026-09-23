"""Source : API La Bonne Boîte v2 (France Travail, même application que les offres).

Renvoie les établissements qui ont statistiquement de fortes chances d'embaucher dans
les métiers visés : de bonnes cibles pour une candidature spontanée.
Il faut ajouter l'API « La Bonne Boîte » à son application sur francetravail.io.
"""

from app import config
from app.services import referentiels as ref
from app.sources.base import EntrepriseRecord, FetchContext, Source, SourceResult
from app.sources.france_travail_auth import get_token
from app.sources.france_travail_offres import ROME_SISR

API_URL = "https://api.francetravail.io/partenaire/labonneboite/v2/recherche"
SCOPE = "api_labonneboitev2"
PAGE_SIZE = 100


def _tranche_depuis_effectif(mini) -> str | None:
    """Convertit un effectif minimum en code de tranche INSEE (approximation)."""
    try:
        n = int(mini)
    except (TypeError, ValueError):
        return None
    for code, (_, borne) in sorted(ref.TRANCHES.items(), key=lambda x: -(x[1][1] or 0)):
        if code not in ("NN", "00") and borne is not None and n >= borne:
            return code
    return "00"


class LaBonneBoiteSource(Source):
    name = "la_bonne_boite"
    label = "La Bonne Boîte"
    missing_config_message = "clés France Travail absentes du fichier .env"

    def is_configured(self) -> bool:
        return config.france_travail_configured()

    def fetch(self, ctx: FetchContext) -> SourceResult:
        p = ctx.parametres
        ville = p["ville_depart"]
        token = get_token(ctx.http, SCOPE)
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        result = SourceResult()
        vus = set()
        for i, rome in enumerate(ROME_SISR):
            ctx.progress(f"métier {rome} ({i + 1}/{len(ROME_SISR)})", i / len(ROME_SISR))
            page = 1
            while page <= 10:
                data = ctx.http.get_json(API_URL, params={
                    "rome": rome, "latitude": ville["lat"], "longitude": ville["lon"],
                    "distance": int(min(float(p["rayon_km"]), 100)), "page": page, "page_size": PAGE_SIZE,
                }, headers=headers, ttl_heures=72, use_cache=ctx.use_cache) or {}
                items = data.get("items") or data.get("results") or data.get("companies") or []
                for it in items:
                    rec = self._to_record(it, rome)
                    if rec and rec.siret not in vus:
                        vus.add(rec.siret)
                        result.entreprises.append(rec)
                total = data.get("hits") or data.get("total") or 0
                if len(items) < PAGE_SIZE or page * PAGE_SIZE >= int(total or 0):
                    break
                page += 1
        ctx.progress("terminé", 1.0)
        return result

    @staticmethod
    def _to_record(it: dict, rome: str) -> EntrepriseRecord | None:
        siret = str(it.get("siret") or "").strip()
        if not siret:
            return None
        loc = it.get("location") or {}
        naf = it.get("naf")
        if naf and len(naf) == 5 and "." not in naf:  # « 6202A » -> « 62.02A »
            naf = f"{naf[:2]}.{naf[2:]}"
        return EntrepriseRecord(
            nom=(it.get("office_name") or it.get("company_name") or it.get("name") or "?").strip(),
            siret=siret, naf=naf,
            secteur=it.get("naf_label") or ref.secteur_depuis_naf(naf),
            tranche_effectif=_tranche_depuis_effectif(it.get("headcount_min")),
            code_postal=it.get("postcode") or it.get("zipcode"),
            ville=(it.get("city") or "").title() or None,
            lat=loc.get("lat") or it.get("lat") or it.get("latitude"),
            lon=loc.get("lon") or it.get("lon") or it.get("longitude"),
            site_web=it.get("website") or it.get("url") or None,
            email_public=it.get("email") or None,
            tel_public=it.get("phone") or None,
            categorie="standard",
            raw={"hiring_potential": it.get("hiring_potential"), "is_high_potential": it.get("is_high_potential"),
                 "rome": rome, "naf_label": it.get("naf_label")},
        )
