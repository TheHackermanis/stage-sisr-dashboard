"""Interface commune à toutes les sources de données.

Pour ajouter une source : créer un fichier dans app/sources/, hériter de `Source`,
implémenter `fetch()` et l'enregistrer dans la liste des sources (phase 1).
"""

from dataclasses import dataclass, field
from typing import Callable

# Callback de progression : (message, fraction entre 0 et 1)
ProgressCallback = Callable[[str, float], None]


@dataclass
class EntrepriseRecord:
    """Entreprise telle que renvoyée par une source, avant fusion en BDD."""
    nom: str
    siret: str | None = None
    siren: str | None = None
    naf: str | None = None
    secteur: str | None = None
    tranche_effectif: str | None = None
    date_creation: str | None = None
    adresse: str | None = None
    code_postal: str | None = None
    ville: str | None = None
    lat: float | None = None
    lon: float | None = None
    site_web: str | None = None
    email_public: str | None = None
    tel_public: str | None = None
    description_activite: str | None = None
    categorie: str = "standard"          # 'standard' ou 'dsi_interne'
    raw: dict = field(default_factory=dict)  # réponse brute, conservée dans `provenances`


@dataclass
class OffreRecord:
    """Offre publiée telle que renvoyée par une source."""
    source_ref: str
    titre: str
    entreprise: EntrepriseRecord
    description: str | None = None
    type_contrat: str = "autre"          # 'stage', 'alternance' ou 'autre'
    lieu: str | None = None
    lat: float | None = None
    lon: float | None = None
    url: str | None = None
    date_publication: str | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class SourceResult:
    entreprises: list[EntrepriseRecord] = field(default_factory=list)
    offres: list[OffreRecord] = field(default_factory=list)


class SourceNotConfigured(Exception):
    """Levée quand une clé API manque : la source est ignorée, les autres continuent."""


class Source:
    name: str = "source"            # identifiant technique, stocké en BDD
    label: str = "Source"           # nom affiché dans l'interface

    def is_configured(self) -> bool:
        """Faux si une clé API nécessaire est absente."""
        return True

    def fetch(self, parametres: dict, progress: ProgressCallback) -> SourceResult:
        raise NotImplementedError
