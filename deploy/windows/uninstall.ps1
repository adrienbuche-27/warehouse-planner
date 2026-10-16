#Requires -Version 5.1
<#
    Retire les tâches planifiées et le raccourci. Les données (db.sqlite3, media\, sauvegardes)
    ne sont PAS supprimées.

        powershell -ExecutionPolicy Bypass -File deploy\windows\uninstall.ps1
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

foreach ($Name in @($AppTask, $RemindersTask, $BackupTask)) {
    Stop-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Tâche « $Name » retirée."
}
Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" |
    Where-Object { $_.CommandLine -like "*run_server.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Remove-Item (Join-Path ([Environment]::GetFolderPath("Desktop")) "Gestion Stockage.url") -ErrorAction SilentlyContinue
Remove-Item (Join-Path ([Environment]::GetFolderPath("Startup")) "Gestion Stockage (serveur).lnk") -ErrorAction SilentlyContinue
Write-Host "Terminé. Les données sont conservées dans $Root." -ForegroundColor Green
