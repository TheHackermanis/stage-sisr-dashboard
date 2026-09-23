"""Point d'entrée FastAPI : API JSON sous /api, interface web servie depuis static/."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import config, db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Au démarrage : création / mise à jour du schéma SQLite (idempotent).
    db.init_db()
    yield


app = FastAPI(title="Dashboard stage SISR", version=config.APP_VERSION, lifespan=lifespan)


@app.get("/api/health")
def health():
    """État de l'application et des sources (utile pour afficher les avertissements)."""
    with db.get_conn() as conn:
        nb_cibles = conn.execute("SELECT COUNT(*) FROM cibles").fetchone()[0]
        schema = conn.execute("PRAGMA user_version").fetchone()[0]
    return {
        "status": "ok",
        "version": config.APP_VERSION,
        "schema_version": schema,
        "nb_cibles": nb_cibles,
        "sources": {
            "recherche_entreprises": {"configuree": True},
            "api_adresse": {"configuree": True},
            "france_travail_offres": {
                "configuree": config.france_travail_configured(),
                "message": None if config.france_travail_configured()
                else "Clés FT_CLIENT_ID / FT_CLIENT_SECRET absentes du fichier .env",
            },
            "la_bonne_boite": {
                "configuree": config.france_travail_configured(),
                "message": None if config.france_travail_configured()
                else "Utilise les mêmes clés France Travail (absentes)",
            },
        },
    }


@app.get("/api/parametres")
def lire_parametres():
    with db.get_conn() as conn:
        return db.get_parametres(conn)


# Interface web : fichiers statiques + index.html à la racine.
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(config.STATIC_DIR / "index.html")
