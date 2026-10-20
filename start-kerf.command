#!/bin/sh
# Starts the Kerf engine (local API on 127.0.0.1:7878). Used by the Premiere panel's "Start engine" button.
cd "$(dirname "$0")" && exec python3 -m kerf serve --follow-editors
