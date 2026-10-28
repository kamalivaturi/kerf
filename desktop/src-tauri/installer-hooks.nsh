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

!macro NSIS_HOOK_PREUNINSTALL
  ; the helper takes Kerf out of every editor with the same paths it installed to (kerf.exe --remove-panels):
  ; the Premiere plugin, the After Effects panel, Kerf FX and its OFX_PLUGIN_PATH entry (and any old Resolve script)
  ExecWait '"$INSTDIR\kerf.exe" --remove-panels'
!macroend
