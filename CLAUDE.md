# pc-doctor

Sistema de diagnóstico de la PC (Zorin OS 17 / Ubuntu 24.04) en dos partes:

1. `collector.py`: recolector pasivo; lo ejecuta un systemd user timer (cada 15 min y al boot). Guarda en SQLite.
2. `server.py`: servidor MCP (FastMCP) para consultar historial, estado en vivo y ejecutar acciones seguras.

`seguridad.py` hace el escaneo de seguridad (lo usan el recolector y el servidor).
`linea_base.py` aprende los valores normales (registro diario, línea base, anomalías y deriva).
`salud.py` lee sensores, aplica reglas de valores normales y envía alertas de salud.
`db.py` tiene el esquema, la conexión y los helpers compartidos (sensores, parseo de fechas, procesos).

## Convenciones
- Todo el código, comentarios y docstrings van en español.
- La base está en `~/.local/share/pc-doctor/doctor.db` (fuera del repo).
- Timestamps (`ts`) como epoch UTC en segundos (INTEGER).
- Comandos externos: siempre vía `db.ejecutar()`; si fallan se loguea y se sigue, nunca se crashea.
- Las respuestas del MCP deben ser compactas (listas truncadas, resúmenes).
- Nada se borra: `limpiar_descargas_viejas` mueve a `~/.local/share/pc-doctor/cuarentena/<fecha>/` y registra en `cuarentena` y `acciones`.
- No usar `sudo`. Entorno con `uv` (`uv sync`, `uv run`).

## Visibilidad y bitácora
- Todo el proyecto debe verse en el explorador de archivos: no crear archivos ni carpetas con punto. `venv` y `datos` son symlinks visibles hacia `.venv` y `~/.local/share/pc-doctor`.
- Cada decisión de diseño se registra en `BITACORA.md`.

## Changelog de la PC (pc-doctor)
Cada vez que el usuario revise algo del funcionamiento de su PC (errores, soluciones, cambios de hardware, software, drivers, kernel o configuración), antes de cerrar la respuesta:
1. Agregá una entrada arriba de "Entradas" en `/home/v/Desktop/Practicas-IA/pc-doctor/CHANGELOG.md` con: fecha, título, tipo (error, solución, cambio u observación), detalle breve y estado (abierto o resuelto). Si un problema abierto se resuelve, actualizá esa entrada en vez de duplicarla.
2. Si algo de la identidad del equipo cambió (SO, kernel, GPU/driver, RAM, discos, paquetes relevantes, etc.), reescribí la tabla "Identidad actual" y su fecha. Podés usar `perfil_entorno()` y `cambios_entorno()` del MCP pc-doctor para verificar los datos.
3. Registrá solo hechos verificados, de forma breve. No dupliques datos que ya están en la base de pc-doctor.

## Privacidad (seguridad)
- Los datos se guardan en la PC. Online solo se consulta el hash de ejecutables ya marcados como sospechosos; nunca se suben archivos ni se consultan procesos no sospechosos.
- Los cambios a servicios del usuario se verifican después de aplicarlos y se registran en `BITACORA.md` y `CHANGELOG.md`.
- Las pruebas que envíen notificaciones de escritorio reales se avisan antes al usuario, con el texto que se va a mostrar (usar un notificador falso en las pruebas automáticas).
- Los scripts que necesitan `sudo` se dejan en el proyecto para que el usuario los revise y los ejecute; nunca se ejecutan sin su aprobación.
