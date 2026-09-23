"""Libellés des codes NAF et des tranches d'effectif INSEE, et normalisation de texte."""

import math
import re
import unicodedata

NAF_LIBELLES = {
    "62.01Z": "Programmation informatique",
    "62.02A": "Conseil en systèmes et logiciels informatiques",
    "62.02B": "Tierce maintenance de systèmes et d'applications",
    "62.03Z": "Gestion d'installations informatiques",
    "62.09Z": "Autres activités informatiques",
    "63.11Z": "Traitement de données, hébergement",
    "61.10Z": "Télécommunications filaires",
    "61.20Z": "Télécommunications sans fil",
    "61.90Z": "Autres activités de télécommunication",
    "95.11Z": "Réparation d'ordinateurs et d'équipements périphériques",
    "33.20D": "Installation d'équipements électriques, électroniques, optiques",
    "84.11Z": "Administration publique générale",
    "84.12Z": "Administration publique (santé, enseignement, culture…)",
    "84.13Z": "Administration publique des activités économiques",
    "84.22Z": "Défense",
    "84.24Z": "Ordre public et sécurité",
    "84.30A": "Sécurité sociale (régime général)",
    "84.30B": "Sécurité sociale (autres régimes)",
    "86.10Z": "Activités hospitalières",
    "85.31Z": "Enseignement secondaire général",
    "85.32Z": "Enseignement secondaire technique ou professionnel",
    "85.42Z": "Enseignement supérieur",
    "64.19Z": "Banque",
    "65.11Z": "Assurance vie",
    "65.12Z": "Autres assurances",
    "66.19B": "Auxiliaires de services financiers",
    "30.11Z": "Construction navale",
    "35.13Z": "Distribution d'électricité",
    "35.14Z": "Commerce d'électricité",
    "52.22Z": "Services auxiliaires des transports par eau",
}

SECTIONS = {
    "A": "Agriculture", "B": "Industries extractives", "C": "Industrie manufacturière",
    "D": "Énergie", "E": "Eau, déchets", "F": "Construction", "G": "Commerce",
    "H": "Transports", "I": "Hébergement, restauration", "J": "Information et communication",
    "K": "Finance, assurance", "L": "Immobilier", "M": "Activités spécialisées, scientifiques",
    "N": "Services administratifs", "O": "Administration publique", "P": "Enseignement",
    "Q": "Santé, action sociale", "R": "Arts, spectacles", "S": "Autres services",
}

# Tranches d'effectif INSEE -> (libellé, effectif minimum)
TRANCHES = {
    "NN": ("Non employeur", 0), "00": ("0 salarié", 0),
    "01": ("1-2 salariés", 1), "02": ("3-5 salariés", 3), "03": ("6-9 salariés", 6),
    "11": ("10-19 salariés", 10), "12": ("20-49 salariés", 20),
    "21": ("50-99 salariés", 50), "22": ("100-199 salariés", 100),
    "31": ("200-249 salariés", 200), "32": ("250-499 salariés", 250),
    "41": ("500-999 salariés", 500), "42": ("1000-1999 salariés", 1000),
    "51": ("2000-4999 salariés", 2000), "52": ("5000-9999 salariés", 5000),
    "53": ("10000+ salariés", 10000),
}

# Regroupement simple pour les filtres de l'interface
def taille_categorie(tranche: str | None) -> str:
    mini = TRANCHES.get(tranche or "", (None, None))[1]
    if mini is None:
        return "inconnue"
    if mini == 0:
        return "0"
    if mini < 10:
        return "1-9"
    if mini < 50:
        return "10-49"
    if mini < 250:
        return "50-249"
    return "250+"


def tranche_libelle(tranche: str | None) -> str:
    return TRANCHES.get(tranche or "", ("Effectif inconnu", None))[0]


def effectif_min(tranche: str | None) -> int | None:
    return TRANCHES.get(tranche or "", (None, None))[1]


def secteur_depuis_naf(naf: str | None, section: str | None = None) -> str | None:
    if naf and naf in NAF_LIBELLES:
        return NAF_LIBELLES[naf]
    if section and section in SECTIONS:
        return SECTIONS[section]
    return None


def normaliser(texte: str | None) -> str:
    """Minuscules, sans accents ni ponctuation, espaces simples. Sert au dédoublonnage."""
    if not texte:
        return ""
    t = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    # formes juridiques inutiles pour comparer des noms
    t = re.sub(r"\b(sas|sasu|sarl|eurl|sa|sci|scop|snc|ei|eirl)\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def distance_km(lat1, lon1, lat2, lon2) -> float | None:
    """Distance à vol d'oiseau (formule de haversine)."""
    if None in (lat1, lon1, lat2, lon2):
        return None
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)), 1)
