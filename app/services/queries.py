"""Lecture des cibles pour l'interface : liste filtrée, fiche détaillée, statistiques du dashboard."""

import json
import sqlite3
from datetime import date, datetime, timedelta

from app.services import referentiels as ref
from app.services.tracking import STATUTS

SELECT_CIBLES = """
    SELECT c.id, c.type, c.statut, c.favori, c.priorite, c.score, c.score_detail_json, c.technos_json,
           c.notes, c.date_envoi, c.entretien_at, c.vu_at, c.created_at, c.updated_at,
           c.statut_avant_suppression,
           e.id AS entreprise_id, e.nom, e.siret, e.naf, e.secteur, e.tranche_effectif, e.adresse,
           e.code_postal, e.ville, e.site_web, e.page_contact, e.page_recrutement, e.email_public,
           e.tel_public, e.description_activite, e.categorie, e.date_creation, e.saisie_manuelle,
           COALESCE(o.lat, e.lat) AS lat, COALESCE(o.lon, e.lon) AS lon,
           COALESCE(o.distance_km, e.distance_km) AS distance_km,
           o.id AS offre_id, o.titre, o.description AS offre_description, o.type_contrat, o.url AS offre_url,
           o.date_publication, o.active AS offre_active, o.source AS offre_source, o.lieu,
           (SELECT group_concat(DISTINCT p.source) FROM provenances p WHERE p.entreprise_id = e.id) AS sources,
           (SELECT max(p.fetched_at) FROM provenances p WHERE p.entreprise_id = e.id) AS fetched_at
    FROM cibles c
    JOIN entreprises e ON e.id = c.entreprise_id
    LEFT JOIN offres o ON o.id = c.offre_id
"""


def _row_to_dict(r: sqlite3.Row, complet: bool = False) -> dict:
    d = dict(r)
    d["technos"] = json.loads(d.pop("technos_json") or "[]")
    d["score_detail"] = json.loads(d.pop("score_detail_json") or "[]")
    d["favori"] = bool(d["favori"])
    d["taille"] = ref.taille_categorie(d["tranche_effectif"])
    d["taille_libelle"] = ref.tranche_libelle(d["tranche_effectif"])
    d["sources"] = sorted(set((d["sources"] or "").split(","))) if d["sources"] else []
    if d["saisie_manuelle"] and "manuel" not in d["sources"]:
        d["sources"].append("manuel")
    d["titre_affiche"] = d["titre"] or d["nom"]
    if not complet:
        # Liste allégée : pas de longues descriptions
        desc = d.pop("offre_description") or d.get("description_activite") or ""
        d["resume"] = desc[:200]
    return d


def lister_cibles(conn: sqlite3.Connection, f: dict | None = None) -> list[dict]:
    """Toutes les cibles correspondant aux filtres combinés.

    Filtres acceptés (tous optionnels) : statut[], type[], distance_max, taille[], secteur[],
    technos[] (toutes requises), score_min, favoris, q (texte libre), corbeille, priorite_min,
    tri (colonne), ordre ('asc'|'desc').
    """
    f = f or {}
    rows = [_row_to_dict(r) for r in conn.execute(SELECT_CIBLES).fetchall()]
    # Rayon strict : si le rayon a été réduit dans les réglages, ce qui est désormais hors zone
    # est masqué (sauf les saisies manuelles, ajoutées volontairement).
    row = conn.execute("SELECT valeur FROM parametres WHERE cle = 'rayon_km'").fetchone()
    rayon = float(json.loads(row[0])) if row else None

    corbeille = bool(f.get("corbeille"))
    out = []
    q = ref.normaliser(f.get("q") or "")
    mots = q.split() if q else []
    for d in rows:
        if corbeille != (d["statut"] == "supprime"):
            continue
        if rayon and not d["saisie_manuelle"] and d["distance_km"] is not None and d["distance_km"] > rayon:
            continue
        if f.get("statut") and d["statut"] not in f["statut"]:
            continue
        if f.get("type") and d["type"] not in f["type"]:
            continue
        if f.get("distance_max") not in (None, "") and (d["distance_km"] is None
                                                        or d["distance_km"] > float(f["distance_max"])):
            continue
        if f.get("taille") and d["taille"] not in f["taille"]:
            continue
        if f.get("secteur") and d["secteur"] not in f["secteur"]:
            continue
        if f.get("technos") and not set(f["technos"]) <= set(d["technos"]):
            continue
        if f.get("score_min") not in (None, "") and d["score"] < int(f["score_min"]):
            continue
        if f.get("priorite_min") not in (None, "") and d["priorite"] < int(f["priorite_min"]):
            continue
        if f.get("favoris") and not d["favori"]:
            continue
        if mots:
            texte = ref.normaliser(" ".join(str(d.get(k) or "") for k in (
                "nom", "ville", "secteur", "titre", "resume", "notes", "naf", "siret")) + " " +
                " ".join(d["technos"]))
            if not all(m in texte for m in mots):
                continue
        out.append(d)

    tri = f.get("tri") or "score"
    desc = (f.get("ordre") or ("asc" if tri in ("nom", "distance_km", "ville") else "desc")) == "desc"
    ordre_statut = list(STATUTS)

    def cle(d):
        v = d.get(tri)
        if tri == "statut":
            v = ordre_statut.index(d["statut"])
        if v is None:  # valeurs vides toujours en fin de liste
            return (1, "")
        return (0, v.lower() if isinstance(v, str) else v)

    vides = [d for d in out if cle(d)[0] == 1]
    pleins = sorted([d for d in out if cle(d)[0] == 0], key=cle, reverse=desc)
    return pleins + vides


def fiche(conn: sqlite3.Connection, cible_id: int) -> dict | None:
    r = conn.execute(SELECT_CIBLES + " WHERE c.id = ?", (cible_id,)).fetchone()
    if not r:
        return None
    d = _row_to_dict(r, complet=True)
    d["historique"] = [dict(h) for h in conn.execute(
        "SELECT ancien_statut, nouveau_statut, commentaire, created_at FROM historique "
        "WHERE cible_id = ? ORDER BY id DESC", (cible_id,))]
    # Autres cibles de la même entreprise (ex. offre + candidature spontanée)
    d["liees"] = [dict(x) for x in conn.execute(
        "SELECT c.id, c.type, c.statut, o.titre FROM cibles c LEFT JOIN offres o ON o.id = c.offre_id "
        "WHERE c.entreprise_id = ? AND c.id != ?", (d["entreprise_id"], cible_id))]
    return d


def options_filtres(conn: sqlite3.Connection) -> dict:
    """Valeurs disponibles pour les listes déroulantes de filtres."""
    secteurs = [r[0] for r in conn.execute(
        "SELECT DISTINCT e.secteur FROM cibles c JOIN entreprises e ON e.id = c.entreprise_id "
        "WHERE e.secteur IS NOT NULL ORDER BY 1")]
    technos: set[str] = set()
    for (t,) in conn.execute("SELECT technos_json FROM cibles"):
        technos.update(json.loads(t or "[]"))
    return {
        "statuts": [{"id": k, **v} for k, v in STATUTS.items()],
        "types": [{"id": "offre", "label": "Offre publiée"}, {"id": "spontanee", "label": "Candidature spontanée"},
                  {"id": "dsi_interne", "label": "DSI interne"}],
        "tailles": [{"id": k, "label": v} for k, v in [
            ("0", "0 salarié"), ("1-9", "1 à 9"), ("10-49", "10 à 49"), ("50-249", "50 à 249"),
            ("250+", "250 et plus"), ("inconnue", "Inconnue")]],
        "secteurs": secteurs,
        "technos": sorted(technos),
    }


def stats_dashboard(conn: sqlite3.Connection) -> dict:
    """Compteurs et données de la vue d'accueil."""
    compteurs = {k: 0 for k in STATUTS}
    for statut, n in conn.execute("SELECT statut, COUNT(*) FROM cibles GROUP BY statut"):
        compteurs[statut] = n
    par_type = {t: n for t, n in conn.execute(
        "SELECT type, COUNT(*) FROM cibles WHERE statut != 'supprime' GROUP BY type")}

    today = date.today()
    lundi = today - timedelta(days=today.weekday())
    # « Envoyées » = passages au statut envoyée dans l'historique (compte aussi les relances)
    envois = [r[0] for r in conn.execute(
        "SELECT created_at FROM historique WHERE nouveau_statut = 'envoyee' ORDER BY created_at")]
    envoyees_semaine = sum(1 for d in envois if d[:10] >= lundi.isoformat())

    a_relancer = [dict(r) for r in conn.execute(
        "SELECT c.id, e.nom, o.titre, c.date_envoi FROM cibles c JOIN entreprises e ON e.id = c.entreprise_id "
        "LEFT JOIN offres o ON o.id = c.offre_id WHERE c.statut = 'a_relancer' ORDER BY c.date_envoi")]
    maintenant = datetime.now().strftime("%Y-%m-%dT%H:%M")
    entretiens = [dict(r) for r in conn.execute(
        "SELECT c.id, e.nom, o.titre, c.entretien_at, e.ville FROM cibles c "
        "JOIN entreprises e ON e.id = c.entreprise_id LEFT JOIN offres o ON o.id = c.offre_id "
        "WHERE c.statut = 'entretien' AND c.entretien_at IS NOT NULL AND replace(c.entretien_at, ' ', 'T') >= ? "
        "ORDER BY c.entretien_at LIMIT 10", (maintenant[:10],))]

    # Progression : candidatures envoyées cumulées par jour (première fois par cible)
    premiers = [r[0][:10] for r in conn.execute(
        "SELECT min(created_at) FROM historique WHERE nouveau_statut = 'envoyee' GROUP BY cible_id ORDER BY 1")]
    progression, cumul = [], 0
    for jour in sorted(set(premiers)):
        cumul += premiers.count(jour)
        progression.append({"date": jour, "cumul": cumul})

    top = [dict(r) for r in conn.execute(
        "SELECT c.id, e.nom, o.titre, c.score, c.type, COALESCE(o.distance_km, e.distance_km) AS distance_km "
        "FROM cibles c JOIN entreprises e ON e.id = c.entreprise_id LEFT JOIN offres o ON o.id = c.offre_id "
        "WHERE c.statut = 'nouveau' AND (o.id IS NULL OR o.active = 1) ORDER BY c.score DESC LIMIT 8")]
    dernier = conn.execute("SELECT fin, resume_json FROM refresh_runs WHERE fin IS NOT NULL "
                           "ORDER BY id DESC LIMIT 1").fetchone()
    return {
        "compteurs": compteurs,
        "par_type": par_type,
        "total_actifs": sum(v for k, v in compteurs.items() if k != "supprime"),
        "envoyees_total": len(premiers),
        "envoyees_semaine": envoyees_semaine,
        "a_relancer": a_relancer,
        "entretiens": entretiens,
        "progression": progression,
        "top_nouveaux": top,
        "derniere_actualisation": dict(dernier) if dernier else None,
    }
