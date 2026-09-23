# Dashboard stage BTS SIO SISR — Brest

Application web locale pour trouver, trier et suivre les entreprises susceptibles
d'accueillir un stage SISR (7 à 8 semaines à partir du 4 janvier 2027),
**à Brest ou dans un rayon de 50 km maximum**.

> Projet en cours de développement par phases. Ce README sera complété à la fin
> (obtention des clés API pas à pas, captures, etc.).

## Prérequis
- Python 3.10 ou plus récent (`python3 --version`)
- Linux ou macOS, `curl`

## Lancement
```bash
./start.sh
```
Le script crée l'environnement virtuel, installe les dépendances, crée `.env`
à partir de `.env.example` puis ouvre http://127.0.0.1:8000.
Pour ne pas ouvrir le navigateur : `NO_BROWSER=1 ./start.sh`.

## Clés API
Copier `.env.example` en `.env` (fait automatiquement par `start.sh`) et renseigner
`FT_CLIENT_ID` / `FT_CLIENT_SECRET` (France Travail). Sans clé, l'application
fonctionne avec les autres sources.

## Tests
```bash
.venv/bin/python -m pytest -q
```

## Structure
```
app/            backend FastAPI (config, BDD, services, sources)
app/sources/    une source de données par fichier (interface dans base.py)
static/         interface web (HTML/CSS/JS, bibliothèques en local)
data/           base SQLite (non versionnée)
tests/          tests pytest (BDD temporaire, la vraie base n'est jamais touchée)
```
