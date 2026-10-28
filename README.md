# pc-doctor

Sistema de diagnóstico de la PC (pensado para Zorin OS / Ubuntu) en dos partes:

1. **Recolector** (`collector.py`): corre cada 15 minutos y al arrancar mediante un systemd user timer, tarda ~2 segundos y guarda métricas, eventos y snapshots del entorno en SQLite.
2. **Servidor MCP** (`server.py`, FastMCP): se usa desde Claude Code para consultar el historial, ver el estado en vivo y ejecutar acciones seguras.

Los datos viven en `~/.local/share/pc-doctor/` (visible desde el proyecto como `datos/`). Las decisiones de diseño están en `BITACORA.md`.

## Instalación
Requisitos: `uv`, `python3`, `lm-sensors` y `lshw` (opcionales: `nvidia-smi`, `flatpak`, `snap`).

```bash
cd ~/Desktop/Practicas-IA/pc-doctor
uv sync                                   # crea el entorno (.venv, visible como venv/)

# Timer de systemd (usuario)
mkdir -p ~/.config/systemd/user
cp systemd/pc-doctor.service systemd/pc-doctor.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now pc-doctor.timer

# Servidor MCP en Claude Code
claude mcp add pc-doctor -s user -- uv run --directory ~/Desktop/Practicas-IA/pc-doctor server.py
```

Verificación: `systemctl --user list-timers pc-doctor.timer` y `claude mcp list`.
Corrida manual: `uv run collector.py`.

## Tools del MCP
| Tool | Qué hace |
|---|---|
| `perfil_entorno()` | Último snapshot: SO, kernel, hardware, drivers |
| `cambios_entorno(desde)` | Paquetes agregados, quitados o cambiados |
| `espacio_disco()` | Espacio en vivo por partición |
| `procesos_que_mas_consumen(n)` | Top de procesos en vivo |
| `temperatura_cpu()` | Temperatura actual |
| `historial(metrica, desde)` | Serie o resumen (mín, máx, promedio, tendencia) |
| `errores_recientes(horas)` | Errores del journal agrupados |
| `limpiar_descargas_viejas(dias, simular)` | Mueve a cuarentena archivos viejos de Descargas (por defecto solo simula) |
| `restaurar_cuarentena(id)` | Devuelve un archivo a su ruta original |
| `revision_seguridad()` | Escaneo en vivo: mineros, procesos fantasma, posibles keyloggers, puertos y conexiones |
| `hallazgos_seguridad(estado, dias)` | Hallazgos guardados, por severidad |
| `marcar_hallazgo(id, estado)` | Marca un hallazgo como revisado o falso positivo |
| `puertos_en_escucha()` | Puertos accesibles desde la red, en vivo |
| `estado_salud()` | Sensores en vivo (CPU, GPU, discos, memoria, ventiladores, voltajes) contra los valores normales |
| `alertas_salud(solo_activas, dias)` | Alertas de salud registradas por el recolector |
| `linea_base_aprendida(categoria, contexto)` | Lo que pc-doctor aprendió como normal de cada componente (reposo y carga) |
| `medias_diarias(sensor, dias)` | Registro diario permanente (media, mínimo, máximo) de un sensor |

## Seguridad
Cada corrida del recolector (~0,4 s extra) revisa procesos y red y guarda los resultados en `hallazgos_seguridad` y `escuchas`.
Contrasta con listas públicas (Feodo Tracker y NoCoin) que se descargan como máximo una vez al día; **nunca se envía información de la PC**.

- **Detecta:** mineros de criptomonedas, procesos fantasma (ejecutan desde `/tmp`, binario borrado, imitan hilos del kernel), lectores de `/dev/input`, puertos accesibles desde la red, terminales web sin contraseña y conexiones a IPs de botnets.
- **No detecta:** rootkits ni lo que hacen procesos de otros usuarios (corre sin root). No es un antivirus: un resultado limpio no garantiza un equipo limpio.
- **Reputación online:** los hashes se calculan y guardan en tu PC. Solo el **hash** de un ejecutable ya marcado como sospechoso se consulta online (Team Cymru por DNS y CIRCL por HTTPS, sin clave); nunca se envía el archivo. Si alguno figura como malware, queda en `alertas` y el hallazgo sube a severidad alta. Se desactiva con `"consulta_online": false` en `~/.local/share/pc-doctor/config.json` (visible en `datos/config.json`). Opcional: una clave gratuita de abuse.ch en `malwarebazaar_key` agrega MalwareBazaar.
- **Alertas de escritorio:** si aparece un hallazgo grave (severidad alta, por ejemplo malware según la reputación online), el recolector envía una notificación, una sola vez por hallazgo y agrupada. Se desactivan con `"notificaciones": false` en `config.json`. Probar con `uv run alertas.py --probar`.
- **Falsos positivos:** marcalos con `marcar_hallazgo(id, "falso_positivo")` y dejan de mostrarse como nuevos.

## Alertas de salud
Cada corrida lee los sensores (se guardan 30 días en la tabla `lecturas`) y los compara con unas reglas de valores normales; si algo se sale, envía **una** notificación de escritorio agrupada.

- **Qué vigila:** temperatura de CPU, GPU, NVMe y placa; ventiladores; voltaje de GPU; uso sostenido de CPU y GPU; VRAM; RAM y swap; carga; espacio libre, saturación y solo-lectura de discos; y errores del kernel (disco, GPU, memoria agotada, limitación térmica).
- **Sin ruido:** el aviso salta tras varias lecturas seguidas (el crítico, con una sola), no se repite hasta 6 h después (2 h si es crítico) y las resueltas se cierran en silencio.
- **Ajustar límites:** en `datos/config.json`, por ejemplo `"umbrales": {"temp_cpu": {"aviso": 80, "muestras": 1}}`. `"salud": false` apaga estas alertas.
- **No disponible en este equipo:** voltajes de la placa y SMART o temperatura de discos SATA (requieren `sudo`; ver `CHANGELOG.md`). `estado_salud()` los informa como no disponibles.

## Valores normales aprendidos
Además de límites fijos, pc-doctor aprende qué es normal **en tu PC**, por componente y por contexto (reposo o carga):

- `lecturas` guarda 30 días de lecturas; `lecturas_diarias` guarda para siempre la media, el mínimo y el máximo de cada día; `linea_base` guarda lo normal de hoy (mediana, media, p95 y p99).
- **Anomalía:** un valor muy fuera de lo habitual dos lecturas seguidas avisa (nunca como crítico). Se activa cuando un sensor tiene unas 200 muestras (~2 días).
- **Deriva:** si en reposo la temperatura sube 6 °C, un ventilador gira 30 % más o el disco pierde 8 puntos libres frente al mes anterior, avisa (como mucho una vez por semana). Necesita ~3 semanas de datos.
- Consultar: `linea_base_aprendida()` y `medias_diarias('k10temp/Tctl')`.

## Habilitar voltajes y SMART
Requiere `sudo`. Revisá `habilitar-sensores.sh` y ejecutá `sudo bash habilitar-sensores.sh`. Instala `smartmontools`, activa `drivetemp`, prueba `nct6775` (voltajes de placa, puede no ser compatible) y permite leer el SMART sin contraseña **solo** con `smartctl -j -H -A` sobre tus discos. Para deshacerlo: `sudo rm /etc/sudoers.d/pc-doctor /etc/modules-load.d/pc-doctor.conf`.

## Desactivar el timer
```bash
systemctl --user disable --now pc-doctor.timer     # detiene y deshabilita
rm ~/.config/systemd/user/pc-doctor.{service,timer} # opcional: quitar las unidades
systemctl --user daemon-reload
claude mcp remove pc-doctor -s user                 # opcional: quitar el MCP
```
La base de datos no se borra; para empezar de cero eliminá `~/.local/share/pc-doctor/doctor.db` a mano.

## Restaurar la cuarentena
`limpiar_descargas_viejas(simular=False)` nunca borra: mueve los archivos a
`~/.local/share/pc-doctor/cuarentena/<fecha>/` y los registra en la tabla `cuarentena`.

- Desde Claude Code: pedí `restaurar_cuarentena(id)` con el id del registro.
- Para ver los ids:
  ```bash
  sqlite3 ~/.local/share/pc-doctor/doctor.db \
    "select id, ruta_original, tamano_bytes, restaurado from cuarentena order by id desc limit 20"
  ```
- O a mano: mové el archivo desde `cuarentena/<fecha>/` a su ruta original. La restauración con la tool no pisa archivos que ya existan en el destino.
