"""Reglas de salud: avisos sostenidos, persistencia, escalada, histéresis, límites del hardware, ventiladores, discos,
memoria, voltajes, eventos del journal, agrupación de avisos, lectura de hwmon y parser de nvidia-smi.

Rescatadas de las comprobaciones de las primeras etapas del proyecto (ver BITACORA.md, "Alertas de salud del equipo")."""

import pytest
from ayudas import L

import db
import salud


class Simulador:
    """Simula las corridas del recolector: guarda las lecturas, evalúa, aplica y avisa (con un notificador falso)."""

    def __init__(self, con):
        self.con = con
        self.enviados = []
        self.cfg = {"umbrales": {}}
        self.t = 1_000_000

    def _falso(self, titulo, msg, critica=False, **extra):
        self.enviados.append((titulo, msg, critica))
        return True

    def corrida(self, lecturas, extra=None):
        self.t += 900
        salud.guardar_lecturas(self.con, 1, self.t, lecturas)
        activas = {f["clave"] for f in self.con.execute("SELECT clave FROM alertas_salud WHERE activa=1")}
        conds = salud.condiciones(self.con, lecturas, self.cfg, activas, en_base=True)
        conds.update(extra or {})
        r = salud.aplicar_condiciones(self.con, conds, {l["nombre"] for l in lecturas}, self.t)
        antes = len(self.enviados)
        salud.enviar_aviso(self.con, r["a_avisar"], self.t, self._falso)
        return conds, r, len(self.enviados) - antes


@pytest.fixture
def sim(con):
    return Simulador(con)


def test_temperatura_sostenida_persistencia_escalada_e_histeresis(sim):
    # sostenido: 86 °C una vez no avisa; dos veces seguidas, sí
    c, r, n = sim.corrida([L("k10temp/Tctl", 86)])
    assert not c and n == 0
    c, r, n = sim.corrida([L("k10temp/Tctl", 86)])
    assert len(c) == 1 and n == 1
    # persistencia: no repite hasta pasadas 6 h
    assert sim.corrida([L("k10temp/Tctl", 87)])[2] == 0
    sim.t += 6 * 3600
    assert sim.corrida([L("k10temp/Tctl", 87)])[2] == 1
    # escalada a crítico: avisa de inmediato y la notificación es crítica
    c, r, n = sim.corrida([L("k10temp/Tctl", 93)])
    assert n == 1 and sim.enviados[-1][2] is True
    # histéresis: 83 °C (aviso en 85, margen de 4) no resuelve; 80 °C sí, en silencio
    c, r, n = sim.corrida([L("k10temp/Tctl", 83)])
    assert len(c) == 1 and not r["resueltas"]
    c, r, n = sim.corrida([L("k10temp/Tctl", 80)])
    assert not c and len(r["resueltas"]) == 1 and n == 0


def test_poco_espacio_libre_escala_a_critico(sim):
    c, _, _ = sim.corrida([L("fs:/home/libre_pct", 12, "disco", "%")])
    assert list(c.values())[0]["severidad"] == "aviso"
    c, _, _ = sim.corrida([L("fs:/home/libre_pct", 5, "disco", "%")])
    assert list(c.values())[0]["severidad"] == "critico"


def test_limite_critico_que_informa_el_propio_hardware(sim):
    # NVMe con crit 87,8 °C: el aviso baja a 69,8 y el crítico a 79,8
    c, _, _ = sim.corrida([L("nvme/Composite", 82, "disco", crit=87.8)])
    assert c and list(c.values())[0]["severidad"] == "critico"


def test_gpu_necesita_dos_lecturas_seguidas(sim):
    g = lambda: [L("amdgpu/junction", 95, "gpu", crit=110.0)]
    assert sim.corrida(g())[2] == 0
    assert sim.corrida(g())[2] == 1


def test_ventilador_detenido_con_el_chip_caliente(sim):
    # el ventilador giraba antes: ahora a 0 RPM con el chip a 82 °C es crítico
    sim.corrida([L("amdgpu/fan1", 900, "gpu", "RPM"), L("amdgpu/edge", 50, "gpu", crit=110.0)])
    c, _, _ = sim.corrida([L("amdgpu/fan1", 0, "gpu", "RPM"), L("amdgpu/edge", 82, "gpu", crit=110.0)])
    assert any(k.startswith("ventilador:") and v["severidad"] == "critico" for k, v in c.items())
    # a 0 RPM con el chip frío (modo silencioso normal): sin alerta de ventilador
    c, _, _ = sim.corrida([L("amdgpu/fan1", 0, "gpu", "RPM"), L("amdgpu/edge", 50, "gpu", crit=110.0)])
    assert not any(k.startswith("ventilador:") for k in c)


def test_conector_de_ventilador_vacio_no_genera_alerta(sim):
    # un conector sin ventilador marca 0 RPM siempre: nunca giró, así que no cuenta como "detenido"
    for _ in range(3):
        c, _, _ = sim.corrida([L("nct6798/fan1", 0, "placa", "RPM"), L("nct6798/TSI0_TEMP", 84, "placa")])
        assert not any(k.startswith("ventilador:") for k in c)


@pytest.mark.parametrize("lectura,prefijo,severidad", [
    ([L("fs:/home/solo_lectura", 1, "disco", "bool")], "disco_ro:", None),
])
def test_particion_en_solo_lectura(sim, lectura, prefijo, severidad):
    c, _, _ = sim.corrida(lectura)
    assert any(k.startswith(prefijo) for k in c)


def test_disco_saturado_tras_tres_lecturas(sim):
    for _ in range(3):
        c, _, _ = sim.corrida([L("sda/io_util_pct", 99, "disco", "%")])
    assert any(k.startswith("disco_io:") for k in c)


def test_ram_alta_sostenida(sim):
    for _ in range(2):
        c, _, _ = sim.corrida([L("memoria/ram_pct", 93, "memoria", "%")])
    assert any(k.startswith("ram:") for k in c)


def test_voltaje_del_nucleo_de_la_gpu(sim):
    c, _, _ = sim.corrida([L("amdgpu/vddgfx", 1400, "gpu", "mV")])
    assert list(c.values())[0]["severidad"] == "critico"
    assert not sim.corrida([L("amdgpu/vddgfx", 707, "gpu", "mV")])[0]


def test_riel_de_la_placa_con_desviacion_negativa_es_critico(sim):
    for _ in range(2):
        c, _, _ = sim.corrida([L("nct/+12V/desviacion_pct", -11.5, "placa", "%")])
    assert any(v["severidad"] == "critico" for v in c.values())  # la desviación se compara en valor absoluto


def test_umbral_personalizado_del_usuario(sim):
    sim.cfg["umbrales"] = {"temp_cpu": {"aviso": 70, "muestras": 1}}
    c, _, n = sim.corrida([L("k10temp/Tctl", 72)])
    assert len(c) == 1 and n == 1


# ---------- eventos del journal ----------

BENIGNOS = ["thermal_sys: Registered thermal governor 'fair_share'", "EDAC MC: Ver: 3.0.0", "MCE: In-kernel MCE decoding enabled.",
            "amdgpu 0000:09:00.0: ring gfx_0.0.0 uses VM inv eng 0 on hub 0", "systemd: Started pc-doctor", "kernel: Linux version 7.0.0"]
REALES = {
    "disco_ext4": "kernel: EXT4-fs error (device sda1): ext4_find_entry:1455: inode #2: comm ls: reading directory lblock 0",
    "disco_io": "kernel: blk_update_request: I/O error, dev nvme0n1, sector 4096 op 0x0:(READ)",
    "gpu": "kernel: amdgpu 0000:09:00.0: amdgpu: ring gfx_0.0.0 timeout, signaled seq=1 emitted seq=3",
    "memoria": "kernel: Out of memory: Killed process 4242 (chrome) total-vm:9876kB",
    "termico": "kernel: CPU3: Package temperature above threshold, cpu clock throttled",
}


@pytest.mark.parametrize("mensaje", BENIGNOS)
def test_mensajes_normales_del_arranque_no_son_falsos_positivos(mensaje):
    assert not any(rx.search(mensaje) for *_, rx in salud.PATRONES_EVENTO)


@pytest.mark.parametrize("mensaje", REALES.values(), ids=REALES.keys())
def test_eventos_graves_se_detectan(mensaje):
    assert any(rx.search(mensaje) for *_, rx in salud.PATRONES_EVENTO)


def test_ciclo_de_vida_de_una_alerta_por_evento(con):
    enviados = []
    falso = lambda t, m, critica=False, **k: enviados.append(m) or True
    ahora = 2_000_000
    con.execute("INSERT INTO eventos (ts, origen, severidad, mensaje) VALUES (?,?,?,?)", (ahora, "kernel", "err", "blk_update_request: I/O error, dev sda, sector 8"))
    c = salud.condiciones_eventos(con, ahora)
    r = salud.aplicar_condiciones(con, c, set(), ahora)
    assert "evento:disco_io" in c and len(r["a_avisar"]) == 1
    salud.enviar_aviso(con, r["a_avisar"], ahora, falso)
    assert not salud.aplicar_condiciones(con, c, set(), ahora + 900)["a_avisar"]  # el mismo evento 15 min después: no repite
    con.execute("INSERT INTO eventos (ts, origen, severidad, mensaje) VALUES (?,?,?,?)", (ahora + 1000, "kernel", "err", "EXT4-fs error (device sda1)"))
    c = salud.condiciones_eventos(con, ahora + 1100)
    assert len(salud.aplicar_condiciones(con, c, set(), ahora + 1100)["a_avisar"]) == 1  # un evento NUEVO dentro de la ventana avisa otra vez
    assert salud.aplicar_condiciones(con, {}, set(), ahora + 90000)["resueltas"] == ["evento:disco_io"]  # 24 h sin eventos: se resuelve


def test_siete_alertas_salen_en_un_solo_aviso_con_resumen(con):
    muchas = {f"x{i}": {"clave": f"x{i}", "categoria": "cpu", "nombre": "n", "severidad": "aviso", "valor": 1, "mensaje": f"msg{i}"} for i in range(7)}
    for k in muchas:
        con.execute("INSERT INTO alertas_salud (clave, severidad, mensaje, valor, desde, ultima_vez) VALUES (?,?,?,?,?,?)", (k, "aviso", "m", 1, 1, 1))
    enviados = []
    salud.enviar_aviso(con, list(muchas.values()), 5, lambda t, m, **k: enviados.append(m) or True)
    assert len(enviados) == 1 and "y 3 más" in enviados[0]


def test_enviar_aviso_no_marca_como_avisadas_las_alertas_si_el_envio_falla(con):
    con.execute("INSERT INTO alertas_salud (clave, severidad, mensaje, valor, desde, ultima_vez, ultima_notif) VALUES ('a','aviso','m',1,1,1,0)")
    cond = [{"clave": "a", "categoria": "cpu", "severidad": "aviso", "mensaje": "m"}]
    assert salud.enviar_aviso(con, cond, 99, lambda *a, **k: False) is False
    assert con.execute("SELECT ultima_notif FROM alertas_salud WHERE clave='a'").fetchone()[0] == 0  # se reintenta en la próxima corrida


# ---------- parser de nvidia-smi ----------

def test_parser_de_nvidia_smi_tolera_na():
    p = salud.parsear_nvidia("45, 12, 1024, 8192, 35.20, 30\n[N/A], [N/A], 100, 200, [N/A], [N/A]")
    por_nombre = {l["nombre"]: l["valor"] for l in p}
    assert por_nombre["nvidia0/temp"] == 45 and por_nombre["nvidia1/vram_pct"] == 50


# ---------- lectura de hwmon con un árbol falso (sin depender del hardware) ----------

def _chip(raiz, n, nombre, archivos, disco=None):
    d = raiz / f"hwmon{n}"
    d.mkdir(parents=True)
    (d / "name").write_text(nombre + "\n")
    for k, v in archivos.items():
        (d / k).write_text(str(v) + "\n")
    if disco:
        (d / "device" / "block" / disco).mkdir(parents=True)
    return d


@pytest.fixture
def hwmon_falso(tmp_path, monkeypatch):
    raiz = tmp_path / "hwmon"
    raiz.mkdir()
    _chip(raiz, 0, "k10temp", {"temp1_input": 67500, "temp1_label": "Tctl"})
    _chip(raiz, 1, "drivetemp", {"temp1_input": 29000}, disco="sda")
    _chip(raiz, 2, "drivetemp", {"temp1_input": 33000}, disco="sdb")
    _chip(raiz, 3, "nct6798", {
        "temp1_input": 33000, "temp1_label": "SYSTIN",
        "temp3_input": 84000, "temp3_label": "AUXTIN0",          # termistor sin conectar: valor basura
        "temp5_input": -61000, "temp5_label": "AUXTIN2",
        "temp9_input": 56000, "temp9_label": "PECI Agent 0 Calibration",
        "fan1_input": 0, "fan2_input": 1518, "in0_input": 576, "in3_input": 3328})
    _chip(raiz, 4, "amdgpu", {"temp1_input": 50000, "temp1_label": "edge", "temp1_crit": 100000, "temp2_input": 52000, "temp2_label": "junction",
                              "temp2_crit": 65261000})              # límite absurdo que informa el firmware
    monkeypatch.setattr(salud, "HWMON", raiz)
    return raiz


def test_hwmon_ignora_entradas_sin_sensor_real(hwmon_falso):
    nombres = {l["nombre"] for l in salud._hwmon()}
    assert "nct6798/SYSTIN" in nombres
    assert not {n for n in nombres if "AUXTIN" in n or "PECI" in n}


def test_hwmon_nombra_cada_disco_drivetemp_por_separado(hwmon_falso):
    por = {l["nombre"]: l for l in salud._hwmon()}
    assert por["drivetemp_sda/temp1"]["valor"] == 29.0 and por["drivetemp_sdb/temp1"]["valor"] == 33.0
    assert por["drivetemp_sda/temp1"]["categoria"] == "disco"


def test_hwmon_categorias_unidades_y_limites(hwmon_falso):
    por = {l["nombre"]: l for l in salud._hwmon()}
    assert por["k10temp/Tctl"]["categoria"] == "cpu" and por["amdgpu/edge"]["categoria"] == "gpu"
    assert por["nct6798/fan2"]["unidad"] == "RPM" and por["nct6798/in0"]["unidad"] == "mV"
    assert por["amdgpu/edge"]["crit"] == 100.0
    assert por["amdgpu/junction"]["crit"] is None  # el límite de 65261 °C se descarta por absurdo
