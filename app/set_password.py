"""Définit (ou change) le mot de passe du dashboard.

Usage :  ./set_password.sh
Le mot de passe est demandé sans être affiché, puis seule son empreinte est écrite dans .env
(APP_PASSWORD_HASH), avec une clé secrète de session (SECRET_KEY) générée au besoin.
Redémarre ensuite l'application. Changer le mot de passe déconnecte tous les appareils.
"""

import getpass
import re
import secrets
import sys

from app import config
from app.auth import hasher

ENV = config.BASE_DIR / ".env"


def ecrire_env(cle: str, valeur: str, texte: str) -> str:
    ligne = f"{cle}='{valeur}'"  # guillemets simples : pas d'interprétation des « $ » par dotenv
    if re.search(rf"^{cle}=.*$", texte, flags=re.M):
        return re.sub(rf"^{cle}=.*$", lambda _: ligne, texte, flags=re.M)
    return texte.rstrip("\n") + f"\n{ligne}\n"


def main() -> int:
    if not ENV.exists():
        ENV.write_text((config.BASE_DIR / ".env.example").read_text())
    print("Mot de passe du dashboard (12 caractères minimum, rien ne s'affiche pendant la saisie).")
    mdp = getpass.getpass("Nouveau mot de passe : ")
    if len(mdp) < 12:
        print("❌ Trop court : 12 caractères minimum.")
        return 1
    if getpass.getpass("Confirme le mot de passe : ") != mdp:
        print("❌ Les deux saisies ne correspondent pas.")
        return 1
    texte = ENV.read_text()
    texte = ecrire_env("APP_PASSWORD_HASH", hasher(mdp), texte)
    if not re.search(r"^SECRET_KEY=.+$", texte, flags=re.M):
        texte = ecrire_env("SECRET_KEY", secrets.token_urlsafe(48), texte)
    ENV.write_text(texte)
    ENV.chmod(0o600)  # lisible par toi seul
    print("✅ Mot de passe enregistré (empreinte seulement) dans .env. Redémarre l'application.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
