#!/usr/bin/env bash
# Définit ou change le mot de passe du dashboard : ./set_password.sh
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Lance d'abord ./start.sh une fois pour installer l'application." >&2
  exit 1
fi
exec .venv/bin/python -m app.set_password
