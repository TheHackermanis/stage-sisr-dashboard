"""Détection des doublons entre sources : même SIRET, ou nom + ville très proches."""

import sqlite3

from rapidfuzz import fuzz

from app.services.referentiels import normaliser

SEUIL_SIMILARITE = 90  # sur 100 (token_sort_ratio)


def chercher_doublon_nom(conn: sqlite3.Connection, nom: str, ville: str | None,
                         siret: str | None = None) -> sqlite3.Row | None:
    """Cherche une entreprise existante au nom très proche dans la même ville.

    Si les deux entreprises ont un SIRET différent, ce ne sont pas des doublons
    (ex. deux agences d'un même groupe).
    """
    n = normaliser(nom)
    v = normaliser(ville)
    if not n:
        return None
    # Avec un SIRET connu, seules les fiches sans SIRET peuvent être des doublons
    # (celles avec le même SIRET ont déjà été trouvées par l'appelant).
    candidats = conn.execute(
        "SELECT * FROM entreprises WHERE (? = '' OR lower(ville) = lower(?) OR ville IS NULL)"
        + (" AND siret IS NULL" if siret else ""),
        (v, ville or ""),
    ).fetchall()
    meilleur, meilleur_score = None, 0
    for c in candidats:
        if siret and c["siret"] and c["siret"] != siret:
            continue
        s = fuzz.token_sort_ratio(n, c["nom_normalise"])
        # Un nom contenu dans l'autre (« ACME » vs « ACME INFORMATIQUE ») compte aussi
        if s < SEUIL_SIMILARITE and len(n) >= 4 and len(c["nom_normalise"]) >= 4:
            if (f" {n} " in f" {c['nom_normalise']} ") or (f" {c['nom_normalise']} " in f" {n} "):
                s = max(s, SEUIL_SIMILARITE)
        if s >= SEUIL_SIMILARITE and s > meilleur_score:
            meilleur, meilleur_score = c, s
    return meilleur


def lister_doublons_potentiels(conn: sqlite3.Connection) -> list[dict]:
    """Paires d'entreprises probablement identiques (pour affichage / fusion manuelle)."""
    rows = conn.execute("SELECT id, nom, nom_normalise, ville, siret FROM entreprises").fetchall()
    par_ville: dict[str, list] = {}
    for r in rows:
        par_ville.setdefault(normaliser(r["ville"]), []).append(r)
    paires = []
    for groupe in par_ville.values():
        for i, a in enumerate(groupe):
            for b in groupe[i + 1:]:
                if a["siret"] and b["siret"] and a["siret"] != b["siret"]:
                    continue
                s = fuzz.token_sort_ratio(a["nom_normalise"], b["nom_normalise"])
                if s >= SEUIL_SIMILARITE:
                    paires.append({"a": dict(a), "b": dict(b), "similarite": round(s)})
    return paires
