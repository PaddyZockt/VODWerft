# VODWerft - Start (Autostart): Watcher, Status-Dienst und Tray, jeweils nur einmal
$app  = $PSScriptRoot
$data = Join-Path $env:LOCALAPPDATA 'VODWerft'
$py   = Join-Path $app 'venv\Scripts\pythonw.exe'
$cfg  = Join-Path $data 'production\watcher.json'
$log  = Join-Path $data 'production\watcher.log'
function Laeuft($muster) {
    [bool](Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -match $muster })
}
$eingerichtet = Test-Path $cfg
if ($eingerichtet -and -not (Laeuft 'watch_folder\.py')) {
    Start-Process $py -WindowStyle Hidden -ArgumentList "-X utf8 -B -u `"$app\vodwerft\watch_folder.py`" `"$cfg`" --log `"$log`""
}
if ($eingerichtet -and -not (Laeuft 'status_report\.py')) {
    Start-Process $py -WindowStyle Hidden -ArgumentList "-X utf8 -B -u `"$app\vodwerft\status_report.py`" `"$cfg`""
}
# Direkt-Modus (VODWerft): der Upload-Worker laeuft auf diesem PC statt auf einem Server
if ($eingerichtet) {
    $c = Get-Content $cfg -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($c.upload_mode -eq 'direct' -and -not (Laeuft 'upload_worker\.py')) {
        $share = Split-Path $c.upload_incoming -Parent
        $env:UPLOAD_INCOMING_DIR = $c.upload_incoming
        $env:UPLOAD_UPLOADED_DIR = Join-Path $share 'Fertig'
        $env:UPLOAD_STATE_DIR    = Join-Path $share 'state'
        $env:UPLOAD_SECRETS_DIR  = Join-Path $share 'secrets'
        $env:UPLOAD_NOTICES_DIR  = Join-Path $share '.status'
        $env:FOOTER_FILE         = Join-Path $data 'config\description-footer.txt'
        $env:VERSION_FILE        = Join-Path $app 'VERSION'
        $env:UPLOAD_ENABLED = '1'; $env:ALLOW_PUBLISH = '1'; $env:SCHEDULE_ONLY = '1'
        $pyc = Join-Path $app 'venv\Scripts\python.exe'
        Start-Process $pyc -WindowStyle Hidden -ArgumentList "-X utf8 -B -u `"$app\vodwerft\upload_worker.py`"" `
            -RedirectStandardOutput (Join-Path $data 'production\upload-worker.log') -RedirectStandardError (Join-Path $data 'production\upload-worker.err.log')
    }
}
if (-not (Get-Process -Name 'VODWerft' -ErrorAction SilentlyContinue)) {
    Start-Process (Join-Path $app 'tray\VODWerft.exe') -ArgumentList '--tray'
}
