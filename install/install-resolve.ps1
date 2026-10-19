# Installs the Kerf script into DaVinci Resolve (Workspace > Scripts > Kerf). Free and Studio.
$ErrorActionPreference = "Stop"
$kerf = (Resolve-Path "$PSScriptRoot\..").Path
$dest = Join-Path $env:APPDATA "Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility"
New-Item -ItemType Directory -Force $dest | Out-Null
$src = Get-Content "$kerf\resolve\Kerf.py" -Raw
$src = $src.Replace('os.environ.get("KERF_HOME", r"C:\Kerf")', "os.environ.get(`"KERF_HOME`", r`"$kerf`")")
Set-Content -Path (Join-Path $dest "Kerf.py") -Value $src -Encoding utf8
Write-Host "Installed to $dest. In Resolve: Workspace > Scripts > Kerf"
