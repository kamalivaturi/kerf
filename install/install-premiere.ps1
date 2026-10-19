# Installs the Kerf UXP plugin into Premiere Pro (25.6+) by opening the packaged .ccx with Creative Cloud.
# Developers: load ui\dist-uxp\manifest.json in the UXP Developer Tool instead (live reload with `npm run dev:uxp`).
$ErrorActionPreference = "Stop"
$kerf = (Resolve-Path "$PSScriptRoot\..").Path
$ccx = Get-ChildItem "$kerf\release\*.ccx" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime | Select-Object -Last 1
if (-not $ccx) {
  Write-Host "No .ccx found. Build it first:  python scripts\build_release.py"
  exit 1
}
Start-Process $ccx.FullName   # Creative Cloud's installer takes it from here
Write-Host "Opening $($ccx.Name) - confirm the install in Creative Cloud, then Window > UXP Plugins > Kerf in Premiere."
