; Kerf installer hooks (Windows). Kerf has no app window: installing it puts the Kerf panels into
; Premiere Pro, After Effects and DaVinci Resolve. Kerf 0.3 replaces the old "Kerf Studio" app.

!macro NSIS_HOOK_POSTINSTALL
  IfFileExists "$LOCALAPPDATA\Kerf Studio\uninstall.exe" 0 +2
    ExecWait '"$LOCALAPPDATA\Kerf Studio\uninstall.exe" /S'
  ExecWait '"$INSTDIR\kerf.exe" --install-panels'
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  RMDir /r "$APPDATA\Adobe\CEP\extensions\com.kerf.aftereffects"
  Delete "$APPDATA\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\Kerf.py"
  Delete "$PROFILE\.kerf\panels-version"
!macroend
