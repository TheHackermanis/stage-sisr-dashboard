"""Source : API France Travail « Offres d'emploi v2 » (clé gratuite sur francetravail.io).

Recherche des offres informatiques (systèmes, réseaux, support, cybersécurité) autour de
la ville de départ, puis classement stage / alternance. Les CDI/CDD classiques sont ignorés
par défaut (réglage `ft_inclure_emplois`).
"""

import re

from app import config
from app.services.referentiels import normaliser
from app.sources.base import EntrepriseRecord, FetchContext, OffreRecord, Source, SourceResult
from app.sources.france_travail_auth import get_token
from app.sources.geocodage_adresse import code_insee

API_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
SCOPE = "api_offresdemploiv2 o2dsoffre"
PAGE = 150          # maximum autorisé par l'API
MAX_START = 3000    # l'API refuse les plages au-delà de 3149

# Codes ROME des métiers SISR (systèmes, réseaux, support, exploitation, télécoms)
ROME_SISR = ["M1801", "M1810", "M1802", "I1401", "M1804", "M1806"]
# Requêtes complémentaires par mots-clés (offres mal codées côté ROME)
MOTS_CLES = ["stage informatique", "technicien réseau", "administrateur système", "support informatique",
             "cybersécurité", "alternance informatique"]

RE_STAGE = re.compile(r"\b(stage|stagiaire|internship)\b")


def classer_contrat(offre: dict) -> str:
    """'stage', 'alternance' ou 'autre' à partir des champs de l'offre."""
    texte = normaliser(" ".join(str(offre.get(k) or "") for k in
                                ("intitule", "typeContratLibelle", "natureContrat", "description")))
    if offre.get("alternance") or re.search(r"\b(alternance|apprenti|apprentissage|professionnalisation)\b", texte):
        return "alternance"
    if RE_STAGE.search(normaliser(offre.get("intitule") or "")) or RE_STAGE.search(texte[:400]):
        return "stage"
    return "autre"


class FranceTravailOffresSource(Source):
    name = "france_travail_offres"
    label = "France Travail – offres"
    missing_config_message = "clés FT_CLIENT_ID / FT_CLIENT_SECRET absentes du fichier .env"

    def is_configured(self) -> bool:
        return config.france_travail_configured()

    def fetch(self, ctx: FetchContext) -> SourceResult:
        p = ctx.parametres
        ville = p["ville_depart"]
        insee = ville.get("code_insee") or code_insee(ctx.http, ville["nom"], ville.get("code_postal"))
        if not insee:
            raise RuntimeError(f"Code commune INSEE introuvable pour {ville['nom']}")
        distance = int(min(float(p["rayon_km"]), 100))  # l'API accepte jusqu'à 100 km (filtré à 50 ensuite)
        inclure_emplois = p.get("ft_inclure_emplois", False)

        token = get_token(ctx.http, SCOPE)
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

        requetes = [{"codeROME": ",".join(ROME_SISR)}] + [{"motsCles": m} for m in MOTS_CLES]
        brutes: dict[str, dict] = {}
        for i, extra in enumerate(requetes):
            ctx.progress(f"requête {i + 1}/{len(requetes)}", i / len(requetes))
            start = 0
            while start <= MAX_START:
                params = {"commune": insee, "distance": distance, "range": f"{start}-{start + PAGE - 1}",
                          "sort": 1, **extra}
                data = ctx.http.get_json(API_URL, params=params, headers=headers, ttl_heures=6,
                                         use_cache=ctx.use_cache, ok_statuses=(200, 206))
                resultats = (data or {}).get("resultats") or []
                for o in resultats:
                    brutes[o["id"]] = o
                if len(resultats) < PAGE:
                    break
                start += PAGE

        result = SourceResult()
        ignorees = 0
        for o in brutes.values():
            contrat = classer_contrat(o)
            if contrat == "autre" and not inclure_emplois:
                ignorees += 1
                continue
            # Les mots-clés génériques ramènent aussi des offres hors informatique : on filtre.
            if not self._est_informatique(o):
                ignorees += 1
                continue
            result.offres.append(self._to_record(o, contrat))
        # Toutes les offres actuelles ont été vues : celles absentes pourront être marquées expirées
        result.offres_complet = True
        if ignorees:
            ctx.avertissements.append(f"{ignorees} offre(s) CDI/CDD ou hors informatique ignorée(s)")
        ctx.progress("terminé", 1.0)
        return result

    @staticmethod
    def _est_informatique(o: dict) -> bool:
        if (o.get("romeCode") or "") in ROME_SISR:
            return True
        t = normaliser(f"{o.get('intitule', '')} {o.get('romeLibelle', '')} {(o.get('description') or '')[:600]}")
        return bool(re.search(r"informati|reseau|systeme|cyber|helpdesk|support|infrastructure|\bsi\b|\bit\b|"
                              r"telecom|sisr|tssr|devops|cloud", t))

    @staticmethod
    def _to_record(o: dict, contrat: str) -> OffreRecord:
        lieu = o.get("lieuTravail") or {}
        ent = o.get("entreprise") or {}
        nom_ent = (ent.get("nom") or "").strip()
        anonyme = not nom_ent
        if anonyme:  # nom unique : deux employeurs anonymes ne doivent pas être fusionnés
            nom_ent = f"Employeur non communiqué (offre {o['id']})"
        cp = lieu.get("codePostal")
        ville = re.sub(r"^\d+\s*-\s*", "", lieu.get("libelle") or "").strip().title() or None
        url = (o.get("origineOffre") or {}).get("urlOrigine") or \
            f"https://candidat.francetravail.fr/offres/recherche/detail/{o['id']}"
        e = EntrepriseRecord(
            nom=nom_ent, siret=None, secteur=o.get("secteurActiviteLibelle"),
            code_postal=cp, ville=ville, lat=lieu.get("latitude"), lon=lieu.get("longitude"),
            site_web=ent.get("url") or None,
            description_activite=ent.get("description"),
            tranche_effectif=None, raw={"source": "france_travail", "entreprise": ent, "anonyme": anonyme},
        )
        desc = o.get("description") or ""
        if o.get("competences"):
            desc += "\n\nCompétences : " + ", ".join(c.get("libelle", "") for c in o["competences"])
        return OffreRecord(
            source_ref=o["id"], titre=o.get("intitule") or "Offre", entreprise=e, description=desc,
            type_contrat=contrat, lieu=lieu.get("libelle"), lat=lieu.get("latitude"), lon=lieu.get("longitude"),
            url=url, date_publication=(o.get("dateCreation") or "")[:10] or None,
            raw={k: o.get(k) for k in ("id", "intitule", "typeContrat", "typeContratLibelle", "natureContrat",
                                        "alternance", "romeCode", "dateCreation", "dateActualisation",
                                        "salaire", "dureeTravailLibelle", "experienceLibelle")},
        )
