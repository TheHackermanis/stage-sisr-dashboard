"""Fusion des données des sources dans la BDD.

Règles :
- dédoublonnage par SIRET, sinon par nom normalisé + ville (approché, voir doublons.py) ;
- exclusion stricte de tout ce qui est au-delà du rayon (50 km par défaut) ;
- les colonnes de suivi (table `cibles` : statut, notes, favori, priorité, dates) ne sont
  JAMAIS modifiées ici : seules les colonnes calculées (score, technos) sont mises à jour ;
- les champs enrichis ou saisis à la main (site web, contact…) ne sont jamais écrasés
  par une valeur venant d'une source : on ne fait que compléter les champs vides.
"""

import json
import sqlite3

from app.services import referentiels as ref
from app.services.scoring import calculer_score
from app.services.technos import detecter_technos
from app.sources.base import EntrepriseRecord, OffreRecord

# Champs « source » : mis à jour à chaque actualisation (sauf saisie manuelle)
CHAMPS_SOURCE = ["nom", "siren", "naf", "secteur", "tranche_effectif", "date_creation",
                 "adresse", "code_postal", "ville", "lat", "lon", "distance_km"]
# Champs « enrichis » : seulement complétés s'ils sont vides
CHAMPS_COMPLETES = ["site_web", "email_public", "tel_public", "description_activite"]


def calculer_distance(parametres: dict, lat, lon) -> float | None:
    v = parametres["ville_depart"]
    return ref.distance_km(v["lat"], v["lon"], lat, lon)


def dans_rayon(parametres: dict, distance: float | None) -> bool:
    return distance is not None and distance <= float(parametres["rayon_km"])


def trouver_entreprise(conn: sqlite3.Connection, rec: EntrepriseRecord) -> sqlite3.Row | None:
    if rec.siret:
        row = conn.execute("SELECT * FROM entreprises WHERE siret = ?", (rec.siret,)).fetchone()
        if row:
            return row
    if rec.raw.get("anonyme"):
        return None
    from app.services.doublons import chercher_doublon_nom  # import tardif (évite les cycles)
    return chercher_doublon_nom(conn, rec.nom, rec.ville, siret=rec.siret)


def upsert_entreprise(conn: sqlite3.Connection, rec: EntrepriseRecord, source: str,
                      distance: float | None) -> tuple[int, bool]:
    """Insère ou met à jour une entreprise. Retourne (id, créée ?)."""
    valeurs = {
        "nom": rec.nom, "siren": rec.siren, "naf": rec.naf, "secteur": rec.secteur,
        "tranche_effectif": rec.tranche_effectif, "date_creation": rec.date_creation,
        "adresse": rec.adresse, "code_postal": rec.code_postal, "ville": rec.ville,
        "lat": rec.lat, "lon": rec.lon, "distance_km": distance,
    }
    completes = {"site_web": rec.site_web, "email_public": rec.email_public,
                 "tel_public": rec.tel_public, "description_activite": rec.description_activite}
    existing = trouver_entreprise(conn, rec)

    if existing is None:
        cols = ["siret", "nom_normalise", "categorie"] + CHAMPS_SOURCE + CHAMPS_COMPLETES
        vals = [rec.siret, ref.normaliser(rec.nom), rec.categorie] + \
               [valeurs[c] for c in CHAMPS_SOURCE] + [completes[c] for c in CHAMPS_COMPLETES]
        cur = conn.execute(
            f"INSERT INTO entreprises ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals)
        ent_id, created = cur.lastrowid, True
    else:
        ent_id, created = existing["id"], False
        sets, params = [], []
        for c in CHAMPS_SOURCE:
            v = valeurs[c]
            if v is None:
                continue
            if existing["saisie_manuelle"] and existing[c] not in (None, ""):
                continue  # ne pas écraser une saisie manuelle
            sets.append(f"{c} = ?")
            params.append(v)
        for c in CHAMPS_COMPLETES:
            if completes[c] and not existing[c]:
                sets.append(f"{c} = ?")
                params.append(completes[c])
        if rec.siret and not existing["siret"]:
            sets.append("siret = ?")
            params.append(rec.siret)
        if "nom = ?" in sets:
            sets.append("nom_normalise = ?")
            params.append(ref.normaliser(rec.nom))
        # Une entreprise « standard » (NAF SISR) reste standard même si elle apparaît côté DSI.
        if rec.categorie == "standard" and existing["categorie"] != "standard":
            sets.append("categorie = 'standard'")
        if sets:
            sets.append("updated_at = datetime('now', 'localtime')")
            conn.execute(f"UPDATE entreprises SET {', '.join(sets)} WHERE id = ?", params + [ent_id])

    # Traçabilité : on garde la dernière réponse de chaque source pour cette entreprise
    conn.execute("DELETE FROM provenances WHERE entreprise_id = ? AND offre_id IS NULL AND source = ?",
                 (ent_id, source))
    conn.execute("INSERT INTO provenances (entreprise_id, source, payload_json) VALUES (?, ?, ?)",
                 (ent_id, source, json.dumps(rec.raw, ensure_ascii=False, default=str)[:20000]))
    return ent_id, created


def assurer_cible_entreprise(conn: sqlite3.Connection, ent_id: int, categorie: str) -> bool:
    """Crée la cible « candidature spontanée » / « DSI interne » si elle n'existe pas. Retourne True si créée."""
    type_cible = "dsi_interne" if categorie == "dsi_interne" else "spontanee"
    row = conn.execute("SELECT id, type FROM cibles WHERE entreprise_id = ? AND offre_id IS NULL",
                       (ent_id,)).fetchone()
    if row:
        # Une DSI interne reclassée en entreprise SISR devient une candidature spontanée
        if row["type"] == "dsi_interne" and type_cible == "spontanee":
            conn.execute("UPDATE cibles SET type = 'spontanee' WHERE id = ?", (row["id"],))
        return False
    cur = conn.execute("INSERT INTO cibles (entreprise_id, type) VALUES (?, ?)", (ent_id, type_cible))
    conn.execute("INSERT INTO historique (cible_id, ancien_statut, nouveau_statut, commentaire) "
                 "VALUES (?, NULL, 'nouveau', 'Ajout automatique')", (cur.lastrowid,))
    return True


def upsert_offre(conn: sqlite3.Connection, off: OffreRecord, source: str, ent_id: int,
                 distance: float | None) -> tuple[int, bool]:
    """Insère ou met à jour une offre et sa cible. Retourne (id offre, cible créée ?)."""
    row = conn.execute("SELECT id FROM offres WHERE source = ? AND source_ref = ?",
                       (source, off.source_ref)).fetchone()
    vals = (ent_id, off.titre, off.description, off.type_contrat, off.lieu, off.lat, off.lon,
            distance, off.url, off.date_publication)
    if row:
        off_id = row["id"]
        conn.execute(
            "UPDATE offres SET entreprise_id=?, titre=?, description=?, type_contrat=?, lieu=?, lat=?, lon=?, "
            "distance_km=?, url=?, date_publication=?, active=1, updated_at=datetime('now','localtime') "
            "WHERE id=?", vals + (off_id,))
    else:
        off_id = conn.execute(
            "INSERT INTO offres (entreprise_id, titre, description, type_contrat, lieu, lat, lon, distance_km, "
            "url, date_publication, source, source_ref) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            vals + (source, off.source_ref)).lastrowid
        conn.execute("INSERT INTO provenances (entreprise_id, offre_id, source, payload_json) VALUES (?,?,?,?)",
                     (ent_id, off_id, source, json.dumps(off.raw, ensure_ascii=False, default=str)[:20000]))
    created = False
    if not conn.execute("SELECT 1 FROM cibles WHERE offre_id = ?", (off_id,)).fetchone():
        cur = conn.execute("INSERT INTO cibles (entreprise_id, offre_id, type) VALUES (?, ?, 'offre')",
                           (ent_id, off_id))
        conn.execute("INSERT INTO historique (cible_id, ancien_statut, nouveau_statut, commentaire) "
                     "VALUES (?, NULL, 'nouveau', 'Ajout automatique')", (cur.lastrowid,))
        created = True
    return off_id, created


def desactiver_offres_absentes(conn: sqlite3.Connection, source: str, refs_vues: set[str]) -> int:
    """Marque inactives les offres d'une source qui n'apparaissent plus (sans rien supprimer)."""
    rows = conn.execute("SELECT id, source_ref FROM offres WHERE source = ? AND active = 1", (source,)).fetchall()
    ids = [r["id"] for r in rows if r["source_ref"] not in refs_vues]
    conn.executemany("UPDATE offres SET active = 0 WHERE id = ?", [(i,) for i in ids])
    return len(ids)


def recalculer_scores(conn: sqlite3.Connection, parametres: dict, cible_ids: list[int] | None = None) -> int:
    """Recalcule technos + score de toutes les cibles (ou d'une liste). Ne touche pas au suivi."""
    sql = """
        SELECT c.id, c.type, e.nom, e.secteur, e.naf, e.tranche_effectif, e.description_activite,
               e.distance_km AS e_dist, o.titre, o.description, o.type_contrat, o.date_publication,
               o.distance_km AS o_dist,
               (SELECT payload_json FROM provenances p WHERE p.entreprise_id = e.id
                  AND p.source = 'la_bonne_boite' ORDER BY p.id DESC LIMIT 1) AS lbb
        FROM cibles c JOIN entreprises e ON e.id = c.entreprise_id
        LEFT JOIN offres o ON o.id = c.offre_id
    """
    args: list = []
    if cible_ids:
        sql += f" WHERE c.id IN ({', '.join('?' * len(cible_ids))})"
        args = cible_ids
    rows = conn.execute(sql, args).fetchall()
    maj = []
    for r in rows:
        texte = " ".join(x for x in (r["titre"], r["description"], r["nom"], r["secteur"],
                                     r["description_activite"]) if x)
        bonus = None
        if r["lbb"] and r["type"] != "offre":
            try:
                potentiel = json.loads(r["lbb"]).get("hiring_potential")
                if potentiel and float(potentiel) >= 1:
                    bonus = (5, "fort potentiel d'embauche (La Bonne Boîte)")
            except (ValueError, TypeError, AttributeError):
                pass
        dist = r["o_dist"] if r["o_dist"] is not None else r["e_dist"]
        score, detail = calculer_score(
            type_cible=r["type"], texte=texte, naf=r["naf"], distance_km=dist,
            tranche=r["tranche_effectif"], parametres=parametres, type_contrat=r["type_contrat"],
            date_publication=r["date_publication"], bonus_externe=bonus)
        maj.append((json.dumps(detecter_technos(texte), ensure_ascii=False), score,
                    json.dumps(detail, ensure_ascii=False), r["id"]))
    conn.executemany("UPDATE cibles SET technos_json = ?, score = ?, score_detail_json = ? WHERE id = ?", maj)
    return len(maj)
