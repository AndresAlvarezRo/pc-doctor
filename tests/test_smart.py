"""Lectura de SMART: el parser (con salidas JSON del formato de smartctl 7.4) y las reglas de alerta sobre sus resultados.

Nada llama a `smartctl` ni a `sudo`: se prueba solo el texto que devolvería."""

import pytest

import salud

ATA = ('{"smart_status":{"passed":true},"power_on_time":{"hours":9120},"ata_smart_attributes":{"table":['
       '{"id":5,"raw":{"value":0}},{"id":197,"raw":{"value":0}},{"id":198,"raw":{"value":0}},{"id":199,"raw":{"value":3}},'
       '{"id":231,"value":96,"raw":{"value":4}}]}}')
NVME = ('{"smart_status":{"passed":true},"nvme_smart_health_information_log":{"critical_warning":0,"percentage_used":3,'
        '"available_spare":100,"media_errors":0},"power_on_time":{"hours":500}}')


def valores(dev, texto):
    return {l["nombre"]: l["valor"] for l in salud.parsear_smart(dev, texto)}


def test_sata_salud_crc_desgaste_y_horas():
    p = valores("sda", ATA)
    assert p["sda/smart_ok"] == 1 and p["sda/errores_crc"] == 3 and p["sda/desgaste_pct"] == 4 and p["sda/horas_encendido"] == 9120


def test_nvme_desgaste_y_reserva():
    q = valores("nvme0n1", NVME)
    assert q["nvme0n1/desgaste_pct"] == 3 and q["nvme0n1/spare_pct"] == 100


def test_smart_fallido_y_sectores_pendientes_son_criticos(con):
    mal = ATA.replace('"passed":true', '"passed":false').replace('"id":197,"raw":{"value":0}', '"id":197,"raw":{"value":12}')
    cs = salud.condiciones(con, salud.parsear_smart("sda", mal), {"umbrales": {}}, set(), en_base=False)
    assert any(k.startswith("smart_fallo:") and v["severidad"] == "critico" for k, v in cs.items())
    assert any(k.startswith("smart_pendientes:") and v["severidad"] == "critico" for k, v in cs.items())


def test_disco_sano_no_genera_alertas(con):
    assert not salud.condiciones(con, salud.parsear_smart("sda", ATA), {"umbrales": {}}, set(), en_base=False)


@pytest.mark.parametrize("texto", ["basura", "", "{}", "[1,2,3]", "null"])
def test_salida_invalida_devuelve_lista_vacia_sin_romper(texto):
    assert salud.parsear_smart("sda", texto) == []
