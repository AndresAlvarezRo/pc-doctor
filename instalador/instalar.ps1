<#
.SYNOPSIS
    Instala pc-doctor en Windows 10/11 para tu usuario, SIN administrador.

.DESCRIPTION
    Ejecutalo con:   powershell -ExecutionPolicy Bypass -File instalar.ps1
    Muestra el plan, pide confirmación y deja pc-doctor funcionando: recolector, dashboard local (solo 127.0.0.1), reporte semanal y
    un acceso directo. Se puede volver a correr cuando quieras: actualiza lo que haya cambiado y no duplica nada.

    Si ya hay una versión instalada, la ACTUALIZA en el lugar (no reinstala): conserva toda tu carpeta de datos (base, configuración,
    memoria, token), hace antes una copia de la base y de config.json, aplica los cambios de esquema que hagan falta, agrega a
    config.json las opciones nuevas sin tocar las que ya tenías y actualiza el bloque de pc-doctor de tu CLAUDE.md sin pisar lo tuyo.

    Lo único que necesita administrador es el ayudante opcional (SMART detallado, BitLocker, Secure Boot, temperaturas): está en
    habilitar-sensores.ps1, aparte, y este script nunca lo ejecuta.

.PARAMETER Verificar
    No cambia nada: informa qué está instalado y funcionando, qué se puede medir y qué no.
.PARAMETER Desinstalar
    Quita las tareas, los accesos directos y el programa. NO borra tus datos (base, configuración, reportes, cuarentena).
.PARAMETER Simular
    Muestra qué haría y no cambia nada (si ya hay algo instalado: versión actual -> nueva, cambios de esquema y opciones nuevas).
#>
[CmdletBinding()]
param(
    [switch]$Verificar,
    [switch]$Desinstalar,
    [switch]$Simular
)

Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'

$Origen = $PSScriptRoot
$Destino = Join-Path $env:LOCALAPPDATA 'Programs\pc-doctor'
$Datos = Join-Path $env:LOCALAPPDATA 'pc-doctor'
$Herramientas = Join-Path $Destino 'herramientas'
$Puerto = 8787
$TareaRecolector = 'pc-doctor-recolector'
$TareaReporte = 'pc-doctor-reporte'
$TareaWeb = 'pc-doctor-web'
$Tareas = @($TareaRecolector, $TareaReporte, $TareaWeb)
$Usuario = [Security.Principal.WindowsIdentity]::GetCurrent().Name

function Escribir([string]$texto, [string]$color = 'Gray') { Write-Host $texto -ForegroundColor $color }
function Titulo([string]$texto) { Write-Host ''; Write-Host $texto -ForegroundColor Cyan }
function Bien([string]$texto) { Write-Host ("  [ok] " + $texto) -ForegroundColor Green }
function Aviso([string]$texto) { Write-Host ("  [!]  " + $texto) -ForegroundColor Yellow }
function Falla([string]$texto) { Write-Host ("  [x]  " + $texto) -ForegroundColor Red }

function Confirmar([string]$pregunta) {
    $r = Read-Host ($pregunta + ' Escribí SI para continuar')
    return ($r.Trim().ToUpper() -eq 'SI')
}

# versiones.toml solo tiene [secciones] y clave = "valor": alcanza con leerlo línea por línea.
function LeerVersiones([string]$ruta) {
    $res = @{}
    $seccion = ''
    foreach ($linea in Get-Content -LiteralPath $ruta -Encoding UTF8) {
        $l = $linea.Trim()
        if ($l -eq '' -or $l.StartsWith('#')) { continue }
        if ($l -match '^\[([a-z0-9_]+)\]$') { $seccion = $Matches[1]; $res[$seccion] = @{}; continue }
        if ($l -match '^([a-z0-9_]+)\s*=\s*"([^"]*)"') { $res[$seccion][$Matches[1]] = $Matches[2] }
    }
    return $res
}

# Solo se descarga de github.com y solo si el SHA-256 coincide con el de versiones.toml; si no, se borra y se corta.
function Descargar([string]$url, [string]$destino, [string]$sha256) {
    if (-not $url.StartsWith('https://github.com/')) { throw "Dirección no permitida (solo https://github.com/): $url" }
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $destino
    $real = (Get-FileHash -Algorithm SHA256 -LiteralPath $destino).Hash.ToLower()
    if ($real -ne $sha256.ToLower()) {
        Remove-Item -LiteralPath $destino -Force
        throw "El SHA-256 de lo descargado no coincide.`n  esperado: $sha256`n  recibido: $real`nNo se instaló nada de esto."
    }
    Bien "descargado y verificado (SHA-256 $real)"
}

# Corre un programa nativo sin que lo que escriba por stderr corte el script (Windows PowerShell 5.1 lo trata como error con 'Stop').
function Nativo([string]$exe, [string[]]$argumentos) {
    $antes = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $salida = & $exe @argumentos 2>&1 | Out-String
        return @{ Codigo = $LASTEXITCODE; Salida = $salida }
    } finally { $ErrorActionPreference = $antes }
}

function BuscarUv {
    $propio = Join-Path $Herramientas 'uv.exe'
    if (Test-Path -LiteralPath $propio) { return $propio }
    $c = Get-Command uv -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    return $null
}

function BuscarClaude {
    $c = Get-Command claude -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    $nativo = Join-Path $env:USERPROFILE '.local\bin\claude.exe'
    if (Test-Path -LiteralPath $nativo) { return $nativo }
    return $null
}

function PythonDelPrograma { return (Join-Path $Destino '.venv\Scripts\python.exe') }
function PythonwDelPrograma { return (Join-Path $Destino '.venv\Scripts\pythonw.exe') }

function Dashboard-Responde {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Puerto/api/config" -TimeoutSec 3
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

function EsperarDashboard([int]$segundos) {
    $limite = (Get-Date).AddSeconds($segundos)
    while ((Get-Date) -lt $limite) {
        if (Dashboard-Responde) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function QuitarTarea([string]$nombre) {
    if (Get-ScheduledTask -TaskName $nombre -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $nombre -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $nombre -Confirm:$false
        Bien "tarea $nombre quitada"
    }
}

function RutasAccesos {
    return @((Join-Path ([Environment]::GetFolderPath('Desktop')) 'pc-doctor.lnk'),
             (Join-Path ([Environment]::GetFolderPath('Programs')) 'pc-doctor.lnk'))
}

# La versión instalada está en version.txt (la 1.0 no lo traía: con collector.py pero sin version.txt, es la 1.0).
function VersionInstalada {
    $f = Join-Path $Destino 'version.txt'
    if (Test-Path -LiteralPath $f) { return ([IO.File]::ReadAllText($f)).Trim() }
    if (Test-Path -LiteralPath (Join-Path $Destino 'collector.py')) { return '1.0' }
    return $null
}

function VersionNueva { return ([IO.File]::ReadAllText((Join-Path $Origen 'version.txt'))).Trim() }

# Corre actualizar.py (el trabajo de la actualización está ahí, probado en Linux) y devuelve su JSON como objeto, o $null si no pudo.
function Actualizador([string]$python, [string]$carpetaDelScript, [string[]]$argumentos) {
    if (-not (Test-Path -LiteralPath $python)) { return $null }
    $r = Nativo $python (@((Join-Path $carpetaDelScript 'actualizar.py')) + $argumentos)
    if ($r.Codigo -ne 0) { Aviso ("actualizar.py falló: " + $r.Salida.Trim()); return $null }
    $linea = ($r.Salida -split "`n" | Where-Object { $_.Trim().StartsWith('{') } | Select-Object -Last 1)
    if (-not $linea) { return $null }
    return ($linea | ConvertFrom-Json)
}

function PararTodo {
    foreach ($n in $Tareas) {
        if (Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue) { Stop-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue }
    }
    # lo que siga vivo desde la carpeta del programa (dashboard, recolector) bloquearía la copia de archivos
    $limite = (Get-Date).AddSeconds(15)
    do {
        $vivos = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($Destino, [StringComparison]::OrdinalIgnoreCase) })
        if ($vivos.Count -eq 0) { break }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $limite)
    if ($vivos.Count -gt 0) { throw "Quedan procesos de pc-doctor en marcha ($($vivos[0].Name)). Cerralos y volvé a correr instalar.ps1." }
    Bien 'tareas y dashboard detenidos'
}

# ---------------------------------------------------------------------------------------------------------------------------
# -Verificar: solo lee
# ---------------------------------------------------------------------------------------------------------------------------
function VerificarTodo {
    $problemas = 0
    Titulo 'Verificación de pc-doctor'
    $vi = VersionInstalada
    if ($vi) { Bien "versión instalada: $vi" }
    if (Test-Path -LiteralPath (Join-Path $Destino 'collector.py')) { Bien "programa instalado en $Destino" } else { Falla "no está instalado en $Destino"; $problemas++ }
    $py = PythonDelPrograma
    if (Test-Path -LiteralPath $py) { Bien ("Python del programa: " + (& $py --version)) } else { Falla 'falta el entorno de Python (.venv)'; $problemas++ }

    Titulo 'Tareas programadas'
    foreach ($n in $Tareas) {
        $t = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
        if (-not $t) { Falla "$n no está registrada"; $problemas++; continue }
        $i = Get-ScheduledTaskInfo -TaskName $n
        $ultimo = if ($i.LastRunTime.Year -gt 2000) { $i.LastRunTime.ToString('yyyy-MM-dd HH:mm') + " (resultado $($i.LastTaskResult))" } else { 'todavía no corrió' }
        Bien "$n  estado: $($t.State)  última vez: $ultimo"
    }

    Titulo 'Dashboard'
    if (Dashboard-Responde) { Bien "responde en http://127.0.0.1:$Puerto/" } else { Aviso "no responde en el puerto $Puerto (se inicia al abrir sesión o con el acceso directo)" }

    Titulo 'Claude Code (MCP)'
    $claude = BuscarClaude
    if (-not $claude) { Aviso 'Claude Code no está instalado: pc-doctor funciona igual, sin la herramienta MCP ni el reporte redactado por el modelo' }
    else {
        $lista = (Nativo $claude @('mcp', 'list')).Salida
        if ($lista -match 'pc-doctor') { Bien 'servidor MCP pc-doctor registrado' } else { Falla 'el servidor MCP pc-doctor no está registrado'; $problemas++ }
    }

    Titulo 'Qué se puede medir'
    if (Test-Path -LiteralPath $py) {
        Push-Location $Destino
        try { & $py (Join-Path $Destino 'verificar.py') | Out-Host } catch { Falla "no pude leer los sensores: $($_.Exception.Message)"; $problemas++ }
        Pop-Location
    }

    Titulo 'Windows Defender'
    try {
        $d = Get-MpComputerStatus
        if ($d.RealTimeProtectionEnabled) { Bien 'protección en tiempo real activada' } else { Aviso 'la protección en tiempo real de Defender está desactivada' }
        Escribir "      antivirus actualizado al: $($d.AntivirusSignatureLastUpdated)"
    } catch { Aviso 'no pude consultar el estado de Defender (puede haber otro antivirus)' }

    Titulo 'Resultado'
    if ($problemas -eq 0) { Escribir 'Todo en orden.' 'Green' } else { Escribir "$problemas problema(s). Volvé a correr instalar.ps1 para repararlos." 'Yellow' }
    return $problemas
}

# ---------------------------------------------------------------------------------------------------------------------------
# -Desinstalar
# ---------------------------------------------------------------------------------------------------------------------------
function DesinstalarTodo {
    Titulo 'Desinstalar pc-doctor'
    if (Test-Path -LiteralPath (Join-Path $env:ProgramFiles 'pc-doctor-ayudante')) {
        Aviso 'Está instalado el ayudante con privilegios. Quitalo primero, como administrador:'
        Escribir ('      powershell -ExecutionPolicy Bypass -File "' + (Join-Path $Destino 'habilitar-sensores.ps1') + '" -Deshacer')
        throw 'Quitá el ayudante y volvé a correr -Desinstalar.'
    }
    Escribir 'Se va a quitar:'
    foreach ($n in $Tareas) { Escribir "  - la tarea programada $n" }
    foreach ($a in RutasAccesos) { Escribir "  - el acceso directo $a" }
    Escribir "  - el registro de pc-doctor en Claude Code (si está)"
    Escribir "  - el programa en $Destino"
    Escribir "NO se borra nada de tus datos: $Datos (base de datos, configuración, reportes, cuarentena)." 'Green'
    Escribir '  Tampoco se toca tu CLAUDE.md: si querés quitar el bloque, es el que empieza con "Memoria de la PC (pc-doctor)".'
    if ($Simular) { Escribir "`n(Simulación: no se cambió nada.)" 'Yellow'; return }
    if (-not (Confirmar 'Se quitará lo anterior.')) { Escribir 'Cancelado.'; return }
    foreach ($n in $Tareas) { QuitarTarea $n }
    foreach ($a in RutasAccesos) { if (Test-Path -LiteralPath $a) { Remove-Item -LiteralPath $a -Force; Bien "acceso directo quitado: $a" } }
    $claude = BuscarClaude
    if ($claude) { Nativo $claude @('mcp', 'remove', 'pc-doctor', '-s', 'user') | Out-Null; Bien 'registro en Claude Code quitado' }
    Set-Location $env:TEMP
    if (Test-Path -LiteralPath $Destino) { Remove-Item -LiteralPath $Destino -Recurse -Force; Bien "programa quitado: $Destino" }
    Titulo 'Listo'
    Escribir "Tus datos siguen en: $Datos" 'Green'
}

# ---------------------------------------------------------------------------------------------------------------------------
# instalación
# ---------------------------------------------------------------------------------------------------------------------------
function ComprobarSistema {
    Titulo '1. Comprobando el sistema'
    $v = [Environment]::OSVersion.Version
    if ($v.Major -lt 10) { throw "pc-doctor necesita Windows 10 u 11 (este es $v)." }
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'pc-doctor necesita Windows de 64 bits.' }
    if ($PSVersionTable.PSVersion -lt [Version]'5.1') { throw "Hace falta PowerShell 5.1 o más nuevo (este es $($PSVersionTable.PSVersion))." }
    Bien "Windows $v de 64 bits, PowerShell $($PSVersionTable.PSVersion)"
    foreach ($f in 'collector.py', 'server.py', 'pyproject.toml', 'uv.lock', 'versiones.toml', 'lanzador.pyw', 'icono.ico', 'config.ejemplo.json') {
        if (-not (Test-Path -LiteralPath (Join-Path $Origen $f))) { throw "Falta $f junto a instalar.ps1: ¿descomprimiste todo el .zip?" }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $Origen 'web\frontend\dist\index.html'))) { throw 'Falta el dashboard compilado (web\frontend\dist): ¿descomprimiste todo el .zip?' }
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    if ((New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Aviso 'Estás ejecutando como administrador. No hace falta: las tareas y los accesos quedan a nombre de esta cuenta.'
    }
}

function MostrarPlan($v) {
    Titulo 'Plan'
    $actual = VersionInstalada
    $nueva = VersionNueva
    if ($actual) {
        if ([Version]$actual -gt [Version]$nueva) { throw "Tenés instalada la versión $actual, más nueva que esta ($nueva). No se baja de versión." }
        if ($actual -eq $nueva) { Escribir "  Versión: $nueva (ya instalada: se repara y se vuelven a registrar las tareas)" 'White' }
        else { Escribir "  ACTUALIZACIÓN: $actual -> $nueva, en el lugar. Tus datos no se tocan." 'White' }
        $plan = Actualizador (PythonDelPrograma) $Origen @('plan', '--datos', $Datos, '--programa', $Origen, '--instalado', $Destino)
        if ($plan) {
            if ($plan.migraciones.Count -gt 0) { Escribir ('      cambios de esquema de la base: ' + ($plan.migraciones -join ', ')) } else { Escribir '      la base ya está al día' }
            if ($plan.opciones_nuevas.Count -gt 0) { Escribir ('      opciones nuevas en config.json (con su valor por defecto): ' + ($plan.opciones_nuevas -join ', ')) } else { Escribir '      config.json ya tiene todas las opciones' }
        } else { Escribir '      (no pude calcular los cambios de esquema y de configuración antes de actualizar; se aplican igual al actualizar)' }
        Escribir "  Antes de tocar nada: copia de la base y de config.json en $Datos\copias\antes-de-$actual-<fecha>"
        Escribir '  Se detienen las tareas y el dashboard mientras se copia el código, y después se vuelven a registrar y a arrancar.'
    } else { Escribir "  Versión: $nueva (instalación nueva)" 'White' }
    Escribir "  Programa:  $Destino"
    Escribir "  Datos:     $Datos  (base, configuración y reportes; nunca se borran)"
    Escribir "  uv $($v['uv']['version']) (gestor de Python) y Python $($v['python']['version']): se instalan para tu usuario si faltan."
    if (-not (BuscarUv)) { Escribir "      descarga de $($v['uv']['url'])`n      verificada con SHA-256 $($v['uv']['sha256'])" }
    Escribir '  Tareas programadas (sin ventana, sin administrador):'
    Escribir '      pc-doctor-recolector   al iniciar sesión y cada 15 minutos'
    Escribir '      pc-doctor-reporte      domingos 20:00 (si la PC estaba apagada, corre al encenderla)'
    Escribir "      pc-doctor-web          dashboard en http://localhost:$Puerto (solo esta PC), se reinicia si falla"
    Escribir '  Acceso directo "pc-doctor" en el escritorio y en el menú Inicio.'
    $claude = BuscarClaude
    if ($claude) { Escribir "  Claude Code encontrado: se registra el servidor MCP pc-doctor y se agregan reglas a $env:USERPROFILE\.claude\CLAUDE.md (sin tocar lo que ya tenés)." }
    else { Escribir '  Claude Code no está instalado: se instala todo menos el servidor MCP y el reporte redactado por el modelo.' }
    Escribir '  Se hace una primera medición y se verifica que todo responda.'
    Escribir '  Solo se consulta en internet el hash de archivos que ya parecieron sospechosos; nunca se suben archivos.'
}

function InstalarUv($v) {
    $uv = BuscarUv
    if ($uv) { Bien "uv ya está instalado: $uv"; return $uv }
    Escribir '  Descargando uv...'
    New-Item -ItemType Directory -Path $Herramientas -Force | Out-Null
    $zip = Join-Path ([IO.Path]::GetTempPath()) 'pc-doctor-uv.zip'
    $tmp = Join-Path ([IO.Path]::GetTempPath()) 'pc-doctor-uv'
    Descargar $v['uv']['url'] $zip $v['uv']['sha256']
    if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Recurse -Force }
    Expand-Archive -LiteralPath $zip -DestinationPath $tmp -Force
    Copy-Item -LiteralPath (Join-Path $tmp 'uv.exe') -Destination (Join-Path $Herramientas 'uv.exe') -Force
    Remove-Item -LiteralPath $zip -Force
    Remove-Item -LiteralPath $tmp -Recurse -Force
    Bien "uv instalado en $Herramientas"
    return (Join-Path $Herramientas 'uv.exe')
}

function CopiarPrograma {
    if ((Resolve-Path -LiteralPath $Origen).Path.TrimEnd('\') -eq $Destino.TrimEnd('\')) { Bien 'ya se está ejecutando desde la carpeta de instalación'; return }
    New-Item -ItemType Directory -Path $Destino -Force | Out-Null
    # lo compilado se reemplaza entero (si no, quedarían archivos viejos); el código se pisa archivo por archivo
    $dist = Join-Path $Destino 'web\frontend\dist'
    if (Test-Path -LiteralPath $dist) { Remove-Item -LiteralPath $dist -Recurse -Force }
    Get-ChildItem -LiteralPath $Origen -Force | Where-Object { $_.Name -notin @('.venv', 'herramientas', 'version.txt') } |
        ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $Destino -Recurse -Force }
    Bien "programa copiado a $Destino"
}

function PrepararDatos {
    New-Item -ItemType Directory -Path $Datos -Force | Out-Null
    $cfg = Join-Path $Datos 'config.json'
    if (-not (Test-Path -LiteralPath $cfg)) {
        Copy-Item -LiteralPath (Join-Path $Origen 'config.ejemplo.json') -Destination $cfg
        Bien 'config.json creado (sin claves ni secretos)'
    } else { Bien 'config.json ya existía: se conserva (las opciones nuevas se agregan después, sin tocar las tuyas)' }
    $tok = Join-Path $Datos 'web_token'
    if (-not (Test-Path -LiteralPath $tok)) {
        $bytes = New-Object byte[] 32
        $rng = New-Object Security.Cryptography.RNGCryptoServiceProvider
        $rng.GetBytes($bytes)
        $rng.Dispose()
        [IO.File]::WriteAllText($tok, (($bytes | ForEach-Object { $_.ToString('x2') }) -join ''), (New-Object Text.UTF8Encoding($false)))
        # solo esta cuenta puede leerlo (por SID: no depende del idioma de Windows)
        & icacls.exe $tok '/inheritance:r' '/grant:r' ('*' + [Security.Principal.WindowsIdentity]::GetCurrent().User.Value + ':(R,W)') | Out-Null
        Bien 'web_token generado para esta PC'
    } else { Bien 'web_token ya existía' }
}

function RegistrarTareas {
    $py = PythonwDelPrograma
    $lanzador = Join-Path $Destino 'lanzador.pyw'
    $accion = { param($argumentos) New-ScheduledTaskAction -Execute $py -Argument ('"' + $lanzador + '" ' + $argumentos) -WorkingDirectory $Destino }
    $principal = New-ScheduledTaskPrincipal -UserId $Usuario -LogonType Interactive -RunLevel Limited
    $alIniciar = New-ScheduledTaskTrigger -AtLogOn -User $Usuario
    $cada15 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Days 3650)
    $comun = @{ AllowStartIfOnBatteries = $true; DontStopIfGoingOnBatteries = $true; StartWhenAvailable = $true; Hidden = $true; MultipleInstances = 'IgnoreNew' }

    $ajustes = New-ScheduledTaskSettingsSet @comun -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
    Register-ScheduledTask -TaskName $TareaRecolector -Action (& $accion 'collector.py') -Trigger @($alIniciar, $cada15) -Settings $ajustes -Principal $principal -Force | Out-Null
    Bien "$TareaRecolector (al iniciar sesión y cada 15 minutos)"

    $semanal = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '20:00'
    $ajustes = New-ScheduledTaskSettingsSet @comun -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
    Register-ScheduledTask -TaskName $TareaReporte -Action (& $accion 'reporte.py') -Trigger $semanal -Settings $ajustes -Principal $principal -Force | Out-Null
    Bien "$TareaReporte (domingos 20:00; si estaba apagada, corre al encender)"

    $ajustes = New-ScheduledTaskSettingsSet @comun -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
    $web = '-m uvicorn web.api:app --host 127.0.0.1 --port ' + $Puerto + ' --log-level warning'
    Register-ScheduledTask -TaskName $TareaWeb -Action (& $accion $web) -Trigger $alIniciar -Settings $ajustes -Principal $principal -Force | Out-Null
    Bien "$TareaWeb (dashboard en 127.0.0.1:$Puerto, se reinicia si falla)"
}

function CrearAccesos {
    $shell = New-Object -ComObject WScript.Shell
    foreach ($ruta in RutasAccesos) {
        $a = $shell.CreateShortcut($ruta)
        $a.TargetPath = PythonwDelPrograma
        $a.Arguments = '"' + (Join-Path $Destino 'lanzador.pyw') + '" dashboard.py abrir'
        $a.WorkingDirectory = $Destino
        $a.IconLocation = (Join-Path $Destino 'icono.ico') + ',0'
        $a.Description = 'Estado de salud de la PC (pc-doctor)'
        $a.Save()
        Bien "acceso directo: $ruta"
    }
}

function ConfigurarClaude($uv) {
    $claude = BuscarClaude
    if (-not $claude) {
        Aviso 'Claude Code no está instalado en esta PC.'
        Escribir '      pc-doctor funciona igual (medición, alertas, dashboard), pero sin la herramienta MCP ni el reporte semanal redactado por el modelo.'
        Escribir '      Para sumarlo: instalá Claude Code (claude.com/claude-code; en Windows necesita Git for Windows, git-scm.com) y volvé a correr instalar.ps1.'
        return
    }
    Bien "Claude Code encontrado: $claude"
    Nativo $claude @('mcp', 'remove', 'pc-doctor', '-s', 'user') | Out-Null
    $alta = Nativo $claude @('mcp', 'add', '-s', 'user', 'pc-doctor', '--', $uv, 'run', '--frozen', '--no-dev', '--directory', $Destino, 'server.py')
    if ($alta.Codigo -ne 0) { Aviso 'No pude registrar el servidor MCP (claude mcp add falló). Probá a mano con el comando de INSTALAR-WINDOWS.md.' }
    else { Bien 'servidor MCP pc-doctor registrado (para todos tus proyectos)' }

    # El bloque de pc-doctor lleva marcas de inicio y fin: se agrega si falta, se actualiza si cambió (también el de la 1.0, si no lo editaste)
    # y lo que escribiste fuera de él no se toca. Si editaste el bloque de la 1.0 a mano, se deja como está y se avisa.
    $md = Join-Path (Join-Path $env:USERPROFILE '.claude') 'CLAUDE.md'
    $r = Actualizador (PythonDelPrograma) $Destino @('claude-md', '--datos', $Datos, '--programa', $Destino, '--claude-md', $md)
    if (-not $r) { Aviso "No pude actualizar $md. Las reglas están en $Destino\plantillas\CLAUDE.usuario.md." }
    else {
        switch ($r.claude_md) {
            'agregado' { Bien "reglas de pc-doctor agregadas al final de $md (lo que ya tenías no se tocó)" }
            'actualizado' { Bien "bloque de pc-doctor actualizado en $md (lo que escribiste fuera del bloque no se tocó)" }
            'igual' { Bien 'tu CLAUDE.md ya tenía el bloque de pc-doctor al día' }
            'bloque_editado' { Aviso "El bloque de pc-doctor de $md tiene cambios tuyos: no lo toqué. Las reglas nuevas están en $Destino\plantillas\CLAUDE.usuario.md." }
        }
    }
}

function PrimeraMedicion {
    $py = PythonDelPrograma
    Push-Location $Destino
    try {
        & $py collector.py | Out-Host
        $n = & $py -c "import db; print(db.conectar().execute('SELECT COUNT(*) FROM metricas').fetchone()[0])"
        if ([int]$n -gt 0) { Bien "primera medición guardada ($n registro)" } else { Aviso 'el recolector corrió pero no guardó mediciones' }
    } finally { Pop-Location }
    Start-ScheduledTask -TaskName $TareaWeb
    if (EsperarDashboard 25) { Bien "dashboard funcionando en http://localhost:$Puerto" } else { Aviso 'el dashboard no respondió a tiempo: mirá el log en la carpeta de datos (logs\uvicorn.log)' }
}

function OfrecerAyudante {
    Titulo 'Opcional: el ayudante con privilegios'
    Escribir '  Sin administrador, Windows no deja leer temperaturas, ventiladores, voltajes ni el SMART detallado de los discos, y pc-doctor'
    Escribir '  te lo avisa como "no disponible". Si querés medirlos, hay un script aparte que se ejecuta una sola vez como administrador.'
    Escribir '  Primero mirá qué haría, sin cambiar nada:'
    Escribir ('      powershell -ExecutionPolicy Bypass -File "' + (Join-Path $Destino 'habilitar-sensores.ps1') + '" -Simular') 'White'
    Escribir '  Este instalador no lo ejecuta.'
}

# ---------------------------------------------------------------------------------------------------------------------------
# principal
# ---------------------------------------------------------------------------------------------------------------------------
if ($Verificar) { $n = VerificarTodo; exit ([int]($n -gt 0)) }
if ($Desinstalar) { DesinstalarTodo; exit 0 }

try {
    ComprobarSistema
    $v = LeerVersiones (Join-Path $Origen 'versiones.toml')
    MostrarPlan $v
    if ($Simular) { Escribir "`n(Simulación: no se cambió nada.)" 'Yellow'; exit 0 }
    Write-Host ''
    if (-not (Confirmar 'Se instalará lo anterior.')) { Escribir 'Cancelado: no se cambió nada.'; exit 0 }

    # Los archivos descargados de internet llevan una marca que hace que PowerShell pregunte por cada script: se quita.
    Get-ChildItem -LiteralPath $Origen -Recurse -File | Unblock-File

    Titulo '2. uv y Python'
    $uv = InstalarUv $v
    & $uv python install $v['python']['version']
    if ($LASTEXITCODE -ne 0) { throw 'uv no pudo instalar Python.' }
    Bien "Python $($v['python']['version']) disponible"

    $anterior = VersionInstalada
    $nueva = VersionNueva
    Titulo '3. Programa'
    if ($anterior) {
        Escribir "  Actualizando de $anterior a $nueva en el lugar."
        PararTodo
        # copia previa de la base y de config.json, con el Python de la versión instalada y ANTES de tocar el código
        if (Test-Path -LiteralPath (PythonDelPrograma)) {
            $copia = Actualizador (PythonDelPrograma) $Origen @('respaldar', '--datos', $Datos, '--instalado', $Destino)
            if ($copia -and $copia.copia) { Bien "copia previa en $($copia.copia)" }
            elseif ($copia) { Bien 'no había base ni configuración que copiar' }
            else { throw 'No pude hacer la copia previa de la base: no se toca nada. Revisá el mensaje de arriba.' }
        } else {
            # instalación dañada (sin su Python): con las tareas ya detenidas se copian los archivos tal cual
            $carpeta = Join-Path $Datos ('copias\antes-de-' + $anterior + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
            New-Item -ItemType Directory -Path $carpeta -Force | Out-Null
            Get-ChildItem -LiteralPath $Datos -File | Where-Object { $_.Name -like 'doctor.db*' -or $_.Name -eq 'config.json' } | Copy-Item -Destination $carpeta
            Bien "copia previa en $carpeta"
        }
    }
    CopiarPrograma
    Push-Location $Destino
    try {
        & $uv sync --frozen --no-dev --python $v['python']['version']
        if ($LASTEXITCODE -ne 0) { throw 'uv sync falló: no se pudieron instalar las dependencias (¿hay internet?).' }
    } finally { Pop-Location }
    Bien 'dependencias instaladas (versiones exactas de uv.lock)'

    Titulo '4. Datos'
    PrepararDatos
    if ($anterior) {
        $r = Actualizador (PythonDelPrograma) $Destino @('aplicar', '--datos', $Datos, '--programa', $Destino)
        if (-not $r) { throw 'No pude aplicar los cambios de esquema y de configuración (mirá el mensaje de arriba). Tus datos y la copia previa están intactos.' }
        if ($r.migraciones.Count -gt 0) { Bien ('base migrada: ' + ($r.migraciones -join ', ')) } else { Bien 'la base ya estaba al día' }
        if ($r.opciones_nuevas.Count -gt 0) { Bien ('opciones nuevas agregadas a config.json: ' + ($r.opciones_nuevas -join ', ')) } else { Bien 'config.json ya tenía todas las opciones' }
        if ($r.PSObject.Properties['aviso']) { Aviso $r.aviso }
    }

    Titulo '5. Tareas programadas'
    RegistrarTareas

    Titulo '6. Acceso directo'
    CrearAccesos

    Titulo '7. Claude Code'
    ConfigurarClaude $uv

    Titulo '8. Primera medición'
    PrimeraMedicion

    # la versión se anota al final: si algo falló antes, la próxima corrida vuelve a actualizar (todo es idempotente)
    Copy-Item -LiteralPath (Join-Path $Origen 'version.txt') -Destination (Join-Path $Destino 'version.txt') -Force
    OfrecerAyudante
    Titulo 'Listo'
    Escribir '  Para comprobar todo en cualquier momento:' 'Gray'
    Escribir ('      powershell -ExecutionPolicy Bypass -File "' + (Join-Path $Destino 'instalar.ps1') + '" -Verificar') 'White'
    Escribir '  Para que Claude Code revise la instalación, abrilo y pegale el contenido de PROMPT-VERIFICACION.md (está en la carpeta del programa).'
    exit 0
} catch {
    Write-Host ''
    Falla $_.Exception.Message
    Escribir 'La instalación se detuvo. Se puede volver a correr instalar.ps1: retoma sin duplicar nada.' 'Yellow'
    exit 1
}
