@echo off
rem Starts the Kerf engine (local API on 127.0.0.1:7878) without a console window. A source-checkout fallback:
rem installed Kerf is started by its helper.
cd /d "%~dp0"
start "" pythonw -m kerf serve --follow-editors
