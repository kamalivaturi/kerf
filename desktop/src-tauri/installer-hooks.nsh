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
  RMDir /r "$LOCALAPPDATA\Kerf\OFX"
  ; OFX_PLUGIN_PATH: remove it only when Kerf FX is all it points to (other plugins may share it)
  ReadRegStr $0 HKCU "Environment" "OFX_PLUGIN_PATH"
  StrCmp $0 "$LOCALAPPDATA\Kerf\OFX" 0 +2
    DeleteRegValue HKCU "Environment" "OFX_PLUGIN_PATH"
!macroend
