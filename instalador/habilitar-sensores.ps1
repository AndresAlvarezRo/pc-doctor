<#
.SYNOPSIS
    Habilita el ayudante con privilegios de pc-doctor (opcional): temperaturas, ventiladores y voltajes con LibreHardwareMonitor, SMART
    detallado, estado de BitLocker, Secure Boot, exclusiones de Defender y suscripciones WMI.

.DESCRIPTION
    Hay que ejecutarlo UNA vez como administrador, después de leerlo. Windows sin administrador mide poco y no lee SMART: este
    script instala dos tareas programadas con privilegios y nada más:

      pc-doctor-ayudante  (SYSTEM)       corre ayudante.ps1 al arrancar y cada 15 minutos. Solo LEE y escribe estado.json.
      pc-doctor-lhm       (tu usuario)   abre LibreHardwareMonitor al iniciar sesión, minimizado, para que exponga sus sensores.

    Todo queda en %ProgramFiles%\pc-doctor-ayudante y %ProgramData%\pc-doctor\ayudante, carpetas donde un usuario común no puede
    escribir (si pudiera, una tarea con privilegios podría ser engañada para ejecutar lo que ese usuario quisiera).
    El recolector, el dashboard y el reporte de pc-doctor siguen corriendo SIN privilegios.

    Antes de cambiar algo muestra el plan, con versiones, direcciones y SHA-256, y pide confirmación. Cada descarga se verifica
    contra versiones.toml y se detiene si no coincide.

.PARAMETER Simular
    Muestra el plan y no cambia nada (no hace falta ser administrador).
.PARAMETER Deshacer
    Quita las tareas, LibreHardwareMonitor, smartctl (si se instaló con este script) y las dos carpetas. No toca la carpeta de datos
    de pc-doctor ni desinstala PawnIO (otros programas pueden usarlo).
.PARAMETER ConSmartctl
    Instala smartmontools (oficial, firmado) para leer los contadores SMART crudos: sectores realocados, pendientes y errores CRC.
.PARAMETER InstalarPawnIO
    Descarga y abre el instalador del driver PawnIO, que LibreHardwareMonitor usa para leer la CPU y la placa. Se instala a mano,
    con su asistente, después de una confirmación aparte.
.PARAMETER SinLibreHardwareMonitor
    No instala LibreHardwareMonitor (solo el ayudante).
#>
[CmdletBinding()]
param(
    [switch]$Simular,
    [switch]$Deshacer,
    [switch]$ConSmartctl,
    [switch]$InstalarPawnIO,
    [switch]$SinLibreHardwareMonitor
)

Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'

$DirAyudante = Join-Path $env:ProgramFiles 'pc-doctor-ayudante'
$DirSalida = Join-Path $env:ProgramData 'pc-doctor\ayudante'
$DirLhm = Join-Path $DirAyudante 'LibreHardwareMonitor'
$DirSmartctl = Join-Path $DirAyudante 'smartctl'
$DirDescargas = Join-Path $DirAyudante 'descargas'
$Manifiesto = Join-Path $DirAyudante 'instalado.json'
$TareaAyudante = 'pc-doctor-ayudante'
$TareaLhm = 'pc-doctor-lhm'
$Powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'

function Escribir([string]$texto, [string]$color = 'Gray') { Write-Host $texto -ForegroundColor $color }
function Titulo([string]$texto) { Write-Host ''; Write-Host $texto -ForegroundColor Cyan }

function EsAdministrador {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Confirmar([string]$palabra, [string]$pregunta) {
    $r = Read-Host ($pregunta + " Escribí $palabra para continuar")
    return ($r.Trim().ToUpper() -eq $palabra.ToUpper())
}

# versiones.toml solo tiene [secciones] y clave = "valor" (una prueba lo exige): alcanza con leerlo línea por línea.
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

function HashDe([string]$ruta) { return (Get-FileHash -Algorithm SHA256 -LiteralPath $ruta).Hash.ToLower() }

# Solo se descarga de github.com y solo si el SHA-256 coincide con el de versiones.toml; si no, se borra y se corta.
function Descargar([string]$url, [string]$destino, [string]$sha256) {
    if (-not $url.StartsWith('https://github.com/')) { throw "Dirección no permitida (solo https://github.com/): $url" }
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $destino
    $real = HashDe $destino
    if ($real -ne $sha256.ToLower()) {
        Remove-Item -LiteralPath $destino -Force
        throw "El SHA-256 de lo descargado no coincide.`n  esperado: $sha256`n  recibido: $real`nNo se instaló nada de esto."
    }
    Escribir "  descargado y verificado (SHA-256 $real)" 'Green'
}

function VerificarFirma([string]$ruta) {
    $f = Get-AuthenticodeSignature -LiteralPath $ruta
    if ($f.Status -ne 'Valid') { throw "El instalador no tiene una firma digital válida (estado: $($f.Status))." }
    Escribir ("  firma digital válida: " + $f.SignerCertificate.Subject) 'Green'
}

# Solo SYSTEM y Administradores pueden escribir; los usuarios, leer y ejecutar. (Se usan SID: no dependen del idioma de Windows.)
function PonerPermisos([string]$ruta) {
    & icacls.exe $ruta '/inheritance:r' '/grant:r' '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-32-545:(OI)(CI)RX' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "No pude fijar los permisos de $ruta" }
}

function VerificarPermisos([string]$ruta) {
    $escritura = [Security.AccessControl.FileSystemRights]'WriteData, AppendData, Delete, ChangePermissions, TakeOwnership'
    $comunes = @('S-1-5-32-545', 'S-1-5-11', 'S-1-1-0')
    foreach ($r in (Get-Acl -LiteralPath $ruta).Access) {
        $sid = $r.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
        if ($r.AccessControlType -eq 'Allow' -and ($comunes -contains $sid) -and ([int]($r.FileSystemRights -band $escritura) -ne 0)) {
            throw "La carpeta $ruta quedó con permiso de escritura para usuarios comunes ($($r.IdentityReference)). No sigo."
        }
    }
}

function UsuarioInteractivo {
    $u = (Get-CimInstance -ClassName Win32_ComputerSystem).UserName
    if ([string]::IsNullOrEmpty($u)) { $u = [Security.Principal.WindowsIdentity]::GetCurrent().Name }
    return $u
}

function UsuarioEsAdministrador([string]$usuario) {
    try {
        $corto = $usuario.Split('\')[-1].ToLower()
        foreach ($m in @(Get-LocalGroupMember -SID 'S-1-5-32-544')) {
            if ($m.Name.Split('\')[-1].ToLower() -eq $corto) { return $true }
        }
        return $false
    } catch {
        Escribir "  No pude comprobar si $usuario es administrador ($($_.Exception.Message)); sigo igual." 'Yellow'
        return $true
    }
}

function QuitarTarea([string]$nombre) {
    if (Get-ScheduledTask -TaskName $nombre -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $nombre -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $nombre -Confirm:$false
        Escribir "  tarea $nombre quitada"
    }
}

# ---------------------------------------------------------------------------------------------------------------------------
$v = LeerVersiones (Join-Path $PSScriptRoot 'versiones.toml')
$origenAyudante = Join-Path $PSScriptRoot 'ayudante.ps1'
if (-not (Test-Path -LiteralPath $origenAyudante)) { throw "No encuentro ayudante.ps1 junto a este script." }
$hashAyudante = HashDe $origenAyudante
$usuario = UsuarioInteractivo

Titulo 'pc-doctor: ayudante con privilegios'
if ($Deshacer) {
    Escribir 'Se va a DESHACER todo lo que instaló este script:'
    Escribir "  - tareas programadas $TareaAyudante y $TareaLhm"
    Escribir "  - LibreHardwareMonitor y smartctl (si los instaló este script)"
    Escribir "  - las carpetas $DirAyudante y $DirSalida"
    Escribir '  - NO se toca la carpeta de datos de pc-doctor ni se desinstala el driver PawnIO (otros programas pueden usarlo;'
    Escribir '    si lo querés quitar, hacelo desde Configuración > Aplicaciones > Aplicaciones instaladas > PawnIO).'
} else {
    Escribir 'Se va a instalar, con privilegios de administrador (nada más corre elevado):'
    Escribir "  1. Carpetas $DirAyudante y $DirSalida, con permiso de escritura solo para SYSTEM y Administradores."
    Escribir "  2. ayudante.ps1 (SHA-256 $hashAyudante) y la tarea '$TareaAyudante' (SYSTEM, cada 15 min): solo lee y escribe estado.json."
    if (-not $SinLibreHardwareMonitor) {
        Escribir "  3. LibreHardwareMonitor $($v['librehardwaremonitor']['version']) desde $($v['librehardwaremonitor']['url'])"
        Escribir "     SHA-256 esperado $($v['librehardwaremonitor']['sha256'])"
        Escribir "     y la tarea '$TareaLhm' (usuario $usuario, al iniciar sesión, minimizado). El usuario tiene que ser administrador."
    }
    if ($ConSmartctl) {
        Escribir "  4. smartmontools $($v['smartmontools']['version']) desde $($v['smartmontools']['url'])"
        Escribir "     SHA-256 esperado $($v['smartmontools']['sha256']) (instalador firmado; se verifica la firma)"
    }
    if ($InstalarPawnIO) {
        Escribir "  5. Driver PawnIO $($v['pawnio']['version']) desde $($v['pawnio']['url'])"
        Escribir "     SHA-256 esperado $($v['pawnio']['sha256']). Es un driver de kernel: se abre su asistente y lo instalás vos, con otra confirmación."
    }
    Escribir 'Para ver el contenido exacto de lo que va a correr con privilegios, abrí ayudante.ps1 antes de continuar.'
}

if ($Simular) {
    Titulo 'Simulación: no se cambió nada.'
    exit 0
}
if (-not (EsAdministrador)) {
    Escribir 'Este script tiene que ejecutarse como administrador (clic derecho en PowerShell > Ejecutar como administrador).' 'Red'
    exit 1
}
if (-not (Confirmar 'SI' '¿Seguimos?')) { Escribir 'Cancelado: no se cambió nada.' 'Yellow'; exit 1 }

try {
    if ($Deshacer) {
        Titulo 'Deshaciendo'
        QuitarTarea $TareaAyudante
        QuitarTarea $TareaLhm
        Get-Process -Name 'LibreHardwareMonitor' -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($DirAyudante, [StringComparison]::OrdinalIgnoreCase) } | Stop-Process -Force
        $desinstalador = $null
        if (Test-Path -LiteralPath $DirSmartctl) {
            $desinstalador = Get-ChildItem -LiteralPath $DirSmartctl -Filter 'uninst*.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
        }
        if ($desinstalador) {
            Escribir '  desinstalando smartmontools'
            Start-Process -FilePath $desinstalador.FullName -ArgumentList @('/S', "_?=$DirSmartctl") -Wait
        }
        foreach ($d in $DirAyudante, $DirSalida) {
            if (Test-Path -LiteralPath $d) { Remove-Item -LiteralPath $d -Recurse -Force; Escribir "  carpeta $d quitada" }
        }
        $padre = Split-Path -Parent $DirSalida
        if ((Test-Path -LiteralPath $padre) -and -not (Get-ChildItem -LiteralPath $padre -Force)) { Remove-Item -LiteralPath $padre -Force }
        Titulo 'Listo. La carpeta de datos de pc-doctor no se tocó.'
        exit 0
    }

    Titulo '1. Carpetas y permisos'
    foreach ($d in $DirAyudante, $DirSalida) {
        if (-not (Test-Path -LiteralPath $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
        PonerPermisos $d
        VerificarPermisos $d
        Escribir "  $d" 'Green'
    }
    New-Item -ItemType Directory -Path $DirDescargas -Force | Out-Null

    $manifiesto = [ordered]@{ version = 1; fecha = (Get-Date).ToString('s'); usuario = $usuario; librehardwaremonitor = $null; smartmontools = $null; pawnio = $null }

    Titulo '2. Ayudante'
    $destinoAyudante = Join-Path $DirAyudante 'ayudante.ps1'
    Copy-Item -LiteralPath $origenAyudante -Destination $destinoAyudante -Force
    if ((HashDe $destinoAyudante) -ne $hashAyudante) { throw 'La copia de ayudante.ps1 no coincide con el original.' }
    Escribir "  ayudante.ps1 copiado (SHA-256 $hashAyudante)" 'Green'

    if (-not $SinLibreHardwareMonitor) {
        Titulo '3. LibreHardwareMonitor'
        $sec = $v['librehardwaremonitor']
        $zip = Join-Path $DirDescargas 'LibreHardwareMonitor.zip'
        Descargar $sec['url'] $zip $sec['sha256']
        if (Test-Path -LiteralPath $DirLhm) { Remove-Item -LiteralPath $DirLhm -Recurse -Force }
        Expand-Archive -LiteralPath $zip -DestinationPath $DirLhm -Force
        # Ajustes: abrir minimizado, a la bandeja, sin servidor web. (Si esta versión usa otros nombres de ajuste, la ventana se
        # ve al iniciar sesión pero los sensores funcionan igual.)
        $ajustes = @'
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <appSettings>
    <add key="startMinMenuItem" value="true" />
    <add key="minTrayMenuItem" value="true" />
    <add key="minCloseMenuItem" value="true" />
    <add key="runWebServerMenuItem" value="false" />
  </appSettings>
</configuration>
'@
        [System.IO.File]::WriteAllText((Join-Path $DirLhm 'LibreHardwareMonitor.config'), $ajustes, (New-Object System.Text.UTF8Encoding($false)))
        $manifiesto.librehardwaremonitor = [ordered]@{ version = $sec['version']; sha256 = $sec['sha256'] }
        if (UsuarioEsAdministrador $usuario) {
            $accion = New-ScheduledTaskAction -Execute (Join-Path $DirLhm 'LibreHardwareMonitor.exe') -WorkingDirectory $DirLhm
            $disparador = New-ScheduledTaskTrigger -AtLogOn -User $usuario
            $principal = New-ScheduledTaskPrincipal -UserId $usuario -LogonType Interactive -RunLevel Highest
            $config = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
            Register-ScheduledTask -TaskName $TareaLhm -Action $accion -Trigger $disparador -Principal $principal -Settings $config -Force | Out-Null
            Start-ScheduledTask -TaskName $TareaLhm
            Escribir "  tarea $TareaLhm registrada y LibreHardwareMonitor iniciado" 'Green'
        } else {
            Escribir "  $usuario no es administrador: LibreHardwareMonitor necesita privilegios para leer los sensores, así que no se registró su tarea." 'Yellow'
            Escribir '  Las temperaturas, ventiladores y voltajes van a seguir como "no disponible".' 'Yellow'
        }
    }

    if ($ConSmartctl) {
        Titulo '4. smartmontools'
        $sec = $v['smartmontools']
        $instalador = Join-Path $DirDescargas 'smartmontools-setup.exe'
        Descargar $sec['url'] $instalador $sec['sha256']
        VerificarFirma $instalador
        Start-Process -FilePath $instalador -ArgumentList "/S /D=$DirSmartctl" -Wait
        $smartctl = Join-Path $DirSmartctl 'bin\smartctl.exe'
        if (-not (Test-Path -LiteralPath $smartctl)) { throw "El instalador terminó pero no encuentro $smartctl." }
        Escribir ("  " + ((& $smartctl --version) | Select-Object -First 1)) 'Green'
        $manifiesto.smartmontools = [ordered]@{ version = $sec['version']; sha256 = $sec['sha256'] }
    }

    if ($InstalarPawnIO) {
        Titulo '5. Driver PawnIO'
        $sec = $v['pawnio']
        $instalador = Join-Path $DirDescargas 'PawnIO_setup.exe'
        Descargar $sec['url'] $instalador $sec['sha256']
        VerificarFirma $instalador
        if (Confirmar 'INSTALAR' 'Se va a abrir el instalador de un driver de kernel.') {
            Start-Process -FilePath $instalador -Wait
            $manifiesto.pawnio = [ordered]@{ version = $sec['version']; sha256 = $sec['sha256'] }
        } else {
            Escribir '  PawnIO no se instaló.' 'Yellow'
        }
    }

    Titulo '6. Tarea del ayudante'
    $accion = New-ScheduledTaskAction -Execute $Powershell -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $destinoAyudante)
    $alArrancar = New-ScheduledTaskTrigger -AtStartup
    $cadaQuince = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Days 3650)
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $config = New-ScheduledTaskSettingsSet -StartWhenAvailable -Hidden -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $TareaAyudante -Action $accion -Trigger @($alArrancar, $cadaQuince) -Principal $principal -Settings $config -Force | Out-Null
    Escribir "  tarea $TareaAyudante registrada (SYSTEM, al arrancar y cada 15 minutos)" 'Green'

    Remove-Item -LiteralPath $DirDescargas -Recurse -Force
    [System.IO.File]::WriteAllText($Manifiesto, ($manifiesto | ConvertTo-Json -Depth 4), (New-Object System.Text.UTF8Encoding($false)))

    Titulo '7. Primera lectura'
    Start-ScheduledTask -TaskName $TareaAyudante
    $estado = Join-Path $DirSalida 'estado.json'
    $limite = (Get-Date).AddSeconds(90)
    while (-not (Test-Path -LiteralPath $estado) -and (Get-Date) -lt $limite) { Start-Sleep -Seconds 2 }
    if (Test-Path -LiteralPath $estado) {
        $e = Get-Content -LiteralPath $estado -Raw -Encoding UTF8 | ConvertFrom-Json
        Escribir ("  discos con SMART de smartctl: " + @($e.smart.PSObject.Properties).Count) 'Green'
        Escribir ("  discos con contadores de fiabilidad: " + @($e.fiabilidad).Count) 'Green'
        Escribir ("  volúmenes de BitLocker: " + @($e.bitlocker).Count + "; Secure Boot: " + $e.arranque_seguro) 'Green'
        foreach ($m in @($e.errores)) { Escribir "  no se pudo leer: $m" 'Yellow' }
    } else {
        Escribir '  El ayudante todavía no dejó estado.json; probá de nuevo en unos minutos (Programador de tareas > pc-doctor-ayudante).' 'Yellow'
    }
    Titulo 'Listo. pc-doctor lo va a usar solo en la próxima corrida. Para deshacerlo: habilitar-sensores.ps1 -Deshacer'
} catch {
    Escribir ('Error: ' + $_.Exception.Message) 'Red'
    Escribir 'Lo ya instalado queda como estaba; podés volver atrás con habilitar-sensores.ps1 -Deshacer.' 'Yellow'
    exit 1
}
