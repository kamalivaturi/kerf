# Installs the Kerf script into DaVinci Resolve (Workspace > Scripts > Kerf). Free and Studio.
$ErrorActionPreference = "Stop"
$kerf = (Resolve-Path "$PSScriptRoot\..").Path
$dest = Join-Path $env:APPDATA "Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility"
New-Item -ItemType Directory -Force $dest | Out-Null
$src = Get-Content "$kerf\resolve\Kerf.py" -Raw -Encoding utf8  # PS 5.1 reads ANSI otherwise
$src = $src.Replace('os.environ.get("KERF_HOME", r"C:\Kerf")', "os.environ.get(`"KERF_HOME`", r`"$kerf`")")
# UTF-8 without a byte-order mark: PS 5.1's Set-Content -Encoding utf8 adds one, and Resolve's Python then fails on line 1
[IO.File]::WriteAllText((Join-Path $dest "Kerf.py"), $src, (New-Object Text.UTF8Encoding $false))
Write-Host "Installed to $dest. In Resolve: Workspace > Scripts > Kerf"
