"""Score de pertinence SISR sur 100, avec son explication ligne par ligne.

Répartition :
- Pertinence (40 pts max) : mots-clés pondérés (réglables) + code NAF de l'activité
- Distance   (25 pts max) : 25 pts à moins de 5 km, puis décroissance linéaire jusqu'au rayon
- Type       (20 pts max) : offre de stage > candidature spontanée > DSI interne > alternance
- Taille / fraîcheur (15 pts max) : taille compatible avec un encadrement, offre récente
"""

import re
from datetime import date, datetime

from app.services import referentiels as ref

MAX_PERTINENCE, MAX_DISTANCE, MAX_TYPE, MAX_BONUS = 40, 25, 20, 15


def _points_mots_cles(texte: str, mots_cles: dict[str, int]) -> list[tuple[int, str]]:
    t = ref.normaliser(texte)
    out = []
    for mot, pts in mots_cles.items():
        m = ref.normaliser(mot)
        if m and re.search(rf"\b{re.escape(m)}\b", t):
            out.append((int(pts), mot.strip()))
    return out


def _points_taille(tranche: str | None) -> tuple[int, str]:
    mini = ref.effectif_min(tranche)
    if mini is None:
        return 4, "effectif inconnu"
    if mini == 0:
        return 1, "aucun salarié déclaré"
    if mini < 3:
        return 5, ref.tranche_libelle(tranche)
    if mini < 10:
        return 8, ref.tranche_libelle(tranche)
    if mini < 250:
        return 10, ref.tranche_libelle(tranche) + " (bon encadrement)"
    return 8, ref.tranche_libelle(tranche)


def calculer_score(*, type_cible: str, texte: str, naf: str | None, distance_km: float | None,
                   tranche: str | None, parametres: dict, type_contrat: str | None = None,
                   date_publication: str | None = None, bonus_externe: tuple[int, str] | None = None
                   ) -> tuple[int, list[dict]]:
    """Retourne (score 0-100, détail [{points, raison}]) ."""
    details: list[dict] = []

    def add(pts, raison):
        details.append({"points": int(pts), "raison": raison})

    # 1. Pertinence : mots-clés + NAF
    kw = _points_mots_cles(texte, parametres.get("mots_cles", {}))
    naf_pts = int(parametres.get("naf_poids", {}).get(naf or "", 0))
    if type_cible == "dsi_interne":
        naf_pts = max(naf_pts, 8)
    brut = sum(p for p, _ in kw) + naf_pts
    pertinence = max(-10, min(MAX_PERTINENCE, brut))
    if naf_pts:
        libelle = "service informatique interne probable" if type_cible == "dsi_interne" \
            else ref.NAF_LIBELLES.get(naf, naf)
        add(naf_pts, f"activité : {libelle}")
    if kw:
        positifs = [m for p, m in kw if p > 0]
        negatifs = [m for p, m in kw if p < 0]
        if positifs:
            add(sum(p for p, _ in kw if p > 0), "mots-clés : " + ", ".join(positifs))
        if negatifs:
            add(sum(p for p, _ in kw if p < 0), "orienté développement : " + ", ".join(negatifs))
    if brut != pertinence:
        add(pertinence - brut, f"plafond pertinence ({MAX_PERTINENCE} pts max)")

    # 2. Distance
    rayon = float(parametres.get("rayon_km", 50)) or 50
    if distance_km is None:
        dist_pts = 8
        add(dist_pts, "distance inconnue")
    else:
        if distance_km <= 5:
            dist_pts = MAX_DISTANCE
        else:
            dist_pts = round(MAX_DISTANCE * max(0.0, 1 - (distance_km - 5) / max(rayon - 5, 1)))
        add(dist_pts, f"distance {distance_km:.0f} km")

    # 3. Type
    if type_cible == "offre":
        type_pts = {"stage": 20, "alternance": 8}.get(type_contrat or "", 5)
        add(type_pts, {"stage": "offre de stage", "alternance": "offre d'alternance (stage possible)"}
            .get(type_contrat or "", "offre d'emploi"))
    elif type_cible == "spontanee":
        type_pts = 15
        add(type_pts, "candidature spontanée")
    else:
        type_pts = 12
        add(type_pts, "DSI interne")

    # 4. Taille + fraîcheur / bonus
    taille_pts, taille_lib = _points_taille(tranche)
    add(taille_pts, f"taille : {taille_lib}")
    bonus = taille_pts
    if date_publication:
        try:
            d = datetime.fromisoformat(date_publication[:10]).date()
            age = (date.today() - d).days
            if age <= 30:
                bonus += 5
                add(5, f"offre récente ({age} j)")
        except ValueError:
            pass
    if bonus_externe:
        bonus += bonus_externe[0]
        add(bonus_externe[0], bonus_externe[1])
    if bonus > MAX_BONUS:
        add(MAX_BONUS - bonus, f"plafond taille/fraîcheur ({MAX_BONUS} pts max)")
        bonus = MAX_BONUS

    total = max(0, min(100, pertinence + dist_pts + type_pts + bonus))
    return total, details
