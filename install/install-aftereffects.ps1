# Installs the Kerf panel into every After Effects on this PC (Window > Kerf.jsx). Asks for admin once:
# AE only loads ScriptUI panels from its Program Files folder.
$ErrorActionPreference = "Stop"
$kerf = (Resolve-Path "$PSScriptRoot\..").Path
$targets = Get-ChildItem "C:\Program Files\Adobe\Adobe After Effects *\Support Files\Scripts\ScriptUI Panels" -Directory -ErrorAction SilentlyContinue
if (-not $targets) { Write-Host "After Effects not found under C:\Program Files\Adobe."; exit 1 }
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
  Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
  exit $LASTEXITCODE
}
foreach ($t in $targets) {
  Copy-Item "$kerf\aftereffects\Kerf.jsx" $t.FullName -Force
  Write-Host "Installed to $($t.FullName)"
}
Write-Host "In After Effects: Edit > Preferences > Scripting & Expressions > Allow Scripts to Write Files and Access Network, then Window > Kerf.jsx"
