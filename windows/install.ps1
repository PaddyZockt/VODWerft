# VODWerft - Installation (Schritt A: Programm + Python-Umgebung)
# Fasst das laufende System NICHT an. Kopiert nur nach C:\Program Files\VODWerft
$ErrorActionPreference = 'Stop'
$quelle = $PSScriptRoot
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}
Start-Transcript -Path (Join-Path $quelle 'install.log') -Force | Out-Null
try {
    $ziel = Join-Path $env:ProgramFiles 'VODWerft'
    Write-Host "1/7 Voraussetzungen prüfen ..."
    function Finde($name, $pfade) {
        $c = (Get-Command $name -ErrorAction SilentlyContinue).Source
        if ($c) { return $c }
        foreach ($p in $pfade) { $t = Get-ChildItem $p -ErrorAction SilentlyContinue | Select-Object -First 1; if ($t) { return $t.FullName } }
        return $null
    }
    function Biete($titel, $paketId) {
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { Write-Host "    $titel fehlt. Bitte von Hand installieren." -ForegroundColor Yellow; return }
        $antwort = Read-Host "    $titel fehlt. Jetzt mit winget installieren? (j/n)"
        if ($antwort -match '^[jJyY]') { winget install --id=$paketId -e --accept-source-agreements --accept-package-agreements }
        else { Write-Host "    Übersprungen. Ohne $titel läuft die Verarbeitung später nicht." -ForegroundColor Yellow }
    }
    if (-not (Finde 'uv' @("$env:USERPROFILE\.local\bin\uv.exe", "$env:LOCALAPPDATA\Programs\uv\uv.exe"))) { Biete 'uv (Python-Verwaltung)' 'astral-sh.uv' }
    if (-not (Finde 'ffmpeg' @("$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Gyan.FFmpeg*\*\bin\ffmpeg.exe"))) { Biete 'ffmpeg (Videobearbeitung)' 'Gyan.FFmpeg' }
    if (-not (Finde 'ollama' @("$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"))) { Biete 'Ollama (KI-Modelle)' 'Ollama.Ollama' }
    $gpu = (Get-Command nvidia-smi -ErrorAction SilentlyContinue)
    if ($gpu) {
        $mb = [int]((& nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | Select-Object -First 1).Trim())
        if ($mb -lt 15500) { Write-Host "    Grafikspeicher: $([math]::Round($mb/1024)) GB. Empfohlen sind 16 GB, sonst kann es langsam sein oder scheitern." -ForegroundColor Yellow }
        else { Write-Host "    Grafikkarte OK ($([math]::Round($mb/1024)) GB)." }
    } else { Write-Host "    Keine NVIDIA-Grafikkarte erkannt. Die Videoverarbeitung braucht eine NVIDIA-Karte mit 16 GB Grafikspeicher." -ForegroundColor Yellow }

    Write-Host "2/7 Programmdateien nach $ziel kopieren ..."
    robocopy "$quelle\app" $ziel /E /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy Fehler $LASTEXITCODE" }

    Write-Host "3/7 Tray-Symbol bauen ..."
    & (Join-Path $quelle 'tray-src\build.ps1') -Ziel (Join-Path $ziel 'tray')

    Write-Host "4/7 uv (Python-Paketverwaltung) suchen ..."
    $uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
    if (-not $uv) {
        foreach ($p in @("$env:USERPROFILE\.local\bin\uv.exe", "$env:LOCALAPPDATA\Programs\uv\uv.exe", "$env:LOCALAPPDATA\Microsoft\WinGet\Links\uv.exe")) {
            if (Test-Path $p) { $uv = $p; break }
        }
    }
    if (-not $uv) { throw "uv nicht gefunden. Bitte zuerst installieren (PowerShell: winget install --id=astral-sh.uv -e) und install.bat danach erneut starten." }
    Write-Host "    uv: $uv"

    Write-Host "5/7 Python-Umgebung aufbauen (lädt einige GB, dauert einige Minuten) ..."
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $ziel 'venv'
    & $uv sync --frozen --project (Join-Path $ziel 'nightcut')
    if ($LASTEXITCODE -ne 0) { throw "uv sync Fehler $LASTEXITCODE" }

    Write-Host "6/7 Autostart und Verknüpfungen anlegen ..."
    $ps = (Get-Command powershell.exe).Source
    $ico = Join-Path $ziel 'vodwerft\vodwerft.ico'
    $ws = New-Object -ComObject WScript.Shell
    $verknuepfungen = @((Join-Path ([Environment]::GetFolderPath('Startup')) 'VODWerft.lnk'),
                        (Join-Path ([Environment]::GetFolderPath('Desktop')) 'VODWerft.lnk'),
                        (Join-Path ([Environment]::GetFolderPath('Programs')) 'VODWerft.lnk'))
    foreach ($pfad in $verknuepfungen) {
        $l = $ws.CreateShortcut($pfad); $l.TargetPath = $ps
        $l.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ziel\start.ps1`""
        $l.WorkingDirectory = $ziel; $l.IconLocation = $ico; $l.WindowStyle = 7; $l.Save()
    }

    Write-Host "7/7 Kurztest ..."
    & (Join-Path $ziel 'venv\Scripts\python.exe') -c "import nightcut, torch, transformers; print('OK: nightcut', nightcut.__file__, '| torch', torch.__version__, '| CUDA', torch.cuda.is_available())"
    if ($LASTEXITCODE -ne 0) { throw "Kurztest fehlgeschlagen" }
    Write-Host "Fertig. VODWerft startest du über das Desktop-Symbol. Beim ersten Start öffnet sich die Einrichtung."
} catch {
    Write-Host "FEHLER: $_" -ForegroundColor Red
} finally {
    Stop-Transcript | Out-Null
    Read-Host "Enter zum Schliessen"
}
