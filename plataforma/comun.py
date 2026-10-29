"""Lo que comparten los dos backends y no depende del sistema."""

import logging

log = logging.getLogger("pc-doctor")

# IDs de proveedor PCI conocidos; cualquier otro se informa con su ID crudo.
PROVEEDORES_PCI = {
    "10de": "NVIDIA", "1002": "AMD", "1022": "AMD", "8086": "Intel",
    "1a03": "ASPEED", "15ad": "VMware", "1af4": "Red Hat (virtio)", "1234": "QEMU",
    "5143": "Qualcomm", "13b5": "ARM", "1414": "Microsoft", "80ee": "VirtualBox",
}


def lista(valor) -> list:
    """PowerShell convierte una lista de un solo elemento en un objeto suelto y una vacía en nada: siempre devuelve una lista."""
    if valor is None:
        return []
    return valor if isinstance(valor, list) else [valor]


def lectura(cat: str, nombre: str, valor: float, unidad: str, crit: float | None = None) -> dict:
    """Una lectura con el mismo formato que las de salud.py (`_l`)."""
    return {"categoria": cat, "nombre": nombre, "valor": round(float(valor), 2), "unidad": unidad, "crit": crit}
