# pc-doctor

Sistema de diagnóstico de la PC (Zorin OS 18 / Ubuntu 24.04) en tres partes:

1. `collector.py`: recolector pasivo; lo ejecuta un systemd user timer (cada 15 min y al boot). Guarda en SQLite.
2. `server.py`: servidor MCP (FastMCP) para consultar historial, estado en vivo y ejecutar acciones seguras (35 tools).
3. `web/`: dashboard local. Backend FastAPI en `web/api.py` (solo `127.0.0.1:8787`, solo lectura por ahora) y frontend React + Vite + TypeScript + Recharts en `web/frontend/`, que se compila con `bash web/construir.sh` a `web/frontend/dist/` y lo sirve la propia API. `web/datos_de_prueba.py` genera datos sintéticos; `web/generar_iconos.py`, los íconos.

Módulos compartidos (el dashboard y el MCP muestran exactamente lo mismo porque usan las mismas funciones):
- `db.py`: esquema, conexión (con modo de solo lectura para el dashboard) y helpers (sensores, fechas, procesos).
- `consultas.py`: consultas compartidas (alertas, hallazgos, sesiones, estado en vivo, componentes, series con banda de la línea base).
- `salud.py`: lee sensores, aplica reglas de valores normales y envía alertas de salud.
- `linea_base.py`: aprende los valores normales (registro diario, línea base por contexto reposo/carga/juego, anomalías y deriva).
- `actividad.py`: detecta juegos por procesos y registra sesiones; migra el historial al contexto `juego`.
- `correlacion.py`: posibles causas de una alerta (cambios de entorno, eventos, sesiones...) y línea de tiempo.
- `seguridad.py` y `reputacion.py`: escaneo de seguridad y consulta de reputación (solo de hashes de ejecutables sospechosos).
- `alertas.py`: notificaciones de escritorio, con botón "Ver en el dashboard". `dashboard.py`: abre el dashboard (URL, arranque del servicio, navegador).
- `reporte.py`: reporte semanal redactado por `claude -p` con tools de solo lectura (plan B determinístico si falla).
- `systemd/`: unidades de usuario (recolector, reporte semanal, dashboard). `tests/`: suite de pruebas. `scripts/`: hooks de git.

## Convenciones
- Todo el código, comentarios y docstrings van en español.
- La base está en `~/.local/share/pc-doctor/doctor.db` (fuera del repo).
- Timestamps (`ts`) como epoch UTC en segundos (INTEGER).
- Comandos externos: siempre vía `db.ejecutar()`; si fallan se loguea y se sigue, nunca se crashea.
- Las respuestas del MCP deben ser compactas (listas truncadas, resúmenes).
- Nada se borra: `limpiar_descargas_viejas` mueve a `~/.local/share/pc-doctor/cuarentena/<fecha>/` y registra en `cuarentena` y `acciones`.
- No usar `sudo`. Entorno con `uv` (`uv sync`, `uv run`).
- Interfaz del dashboard en español rioplatense, con mayúscula solo al inicio de cada frase; el color nunca va solo (siempre con ícono y texto).

## Visibilidad y bitácora
- El proyecto debe verse en el explorador de archivos: no crear archivos ni carpetas con punto. **Excepción (para git):** `.gitignore`, `.git/`, `.github/` y lo que git necesite. `venv` y `datos` son symlinks visibles hacia `.venv` y `~/.local/share/pc-doctor`.
- Cada decisión de diseño, error encontrado y limitación se registra en `BITACORA.md`.

## Pruebas
- `uv run pytest` corre todo (unos 26 s). Marcadores: `lento` (procesos, esperas, datos sintéticos grandes; el hook pre-commit corre `-m "not lento"`, unos 9 s) y `local` (leen sensores o procesos reales de esta PC; en CI se saltean con `-m "not local"`).
- Ninguna prueba puede tocar la base real, la configuración real, `~/.steam`, `~/.local/bin/claude` ni servicios reales: `tests/conftest.py` usa una carpeta de datos y un `HOME` temporales y pone los reemplazos de `tests/falsos/` (`notify-send`, `systemd-run`, `systemctl`, `gdbus`, `xdg-open`, `claude`) al principio del `PATH`. Los sensores y los procesos están bloqueados salvo en las marcadas `local`. Una prueba nueva sigue las mismas reglas.
- Al corregir un error, agregar la prueba que lo habría detectado.

## Flujo de git
- Al terminar cada cambio coherente (no cada archivo suelto), correr `uv run pytest`.
- Si pasan: hacer commit con un mensaje en español, en imperativo, con una primera línea corta y, si hace falta, un párrafo explicando el porqué. Prefijos: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`. El mensaje termina con la línea `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- El commit incluye la entrada correspondiente de `BITACORA.md`, si la hay.
- Después del commit, `git push`.
- Si las pruebas fallan, **no** se hace commit: se informa y se espera.
- Nunca usar `git push --force`, `git reset --hard` ni reescribir historial sin preguntar.
- Antes de cada push, mostrar `git log --oneline origin/main..HEAD` para que quede claro qué se sube.
- El hook `scripts/pre-commit` (se instala con `bash scripts/instalar-hooks.sh`) bloquea el commit si se agregan bases `.db`, `config.json`, `web_token` o algo bajo `datos/`, si aparece algo con forma de secreto, si un archivo pesa más de 1 MiB o si fallan las pruebas rápidas. No usar `--no-verify` sin preguntar.

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
