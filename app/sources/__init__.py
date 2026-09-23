"""Registre des sources. Pour en ajouter une : créer le fichier puis l'ajouter à `toutes_les_sources`."""

from app.sources.base import Source


def toutes_les_sources() -> list[Source]:
    # Imports ici pour qu'une source cassée n'empêche pas l'app de démarrer.
    from app.sources.recherche_entreprises import RechercheEntreprisesSource
    sources: list[Source] = [RechercheEntreprisesSource()]
    try:
        from app.sources.france_travail_offres import FranceTravailOffresSource
        sources.append(FranceTravailOffresSource())
    except ImportError:
        pass
    try:
        from app.sources.la_bonne_boite import LaBonneBoiteSource
        sources.append(LaBonneBoiteSource())
    except ImportError:
        pass
    from app.sources.enrichissement_web import EnrichissementWebSource
    sources.append(EnrichissementWebSource())
    return sources
