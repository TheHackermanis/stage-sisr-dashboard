#!/usr/bin/env bash
# Supprime le démarrage automatique (Linux / systemd --user). Tes données ne sont pas touchées.
set -euo pipefail
systemctl --user disable --now stage-sisr-app.service stage-sisr-tunnel.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/stage-sisr-app.service" "$HOME/.config/systemd/user/stage-sisr-tunnel.service"
systemctl --user daemon-reload
echo "✅ Démarrage automatique désinstallé (le dashboard n'est plus en ligne depuis cette machine)."
