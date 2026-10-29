# ayudante.ps1 -- LO ÚNICO de pc-doctor que corre con privilegios (tarea "pc-doctor-ayudante", como SYSTEM, cada 15 minutos).
#
# Reglas que no se rompen (una prueba del proyecto las revisa leyendo este archivo):
#  - No recibe parámetros, no usa la red, no descarga ni ejecuta nada que venga de afuera.
#  - Solo lee: discos (SMART y contadores), BitLocker (estado, nunca claves ni protectores), Secure Boot, exclusiones de
#    Defender y suscripciones WMI. Lo único que escribe es estado.json, y solo en %ProgramData%\pc-doctor\ayudante.
#  - Vive en %ProgramFiles%\pc-doctor-ayudante, una carpeta donde un usuario común no puede escribir. La carpeta de salida
#    también es de solo lectura para los usuarios y la crea habilitar-sensores.ps1 con esos permisos; este script no crea nada.
#  - Lo único que ejecuta además de PowerShell es smartctl.exe, de la carpeta de al lado, con argumentos fijos.

Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'

$carpetaSalida = Join-Path $env:ProgramData 'pc-doctor\ayudante'
if (-not (Test-Path -LiteralPath $carpetaSalida)) { exit 2 }

$errores = @()

function Corto($texto, [int]$maximo) {
    $s = [string]$texto
    if ($s.Length -gt $maximo) { return $s.Substring(0, $maximo) }
    return $s
}

function NotaError([string]$seccion, $e) {
    $script:errores += (Corto ($seccion + ': ' + $e.Exception.Message) 200)
}

# --- SMART con smartctl (opcional: solo si habilitar-sensores.ps1 lo instaló) ---
$smart = [ordered]@{}
$smartctl = Join-Path $PSScriptRoot 'smartctl\bin\smartctl.exe'
if (Test-Path -LiteralPath $smartctl) {
    try {
        $busqueda = (& $smartctl --scan -j | Out-String) | ConvertFrom-Json
        foreach ($d in @($busqueda.devices)) {
            try {
                if ($d.name -match '^/dev/sd([a-z])$') {
                    $letra = $Matches[1]
                    if ($d.type -match '^[a-z0-9,]{1,20}$') {
                        $clave = 'disk' + ([int][char]$letra - [int][char]'a')
                        $texto = (& $smartctl -j -H -A -d $d.type $d.name | Out-String)
                        if ($texto.Length -le 200000) { $smart[$clave] = $texto }
                    }
                }
            } catch { NotaError 'smart' $_ }
        }
    } catch { NotaError 'smart' $_ }
}

# --- Contadores de fiabilidad de los discos (necesitan privilegios) ---
$fiabilidad = @()
try {
    foreach ($disco in @(Get-PhysicalDisk)) {
        $c = $disco | Get-StorageReliabilityCounter
        $fiabilidad += [pscustomobject]@{
            Id = [int]$disco.DeviceId
            Temperatura = $c.Temperature
            Desgaste = $c.Wear
            Horas = $c.PowerOnHours
            LecturasNoCorregidas = $c.ReadErrorsUncorrected
            EscriturasNoCorregidas = $c.WriteErrorsUncorrected
        }
    }
} catch { NotaError 'fiabilidad' $_ }

# --- BitLocker: solo el estado de cada volumen ---
$bitlocker = @()
try {
    foreach ($v in @(Get-BitLockerVolume)) {
        $bitlocker += [pscustomobject]@{
            Punto = [string]$v.MountPoint
            Estado = [string]$v.VolumeStatus
            Proteccion = [string]$v.ProtectionStatus
            Bloqueo = [string]$v.LockStatus
            Metodo = [string]$v.EncryptionMethod
        }
    }
} catch { NotaError 'bitlocker' $_ }

# --- Secure Boot ---
$arranqueSeguro = 'no_soportado'
try {
    if (Confirm-SecureBootUEFI) { $arranqueSeguro = 'activado' } else { $arranqueSeguro = 'desactivado' }
} catch { $arranqueSeguro = 'no_soportado' }

# --- Exclusiones de Defender ---
$exclRutas = @()
$exclExtensiones = @()
$exclProcesos = @()
try {
    $pref = Get-MpPreference
    if ($pref.ExclusionPath) { $exclRutas = @($pref.ExclusionPath | Select-Object -First 100 | ForEach-Object { Corto $_ 260 }) }
    if ($pref.ExclusionExtension) { $exclExtensiones = @($pref.ExclusionExtension | Select-Object -First 100 | ForEach-Object { Corto $_ 260 }) }
    if ($pref.ExclusionProcess) { $exclProcesos = @($pref.ExclusionProcess | Select-Object -First 100 | ForEach-Object { Corto $_ 260 }) }
} catch { NotaError 'defender' $_ }

# --- Suscripciones WMI (persistencia típica de mineros y malware sin archivos) ---
$consumidores = @()
try {
    foreach ($c in @(Get-CimInstance -Namespace 'root/subscription' -ClassName 'CommandLineEventConsumer')) {
        $consumidores += [pscustomobject]@{
            Name = (Corto $c.Name 200)
            CommandLineTemplate = (Corto $c.CommandLineTemplate 500)
            ExecutablePath = (Corto $c.ExecutablePath 260)
        }
    }
    foreach ($c in @(Get-CimInstance -Namespace 'root/subscription' -ClassName 'ActiveScriptEventConsumer')) {
        $consumidores += [pscustomobject]@{
            Name = (Corto $c.Name 200)
            ScriptFileName = (Corto $c.ScriptFileName 260)
        }
    }
} catch { NotaError 'wmi' $_ }

$estado = [ordered]@{
    version = 1
    ts = [int64][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    smart = $smart
    fiabilidad = $fiabilidad
    bitlocker = $bitlocker
    arranque_seguro = $arranqueSeguro
    defender = [ordered]@{ rutas = $exclRutas; extensiones = $exclExtensiones; procesos = $exclProcesos }
    wmi = [ordered]@{ consumidores = $consumidores }
    errores = $errores
}

# Se escribe en un archivo temporal de la misma carpeta y se reemplaza de una vez: pc-doctor nunca lee un archivo a medias.
$json = $estado | ConvertTo-Json -Depth 6 -Compress
$temporal = Join-Path $carpetaSalida ('estado.' + [guid]::NewGuid().ToString('N') + '.tmp')
[System.IO.File]::WriteAllText($temporal, $json, (New-Object System.Text.UTF8Encoding($false)))
Move-Item -LiteralPath $temporal -Destination (Join-Path $carpetaSalida 'estado.json') -Force
