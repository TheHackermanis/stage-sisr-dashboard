#!/usr/bin/env bash
# Configuration (une seule fois) du tunnel Cloudflare qui publie le dashboard sur un sous-domaine.
#   Prérequis : domaine géré par Cloudflare, `brew install cloudflared`, puis `cloudflared tunnel login`.
#   Usage     : ./setup_tunnel.sh stage.gcosta.fr
# Crée le tunnel « stage-sisr », l'enregistrement DNS du sous-domaine et ~/.cloudflared/stage-sisr.yml.
# Les identifiants du tunnel restent dans ~/.cloudflared (jamais dans le dépôt Git).
set -euo pipefail

HOSTNAME_PUBLIC="${1:-}"
TUNNEL="${TUNNEL_NAME:-stage-sisr}"
CONF="$HOME/.cloudflared/$TUNNEL.yml"
cd "$(dirname "$0")"
PORT="$(grep -E '^PORT=' .env 2>/dev/null | cut -d= -f2- | tr -d "[:space:]'\"" || true)"
PORT="${PORT:-8000}"

if [ -z "$HOSTNAME_PUBLIC" ]; then
  echo "Usage : ./setup_tunnel.sh stage.mondomaine.fr" >&2; exit 1
fi
command -v cloudflared >/dev/null || { echo "❌ cloudflared absent : brew install cloudflared" >&2; exit 1; }
[ -f "$HOME/.cloudflared/cert.pem" ] || { echo "❌ Lance d'abord : cloudflared tunnel login" >&2; exit 1; }

# 1. Tunnel (réutilisé s'il existe déjà)
if ! cloudflared tunnel info "$TUNNEL" >/dev/null 2>&1; then
  cloudflared tunnel create "$TUNNEL"
fi
TUNNEL_ID="$(cloudflared tunnel info "$TUNNEL" 2>/dev/null | grep -Eo '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' | head -1)"
[ -n "$TUNNEL_ID" ] || { echo "❌ Identifiant du tunnel introuvable" >&2; exit 1; }

# 2. DNS : sous-domaine -> tunnel (CNAME proxifié par Cloudflare, HTTPS automatique)
cloudflared tunnel route dns --overwrite-dns "$TUNNEL" "$HOSTNAME_PUBLIC"

# 3. Configuration : tout le trafic du sous-domaine va vers l'application locale, rien d'autre.
cat > "$CONF" <<EOF
tunnel: $TUNNEL_ID
credentials-file: $HOME/.cloudflared/$TUNNEL_ID.json
ingress:
  - hostname: $HOSTNAME_PUBLIC
    service: http://127.0.0.1:$PORT
  - service: http_status:404
EOF
echo "✅ Tunnel prêt : https://$HOSTNAME_PUBLIC  (configuration : $CONF)"
echo "   Lance maintenant : ./online.sh"
