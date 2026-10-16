#Requires -Version 5.1
<#
    Mise à jour de « Gestion Stockage Camping-Cars » après avoir remplacé les fichiers du projet
    (git pull, ou copie d'une nouvelle version du dossier sans toucher à .env, db.sqlite3,
    media\ et logs\).

        powershell -ExecutionPolicy Bypass -File deploy\windows\update.ps1
#>
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$VenvPythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"
$AppTask = "Stockage - application"
$RemindersTask = "Stockage - rappels"
$BackupTask = "Stockage - sauvegarde"

function Step([string]$Text) {
    Write-Host ""
    Write-Host "==> $Text" -ForegroundColor Cyan
}

function Warn([string]$Text) {
    Write-Host "ATTENTION : $Text" -ForegroundColor Yellow
}

# Run a program and stop the script if it fails (PowerShell does not do it by itself).
function Invoke-Checked([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Échec de la commande : $Exe $($Arguments -join ' ')" }
}

Step "Sauvegarde avant la mise à jour"
Invoke-Checked $VenvPython @("manage.py", "backup_data")

Step "Arrêt de l'application"
Stop-ScheduledTask -TaskName $AppTask -ErrorAction SilentlyContinue
# Also stops a server started from the Startup folder (see install.ps1).
Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" |
    Where-Object { $_.CommandLine -like "*run_server.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

if ((Test-Path (Join-Path $Root ".git")) -and (Get-Command git -ErrorAction SilentlyContinue)) {
    Step "Téléchargement de la nouvelle version (git pull)"
    Invoke-Checked "git" @("pull")
}

Step "Dépendances, base de données, fichiers statiques"
Invoke-Checked $VenvPython @("-m", "pip", "install", "-r", "requirements.txt", "--quiet")
Invoke-Checked $VenvPython @("manage.py", "migrate", "--noinput")
Invoke-Checked $VenvPython @("manage.py", "collectstatic", "--noinput", "--verbosity", "0")

Step "Redémarrage de l'application"
if (Get-ScheduledTask -TaskName $AppTask -ErrorAction SilentlyContinue) {
    Start-ScheduledTask -TaskName $AppTask
} else {
    Start-Process -FilePath $VenvPythonw -ArgumentList "`"$Root\deploy\windows\run_server.py`"" -WorkingDirectory $Root
}
Write-Host "Mise à jour terminée." -ForegroundColor Green
