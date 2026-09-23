#!/usr/bin/env bash
# Lance le dashboard en une commande : ./start.sh
# - crée l'environnement virtuel Python (.venv) au premier lancement
# - installe / met à jour les dépendances si requirements.txt a changé
# - crée .env à partir de .env.example s'il n'existe pas
# - démarre le serveur et ouvre le navigateur
# Compatible Linux et macOS.
set -euo pipefail

cd "$(dirname "$0")"

# 1. Python 3.10 minimum
PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "❌ python3 introuvable. Installe Python 3.10 ou plus récent." >&2
  exit 1
fi
if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "❌ Python 3.10+ requis (trouvé : $("$PYTHON" --version))." >&2
  exit 1
fi

# 2. Environnement virtuel
if [ ! -d .venv ]; then
  echo "📦 Création de l'environnement virtuel…"
  "$PYTHON" -m venv .venv
fi
VENV_PY=".venv/bin/python"

# 3. Dépendances (réinstallées seulement si requirements.txt a changé)
STAMP=".venv/.requirements.sha"
CURRENT_SHA="$("$VENV_PY" -c 'import hashlib,sys; print(hashlib.sha256(open("requirements.txt","rb").read()).hexdigest())')"
if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$CURRENT_SHA" ]; then
  echo "📦 Installation des dépendances…"
  "$VENV_PY" -m pip install --quiet --upgrade pip
  "$VENV_PY" -m pip install --quiet -r requirements.txt
  echo "$CURRENT_SHA" > "$STAMP"
fi

# 4. Fichier .env
if [ ! -f .env ]; then
  cp .env.example .env
  echo "ℹ️  Fichier .env créé. Ajoute tes clés France Travail dedans (voir README)."
fi

# 5. Lecture de HOST / PORT depuis .env (valeurs par défaut sinon)
HOST="$(grep -E '^HOST=' .env | cut -d= -f2- | tr -d '[:space:]' || true)"
PORT="$(grep -E '^PORT=' .env | cut -d= -f2- | tr -d '[:space:]' || true)"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
URL="http://${HOST}:${PORT}"

# 6. Ouverture du navigateur une fois le serveur prêt (en arrière-plan)
#    NO_BROWSER=1 ./start.sh pour ne pas l'ouvrir.
[ "${NO_BROWSER:-0}" = "1" ] || (
  for _ in $(seq 1 30); do
    if curl -s -o /dev/null "$URL/api/health"; then
      if command -v open >/dev/null 2>&1; then open "$URL"
      elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1
      fi
      break
    fi
    sleep 0.5
  done
) &

echo "🚀 Dashboard disponible sur $URL  (Ctrl+C pour arrêter)"
exec "$VENV_PY" -m uvicorn app.main:app --host "$HOST" --port "$PORT"
