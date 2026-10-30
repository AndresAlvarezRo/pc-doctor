# Arquitectura

Cómo está hecho pc-doctor por dentro. Para instalarlo y operarlo: [OPERACION.md](OPERACION.md). Para la remediación asistida: [REMEDIACION.md](REMEDIACION.md).

Sistema de diagnóstico de la PC (pensado para Zorin OS / Ubuntu): mide la salud del equipo cada 15 minutos, **aprende qué es normal en esa PC**, avisa cuando algo se sale y permite consultarlo desde Claude Code o desde un dashboard web local. Todo queda en tu equipo.

Tres partes:
1. **Recolector** (`collector.py`): lo corre un systemd user timer cada 15 minutos y al arrancar; tarda ~3 segundos. Guarda sensores, métricas, eventos, snapshots del entorno y hallazgos de seguridad en SQLite.
2. **Servidor MCP** (`server.py`, FastMCP): 46 tools para Claude Code, entre ellas consultas de historial, estado en vivo, alertas, posibles causas y acciones acotadas.
3. **Dashboard** (`web/`): app local en `http://localhost:8787` (solo `127.0.0.1`) con FastAPI y React, que muestra lo mismo que el MCP porque comparten las mismas funciones.

Los datos viven en `~/.local/share/pc-doctor/` (visible desde el proyecto como `datos/`). El registro detallado de cada decisión, error y limitación está en [`BITACORA.md`](../BITACORA.md); lo que se observó del equipo, en [`CHANGELOG.md`](../CHANGELOG.md).

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
Todo lo marcado como listo está probado (ver [Desarrollo](DESARROLLO.md)); cómo se llegó a cada decisión está en la bitácora.

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
| Dashboard, fase 4 | Acciones con token local y verificación de origen. Hoy: aprobar, rechazar y deshacer planes de remediación. Faltan marcar alertas, limpiezas, restaurar y la pantalla de configuración | **Parcial** |
| Dashboard, fase 5 | Botón "Diagnosticar con Claude" en cada alerta | **Pendiente** (opcional) |
| Remediación asistida | Una alerta grave dispara un diagnóstico (Claude aislado, o solo correlación sin modelo), un plan de acciones de un catálogo cerrado, aprobación tuya, verificación y recetas aprendidas. Ver [REMEDIACION.md](REMEDIACION.md) | Listo en pruebas con `claude` falso; **falta probarlo con una alerta real** y la sección del dashboard en un navegador |
| Calidad | más de 1100 pruebas, hook pre-commit y GitHub Actions | Listo |
| Windows | Capa de plataforma, instalador y paquete v1.0 (ver [guía](../instalador/INSTALAR-WINDOWS.md)). La seguridad y el reporte no están portados, y nada se verificó todavía en una PC con Windows | **Pendiente de verificar** |
| Cobertura de pruebas | El escáner de seguridad, la reputación online y el hilo principal del recolector no tienen pruebas permanentes | **Pendiente** |

## Estructura
| Carpeta o archivo | Qué es |
|---|---|
| `collector.py`, `server.py` | El recolector y el servidor MCP |
| `db.py`, `consultas.py` | Esquema y conexión (con modo de solo lectura); consultas compartidas entre el MCP y el dashboard |
| `salud.py`, `linea_base.py`, `actividad.py`, `correlacion.py` | Sensores y reglas, valores normales aprendidos, juegos y sesiones, posibles causas |
| `seguridad.py`, `reputacion.py` | Escaneo de seguridad y reputación de hashes |
| `alertas.py`, `dashboard.py`, `reporte.py` | Notificaciones (con botón), abrir el dashboard, reporte semanal |
| `remediacion.py`, `diagnostico.py`, `planes.py`, `recetas.py`, `agente.py` | Catálogo cerrado de acciones y su ejecutor; diagnóstico y plan; aprobar, aplicar, verificar y escalar; recetas; el `claude -p` aislado que comparten el reporte y el diagnóstico |
| `web/` | API (`api.py`), frontend React (`frontend/`), datos de prueba, íconos y el script de compilación |
| `systemd/` | Unidades de usuario: recolector, reporte semanal y dashboard |
| `tests/`, `scripts/` | Suite de pruebas; hook pre-commit y su instalador |
| `memoria.py`, `migrar_memoria.py`, `modulos.py` | Memoria en tablas de `doctor.db` (esquema, búsqueda, bitácora en ítems, exportación e importación de markdown), su migración desde los archivos y el mapa de archivos a módulos |
| [`BITACORA.md`](../BITACORA.md), [`CHANGELOG.md`](../CHANGELOG.md) | **Generados** desde las tablas `bitacora` y `changelog`: decisiones y errores del proyecto; observaciones y cambios del equipo. Son un respaldo completo: llevan los metadatos en comentarios HTML y `memoria.py --importar` reconstruye las tablas |

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
| `diagnosticos(dias)`, `planes(estado)`, `detalle_plan(id)`, `recetas(firma)` | Lo diagnosticado y su plan (las dos primeras, sin el texto del modelo), un plan completo (texto no confiable) y lo aprendido |
| `aprobar_plan(id)`, `rechazar_plan(id)` | Aplican o descartan un plan. **Solo si el usuario lo pide en la conversación**; nunca los usa el `claude -p` |
| `recordar(tema, texto, tipo)`, `buscar_memoria(consulta, n)`, `memoria_reciente(n)`, `olvidar(id)` | Memoria del agente (hechos, decisiones, preferencias, observaciones) con búsqueda de texto completo; `olvidar` marca como inactivo, no borra |
| `hechos_conocidos(aplica_a)`, `agregar_hecho_conocido(...)`, `retirar_hecho_conocido(id)` | Lo que el usuario declaró como sabido. **Solo se agregan o retiran si el usuario lo pide en la conversación** |
| `registrar_bitacora(...)`, `buscar_bitacora(consulta, n)` | Registra un ítem de la bitácora (tipo, módulos, resumen de una línea) y busca sobre los ítems (devuelve resúmenes) |
| `contexto(archivo, modulo, tipo, incluir_superadas, n)`, `detalle_bitacora(id)`, `pendientes(modulo)`, `marcar_superada(id, reemplazada_por, motivo)` | La bitácora por tarea: resúmenes de lo vigente (las invariantes siempre), el texto completo de un ítem, los pendientes y el reemplazo de una decisión vieja. Ninguna entra al reporte semanal |
| `registrar_changelog(...)`, `resolver_changelog(id, detalle)`, `changelog_abierto()` | Historia de la PC: errores, soluciones y cambios, con su estado |
| `registrar_identidad(campo, valor)` | Filas de "Identidad actual" que no se calculan solas (energía, red expuesta, sensores extra, Node.js); se exportan al changelog |

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

## Seguridad
Cada corrida del recolector (~0,4 s extra) revisa procesos y red y guarda los resultados en `hallazgos_seguridad` y `escuchas`.
Contrasta con listas públicas (Feodo Tracker y NoCoin) que se descargan como máximo una vez al día; **nunca se envía información de la PC**.

- **Detecta:** mineros de criptomonedas, procesos fantasma (ejecutan desde `/tmp`, binario borrado, imitan hilos del kernel), lectores de `/dev/input`, puertos accesibles desde la red, terminales web sin contraseña y conexiones a IPs de botnets.
- **No detecta:** rootkits ni lo que hacen procesos de otros usuarios (corre sin root). No es un antivirus: un resultado limpio no garantiza un equipo limpio.
- **Reputación online:** los hashes se calculan y guardan en tu PC. Solo el **hash** de un ejecutable ya marcado como sospechoso se consulta online (Team Cymru por DNS y CIRCL por HTTPS, sin clave); nunca se envía el archivo. Si alguno figura como malware, queda en `alertas` y el hallazgo sube a severidad alta. Se desactiva con `"consulta_online": false` en `~/.local/share/pc-doctor/config.json` (visible en `datos/config.json`). Opcional: una clave gratuita de abuse.ch en `malwarebazaar_key` agrega MalwareBazaar.
- **Alertas de escritorio:** si aparece un hallazgo grave (severidad alta, por ejemplo malware según la reputación online), el recolector envía una notificación, una sola vez por hallazgo y agrupada. Se desactivan con `"notificaciones": false` en `config.json`. Probar con `uv run alertas.py --probar`.
- **Falsos positivos:** marcalos con `marcar_hallazgo(id, "falso_positivo")` y dejan de mostrarse como nuevos.

## Memoria
La memoria vive en cuatro tablas de `doctor.db` y se consulta por el MCP, en vez de cargarse entera en cada sesión desde archivos:

| Tabla | Qué guarda |
|---|---|
| `memoria` | Lo que el agente aprende (hecho, decisión, preferencia u observación), con `origen` (agente o usuario) y búsqueda de texto completo (FTS5, sin distinguir acentos). Personal: no se exporta |
| `hechos_conocidos` | Lo que **el usuario** declara como sabido, con a qué se aplica (`aplica_a`: sensor, disco, alerta) y una fecha de revisión opcional. Personal: no se exporta |
| `bitacora` | Agrupación de la bitácora del proyecto: sección, título, fecha y tipo |
| `bitacora_items` (+ `bitacora_item_modulo`, `bitacora_item_archivo`) | Cada decisión, error, limitación, prueba, pendiente, nota o invariante: tipo, vigencia (vigente, superada, histórica), reemplazo y motivo, resumen de una línea, texto original, prueba que lo protege, módulos y archivos. Índice de texto completo sobre resumen y contenido |
| `changelog` | Errores, soluciones y cambios de la PC, con estado (abierto o resuelto) |
| `identidad_manual` | Las filas de "Identidad actual" que no se pueden recalcular (energía, red expuesta, sensores extra, Node.js). Es identidad de la PC, no datos personales: **sí se exporta** |

**Un hecho conocido silencia lo conocido, no lo nuevo.** Una alerta cubierta por un hecho no se vuelve a notificar ni a recomendar en el reporte semanal mientras no empeore (sube la severidad, o el valor se aleja de lo normal: cualquier aumento en los contadores de SMART, más del 5 % en el resto). Si el hecho vence, deja de silenciar y aparece en el reporte como "para revisar". El dashboard muestra el hecho junto a cada alerta cubierta y tiene las secciones "Hechos conocidos" y "Changelog" (solo lectura).

**Exportar:** `BITACORA.md` y `CHANGELOG.md` se generan desde las tablas con `uv run memoria.py --exportar` (con `--destino CARPETA` para ver el resultado sin pisar los archivos). No se editan a mano: el hook pre-commit los regenera y los agrega al commit. La "Identidad actual" del changelog se calcula del último snapshot de entorno y su hardware, más las filas de `identidad_manual`. Las tablas se crean al escribir por primera vez; las lecturas nunca las crean.

**Módulos:** `modulos.py` mapea cada archivo del repo a un módulo (salud, seguridad, actividad, correlacion, reporte, alertas, dashboard, memoria, datos, mcp, infra, git; `sistema` es lo que está fuera del repo). Una prueba falla si un archivo de código no cae en ninguno. `contexto(archivo=...)` usa ese mapa.

**Respaldo completo:** cada entrada, cada ítem, cada entrada del changelog y cada fila de identidad manual llevan un comentario HTML de una línea con sus metadatos (JSON; GitHub no lo muestra). Las marcas `**(invariante)**` y `(superada por #N: motivo)` son visibles. `uv run memoria.py --importar [--origen CARPETA]` reconstruye `bitacora`, `bitacora_items` y sus relaciones desde `BITACORA.md` y `changelog` e `identidad_manual` desde `CHANGELOG.md`, con los mismos ids de ítems; se niega si esas tablas ya tienen datos, salvo `--reemplazar` (hace antes una copia `doctor.db.antes-de-importar-*`). Exportar, importar y volver a exportar da archivos idénticos byte a byte; la excepción es la parte calculada de la "Identidad actual", que sale del último snapshot y no está en el markdown. `memoria` y `hechos_conocidos` no se exportan.

**Migrar** (una sola vez, solo si venís de los archivos de memoria anteriores): `uv run migrar_memoria.py` simula y `--ejecutar` escribe; exige una copia previa de la base (`doctor.db.antes-de-memoria-*`) y que las tablas estén vacías. La división de la bitácora en ítems se hizo con `uv run migrar_memoria.py --items PROPUESTA.json [--ejecutar]` (copia `doctor.db.antes-de-items-*`; valida que los ítems de cada entrada, unidos, den exactamente su texto).
