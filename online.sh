#!/usr/bin/env bash
# Démarre le dashboard ET le tunnel Cloudflare : accessible depuis n'importe quel appareil.
#   Usage : ./online.sh        (Ctrl+C arrête les deux)
# Sécurité : refuse de publier le dashboard tant qu'aucun mot de passe n'est défini.
set -euo pipefail
cd "$(dirname "$0")"
TUNNEL="${TUNNEL_NAME:-stage-sisr}"
CONF="$HOME/.cloudflared/$TUNNEL.yml"

if ! grep -Eq "^APP_PASSWORD_HASH=['\"]?scrypt" .env 2>/dev/null; then
  echo "❌ Aucun mot de passe défini : lance d'abord ./set_password.sh" >&2
  echo "   (le dashboard ne sera jamais publié en ligne sans mot de passe)" >&2
  exit 1
fi
[ -f "$CONF" ] || { echo "❌ Tunnel non configuré : lance ./setup_tunnel.sh stage.mondomaine.fr" >&2; exit 1; }

PORT="$(grep -E '^PORT=' .env | cut -d= -f2- | tr -d "[:space:]'\"" || true)"
PORT="${PORT:-8000}"

# 1. Application (sauf si elle tourne déjà)
APP_PID=""
if ! curl -s -o /dev/null "http://127.0.0.1:$PORT/login"; then
  NO_BROWSER=1 ./start.sh &
  APP_PID=$!
  for _ in $(seq 1 60); do curl -s -o /dev/null "http://127.0.0.1:$PORT/login" && break; sleep 0.5; done
fi
cleanup() { [ -n "$APP_PID" ] && kill "$APP_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

# 2. Tunnel
HOST_PUBLIC="$(grep -E 'hostname:' "$CONF" | head -1 | awk '{print $NF}')"
echo "🌍 Dashboard en ligne sur https://$HOST_PUBLIC  (Ctrl+C pour arrêter)"
cloudflared tunnel --config "$CONF" --no-autoupdate run "$TUNNEL"
