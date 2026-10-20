@echo off
rem Starts the Kerf engine (local API on 127.0.0.1:7878). Used by the Premiere panel's "Start engine" button.
cd /d "%~dp0"
start "Kerf engine" /min python -m kerf serve --follow-editors
