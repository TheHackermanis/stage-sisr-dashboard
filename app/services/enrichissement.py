"""Enrichissement web : site, description de l'activité, pages contact / recrutement.

Méthode légale et respectueuse (pas de scraping de moteur de recherche) :
1. OpenStreetMap (API Overpass) : lieux proches de l'adresse portant un tag `website`,
   rapprochés par SIRET (tag ref:FR:SIRET) ou par nom ;
2. sinon, domaines probables (nom-entreprise.fr/.com/.bzh…) retenus seulement si la page
   d'accueil contient le SIREN ou le nom de l'entreprise dans son titre ;
3. sur le site retenu : robots.txt respecté, page d'accueil seulement (+ page contact),
   délai entre les requêtes. Seuls les emails/téléphones GÉNÉRIQUES sont gardés (RGPD).
"""

import json
import re
import sqlite3
import time
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from rapidfuzz import fuzz
from selectolax.parser import HTMLParser

from app import db
from app.services import merge
from app.services.http_cache import CachedHttp, HttpError
from app.services.referentiels import normaliser

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
TLDS = [".fr", ".com", ".bzh", ".net", ".eu"]
MOTS_VIDES = {"sas", "sarl", "sa", "eurl", "sasu", "groupe", "societe", "france", "the", "de", "du", "des", "la",
              "le", "les", "et", "services", "service", "solutions", "informatique", "conseil", "ouest", "bretagne"}
PREFIXES_GENERIQUES = ("contact", "info", "infos", "accueil", "rh", "recrutement", "jobs", "job", "emploi",
                       "hello", "bonjour", "secretariat", "commercial", "support", "direction", "candidature",
                       "carriere", "carrieres", "admin", "agence", "brest", "ressources.humaines", "drh")
RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
RE_TEL = re.compile(r"(?:\+33\s?|0)[1-9](?:[\s.-]?\d{2}){4}")
MOTS_RECRUTEMENT = ("recrut", "carriere", "career", "emploi", "jobs", "nous-rejoindre", "rejoignez", "rejoindre",
                    "join", "offres", "candidat", "stage")
MOTS_CONTACT = ("contact", "nous-contacter", "contactez")


class Enrichisseur:
    def __init__(self, http: CachedHttp | None = None):
        self.http = http or CachedHttp({"overpass-api.de": 1.5}, timeout=8.0)
        self._robots: dict[str, RobotFileParser | None] = {}
        self._morts: set[str] = set()  # domaines injoignables (DNS, TLS…) : on ne réessaie pas

    # ------------------------------------------------------------ robots.txt
    def _autorise(self, url: str) -> bool:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base in self._morts:
            return False
        if base not in self._robots:
            rp = RobotFileParser()
            try:
                status, text = self.http.request_text("GET", base + "/robots.txt", ttl_heures=24 * 7,
                                                      retries=1, ok_statuses=(200, 404))
                rp.parse(text.splitlines() if status == 200 else [])
            except HttpError:
                self._morts.add(base)
                return False
            self._robots[base] = rp
        rp = self._robots[base]
        return rp is None or rp.can_fetch("StageSISR-Dashboard", url)

    def _get_html(self, url: str) -> tuple[str, str] | None:
        """(url finale, html) ou None. Respecte robots.txt ; limite 1 req/s par site (throttle)."""
        host = urlparse(url).hostname or ""
        self.http.min_interval.setdefault(host, 1.0)
        if not self._autorise(url):
            return None
        try:
            status, text = self.http.request_text("GET", url, ttl_heures=24 * 14, retries=1)
        except HttpError:
            return None
        if status != 200 or "<html" not in text[:3000].lower():
            return None
        return url, text[:600_000]

    # ------------------------------------------------------------ 1. OpenStreetMap
    def site_osm(self, ent: sqlite3.Row) -> dict | None:
        if ent["lat"] is None:
            return None
        q = (f'[out:json][timeout:20];nwr(around:350,{ent["lat"]},{ent["lon"]})'
             f'[~"^(website|contact:website)$"~"."];out tags center 40;')
        try:
            status, text = self.http.request_text("POST", OVERPASS_URL, data={"data": q}, ttl_heures=24 * 30,
                                                  retries=1)
            elements = json.loads(text).get("elements", []) if status == 200 else []
        except (HttpError, ValueError):
            return None
        nom = self._nom_court(ent["nom"])
        meilleur, score = None, 0
        for el in elements:
            t = el.get("tags", {})
            if ent["siret"] and t.get("ref:FR:SIRET", "").replace(" ", "") == ent["siret"]:
                meilleur, score = t, 100
                break
            for cle in ("name", "brand", "operator", "official_name"):
                if t.get(cle):
                    s = fuzz.token_set_ratio(nom, normaliser(t[cle]))
                    if s > score:
                        meilleur, score = t, s
        if not meilleur or score < 85:
            return None
        return {
            "site_web": meilleur.get("website") or meilleur.get("contact:website"),
            "email_public": self._email_generique(meilleur.get("email") or meilleur.get("contact:email")),
            "tel_public": meilleur.get("phone") or meilleur.get("contact:phone"),
        }

    # ------------------------------------------------------------ 2. domaines probables
    @staticmethod
    def _nom_court(nom: str) -> str:
        return normaliser(nom.split(" (")[0])

    def domaines_candidats(self, nom: str) -> list[str]:
        mots = [m for m in self._nom_court(nom).split() if m not in MOTS_VIDES]
        if not mots:
            return []
        bases = []
        if len(mots[0]) >= 4:
            bases.append(mots[0])
        if len(mots) >= 2:
            bases += ["".join(mots[:2]), "-".join(mots[:2])]
        doms = []
        for b in dict.fromkeys(bases):
            doms += [f"https://{b}{tld}" for tld in TLDS[:3]]
        return doms[:6]

    def site_devine(self, ent: sqlite3.Row) -> tuple[str, str] | None:
        nom = self._nom_court(ent["nom"])
        mots = [m for m in nom.split() if m not in MOTS_VIDES]
        debut = time.monotonic()
        for url in self.domaines_candidats(ent["nom"]):
            if time.monotonic() - debut > 20:  # budget de 20 s par entreprise
                break
            page = self._get_html(url)
            if not page:
                continue
            html = page[1]
            tree = HTMLParser(html)
            titre = normaliser(tree.css_first("title").text() if tree.css_first("title") else "")
            texte = normaliser(tree.body.text(separator=" ")[:20000] if tree.body else "")
            siren_ok = ent["siren"] and ent["siren"] in re.sub(r"\s", "", html)
            titre_ok = mots and fuzz.partial_ratio(" ".join(mots), titre) >= 90
            if siren_ok or (titre_ok and " ".join(mots) in texte):
                return page
        return None

    # ------------------------------------------------------------ 3. analyse du site
    @staticmethod
    def _email_generique(email: str | None) -> str | None:
        if not email:
            return None
        email = email.strip().lower()
        local = email.split("@")[0]
        return email if local.startswith(PREFIXES_GENERIQUES) else None

    def analyser_site(self, url: str, html: str) -> dict:
        tree = HTMLParser(html)
        out: dict = {}
        for sel in ('meta[name="description"]', 'meta[property="og:description"]'):
            n = tree.css_first(sel)
            if n and (n.attributes.get("content") or "").strip():
                out["description_activite"] = n.attributes["content"].strip()[:600]
                break
        if "description_activite" not in out:
            for p in tree.css("p"):
                t = p.text(strip=True)
                if 80 <= len(t) <= 600:
                    out["description_activite"] = t
                    break
        emails, tels = [], []
        for a in tree.css("a[href]"):
            href = a.attributes.get("href") or ""
            libelle = normaliser(a.text() + " " + href)
            if href.startswith("mailto:"):
                emails.append(href[7:].split("?")[0])
                continue
            if href.startswith("tel:"):
                tels.append(href[4:])
                continue
            absolu = urljoin(url, href)
            if urlparse(absolu).netloc != urlparse(url).netloc:
                continue
            if "page_recrutement" not in out and any(m in libelle for m in MOTS_RECRUTEMENT):
                out["page_recrutement"] = absolu
            elif "page_contact" not in out and any(m in libelle for m in MOTS_CONTACT):
                out["page_contact"] = absolu
        texte = tree.body.text(separator=" ") if tree.body else ""
        emails += RE_EMAIL.findall(texte)
        tels += RE_TEL.findall(texte)
        # Page contact : souvent le seul endroit où figure l'adresse email
        if "page_contact" in out and not any(self._email_generique(e) for e in emails):
            page = self._get_html(out["page_contact"])
            if page:
                t2 = HTMLParser(page[1])
                emails += [a.attributes["href"][7:].split("?")[0] for a in t2.css('a[href^="mailto:"]')]
                emails += RE_EMAIL.findall(t2.body.text(separator=" ") if t2.body else "")
                tels += RE_TEL.findall(t2.body.text(separator=" ") if t2.body else "")
        for e in emails:
            g = self._email_generique(e)
            if g and not g.endswith((".png", ".jpg")):
                out["email_public"] = g
                break
        if tels:
            out["tel_public"] = re.sub(r"[\s.-]", " ", tels[0]).strip()
        return out

    # ------------------------------------------------------------ orchestration
    def enrichir(self, ent: sqlite3.Row) -> dict:
        """Cherche les infos manquantes d'une entreprise. Ne renvoie que ce qui a été trouvé."""
        trouve: dict = {}
        site = ent["site_web"]
        if not site:
            osm = self.site_osm(ent)
            if osm:
                trouve.update({k: v for k, v in osm.items() if v})
                site = osm.get("site_web")
        page = None
        if site:
            if not site.startswith("http"):
                site = "https://" + site
            page = self._get_html(site)
        elif not ent["site_web"]:
            page = self.site_devine(ent)
            if page:
                trouve["site_web"] = f"{urlparse(page[0]).scheme}://{urlparse(page[0]).netloc}"
        if page:
            for k, v in self.analyser_site(page[0], page[1]).items():
                trouve.setdefault(k, v)
        return trouve

    def close(self):
        self.http.close()


CHAMPS = ["site_web", "page_contact", "page_recrutement", "email_public", "tel_public", "description_activite"]


def appliquer(conn: sqlite3.Connection, ent_id: int, trouve: dict) -> list[str]:
    """Complète uniquement les champs vides. Retourne la liste des champs ajoutés."""
    ent = conn.execute("SELECT * FROM entreprises WHERE id = ?", (ent_id,)).fetchone()
    ajoutes = [k for k in CHAMPS if trouve.get(k) and not ent[k]]
    if ajoutes:
        conn.execute(f"UPDATE entreprises SET {', '.join(f'{k} = ?' for k in ajoutes)}, "
                     "updated_at = datetime('now','localtime') WHERE id = ?",
                     [trouve[k] for k in ajoutes] + [ent_id])
    conn.execute("DELETE FROM provenances WHERE entreprise_id = ? AND source = 'enrichissement_web'", (ent_id,))
    conn.execute("INSERT INTO provenances (entreprise_id, source, payload_json) VALUES (?, 'enrichissement_web', ?)",
                 (ent_id, json.dumps({"trouve": trouve, "ajoutes": ajoutes}, ensure_ascii=False)))
    ids = [r[0] for r in conn.execute("SELECT id FROM cibles WHERE entreprise_id = ?", (ent_id,))]
    merge.recalculer_scores(conn, db.get_parametres(conn), ids)
    return ajoutes


def enrichir_une(ent_id: int) -> dict:
    """Enrichissement à la demande depuis la fiche."""
    with db.get_conn() as conn:
        ent = conn.execute("SELECT * FROM entreprises WHERE id = ?", (ent_id,)).fetchone()
    if not ent:
        raise ValueError("Entreprise introuvable")
    e = Enrichisseur()
    try:
        trouve = e.enrichir(ent)
    finally:
        e.close()
    with db.get_conn() as conn:
        ajoutes = appliquer(conn, ent_id, trouve)
    libelles = {"site_web": "site web", "page_contact": "page contact", "page_recrutement": "page recrutement",
                "email_public": "email", "tel_public": "téléphone", "description_activite": "description"}
    if ajoutes:
        return {"trouve": True, "message": "Ajouté : " + ", ".join(libelles[k] for k in ajoutes)}
    if trouve:
        return {"trouve": False, "message": "Rien de nouveau (les champs étaient déjà remplis)"}
    return {"trouve": False, "message": "Aucun site trouvé automatiquement. Utilise « Rechercher » puis « Modifier »."}
