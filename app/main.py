"""Point d'entrée FastAPI : API JSON sous /api, interface web servie depuis static/."""

from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import auth, config, db
from app.services import doublons as doublons_srv
from app.services import enrichissement, export, gestion, queries, refresh, tracking


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Au démarrage : création / mise à jour du schéma SQLite (idempotent),
    # puis passage en « À relancer » des candidatures sans réponse.
    if auth.actif() and len(config.SECRET_KEY) < 32:
        raise RuntimeError("SECRET_KEY absente ou trop courte dans .env : relance ./set_password.sh")
    db.init_db()
    with db.get_conn() as conn:
        tracking.appliquer_relances_auto(conn)
    yield


app = FastAPI(title="Dashboard stage SISR", version=config.APP_VERSION, lifespan=lifespan,
              # Documentation interactive de l'API désactivée quand le dashboard est protégé
              docs_url=None if auth.actif() else "/docs", redoc_url=None,
              openapi_url=None if auth.actif() else "/openapi.json")


@app.middleware("http")
async def exiger_connexion(request: Request, call_next):
    """Toutes les pages et l'API exigent une session valide (sauf la page de connexion)."""
    if auth.actif() and not request.url.path.startswith(auth.PUBLICS) \
            and not auth.session_valide(request.cookies.get(auth.COOKIE)):
        if request.url.path.startswith("/api/"):
            return JSONResponse(status_code=401, content={"detail": "Connexion requise"})
        return RedirectResponse("/login", status_code=303)
    response = await call_next(request)
    # En-têtes de sécurité de base
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


# ---------------------------------------------------------------- connexion
class Login(BaseModel):
    mot_de_passe: str


@app.get("/login", include_in_schema=False)
def page_login(request: Request):
    if not auth.actif() or auth.session_valide(request.cookies.get(auth.COOKIE)):
        return RedirectResponse("/", status_code=303)
    return FileResponse(config.STATIC_DIR / "login.html")


@app.post("/api/login")
def login(body: Login, request: Request):
    if not auth.actif():
        return {"ok": True}
    ip = auth.ip_client(request)
    if auth.bloque(ip):
        raise HTTPException(429, "Trop de tentatives. Réessaie dans 15 minutes.")
    if not auth.verifier(body.mot_de_passe, config.APP_PASSWORD_HASH):
        auth.noter_echec(ip)
        raise HTTPException(401, "Mot de passe incorrect")
    auth.reinitialiser(ip)
    resp = JSONResponse({"ok": True})
    resp.set_cookie(auth.COOKIE, auth.creer_session(), max_age=auth.DUREE_SESSION, httponly=True,
                    samesite="strict", secure=auth.est_https(request), path="/")
    return resp


@app.post("/api/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp


@app.exception_handler(tracking.SuiviError)
async def suivi_error_handler(request: Request, exc: tracking.SuiviError):
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
        "auth": auth.actif(),
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


# ---------------------------------------------------------- export
@app.get("/api/export")
def exporter(request: Request, format: str = "csv"):
    """Export de la liste filtrée (mêmes filtres que /api/cibles)."""
    with db.get_conn() as conn:
        rows = queries.lister_cibles(conn, filtres_depuis_requete(request))
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    if format == "xlsx":
        return Response(export.to_xlsx(rows),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="stages-sisr-{stamp}.xlsx"'})
    return Response(export.to_csv(rows), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="stages-sisr-{stamp}.csv"'})


# ---------------------------------------------------------- saisie manuelle / édition
@app.post("/api/manuel")
def ajout_manuel(data: dict):
    with db.get_conn() as conn:
        cid = gestion.ajouter_manuel(conn, data)
        return queries.fiche(conn, cid)


@app.patch("/api/entreprises/{ent_id}")
def modifier_entreprise(ent_id: int, data: dict):
    with db.get_conn() as conn:
        gestion.modifier_entreprise(conn, ent_id, data)
    return {"ok": True}


@app.post("/api/entreprises/{ent_id}/enrichir")
def enrichir_entreprise(ent_id: int):
    """Cherche site web / contact / description pour une entreprise (quelques secondes)."""
    try:
        return enrichissement.enrichir_une(ent_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@app.get("/api/cibles/{cible_id}/mail")
def mail_cible(cible_id: int):
    with db.get_conn() as conn:
        return gestion.modele_mail(conn, cible_id)


# ---------------------------------------------------------- doublons
@app.get("/api/doublons")
def doublons():
    with db.get_conn() as conn:
        return doublons_srv.lister_doublons_potentiels(conn)


class Fusion(BaseModel):
    garder_id: int
    fusion_id: int


@app.post("/api/doublons/fusionner")
def fusionner(body: Fusion):
    with db.get_conn() as conn:
        gestion.fusionner_entreprises(conn, body.garder_id, body.fusion_id)
    return {"ok": True}


# ---------------------------------------------------------- paramètres
@app.get("/api/parametres")
def lire_parametres():
    with db.get_conn() as conn:
        return db.get_parametres(conn)


@app.put("/api/parametres")
def ecrire_parametres(data: dict):
    with db.get_conn() as conn:
        return gestion.maj_parametres(conn, data)


@app.post("/api/parametres/reinitialiser")
def reinitialiser_parametres(cles: list[str]):
    """Remet les clés indiquées à leur valeur par défaut."""
    with db.get_conn() as conn:
        return gestion.maj_parametres(conn, {k: config.DEFAULT_PARAMETRES[k] for k in cles
                                             if k in config.DEFAULT_PARAMETRES})


# Interface web : fichiers statiques + index.html à la racine.
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(config.STATIC_DIR / "index.html")
