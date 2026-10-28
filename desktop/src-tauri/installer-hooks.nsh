; Kerf installer hooks (Windows). Kerf has no app window: installing it puts the Kerf panels into
; Premiere Pro, After Effects and DaVinci Resolve. Kerf 0.3 replaces the old "Kerf Studio" app.

!macro NSIS_HOOK_POSTINSTALL
  IfFileExists "$LOCALAPPDATA\Kerf Studio\uninstall.exe" 0 +2
    ExecWait '"$LOCALAPPDATA\Kerf Studio\uninstall.exe" /S'
  ExecWait '"$INSTDIR\kerf.exe" --install-panels'
  ; Kerf has no window of its own: no Desktop or Start menu shortcuts (it's opened from the editors' panels)
  Delete "$DESKTOP\Kerf.lnk"
  Delete "$SMPROGRAMS\Kerf.lnk"
  Delete "$SMPROGRAMS\Kerf\Kerf.lnk"
  RMDir "$SMPROGRAMS\Kerf"
  Delete "$DESKTOP\Kerf Studio.lnk"
  Delete "$SMPROGRAMS\Kerf Studio.lnk"
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  RMDir /r "$APPDATA\Adobe\CEP\extensions\com.kerf.aftereffects"
  Delete "$APPDATA\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\Kerf.py"
  Delete "$PROFILE\.kerf\panels-version"
  Delete "$PROFILE\.kerf\ofx-version"
  RMDir /r "$LOCALAPPDATA\Kerf\OFX"
  ; OFX_PLUGIN_PATH: take out only Kerf's folder, keep other plugins' folders, drop the variable if nothing is left
  nsExec::Exec `powershell -NoProfile -NonInteractive -Command "$$d = Join-Path $$env:LOCALAPPDATA 'Kerf\OFX'; $$v = [Environment]::GetEnvironmentVariable('OFX_PLUGIN_PATH', 'User'); if ($$v) { $$p = @($$v -split ';' | Where-Object { $$_ -and $$_.TrimEnd('\') -ne $$d }); [Environment]::SetEnvironmentVariable('OFX_PLUGIN_PATH', $$(if ($$p) { $$p -join ';' } else { $$null }), 'User') }"`
  Pop $0
!macroend
