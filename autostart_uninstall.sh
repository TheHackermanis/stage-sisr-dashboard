#!/usr/bin/env bash
# Supprime le démarrage automatique (arrête l'application et le tunnel). Tes données ne sont pas touchées.
set -euo pipefail
for L in local.stage-sisr.app local.stage-sisr.tunnel; do
  launchctl bootout "gui/$(id -u)/$L" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/$L.plist"
done
echo "✅ Démarrage automatique désinstallé (le dashboard n'est plus en ligne)."
