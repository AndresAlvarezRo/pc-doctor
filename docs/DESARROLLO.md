# Desarrollo

## Pruebas
```bash
uv sync                          # instala también las dependencias de desarrollo (pytest, pytest-cov)
uv run pytest                    # todo (más de 1100 pruebas, ~1 min)
uv run pytest -m "not lento"     # lo rápido (~9 s): es lo que corre el hook en cada commit
uv run pytest -m "not local"     # lo que corre GitHub Actions
uv run pytest --cov              # con cobertura
```
- Marcadores: `lento` (levanta procesos, espera o genera datos grandes) y `local` (lee sensores o procesos reales del equipo donde corre; en CI se saltea).
- Ninguna prueba toca la base real, la configuración, `~/.steam`, `claude` ni servicios reales: `tests/conftest.py` usa carpetas temporales y reemplazos de `notify-send`, `systemd-run`, `systemctl`, `gdbus`, `xdg-open` y `claude` (en `tests/falsos/`). Una prueba nueva sigue las mismas reglas. Al corregir un error, se agrega la prueba que lo habría detectado.

## Hook pre-commit
```bash
bash scripts/instalar-hooks.sh   # una vez por clon; se puede repetir
```
Antes de revisar, regenera `BITACORA.md` y `CHANGELOG.md` desde la base y los agrega al commit (`PC_DOCTOR_HOOK_SIN_EXPORTAR=1` lo saltea). Bloquea el commit si se agrega una base `.db`, `config.json`, `web_token` o algo bajo `datos/`; si una línea agregada parece un secreto (tokens de GitHub, claves de API, `password=` con un valor, claves privadas); si un archivo pesa más de 1 MiB; o si fallan las pruebas rápidas. Dice qué archivo y por qué (los secretos se muestran enmascarados). Un ejemplo falso a propósito se marca con `permitir-secreto` en un comentario de esa línea. Salida de emergencia: `git commit --no-verify`.

## Flujo de commits
1. Se termina un cambio coherente (no un archivo suelto) y se corre `uv run pytest`.
2. Si pasan, se hace el commit: mensaje en español, en imperativo, con una primera línea corta y, si hace falta, un párrafo con el porqué. Prefijos: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`. `BITACORA.md` y `CHANGELOG.md` los regenera el hook desde la base (las decisiones se registran con `registrar_bitacora`).
3. Antes del push se revisa `git log --oneline origin/main..HEAD` y después se hace `git push`.
4. Si las pruebas fallan, no hay commit. Nunca `git push --force`, `git reset --hard` ni reescribir historial sin preguntar.

## Integración continua
`.github/workflows/pruebas.yml` corre en cada push y pull request a `main`: `uv sync --frozen` y `uv run pytest -m "not local"`, y la compilación del frontend (`npm ci` y `npm run build`). Las actions están fijadas por SHA de commit y el workflow tiene permisos mínimos (`contents: read`). Para ver el resultado: `gh run watch` o la pestaña Actions del repositorio.

## Frontend
`bash web/construir.sh` compila `web/frontend/` a `web/frontend/dist/` (lo sirve el dashboard) con el Node aislado de `~/.local/share/pc-doctor/node`. Para desarrollar con recarga en vivo: `web/frontend/` → `npm run dev` y, en otra terminal, la API con datos de prueba (`uv run python web/datos_de_prueba.py CARPETA` y `PC_DOCTOR_DATOS=CARPETA uv run uvicorn web.api:app --host 127.0.0.1 --port 8787`).
