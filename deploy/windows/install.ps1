#Requires -Version 5.1
<#
    Installation de « Gestion Stockage Camping-Cars » sur ce PC Windows.

    Depuis le dossier du projet, dans PowerShell :
        powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1

    Le script peut être relancé sans risque : il ne refait que ce qui manque.
    Voir docs/INSTALLATION-WINDOWS.md pour le détail.
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

# --- 1. Python ---------------------------------------------------------------------
Step "Vérification de Python (3.12 ou plus récent)"
$Python = $null
# Probes may fail (no Python yet): do not let PowerShell stop the script on their error output.
$ErrorActionPreference = "Continue"
if (Get-Command py -ErrorAction SilentlyContinue) {
    $Python = (& py -3 -c "import sys; print(sys.executable)" 2>$null)
}
if (-not $Python -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $Python = (& python -c "import sys; print(sys.executable)" 2>$null)
}
$ErrorActionPreference = "Stop"
if (-not $Python) {
    throw "Python est introuvable. Installez Python 3.12 depuis python.org (cochez « Add python.exe to PATH »), puis relancez ce script."
}
$Version = [version](& $Python -c "import sys; print('%d.%d' % sys.version_info[:2])")
if ($Version -lt [version]"3.12") { throw "Python $Version est trop ancien : installez Python 3.12 ou plus récent." }
Write-Host "Python $Version : $Python"

# --- 2. Environnement Python et dépendances ----------------------------------------
Step "Installation des dépendances (quelques minutes la première fois)"
if (-not (Test-Path $VenvPython)) { Invoke-Checked $Python @("-m", "venv", ".venv") }
Invoke-Checked $VenvPython @("-m", "pip", "install", "--upgrade", "pip", "--quiet")
Invoke-Checked $VenvPython @("-m", "pip", "install", "-r", "requirements.txt", "--quiet")

# --- 3. Bibliothèques pour les PDF (MSYS2 / Pango) ---------------------------------
Step "Bibliothèques nécessaires aux factures PDF"
$PangoDir = "C:\msys64\mingw64\bin"
if (Test-Path (Join-Path $PangoDir "libpango-1.0-0.dll")) {
    Write-Host "Pango trouvé dans $PangoDir"
} else {
    $PangoDir = ""
    Warn "Pango est introuvable : les factures PDF ne pourront pas être générées. Suivez l'étape « MSYS2 » de docs/INSTALLATION-WINDOWS.md, puis relancez ce script."
}

# --- 4. Fichier de configuration .env ------------------------------------------------
Step "Configuration (.env)"
$EnvFile = Join-Path $Root ".env"
if (Test-Path $EnvFile) {
    Write-Host ".env existe déjà : il n'est pas modifié."
    if ($PangoDir -and -not (Select-String -Path $EnvFile -Pattern "^WEASYPRINT_DLL_DIRECTORIES=." -Quiet)) {
        Warn "Ajoutez la ligne  WEASYPRINT_DLL_DIRECTORIES=$PangoDir  dans .env"
    }
} else {
    if ($env:OneDrive) { $DefaultBackup = Join-Path $env:OneDrive "Sauvegardes Stockage" }
    else { $DefaultBackup = Join-Path $env:USERPROFILE "Documents\Sauvegardes Stockage" }
    $BackupDir = Read-Host "Dossier des sauvegardes (idéalement un dossier synchronisé : OneDrive, Google Drive...)`n[Entrée = $DefaultBackup]"
    if (-not $BackupDir) { $BackupDir = $DefaultBackup }
    $Secret = (& $VenvPython -c "import secrets; print(secrets.token_urlsafe(50))")
    $Lines = @(
        "# Configuration de Gestion Stockage Camping-Cars sur ce PC. Ne jamais partager ce fichier.",
        "DJANGO_SECRET_KEY=$Secret",
        "DJANGO_DEBUG=False",
        "DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1",
        "DJANGO_HTTPS=False",
        "APP_PORT=8000",
        "BACKUP_DIR=$BackupDir",
        "WEASYPRINT_DLL_DIRECTORIES=$PangoDir",
        "",
        "# Envoi des emails (rappels, factures) : à compléter, voir docs/INSTALLATION-WINDOWS.md",
        "EMAIL_HOST=",
        "EMAIL_PORT=587",
        "EMAIL_HOST_USER=",
        "EMAIL_HOST_PASSWORD=",
        "EMAIL_USE_TLS=True",
        "DEFAULT_FROM_EMAIL="
    )
    # UTF-8 without BOM: a BOM would corrupt the first line for Python.
    [System.IO.File]::WriteAllLines($EnvFile, $Lines, (New-Object System.Text.UTF8Encoding $false))
    Write-Host ".env créé. Pensez à compléter la partie « Envoi des emails »."
}

# --- 5. Base de données et fichiers statiques ----------------------------------------
Step "Base de données"
New-Item -ItemType Directory -Force -Path (Join-Path $Root "logs") | Out-Null
Invoke-Checked $VenvPython @("manage.py", "migrate", "--noinput")
Invoke-Checked $VenvPython @("manage.py", "collectstatic", "--noinput", "--verbosity", "0")

$UserCount = (& $VenvPython manage.py shell --verbosity 0 -c "from django.contrib.auth.models import User; print(User.objects.count())" | Select-Object -Last 1)
if ($UserCount -eq "0") {
    Step "Création du premier utilisateur (administrateur)"
    Invoke-Checked $VenvPython @("manage.py", "createsuperuser")
}

Step "Test de génération d'un PDF"
$ErrorActionPreference = "Continue"  # a failure here is reported, not fatal
& $VenvPython manage.py shell --verbosity 0 -c "from weasyprint import HTML; HTML(string='<p>test</p>').write_pdf(); print('PDF : OK')"
$PdfOk = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = "Stop"
if (-not $PdfOk) { Warn "La génération de PDF ne fonctionne pas encore (voir l'étape MSYS2 du guide)." }

# --- 6. Tâches planifiées ------------------------------------------------------------
Step "Tâches planifiées (démarrage, rappels 08:00, sauvegarde 19:00)"
function Register-StockageTask([string]$Name, $Trigger, [string]$Arguments, [string]$Description, [bool]$Forever) {
    $Action = New-ScheduledTaskAction -Execute $VenvPythonw -Argument $Arguments -WorkingDirectory $Root
    $Limit = if ($Forever) { [TimeSpan]::Zero } else { New-TimeSpan -Hours 1 }
    # StartWhenAvailable: if the PC was off at the planned time, run as soon as possible.
    $Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -ExecutionTimeLimit $Limit -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $Name -Action $Action -Trigger $Trigger -Settings $Settings `
        -Description $Description -Force | Out-Null
    Write-Host "Tâche « $Name » enregistrée."
}
$AppStartedByTask = $true
try {
    Register-StockageTask $AppTask (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME) `
        "`"$Root\deploy\windows\run_server.py`"" "Démarre l'application sur http://localhost:8000" $true
} catch {
    # Some Windows setups only allow "at logon" tasks from an administrator PowerShell:
    # fall back to a shortcut in the user's Startup folder, which needs no special rights.
    $AppStartedByTask = $false
    $Startup = [Environment]::GetFolderPath("Startup")
    $Link = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $Startup "Gestion Stockage (serveur).lnk"))
    $Link.TargetPath = $VenvPythonw
    $Link.Arguments = "`"$Root\deploy\windows\run_server.py`""
    $Link.WorkingDirectory = $Root
    $Link.Save()
    Write-Host "Démarrage automatique via le dossier Démarrage de Windows (tâche refusée : $($_.Exception.Message))."
}
Register-StockageTask $RemindersTask (New-ScheduledTaskTrigger -Daily -At "08:00") `
    "`"$Root\deploy\windows\run_task.py`" send_reminders" "Rappels de fin de stockage" $false
Register-StockageTask $BackupTask (New-ScheduledTaskTrigger -Daily -At "19:00") `
    "`"$Root\deploy\windows\run_task.py`" backup_data" "Sauvegarde quotidienne" $false

# --- 7. Raccourci et démarrage -------------------------------------------------------
Step "Raccourci sur le bureau et démarrage"
$Port = (Select-String -Path $EnvFile -Pattern "^APP_PORT=(\d+)" | ForEach-Object { $_.Matches[0].Groups[1].Value } | Select-Object -First 1)
if (-not $Port) { $Port = "8000" }
$Url = "http://localhost:$Port/"
$Shortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "Gestion Stockage.url"
[System.IO.File]::WriteAllLines($Shortcut, @("[InternetShortcut]", "URL=$Url"))
if ($AppStartedByTask) {
    Stop-ScheduledTask -TaskName $AppTask -ErrorAction SilentlyContinue
    Start-ScheduledTask -TaskName $AppTask
} else {
    Start-Process -FilePath $VenvPythonw -ArgumentList "`"$Root\deploy\windows\run_server.py`"" -WorkingDirectory $Root
}
Start-Sleep -Seconds 4
Start-Process $Url

Write-Host ""
Write-Host "Installation terminée. L'application est ouverte dans le navigateur : $Url" -ForegroundColor Green
Write-Host "Elle démarrera toute seule à chaque ouverture de session Windows."
