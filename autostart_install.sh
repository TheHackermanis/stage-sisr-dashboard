#!/usr/bin/env bash
# Démarrage automatique (macOS) : l'application + le tunnel Cloudflare se lancent à l'ouverture
# de session et redémarrent seuls s'ils s'arrêtent. Aucun droit administrateur nécessaire.
#   Installer   : ./autostart_install.sh
#   Désinstaller: ./autostart_uninstall.sh
#   Journaux    : ~/Library/Logs/stage-sisr/
set -euo pipefail
cd "$(dirname "$0")"
DIR="$(pwd)"
TUNNEL="${TUNNEL_NAME:-stage-sisr}"
CONF="$HOME/.cloudflared/$TUNNEL.yml"
AGENTS="$HOME/Library/LaunchAgents"
LOGS="$HOME/Library/Logs/stage-sisr"
LABEL_APP="local.stage-sisr.app"
LABEL_TUNNEL="local.stage-sisr.tunnel"

[ "$(uname)" = "Darwin" ] || { echo "❌ Script réservé à macOS (sous Linux : service systemd)." >&2; exit 1; }
[ -x .venv/bin/python ] || { echo "❌ Lance d'abord ./start.sh une fois." >&2; exit 1; }
grep -Eq "^APP_PASSWORD_HASH=['\"]?scrypt" .env || { echo "❌ Définis d'abord un mot de passe : ./set_password.sh" >&2; exit 1; }
[ -f "$CONF" ] || { echo "❌ Tunnel non configuré : ./setup_tunnel.sh stage.mondomaine.fr" >&2; exit 1; }
CLOUDFLARED="$(command -v cloudflared)"
PORT="$(grep -E '^PORT=' .env | cut -d= -f2- | tr -d "[:space:]'\"" || true)"
PORT="${PORT:-8000}"

mkdir -p "$AGENTS" "$LOGS"

# Échappement XML minimal pour les chemins (espaces et accents sont acceptés tels quels)
xml() { sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' <<<"$1"; }

cat > "$AGENTS/$LABEL_APP.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL_APP</string>
  <key>WorkingDirectory</key><string>$(xml "$DIR")</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(xml "$DIR/.venv/bin/python")</string>
    <string>-m</string><string>uvicorn</string><string>app.main:app</string>
    <string>--host</string><string>127.0.0.1</string>
    <string>--port</string><string>$PORT</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$(xml "$LOGS/app.log")</string>
  <key>StandardErrorPath</key><string>$(xml "$LOGS/app.log")</string>
</dict>
</plist>
EOF

cat > "$AGENTS/$LABEL_TUNNEL.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL_TUNNEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(xml "$CLOUDFLARED")</string>
    <string>tunnel</string><string>--config</string><string>$(xml "$CONF")</string>
    <string>--no-autoupdate</string><string>run</string><string>$TUNNEL</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$(xml "$LOGS/tunnel.log")</string>
  <key>StandardErrorPath</key><string>$(xml "$LOGS/tunnel.log")</string>
</dict>
</plist>
EOF

plutil -lint "$AGENTS/$LABEL_APP.plist" "$AGENTS/$LABEL_TUNNEL.plist" >/dev/null

# (Re)chargement des services
for L in "$LABEL_APP" "$LABEL_TUNNEL"; do
  launchctl bootout "gui/$(id -u)/$L" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$AGENTS/$L.plist"
done

echo "✅ Démarrage automatique installé."
echo "   Application : http://127.0.0.1:$PORT   ·   En ligne : https://$(grep -E 'hostname:' "$CONF" | head -1 | awk '{print $NF}')"
echo "   Journaux    : $LOGS"
echo "   Après une mise à jour du code : ./autostart_install.sh (relance les services)"
