#!/usr/bin/env bash
# Démarrage automatique (Linux / systemd --user) : équivalent de autostart_install.sh (macOS).
# L'application + le tunnel Cloudflare démarrent à l'ouverture de session et redémarrent seuls.
#
# Prérequis :
#   - ./set_password.sh déjà exécuté (mot de passe défini) ;
#   - ./setup_tunnel.sh mondomaine.fr déjà exécuté (tunnel + DNS créés) ;
#   - pour que les services tournent MÊME SANS SESSION OUVERTE (redémarrage du serveur,
#     déconnexion SSH) : `loginctl enable-linger $USER` (une fois, peut demander sudo).
#
#   Installer   : ./autostart_install_linux.sh
#   Désinstaller: ./autostart_uninstall_linux.sh
#   Journaux    : journalctl --user -u stage-sisr-app -u stage-sisr-tunnel -f
set -euo pipefail
cd "$(dirname "$0")"
DIR="$(pwd)"
TUNNEL="${TUNNEL_NAME:-stage-sisr}"
CONF="$HOME/.cloudflared/$TUNNEL.yml"
UNITS="$HOME/.config/systemd/user"
UNIT_APP="stage-sisr-app.service"
UNIT_TUNNEL="stage-sisr-tunnel.service"

[ -x .venv/bin/python ] || { echo "❌ Lance d'abord ./start.sh une fois." >&2; exit 1; }
grep -Eq "^APP_PASSWORD_HASH=['\"]?scrypt" .env || { echo "❌ Définis d'abord un mot de passe : ./set_password.sh" >&2; exit 1; }
[ -f "$CONF" ] || { echo "❌ Tunnel non configuré : ./setup_tunnel.sh mondomaine.fr" >&2; exit 1; }
CLOUDFLARED="$(command -v cloudflared)"
PORT="$(grep -E '^PORT=' .env | cut -d= -f2- | tr -d "[:space:]'\"" || true)"
PORT="${PORT:-8000}"

mkdir -p "$UNITS"

cat > "$UNITS/$UNIT_APP" <<EOF
[Unit]
Description=Dashboard stage SISR - application
After=network-online.target

[Service]
WorkingDirectory=$DIR
ExecStart=$DIR/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port $PORT
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

cat > "$UNITS/$UNIT_TUNNEL" <<EOF
[Unit]
Description=Dashboard stage SISR - tunnel Cloudflare
After=network-online.target $UNIT_APP
Wants=$UNIT_APP

[Service]
ExecStart=$CLOUDFLARED tunnel --config $CONF --no-autoupdate run $TUNNEL
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now "$UNIT_APP" "$UNIT_TUNNEL"

if [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]; then
  echo "⚠️  loginctl linger désactivé : les services s'arrêteront à la déconnexion SSH."
  echo "   Active-le (une fois, avec sudo) :  sudo loginctl enable-linger $USER"
fi

HOST_PUBLIC="$(grep -E 'hostname:' "$CONF" | head -1 | awk '{print $NF}')"
echo "✅ Démarrage automatique installé."
echo "   Application : http://127.0.0.1:$PORT   ·   En ligne : https://$HOST_PUBLIC"
echo "   Journaux    : journalctl --user -u $UNIT_APP -u $UNIT_TUNNEL -f"
echo "   Après une mise à jour du code (git pull) : ./autostart_install_linux.sh"
