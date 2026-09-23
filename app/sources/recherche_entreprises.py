"""Source : API Recherche d'entreprises (recherche-entreprises.api.gouv.fr), sans clé.

On utilise l'endpoint /near_point qui renvoie les unités légales ayant au moins un
établissement actif dans un rayon donné, avec la liste `matching_etablissements`.
Chaque établissement local devient une entreprise en BDD (clé = SIRET de l'établissement,
c'est lui qui peut accueillir un stagiaire à Brest, pas le siège parisien).

Deux passes :
1. codes NAF « cœur SISR » -> candidatures spontanées ;
2. codes NAF de grosses structures (collectivités, hôpitaux, défense…) avec un effectif
   minimum -> catégorie « DSI interne ».
Quota de l'API : 7 requêtes/s -> on espace les appels de 0,2 s.
"""

from app.services import referentiels as ref
from app.sources.base import EntrepriseRecord, FetchContext, Source, SourceResult

API_URL = "https://recherche-entreprises.api.gouv.fr/near_point"
PER_PAGE = 25
MAX_RADIUS_API = 50  # limite imposée par l'API /near_point


def _float(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


class RechercheEntreprisesSource(Source):
    name = "recherche_entreprises"
    label = "Annuaire des entreprises (API gouv)"

    def fetch(self, ctx: FetchContext) -> SourceResult:
        p = ctx.parametres
        ville = p["ville_depart"]
        rayon = min(float(p["rayon_km"]), MAX_RADIUS_API)
        if float(p["rayon_km"]) > MAX_RADIUS_API:
            ctx.avertissements.append(f"Rayon limité à {MAX_RADIUS_API} km par l'API Recherche d'entreprises")

        passes = [(naf, "standard") for naf in p["naf_sisr"]]
        passes += [(naf, "dsi_interne") for naf in p["naf_dsi_interne"]]
        exclure_sans_salarie = p.get("exclure_sans_salarie", True)
        dsi_min = int(p.get("dsi_effectif_min", 100))

        result = SourceResult()
        vus: set[str] = set()
        stats = {"sans_salarie": 0, "dsi_trop_petites": 0}

        for i, (naf, categorie) in enumerate(passes):
            ctx.progress(f"Entreprises NAF {naf} ({i + 1}/{len(passes)})", i / len(passes))
            page, total_pages = 1, 1
            while page <= total_pages:
                data = ctx.http.get_json(API_URL, params={
                    "lat": ville["lat"], "long": ville["lon"], "radius": rayon,
                    "activite_principale": naf, "per_page": PER_PAGE, "page": page,
                }, ttl_heures=72, use_cache=ctx.use_cache) or {}
                total_pages = min(int(data.get("total_pages") or 1), 400)
                for ul in data.get("results", []):
                    for etab in ul.get("matching_etablissements") or []:
                        rec = self._to_record(ul, etab, categorie)
                        if rec is None or rec.siret in vus:
                            continue
                        tranche = etab.get("tranche_effectif_salarie")
                        mini = ref.effectif_min(tranche)
                        if categorie == "dsi_interne" and (mini is None or mini < dsi_min):
                            stats["dsi_trop_petites"] += 1
                            continue
                        # Auto-entrepreneurs / sociétés sans salarié : impossible d'être encadré.
                        if (exclure_sans_salarie and categorie == "standard"
                                and (mini is None or mini == 0) and etab.get("caractere_employeur") != "O"):
                            stats["sans_salarie"] += 1
                            continue
                        vus.add(rec.siret)
                        result.entreprises.append(rec)
                page += 1
        ctx.progress("Annuaire des entreprises terminé", 1.0)
        if stats["sans_salarie"]:
            ctx.avertissements.append(
                f"{stats['sans_salarie']} établissements sans salarié ignorés (réglage « exclure sans salarié »)")
        return result

    @staticmethod
    def _nom(ul: dict, etab: dict) -> str:
        """Enseigne locale + raison sociale entre parenthèses si elles diffèrent."""
        raison = ul.get("nom_raison_sociale") or ul.get("nom_complet") or "?"
        enseignes = etab.get("liste_enseignes") or []
        enseigne = etab.get("nom_commercial") or (enseignes[0] if enseignes else None)
        if enseigne and ref.normaliser(enseigne) != ref.normaliser(raison) \
                and ref.normaliser(enseigne) not in ref.normaliser(raison):
            return f"{enseigne} ({raison})"
        return raison

    @staticmethod
    def _to_record(ul: dict, etab: dict, categorie: str) -> EntrepriseRecord | None:
        if etab.get("etat_administratif") != "A" or not etab.get("siret"):
            return None
        naf = etab.get("activite_principale") or ul.get("activite_principale")
        nom = RechercheEntreprisesSource._nom(ul, etab)
        return EntrepriseRecord(
            nom=nom.strip(),
            siret=etab["siret"],
            siren=ul.get("siren"),
            naf=naf,
            secteur=ref.secteur_depuis_naf(naf, ul.get("section_activite_principale")),
            tranche_effectif=etab.get("tranche_effectif_salarie"),
            date_creation=etab.get("date_creation") or ul.get("date_creation"),
            adresse=etab.get("adresse"),
            code_postal=etab.get("code_postal"),
            ville=(etab.get("libelle_commune") or "").title() or None,
            lat=_float(etab.get("latitude")),
            lon=_float(etab.get("longitude")),
            categorie=categorie,
            raw={"siren": ul.get("siren"), "nom_complet": ul.get("nom_complet"),
                 "categorie_entreprise": ul.get("categorie_entreprise"),
                 "etablissement": etab},
        )
