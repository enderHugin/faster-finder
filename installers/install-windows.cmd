@echo off
rem Faster Finder - instalador para Windows (no necesita permisos de administrador ni Python).
rem Este archivo es un .cmd con un script de PowerShell dentro: lo extrae y lo ejecuta.
title Faster Finder - instalador
set "FF_SELF=%~f0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$t=[IO.File]::ReadAllText($env:FF_SELF); $i=$t.IndexOf('#'+'#PS##'); $p=Join-Path $env:TEMP 'faster-finder-setup.ps1'; [IO.File]::WriteAllText($p,$t.Substring($i),(New-Object Text.UTF8Encoding $true)); & powershell -NoProfile -ExecutionPolicy Bypass -File $p %*; exit $LASTEXITCODE"
set "FF_RC=%ERRORLEVEL%"
if not "%FF_RC%"=="0" pause
exit /b %FF_RC%
##PS##
# ---------------------------------------------------------------------------------------------
# Faster Finder - instalador de Windows.
# Todo va a carpetas del usuario: consigue un Python 3.12 propio con "uv" (no toca el Python que
# tengas instalado, si es que tienes alguno), crea su entorno y deja accesos directos y la entrada
# en "Aplicaciones instaladas". Volver a ejecutarlo actualiza. Para quitarlo: desde "Aplicaciones
# instaladas" de Windows, o ejecutando este archivo con "desinstalar".
# ---------------------------------------------------------------------------------------------
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }

$Base   = '__BASE_URL__'
$Root   = Join-Path $env:LOCALAPPDATA 'faster-finder'
$Prog   = Join-Path $env:LOCALAPPDATA 'Programs\faster-finder'
$Bin    = Join-Path $Root 'bin'
$Rt     = Join-Path $Root 'runtime'
$Stage  = Join-Path $Root 'stage'
$Venv   = Join-Path $Prog 'venv'
$RegKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\faster-finder'
$Total  = 5
$LogDir  = Join-Path $Root 'logs'
$LogFile = Join-Path $LogDir 'instalacion.log'
try { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null; Start-Transcript -Path $LogFile -Append -Force | Out-Null } catch { }

function Step([int]$n, [string]$text) {
    Write-Host ''
    Write-Host ("[{0}/{1}] {2}" -f $n, $Total, $text) -ForegroundColor Cyan
}
function Say([string]$text) { Write-Host ('      ' + $text) }

function Get-File([string]$url, [string]$dest) {
    # Hasta 3 intentos con espera creciente: una descarga a medias no deja un archivo roto.
    $last = $null
    for ($try = 1; $try -le 3; $try++) {
        try {
            if (Test-Path $dest) { Remove-Item $dest -Force -ErrorAction SilentlyContinue }
            Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $dest -TimeoutSec 180
            if ((Get-Item $dest -ErrorAction SilentlyContinue).Length -gt 0) { return }
            throw 'el archivo descargado esta vacio'
        } catch {
            $last = $_
            Start-Sleep -Seconds (2 * $try)
        }
    }
    throw ("No se pudo descargar " + $url + " (" + $last.Exception.Message + "). Comprueba tu conexion a internet.")
}

# Ejecuta un programa nativo sin que su salida por stderr tire abajo el instalador.
function Run-Native([string]$exe, [string[]]$nativeArgs) {
    $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { $o = & $exe @nativeArgs 2>&1 | ForEach-Object { [string]$_ }; $rc = $LASTEXITCODE }
    catch { $o = @([string]$_); $rc = 99 }
    $ErrorActionPreference = $old
    foreach ($l in $o) { if ($l.Trim()) { Write-Host ('      ' + $l) } }
    return $rc
}

function Stop-Running {
    try {
        $pat = '*' + [Management.Automation.WildcardPattern]::Escape($Prog) + '*faster_finder.py*'
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -and $_.Name -like 'python*' -and $_.CommandLine -like $pat -and $_.ProcessId -ne $PID } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    } catch { }
}

function Show-Box([string]$text, [string]$icon) {
    try {
        Add-Type -AssemblyName System.Windows.Forms
        [void][Windows.Forms.MessageBox]::Show($text, 'Faster Finder', 'OK', $icon)
    } catch { }
}

# ---- "desinstalar" directo ---------------------------------------------------------------------
if ($args.Count -ge 1 -and $args[0] -eq 'desinstalar') {
    $u = Join-Path $Root 'uninstall.ps1'
    if (Test-Path $u) { & powershell -NoProfile -ExecutionPolicy Bypass -File $u }
    else { Write-Host '  Faster Finder no parece estar instalado.' }
    try { Stop-Transcript | Out-Null } catch { }
    exit 0
}

try {
    Write-Host ''
    Write-Host '  ==============================' -ForegroundColor Yellow
    Write-Host '        Faster Finder'             -ForegroundColor Yellow
    Write-Host '  ==============================' -ForegroundColor Yellow
    Write-Host '  Se instala solo para tu usuario. No hace falta Python ni permisos de administrador.'
    Say ('registro de esta instalacion: ' + $LogFile)
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'Faster Finder necesita un Windows de 64 bits.' }
    New-Item -ItemType Directory -Force -Path $Root, $Bin, $Rt, $Stage, $Prog | Out-Null
    Stop-Running

    # --- 1) uv: gestor de Python de un solo archivo ------------------------------------------------
    Step 1 'Preparando el gestor de Python (uv)'
    $uv = Join-Path $Bin 'uv.exe'
    $uvOk = $false
    if (Test-Path $uv) { & $uv --version *> $null; $uvOk = ($LASTEXITCODE -eq 0) }
    if ($uvOk) { Say 'ya estaba instalado' } else {
        $zip = Join-Path $Root 'uv.zip'
        Get-File 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' $zip
        $tmp = Join-Path $Root 'uv-tmp'
        if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
        Expand-Archive -Path $zip -DestinationPath $tmp -Force
        $found = Get-ChildItem -Path $tmp -Recurse -Filter 'uv.exe' | Select-Object -First 1
        if (-not $found) { throw 'El archivo descargado de uv no contiene uv.exe.' }
        Copy-Item $found.FullName $uv -Force
        Remove-Item -Recurse -Force $tmp, $zip
        Say 'listo'
    }

    # --- 2) Python 3.12 propio (con tkinter) -------------------------------------------------------
    Step 2 'Preparando Python 3.12'
    $env:UV_PYTHON_INSTALL_DIR = $Rt
    $env:UV_CACHE_DIR = Join-Path $Root 'cache'
    $env:UV_PYTHON_PREFERENCE = 'only-managed'
    $env:UV_NO_PROGRESS = '1'
    $rc = Run-Native $uv @('python', 'install', '3.12')
    $py = $null
    if ($rc -eq 0) {
        $f = & $uv python find 3.12
        if ($LASTEXITCODE -eq 0 -and $f) { $py = ([string]@($f)[0]).Trim() }
    }
    if (-not $py -or -not (Test-Path $py)) {
        throw 'No se pudo conseguir Python 3.12. Puede ser el antivirus (que borra archivos al descomprimirlos) o un proxy o cortafuegos que bloquea GitHub. Revisa el registro de la instalacion y vuelve a intentarlo.'
    }
    Say $py
    $tkOk = $false
    & $py -c "import tkinter; tkinter.Tcl()" *> $null
    if ($LASTEXITCODE -eq 0) { $tkOk = $true }
    if (-not $tkOk) { throw 'El Python descargado no trae tkinter funcionando (Tcl/Tk). Vuelve a ejecutar el instalador.' }

    # --- 3) el programa ----------------------------------------------------------------------------
    Step 3 'Descargando Faster Finder'
    foreach ($f in @('faster_finder.py', 'VERSION')) { Get-File ($Base + '/' + $f) (Join-Path $Stage $f) }
    $version = (Get-Content (Join-Path $Stage 'VERSION') -Raw).Trim()
    Say ('version ' + $version)

    # --- 4) entorno y archivos del programa --------------------------------------------------------
    Step 4 'Preparando el entorno'
    Copy-Item (Join-Path $Stage 'faster_finder.py') (Join-Path $Prog 'faster_finder.py') -Force
    $vpy  = Join-Path $Venv 'Scripts\python.exe'
    $vpyw = Join-Path $Venv 'Scripts\pythonw.exe'
    if (-not (Test-Path $vpyw)) {
        if (Test-Path $Venv) { Remove-Item -LiteralPath $Venv -Recurse -Force -ErrorAction SilentlyContinue }
        $rc = Run-Native $uv @('venv', '--python', $py, $Venv)
        if ($rc -ne 0 -or -not (Test-Path $vpyw)) { throw 'no se pudo crear el entorno de Python' }
    } else { Say 'el entorno ya estaba' }

    # --- 5) accesos directos, desinstalador y comprobacion ----------------------------------------
    Step 5 'Terminando: accesos directos y desinstalador'
    $sh = New-Object -ComObject WScript.Shell
    foreach ($dir in @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop'))) {
        $s = $sh.CreateShortcut((Join-Path $dir 'Faster Finder.lnk'))
        $s.TargetPath = $vpyw
        $s.Arguments = '"faster_finder.py"'
        $s.WorkingDirectory = $Prog
        $s.Description = 'Faster Finder'
        $s.Save()
    }

    $smoke = $null; $smokeRc = 1
    $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { $smoke = (& $vpy -c "import tkinter; tkinter.Tcl(); print('FF_OK')" 2>&1 | Out-String); $smokeRc = $LASTEXITCODE } catch { $smoke = [string]$_ }
    $ErrorActionPreference = $old
    if ($smokeRc -ne 0 -or $smoke -notmatch 'FF_OK') {
        try { Stop-Transcript | Out-Null } catch { }
        Show-Box ("Faster Finder se ha instalado, pero no arranca en este equipo.`n`nRegistro: " + $LogFile) 'Warning'
        exit 2
    }

    $un = @'
Add-Type -AssemblyName System.Windows.Forms
$r = [Windows.Forms.MessageBox]::Show('¿Desinstalar Faster Finder?', 'Faster Finder', 'YesNo', 'Question')
if ($r -ne 'Yes') { exit 0 }
try {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.Name -like 'python*' -and $_.CommandLine -like '__PROCPAT__' -and $_.ProcessId -ne $PID } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
} catch { }
Start-Sleep -Milliseconds 800
try { Remove-Item -LiteralPath (Join-Path ([Environment]::GetFolderPath('Programs')) 'Faster Finder.lnk') -Force -ErrorAction SilentlyContinue } catch { }
try { Remove-Item -LiteralPath (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Faster Finder.lnk') -Force -ErrorAction SilentlyContinue } catch { }
Remove-Item -LiteralPath '__PROG__' -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\faster-finder' -Recurse -Force -ErrorAction SilentlyContinue
Start-Process -WindowStyle Hidden -FilePath cmd.exe -ArgumentList '/c ping -n 4 127.0.0.1 >nul & rmdir /s /q "__ROOT__"'
[void][Windows.Forms.MessageBox]::Show('Faster Finder se ha desinstalado.', 'Faster Finder', 'OK', 'Information')
'@
    $procPat = '*' + [Management.Automation.WildcardPattern]::Escape($Prog) + '*faster_finder.py*'
    $un = $un.Replace('__PROG__', $Prog).Replace('__ROOT__', $Root).Replace('__PROCPAT__', $procPat)
    [IO.File]::WriteAllText((Join-Path $Root 'uninstall.ps1'), $un, (New-Object Text.UTF8Encoding $true))

    New-Item -Path $RegKey -Force | Out-Null
    $vals = @{
        DisplayName     = 'Faster Finder'
        DisplayVersion  = $version
        Publisher       = 'Faster Finder'
        InstallLocation = $Prog
        UninstallString = ('powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + (Join-Path $Root 'uninstall.ps1') + '"')
        URLInfoAbout    = $Base
    }
    foreach ($k in $vals.Keys) { New-ItemProperty -Path $RegKey -Name $k -Value $vals[$k] -PropertyType String -Force | Out-Null }
    New-ItemProperty -Path $RegKey -Name NoModify -Value 1 -PropertyType DWord -Force | Out-Null
    New-ItemProperty -Path $RegKey -Name NoRepair -Value 1 -PropertyType DWord -Force | Out-Null

    Remove-Item -Recurse -Force $Stage -ErrorAction SilentlyContinue

    Write-Host ''
    Write-Host '  Listo. Faster Finder esta instalado.' -ForegroundColor Green
    Write-Host '  Lo encuentras en el menu Inicio y en el escritorio. Se abre ahora.'
    Start-Process -FilePath $vpyw -ArgumentList '"faster_finder.py"' -WorkingDirectory $Prog
    try { Stop-Transcript | Out-Null } catch { }
    exit 0
}
catch {
    Write-Host ''
    Write-Host ('  ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    Show-Box ("No se pudo completar la instalacion:`n`n" + $_.Exception.Message + "`n`nPuedes volver a ejecutar el instalador.`n`nRegistro: " + $LogFile) 'Error'
    try { Stop-Transcript | Out-Null } catch { }
    exit 1
}
