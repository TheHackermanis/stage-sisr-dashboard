"""Point d'entrée FastAPI : API JSON sous /api, interface web servie depuis static/."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import config, db
from app.services import queries, refresh, tracking


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Au démarrage : création / mise à jour du schéma SQLite (idempotent),
    # puis passage en « À relancer » des candidatures sans réponse.
    db.init_db()
    with db.get_conn() as conn:
        tracking.appliquer_relances_auto(conn)
    yield


app = FastAPI(title="Dashboard stage SISR", version=config.APP_VERSION, lifespan=lifespan)


@app.exception_handler(tracking.SuiviError)
async def suivi_error_handler(request: Request, exc: tracking.SuiviError):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# ---------------------------------------------------------------- santé
@app.get("/api/health")
def health():
    """État de l'application et des sources (utile pour afficher les avertissements)."""
    with db.get_conn() as conn:
        nb_cibles = conn.execute("SELECT COUNT(*) FROM cibles").fetchone()[0]
        schema = conn.execute("PRAGMA user_version").fetchone()[0]
    ft = config.france_travail_configured()
    return {
        "status": "ok",
        "version": config.APP_VERSION,
        "schema_version": schema,
        "nb_cibles": nb_cibles,
        "sources": {
            "recherche_entreprises": {"configuree": True},
            "api_adresse": {"configuree": True},
            "france_travail_offres": {
                "configuree": ft,
                "message": None if ft else "Clés FT_CLIENT_ID / FT_CLIENT_SECRET absentes du fichier .env",
            },
            "la_bonne_boite": {
                "configuree": ft,
                "message": None if ft else "Utilise les mêmes clés France Travail (absentes)",
            },
        },
    }


# ---------------------------------------------------------- actualisation
class RefreshRequest(BaseModel):
    sources: list[str] | None = None   # None = toutes
    force: bool = False                # True = ignorer le cache HTTP


@app.post("/api/refresh")
def lancer_refresh(req: RefreshRequest | None = None):
    req = req or RefreshRequest()
    if not refresh.manager.lancer(req.sources, req.force):
        raise HTTPException(409, "Une actualisation est déjà en cours")
    return refresh.manager.etat()


@app.get("/api/refresh/status")
def statut_refresh():
    return refresh.manager.etat()


# ------------------------------------------------------------- cibles
LIST_FILTERS = ("statut", "type", "taille", "secteur", "technos")


def filtres_depuis_requete(request: Request) -> dict:
    """Convertit la query string (?statut=vu&statut=retenu&score_min=40…) en dict de filtres."""
    qp = request.query_params
    f: dict = {k: qp.getlist(k) for k in LIST_FILTERS if qp.getlist(k)}
    for k in ("distance_max", "score_min", "priorite_min", "q", "tri", "ordre"):
        if qp.get(k) not in (None, ""):
            f[k] = qp.get(k)
    for k in ("favoris", "corbeille"):
        f[k] = qp.get(k) in ("1", "true", "on")
    return f


@app.get("/api/cibles")
def liste_cibles(request: Request):
    with db.get_conn() as conn:
        return queries.lister_cibles(conn, filtres_depuis_requete(request))


@app.get("/api/cibles/{cible_id}")
def detail_cible(cible_id: int, marquer_vu: bool = False):
    with db.get_conn() as conn:
        if marquer_vu:
            tracking.marquer_vu(conn, cible_id)  # Nouveau -> Vu à l'ouverture de la fiche
        d = queries.fiche(conn, cible_id)
    if not d:
        raise HTTPException(404, "Cible introuvable")
    return d


class SuiviUpdate(BaseModel):
    favori: bool | None = None
    priorite: int | None = None
    notes: str | None = None
    entretien_at: str | None = None
    date_envoi: str | None = None


@app.patch("/api/cibles/{cible_id}")
def maj_cible(cible_id: int, body: SuiviUpdate):
    with db.get_conn() as conn:
        tracking.maj_suivi(conn, cible_id, **body.model_dump())
        return queries.fiche(conn, cible_id)


class StatutUpdate(BaseModel):
    statut: str
    commentaire: str | None = None
    entretien_at: str | None = None


@app.post("/api/cibles/{cible_id}/statut")
def statut_cible(cible_id: int, body: StatutUpdate):
    with db.get_conn() as conn:
        tracking.changer_statut(conn, cible_id, body.statut, commentaire=body.commentaire,
                                entretien_at=body.entretien_at)
        return queries.fiche(conn, cible_id)


class StatutLot(BaseModel):
    ids: list[int]
    statut: str


@app.post("/api/lot/statut")
def statut_lot(body: StatutLot):
    with db.get_conn() as conn:
        n = tracking.changer_statut_lot(conn, body.ids, body.statut)
    return {"modifiees": n}


@app.post("/api/cibles/{cible_id}/restaurer")
def restaurer_cible(cible_id: int):
    with db.get_conn() as conn:
        tracking.restaurer(conn, cible_id)
        return queries.fiche(conn, cible_id)


# ---------------------------------------------------------- dashboard
@app.get("/api/dashboard")
def dashboard():
    with db.get_conn() as conn:
        tracking.appliquer_relances_auto(conn)
        return queries.stats_dashboard(conn)


@app.get("/api/filtres")
def options_filtres():
    with db.get_conn() as conn:
        return queries.options_filtres(conn)


# ---------------------------------------------------------- paramètres
@app.get("/api/parametres")
def lire_parametres():
    with db.get_conn() as conn:
        return db.get_parametres(conn)


# Interface web : fichiers statiques + index.html à la racine.
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(config.STATIC_DIR / "index.html")
