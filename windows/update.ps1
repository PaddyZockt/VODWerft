# VODWerft - Update: spielt geaenderte Skripte aus "app" nach C:\Program Files\VODWerft
# und startet Watcher und Status-Dienst neu. Bricht ab, wenn gerade gerendert wird.
$ErrorActionPreference = 'Stop'
$quelle = $PSScriptRoot
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" $($args -join ' ')"
    exit
}
Start-Transcript -Path (Join-Path $quelle 'update.log') -Force | Out-Null
try {
    $app = Join-Path $env:ProgramFiles 'VODWerft'
    if (-not (Test-Path "$app\venv\Scripts\python.exe")) { throw "Programm nicht installiert." }
    if ((Get-Process -Name ffmpeg -ErrorAction SilentlyContinue) -and ($args -notcontains '-Force')) {
        throw "Gerade läuft ein Render (ffmpeg). Bitte später erneut ausführen."
    }
    $sicher = Join-Path $env:LOCALAPPDATA ('VODWerft\update-backup\' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
    New-Item -ItemType Directory -Force $sicher | Out-Null
    Write-Host "1/4 Alten Stand sichern nach $sicher ..."
    robocopy "$app\vodwerft" "$sicher\vodwerft" /E /NFL /NDL /NJH /NJS /NP | Out-Null
    Copy-Item "$app\start.ps1" $sicher -ErrorAction SilentlyContinue

    Write-Host "2/4 Dienste anhalten ..."
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'watch_folder\.py|status_report\.py' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 4

    Write-Host "3/4 Neue Dateien kopieren ..."
    robocopy "$quelle\app\vodwerft" "$app\vodwerft" /E /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy Fehler $LASTEXITCODE" }
    Copy-Item "$quelle\app\start.ps1" "$app\start.ps1" -Force
    Copy-Item "$quelle\app\vodwerft.ico" "$app\vodwerft.ico" -Force

    Write-Host "4/4 Neu starten und prüfen ..."
    Start-Process (Get-Command powershell.exe).Source -WindowStyle Hidden -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$app\start.ps1`""
    Start-Sleep -Seconds 25
    $st = Get-Item (Join-Path $env:LOCALAPPDATA 'VODWerft\production\tray-status.json')
    $alter = [int]((Get-Date) - $st.LastWriteTime).TotalSeconds
    $n = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'watch_folder\.py' }).Count
    Write-Host "    Watcher-Prozesse: $n | tray-status.json zuletzt vor $alter s"
    if ($n -ge 1 -and $alter -lt 60) { Write-Host "Fertig: Das Update ist installiert." } else { Write-Host "Achtung: Das Update ist nicht sauber angelaufen. Der alte Stand liegt in $sicher" -ForegroundColor Yellow }
} catch {
    Write-Host "FEHLER: $_" -ForegroundColor Red
} finally {
    Stop-Transcript | Out-Null
    Read-Host "Enter zum Schliessen"
}
