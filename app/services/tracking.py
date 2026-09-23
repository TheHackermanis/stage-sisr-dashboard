"""Suivi des candidatures : statuts, historique, relances automatiques, corbeille."""

import sqlite3
from datetime import datetime, timedelta

from app import db

# Ordre = ordre des colonnes du Kanban
STATUTS = {
    "nouveau":    {"label": "Nouveau", "emoji": "🆕"},
    "vu":         {"label": "Vu", "emoji": "👁️"},
    "retenu":     {"label": "Retenu / à contacter", "emoji": "⭐"},
    "envoyee":    {"label": "Candidature envoyée", "emoji": "📨"},
    "a_relancer": {"label": "À relancer", "emoji": "🔔"},
    "entretien":  {"label": "Entretien prévu", "emoji": "🗓️"},
    "accepte":    {"label": "Accepté", "emoji": "✅"},
    "refuse":     {"label": "Refusé", "emoji": "❌"},
    "supprime":   {"label": "Supprimé", "emoji": "🗑️"},
}


class SuiviError(ValueError):
    pass


def maintenant() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _get(conn: sqlite3.Connection, cible_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM cibles WHERE id = ?", (cible_id,)).fetchone()
    if not row:
        raise SuiviError(f"Cible {cible_id} introuvable")
    return row


def _historiser(conn, cible_id, ancien, nouveau, commentaire=None):
    conn.execute("INSERT INTO historique (cible_id, ancien_statut, nouveau_statut, commentaire, created_at) "
                 "VALUES (?, ?, ?, ?, ?)", (cible_id, ancien, nouveau, commentaire, maintenant()))


def changer_statut(conn: sqlite3.Connection, cible_id: int, nouveau: str, *,
                   commentaire: str | None = None, entretien_at: str | None = None) -> dict:
    """Change le statut d'une cible et l'enregistre dans l'historique."""
    if nouveau not in STATUTS:
        raise SuiviError(f"Statut inconnu : {nouveau}")
    c = _get(conn, cible_id)
    ancien = c["statut"]
    sets = {"statut": nouveau, "updated_at": maintenant()}

    if nouveau == "supprime" and ancien != "supprime":
        sets["statut_avant_suppression"] = ancien
    if nouveau == "envoyee" and ancien != "envoyee":
        # Date d'envoi enregistrée automatiquement (une relance repart aussi de zéro)
        sets["date_envoi"] = maintenant()
        if ancien == "a_relancer" and not commentaire:
            commentaire = "Relance effectuée"
    if nouveau == "entretien" and entretien_at:
        sets["entretien_at"] = entretien_at
        commentaire = commentaire or f"Entretien le {entretien_at.replace('T', ' à ')}"
    if ancien == "nouveau" and not c["vu_at"]:
        sets["vu_at"] = maintenant()

    if ancien == nouveau and nouveau != "entretien":
        return dict(_get(conn, cible_id))
    conn.execute(f"UPDATE cibles SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?",
                 list(sets.values()) + [cible_id])
    _historiser(conn, cible_id, ancien, nouveau, commentaire)
    return dict(_get(conn, cible_id))


def changer_statut_lot(conn: sqlite3.Connection, ids: list[int], nouveau: str) -> int:
    for i in ids:
        changer_statut(conn, i, nouveau, commentaire="Modification groupée")
    return len(ids)


def restaurer(conn: sqlite3.Connection, cible_id: int) -> dict:
    """Sort une cible de la corbeille en lui rendant son statut précédent."""
    c = _get(conn, cible_id)
    if c["statut"] != "supprime":
        return dict(c)
    precedent = c["statut_avant_suppression"] or "vu"
    conn.execute("UPDATE cibles SET statut = ?, statut_avant_suppression = NULL, updated_at = ? WHERE id = ?",
                 (precedent, maintenant(), cible_id))
    _historiser(conn, cible_id, "supprime", precedent, "Restaurée depuis la corbeille")
    return dict(_get(conn, cible_id))


def marquer_vu(conn: sqlite3.Connection, cible_id: int) -> None:
    """Ouverture de la fiche : Nouveau -> Vu automatiquement."""
    c = _get(conn, cible_id)
    if c["statut"] == "nouveau":
        changer_statut(conn, cible_id, "vu", commentaire="Fiche ouverte")


def maj_suivi(conn: sqlite3.Connection, cible_id: int, *, favori: bool | None = None,
              priorite: int | None = None, notes: str | None = None,
              entretien_at: str | None = None, date_envoi: str | None = None) -> dict:
    """Met à jour les champs de suivi autres que le statut."""
    _get(conn, cible_id)
    sets: dict = {}
    if favori is not None:
        sets["favori"] = 1 if favori else 0
    if priorite is not None:
        if not 0 <= int(priorite) <= 5:
            raise SuiviError("La priorité doit être entre 0 et 5")
        sets["priorite"] = int(priorite)
    if notes is not None:
        sets["notes"] = notes
    if entretien_at is not None:
        sets["entretien_at"] = entretien_at or None
    if date_envoi is not None:
        sets["date_envoi"] = date_envoi or None
    if sets:
        sets["updated_at"] = maintenant()
        conn.execute(f"UPDATE cibles SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?",
                     list(sets.values()) + [cible_id])
    return dict(_get(conn, cible_id))


def appliquer_relances_auto(conn: sqlite3.Connection, now: datetime | None = None) -> int:
    """Passe en « À relancer » les candidatures envoyées sans réponse depuis N jours."""
    delai = int(db.get_parametres(conn).get("delai_relance_jours", 7))
    limite = ((now or datetime.now()) - timedelta(days=delai)).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute("SELECT id FROM cibles WHERE statut = 'envoyee' AND date_envoi IS NOT NULL "
                        "AND date_envoi <= ?", (limite,)).fetchall()
    for r in rows:
        conn.execute("UPDATE cibles SET statut = 'a_relancer', updated_at = ? WHERE id = ?",
                     (maintenant(), r["id"]))
        _historiser(conn, r["id"], "envoyee", "a_relancer",
                    f"Relance automatique ({delai} jours sans réponse)")
    return len(rows)
