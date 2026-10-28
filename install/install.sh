#!/bin/sh
# Kerf installer for macOS and Linux.
#   DaVinci Resolve: Kerf FX comes with the Kerf installer (Effects > OpenFX > Kerf)
#   After Effects (macOS): Window > Kerf.jsx
#   Premiere Pro (macOS): installs the .ccx through Adobe's Unified Plugin Installer Agent
#   --engine: also pip-install the Kerf engine from this folder (not needed with Kerf Studio installed)
set -e
KERF="$(cd "$(dirname "$0")/.." && pwd)"
OS="$(uname -s)"
say() { printf '  %s\n' "$1"; }

if [ "$OS" = Darwin ]; then
  found=0
  for d in /Applications/Adobe\ After\ Effects*/Scripts/ScriptUI\ Panels; do
    [ -d "$d" ] || continue
    found=1
    if cp "$KERF/aftereffects/Kerf.jsx" "$d/" 2>/dev/null || sudo cp "$KERF/aftereffects/Kerf.jsx" "$d/"; then
      say "After Effects: installed to $d (Window > Kerf.jsx)"
    fi
  done
  [ $found = 1 ] && say "After Effects: enable Settings > Scripting & Expressions > Allow Scripts to Write Files and Access Network"
  CCX="$(ls -t "$KERF"/release/*.ccx "$KERF"/*.ccx 2>/dev/null | head -n 1 || true)"
  UPIA="/Library/Application Support/Adobe/Adobe Desktop Common/RemoteComponents/UPI/UnifiedPluginInstallerAgent/UnifiedPluginInstallerAgent.app/Contents/MacOS/UnifiedPluginInstallerAgent"
  if [ -n "$CCX" ]; then
    if [ -x "$UPIA" ]; then "$UPIA" --install "$CCX" && say "Premiere Pro: installed $(basename "$CCX") (Window > UXP Plugins > Kerf)"
    else open "$CCX" && say "Premiere Pro: confirm the install in Creative Cloud"; fi
  else
    say "Premiere Pro: no .ccx here (download kerf-premiere-*.ccx from the release page)"
  fi
else
  say "Premiere Pro and After Effects are not available on Linux: Kerf FX for DaVinci Resolve comes with the Kerf installer"
fi

if [ "$1" = "--engine" ]; then
  python3 -m pip install --user -e "$KERF" && say "Engine: installed (start with: python3 -m kerf serve)"
fi
say "Done. Kerf Studio (desktop app) starts the engine for you; otherwise run start-kerf.command / start-kerf.sh."
