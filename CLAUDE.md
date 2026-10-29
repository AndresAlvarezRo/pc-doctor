# pc-doctor

Diagnóstico de la PC (Zorin OS 18 / Ubuntu 24.04): recolector, servidor MCP y dashboard local. La arquitectura y los módulos están en `README.md`.

## Convenciones
- Todo el código, comentarios y docstrings van en español.
- La base está en `~/.local/share/pc-doctor/doctor.db` (fuera del repo). Timestamps (`ts`) como epoch UTC en segundos (INTEGER).
- Comandos externos: siempre vía `db.ejecutar()`; si fallan se loguea y se sigue, nunca se crashea.
- Las respuestas del MCP deben ser compactas (listas truncadas, resúmenes).
- Nada se borra: `limpiar_descargas_viejas` mueve a cuarentena y registra en `cuarentena` y `acciones`.
- No usar `sudo`. Entorno con `uv` (`uv sync`, `uv run`).
- Interfaz del dashboard en español rioplatense, con mayúscula solo al inicio de cada frase; el color nunca va solo (siempre con ícono y texto).
- El proyecto debe verse en el explorador de archivos: no crear archivos ni carpetas con punto. Excepción (para git): `.gitignore`, `.git/`, `.github/` y lo que git necesite.

## Memoria
- Antes de responder sobre la PC o el proyecto, usar `buscar_memoria`, `hechos_conocidos` y `changelog_abierto` en vez de suponer.
- Registrar cada decisión de diseño, error encontrado y limitación con `registrar_bitacora`, y cada revisión del funcionamiento de la PC con `registrar_changelog` (`resolver_changelog` si cierra una entrada abierta).
- `BITACORA.md` y `CHANGELOG.md` son archivos generados desde la base: no se editan a mano (el hook pre-commit los regenera con `uv run memoria.py --exportar`). `memoria` y `hechos_conocidos` no se exportan a git.
- Si cambia una fila de la identidad de la PC que no se calcula sola (energía, red expuesta, sensores extra, Node.js), actualizarla con `registrar_identidad`.
- Los hechos conocidos solo se declaran o retiran si el usuario lo pide de forma explícita.

## Pruebas
- `uv run pytest` corre todo. Marcadores: `lento` (el hook pre-commit corre `-m "not lento"`) y `local` (leen sensores o procesos reales; en CI se saltean con `-m "not local"`).
- Ninguna prueba puede tocar la base real, la configuración real, `~/.steam`, `~/.local/bin/claude` ni servicios reales: `tests/conftest.py` usa una carpeta de datos y un `HOME` temporales y los reemplazos de `tests/falsos/` en el `PATH`. Una prueba nueva sigue las mismas reglas.
- Al corregir un error, agregar la prueba que lo habría detectado.

## Flujo de git
- Al terminar cada cambio coherente (no cada archivo suelto), correr `uv run pytest`. Si pasan, commit en español, en imperativo, primera línea corta y, si hace falta, un párrafo con el porqué. Prefijos: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`. El mensaje termina con `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Después del commit, `git push`. Si las pruebas fallan, no se hace commit: se informa y se espera.
- Nunca `git push --force`, `git reset --hard` ni reescribir historial sin preguntar. Antes de cada push, mostrar `git log --oneline origin/main..HEAD`.
- El hook `scripts/pre-commit` (se instala con `bash scripts/instalar-hooks.sh`) bloquea bases `.db`, `config.json`, `web_token`, `datos/`, secretos, archivos de más de 1 MiB y pruebas rápidas rotas. No usar `--no-verify` sin preguntar.

## Privacidad (seguridad)
- Los datos se guardan en la PC. Online solo se consulta el hash de ejecutables ya marcados como sospechosos; nunca se suben archivos ni se consultan procesos no sospechosos.
- Los cambios a servicios del usuario se verifican después de aplicarlos y se registran con `registrar_bitacora` y `registrar_changelog`.
- Las pruebas que envíen notificaciones de escritorio reales se avisan antes al usuario, con el texto que se va a mostrar (usar un notificador falso en las pruebas automáticas).
- Los scripts que necesitan `sudo` se dejan en el proyecto para que el usuario los revise y los ejecute; nunca se ejecutan sin su aprobación.
