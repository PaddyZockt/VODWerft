# VODWerft - Tray-Programm bauen (kein Zusatzprogramm noetig: der C#-Compiler gehoert zu Windows)
# Aufruf: build.ps1 -Ziel "C:\Program Files\VODWerft\tray"
param([Parameter(Mandatory)][string]$Ziel)
$ErrorActionPreference = 'Stop'
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path $csc)) { throw "C#-Compiler nicht gefunden: $csc" }
New-Item -ItemType Directory -Force $Ziel | Out-Null
$exe = Join-Path $Ziel 'VODWerft.exe'
& $csc /nologo /target:winexe /optimize+ "/out:$exe" /r:System.Windows.Forms.dll /r:System.Drawing.dll /r:System.Web.Extensions.dll (Join-Path $PSScriptRoot 'NightcutTray.cs')
if ($LASTEXITCODE -ne 0) { throw "Tray konnte nicht gebaut werden (csc Fehler $LASTEXITCODE)" }
Write-Host "Tray gebaut: $exe"
