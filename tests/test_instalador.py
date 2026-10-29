"""Revisión estática de los scripts de PowerShell del instalador. Acá no hay PowerShell: lo que se comprueba es que los archivos
cumplan las reglas de seguridad del diseño (lo elevado hace lo mínimo, nada se instala sin verificar el hash, nada se deshace de más)
y que estén guardados de forma que Windows PowerShell 5.1 los lea bien."""

import re
from pathlib import Path

import pytest

DIR = Path(__file__).resolve().parent.parent / "instalador"
AYUDANTE = DIR / "ayudante.ps1"
HABILITAR = DIR / "habilitar-sensores.ps1"
VERSIONES = DIR / "versiones.toml"


def codigo(ruta: Path) -> str:
    """El archivo sin las líneas de comentario."""
    return "\n".join(l for l in ruta.read_text(encoding="utf-8-sig").splitlines() if not l.lstrip().startswith("#"))


# ---------- formato ----------

@pytest.mark.parametrize("ruta", [AYUDANTE, HABILITAR])
def test_los_scripts_estan_en_utf8_con_marca_de_orden_de_bytes(ruta):
    # sin la marca, Windows PowerShell 5.1 los lee como ANSI y rompe los acentos
    assert ruta.read_bytes()[:3] == b"\xef\xbb\xbf"
    ruta.read_bytes().decode("utf-8")


# ---------- lo que corre con privilegios ----------

COMANDOS_PERMITIDOS = {"Set-StrictMode", "Join-Path", "Test-Path", "Get-PhysicalDisk", "Get-StorageReliabilityCounter", "Get-BitLockerVolume",
                       "Confirm-SecureBootUEFI", "Get-MpPreference", "Get-CimInstance", "ConvertFrom-Json", "ConvertTo-Json", "New-Object",
                       "Move-Item", "ForEach-Object", "Select-Object", "Out-String"}


def test_el_ayudante_solo_usa_los_comandos_permitidos():
    usados = set(re.findall(r"\b([A-Z][a-z]+-[A-Z][A-Za-z]+)\b", codigo(AYUDANTE)))
    assert usados <= COMANDOS_PERMITIDOS, f"comandos no permitidos en lo que corre con privilegios: {sorted(usados - COMANDOS_PERMITIDOS)}"
    assert {"Get-PhysicalDisk", "Get-BitLockerVolume", "Move-Item"} <= usados


@pytest.mark.parametrize("prohibido", [
    r"param\s*\(", r"Invoke-", r"\biex\b", r"Start-Process", r"Add-Type", r"Set-ExecutionPolicy", r"Register-", r"Remove-", r"Set-Content", r"Out-File",
    r"WebClient", r"System\.Net", r"Reflection", r"DownloadString", r"-EncodedCommand", r"https?://", r"LOCALAPPDATA", r"USERPROFILE", r"\bAPPDATA\b",
    r"\\Users\\", r"KeyProtector", r"RecoveryPassword", r"\$args", r"\[Environment\]::GetCommandLineArgs"])
def test_el_ayudante_no_tiene_nada_de_lo_prohibido(prohibido):
    assert not re.search(prohibido, codigo(AYUDANTE), re.I), prohibido


def test_el_ayudante_solo_escribe_su_archivo_de_estado_en_la_carpeta_de_solo_lectura():
    c = codigo(AYUDANTE)
    assert len(re.findall(r"WriteAllText", c)) == 1 and len(re.findall(r"Move-Item", c)) == 1
    assert "$env:ProgramData 'pc-doctor\\ayudante'" in c or "$env:ProgramData, 'pc-doctor\\ayudante'" in c
    assert "-LiteralPath $temporal -Destination (Join-Path $carpetaSalida 'estado.json')" in c
    assert re.search(r"if \(-not \(Test-Path -LiteralPath \$carpetaSalida\)\) \{ exit 2 \}", c)        # no crea la carpeta (la crea el instalador con permisos)
    assert "New-Item" not in c


def test_el_unico_programa_que_ejecuta_es_smartctl_de_su_carpeta_con_argumentos_fijos():
    c = codigo(AYUDANTE)
    llamadas = re.findall(r"&\s*\$(\w+)\s+([^\n|)]*)", c)
    assert llamadas and {nombre for nombre, _ in llamadas} == {"smartctl"}
    assert "$smartctl = Join-Path $PSScriptRoot 'smartctl\\bin\\smartctl.exe'" in c
    assert "'^/dev/sd([a-z])$'" in c and "'^[a-z0-9,]{1,20}$'" in c               # el nombre y el tipo del dispositivo se validan antes de usarlos


def test_el_ayudante_limita_el_tamano_de_lo_que_escribe():
    c = codigo(AYUDANTE)
    assert "-le 200000" in c and "Select-Object -First 100" in c and "Corto" in c


# ---------- el instalador ----------

def test_el_instalador_tiene_las_opciones_acordadas():
    t = HABILITAR.read_text(encoding="utf-8-sig")
    bloque = re.search(r"param\((.*?)\n\)", t, re.S).group(1)
    assert sorted(re.findall(r"\[switch\]\$(\w+)", bloque)) == ["ConSmartctl", "Deshacer", "InstalarPawnIO", "Simular", "SinLibreHardwareMonitor"]


def test_pide_administrador_y_confirmacion_salvo_para_simular():
    c = codigo(HABILITAR)
    simular, admin, confirmar = c.index("if ($Simular)"), c.index("if (-not (EsAdministrador))"), c.index("if (-not (Confirmar 'SI'")
    principal = c.index("try {\n    if ($Deshacer)")
    assert simular < admin < confirmar < principal                # la simulación no necesita administrador; nada se cambia antes de confirmar
    assert "Read-Host" in c


def test_cada_descarga_se_verifica_contra_versiones_toml_antes_de_usarla():
    c = codigo(HABILITAR)
    assert "StartsWith('https://github.com/')" in c
    # las direcciones salen de versiones.toml: en el script solo está el prefijo permitido (en la comprobación y en su mensaje de error)
    assert set(re.findall(r"https?://[^\s'\")]*", c)) == {"https://github.com/"}
    descargas = re.findall(r"Descargar \$sec\['url'\] (\$\w+) \$sec\['sha256'\]", c)
    assert len(descargas) == 3
    for archivo in descargas:
        primer_uso = min(i for i in [c.find(f"Expand-Archive -LiteralPath {archivo}"), c.find(f"-FilePath {archivo}")] if i >= 0)
        assert c.index(f"Descargar $sec['url'] {archivo}") < primer_uso
    fn = re.search(r"function Descargar.*?\n\}\n", c, re.S).group(0)
    web, hash_, cmp_ = fn.index("Invoke-WebRequest"), fn.index("HashDe $destino"), fn.index("if ($real -ne $sha256.ToLower())")
    borra = fn.index("Remove-Item -LiteralPath $destino -Force")
    assert web < hash_ < cmp_ < borra < fn.index("throw", borra)        # descarga, hash, comparación y, si no coincide: borra y corta


def test_los_instaladores_ejecutables_tambien_verifican_la_firma_digital():
    c = codigo(HABILITAR)
    assert c.count("VerificarFirma $instalador") == 2 and "$f.Status -ne 'Valid'" in c
    assert c.index("VerificarFirma $instalador") < c.index("Start-Process -FilePath $instalador")


def test_el_driver_se_instala_a_mano_con_su_asistente_y_otra_confirmacion():
    c = codigo(HABILITAR)
    assert "Confirmar 'INSTALAR'" in c
    assert "Start-Process -FilePath $instalador -Wait" in c                    # sin parámetros de instalación silenciosa
    assert not re.search(r"PawnIO.*(-silent|/S\b|-install)", c, re.I)


def test_las_carpetas_con_privilegios_solo_se_escriben_por_system_y_administradores_y_se_verifica():
    c = codigo(HABILITAR)
    assert "'*S-1-5-18:(OI)(CI)F'" in c and "'*S-1-5-32-544:(OI)(CI)F'" in c and "'*S-1-5-32-545:(OI)(CI)RX'" in c and "/inheritance:r" in c
    assert c.count("PonerPermisos $d") == 1 and c.count("VerificarPermisos $d") == 1
    assert c.index("PonerPermisos $d") < c.index("VerificarPermisos $d") < c.index("Copy-Item -LiteralPath $origenAyudante")
    assert "Everyone" not in c and "'Users'" not in c                         # los permisos van por SID, no por nombre (no dependen del idioma)


def test_las_tareas_con_privilegios_son_solo_dos_y_con_la_identidad_acordada():
    c = codigo(HABILITAR)
    assert len(re.findall(r"Register-ScheduledTask", c)) == 2
    assert "-UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest" in c
    assert "-UserId $usuario -LogonType Interactive -RunLevel Highest" in c
    assert "-File \"{0}\"' -f $destinoAyudante" in c and "-ExecutionPolicy Bypass" in c
    assert "(New-TimeSpan -Minutes 15)" in c and "-AtStartup" in c and "-ExecutionTimeLimit (New-TimeSpan -Minutes 5)" in c and "-Hidden" in c
    assert "Set-ExecutionPolicy" not in c


def test_deshacer_quita_lo_instalado_y_no_toca_los_datos_ni_el_driver():
    c = codigo(HABILITAR)
    bloque = c[c.index("if ($Deshacer) {\n        Titulo 'Deshaciendo'"):c.index("Titulo '1. Carpetas y permisos'")]
    assert "QuitarTarea $TareaAyudante" in bloque and "QuitarTarea $TareaLhm" in bloque and "Remove-Item -LiteralPath $d -Recurse -Force" in bloque
    assert "foreach ($d in $DirAyudante, $DirSalida)" in bloque
    assert "LOCALAPPDATA" not in bloque and "PawnIO" not in bloque.replace("PawnIO desde", "")                # no desinstala el driver ni toca la carpeta de datos
    assert "StartsWith($DirAyudante" in bloque                                                           # solo detiene el LibreHardwareMonitor que es el suyo


def test_el_instalador_registra_lo_que_instalo():
    c = codigo(HABILITAR)
    assert "instalado.json" in c and "$manifiesto.librehardwaremonitor" in c and "$manifiesto.smartmontools" in c and "$manifiesto.pawnio" in c


def test_ningun_script_toca_la_carpeta_de_datos_de_pc_doctor():
    for ruta in (AYUDANTE, HABILITAR):
        assert "LOCALAPPDATA" not in codigo(ruta).upper() and "USERPROFILE" not in codigo(ruta).upper()


# ---------- versiones.toml ----------

def test_versiones_toml_solo_tiene_secciones_y_claves_con_texto_entre_comillas():
    # habilitar-sensores.ps1 lo lee línea por línea (Windows PowerShell 5.1 no trae un lector de TOML)
    for linea in VERSIONES.read_text(encoding="utf-8").splitlines():
        l = linea.strip()
        assert not l or l.startswith("#") or re.fullmatch(r"\[[a-z0-9_]+\]", l) or re.fullmatch(r'[a-z0-9_]+ = "[^"]*"', l), linea


def test_cada_descarga_fijada_tiene_version_direccion_de_github_y_sha256():
    tomllib = pytest.importorskip("tomllib")
    d = tomllib.loads(VERSIONES.read_text(encoding="utf-8"))
    assert set(d) == {"librehardwaremonitor", "smartmontools", "pawnio"}
    for nombre, s in d.items():
        assert set(s) == {"version", "url", "sha256"} and re.fullmatch(r"[0-9a-f]{64}", s["sha256"]), nombre
        assert s["url"].startswith("https://github.com/") and s["version"] in s["url"], nombre
    assert d["librehardwaremonitor"]["sha256"] == "086d9f1b5a99e643edc2cfaaac16051685b551e4c5ac0b32a57c58c0e529c001"   # verificado contra el hash que publica GitHub
