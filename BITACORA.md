# Bitácora de pc-doctor

Registro cronológico de las decisiones del proyecto. Cada decisión nueva se agrega al final de su fecha.

## 2026-10-28

### Prerequisitos
- Estaban `uv` 0.13.6, `python3` 3.12.3, `sensors`, `lshw`, `journalctl`, `flatpak`, `snap` y `claude`. Faltaba `nvidia-smi`, que es opcional. No hizo falta instalar nada con `sudo`.
- Carpeta de descargas real: `~/Downloads` (no existe `~/Descargas`).

### Estructura y datos
- **Base de datos fuera del repo:** `~/.local/share/pc-doctor/doctor.db`, como se pidió. Así el repo queda limpio y los datos no se versionan por error.
- **Timestamps como epoch UTC (INTEGER):** se comparan y ordenan fácil, y los índices por `ts` rinden. La conversión a hora local se hace solo al mostrar.
- **`metricas_diarias` con clave (workspace_id, dia):** se llena solo al aplicar la retención (resumir y luego borrar lo de más de 30 días). `historial` mezcla esos promedios diarios con las métricas crudas cuando el rango los incluye.
- **Snapshot de entorno solo si cambia el hash** de kernel + driver GPU + lista de paquetes (apt, flatpak, snap). Evita llenar la base con copias idénticas de ~2500 paquetes cada 15 minutos.

### Recolector
- **Cada paso está aislado:** si falla uno (por ejemplo `journalctl`), se loguea y siguen los demás. Los comandos externos pasan por `db.ejecutar()`, que devuelve `None` si el comando no existe, falla o excede el timeout.
- **Eventos del journal:** `journalctl -p err --since @<último ts> -n 50`. La primera corrida mira solo la última hora.

### Servidor MCP
- **`mcp` fijado a `<2`:** `uv` resolvía mcp 2.x, donde `FastMCP` pasó a llamarse `MCPServer` y `mcp.server.fastmcp` ya no existe. Se pineó 1.x para usar FastMCP como se pidió.
- **Respuestas compactas:** las listas se recortan a 20 elementos y `historial` pasa a resumen (mín, máx, promedio, tendencia) con más de 60 puntos.
- **Seguridad de la cuarentena:**
  - Solo se mueven archivos regulares dentro de la carpeta de descargas.
  - Se ignoran los symlinks y se comprueba que la ruta real siga dentro de esa carpeta.
  - Nunca se borra nada.
  - Restaurar no pisa un archivo que ya exista en la ruta original.

### Hardware agnóstico a fabricante (pedido del usuario)
- **GPU:** se detecta con `lspci -nnk` y el proveedor sale del ID PCI (NVIDIA 10de, AMD 1002/1022, Intel 8086, más virtuales y ARM), no del texto de la descripción. Un ID desconocido se informa como `desconocido (xxxx)`.
- **Versión del driver, por fabricante:**
  - NVIDIA: `nvidia-smi` si existe; si no, el módulo.
  - AMD e Intel: versión del módulo si la expone. Si es in-tree se informa `kernel X (in-tree)`.
  - Mesa: se agrega la versión de `libgl1-mesa-dri` para drivers que no son `nvidia`.
- **CPU:** se usa `vendor_id` de `/proc/cpuinfo` y, si falta (ARM), `lscpu`. Se guarda también la arquitectura.
- Probado en esta máquina: Ryzen 5 5600X + AMD Navi 33 (`amdgpu`, in-tree), 3 discos y placa ASUS PRIME B550-PLUS.

### Visibilidad total en el explorador de archivos (pedido del usuario)
- Lo único oculto era `.venv`. Se agregó el symlink visible `venv -> .venv`. No se renombró, para que el comando de registro del MCP y `uv` sigan funcionando sin variables de entorno extra.
- Se agregó el symlink `datos -> ~/.local/share/pc-doctor` para ver la base y la cuarentena desde el proyecto. Los datos siguen físicamente fuera del repo.
- Convención: no crear archivos ni carpetas con punto dentro del proyecto.

### systemd (archivos creados, **todavía sin instalar**)
- `systemd/pc-doctor.service`: `Type=oneshot`, ejecuta `uv run --directory %h/Desktop/Practicas-IA/pc-doctor collector.py`. Se usa la ruta absoluta de `uv` porque systemd --user no hereda el PATH del shell. Se agregaron `Nice=10` (que no moleste al trabajar) y `TimeoutStartSec=120`.
- `systemd/pc-doctor.timer`: `OnBootSec=2min`, `OnUnitActiveSec=15min`, `Persistent=true`.
- Nota: `Persistent=true` solo tiene efecto con `OnCalendar=`. Con los disparadores actuales es inofensivo y se dejó porque se pidió.
- Los archivos viven en el proyecto. La instalación a `~/.config/systemd/user/` espera la aprobación del usuario.

### Instalación y activación (Paso 6, aprobada por el usuario)
- Se copiaron las unidades a `~/.config/systemd/user/` y se ejecutó `enable --now pc-doctor.timer`.
- Al activarse, el timer disparó una corrida inmediata (12:56). La siguiente quedó a +15 min. La corrida manual de verificación fue la segunda.

### Registro del MCP (Paso 7)
- `claude mcp add pc-doctor -s user -- uv run --directory ~/Desktop/Practicas-IA/pc-doctor server.py`. `claude mcp list` lo muestra como ✔ Connected.

### Verificación (Paso 8)
- Corrida manual del recolector: 1,9 s. Filas resultantes: workspace 1, snapshot_entorno 1, hardware 7, software 2448, metricas 2, top_procesos 10, eventos 0, acciones 0, cuarentena 0, metricas_diarias 0.
- La segunda corrida no creó snapshot porque el hash no cambió: la lógica de deduplicación funciona.
- Eventos = 0 se contrastó con `journalctl -p err --since -24h`, que también da 0 líneas. No es un bug.
- Detectado: la máquina es **Zorin OS 18.1** (kernel 7.0), no 17 como se supuso. No afecta al código, que lee `/etc/os-release`.
- Detectado: `Tctl` de la CPU marcó ~85 °C justo después de correr el recolector (la GPU estaba a 55 °C). Probablemente fue un pico por la carga de `uv`. Queda para vigilar con `historial("temp_cpu", ...)` cuando haya más datos.

### Ajuste a `limpiar_descargas_viejas` tras la primera simulación
- Problema: la simulación listó 20.768 archivos, casi todos de una carpeta descomprimida de drivers, con rutas larguísimas.
- Decisión 1: la salida se agrupa **por elemento de primer nivel** (archivos y MB por carpeta o archivo suelto). Se mantiene el movimiento archivo por archivo y el registro individual en `cuarentena` y `acciones`, como pidió el usuario.
- Decisión 2: la edad del archivo es `max(mtime, ctime)`. Un archivo recién descomprimido o copiado conserva un `mtime` viejo, pero su `ctime` es reciente. Así no se marca como "viejo" algo que llegó hace poco. La regla solo puede excluir más archivos, nunca menos, por lo que es más conservadora.
- En esta máquina el resultado no cambió: 20.768 archivos (424 MB) son viejos también por `ctime`.
- Advertencia: una ejecución real sobre este resultado movería esos archivos uno por uno y generaría ~20.000 filas en `cuarentena` y en `acciones`. Antes de ejecutar conviene revisar la simulación.

### Documentación
- Se escribió `README.md`: qué es, instalación, cómo desactivar el timer y cómo restaurar la cuarentena.

### Regla de changelog de la PC (pedido del usuario)
- Pedido: que cada vez que se revise algo del funcionamiento de la PC (errores, soluciones, cambios) se registre en un changelog dentro de pc-doctor, para mantener el contexto del equipo y su identidad siempre actualizados.
- Se creó `CHANGELOG.md` con dos partes: la tabla **Identidad actual**, que se reescribe cuando algo cambia (SO, kernel, GPU/driver, RAM, discos, paquetes), y **Entradas**, cronológicas (de la más nueva a la más vieja) con tipo, detalle y estado (abierto o resuelto). Se sembró con los datos reales de esta máquina y la observación de la temperatura de CPU.
- Se agregó la regla como instrucción en dos lugares:
  - `~/.claude/CLAUDE.md` (nivel usuario, archivo nuevo): como el MCP se usa desde cualquier carpeta, la regla debe cargarse en cualquier sesión de Claude Code y no solo dentro de pc-doctor.
  - `CLAUDE.md` del proyecto: para que quede documentada junto al código.
- Interpretación: "rule en el modelo local" se entendió como una instrucción persistente de Claude Code (CLAUDE.md). La regla usa la ruta absoluta del changelog.
- Diferencia con la bitácora: `BITACORA.md` registra decisiones de diseño del proyecto; `CHANGELOG.md` registra el estado y la historia de la PC.

### Perfil de energía en lugar de `schedutil` (pedido del usuario)
- Pedido: pasar el governor a `schedutil`. Verificado: con `amd-pstate-epp` el kernel solo ofrece `performance` y `powersave`, así que `schedutil` no es posible en este equipo.
- Decisión: aplicar el equivalente de la intención (dejar de forzar frecuencias máximas) con `powerprofilesctl set balanced`. El governor lo fijaba el perfil de energía del sistema. No requiere `sudo`, persiste entre reinicios y se revierte con `powerprofilesctl set performance`. Resultado: governor `powersave` + EPP `balance_performance`.

### Módulo de seguridad: mineros, keyloggers, fantasmas y red (pedido del usuario)
- Pedido: saber si hay procesos de minería de criptomonedas, keyloggers, procesos fantasma o escuchas raras; guardarlo en tablas e incluirlo en el chequeo de cada 15 minutos junto con alguna base de datos online.
- **Nuevo `seguridad.py`**, usado por el recolector y por el servidor MCP. Se agregaron tres tablas al esquema: `hallazgos_seguridad`, `escuchas` y `listas_seguridad`.
- **Detecciones:**
  - Mineros: nombres conocidos (xmrig, minerd, kinsing, etc.), argumentos típicos (`stratum+tcp://`, `--donate-level`, randomx), dominios de pools en la línea de comandos y conexiones a puertos de pool.
  - Fantasmas: ejecutables en `/tmp` o `/dev/shm`, binarios borrados que siguen vivos, procesos que imitan hilos del kernel, nombres ocultos y `LD_PRELOAD` hacia rutas temporales.
  - Keyloggers: nombres conocidos y procesos que tienen abierto `/dev/input/event*` fuera de una lista de lectores legítimos.
  - Red: puertos TCP accesibles desde la red, terminales web sin autenticación y conexiones a IPs de botnets.
- **Listas online usadas:** Feodo Tracker (IPs de C2, `abuse.ch`) y NoCoin (312 dominios de minado, GitHub). Descubierto al probar: las listas de CoinBlocker en GitLab piden login, algunas URLs de GitHub y de URLhaus devuelven 404/410, y ThreatFox/MalwareBazaar exigen clave de API. Por eso las firmas de pools y mineros también viven en el código.
- **Privacidad:** las listas solo se descargan (máximo 1 vez cada 24 h, timeout de 10 s, tope de 5 MB, con copia previa si falla). No se envía nada de esta máquina a ningún servicio; no se consultan hashes de ejecutables online por ese motivo.
- **Deduplicación:** cada hallazgo tiene una huella (categoría, regla, nombre y ruta o puerto, sin el pid) y se guarda una sola fila con `veces` y `ultima_vez`. Así el timer no genera ~96 filas por día por el mismo hallazgo. El estado `falso_positivo` o `revisado` se conserva si reaparece.
- **Corre sin root:** no ve los descriptores de archivo de procesos de otros usuarios (45 de 450 en esta máquina) ni detecta rootkits. Queda documentado en las respuestas de las tools y en el README.
- **Validación:** se simularon un `sleep` renombrado como `xmrig` en `/tmp`, otro con argumentos `stratum+tcp://pool.minexmr.com` y se detectaron los tres casos. Los procesos y archivos de prueba se eliminaron y no se guardaron en la base.
- **Ajustes tras el primer escaneo real:** falso positivo del overlay de Steam (`LD_PRELOAD` desde `/tmp`) excluido. Se agregó la regla `shell_web_sin_auth` al descubrir que `ttyd` expone un `bash` sin credenciales en `0.0.0.0:7681`.
- **Nuevas tools MCP (13 en total):** `revision_seguridad()`, `hallazgos_seguridad(estado, dias)`, `marcar_hallazgo(id, estado)` y `puertos_en_escucha()`.
- Costo en el recolector: la corrida completa pasó de 1,9 s a ~2,0 s.
- No se tocó ningún servicio: la exposición de `ttyd` y `fluidsynth` se informa en `CHANGELOG.md` y la decisión es del usuario.

### ttyd y fluidsynth fuera de la LAN (pedido del usuario)
- Pedido: dejar `ttyd` y `fluidsynth` solo en localhost.
- **ttyd:** servicio de usuario `centro-hogar-ttyd.service`; se cambió `-i 0.0.0.0` por `-i 127.0.0.1` (se respaldó el original fuera del proyecto). Antes de reiniciar se comprobó que no hubiera conexiones activas a los puertos. Consecuencia: el portal ya no es accesible desde otros equipos.
- **fluidsynth:** su unit viene del paquete (`/usr/lib/systemd/user`), así que no se editó. La versión 2.3.4 no tiene ninguna opción para limitar la dirección del servidor (no existe `shell.address`), por lo que "solo localhost" **no es posible**.
- Primer intento, **fallido**: quitar el servidor (`-s`) con un override. El proceso terminaba al instante porque ese servidor es lo que lo mantiene vivo, y el servicio quedó caído unos 30 segundos por mi cambio. Se detectó al verificar y se corrigió en el acto.
- Solución final: override de usuario `fluidsynth.service.d/sin-servidor-red.conf` con `PrivateNetwork=yes`. El proceso conserva su comando original, pero su red es privada, así que el puerto 9800 no se alcanza desde la LAN ni desde el host. Es más estricto que localhost. Antes de aplicarlo se comprobó que nada usaba ese puerto (MIDI va por ALSA y el audio por PipeWire, ambos verificados después).
- Verificación desde la red real: `ttyd` en 192.168.0.9:7681 no responde (HTTP 000) y en 127.0.0.1 devuelve 200; el puerto 9800 está cerrado en la LAN.
- Los tres hallazgos de seguridad viejos de esos servicios se marcaron como `revisado` (queda registro en la tabla `acciones`).

### Reputación online de procesos sospechosos: local primero (pedido del usuario)
- Pedido (corrige mi planteo anterior de no consultar nada): los datos se guardan en la PC; online solo se consultan los procesos **sospechosos**, para alertar si alguno figura como malicioso. Las alertas en sí se trabajan después; ahora importa que el flujo funcione.
- **Nuevo `reputacion.py`** y tabla `reputacion` (sha256, sha1, ruta, veredicto, fuente, detalle, fecha). Flujo: el escaneo local marca un hallazgo de severidad alta o media con ejecutable en disco, se calculan sus hashes **localmente**, se guardan y recién entonces se consulta online **únicamente ese hash**.
- **Qué no sale de la PC:** archivos (nunca se sube nada binario), hashes de procesos no sospechosos y cualquier otro dato del sistema. Hallazgos de red o sin ejecutable no generan consultas. Se puede apagar todo con `"consulta_online": false` en `~/.local/share/pc-doctor/config.json` (el archivo se crea con los valores por defecto).
- **Fuentes (probadas, sin clave):**
  - Team Cymru Malware Hash Registry, por DNS con SHA-1: detecta malware. Verificado con EICAR (100 %) y con un binario normal (sin registro).
  - CIRCL hashlookup, por HTTPS con SHA-256: base de archivos conocidos. Solo sirve para descartar, no para detectar.
  - MalwareBazaar: requiere una clave gratuita de abuse.ch en `config.json`. Implementada pero **sin probar** porque no hay clave; sin clave devuelve `Unauthorized` y no se usa.
  - Descartado: un SHA-256 no cabe en una etiqueta DNS (64 > 63 caracteres), de ahí el SHA-1 para Cymru.
- **Error corregido en la primera prueba:** EICAR no daba alerta porque CIRCL lo conoce como archivo existente (`eicar.com`) y mi lógica se detenía ahí. "Conocido" no es "limpio". Ahora se consultan todos los proveedores y un veredicto de malware siempre gana.
- **Control de costo:** máximo 3 consultas nuevas por corrida, los veredictos se reutilizan por hash durante 7 días y los hallazgos que comparten ejecutable hacen una sola consulta. Los pendientes pasan a la corrida siguiente.
- Un veredicto `malicioso` o `sospechoso` sube el hallazgo a severidad alta y queda en la lista `alertas` de `revision_seguridad()`. El aviso al usuario (notificación) queda pendiente.
- **Pruebas en una base temporal** (la real no se tocó): falso minero real en `/tmp` -> `sin_registro`, 1 sola consulta para 2 hallazgos; EICAR -> `malicioso` con alerta; segunda pasada -> 0 consultas (caché); con la consulta desactivada -> `sin_consultar`. Los archivos de prueba se eliminaron.
- `hallazgos_seguridad()` ahora muestra la reputación de cada hallazgo. Costo en el recolector: ~2,0 s en total.

### Alertas de escritorio (pedido del usuario)
- Decisiones del usuario: las alertas son **notificaciones de escritorio**, y MalwareBazaar queda **desactivado** (sin clave de abuse.ch por ahora; `malwarebazaar_key` sigue vacío en `config.json`).
- **Nuevo `alertas.py`** y tabla `notificaciones` (huella, fecha, título). Usa `notify-send`.
- **Qué avisa:** hallazgos de severidad alta con estado `nuevo` vistos en la corrida actual. Incluye lo que la reputación online marcó como malware (que sube a alta) y las reglas graves locales (minero por nombre, ejecución desde `/tmp`, terminal web sin contraseña, etc.). Los hallazgos de severidad baja o media no generan aviso.
- **Una vez por hallazgo:** se registra en `notificaciones` para no repetir el aviso cada 15 minutos. Los hallazgos marcados `revisado` o `falso_positivo` no avisan.
- **Un solo aviso agrupado por corrida:** detalla hasta 3 hallazgos y resume el resto. Es de urgencia crítica si hay veredicto de malware y normal en el resto de los casos.
- **Los fallos se reintentan:** un hallazgo solo se marca como avisado si la notificación realmente se envió; si falla (por ejemplo, sin sesión gráfica) se vuelve a intentar en la próxima corrida y nunca rompe el recolector.
- **Funciona desde el timer:** se verificó con `systemd-run --user`, que reproduce el entorno de un servicio de usuario. El bus de D-Bus es visible y, si faltara la variable, el módulo la reconstruye a partir del UID.
- **Interruptor:** `"notificaciones": false` en `config.json` (visible en `datos/config.json`).
- `uv run alertas.py --probar` envía una notificación de prueba.
- Pruebas en base temporal: EICAR + falso minero -> 1 aviso con 2 hallazgos; repetir -> 0; falso positivo -> 0; con la opción apagada -> 0. El recolector real no avisó porque no hay hallazgos graves nuevos. Ya no quedan hallazgos sin revisar con severidad alta.

### Alertas de salud del equipo (pedido del usuario)
- Pedido: avisar con notificación de escritorio cada vez que algo salga de sus valores normales (temperatura de CPU, velocidad y estado de discos, memoria, estado de GPU y CPU, voltaje; todo lo que diagnostica pc-doctor).
- **Inventario antes de diseñar** (lo que esta máquina expone sin root): temperaturas de CPU (`k10temp`), GPU (edge, junction, memoria) y NVMe; ventilador, voltaje del núcleo (`vddgfx`), potencia, uso y VRAM de la GPU; E/S, espacio y modo solo-lectura de los discos; RAM, carga y uso de CPU; mensajes del kernel (el usuario está en el grupo `adm`).
- **No disponible, y se informa en lugar de inventarlo:** voltajes de la placa (el sensor `asus` no expone ninguno y no hay un chip tipo `nct6775` cargado) y temperatura o SMART de los discos SATA `sda` y `sdb` (falta `smartmontools`, el módulo `drivetemp` y permisos). Ambos requieren `sudo`, así que quedan pendientes de aprobación.
- **Nuevo `salud.py`**, con tres tablas: `lecturas` (sensores por corrida, con el límite crítico que informa el hardware), `alertas_salud` (estado de cada alerta: activa o resuelta, última notificación) y la configuración en `config.json`.
- **Lectura agnóstica al fabricante:** recorre `/sys/class/hwmon` (cualquier chip: `k10temp`, `coretemp`, `amdgpu`, `nvme`, `drivetemp`, `nct*`...), `sysfs` de AMD para uso y VRAM, y `nvidia-smi` si existe. El parser de NVIDIA se probó con datos simulados (incluido `[N/A]`), pero no con una GPU NVIDIA real.
- **Reglas de "valores normales":** 15 reglas con umbrales de aviso y crítico, y un número de lecturas consecutivas (una cada 15 min) para evitar avisar por picos: temperatura de CPU (85/92), GPU, disco y placa, uso de GPU y CPU sostenidos, VRAM, voltaje de GPU, carga, RAM, swap, espacio libre, saturación y solo-lectura de discos, y desviación de rieles de la placa.
  - GPU y disco usan **el límite crítico que informa el propio hardware** (aviso a 20 y 18 grados por debajo, crítico a 8), con valores por defecto si no lo informa.
  - El crítico salta con una sola lectura; el aviso necesita varias seguidas (por ejemplo, 2 para temperaturas y 8 para GPU al máximo, es decir 2 horas).
  - Decisión: el uso alto de GPU o CPU **solo avisa si es sostenido** (jugar a pleno es normal).
  - Una alerta no parpadea: tiene histéresis (por ejemplo, un aviso de 85 °C no se resuelve hasta bajar de 81).
  - Ventilador detenido con el chip caliente (75 °C aviso, 80 °C crítico). A 0 RPM con el chip frío se considera modo silencioso normal, como en esta GPU.
- **Eventos del kernel y del journal:** patrones específicos de errores de disco o sistema de archivos, fallos de GPU, memoria agotada o con errores (OOM, MCE), limitación térmica y problemas de PCIe o energía. Descubierto al revisar los últimos 7 días: mi primer patrón genérico (`thermal`, `EDAC`, `MCE`, `amdgpu ring`) coincidía con mensajes normales del arranque, así que se reescribió y se probó con esos mensajes reales para comprobar que no producen alertas.
- **Control de ruido:** una sola notificación agrupada por corrida (4 detalladas y el resto resumidas). Alertas que persisten: se repiten cada 6 h (aviso) o 2 h (crítico). Un evento nuevo avisa de nuevo. Las resueltas se cierran en silencio. Si el envío falla, se reintenta en la siguiente corrida.
- **Configurable** en `config.json` (visible en `datos/config.json`): `"salud": false` apaga estas alertas, y `"umbrales": {"temp_cpu": {"aviso": 80, "muestras": 1}}` cambia cualquier límite.
- **Nuevas tools MCP (15 en total):** `estado_salud()` (lecturas en vivo, lo que está fuera de lo normal y lo que no se puede medir) y `alertas_salud(solo_activas, dias)`.
- **Pruebas:** 40 comprobaciones en una base temporal con un notificador falso (sostenido, persistencia, escalada, histéresis, límites del hardware, ventilador, discos, memoria, voltajes, config, eventos reales y benignos, agrupación y parser NVIDIA); todas pasaron sin enviar notificaciones reales. En la máquina real: 30 lecturas por corrida y nada fuera de lo normal. El recolector completo pasó de 2,0 s a 2,5 s.
- **Aviso previo antes de probar notificaciones reales:** se envió una única notificación marcada como [PRUEBA], con valores inventados y sin escribir nada en la base.
- Retención: las lecturas se borran a los 30 días junto con las métricas crudas, sin resumen diario. Las alertas resueltas se borran a los 90 días.
- Limitaciones: umbrales fijos, no aprendidos del historial de esta PC. Los voltajes de placa se evalúan solo si el kernel los expone con etiquetas de riel conocidas (+12 V, +5 V, +3,3 V). Las lecturas nuevas aún no se consultan desde `historial()`.

### Habilitar voltajes y SMART (pedido del usuario) - preparado, pendiente de ejecutar
- Pedido: habilitar los voltajes y el SMART. Requiere `sudo` y modifica `/etc`, por lo que **no se ejecutó**: se dejó el script `habilitar-sensores.sh` en el proyecto para que el usuario lo revise y lo ejecute.
- **Investigación previa (sin sudo):** `smartmontools` está en los repositorios y `drivetemp` existe en el kernel. Para los voltajes, ni `asus_ec_sensors` ni `asus_wmi_sensors` declaran la placa PRIME B550-PLUS; la única vía es `nct6775` (familia NCT679x), cuyo soporte para esta placa **no está confirmado**. Descubierto al revisar la lista de placas de cada driver.
- **El script (idempotente):** instala `smartmontools`; carga `drivetemp` y lo deja permanente en `/etc/modules-load.d/pc-doctor.conf`; prueba `nct6775` y solo lo deja permanente si aparece un sensor real (si no carga, informa el motivo y no toca el arranque; el parámetro `acpi_enforce_resources=lax` queda como decisión del usuario); crea `/etc/sudoers.d/pc-doctor`.
- **Permiso mínimo para el SMART:** una regla de sudoers que permite únicamente `smartctl -j -H -A` sobre cada disco, con esos argumentos exactos y sin contraseña. No permite otras opciones ni otros dispositivos. Se descartó añadir al usuario al grupo `disk` (da lectura cruda a todos los discos) y `setcap` sobre `smartctl` (cualquier proceso podría usarlo con sus capacidades). La regla se valida con `visudo -cf` antes de instalarse; el script generado se probó sin privilegios (sintaxis y regla válidas).
- **Lector de SMART en `salud.py`:** `parsear_smart` y `_smart`, que llaman a `sudo -n smartctl ...`; si falta el permiso se omite sin romper y `estado_salud()` lo informa como no disponible. Cubre salud general, sectores realocados, pendientes e incorregibles, errores CRC, desgaste y reserva (SATA y NVMe), con 9 reglas nuevas. El parser se probó con salidas JSON de ejemplo en el formato de `smartctl` 7.4, **no con un disco real** hasta que se habilite el permiso.
- Para deshacerlo todo: `sudo rm /etc/sudoers.d/pc-doctor /etc/modules-load.d/pc-doctor.conf && sudo apt remove smartmontools`.

### Umbrales aprendidos y registro histórico (pedido del usuario)
- Pedido: por sostenibilidad en el tiempo, un registro de los valores y las medias de cada componente, con umbrales que se aprendan de esta PC.
- **Contexto reposo/carga en cada lectura** (nueva columna `lecturas.contexto`, con migración automática de la base existente): reposo si la CPU está bajo 25 % y la GPU bajo 20 %. Es necesario porque una GPU a 70 °C jugando es normal y a 70 °C en reposo no; sin separar contextos, la media mezclaría ambas situaciones.
- **Tres niveles de memoria:**
  1. `lecturas`: lecturas crudas, 30 días (sin cambios).
  2. `lecturas_diarias` (nueva, **permanente**): por día, sensor y contexto: muestras, media, mínimo y máximo. Se completa al cerrar cada día y antes de borrar las crudas. Hace posible comparar contra meses atrás aunque las lecturas ya no existan. Resumir lecturas viejas se habría podido hacer solo al borrarlas, pero así el registro existe desde el primer día completo.
  3. `linea_base` (nueva): lo que es normal hoy, por sensor y contexto, con los últimos 30 días: n, media, desviación, mínimo, máximo, mediana, MAD, p95 y p99. Se recalcula cada 6 h.
- **Estadística robusta:** las anomalías se miden con mediana y MAD (desvío absoluto mediano) en vez de media y desviación, porque resisten datos atípicos (un día de mucho calor no corre la línea base). La media y la desviación se guardan igual para consulta.
- **Madurez:** un sensor solo genera avisos aprendidos con al menos 200 muestras en ese contexto (unos 2 días). Mientras tanto, `estado_salud()` informa "aprendiendo". Los avisos de límites absolutos siguen funcionando desde el primer momento.
- **Anomalía aprendida** (siempre `aviso`, nunca crítico): valor a 4 o más desvíos robustos de la mediana **y** con un cambio mínimo que importa (por ejemplo, 8 °C o 30 % en RPM), **dos lecturas seguidas**. Temperatura, potencia, RAM y VRAM solo hacia arriba; espacio libre solo hacia abajo; ventiladores y voltajes hacia ambos lados (un ventilador mucho más lento que lo habitual puede ser una falla).
- **Deriva lenta:** compara los últimos 7 días contra los 14 a 45 días anteriores, solo en reposo y solo sobre el registro diario: temperatura +6 °C, ventilador +30 % o espacio libre -8 puntos. Es lo que detecta un desgaste gradual (polvo, pasta térmica, disco llenándose). Se avisa como mucho una vez por semana. Necesita al menos 3 semanas de datos (7 recientes y 14 de referencia).
- **Errores encontrados y corregidos durante las pruebas:**
  - Las alertas de anomalía y deriva nunca se habrían resuelto: la comprobación usaba una parte de la clave que no coincide con el sensor. Ahora usa el nombre guardado.
  - Los mensajes mostraban `52.0563` con decimales sin sentido; ahora un decimal.
  - La deriva se activaba con solo 13 días de referencia, una base débil que daría falsas alarmas por variaciones normales; ahora exige 14.
- **Pruebas:** historial sintético de 10 días (reposo ~52 °C, carga ~72 °C): la base aprende cada contexto por separado; 70 °C bajo carga es normal y 70-71 °C en reposo avisa; +3 °C no avisa; una temperatura más fría no avisa; un ventilador a 300 RPM cuando suele estar en 900 avisa; la alerta se resuelve al volver a lo normal; el registro diario es idempotente; la deriva se detecta con 45 días y no con 20; migración de una base con el esquema anterior; y regresión de las alertas de límites (sostenido, persistencia, escalada, histéresis). Todas pasaron. En el equipo real el aprendizaje arrancó con 0 sensores maduros.
- **Nuevas tools MCP (17 en total):** `linea_base_aprendida(categoria, contexto)` y `medias_diarias(sensor, dias)`. `estado_salud()` ahora incluye el estado del aprendizaje.
- Limitaciones: la línea base no distingue franja horaria ni estación del año (el calor de verano puede mover la mediana, por eso la deriva compara contra un mes y avisa como máximo semanalmente). La CPU medida en cada corrida incluye el propio arranque del recolector, así que algunas corridas se clasifican como carga sin serlo; no afecta a la mediana porque son pocas.

### Verificación de los sensores habilitados (el usuario ejecutó el script)
- `nct6775` reconoció la placa (chip `nct6798`), `drivetemp` creó un chip por disco y el permiso de SMART funciona sin contraseña. Se leen SMART de los tres discos y 15 voltajes.
- **Errores encontrados en la primera corrida real:**
  - Las entradas `AUXTIN*` (termistores sin conectar) daban 84 °C y -61 °C, y la regla de ventilador detenido usaba esa temperatura: 5 alertas críticas falsas y una notificación real. Decisión: ignorar por etiqueta las entradas sin sensor (`AUXTIN*`, `PECI ... Calibration`, `PCH_*`) y exigir, para la regla de ventilador detenido, que ese ventilador haya girado alguna vez (un conector vacío marca 0 siempre).
  - Los dos `drivetemp` se llamaban igual (`drivetemp/temp1`) y habrían mezclado sus líneas base. Decisión: si el chip hwmon pertenece a un disco, el nombre lleva el disco (`drivetemp_sda`, `drivetemp_sdb`).
  - Se borraron de la base las lecturas basura de esa primera corrida; el resto de las pruebas usó un notificador falso.
- **Voltajes sin etiqueta:** el kernel entrega `in0`–`in14` sin nombre de rail y el mapeo depende de cada placa, así que no se inventó ninguno: se registran y se aprenden por línea base, sin regla de desviación fija.
- **Hallazgo real:** SMART de `sdb` con sectores realocados, pendientes e incorregibles y errores CRC (ver CHANGELOG).

## Nivel nuevo 1: perfil por actividad (pedido del usuario, en fases)
El usuario pidió cuatro fases con parada y OK al final de cada una. Esta es la **Fase 1: contexto `juego`**.

### Decisiones
- **Contexto `juego`:** además de `reposo` y `carga`, una lectura se etiqueta `juego` si hay un juego en ejecución. Tiene prioridad sobre los otros dos, porque una GPU a 80 °C jugando es normal. Se aprende por separado (línea base, anomalías y registro diario funcionan igual con cualquier contexto).
- **Qué cuenta como juego (decisión del usuario):** solo la ejecución directa del juego. El cliente de Steam siempre está abierto, así que ni `steam` ni `steamwebhelper` cuentan. Las firmas están todas en `FIRMAS` (`actividad.py`), en un solo lugar:
  1. `reaper SteamLaunch AppId=N`: el lanzador que Steam crea por cada juego; el nombre sale del `appmanifest`.
  2. Primer argumento dentro de `steamapps/common/<juego>/` (juegos nativos y el proceso de Proton). Las carpetas de herramientas (Proton, SteamLinuxRuntime, GE-Proton) no cuentan. Si el primer argumento es un intérprete (bash, java, python), se mira el programa que ejecuta.
  3. Un `.exe` como primer argumento (wine/Proton renombran el proceso), o `wine`/`wine64` con un `.exe`. Se ignoran los `.exe` auxiliares (services, winedevice, explorer, steam, crashhandler, etc.).
  4. `gamescope` y los clientes de `gamemode` son **genéricos**: solo valen si no se identificó un juego concreto, para no duplicar la sesión de un juego que corre dentro de gamescope.
- **Desvío respecto del pedido:** `wineserver` solo **no** cuenta. Un wineserver puede quedar vivo con `winecfg` o `winetricks` y no tiene `.exe` en su línea de comandos; se detecta el juego por su propio proceso.
- **Se leen los procesos con psutil** (primeros 3 argumentos de cada línea de comandos, sin permisos especiales). Los appmanifest de Steam solo se leen cuando algo coincide. Costo medido: 30 ms (máximo 62 ms).
- **Sesiones (`sesiones_actividad`: tipo, detalle, inicio, fin, ultima_vez, origen):** el recolector abre una sesión al ver un juego, la extiende en cada corrida y la cierra cuando desaparece (`fin` = la última vez que se lo vio). El inicio es la hora real de arranque del proceso, no la de la primera corrida. Si una sesión abierta no se vio en 45 min (equipo apagado), se cierra y la siguiente es otra. El paso `actividad` va **antes** de `salud` en el recolector, porque el contexto de las lecturas depende de él.
- **Base temporal para pruebas:** `PC_DOCTOR_DATOS` cambia la carpeta de datos (`db.py`). Las pruebas la usan y parchean el notificador; la base real no se toca para probar.

### Migración del historial (opción B, elegida por el usuario)
- Una función de una sola vez (`uv run actividad.py --reclasificar`, simula; con `--aplicar` aplica) pasa a `juego` las lecturas `reposo` o `carga` de las corridas donde había un juego entre los procesos de `top_procesos`. Se une por `metrica_id`, exacto, sin la ventana de ±60 s que había propuesto. Los juegos se reconocen por la carpeta de instalación y los ejecutables sin extensión de sus bibliotecas de Steam.
- **Seguridad de la migración:** simula por defecto; al aplicar guarda una copia (`VACUUM INTO`) junto a la base, rehace los resúmenes diarios de los días afectados, reconstruye las sesiones (origen `reconstruida`), recalcula la línea base y deja registro en `acciones`. Es idempotente: si no hay nada que cambiar, no toca ni copia nada.
- **Resultado en la base real:** 26 corridas con `SlayTheSpire`; 636 lecturas `carga` y 150 `reposo` pasaron a `juego`; 1 sesión reconstruida (12:56 a 17:27). Copia: `datos/doctor.db.antes-de-juego-1793220248`. Todas las lecturas `reposo` de ese período también cambiaron: el juego estuvo abierto todo el rato, y por la regla nueva eso es `juego`.
- La línea base de `juego` quedó vacía: cada sensor tiene 19 lecturas y el mínimo para mostrar algo es 20. Lo esperado.

### Errores encontrados y corregidos
- La copia de seguridad se llamaba igual si la migración se aplicaba dos veces en el mismo segundo y fallaba; además una migración sin nada que cambiar igual creaba copia. Ahora no hace nada si no hay cambios.
- Mi prueba esperaba que `java -jar .../SlayTheSpire/...jar` no fuera un juego; sí lo es (intérprete con el programa en los argumentos) y se detecta bien. Era un error de la expectativa.

### Pruebas (base temporal, notificador falso)
20 casos de firmas (cliente de Steam, helpers de pressure-vessel, Proton y runtimes, editores con la ruta de un juego, `.exe` auxiliares, wine, gamescope), unificación de varios procesos en un juego, concreto sobre genérico, ciclo de vida de sesiones (abrir, extender, cerrar, vencer), contexto `juego` de punta a punta con `salud.ciclo`, migración sobre una copia de la base real (simulacro, aplicación, idempotencia, copia) y tiempo del recolector: 2,7 a 3,1 s (antes ~2,5 s; el límite pedido es 4 s).

### Limitaciones
- **No verificado con un juego real en ejecución:** las firmas se probaron con líneas de comandos sintéticas. En especial, no sé cómo se ve exactamente el `argv` de un proceso de Proton, y el formato de `gamemodelist` es una suposición (no había gamemode con clientes).
- La migración solo ve los 5 procesos que más CPU usaban por corrida: un juego fuera de ese top queda con el contexto viejo.
- Cualquier `.exe` bajo wine que no esté en la lista de auxiliares cuenta como juego (un Notepad++ en wine, por ejemplo). Un editor o gestor de archivos no cuenta porque se excluye por nombre, pero un programa no listado que tenga como primer argumento la ruta de un juego sí.
- Resolución de sesiones: ±15 min. Un juego abierto y cerrado entre dos corridas no se ve.
- Madurez: `juego` necesita 200 muestras por sensor y hay una por corrida, es decir unas **50 horas de juego** para que se activen las anomalías (reposo y carga tardan unos 2 días de reloj). Queda pendiente decidir si se baja ese mínimo para este contexto.
- La deriva lenta solo mira `reposo`. Con las lecturas de `reposo` de hoy convertidas a `juego`, tardará en tener referencia suficiente.

## Nivel nuevo 2: correlación de eventos y línea de tiempo (Fase 2)

### Decisiones
- **`correlacion.py`** junta en una lista común lo que pc-doctor ya registra: cambios de entorno (diferencia entre snapshots consecutivos: kernel, driver de GPU y paquetes instalados, quitados o actualizados), eventos del sistema, alertas de salud, hallazgos de seguridad, sesiones de actividad y acciones de pc-doctor. No agrega tablas ni recolección nueva.
- **Ventana:** 48 h antes y 2 h después del inicio de la alerta, configurable en `config.json` (`"correlacion": {"horas_antes": N, "horas_despues": N}`) o por llamada.
- **Puntaje = afinidad × cercanía.** Afinidad: cuánto se relaciona el elemento con la categoría de la alerta (un driver de GPU con una alerta de GPU: 1,0; con una de disco: 0,25 del valor base). Las listas (paquetes por categoría, herramientas de monitoreo, categoría de eventos) están al principio del módulo. Cercanía: baja a la mitad cada 12 h; lo ocurrido *después* de la alerta baja a la mitad cada 1 h y parte del 50 %, porque no puede ser causa.
- **No se afirma causalidad:** el resultado se llama `posibles_causas`, lleva la etiqueta alta, media o baja y el aviso "coincidencias en el tiempo, no causas demostradas".
- **Herramientas de monitoreo (smartmontools, lm-sensors, nvtop...):** instalarlas suele *destapar* un problema que ya existía; tienen afinidad baja y el texto lo aclara. Caso real: `smartmontools` quedó instalado un minuto antes de las alertas de SMART de `sdb`, pero los sectores defectuosos ya estaban.
- **Kernel y driver de GPU fusionados:** `amdgpu` viene dentro del kernel (`version_driver` = "kernel X (in-tree)"), así que cada kernel nuevo se veía además como un "cambio de driver". Ahora es un solo elemento, con afinidad máxima para alertas de GPU.
- **Variedad:** como mucho 3 candidatos del mismo tipo entre los primeros. Sin esto, un origen ruidoso (`smartd` repetido) tapaba al resto.
- **Notificación:** se agrega `↳ posible relación: ...` solo si hay un **cambio de entorno** (driver de GPU, kernel que trae el driver de GPU, o paquete de la misma categoría) con afinidad mínima 0,8 en las 24 h anteriores al inicio de la alerta. No se citan eventos, alertas ni sesiones (darían ruido) ni herramientas de monitoreo. El kernel solo supera el umbral cuando trae el driver de la GPU: un kernel nuevo no se cita en una alerta de SMART. Sin candidato fuerte, el texto es idéntico al de antes. La búsqueda va dentro de un `try`: si falla, el aviso sale igual.
- **Orden del recolector:** `snapshot` pasa antes de `salud`. Antes quedaba segundos *después* de la alerta, así que el aviso de la corrida en que cambiaba un driver nunca podía citarlo.
- **Tools nuevas (ya son 20):** `linea_de_tiempo(desde, hasta)` y `correlacionar(alerta_id)` (acepta el `id` de `alertas_salud()`, que ahora se muestra, o `hallazgo:N`).
- **`historial()` ampliado:** además de las métricas de siempre, acepta el nombre de cualquier sensor (`k10temp/Tctl`, `sda/errores_crc`...). Usa las lecturas crudas (30 días) y completa lo más antiguo con el promedio diario ponderado de `lecturas_diarias`; el parámetro `contexto` filtra reposo, carga o juego. Si el sensor no existe, sugiere nombres parecidos.

### Errores encontrados y corregidos
- Driver de GPU y kernel duplicados (ver arriba).
- El kernel aparecía como "posible relación" de una alerta de SMART de disco: ruido. Bajé su afinidad base de 0,8 a 0,7 (bajo el umbral de "fuerte") y quité los paquetes `linux-image` de las categorías disco, memoria y placa.
- La acción `limpiar_descargas_viejas` puntuaba alto para una alerta de disco; bajé su afinidad de 0,9 a 0,5.
- `historial()` comparaba una fecha en texto con un epoch y fallaba al mezclar crudas y diarias.
- `parecidos` buscaba en `linea_base`, vacía por ahora; ahora busca en `lecturas`.
- Un escenario de mi prueba ponía la alerta *antes* de instalar `smartmontools`; el módulo lo descartó bien (no puede ser causa).

### Pruebas (base temporal, notificador falso)
Escenario sintético con 4 snapshots (kernel, mesa, fuentes, smartmontools), eventos repetidos, sesión de juego, hallazgo de minero y acción: orden, agrupación de eventos repetidos, observadores, alerta que no se cita a sí misma, ventana configurable, ids inexistentes, línea de tiempo en orden. Notificación con candidato, sin candidato (texto idéntico al anterior) y con la correlación rota (el aviso sale igual). `historial` con sensor crudo, mezcla con diario, filtro de contexto, sensor inexistente y métricas viejas. Sobre la base real, solo lectura: `correlacionar` de la alerta real de `sdb` y `linea_de_tiempo("6h")`. Tiempo de la búsqueda de relación sobre la base real: 5 ms. Recolector completo: 2,7 a 3,3 s.

### Limitaciones
- Los snapshots solo se guardan cuando cambia algo y la hora es la de la corrida (±15 min). Hoy hay 2, así que las comparaciones de entorno son pobres hasta que pase tiempo.
- Es una heurística: las listas de afinidad son nuestras y se ajustan a ojo. Puede sugerir coincidencias sin relación real o pasar por alto una causa que no esté registrada (por ejemplo, un cambio de BIOS o de hardware).
- Los eventos sólo incluyen lo que `eventos` ya guarda (errores del journal); no hay línea de tiempo de lo que no se registró.
- Si el recolector estuvo apagado, el cambio se registra al volver a correr, no cuando ocurrió.

## Nivel nuevo 3: reporte semanal con Claude (Fase 3)

### Decisiones
- **`reporte.py`** ejecuta `claude -p` en modo no interactivo, toma su texto y **lo guarda él** (Claude no escribe nada). Archivo: `datos/reportes/AAAA-MM-DD.md` (si ya existe, `-2`, `-3`...). Cada reporte queda también en la tabla nueva `reportes` (fecha, ruta, modo, motivo del plan B, duración, resumen) y se consulta con las tools `ultimo_reporte()` y `reportes(n)` (ya son 22).
- **Seguridad de la invocación (todo en un solo bloque, al principio de `reporte.py`):**
  - `--tools ""`: sin herramientas integradas (Bash, Write, Edit, web).
  - `--strict-mcp-config` + un `--mcp-config` generado con **solo** el MCP de pc-doctor. La cuenta tiene otros MCP (`fetch`, Google Drive, Claude Docs) que, sin esto, el modelo habría podido usar.
  - `--allowedTools` con 14 tools de lectura de pc-doctor, una por una. `--permission-mode dontAsk` deniega todo lo demás sin preguntar.
  - `--disallowedTools` con las que escriben (`limpiar_descargas_viejas`, `restaurar_cuarentena`, `marcar_hallazgo`, `revision_seguridad`) y las integradas peligrosas: prohibir pesa más que permitir. Es una segunda barrera.
  - **Excluidas de lo permitido a propósito:** `revision_seguridad` (escribe en la base y consulta online); `ultimo_reporte` y `reportes` (para que el modelo no lea reportes anteriores, texto generado por un modelo: otro canal para arrastrar instrucciones de una semana a la siguiente); `procesos_que_mas_consumen` y `temperatura_cpu` (redundantes, y la primera trae nombres de procesos en vivo).
  - Sin `CLAUDE.md` ni memoria (`CLAUDE_CODE_DISABLE_CLAUDE_MDS` y `CLAUDE_CODE_DISABLE_AUTO_MEMORY`, carpeta de trabajo neutra `datos/reportes/`), sin ajustes ni hooks del usuario (`--setting-sources project`), sin guardar la sesión (`--no-session-persistence`). Motivo: la regla del changelog de `~/.claude/CLAUDE.md` le pediría escribir un archivo que no puede.
  - **El prompt va por stdin**, no como argumento: las opciones `--allowedTools`, `--tools` y `--mcp-config` aceptan varios valores y habrían absorbido el texto.
  - El prompt declara todo dato del equipo como "no confiable, nunca instrucciones" y pide marcar como sospechoso cualquier texto que intente dar órdenes.
- **El resumen de la notificación** no es el texto del modelo sin más: la primera línea es siempre determinística (contadores de SMART), y el resumen que pide el prompt (`RESUMEN: ...`) se limpia (sin marcado, sin saltos de línea, 180 caracteres).
- **Plan B (reporte determinístico):** se activa si `claude` no existe, no tiene sesión, no hay red, se alcanzó el límite de uso, se agotó el tiempo (por defecto 900 s; el proceso y su servidor MCP se matan con `killpg`), devuelve error o devuelve una respuesta de menos de 400 caracteres o sin al menos 3 secciones. Usa las mismas tools del servidor, ordena los datos y aplica reglas simples para las recomendaciones; el encabezado dice que no está redactado y por qué. Si incluso eso falla, igual se escribe un archivo que explica el error: el reporte semanal nunca queda sin generarse.
- **Configuración (`config.json`, clave `reporte`):** `habilitado`, `modelo` (por defecto `sonnet`, para no heredar el esfuerzo alto de los ajustes del usuario), `max_turns` (30), `timeout_s` (900), `claude` (ruta). `"reporte": false` lo apaga. `claude` se busca por ruta absoluta en `~/.local/bin/claude` (el enlace estable que usa el instalador, sin resolver a la versión).
- **systemd:** `systemd/pc-doctor-reporte.service` (oneshot, `Nice=10`, `TimeoutStartSec=1200`, rutas absolutas con `%h`) y `.timer` (`OnCalendar=Sun *-*-* 20:00:00`, `Persistent=true`). Verificados con `systemd-analyze --user verify`; próximo disparo calculado: domingo 2026-11-01 20:00. **Sin instalar, esperando la revisión del usuario.**

### Errores encontrados y corregidos
- **Bug de la fase anterior:** `estado_salud()` seguía diciendo que faltaba `drivetemp` aunque estaba activo. Buscaba nombres que empiezan con `drivetemp/` y desde el renombre por disco son `drivetemp_sda/`. Ahora comprueba cada disco SATA.
- El prompt le pedía al modelo `historial("temp_gpu")`, métrica vieja que en este equipo (GPU `amdgpu`) viene vacía: la temperatura real está en las lecturas de salud (`amdgpu/edge`, `junction`...). El prompt y el plan B usan ahora los sensores reales, separados por contexto (reposo, carga, juego).
- Plan B: sublistas sin sangría, línea vacía en "Cambios de entorno" y el mismo origen repetido en "Errores del sistema".
- Mi prueba esperaba "datos no confiables" en minúsculas y el prompt lo dice en mayúsculas (error de la prueba).

### Pruebas (base temporal, `claude` falso, notificador falso)
- Invocación: 14 tools permitidas, todas existen en el servidor; ninguna de las que escriben está permitida; solo el MCP de pc-doctor; sin integradas; prompt por stdin; carpeta neutra; variables de entorno puestas.
- Plan B ante: sin sesión, límite de uso, sin red, código de error desconocido, respuesta corta, tiempo agotado (el proceso queda muerto), `claude` inexistente. Modos `--sin-claude`, `--sin-notificar` y reporte desactivado.
- Resumen malicioso (`<b>`, escape ANSI, salto de línea con una "orden"): el resumen guardado y el de la notificación quedan limpios; la línea con la "orden" queda en el cuerpo del archivo como texto.
- **Sin costo, con el `claude` real:** el comando exacto contra el binario real, con una carpeta de usuario vacía y una clave de API inválida, termina con `Invalid API key`: acepta todas las opciones y el clasificador lo reconoce como "sin sesión".
- **Desde un servicio (`systemd-run --user`):** (A) `claude` falso: reporte en modo `claude`; (B) `claude` real con clave inválida: cae al plan B con el motivo correcto. En ambos, rutas absolutas y entorno funcionan. Sin notificaciones reales (ya se probaron desde un servicio en fases anteriores).

### Limitaciones
- **Sin verificar:** una ejecución real de `claude -p` con tu sesión iniciada desde un servicio. Falta confirmar que el login está disponible fuera del terminal y que el modelo usa las tools como se espera. Costo: una consulta con varias llamadas a tools.
- Los nombres exactos de las tools MCP (`mcp__pc-doctor__<tool>`) se infirieron de la convención de Claude Code; si estuvieran mal, `dontAsk` denegaría todo y el reporte caería al plan B con el modelo sin datos útiles. La prueba real lo confirma.
- Texto malicioso en los datos del equipo puede terminar en el archivo del reporte (no se filtra el contenido que redacta el modelo); el límite es que el modelo no puede ejecutar nada ni salir de pc-doctor.
- Con `Persistent=true`, si la PC arranca después del domingo, el reporte puede correr apenas se enciende y antes de tener red: en ese caso queda el plan B de esa semana.
- La línea base todavía no es madura: las "tendencias contra la línea base" serán pobres durante semanas.

### Cierre de la fase 3: instalación y primera ejecución real (autorizadas por el usuario)
- **Timer instalado y habilitado** (`~/.config/systemd/user/pc-doctor-reporte.{service,timer}`, copias de `systemd/`). Próximo disparo: domingo 2026-11-01 20:00. El timer del recolector sigue activo.
- **Primera ejecución real** con la sesión del usuario, desde `systemd-run --user`, sin notificaciones: 27 s, modo `claude`, sin plan B. Las tres dudas quedaron resueltas: el login funciona desde un servicio, los nombres `mcp__pc-doctor__<tool>` son correctos y el modelo usó las tools (el contenido coincide con la base: contadores de `sdb`, sesión de juego, único paquete nuevo, `ttyd`, aviso de correo de `smartd`). Declaró que la línea base no es madura y que solo hay 5 horas de datos, en vez de inventar tendencias. Archivo: `datos/reportes/2026-10-28.md`.
- **Problema detectado en esa ejecución:** el reporte recomendaba revisar a mano los ventiladores `fan1/3/4/5/6`. Eran las 5 alertas críticas falsas de la primera corrida con los sensores nuevos (conectores vacíos, bug ya corregido), que seguían en `alertas_salud`. El modelo no tiene forma de saber que eran falsas. Se borraron esas 5 filas (todas ya resueltas) y quedó registro en `acciones` (`limpieza_falsos_positivos`). Esa recomendación del primer reporte es errónea; el archivo se dejó tal cual salió.
- **Observación sobre el modelo:** señaló una diferencia entre el máximo de CPU de la sesión (81,75 °C, sensor `Tccd1`) y las lecturas listadas (72,9 °C, `Tctl`). No es un error: son sensores distintos, y el resumen de sesiones usa el máximo de todos los de CPU.

## Nivel nuevo 4: dashboard interactivo (pedido del usuario, en fases)
El usuario pidió una app web local (FastAPI + React/Vite/TypeScript + Recharts) para ver y gestionar lo que pc-doctor diagnostica, en 5 fases con parada y OK al final de cada una. La Fase 4 original del nivel anterior (diagnóstico automático por alertas) queda **pendiente**; mientras tanto la sección "diagnósticos" del dashboard mostrará "no disponible todavía" porque la tabla `diagnosticos` no existe.

### Fase 0: prerequisitos
- **Node y npm no están instalados** (`node`, `npm`, `npx` no existen; tampoco fnm, volta, nvm, bun ni pnpm). Por pedido del usuario no se instaló nada y se le presentaron opciones. El repositorio de Ubuntu ofrece `nodejs 18.19.1` y `npm 9.2.0`; Node 18 terminó su soporte en abril de 2025, así que no sirve para versiones actuales de Vite.
- **Puerto 8787:** libre (nada escucha). El servicio irá solo en `127.0.0.1`.
- **Dependencias de Python:** `fastapi 0.162.0` y `uvicorn 0.54.0` agregadas con `uv add` (solo el entorno del proyecto, sin sudo). Compatibilidad: el MCP sigue cargando sus 22 tools y el recolector importa bien.
- **Convención de archivos con punto:** `package.json`, `tsconfig.json` y `vite.config.ts` no llevan punto, así que no hace falta preguntar nada por ahora. Se arma el proyecto de Vite a mano para evitar el `.gitignore` que genera la plantilla (el proyecto no es un repositorio git). `node_modules/` será visible y grande (cientos de MB) dentro de `web/frontend/`.
- **Tablas existentes que alimentan el dashboard:** `lecturas`, `lecturas_diarias`, `linea_base`, `metricas`, `alertas_salud`, `hallazgos_seguridad`, `escuchas`, `eventos`, `snapshot_entorno`/`hardware`/`software`, `sesiones_actividad`, `reportes`, `acciones`, `cuarentena`, `notificaciones`. No existe `diagnosticos`.

### Node instalado (opción A, elegida por el usuario)
- Tarball oficial `node-v24.22.2-linux-x64.tar.xz` (32 MB) de nodejs.org. SHA-256 verificado contra `SHASUMS256.txt` (coincide: `48cc0e21...aaf75`). Limitación honesta: el checksum viene del mismo sitio, así que protege contra una descarga corrupta, no contra un compromiso del sitio; no se verificó la firma GPG.
- Instalado en `~/.local/share/pc-doctor/node/` (visible desde `datos/node/`, 208 MB). Node 24.22.2 y npm 11.19.1. **No está en el PATH global**: solo lo usará `web/construir.sh`, que lo agrega al PATH de su propio proceso. Se desinstala borrando esa carpeta.

### Fase 1 del dashboard: API de solo lectura (`web/api.py`)

#### Decisiones
- **Un módulo compartido, `consultas.py`, para que el dashboard y el MCP muestren exactamente lo mismo.** Las funciones de consulta (alertas, hallazgos, sesiones, estado en vivo, componentes, series, bandas, aprendizaje) salieron de las tools de `server.py` a este módulo, sin dependencias de FastMCP ni de FastAPI. Las tools ahora son envoltorios finos que recortan el resultado para el chat. Comprobado: la salida de las tools antes y después del refactor es idéntica (14 de 16 consultas iguales; las dos que diferían eran un dato nuevo del recolector y el orden de elementos con la misma hora, ya desempatado), y una prueba compara la API contra las tools sobre la misma base (12 comparaciones, 0 diferencias).
- **Solo lectura de verdad, no por convención.** `db.SOLO_LECTURA` hace que `db.conectar()` abra la base con `mode=ro` y no toque el esquema; la API lo activa al importarse. Las acciones de la Fase 4 deberán pedir `escribir=True` de forma explícita. Comprobado: `INSERT`, `UPDATE`, `DELETE`, `DROP` y `CREATE` a través de la conexión de la API fallan con "attempt to write a readonly database", y el hash de la base no cambió tras ejecutar todas las pruebas.
- **Seguridad desde el primer día, no recién en la Fase 4:** solo `127.0.0.1`; se rechaza toda petición cuyo `Host` no sea `localhost:PUERTO` o `127.0.0.1:PUERTO` (421), lo que evita que una página externa lea los datos por DNS rebinding; solo se acepta `GET` (cualquier otro método da 405); `Cache-Control: no-store`, `X-Content-Type-Options`, `X-Frame-Options: DENY` y `Referrer-Policy`; sin cabeceras CORS. `/docs` y `/openapi.json` desactivados. El puerto se puede cambiar con `PC_DOCTOR_PUERTO` (las pruebas lo usan).
- **Bandas coherentes con las alarmas.** `linea_base.limites()` es ahora la única definición de "fuera de lo habitual" y la usan la detección de anomalías y el gráfico. Comprobado contra la implementación anterior con 24.000 casos aleatorios: 0 diferencias (en el borde exacto el resultado depende de la coma flotante, de forma irrelevante). La banda que devuelve la API tiene dos niveles: la zona típica (mediana ± 2 desvíos robustos) y los límites de anomalía (los que realmente disparan un aviso, que además exigen un cambio mínimo según el tipo de sensor). Los puntos de la serie traen `f` (fuera de los límites de su contexto) solo si esa línea base es madura.
- **Series:** hasta 30 días usa las lecturas crudas, agrupadas en intervalos si pasan de 800 puntos (con mínimo y máximo de cada intervalo); sobre 30 días usa `lecturas_diarias` y solo las crudas de hoy. Cada punto lleva el contexto (`c`) y el juego en curso (`a`) para el tooltip.
- **Componentes:** las lecturas se agrupan en cpu, gpu, ram, un componente por disco físico (más "Particiones"), ventiladores y voltajes por chip, y placa. El título de los discos sale del hardware del último snapshot; el de la GPU se extrae de la descripción de `lspci` para cualquier fabricante (`nombre_gpu`). Cada sensor trae estado (normal, aviso, crítico), referencia (aprendida, aprendiendo, fija o ninguna) y si está dentro de la banda de su contexto actual. Cada tarjeta resume `segun_linea_base` (dentro, fuera, aprendiendo, sin referencia).
- **Fuentes ausentes:** una sección cuya tabla no existe, o una instalación sin base, devuelve `{"disponible": false, "mensaje": "No disponible todavía: ..."}` con HTTP 200 en vez de un error. La línea de tiempo sigue funcionando si falta alguna de sus fuentes. `diagnosticos` siempre responde así hasta que exista esa función.
- **Lectura en vivo con caché de 20 s:** `/estado`, `/componentes/*` y `/limitaciones` comparten una sola lectura de sensores (incluye SMART por `sudo`), para que varias pestañas o el refresco automático no la repitan.
- **Configuración:** `/api/config` devuelve `config.json` sin secretos (los campos cuyo nombre sugiere clave, token o contraseña salen como `{"cargada": true|false}`), más la configuración efectiva del reporte. `reputacion.cargar_config(crear=False)` evita que una consulta cree el archivo.
- **Datos de prueba:** `web/datos_de_prueba.py CARPETA` genera una base sintética (120 días de lecturas, 30 crudos y el resto como registro diario, línea base madura, 60 sesiones de juego, alertas, hallazgos, eventos, reportes, 3 snapshots y una configuración con un secreto falso). Se niega a escribir en la carpeta de datos real o en una base existente. Sirve para probar la API ahora y para desarrollar el frontend.

#### Errores encontrados y corregidos
- Título de la GPU `AMD/ATI` (tomaba el primer grupo entre corchetes) y RAM de 33,5 GB (GB decimales; el equipo informa 31,2 GiB).
- La tarjeta no decía si el valor era normal según la línea base del contexto actual.
- Un ventilador a 0 RPM con historia de giro se mostraba como "gira"; ahora `giro` es `gira`, `parado` o `vacio`.
- La estimación de "días para madurar" no tenía sentido para `carga` y `juego` (depende del uso): se quitó, con `depende_del_uso`.
- Dos tarjetas "Ventiladores" idénticas (GPU y placa): el título ahora lleva el chip.
- `correlacion/{id}` sin base daba 503 en lugar de "no disponible".
- Línea de tiempo: los elementos con la misma hora salían en orden variable; se agregó un desempate.
- Mi propio `pkill -f` coincidió con el texto del comando y cerró mi shell; ahora se apaga por PID.

#### Pruebas (base temporal; la real solo se leyó)
27 endpoints con HTTP 200; 9 casos de `Host`, 6 métodos, 23 parámetros inválidos, inyección SQL en el nombre del sensor, recorrido de rutas en reportes (`../`, `%2f`), cabeceras; base de una versión anterior (sin 3 tablas) y carpeta sin base; 384 peticiones en paralelo (8 hilos) mientras otro proceso escribía, sin errores (mediana 17 ms, p95 208 ms); lectura de la base real con datos verdaderos y base real intacta (hash y fecha idénticos). Consumo del servidor en reposo: 61 MB de RAM al arrancar (69 MB tras usar los endpoints) y 0,05 % de un núcleo. Las pruebas de las fases anteriores del MCP siguen pasando.

#### Limitaciones
- La primera lectura en vivo tarda ~1,5 s (SMART por `sudo` más el muestreo de E/S); las siguientes, dentro de los 20 s, son inmediatas.
- Con la base real, la línea base todavía no es madura: todas las tarjetas dicen "aprendiendo" y las bandas aparecerán con los días. En `juego` hacen falta unas 50 horas de juego.
- Un disco se identifica por su nombre de dispositivo (`sda`, `sdb`): si el sistema reasigna los nombres tras un reinicio, el historial de sensores seguirá con el nombre anterior.
- La API no tiene autenticación en las lecturas: cualquier proceso local del mismo equipo puede leerlas. La protección es de red (solo localhost) y de navegador (Host, sin CORS).

### Fase 2 del dashboard: frontend (`web/frontend/`)

#### Decisiones
- **Stack y versiones** (fijadas por `package-lock.json`): React 19.3.1, Recharts 3.10.1, react-markdown 10.1 con remark-gfm 4.0, Vite 7.3.7, `@vitejs/plugin-react` 5.2, TypeScript 5.9.3. Elegí Vite 7 y TypeScript 5.9 en vez de lo último de npm (Vite 8, TypeScript 7 con compilador nuevo) por ser lo más probado, y comprobé que los rangos de dependencias de pares encajan. `npm audit`: 0 vulnerabilidades (también solo producción).
- **Proyecto armado a mano**: sin la plantilla de Vite, que trae un `.gitignore`. No se creó ningún archivo con punto, así que no hizo falta preguntar. npm 11 bloqueó el script de instalación de `esbuild` (no figura en `allowScripts`) y la compilación funciona igual, así que no se habilitó. `node_modules/` ocupa 122 MB y es visible dentro de `web/frontend/`.
- **Una sola página con 8 secciones**: encabezado, tarjetas de estado, vista de detalle, alertas y hallazgos, línea de tiempo (con la tabla de sesiones de juego), reportes y diagnósticos, limitaciones y sensores, entorno. Enrutado propio mínimo con la API de historial (`/`, `/componente/{tipo}?id=&sensor=` y `/alerta/{id}`): el servidor ya devuelve la misma página para esas rutas, así que los enlaces directos de la Fase 3 funcionan desde ahora.
- **Un reloj de 60 s** (`tick`) que reactiva todos los pedidos sin recargar la página. Con la pestaña oculta no se pide nada, y al volver se actualiza si pasó más de un minuto. La hora de la última actualización exitosa figura en el encabezado, con un botón "Actualizar". Si un pedido falla se conservan los últimos datos y se avisa una sola vez, arriba.
- **Colores con significado, nunca solos**: cada estado lleva color, ícono (círculo con tilde, triángulo, octógono con cruz) y texto; los puntos fuera de lo habitual son rombos, no solo un color distinto. Modo claro y oscuro según el sistema (variables CSS). Foco visible, enlace para saltar al contenido, `aria-pressed` en los selectores y descripción de texto del gráfico.
- **Gráfico**: línea medida; detrás, la zona habitual aprendida (mediana ± 2 desvíos robustos) **según el contexto de cada punto** (por eso en "Todos" la banda cambia de altura entre reposo, carga y juego); con un contexto elegido, además, líneas punteadas con los límites de aviso. Rombos para lo que cae fuera de esos límites. El globo muestra valor, hora, contexto, juego en curso, mínimo y máximo si es un promedio diario, y lo habitual de ese contexto. Rangos: 24 h, 7, 30 días y 6 meses.
- **Reportes**: el Markdown se renderiza con react-markdown, que no interpreta HTML crudo, y los enlaces se abren en otra pestaña con `noopener noreferrer nofollow`. Importa porque el texto lo redacta un modelo a partir de datos del equipo.
- **Carga diferida**: Recharts y el renderizador de Markdown pesaban casi todo el JavaScript (825 KB). Con `React.lazy` el paquete inicial quedó en 251 KB (78 KB comprimido); el detalle (404 KB) y los reportes (168 KB) se bajan al usarlos.
- **`web/construir.sh`**: usa el Node aislado de `datos/node` (o `PC_DOCTOR_NODE`), instala con `npm ci` si falta `node_modules` y compila a `web/frontend/dist/`. Sin sudo.
- **Textos**: español rioplatense, con mayúscula solo al inicio de cada frase (salvo nombres propios y de sensores).

#### Errores encontrados y corregidos
- Con React 19 ya no existe el espacio de nombres global `JSX` (error de tipos); se usa `ReactElement`.
- Choque de nombres entre un componente y un tipo `Estado`; el componente pasó a llamarse `Contenido`.
- Un estado sin uso en la vista de detalle.
- Dos errores de redacción que vi en las capturas: "1 paquetes más" (plural en `correlacion.py`) y "salió sin redactar porque límite de uso…" (ahora "Motivo: …"); y un "todavía" repetido en el aviso de diagnósticos.
- Con la API caída cada sección repetía su propio aviso amarillo y el mensaje salía en inglés ("Failed to fetch"); ahora hay un solo aviso global en español y las secciones no lo repiten.
- La banda del gráfico se veía tenue en el modo oscuro: subí su opacidad.
- Brave sin interfaz (`--headless=new --screenshot`) se colgaba en este equipo; las capturas se sacaron con la extensión de Chrome sobre los datos de prueba. Mi `pkill -f` volvió a cerrar mi propia shell (coincidía con el texto del comando) hasta que usé el truco `[p]atrón`.

#### Pruebas
- Compilación con `tsc` estricto sin errores; carga en el navegador real sin errores de consola.
- Recorrido visual con datos de prueba: tarjetas, detalle con gráfico (rangos y contextos), globo, rombos de fuera de lo habitual, enlace directo `/alerta/4` (baja a la sección y abre las causas), línea de tiempo, reportes con tabla, código, cita y enlace, limitaciones y entorno.
- **Actualización automática**: sin recargar, pasó de 18:44 a 18:45 con un segundo pedido a `/api/estado`.
- **Servidor caído y recuperación**: con la API apagada se conservan los datos y aparece un único aviso; al volver y pulsar "Actualizar" desaparece y se actualiza la hora.
- **Fuentes ausentes**: con la base de una versión anterior (sin 3 tablas) las secciones afectadas dicen "No disponible todavía" y el resto funciona; sin base, todas lo dicen; ninguna rompe la página.
- **Diseño angosto y modo oscuro**: se comprobaron aplicando a mano las reglas `@media` de la hoja de estilos (la extensión no pudo achicar la ventana real: su viewport era de 2560 px). Es una simulación fiel del CSS, pero no una ventana real de 420 px.
- Regresión: pruebas de las fases anteriores, API (0 fallos), API contra MCP (0 diferencias) y 384 peticiones concurrentes con escrituras simultáneas, todo sin errores.

#### Limitaciones
- Las capturas de `web/capturas/` son de los datos sintéticos, no de los reales (con los reales todas las tarjetas dirían "aprendiendo"); la 05 y la 06 son anteriores a la corrección de dos textos.
- No se probó en una pantalla táctil ni con lector de pantalla; solo se revisó la estructura accesible por código.
- Cada actualización de 60 s vuelve a pedir todas las secciones (unas 8 peticiones baratas), y la lectura en vivo con SMART se repite cada minuto con la página abierta (la caché es de 20 s). Es poco, pero es más que el recolector (cada 15 min).
- Sin base de datos, ocho secciones repiten el mismo aviso; es correcto pero redundante.
- La banda con el contexto "Todos" tiene escalones cuando el equipo cambia de contexto: es fiel a los datos, pero puede parecer discontinua.

### Fase 3 del dashboard: acceso (servicio, lanzador, PWA, enlaces directos, notificaciones con botón, tool del MCP)

#### Decisiones
- **`dashboard.py`** es el único lugar que sabe armar la URL de una sección, comprobar si el dashboard responde, arrancarlo y abrirlo. Lo usan el lanzador del menú, los botones de las notificaciones y la tool `abrir_dashboard` del MCP (ya son 23 tools). Acepta solo formas conocidas (`estado`, `alertas`, `linea-de-tiempo`, `reportes`, `limitaciones`, `entorno`, `alerta:N`, `hallazgo:N`, `componente:TIPO[:ID]`); cualquier otra cosa se rechaza, nunca se abre una URL arbitraria. Si el dashboard está apagado, lo arranca con `systemctl --user start pc-doctor-web.service` y espera hasta 15 s.
- **Servicio `systemd/pc-doctor-web.service`** (de usuario, `WantedBy=default.target` para que arranque con la sesión, `Restart=on-failure`, `RestartSec=5`, `Nice=10`, `MemoryMax=400M`; en reposo usa ~65 MB). Usa `uv run --frozen` para no resolver ni descargar nada al arrancar. **No** lleva `NoNewPrivileges` porque la lectura de SMART usa `sudo -n smartctl`. Validado con `systemd-analyze --user verify`. **No instalado: pendiente de aprobación del usuario.**
- **Lanzador `web/pc-doctor.desktop`** (con acciones "Ver las alertas" y "Ver los reportes"): su `Exec` llama a `dashboard.py abrir`, así que arranca el servicio si hace falta y después abre el navegador; si no puede, avisa con una notificación (sin terminal no habría otra forma de enterarse). Ruta absoluta de `/home/v` (los `Exec` no expanden `~` ni `%h`). Validado con `desktop-file-validate`. Se copiará a `~/.local/share/applications/` junto con el ícono. **No instalado.**
- **Ícono propio:** un pulso blanco sobre un cuadrado azul. `web/generar_iconos.py` (necesita Pillow) genera el SVG y los PNG de 180, 192 y 512 px, más una versión enmascarable de 512 con el pulso dentro de la zona segura.
- **PWA:** `manifest.webmanifest` (nombre, `display: standalone`, `start_url` y `scope` `/`, íconos de 192 y 512 px, uno enmascarable y el SVG, y atajos a alertas y reportes) con el tipo MIME correcto (`application/manifest+json`), `theme-color` para claro y oscuro e ícono en la cabecera. **Sin service worker, a propósito:** los datos tienen que ser siempre frescos y un caché los volvería viejos sin avisar. Si el navegador ofrece instalarla no depende de eso en Chrome y Edge actuales (no lo pude comprobar: ver limitaciones).
- **Enlaces directos:** además de `/alerta/{id}` y `/componente/{tipo}` (que ya funcionaban), se agregó `/hallazgo/{id}`, que abre la pestaña de hallazgos con ese hallazgo expandido (busca en 365 días).
- **Notificaciones con botón "Ver en el dashboard":**
  - Comprobé que GNOME Shell 46 soporta acciones (anuncia `actions` y `persistence`) y que `notify-send` 0.8.3 tiene `--action`.
  - Para recibir el clic hace falta un proceso vivo. El recolector termina enseguida y systemd mata lo que quede en su servicio, así que el escucha corre en una **unidad transitoria** (`systemd-run --user --collect`) con `RuntimeMaxSec=21600` (6 h): si nadie atiende la notificación, el escucha se cierra solo y el botón deja de funcionar. Tope de 10 escuchas vivos a la vez; pasado eso, las notificaciones salen sin botón.
  - Cada fuente pide su sección: salud abre **la alerta más grave** del aviso (`alerta:N`), seguridad el primer hallazgo (`hallazgo:N`), el reporte semanal `reportes`.
  - Al hacer clic, si el dashboard está apagado se arranca; si el servicio no está instalado o no arranca, sale una notificación simple que lo explica.
  - **Las notificaciones siguen funcionando igual con el dashboard apagado:** el botón es un extra. Se ofrece solo si la opción está activa, el escritorio lo soporta y hay cupo; en cualquier otro caso (o si `systemd-run` falla) sale la notificación de siempre, con el mismo contrato de retorno (False si no se pudo enviar, para reintentar).
  - Si la versión con botón falla dentro del escucha, este manda la simple: nunca se pierde un aviso por el botón.
  - **El botón está apagado por defecto** (`"boton_dashboard": false`) hasta que el usuario lo pruebe en su escritorio real; `uv run alertas.py --probar-boton` lo fuerza (esa prueba es real y se ve en pantalla).
- **Alternativa si el botón no sirviera en el escritorio real:** poner la dirección en el cuerpo de la notificación. GNOME no anuncia `body-hyperlinks`, así que habría que comprobar si la hace clicable.

#### Errores encontrados y corregidos
- **Detección de juegos con un juego real (Crimson Desert bajo Proton), que las pruebas sintéticas no podían mostrar:** el recolector veía **tres juegos en vez de uno**. `CrimsonDesert` salía de un `sh -c "…steam-launch-wrapper… CrimsonDesert.exe…"` (el envoltorio con toda la línea de lanzamiento en un argumento), `xalia` es un ayudante de Steam Input que corre dentro de Proton, y `Crimson Desert Enhanced` era el nombre correcto. Correcciones: un `sh -c "…"` se trata como envoltorio y no como programa; un proceso de Wine descendiente de `reaper` pertenece a un juego de Steam ya identificado; `xalia` se agregó a los ejecutables auxiliares. Comprobado con el juego real en ejecución (devuelve exactamente uno) y con los argumentos reales como pruebas nuevas. La base real no recibió sesiones falsas: el juego arrancó justo después de la corrida de las 19:01 y el código se corrigió antes de la siguiente.
- **Riesgo de pérdida de avisos:** el código del botón ya estaba en producción (el recolector usa el código del proyecto) antes de probarlo en el escritorio real, y con la temperatura alta era probable una alerta real. Se agregó el respaldo del escucha y se apagó el botón por defecto.
- Un `pkill` de las pruebas coincidió con mi propio comando (ya conocido); se usa por PID.
- Carrera en una prueba de la tool: `xdg-open` se lanza sin esperarlo y se leyó su registro antes de tiempo.

#### Pruebas (reemplazos de `notify-send`, `xdg-open`, `gdbus`, `systemd-run` y `systemctl`; un servidor HTTP mínimo hace de dashboard; nada se ve en pantalla)
- 16 comprobaciones de `url_de` (8 válidas, 8 inválidas: URL externas, `javascript:`, `//evil`, inyección, números enormes, ids largos).
- Notificaciones: botón y clic con el dashboard activo (abre `/alerta/4`, urgencia crítica conservada, una sola unidad con tope de vida); sin clic (no abre nada); el escritorio no anuncia acciones; `gdbus` falla; opción apagada; 10 escuchas vivos (y 9 todavía permiten el botón); `systemd-run` falla; sección inválida; sin sección (comportamiento de siempre, sin costo extra); `notify-send` roto (devuelve False); dashboard apagado al hacer clic (lo arranca, 0,9 s); servicio no instalado (avisa); título y mensaje con comillas, `$()`, saltos de línea, `%s`, HTML y caracteres no latinos llegan idénticos; la versión con botón falla (sale la simple); botón apagado por defecto y forzado.
- Cada fuente pide la sección correcta: salud → la alerta crítica entre dos; seguridad → el hallazgo.
- Tool `abrir_dashboard`: arranca el servicio, abre la URL correcta y rechaza secciones inválidas.
- Manifest: tipo MIME, 4 íconos con tamaños reales iguales a los declarados, requisitos de instalación (192, 512 y enmascarable) y `start_url` dentro del alcance. `/hallazgo/2` en el navegador: abre la pestaña y el hallazgo.
- Regresión: pruebas de las fases anteriores, API (0 fallos), API contra MCP (0 diferencias).

#### Limitaciones
- **El botón no se probó todavía en el escritorio real** (requiere hacer clic en una notificación verdadera): por eso está apagado por defecto. Tampoco sé cómo se comporta GNOME con el escucha: con `persistence` la notificación queda en la bandeja y el escucha espera hasta 6 h; si GNOME cerrara la notificación al vencer el aviso, el botón dejaría de responder antes.
- Un escucha vivo por notificación sin atender (hasta 6 h, ~20 MB cada uno, máximo 10).
- La instalación como app (PWA) no se pudo comprobar: la extensión de Chrome no permite disparar ni observar el aviso de instalación. El manifest cumple los requisitos; la instalación se hace desde el menú del navegador.
- El ícono del lanzador se tomará del SVG instalado en `~/.local/share/icons/hicolor/scalable/apps/`; algunos escritorios necesitan reiniciar la sesión para mostrarlo.

#### Instalación (aprobada por el usuario) y estado final de la Fase 3
- Instalados: `~/.config/systemd/user/pc-doctor-web.service` (habilitado y activo), `~/.local/share/applications/pc-doctor.desktop` y el ícono en `~/.local/share/icons/hicolor/scalable/apps/pc-doctor.svg` (con `update-desktop-database` y `gtk-update-icon-cache`).
- Verificado: escucha solo en `127.0.0.1:8787` (desde la IP de la LAN no responde), `Host` ajeno da 421, `/`, `/api/estado`, el manifest y `/alerta/1` responden 200, y con tus datos reales devuelve el estado en vivo. Consumo del servicio: 58 MB de RAM en total (cgroup).
- **No se hizo la prueba real del botón: la hace el usuario.** `uv run alertas.py --probar-boton` envía una notificación real con el botón. Si funciona, se activa con `"boton_dashboard": true` en `config.json` (o la pantalla de configuración de la Fase 4). Hasta entonces las notificaciones salen simples, como siempre.
- No se abrió el lanzador desde mi lado, para no abrir ventanas en tu pantalla sin que lo pidieras.

#### Ícono en el escritorio (pedido del usuario)
- Copia del lanzador en `~/Desktop/pc-doctor.desktop`, ejecutable y marcado como confiable (`gio set ... metadata::trusted true`; sin eso GNOME no deja abrirlo con doble clic). Usa la ruta absoluta del ícono SVG, que el escritorio resuelve con más seguridad que el nombre del tema. Es una copia de `web/pc-doctor.desktop`: si ese archivo cambia, hay que volver a copiarlo.

## Nivel nuevo 5: flujo de git automatizado (pedido del usuario, en fases)
El usuario subió el proyecto a GitHub (`origin/main`, un commit inicial) y pidió automatizar el flujo de cambios en 4 fases con parada y OK al final de cada una: suite de pruebas permanente, hook pre-commit, regla de commits en `CLAUDE.md` y GitHub Actions. **Excepción a la convención de archivos con punto, autorizada por el usuario:** `.gitignore`, `.git/`, `.github/` y lo que git necesite. Además: no usar `sudo`, no tocar la base real ni los servicios instalados.

### Fase 1: suite de pruebas permanente (`tests/`)
#### Decisiones
- **pytest 9.2 y pytest-cov 7.1** como dependencias de desarrollo (`uv add --dev`); `httpx` ya estaba (lo trae `mcp`) y lo usa el cliente de pruebas de FastAPI. Configuración en `pyproject.toml`: `testpaths`, `pythonpath`, dos marcadores y la cobertura. `uv run pytest` corre todo.
- **Se rescataron las pruebas de verdad, no se reescribieron de cero.** Las de las fases recientes estaban en el scratchpad; las de las primeras etapas (reglas de salud, línea base, deriva, SMART, migración, regresión) ya no existían como archivos, pero cada script que se ejecutó quedó en la transcripción de la conversación, así que se extrajeron de ahí. Las pruebas pasaron de scripts con `print` a funciones de pytest con fixtures y parámetros (los casos repetidos son ahora parametrizados: por ejemplo, 25 líneas de comandos de juegos o 23 parámetros inválidos de la API).
- **Aislamiento total, en `tests/conftest.py`, antes de importar cualquier módulo del proyecto:** carpeta de datos y `HOME` temporales (así `Path.home()` apunta a una carpeta vacía y nada lee `~/.steam`, `~/.local/bin/claude` ni la base real), `PATH` con los reemplazos de `tests/falsos/` al principio (`notify-send`, `systemd-run`, `systemctl`, `gdbus`, `xdg-open`, `claude`), puerto de pruebas 8795 (nunca el 8787 del dashboard real) y una barrera al iniciar la sesión que aborta todo si la carpeta de datos apuntara a la real. En cada prueba, `salud.leer_lecturas`, `actividad.detectar` y los juegos de Steam están reemplazados por datos sintéticos, salvo en las marcadas `local`.
- **Marcadores:** `local` (4 pruebas que leen sensores y procesos reales de esta PC; se saltean en CI con `-m "not local"`) y `lento` (189 pruebas que levantan procesos, esperan, crean repositorios git temporales o generan los datos sintéticos grandes; el pre-commit las saltea con `-m "not lento"`).
- **Datos sintéticos compartidos:** las pruebas de la API usan `web/datos_de_prueba.py`, que ahora acepta un segundo argumento con la cantidad de días (45 en las pruebas, 120 por defecto).
- **Una prueba específica contra regresiones de seguridad del reporte:** inspecciona el código fuente de cada tool que se le permite a `claude -p` y falla si alguna tiene un efecto (escribir, mover archivos, consultar online); y verifica que toda tool permitida exista en el servidor.
#### Qué quedó
- **385 pruebas** en 15 archivos: API (81), hook pre-commit (65), actividad (40), salud (30), dashboard (29), línea base (25), cuarentena (22), reporte (19), notificaciones (18), correlación (16), consultas y retención (15), SMART (9), historial (7), API contra MCP (6) y local (3; hay una cuarta marcada `local` dentro de las de actividad).
- **Tiempos:** suite completa 25,9 s; subconjunto rápido (`-m "not lento"`, el del pre-commit) 9,4 s con 196 pruebas; como en CI (`-m "not local"`) 381 pruebas en ~22 s. Cinco corridas completas seguidas (cuando eran 298): 5 de 5 sin fallar.
- **Cobertura total: 72 %** (2817 líneas, 780 sin cubrir). Muy bien cubiertos: `linea_base` 98 %, `correlacion` 96 %, `consultas` 95 %, `salud` 95 %, `web/api` 94 %, `reporte` 90 %, `server` 80 %.
- **No se tocó nada real:** después de la suite, los reportes y las copias de migración reales siguen en 1 y 1, no hay escuchas de notificaciones vivos, el dashboard y los timers siguen activos y no quedan carpetas temporales.
#### Errores del código que las pruebas encontraron y se corrigieron
- `parsear_smart` fallaba con JSON válido que no es un objeto (`null`, una lista): se perdían las lecturas de SMART de todos los discos en esa corrida.
- El dashboard mostraba un ventilador a 0 RPM **sin historia** como "parado: giraba antes", sin evidencia de que hubiera girado; ahora es "parado" solo si hay registro de que giró, y si no, "conector sin ventilador".
- Una prueba de la regla del ventilador detenido, escrita antes del arreglo de los conectores vacíos, ya no valía: se adaptó y se agregó el caso del conector vacío.
#### Problemas de las pruebas mismas
- Carrera entre pruebas: el servidor HTTP falso de una prueba seguía muriéndose cuando la siguiente lanzaba el suyo en el mismo puerto; la limpieza ahora espera a que el puerto quede libre.
- `httpx` normaliza los `..` de una URL antes de enviarla, así que `/api/reportes/../../etc/passwd` llegaba como `/etc/passwd`; la prueba ahora verifica que ninguna ruta filtre contenido del sistema.
- Mi propia comprobación usaba `grep` sobre la línea de resumen con `-q` doble y daba falsos fallos; se usa el código de salida.
#### Limitaciones (lo que la suite NO cubre)
- **`seguridad.py` 18 %, `reputacion.py` 25 % y `collector.py` 21 %:** el escáner de procesos y puertos, las consultas de reputación online y el hilo principal del recolector no tienen pruebas permanentes. Hay que dar datos de procesos y de red sintéticos y simular las consultas HTTP.
- **`server.py` 80 %:** sin pruebas siguen `revision_seguridad` y `marcar_hallazgo`. (`limpiar_descargas_viejas` y `restaurar_cuarentena`, las que mueven archivos del usuario, se cubrieron después: ver más abajo.)
- `db.py` 55 % (ayudas de hardware), `alertas.py` 58 % (la línea de comandos), `dashboard.py` 79 %.
- Las pruebas del recolector, de la lectura real de sensores y de SMART por `sudo` solo corren localmente (`local`).
- El aviso de deprecación de `starlette.testclient` con `httpx` está silenciado en `pyproject.toml`; hay que revisarlo cuando haya un reemplazo estable.

#### Pruebas de las tools que mueven archivos (a pedido del usuario, tras el resumen de la Fase 1)
- `tests/test_cuarentena.py`, 22 pruebas de `limpiar_descargas_viejas` y `restaurar_cuarentena`, en un `HOME` temporal: la simulación (el valor por defecto) no mueve nada; un archivo recién copiado no cuenta como viejo aunque su `mtime` sea de hace un año (la edad es el máximo de `mtime` y `ctime`); se agrupa por elemento de primer nivel y se acota a 20; al ejecutar se mueve a cuarentena con el contenido idéntico y queda registro en `cuarentena` y `acciones`; nunca se borra nada; dos corridas el mismo día no se pisan (`a.txt` y `a.1.txt`); nunca se tocan archivos fuera de Descargas (ni los de una carpeta de nombre parecido); los enlaces simbólicos no se siguen ni se mueven; restaurar devuelve el archivo idéntico, no pisa uno existente, recrea la carpeta si ya no está y da error con ids inexistentes, ya restaurados o sin archivo; el ciclo completo deja todo como estaba.
- Como el `ctime` no se puede falsear, para volver "viejos" a archivos recién creados se adelanta el reloj que usa solo el módulo del servidor, sin tocar el reloj del resto del programa.
- **Prueba de las pruebas:** se rompió el código a propósito de cuatro maneras y las pruebas detectaron tres (restaurar pisando lo existente, ejecutar en simulación, ignorar el `ctime`). La cuarta, seguir enlaces simbólicos, no se detectaba porque el código tiene **dos** barreras (`followlinks=False` y comprobar que la ruta real esté dentro de Descargas) y con una sola rota la otra protege; rompiendo las dos, la prueba falla.
- `conftest.py` ahora también vacía el `HOME` temporal antes de cada prueba (antes solo vaciaba la carpeta de datos).

### Fase 2: hook pre-commit (`scripts/pre-commit` y `scripts/instalar-hooks.sh`)
#### Decisiones
- **Hook en Python** (más fácil de probar y de leer que en shell), versionado en `scripts/pre-commit`. `scripts/instalar-hooks.sh` lo enlaza en `.git/hooks/pre-commit` con un enlace relativo, se puede repetir sin problema y, si ya había otro hook, lo guarda como `pre-commit.antes`. Ya está instalado en este repositorio.
- **Bloquea por nombre:** cualquier archivo `.db` (y `-wal`, `-shm`, copias como `doctor.db.antes-de-juego-…`, `.sqlite`), `config.json`, `web_token` y todo lo que esté bajo `datos/` (incluido el enlace simbólico `datos`).
- **Bloquea por contenido:** tokens de GitHub (`ghp_`, `gho_`…, `github_pat_`), claves de Anthropic, OpenAI, AWS, Slack y Google, claves privadas (`-----BEGIN … PRIVATE KEY-----`), `password=` (y `passwd`, `pwd`, `contraseña`) con un valor, y claves de API, secretos o tokens de 32 caracteres o más asignados a un nombre clave.
- **Bloquea por tamaño:** más de 1 MiB (1.048.576 bytes; justo 1 MiB pasa).
- **Bloquea si fallan las pruebas rápidas** (`uv run pytest -m "not lento"`, ~9 s). Si `uv` no está, bloquea con un mensaje claro. Los problemas de archivos se informan sin correr las pruebas.
- **Se revisa lo que realmente va al commit:** el contenido indexado (no el archivo de trabajo) y solo las líneas **agregadas**, con su número de línea, para no bloquear por cosas que ya estaban. Las bajas no se revisan (sacar un `.db` del repositorio es justo lo que hay que poder hacer). Los renombres cuentan como agregado.
- **Los secretos se muestran enmascarados** (los primeros 4 caracteres y el largo): el mensaje del hook no filtra el secreto a la terminal ni a los registros.
- **Ejemplos falsos a propósito:** una línea con `permitir-secreto` en un comentario se ignora, y solo esa línea.
- **Salida de emergencia:** `git commit --no-verify` sigue funcionando; `CLAUDE.md` pide no usarlo sin preguntar. La variable `PC_DOCTOR_HOOK_SIN_PRUEBAS=1` omite solo el paso de las pruebas y la usan las pruebas del propio hook.
- **Las 65 pruebas del hook** (`tests/test_hook.py`) usan repositorios git temporales: 13 nombres bloqueados, 10 formas de secreto, 13 casos que no deben bloquearse (código normal y nombres parecidos), solo líneas agregadas, enmascarado, índice contra árbol de trabajo, tamaño en el límite exacto, bajas, varios problemas juntos, pruebas rápidas que fallan o pasan (con un `uv` falso), sin `uv`, el instalador (idempotente, respalda otro hook) y `git commit` de punta a punta (bloquea lo malo, deja pasar lo bueno, `--no-verify`). Están marcadas `lento` (crean repositorios): corren en la suite completa y en CI, no en cada commit.
#### Errores encontrados y corregidos
- La prueba de autorrevisión (el hook revisa su propio código y las pruebas del hook) falló: **el hook bloqueaba mi propio archivo de pruebas**, que tiene contraseñas falsas a propósito. Se marcaron esas líneas con `permitir-secreto`.
- Esa misma prueba reveló un falso positivo real: en `"password: str\n"` la secuencia `\n` de un string de Python contaba como parte del valor. Ahora la barra invertida no forma parte del valor.
#### Limitaciones
- Las pruebas rápidas corren sobre el **árbol de trabajo**, no sobre el índice: con un commit parcial (`git add -p`) pueden pasar por cambios que no están en el commit. Es la limitación habitual de los hooks sin `git stash`.
- Solo conoce las formas de secreto de la lista; un secreto con otra forma (o dividido en partes) no se detecta. No reemplaza revisar lo que se sube.
- El hook se instala por clon: cada clon nuevo necesita `bash scripts/instalar-hooks.sh`.

### Fase 3: regla de commits en `CLAUDE.md`
- Se agregó la sección "Flujo de git" con las reglas pedidas (correr `uv run pytest` al terminar un cambio coherente; commit en español, imperativo, primera línea corta y, si hace falta, un párrafo con el porqué; prefijos `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`; el commit incluye la entrada de `BITACORA.md`; `git push` después; sin commit si las pruebas fallan; nunca `push --force`, `reset --hard` ni reescribir historial sin preguntar; mostrar `git log --oneline origin/main..HEAD` antes de cada push). Agregué por mi cuenta la línea `Co-Authored-By` al final del mensaje (la instrucción de atribución de las sesiones de Claude Code) y la mención del hook y de no usar `--no-verify` sin preguntar.
- Además se actualizó el resto de `CLAUDE.md`, que había quedado viejo: describía dos partes del sistema y 4 módulos; ahora lista las tres partes, todos los módulos, las convenciones del dashboard, la sección "Pruebas" (marcadores y las reglas de aislamiento que debe seguir una prueba nueva) y la excepción de los archivos con punto para git.

### Fase 4: GitHub Actions (`.github/workflows/pruebas.yml`)
- Dos trabajos en paralelo, en `ubuntu-24.04`, con `permissions: contents: read`, `persist-credentials: false`, límite de tiempo y cancelación de corridas viejas de la misma rama. Se dispara en cada push y pull request a `main`.
  - **Python:** instala `uv` 0.13.6 (la de desarrollo) con Python 3.12, `uv sync --frozen` (exactamente `uv.lock`) y `uv run pytest -m "not local"`.
  - **Frontend:** Node 24.22.2 (la de desarrollo), `npm ci` (exactamente `package-lock.json`) y `npm run build` (`tsc` estricto y `vite build`).
- **Actions fijadas por SHA de commit**, resuelto desde la API de GitHub y verificado contra el repositorio de cada action: `actions/checkout` v7.0.1 (`3d3c42e5…`, 17/07/2026), `astral-sh/setup-uv` v10.3.0 (`1c37ad07…`, 09/10/2026) y `actions/setup-node` v7.1.0 (`949feb24…`, 08/10/2026). Todas con más de 2 semanas; `setup-uv` v10.3.3 es de hoy y se descartó por reciente.
- **Simulación previa de CI:** copia limpia con solo los archivos que git versionaría, entorno mínimo (`env -i`), zona horaria UTC (la de GitHub; esta PC está en UTC-3) y `HOME` vacío: 381 pruebas pasan, y `npm ci` + `npm run build` compilan. Sin esto no habría forma de saber, antes de subir, si alguna prueba dependía de la máquina.
- **Limitación:** no se pudo probar en GitHub antes de subirlo; la verificación real es `gh run watch` tras el push.

#### Primera corrida de CI: falló una prueba (carrera entre pruebas) y su corrección
- **Qué pasó:** el primer push con el workflow dejó `main` en rojo: el frontend compiló, pero `test_sin_seccion_es_el_comportamiento_de_siempre…` vio 2 llamadas a `notify-send` en vez de 1. En esta PC pasaba siempre (385 de 385, y 5 corridas seguidas).
- **Causa:** una prueba anterior (`…se_puede_forzar`) lanza un escucha de notificación en segundo plano mediante el `systemd-run` falso; ese escucha escribía en el registro compartido *después* de que su prueba había terminado, y en un runner lento caía dentro de la prueba siguiente.
- **Reproducción antes de corregir:** con la CPU saturada (24 procesos de carga) la falla aparece sola: 1 de 12 corridas, con el mismo `assert (2 == 1)`.
- **Corrección:** `tests/conftest.py` mata y espera a cualquier proceso en segundo plano que una prueba haya dejado (el escucha `--con-boton` y los `notify-send` falsos), antes de vaciar el registro y al terminar cada prueba. Con la misma carga: 0 de 24 corridas fallan.
- **Lección:** la simulación previa de CI (copia limpia, entorno mínimo, UTC) no atrapó esto porque no simulaba un equipo lento; la verificación real es la corrida en GitHub. Un runner de CI es un buen detector de carreras.

## Nivel nuevo 6: memoria en tablas (pedido del usuario, en fases)
El usuario pidió mover la memoria dispersa (`CLAUDE.md`, `CHANGELOG.md`, `BITACORA.md`) a tablas de `doctor.db` consultables por el MCP, en 4 fases con parada y OK al final de cada una. Reglas: sin `sudo`, pruebas en base temporal, la base real solo se toca en la migración (Fase 3) y con copia previa, y no se borra ningún markdown hasta que el usuario confirme la migración.

### Fase 1: esquema y tools
#### Decisiones
- **`memoria.py`** concentra el esquema y la lógica de las cuatro tablas (`memoria`, `hechos_conocidos`, `bitacora`, `changelog`); `server.py` solo envuelve. Son 12 tools nuevas (ya son 35).
- **Las tablas no están en `db.ESQUEMA`:** `db.conectar()` lo aplica en cada corrida del recolector (cada 15 min, con el código del proyecto), y la base real no debe cambiar antes de la migración. Las tablas se crean al **escribir** (`asegurar()`); las lecturas devuelven vacío si no existen. Una prueba verifica que ninguna lectura crea tablas.
- **Búsqueda FTS5** (`unicode61 remove_diacritics 2`, tablas de contenido externo con triggers de sincronización) para `memoria` y también para `bitacora`. La consulta del usuario nunca llega cruda a FTS5: se reduce a palabras, cada una entre comillas y como prefijo; primero se exigen todas y, si no hay resultados, alcanza con alguna. Orden por relevancia (bm25) con más peso al tema/título.
- **Hechos conocidos:** `agregar_hecho_conocido` y `retirar_hecho_conocido` dicen en el docstring que solo se usan si el usuario lo pide en la conversación, y dejan constancia en `acciones`. `vence` es AAAA-MM-DD (no puede ser pasada); un hecho vencido deja de contar como activo. `aplica_a` se compara por segmentos (`sdb` aplica a `smart_crc:sdb/errores_crc`, pero `fan1` no aplica a `fan10`).
- **Nada se borra:** `olvidar` y `retirar_hecho_conocido` marcan como inactivo.
- **El reporte semanal** (`claude -p`) no puede usar ninguna de las tools nuevas todavía: las de escritura y las de memoria quedaron en `HERRAMIENTAS_PROHIBIDAS`. La Fase 2 le permitirá solo `hechos_conocidos`.
- **Desvíos pequeños respecto al pedido:** `changelog` tiene una columna opcional `titulo` (las entradas del archivo tienen título y no cabía en otro campo), `registrar_changelog` acepta ese `titulo` opcional y `recordar` acepta un `origen` opcional (por defecto `agente`).
#### Pruebas
- `tests/test_memoria.py`: esquema idempotente y perezoso, FTS sincronizado en insert/update/delete, búsqueda sin acentos ni mayúsculas, consultas hostiles (comillas, `NEAR`, inyección SQL, 5000 caracteres), validación de cada enumeración y largo, hechos por `aplica_a` y vencimiento, flujo del changelog y de punta a punta por las tools.
#### Errores encontrados
- FTS5 no admite un alias de tabla en `MATCH` ni en `bm25()`; se usa el nombre real de la tabla.
#### Limitaciones
- Todavía nada usa los hechos conocidos (Fase 2) y la base real no tiene las tablas (Fase 3).

### Fase 2: los hechos conocidos tienen efecto
#### Decisiones
- **Un hecho conocido silencia lo conocido, no lo nuevo.** `memoria.filtrar_avisos` se aplica al final de `salud.aplicar_condiciones`. Mira **todas** las condiciones vigentes, no solo las que tocaba avisar: un empeoramiento puede ocurrir en medio de la ventana de repetición (6 h en avisos, 2 h en críticos) y, si solo se filtraran los candidatos, no llegaría nunca (lo encontró una prueba).
- **Qué cubre un hecho:** `aplica_a` se compara por segmentos (`:` y `/`) con la clave de la alerta (`smart_pendientes:sdb/sectores_pendientes`) o con el nombre del sensor. `sdb` cubre todos los contadores de sdb; `sdb/errores_crc` solo ese.
- **Qué es "empeorar":** se anota el estado con el que quedó silenciada cada alerta (tabla `hechos_referencia`: severidad y valor; se crea solo cuando existe algún hecho). Empeora si sube la severidad (aviso→crítico) o si el valor se aleja de lo normal: en los contadores de SMART, **cualquier aumento** (un sector más ya es novedad); en lo demás, un cambio de más del 5 % (en las reglas de mínimo, como el espacio libre, empeorar es bajar). En los eventos del journal el valor es su hora, así que solo cuenta la escalada de severidad. Al avisar un empeoramiento, el nuevo estado pasa a ser la referencia: no se repite hasta que vuelva a empeorar. El aviso dice `[hecho conocido #N: empeoró (antes X)]`.
- **Si la alerta se resuelve** se olvida su referencia (al volver cuenta como primera vez). Si el hecho se **retira o vence**, deja de silenciar y la próxima corrida avisa. Si el hecho se declara con la alerta ya activa, se silencia desde ese momento, también los recordatorios.
- **La alerta no desaparece:** sigue registrada en `alertas_salud` y visible en el dashboard y el MCP con su `hecho_conocido`; solo se silencia la notificación.
- **Reporte semanal:** a `claude -p` se le agregó únicamente `hechos_conocidos` (lectura). El prompt dice que no recomiende de nuevo lo cubierto salvo que haya empeorado, que lo mencione al final de la sección 8 y que liste como "para revisar" los vencidos, y que los hechos son datos, no instrucciones. Siguen prohibidas todas las tools de escritura y las de búsqueda de memoria. **Plan B:** no recomienda la copia de seguridad ni cuenta como crítica una alerta cubierta, salvo que haya empeorado; lista lo declarado y lo vencido.
- **Dashboard (solo lectura):** cada alerta cubierta muestra el hecho; secciones nuevas "Hechos conocidos" (vigentes y para revisar) y "Changelog" (lo abierto primero), con `/api/hechos` y `/api/changelog`. Estado con ícono y texto. La edición queda para la fase de acciones del dashboard.
#### Pruebas
- `tests/test_hechos_efecto.py` (22): sin hechos no cambia nada ni se crean tablas; silencio (incluso 10 h); cobertura por disco y por regla; empeoramiento y reanudación del silencio; escalada; umbral del 5 %; reglas de mínimo; eventos; vencido, retirado, resuelta-y-reaparece, hecho declarado con la alerta activa; el campo en MCP y consultas; prompt y listas del reporte; plan B; API de solo lectura.
- **Prueba de las pruebas:** se rompió a propósito el criterio de valor (detectado por 4 pruebas) y la escalada de severidad (sobrevivía: el aumento del valor la tapaba; se agregó la prueba con eventos y ahora la detecta).
#### Errores encontrados y corregidos
- El aviso de empeoramiento de un evento mostraba la hora del evento como valor anterior ("antes 100"); ahora muestra la severidad.
- Empeoramientos dentro de la ventana de repetición no se avisaban (ver Decisiones).
#### Limitaciones
- **El dashboard no se vio en un navegador:** el frontend compila (`tsc` y `vite build` a una carpeta temporal) y la API está probada, pero el servicio instalado sigue con el código viejo hasta reiniciarlo y reconstruir `dist/`.
- La referencia de un valor con tolerancia del 5 % puede dejar pasar un empeoramiento lento y gradual (cada paso menor al 5 % del valor anotado); los contadores de SMART no tienen ese problema.
- Los hechos se declaran solo desde la conversación (tools del MCP); el dashboard todavía no edita.
- No hay hechos cargados en la base real (Fase 3: se proponen, los elegís vos).
