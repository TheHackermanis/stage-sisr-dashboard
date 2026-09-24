# 🖧 Dashboard stage BTS SIO SISR — Brest

Application web **locale** pour trouver, trier et suivre les entreprises susceptibles
d'accueillir un stage SISR (7 à 8 semaines à partir du 4 janvier 2027),
**à Brest ou dans un rayon de 50 km maximum** :

- les **offres publiées** (stages et alternances, France Travail) ;
- les entreprises où envoyer une **candidature spontanée** (ESN, infogérance, télécoms, maintenance…) ;
- les grosses structures avec un **service informatique interne** (CHU, collectivités, défense, banques…).

Tout tourne sur ta machine : une base SQLite (`data/stage.db`), un serveur FastAPI, une interface web.

---

## Sommaire
1. [Installation et lancement](#1-installation-et-lancement)
2. [Obtenir les clés France Travail](#2-obtenir-les-clés-france-travail-gratuit)
3. [Utilisation](#3-utilisation)
4. [Sources de données et règles respectées](#4-sources-de-données-et-règles-respectées)
5. [Le score de pertinence](#5-le-score-de-pertinence)
6. [Sauvegarde, tests, dépannage](#6-sauvegarde-tests-dépannage)
7. [Structure du code / ajouter une source](#7-structure-du-code--ajouter-une-source)

---

## 1. Installation et lancement

### Prérequis
- **Python 3.10 ou plus récent** : `python3 --version`
  - macOS : `brew install python` (ou l'installeur de python.org)
  - Debian/Ubuntu : `sudo apt install python3 python3-venv`
- `curl` (présent par défaut sur macOS et la plupart des Linux)
- Une connexion Internet pour l'actualisation des données et le fond de carte.

### Lancement (une seule commande)
```bash
cd stage-dashboard
./start.sh
```
Au premier lancement, le script :
1. crée un environnement Python isolé (`.venv/`) ;
2. installe les dépendances (`requirements.txt`) ;
3. crée le fichier `.env` à partir de `.env.example` ;
4. démarre le serveur et ouvre **http://127.0.0.1:8000** dans ton navigateur.

Les lancements suivants sont instantanés. `Ctrl+C` pour arrêter.

Options :
```bash
NO_BROWSER=1 ./start.sh     # ne pas ouvrir le navigateur
```
Le port se change dans `.env` (`PORT=8000`).

### Premier usage
Clique sur **🔄 Actualiser les données**. En une minute environ, l'application récupère
les entreprises autour de Brest (≈ 280 cibles avec les réglages par défaut).
Sans clés France Travail, seules les offres sont absentes. Tout le reste fonctionne.

---

## 2. Obtenir les clés France Travail (gratuit)

Les offres d'emploi et La Bonne Boîte passent par l'API de France Travail (ex-Pôle emploi).
L'accès est gratuit mais demande un compte « développeur ».

1. Va sur **https://francetravail.io** et crée un compte (bouton de connexion en haut à droite,
   puis création de compte). Valide ton email.
2. Dans ton espace, crée une **application** (nom au choix, ex. « Dashboard stage »).
3. Dans le catalogue des API, **ajoute à ton application** :
   - **« Offres d'emploi v2 »** (offres de stage et d'alternance) ;
   - **« La Bonne Boîte »** (entreprises qui recrutent, pour les candidatures spontanées).
   Selon l'API, l'accès est immédiat ou soumis à une courte validation.
4. Récupère l'**identifiant client** et la **clé secrète** de l'application.
5. Ouvre le fichier `.env` à la racine du projet et remplis :
   ```ini
   FT_CLIENT_ID=ton_identifiant_client
   FT_CLIENT_SECRET=ta_cle_secrete
   ```
6. Redémarre l'application (`Ctrl+C` puis `./start.sh`) et relance une actualisation.

> 🔒 Le fichier `.env` est dans `.gitignore` : tes clés ne sont jamais versionnées ni écrites dans le code.
> Si une clé est fausse ou qu'une API n'est pas ajoutée à ton application, un message clair
> s'affiche après l'actualisation et les autres sources continuent de fonctionner.

`USER_AGENT_CONTACT` (optionnel) : ton email, ajouté à l'en-tête des requêtes quand
l'application visite des sites d'entreprises (bonne pratique).

---

## 3. Utilisation

| Vue | Ce qu'on y fait |
|---|---|
| **🏠 Accueil** | Compteurs par statut, candidatures envoyées cette semaine, relances à faire, prochains entretiens, graphique de progression, meilleures cibles pas encore vues. Clic sur un compteur = tableau filtré. |
| **📋 Tableau** | Tri par colonne, filtres combinables (statut, type, distance, taille, secteur, technos, score min, priorité, favoris), recherche plein texte sans accents, **sélection multiple** pour changer le statut de plusieurs lignes, **export CSV / Excel** de la liste filtrée. |
| **🗂️ Kanban** | Une colonne par statut, **glisser-déposer** une carte pour changer son statut. |
| **🗺️ Carte** | Marqueurs colorés selon le statut, cercle du rayon autour de Brest, clic = fiche. |
| **🗑️ Corbeille** | Les éléments « supprimés » : masqués partout, jamais effacés, restaurables avec leur statut précédent. |
| **⚙️ Réglages** | Ville de départ, rayon, dates de stage, délai de relance, codes NAF, mots-clés du score, profil et modèle de mail, état des sources, recherche de doublons, recherche des sites web. |

### La fiche détaillée (clic sur n'importe quelle ligne, carte ou marqueur)
- boutons de statut en un clic, favori ⭐, priorité 1 à 5 étoiles ;
- **notes libres** enregistrées automatiquement pendant la frappe ;
- liens cliquables (offre, site, page recrutement/contact, fiche officielle Annuaire des entreprises) ;
- **✨ Trouver site / contact** : cherche le site web, la description et les pages contact/recrutement ;
- **✏️ Modifier** : corriger ou compléter les infos (ces valeurs ne seront plus écrasées) ;
- **✉️ Modèle de mail** : candidature spontanée pré-remplie, à copier en un clic ;
- historique horodaté de tous les changements de statut.

### Le suivi, automatiquement
- 🆕 → 👁️ : une cible passe de **Nouveau** à **Vu** quand tu ouvres sa fiche.
- 📨 : passer en **Candidature envoyée** enregistre la date d'envoi.
- 🔔 : sans réponse après **7 jours** (réglable), la candidature passe en **À relancer**.
  Repasser en « Envoyée » après la relance relance le compteur.
- 🗓️ : **Entretien prévu** demande la date et l'heure, qui apparaissent sur l'accueil.
- ➕ **Ajouter** (en haut) : saisir une entreprise ou une offre trouvée ailleurs (salon, bouche-à-oreille, site d'école…).
- Une actualisation **ne touche jamais** à tes statuts, notes, favoris, priorités ni à ce que tu as modifié à la main.

---

## 3 bis. Mettre le dashboard en ligne (accès depuis n'importe quel appareil)

Le dashboard continue de tourner **sur ton Mac** : un **tunnel Cloudflare** le rend accessible en HTTPS sur un
sous-domaine (ex. `https://stage.gcosta.fr`), sans ouvrir de port sur ta box. Il est protégé par **mot de passe**.

**Une seule fois :**
```bash
./set_password.sh                         # choisis le mot de passe (12 caractères min.)
brew install cloudflared
cloudflared tunnel login                  # autorise ton domaine dans le navigateur
./setup_tunnel.sh stage.gcosta.fr         # crée le tunnel + l'enregistrement DNS
```
**Ensuite, à chaque fois :**
```bash
./online.sh                               # lance l'app + le tunnel (Ctrl+C pour arrêter)
```

Sécurité :
- sans mot de passe défini, `online.sh` **refuse** de publier le dashboard ;
- seule l'**empreinte** du mot de passe (scrypt) est stockée dans `.env`, jamais le mot de passe ;
- session par cookie signé (HttpOnly, Secure, SameSite=Strict, 30 jours), bouton 🔒 Déconnexion ;
- 5 essais ratés = blocage de l'adresse IP pendant 15 minutes ;
- changer le mot de passe (`./set_password.sh` puis redémarrer) **déconnecte tous les appareils** ;
- l'application n'écoute que sur `127.0.0.1` : seul le tunnel peut l'atteindre de l'extérieur.

**Démarrage automatique** : plus besoin de lancer quoi que ce soit, l'application et le tunnel
démarrent à l'ouverture de session (ou au boot) et redémarrent seuls en cas d'arrêt.

macOS (LaunchAgents) :
```bash
./autostart_install.sh      # installer (à relancer après une mise à jour du code)
./autostart_uninstall.sh    # désinstaller
```
Journaux : `~/Library/Logs/stage-sisr/app.log` et `tunnel.log`.

Linux (systemd --user, ex. Raspberry Pi / Compute Module) :
```bash
sudo loginctl enable-linger $USER    # une fois : les services tournent même sans session ouverte
./autostart_install_linux.sh         # installer (à relancer après un git pull)
./autostart_uninstall_linux.sh       # désinstaller
```
Journaux : `journalctl --user -u stage-sisr-app -u stage-sisr-tunnel -f`.

Limites : le dashboard n'est accessible que **quand ton Mac est allumé et pas en veille**. Pour qu'il reste
joignable écran éteint : Réglages Système → Batterie → Options → « Empêcher la suspension automatique
sur l'adaptateur secteur lorsque l'écran est éteint ».
Pour une double protection, tu peux ajouter **Cloudflare Access** (gratuit) devant le sous-domaine :
Cloudflare Zero Trust → Access → Applications → ajoute `stage.gcosta.fr` avec un code envoyé à ton email.

---

## 4. Sources de données et règles respectées

| Source | Clé | Rôle |
|---|---|---|
| [API Recherche d'entreprises](https://recherche-entreprises.api.gouv.fr) | aucune | Établissements actifs dans le rayon, par code NAF SISR (62.01Z, 62.02A/B, 62.03Z, 62.09Z, 63.11Z, 61.10Z/20Z/90Z, 95.11Z, 33.20D) + grosses structures « DSI interne » (≥ 100 salariés, réglable). |
| [France Travail – Offres d'emploi v2](https://francetravail.io) | oui (gratuite) | Offres de stage et d'alternance en informatique (systèmes, réseaux, support, cybersécurité). Les CDI/CDD sont ignorés par défaut. Une offre retirée est marquée « expirée », pas supprimée. |
| [La Bonne Boîte](https://francetravail.io) | oui (même application) | Entreprises à fort potentiel d'embauche dans les métiers IT (bonus de score). |
| [API Adresse](https://adresse.data.gouv.fr) | aucune | Géocodage des adresses manquantes, code commune. |
| [OpenStreetMap / Overpass](https://overpass-api.de) | aucune | Site web des établissements (enrichissement). |
| Sites des entreprises | — | Enrichissement **à la demande** : page d'accueil + page contact uniquement. |

**Règles respectées** :
- API officielles et gratuites en priorité, avec quotas (délai entre requêtes) et **cache** (les réponses
  sont réutilisées 6 h à 3 jours selon la source, « Actualiser sans cache » dans les réglages pour forcer).
- **Pas de scraping de LinkedIn, Indeed, Welcome to the Jungle** ni d'aucun moteur de recherche (interdit par leurs CGU).
  Le bouton « 🔍 Rechercher » de la fiche ouvre simplement une recherche dans ton navigateur.
- Sites d'entreprises : `robots.txt` respecté, 1 requête/s max par site, User-Agent identifiable.
- **RGPD** : seuls les emails et téléphones **génériques** (contact@, rh@, recrutement@, standard…) sont conservés,
  jamais d'adresse nominative. Les noms de dirigeants renvoyés par l'annuaire ne sont pas utilisés.
- Rayon **strict** : tout ce qui est au-delà (50 km par défaut) est ignoré à l'import. Si tu réduis le rayon,
  ce qui sort de la zone est masqué (sauf tes saisies manuelles).
- Les auto-entrepreneurs / sociétés **sans salarié** sont ignorés par défaut (pas d'encadrement possible). Réglable.

---

## 5. Le score de pertinence

Score sur 100, avec son détail au **survol** du badge :

| Critère | Points | Détail |
|---|---|---|
| Pertinence | 40 max | Mots-clés pondérés trouvés dans l'offre ou la description (AD, Windows Server, Linux, Cisco, VMware/Proxmox, cybersécurité, support N1/N2… ; malus pour « développeur », « React »…) + points selon le code NAF (ex. 62.03Z infogérance = 18). |
| Distance | 25 max | 25 pts à moins de 5 km, puis décroissance linéaire jusqu'au bord du rayon. |
| Type | 20 max | Offre de stage 20 · candidature spontanée 15 · DSI interne 12 · alternance 8. |
| Taille / fraîcheur | 15 max | Taille compatible avec un encadrement, offre de moins de 30 jours, fort potentiel La Bonne Boîte. |

Mots-clés, points NAF et rayon se modifient dans **Réglages** ; les scores sont recalculés immédiatement.

---

## 6. Sauvegarde, tests, dépannage

**Sauvegarde** : toutes tes données sont dans un seul fichier, `data/stage.db`. Copie-le pour le sauvegarder
(de préférence application arrêtée). Pour repartir de zéro, supprime-le.

**Tests** :
```bash
.venv/bin/python -m pytest -q
```
Les tests utilisent une base temporaire et des réponses d'API simulées : ils ne touchent ni ta base ni Internet.

**Dépannage**
| Problème | Solution |
|---|---|
| `permission denied: ./start.sh` | `chmod +x start.sh` |
| `Address already in use` | L'app tourne déjà, ou change `PORT` dans `.env`. |
| « France Travail ignorée : clés absentes » | Voir [section 2](#2-obtenir-les-clés-france-travail-gratuit). |
| « Authentification refusée » | Identifiant/clé mal copiés, ou l'API n'est pas ajoutée à ton application francetravail.io. |
| Carte grise sans fond | Pas d'Internet : les tuiles OpenStreetMap ne se chargent pas (le reste marche hors ligne). |
| Une entreprise en double | Réglages → Doublons potentiels → Fusionner (le suivi et les notes sont conservés). |
| Réinstaller les dépendances | `rm -rf .venv && ./start.sh` |

---

## 7. Structure du code / ajouter une source

```
stage-dashboard/
├── start.sh                  lancement en une commande
├── requirements.txt          dépendances Python
├── .env.example              modèle du fichier de clés
├── app/
│   ├── main.py               routes FastAPI (API JSON + interface)
│   ├── config.py             lecture du .env, réglages par défaut
│   ├── db.py                 schéma SQLite, migrations, paramètres
│   ├── services/
│   │   ├── refresh.py        actualisation en tâche de fond + progression
│   │   ├── merge.py          fusion en BDD (dédoublonnage, rayon, suivi préservé)
│   │   ├── doublons.py       détection de doublons (SIRET, nom + ville approchants)
│   │   ├── scoring.py        score /100 et explication
│   │   ├── technos.py        détection des technos
│   │   ├── tracking.py       statuts, historique, relances, corbeille
│   │   ├── queries.py        listes filtrées, fiche, statistiques
│   │   ├── gestion.py        saisie manuelle, édition, réglages, fusion, modèle de mail
│   │   ├── enrichissement.py site web / contact / description
│   │   ├── export.py         CSV et Excel
│   │   └── http_cache.py     client HTTP avec cache, quotas, nouvelles tentatives
│   └── sources/              UNE SOURCE PAR FICHIER
│       ├── base.py           interface commune (Source, EntrepriseRecord, OffreRecord)
│       ├── recherche_entreprises.py
│       ├── france_travail_offres.py  (+ france_travail_auth.py)
│       ├── la_bonne_boite.py
│       ├── geocodage_adresse.py
│       └── enrichissement_web.py
├── static/                   interface (Vue 3, Leaflet, Chart.js, SortableJS copiés en local)
├── data/stage.db             ta base (non versionnée)
└── tests/                    tests pytest, un fichier par phase
```

### Ajouter une nouvelle source
1. Crée `app/sources/ma_source.py` :
   ```python
   from app.sources.base import EntrepriseRecord, OffreRecord, FetchContext, Source, SourceResult

   class MaSource(Source):
       name = "ma_source"            # identifiant stocké en base
       label = "Ma source"           # nom affiché

       def is_configured(self):      # False si une clé manque -> source ignorée proprement
           return True

       def fetch(self, ctx: FetchContext) -> SourceResult:
           data = ctx.http.get_json("https://…", params={…})   # cache + quotas inclus
           ctx.progress("page 1", 0.5)                          # barre de progression
           return SourceResult(entreprises=[EntrepriseRecord(nom=…, siret=…, lat=…, lon=…)],
                               offres=[OffreRecord(source_ref=…, titre=…, entreprise=…)])
   ```
2. Ajoute-la dans `toutes_les_sources()` (`app/sources/__init__.py`).

La fusion, le rayon, les doublons, le score et le suivi s'appliquent automatiquement.
