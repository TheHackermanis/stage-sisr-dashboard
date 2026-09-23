"""Configuration de l'application.

Deux niveaux :
- les secrets et réglages techniques viennent du fichier .env (jamais en dur dans le code) ;
- les réglages « métier » modifiables depuis l'interface (ville, rayon, NAF, mots-clés…)
  sont stockés en BDD dans la table `parametres`. Les valeurs par défaut sont ici.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Racine du projet (dossier qui contient app/, static/, data/)
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"

load_dotenv(BASE_DIR / ".env")

APP_VERSION = "0.1.0"

# Chemin de la BDD : surchargeable (utile pour les tests)
DB_PATH = Path(os.getenv("STAGE_DB_PATH", DATA_DIR / "stage.db"))

# Secrets France Travail (vides = source désactivée, l'app continue sans)
FT_CLIENT_ID = os.getenv("FT_CLIENT_ID", "").strip()
FT_CLIENT_SECRET = os.getenv("FT_CLIENT_SECRET", "").strip()
USER_AGENT_CONTACT = os.getenv("USER_AGENT_CONTACT", "").strip()


def france_travail_configured() -> bool:
    """Vrai si les identifiants France Travail sont renseignés dans .env."""
    return bool(FT_CLIENT_ID and FT_CLIENT_SECRET)


# Codes NAF « cœur SISR » (entreprises à cibler en candidature spontanée)
NAF_SISR = [
    "62.01Z", "62.02A", "62.02B", "62.03Z", "62.09Z",
    "63.11Z", "61.10Z", "61.20Z", "61.90Z", "95.11Z", "33.20D",
]

# Codes NAF des grosses structures susceptibles d'avoir une DSI interne.
# Filtrées en plus sur l'effectif (voir dsi_effectif_min).
NAF_DSI_INTERNE = [
    "84.11Z",  # administration publique générale (mairies, métropole, département…)
    "84.12Z",  # administration publique (santé, enseignement, culture…)
    "84.13Z",  # administration publique des activités économiques
    "84.22Z",  # défense
    "84.24Z",  # ordre public et sécurité
    "84.30A", "84.30B",  # sécurité sociale
    "86.10Z",  # activités hospitalières
    "85.31Z", "85.32Z",  # enseignement secondaire
    "85.42Z",  # enseignement supérieur
    "64.19Z",  # banques
    "65.11Z", "65.12Z",  # assurances
    "66.19B",  # auxiliaires de services financiers
    "30.11Z",  # construction navale
    "35.13Z", "35.14Z",  # distribution d'électricité
    "52.22Z",  # services auxiliaires des transports par eau (port)
]

# Paramètres par défaut (copiés en BDD au premier lancement, puis modifiables)
DEFAULT_PARAMETRES = {
    "ville_depart": {"nom": "Brest", "code_postal": "29200", "lat": 48.390394, "lon": -4.486076},
    # Rayon strict : tout ce qui est au-delà est exclu à l'import (demande explicite).
    "rayon_km": 50,
    "naf_sisr": NAF_SISR,
    "naf_dsi_interne": NAF_DSI_INTERNE,
    "dsi_effectif_min": 100,
    # Poids des mots-clés pour le score (points, négatif = malus)
    "mots_cles": {
        "active directory": 8, "windows server": 8, "linux": 6, "cisco": 6,
        "réseau": 6, "switch": 4, "routeur": 4, "vlan": 4, "pare-feu": 5, "firewall": 5,
        "vmware": 6, "proxmox": 6, "hyper-v": 5, "virtualisation": 5,
        "cybersécurité": 6, "sécurité": 3, "soc": 4,
        "support": 4, "helpdesk": 4, "n1": 3, "n2": 3,
        "cloud": 3, "azure": 3, "aws": 3, "office 365": 3, "microsoft 365": 3,
        "infrastructure": 5, "administrateur système": 8, "technicien": 4,
        "sauvegarde": 3, "supervision": 4, "glpi": 3,
        "développeur": -5, "react": -4, "java ": -3, "full stack": -4,
    },
    "delai_relance_jours": 7,
    "stage_debut": "2027-01-04",
    "stage_fin": "2027-02-26",
    "stage_duree_min_semaines": 7,
    "stage_duree_max_semaines": 8,
}
