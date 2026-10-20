#!/bin/sh
# Starts the Kerf engine (local API on 127.0.0.1:7878) on Linux: bundled build if present, else Python.
cd "$(dirname "$0")"
if [ -x ./kerf-engine/kerf-engine ]; then exec ./kerf-engine/kerf-engine serve --follow-editors; fi
exec python3 -m kerf serve --follow-editors
