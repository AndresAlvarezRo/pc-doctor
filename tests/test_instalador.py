"""Revisión estática de los scripts de PowerShell del instalador. Acá no hay PowerShell: lo que se comprueba es que los archivos
cumplan las reglas de seguridad del diseño (lo elevado hace lo mínimo, nada se instala sin verificar el hash, nada se deshace de más)
y que estén guardados de forma que Windows PowerShell 5.1 los lea bien."""

import re
from pathlib import Path

import pytest

DIR = Path(__file__).resolve().parent.parent / "instalador"
AYUDANTE = DIR / "ayudante.ps1"
HABILITAR = DIR / "habilitar-sensores.ps1"
INSTALAR = DIR / "instalar.ps1"
VERSIONES = DIR / "versiones.toml"


def codigo(ruta: Path) -> str:
    """El archivo sin las líneas de comentario."""
    return "\n".join(l for l in ruta.read_text(encoding="utf-8-sig").splitlines() if not l.lstrip().startswith("#"))


# ---------- formato ----------

@pytest.mark.parametrize("ruta", [AYUDANTE, HABILITAR, INSTALAR])
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
    assert set(d) == {"pc_doctor", "uv", "python", "librehardwaremonitor", "smartmontools", "pawnio"}
    assert set(d["python"]) == {"version"}      # lo descarga uv, que verifica su propia integridad
    assert set(d["pc_doctor"]) == {"version"}   # la versión de este paquete, no una descarga
    for nombre, s in ((n, v) for n, v in d.items() if n not in ("python", "pc_doctor")):
        assert set(s) == {"version", "url", "sha256"} and re.fullmatch(r"[0-9a-f]{64}", s["sha256"]), nombre
        assert s["url"].startswith("https://github.com/") and s["version"] in s["url"], nombre
    assert d["librehardwaremonitor"]["sha256"] == "086d9f1b5a99e643edc2cfaaac16051685b551e4c5ac0b32a57c58c0e529c001"   # verificado contra el hash que publica GitHub


# ---------- instalar.ps1 ----------

def test_instalar_no_pide_administrador_y_las_tareas_corren_con_privilegios_limitados():
    c = codigo(INSTALAR)
    assert "RunLevel Limited" in c and "RunLevel Highest" not in c
    assert not re.search(r"-Verb\s+RunAs|#requires\s+-RunAsAdministrator", INSTALAR.read_text(encoding="utf-8-sig"), re.I)
    assert "SYSTEM" not in c and "S-1-5-18" not in c


def test_instalar_nunca_ejecuta_el_ayudante_solo_lo_ofrece():
    c = codigo(INSTALAR)
    c = c[c.index("Set-StrictMode"):]             # sin el bloque de ayuda del principio
    assert not re.search(r"(?m)^\s*(&|\.|Start-Process|Invoke-Expression)\b.*(habilitar-sensores|ayudante\.ps1)", c)
    assert not re.search(r"-ArgumentList.*habilitar", c)
    assert "habilitar-sensores.ps1" in c           # lo ofrece: imprime el comando con -Simular, que no cambia nada
    for linea in c.splitlines():
        if "habilitar-sensores.ps1" in linea:
            assert linea.strip().startswith("Escribir"), linea


def test_instalar_tiene_las_tres_opciones_y_es_idempotente():
    t = INSTALAR.read_text(encoding="utf-8-sig")
    param = t[t.index("param("):t.index(")\n\nSet-StrictMode")]
    assert sorted(re.findall(r"\[switch\]\$(\w+)", param)) == ["Desinstalar", "Simular", "Verificar"]
    assert t.count("Register-ScheduledTask") == 3 and t.count("-Force | Out-Null") >= 3      # registrar de nuevo reemplaza, no duplica
    assert "Unblock-File" in t


def test_instalar_descarga_solo_con_hash_y_de_github():
    c = codigo(INSTALAR)
    assert c.count("Invoke-WebRequest -UseBasicParsing -Uri $url") == 1       # la única descarga está en Descargar
    assert "StartsWith('https://github.com/')" in c
    assert c.index("Get-FileHash") < c.index("return") or "throw" in c
    assert "Expand-Archive" in c and c.index("Descargar $v['uv']['url']") < c.index("Expand-Archive")
    assert "iex" not in c.lower().split() and "Invoke-Expression" not in c


def test_instalar_no_borra_los_datos_ni_pisa_el_claude_md_del_usuario():
    c = codigo(INSTALAR)
    for m in re.finditer(r"Remove-Item[^\n]*", c):
        assert "$Datos" not in m.group() and "web_token" not in m.group(), m.group()
    assert "WriteAllText($md" not in c and "Set-Content" not in c and "Out-File" not in c   # el CLAUDE.md lo maneja actualizar.py, solo dentro de sus marcas
    assert "'claude-md'" in c and "actualizar.py" in c


def test_instalar_usa_el_entorno_exacto_del_lock_y_sin_dependencias_de_desarrollo():
    assert "sync --frozen --no-dev" in codigo(INSTALAR)


def test_las_tareas_de_instalar_coinciden_con_los_nombres_que_usa_el_codigo():
    from plataforma import windows_notificaciones as wn
    c = codigo(INSTALAR)
    assert "$TareaWeb = 'pc-doctor-web'" in c and "pc-doctor-web" in wn.SCRIPT_ARRANCAR
    assert "dashboard.py abrir" in c                                      # el acceso directo hace lo mismo que `dashboard.py abrir`
    assert "--host 127.0.0.1" in c                                         # el dashboard escucha solo en local
    assert "0.0.0.0" not in c


def test_los_archivos_que_nombra_instalar_existen_en_el_repo():
    for nombre in ("lanzador.pyw", "verificar.py", "versiones.toml", "PROMPT-VERIFICACION.md", "INSTALAR-WINDOWS.md"):
        assert (DIR / nombre).is_file(), nombre


# ---------- actualización en el lugar ----------

def test_instalar_actualiza_en_el_lugar_con_copia_previa_y_sin_tocar_los_datos():
    c = codigo(INSTALAR)
    assert "function VersionInstalada" in c and "'1.0'" in c                       # la 1.0 no traía version.txt
    # el orden: parar -> copia previa -> copiar el código -> migrar y mezclar config -> registrar tareas -> recién al final anotar la versión
    orden = ["PararTodo", "'respaldar'", "CopiarPrograma\n", "'aplicar'", "RegistrarTareas\n", "Copy-Item -LiteralPath (Join-Path $Origen 'version.txt')"]
    cuerpo = c[c.index("ComprobarSistema\n    $v = "):]
    posiciones = [cuerpo.index(x) for x in orden]
    assert posiciones == sorted(posiciones), orden
    assert "'version.txt'" in c.split("function CopiarPrograma")[1].split("function PrepararDatos")[0]   # el copiado general la excluye
    assert "no se baja de versión" in c.lower() or "No se baja de versión" in c


def test_simular_muestra_la_actualizacion_sin_cambiar_nada():
    c = codigo(INSTALAR)
    plan = c.split("function MostrarPlan")[1].split("function InstalarUv")[0]
    assert "'plan'" in plan and "ACTUALIZACIÓN" in plan and "migraciones" in plan and "opciones_nuevas" in plan
    assert c.rindex("MostrarPlan $v") < c.rindex("if ($Simular)") < c.rindex("PararTodo")


def test_la_version_es_la_misma_en_pyproject_versiones_y_el_paquete():
    import tomllib
    raiz = DIR.parent
    v = tomllib.loads((raiz / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert tomllib.loads(VERSIONES.read_text(encoding="utf-8"))["pc_doctor"]["version"] == v
