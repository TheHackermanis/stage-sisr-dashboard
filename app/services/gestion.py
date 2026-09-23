"""Actions de gestion : saisie manuelle, édition d'une entreprise, réglages, fusion de doublons, modèle de mail."""

import json
import sqlite3
import uuid
from datetime import date

from app import config, db
from app.services import merge
from app.services import referentiels as ref
from app.services.http_cache import CachedHttp
from app.services.tracking import SuiviError, maintenant
from app.sources.base import EntrepriseRecord, OffreRecord
from app.sources.geocodage_adresse import geocoder

CHAMPS_EDITABLES = ["nom", "siret", "naf", "secteur", "adresse", "code_postal", "ville", "site_web",
                    "page_contact", "page_recrutement", "email_public", "tel_public", "description_activite",
                    "tranche_effectif"]


def _geocoder(adresse, code_postal, ville):
    http = CachedHttp()
    try:
        return geocoder(http, adresse, code_postal, ville)
    finally:
        http.close()


def ajouter_manuel(conn: sqlite3.Connection, data: dict) -> int:
    """Ajoute une entreprise (et éventuellement une offre) trouvée ailleurs. Retourne l'id de la cible."""
    nom = (data.get("nom") or "").strip()
    if not nom:
        raise SuiviError("Le nom de l'entreprise est obligatoire")
    parametres = db.get_parametres(conn)
    lat, lon = data.get("lat"), data.get("lon")
    if lat is None and (data.get("adresse") or data.get("ville")):
        coords = _geocoder(data.get("adresse"), data.get("code_postal"), data.get("ville"))
        if coords:
            lat, lon = coords
    dist = merge.calculer_distance(parametres, lat, lon)
    type_cible = data.get("type") or "spontanee"
    rec = EntrepriseRecord(
        nom=nom, siret=(data.get("siret") or "").replace(" ", "") or None, naf=data.get("naf") or None,
        secteur=data.get("secteur") or ref.secteur_depuis_naf(data.get("naf")),
        adresse=data.get("adresse") or None, code_postal=data.get("code_postal") or None,
        ville=data.get("ville") or None, lat=lat, lon=lon, site_web=data.get("site_web") or None,
        email_public=data.get("email_public") or None, tel_public=data.get("tel_public") or None,
        description_activite=data.get("description_activite") or None,
        categorie="dsi_interne" if type_cible == "dsi_interne" else "standard",
        raw={"saisie": "manuelle"},
    )
    ent_id, cree = merge.upsert_entreprise(conn, rec, "manuel", dist)
    if cree:
        conn.execute("UPDATE entreprises SET saisie_manuelle = 1 WHERE id = ?", (ent_id,))
    for champ in ("page_contact", "page_recrutement"):
        if data.get(champ):
            conn.execute(f"UPDATE entreprises SET {champ} = ? WHERE id = ?", (data[champ], ent_id))

    if type_cible == "offre":
        titre = (data.get("titre") or "").strip() or f"Offre chez {nom}"
        off = OffreRecord(source_ref=f"manuel-{uuid.uuid4().hex[:12]}", titre=titre, entreprise=rec,
                          description=data.get("description") or None,
                          type_contrat=data.get("type_contrat") or "stage", lieu=data.get("ville"),
                          lat=lat, lon=lon, url=data.get("url") or None,
                          date_publication=data.get("date_publication") or date.today().isoformat(),
                          raw={"saisie": "manuelle"})
        off_id, _ = merge.upsert_offre(conn, off, "manuel", ent_id, dist)
        cible_id = conn.execute("SELECT id FROM cibles WHERE offre_id = ?", (off_id,)).fetchone()[0]
    else:
        merge.assurer_cible_entreprise(conn, ent_id, rec.categorie)
        cible_id = conn.execute("SELECT id FROM cibles WHERE entreprise_id = ? AND offre_id IS NULL",
                                (ent_id,)).fetchone()[0]
    if data.get("notes"):
        conn.execute("UPDATE cibles SET notes = ? WHERE id = ?", (data["notes"], cible_id))
    merge.recalculer_scores(conn, parametres, [cible_id])
    return cible_id


def modifier_entreprise(conn: sqlite3.Connection, ent_id: int, data: dict) -> None:
    """Édition manuelle des infos d'une entreprise (ces valeurs ne seront plus écrasées)."""
    row = conn.execute("SELECT * FROM entreprises WHERE id = ?", (ent_id,)).fetchone()
    if not row:
        raise SuiviError("Entreprise introuvable")
    sets = {k: (v.strip() if isinstance(v, str) else v) or None for k, v in data.items() if k in CHAMPS_EDITABLES}
    if not sets:
        return
    if "nom" in sets:
        if not sets["nom"]:
            raise SuiviError("Le nom ne peut pas être vide")
        sets["nom_normalise"] = ref.normaliser(sets["nom"])
    adresse_changee = any(k in sets and sets[k] != row[k] for k in ("adresse", "code_postal", "ville"))
    if adresse_changee:
        coords = _geocoder(sets.get("adresse", row["adresse"]), sets.get("code_postal", row["code_postal"]),
                           sets.get("ville", row["ville"]))
        if coords:
            sets["lat"], sets["lon"] = coords
            sets["distance_km"] = merge.calculer_distance(db.get_parametres(conn), *coords)
    sets["saisie_manuelle"] = 1
    sets["updated_at"] = maintenant()
    conn.execute(f"UPDATE entreprises SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?",
                 list(sets.values()) + [ent_id])
    ids = [r[0] for r in conn.execute("SELECT id FROM cibles WHERE entreprise_id = ?", (ent_id,))]
    merge.recalculer_scores(conn, db.get_parametres(conn), ids)


def maj_parametres(conn: sqlite3.Connection, data: dict) -> dict:
    """Enregistre les réglages modifiés puis recalcule distances et scores."""
    inconnus = set(data) - set(config.DEFAULT_PARAMETRES)
    if inconnus:
        raise SuiviError(f"Paramètres inconnus : {', '.join(sorted(inconnus))}")
    anciens = db.get_parametres(conn)
    if "rayon_km" in data:
        r = float(data["rayon_km"])
        if not 1 <= r <= 200:
            raise SuiviError("Le rayon doit être compris entre 1 et 200 km")
    if "delai_relance_jours" in data and not 1 <= int(data["delai_relance_jours"]) <= 90:
        raise SuiviError("Le délai de relance doit être compris entre 1 et 90 jours")

    ville = data.get("ville_depart")
    if ville and (ville.get("nom") != anciens["ville_depart"].get("nom") or ville.get("lat") is None):
        coords = _geocoder(None, ville.get("code_postal"), ville.get("nom"))
        if not coords:
            raise SuiviError(f"Ville introuvable : {ville.get('nom')}")
        ville["lat"], ville["lon"] = coords
        data["ville_depart"] = ville

    for k, v in data.items():
        db.set_parametre(conn, k, v)
    p = db.get_parametres(conn)
    if "ville_depart" in data:
        recalculer_distances(conn, p)
    merge.recalculer_scores(conn, p)
    return p


def recalculer_distances(conn: sqlite3.Connection, p: dict) -> None:
    for table in ("entreprises", "offres"):
        rows = conn.execute(f"SELECT id, lat, lon FROM {table}").fetchall()
        conn.executemany(f"UPDATE {table} SET distance_km = ? WHERE id = ?",
                         [(merge.calculer_distance(p, r["lat"], r["lon"]), r["id"]) for r in rows])


def fusionner_entreprises(conn: sqlite3.Connection, garder_id: int, fusion_id: int) -> None:
    """Fusionne deux fiches entreprise en double : tout est rattaché à `garder_id`.

    Le suivi n'est pas perdu : notes concaténées, historique conservé, statut le plus avancé gardé.
    """
    if garder_id == fusion_id:
        raise SuiviError("Impossible de fusionner une entreprise avec elle-même")
    g = conn.execute("SELECT * FROM entreprises WHERE id = ?", (garder_id,)).fetchone()
    f = conn.execute("SELECT * FROM entreprises WHERE id = ?", (fusion_id,)).fetchone()
    if not g or not f:
        raise SuiviError("Entreprise introuvable")
    # Compléter les champs vides de celle qu'on garde
    for c in CHAMPS_EDITABLES + ["lat", "lon", "distance_km", "siren", "date_creation"]:
        if not g[c] and f[c]:
            conn.execute(f"UPDATE entreprises SET {c} = ? WHERE id = ?", (f[c], garder_id))

    cg = conn.execute("SELECT * FROM cibles WHERE entreprise_id = ? AND offre_id IS NULL", (garder_id,)).fetchone()
    cf = conn.execute("SELECT * FROM cibles WHERE entreprise_id = ? AND offre_id IS NULL", (fusion_id,)).fetchone()
    if cg and cf:
        ordre = ["nouveau", "vu", "retenu", "envoyee", "a_relancer", "entretien", "refuse", "accepte"]
        meilleur = cf if (cf["statut"] in ordre and cg["statut"] in ordre
                          and ordre.index(cf["statut"]) > ordre.index(cg["statut"])) else cg
        notes = "\n".join(n for n in (cg["notes"], cf["notes"]) if n)
        conn.execute("UPDATE cibles SET statut = ?, date_envoi = ?, entretien_at = ?, notes = ?, "
                     "favori = ?, priorite = ? WHERE id = ?",
                     (meilleur["statut"], meilleur["date_envoi"], meilleur["entretien_at"], notes,
                      max(cg["favori"], cf["favori"]), max(cg["priorite"], cf["priorite"]), cg["id"]))
        conn.execute("UPDATE historique SET cible_id = ? WHERE cible_id = ?", (cg["id"], cf["id"]))
        conn.execute("INSERT INTO historique (cible_id, ancien_statut, nouveau_statut, commentaire, created_at) "
                     "VALUES (?, ?, ?, ?, ?)", (cg["id"], cg["statut"], meilleur["statut"],
                                                f"Fusion avec le doublon « {f['nom']} »", maintenant()))
        conn.execute("DELETE FROM cibles WHERE id = ?", (cf["id"],))
    conn.execute("UPDATE cibles SET entreprise_id = ? WHERE entreprise_id = ?", (garder_id, fusion_id))
    conn.execute("UPDATE offres SET entreprise_id = ? WHERE entreprise_id = ?", (garder_id, fusion_id))
    conn.execute("UPDATE provenances SET entreprise_id = ? WHERE entreprise_id = ?", (garder_id, fusion_id))
    conn.execute("DELETE FROM entreprises WHERE id = ?", (fusion_id,))
    ids = [r[0] for r in conn.execute("SELECT id FROM cibles WHERE entreprise_id = ?", (garder_id,))]
    merge.recalculer_scores(conn, db.get_parametres(conn), ids)


def _date_fr(iso: str) -> str:
    mois = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
            "octobre", "novembre", "décembre"]
    try:
        d = date.fromisoformat(iso)
        return f"{d.day} {mois[d.month - 1]} {d.year}"
    except (TypeError, ValueError):
        return iso or ""


def modele_mail(conn: sqlite3.Connection, cible_id: int) -> dict:
    """Mail de candidature pré-rempli pour une cible."""
    r = conn.execute("SELECT e.nom, e.ville, e.email_public, o.titre FROM cibles c "
                     "JOIN entreprises e ON e.id = c.entreprise_id LEFT JOIN offres o ON o.id = c.offre_id "
                     "WHERE c.id = ?", (cible_id,)).fetchone()
    if not r:
        raise SuiviError("Cible introuvable")
    p = db.get_parametres(conn)
    profil = p.get("profil") or {}
    nom = r["nom"].split(" (")[0].title() if r["nom"].isupper() else r["nom"].split(" (")[0]
    mn, mx = p.get("stage_duree_min_semaines", 7), p.get("stage_duree_max_semaines", 8)
    valeurs = {
        "entreprise": nom, "ville": (r["ville"] or "Brest"), "poste": r["titre"] or "",
        "poste_phrase": f" et par votre offre « {r['titre']} »" if r["titre"] else "",
        "date_debut": _date_fr(p.get("stage_debut")), "date_fin": _date_fr(p.get("stage_fin")),
        "duree": f"{mn} à {mx} semaines" if mn != mx else f"{mn} semaines",
        "prenom_nom": profil.get("prenom_nom") or "[Prénom Nom]",
        "email": profil.get("email") or "[email]", "telephone": profil.get("telephone") or "[téléphone]",
        "ecole": profil.get("ecole") or "",
        "ecole_phrase": f" au {profil['ecole']}" if profil.get("ecole") else "",
    }

    class _Safe(dict):
        def __missing__(self, k):  # variable inconnue laissée telle quelle
            return "{" + k + "}"

    corps = (p.get("modele_mail") or "").format_map(_Safe(valeurs))
    objet = (p.get("modele_mail_objet") or "").format_map(_Safe(valeurs))
    return {"objet": objet, "corps": corps, "destinataire": r["email_public"] or ""}


def export_parametres_json(conn) -> str:
    return json.dumps(db.get_parametres(conn), ensure_ascii=False, indent=2)
