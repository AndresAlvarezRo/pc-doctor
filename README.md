# pc-doctor

Sistema de diagnóstico de la PC (pensado para Zorin OS / Ubuntu): mide la salud del equipo cada 15 minutos, **aprende qué es normal en esa PC**, avisa cuando algo se sale y permite consultarlo desde Claude Code o desde un dashboard web local. Todo queda en tu equipo.

Tres partes:
1. **Recolector** (`collector.py`): lo corre un systemd user timer cada 15 minutos y al arrancar; tarda ~3 segundos. Guarda sensores, métricas, eventos, snapshots del entorno y hallazgos de seguridad en SQLite.
2. **Servidor MCP** (`server.py`, FastMCP): 23 tools para Claude Code, entre ellas consultas de historial, estado en vivo, alertas, posibles causas y acciones acotadas.
3. **Dashboard** (`web/`): app local en `http://localhost:8787` (solo `127.0.0.1`) con FastAPI y React, que muestra lo mismo que el MCP porque comparten las mismas funciones.

Los datos viven en `~/.local/share/pc-doctor/` (visible desde el proyecto como `datos/`). El registro detallado de cada decisión, error y limitación está en [`BITACORA.md`](BITACORA.md); lo que se observó del equipo, en [`CHANGELOG.md`](CHANGELOG.md).

## Qué hace
- **Alertas de salud** de CPU, GPU, discos (incluido SMART), RAM, ventiladores, voltajes y errores del kernel, con notificaciones de escritorio agrupadas y sin ruido.
- **Valores normales aprendidos:** línea base por componente y por contexto (reposo, carga o juego), anomalías y deriva lenta (polvo, pasta térmica, disco que se llena).
- **Actividad:** detecta cuándo estás jugando (Steam, Proton, Wine, gamescope) y guarda las sesiones: "¿cómo estuvo la temperatura jugando a X?".
- **Posibles causas:** al saltar una alerta, junta lo que pasó cerca (cambios de kernel, driver o paquetes, eventos, otras alertas, sesiones) y lo ordena; nunca afirma una causa.
- **Seguridad:** mineros de criptomonedas, procesos fantasma, posibles keyloggers y puertos raros; consulta online solo el hash de ejecutables ya sospechosos.
- **Reporte semanal** redactado por Claude con tools de solo lectura (con plan B sin modelo si falla).
- **Dashboard** con tarjetas por componente, gráficos con la banda de lo normal, alertas, línea de tiempo, reportes y limitaciones; instalable como app (PWA) y con un botón "Ver en el dashboard" en las notificaciones.
- **Limpieza segura de Descargas:** mueve a cuarentena, nunca borra, y se puede restaurar.

## Estado del proyecto
Todo lo marcado como listo está probado (ver [Desarrollo](#desarrollo)); cómo se llegó a cada decisión está en la bitácora.

| Etapa | Qué incluye | Estado |
|---|---|---|
| Base | Recolector, servidor MCP y limpieza de Descargas con cuarentena; hardware detectado sin depender del fabricante (AMD, Intel, NVIDIA) | Listo (el lector de `nvidia-smi` solo se probó con datos sintéticos) |
| Seguridad | Mineros, procesos fantasma, keyloggers y puertos; reputación online solo de hashes sospechosos; alertas de escritorio | Listo |
| Alertas de salud | Reglas con avisos sostenidos, histéresis y límites del propio hardware; voltajes y SMART habilitados | Listo |
| Valores normales aprendidos | Línea base por contexto, anomalías y deriva, con registro diario permanente | Listo; madura con los días (anomalías ~2 días, deriva ~3 semanas, juego ~50 h de juego) |
| Perfil por actividad | Contexto `juego`, sesiones y migración del historial | Listo |
| Correlación | Posibles causas de una alerta y línea de tiempo | Listo |
| Reporte semanal | `claude -p` con tools de solo lectura, plan B determinístico, timer los domingos a las 20:00 | Listo |
| Dashboard, fases 0 a 3 | API de solo lectura, interfaz, servicio, lanzador y ícono en el escritorio, PWA, enlaces directos, notificaciones con botón (activo) y tool `abrir_dashboard` | Listo |
| Dashboard, fase 4 | Acciones y gestión con token local y verificación de origen (marcar alertas, limpiezas sin root, restaurar, configuración) | **Pendiente** |
| Dashboard, fase 5 | Botón "Diagnosticar con Claude" en cada alerta | **Pendiente** (opcional) |
| Diagnóstico automático | Diagnóstico hecho por Claude disparado por una alerta crítica (tabla `diagnosticos`) | **Pendiente** |
| Calidad | 385 pruebas, hook pre-commit y GitHub Actions | Listo |
| Cobertura de pruebas | El escáner de seguridad, la reputación online y el hilo principal del recolector no tienen pruebas permanentes | **Pendiente** |

**Lo que pc-doctor encontró en esta PC** (detalle en `CHANGELOG.md`): sectores defectuosos y errores CRC en el SSD `sdb`, un ventilador (`fan7`) con velocidad errática y temperaturas de 95-96 °C en CPU y GPU jugando.

## Estructura
| Carpeta o archivo | Qué es |
|---|---|
| `collector.py`, `server.py` | El recolector y el servidor MCP |
| `db.py`, `consultas.py` | Esquema y conexión (con modo de solo lectura); consultas compartidas entre el MCP y el dashboard |
| `salud.py`, `linea_base.py`, `actividad.py`, `correlacion.py` | Sensores y reglas, valores normales aprendidos, juegos y sesiones, posibles causas |
| `seguridad.py`, `reputacion.py` | Escaneo de seguridad y reputación de hashes |
| `alertas.py`, `dashboard.py`, `reporte.py` | Notificaciones (con botón), abrir el dashboard, reporte semanal |
| `web/` | API (`api.py`), frontend React (`frontend/`), datos de prueba, íconos y el script de compilación |
| `systemd/` | Unidades de usuario: recolector, reporte semanal y dashboard |
| `tests/`, `scripts/` | Suite de pruebas; hook pre-commit y su instalador |
| `BITACORA.md`, `CHANGELOG.md` | Decisiones y errores del proyecto; observaciones y cambios del equipo |

## Instalación
Requisitos: `uv`, `python3`, `lm-sensors` y `lshw` (opcionales: `nvidia-smi`, `flatpak`, `snap`).

```bash
cd ~/Desktop/Practicas-IA/pc-doctor
uv sync                                   # crea el entorno (.venv, visible como venv/)

# Recolector, reporte semanal y dashboard (servicios de usuario de systemd)
mkdir -p ~/.config/systemd/user
cp systemd/*.service systemd/*.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now pc-doctor.timer pc-doctor-reporte.timer pc-doctor-web.service

# Servidor MCP en Claude Code
claude mcp add pc-doctor -s user -- uv run --directory ~/Desktop/Practicas-IA/pc-doctor server.py
```

Verificación: `systemctl --user list-timers 'pc-doctor*'`, `systemctl --user status pc-doctor-web` y `claude mcp list`. Corrida manual del recolector: `uv run collector.py`.

Opcional: `bash web/construir.sh` (compila el frontend; necesita Node, ver [Desarrollo](#desarrollo)), el lanzador de `web/pc-doctor.desktop` (copiarlo a `~/.local/share/applications/`, con el ícono `web/frontend/public/icono.svg` en `~/.local/share/icons/hicolor/scalable/apps/pc-doctor.svg`) y `bash scripts/instalar-hooks.sh` si vas a desarrollar.

## Dashboard
- **Abrir:** desde el menú de aplicaciones ("pc-doctor"), el ícono del escritorio, `http://localhost:8787`, `uv run dashboard.py abrir [seccion]` o la tool `abrir_dashboard` desde Claude Code. Si el servicio estaba apagado, se arranca solo.
- **Enlaces directos:** `/alerta/{id}`, `/hallazgo/{id}`, `/componente/{tipo}` y las secciones `#alertas`, `#reportes`, `#linea-de-tiempo`, `#limitaciones` y `#entorno`.
- **Apagar:** `systemctl --user disable --now pc-doctor-web.service`. **Reiniciar tras recompilar:** `systemctl --user restart pc-doctor-web`.
- **Seguridad:** escucha solo en `127.0.0.1`, rechaza cualquier `Host` que no sea `localhost:8787` o `127.0.0.1:8787` (contra DNS rebinding), acepta solo `GET` y abre la base en modo de solo lectura. Hoy no puede modificar nada; las acciones llegan con la fase 4, con token local.
- **Notificaciones con botón:** "Ver en el dashboard" abre la alerta o el hallazgo del aviso. Se activa con `"boton_dashboard": true` en `config.json` (apagado por defecto); si el escritorio no lo soporta, la notificación sale igual, sin botón. Probar: `uv run alertas.py --probar-boton` (envía una notificación real).
- **Instalar como app:** en Chrome o Edge, desde el menú del navegador ("Instalar pc-doctor").

## Tools del MCP
| Tool | Qué hace |
|---|---|
| `perfil_entorno()` | Último snapshot: SO, kernel, hardware, drivers |
| `cambios_entorno(desde)` | Paquetes agregados, quitados o cambiados |
| `espacio_disco()` | Espacio en vivo por partición |
| `procesos_que_mas_consumen(n)` | Top de procesos en vivo |
| `temperatura_cpu()` | Temperatura actual |
| `historial(metrica, desde, contexto)` | Serie o resumen (mín, máx, promedio, tendencia) de una métrica o de **cualquier sensor** (por ejemplo `k10temp/Tctl`) |
| `errores_recientes(horas)` | Errores del journal agrupados |
| `limpiar_descargas_viejas(dias, simular)` | Mueve a cuarentena archivos viejos de Descargas (por defecto solo simula) |
| `restaurar_cuarentena(id)` | Devuelve un archivo a su ruta original |
| `revision_seguridad()` | Escaneo en vivo: mineros, procesos fantasma, posibles keyloggers, puertos y conexiones |
| `hallazgos_seguridad(estado, dias)` | Hallazgos guardados, por severidad |
| `marcar_hallazgo(id, estado)` | Marca un hallazgo como revisado o falso positivo |
| `puertos_en_escucha()` | Puertos accesibles desde la red, en vivo |
| `estado_salud()` | Sensores en vivo contra los valores normales, y lo que no se puede medir |
| `alertas_salud(solo_activas, dias)` | Alertas de salud registradas por el recolector (con su `id`) |
| `linea_base_aprendida(categoria, contexto)` | Lo que pc-doctor aprendió como normal de cada componente (reposo, carga y juego) |
| `medias_diarias(sensor, dias)` | Registro diario permanente (media, mínimo, máximo) de un sensor |
| `sesiones_actividad(tipo, dias)` | Sesiones de juego, con las temperaturas máximas de CPU y GPU de cada una |
| `linea_de_tiempo(desde, hasta)` | Todo lo registrado en orden cronológico: entorno, eventos, alertas, seguridad, sesiones y acciones |
| `correlacionar(alerta_id)` | Posibles causas de una alerta o de un hallazgo (`hallazgo:N`); coincidencias, no causas demostradas |
| `ultimo_reporte()` y `reportes(n)` | El último reporte semanal y el historial |
| `abrir_dashboard(seccion)` | Abre el dashboard en el navegador |

## Alertas de salud
Cada corrida lee los sensores (se guardan 30 días en la tabla `lecturas`) y los compara con unas reglas de valores normales; si algo se sale, envía **una** notificación de escritorio agrupada.

- **Qué vigila:** temperatura de CPU, GPU, NVMe, discos SATA y placa; ventiladores; voltaje de GPU y de la placa; uso sostenido de CPU y GPU; VRAM; RAM y swap; carga; espacio libre, saturación y solo-lectura de discos; SMART (sectores realocados, pendientes e incorregibles, errores CRC, desgaste); y errores del kernel (disco, GPU, memoria agotada, limitación térmica).
- **Sin ruido:** el aviso salta tras varias lecturas seguidas (el crítico, con una sola), no se repite hasta 6 h después (2 h si es crítico) y las resueltas se cierran en silencio. Un conector sin ventilador (siempre 0 RPM) y las entradas de temperatura sin sensor real se ignoran.
- **Ajustar límites:** en `datos/config.json`, por ejemplo `"umbrales": {"temp_cpu": {"aviso": 80, "muestras": 1}}`. `"salud": false` apaga estas alertas.
- **Qué no se puede medir** se ve en `estado_salud()` y en la sección "Limitaciones y sensores" del dashboard. Los voltajes de la placa y el SMART se habilitan con `habilitar-sensores.sh` (ver más abajo).

## Valores normales aprendidos
Además de límites fijos, pc-doctor aprende qué es normal **en tu PC**, por componente y por contexto (reposo, carga o juego):

- `lecturas` guarda 30 días de lecturas; `lecturas_diarias` guarda para siempre la media, el mínimo y el máximo de cada día; `linea_base` guarda lo normal de hoy (mediana, media, p95 y p99).
- **Contexto:** cada lectura se etiqueta según lo que hace el equipo. Una GPU a 80 °C jugando es normal; en reposo, no.
- **Anomalía:** un valor muy fuera de lo habitual dos lecturas seguidas avisa (nunca como crítico). Se activa cuando un sensor tiene unas 200 muestras en ese contexto (~2 días en reposo; en juego, unas 50 horas de juego).
- **Deriva:** si en reposo la temperatura sube 6 °C, un ventilador gira 30 % más o el disco pierde 8 puntos libres frente al mes anterior, avisa (como mucho una vez por semana). Necesita ~3 semanas de datos.
- Consultar: `linea_base_aprendida()` y `medias_diarias('k10temp/Tctl')`, o el gráfico de cada sensor en el dashboard (con la banda de lo normal detrás).

## Actividad y posibles causas
- **Juegos:** se detectan por la línea de comandos de los procesos (el cliente de Steam abierto no cuenta; sí un juego en ejecución, bajo Proton, Wine o nativo). Las firmas están en un solo lugar (`FIRMAS` en `actividad.py`). Las sesiones se consultan con `sesiones_actividad()`.
- **Posibles causas:** `correlacionar(id)` (o el botón "Ver posibles causas" del dashboard) lista lo que ocurrió cerca de una alerta, por cercanía y afinidad. Las notificaciones agregan una línea "posible relación" solo si hay un cambio de entorno claramente afín en las últimas 24 h.

## Reporte semanal
Los domingos a las 20:00 (`pc-doctor-reporte.timer`, y al encender la PC si estaba apagada) se genera `datos/reportes/AAAA-MM-DD.md`: estado general, tendencias contra la línea base, anomalías, cambios de entorno, seguridad, SMART, sesiones de juego y recomendaciones.

- Lo redacta `claude -p` con **solo** tools de lectura de pc-doctor; sin herramientas integradas, sin web ni los demás MCP de la cuenta. El archivo lo escribe `reporte.py`, no el modelo, y todo dato del equipo se declara no confiable en el prompt.
- Si Claude falla (sin sesión, sin red, límite de uso, tiempo agotado), sale un reporte determinístico con los mismos datos, y el encabezado lo dice. El reporte nunca queda sin generarse.
- Consultar: `ultimo_reporte()`, `reportes(n)` o la sección "Reportes y diagnósticos" del dashboard. Apagar: `"reporte": false` en `config.json` o `systemctl --user disable --now pc-doctor-reporte.timer`.

## Configuración
`datos/config.json` (se crea solo; las claves que falten usan su valor por defecto):

| Clave | Para qué |
|---|---|
| `notificaciones` | Apaga todas las notificaciones de escritorio con `false` |
| `salud` | Apaga las alertas de salud con `false` |
| `umbrales` | Cambia límites de las reglas, por ejemplo `{"temp_cpu": {"aviso": 80, "muestras": 1}}` |
| `consulta_online` | Permite consultar la reputación de hashes sospechosos |
| `malwarebazaar_key` | Clave de abuse.ch (vacía: ese proveedor queda apagado) |
| `boton_dashboard` | Botón "Ver en el dashboard" en las notificaciones (apagado por defecto) |
| `reporte` | `false` o un objeto con `habilitado`, `modelo`, `max_turns`, `timeout_s` y `claude` (ruta) |
| `correlacion` | `horas_antes` y `horas_despues` de la ventana de posibles causas (48 y 2 por defecto) |

## Seguridad
Cada corrida del recolector (~0,4 s extra) revisa procesos y red y guarda los resultados en `hallazgos_seguridad` y `escuchas`.
Contrasta con listas públicas (Feodo Tracker y NoCoin) que se descargan como máximo una vez al día; **nunca se envía información de la PC**.

- **Detecta:** mineros de criptomonedas, procesos fantasma (ejecutan desde `/tmp`, binario borrado, imitan hilos del kernel), lectores de `/dev/input`, puertos accesibles desde la red, terminales web sin contraseña y conexiones a IPs de botnets.
- **No detecta:** rootkits ni lo que hacen procesos de otros usuarios (corre sin root). No es un antivirus: un resultado limpio no garantiza un equipo limpio.
- **Reputación online:** los hashes se calculan y guardan en tu PC. Solo el **hash** de un ejecutable ya marcado como sospechoso se consulta online (Team Cymru por DNS y CIRCL por HTTPS, sin clave); nunca se envía el archivo. Si alguno figura como malware, queda en `alertas` y el hallazgo sube a severidad alta. Se desactiva con `"consulta_online": false` en `~/.local/share/pc-doctor/config.json` (visible en `datos/config.json`). Opcional: una clave gratuita de abuse.ch en `malwarebazaar_key` agrega MalwareBazaar.
- **Alertas de escritorio:** si aparece un hallazgo grave (severidad alta, por ejemplo malware según la reputación online), el recolector envía una notificación, una sola vez por hallazgo y agrupada. Se desactivan con `"notificaciones": false` en `config.json`. Probar con `uv run alertas.py --probar`.
- **Falsos positivos:** marcalos con `marcar_hallazgo(id, "falso_positivo")` y dejan de mostrarse como nuevos.

## Habilitar voltajes y SMART
Requiere `sudo`. Revisá `habilitar-sensores.sh` y ejecutá `sudo bash habilitar-sensores.sh`. Instala `smartmontools`, activa `drivetemp`, prueba `nct6775` (voltajes de placa, puede no ser compatible) y permite leer el SMART sin contraseña **solo** con `smartctl -j -H -A` sobre tus discos. Para deshacerlo: `sudo rm /etc/sudoers.d/pc-doctor /etc/modules-load.d/pc-doctor.conf`.

## Desactivar
```bash
systemctl --user disable --now pc-doctor.timer pc-doctor-reporte.timer pc-doctor-web.service   # detiene y deshabilita
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

## Limitaciones conocidas
- El escaneo de seguridad corre sin root: no ve rootkits ni lo que hacen procesos de otros usuarios. No es un antivirus.
- Las lecturas son cada 15 minutos: un pico o un juego abierto y cerrado entre dos corridas no se ven.
- La línea base no distingue la hora del día ni la estación del año; la deriva compara contra un mes.
- Los voltajes de la placa se aprenden pero no tienen un valor nominal de referencia: el kernel no entrega el nombre de cada riel.
- La detección de juegos se basa en la línea de comandos de los procesos: un programa de Windows bajo Wine que no sea un juego puede contar como juego.
- El reporte semanal puede quedar sin redactar (plan B) si Claude no está disponible; texto malicioso en los datos del equipo puede terminar en el archivo del reporte (el modelo no puede ejecutar nada ni salir de pc-doctor).

## Desarrollo
### Pruebas
```bash
uv sync                          # instala también las dependencias de desarrollo (pytest, pytest-cov)
uv run pytest                    # todo (385 pruebas, ~26 s)
uv run pytest -m "not lento"     # lo rápido (~9 s): es lo que corre el hook en cada commit
uv run pytest -m "not local"     # lo que corre GitHub Actions
uv run pytest --cov              # con cobertura
```
- Marcadores: `lento` (levanta procesos, espera o genera datos grandes) y `local` (lee sensores o procesos reales de esta PC; en CI se saltea).
- Ninguna prueba toca la base real, la configuración, `~/.steam`, `claude` ni servicios reales: `tests/conftest.py` usa carpetas temporales y reemplazos de `notify-send`, `systemd-run`, `systemctl`, `gdbus`, `xdg-open` y `claude` (en `tests/falsos/`). Una prueba nueva sigue las mismas reglas. Al corregir un error, se agrega la prueba que lo habría detectado.

### Hook pre-commit
```bash
bash scripts/instalar-hooks.sh   # una vez por clon; se puede repetir
```
Bloquea el commit si se agrega una base `.db`, `config.json`, `web_token` o algo bajo `datos/`; si una línea agregada parece un secreto (tokens de GitHub, claves de API, `password=` con un valor, claves privadas); si un archivo pesa más de 1 MiB; o si fallan las pruebas rápidas. Dice qué archivo y por qué (los secretos se muestran enmascarados). Un ejemplo falso a propósito se marca con `permitir-secreto` en un comentario de esa línea. Salida de emergencia: `git commit --no-verify`.

### Flujo de commits
1. Se termina un cambio coherente (no un archivo suelto) y se corre `uv run pytest`.
2. Si pasan, se hace el commit: mensaje en español, en imperativo, con una primera línea corta y, si hace falta, un párrafo con el porqué. Prefijos: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`. El commit incluye la entrada de `BITACORA.md`, si la hay.
3. Antes del push se revisa `git log --oneline origin/main..HEAD` y después se hace `git push`.
4. Si las pruebas fallan, no hay commit. Nunca `git push --force`, `git reset --hard` ni reescribir historial sin preguntar.

### Integración continua
`.github/workflows/pruebas.yml` corre en cada push y pull request a `main`: `uv sync --frozen` y `uv run pytest -m "not local"`, y la compilación del frontend (`npm ci` y `npm run build`). Las actions están fijadas por SHA de commit y el workflow tiene permisos mínimos (`contents: read`). Para ver el resultado: `gh run watch` o la pestaña Actions del repositorio.

### Frontend
`bash web/construir.sh` compila `web/frontend/` a `web/frontend/dist/` (lo sirve el dashboard) con el Node aislado de `~/.local/share/pc-doctor/node`. Para desarrollar con recarga en vivo: `web/frontend/` → `npm run dev` y, en otra terminal, la API con datos de prueba (`uv run python web/datos_de_prueba.py CARPETA` y `PC_DOCTOR_DATOS=CARPETA uv run uvicorn web.api:app --host 127.0.0.1 --port 8787`).
