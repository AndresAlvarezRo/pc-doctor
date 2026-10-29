# Bitácora de pc-doctor

> Archivo **generado** desde la tabla `bitacora` de `doctor.db` con `uv run memoria.py --exportar` (el hook pre-commit lo regenera). **No se edita a mano**: los cambios se hacen con `registrar_bitacora` y se vuelve a exportar.

Registro cronológico de las decisiones del proyecto. Cada entrada indica su fecha y su tipo.

## Construcción inicial (2026-10-28)

### Prerequisitos
_2026-10-28 · nota_
<!-- entrada {"id":1,"seccion":"Construcción inicial (2026-10-28)","titulo":"Prerequisitos","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":1,"tipo":"nota","vigencia":"historica","fecha":"2026-10-28","resumen":"Estaban `uv` 0.13.6, `python3` 3.12.3, `sensors`, `lshw`, `journalctl`, `flatpak`, `snap` y `claude`","modulos":["salud"]} -->
- Estaban `uv` 0.13.6, `python3` 3.12.3, `sensors`, `lshw`, `journalctl`, `flatpak`, `snap` y `claude`. Faltaba `nvidia-smi`, que es opcional. No hizo falta instalar nada con `sudo`.
  <!-- item {"id":2,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Carpeta de descargas real: `~/Downloads` (no existe `~/Descargas`)","modulos":["sistema"],"archivos":["~/Descargas","~/Downloads"]} -->
- Carpeta de descargas real: `~/Downloads` (no existe `~/Descargas`).

### Estructura y datos
_2026-10-28 · nota_
<!-- entrada {"id":2,"seccion":"Construcción inicial (2026-10-28)","titulo":"Estructura y datos","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":3,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Base de datos fuera del repo: `~/.local/share/pc-doctor/doctor.db`, como se pidió","modulos":["datos","sistema"],"archivos":["~/.local/share/pc-doctor/doctor.db"]} -->
- **Base de datos fuera del repo:** `~/.local/share/pc-doctor/doctor.db`, como se pidió. Así el repo queda limpio y los datos no se versionan por error.
  <!-- item {"id":4,"tipo":"invariante","vigencia":"vigente","fecha":"2026-10-28","resumen":"Timestamps como epoch UTC (INTEGER); la hora local se calcula solo al mostrar","modulos":["datos"]} -->
- **Timestamps como epoch UTC (INTEGER):** se comparan y ordenan fácil, y los índices por `ts` rinden. La conversión a hora local se hace solo al mostrar.
  **(invariante)**
  <!-- item {"id":5,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"`metricas_diarias` con clave (workspace_id, dia): se llena solo al aplicar la retención (resumir y luego borrar lo de…","modulos":["datos"]} -->
- **`metricas_diarias` con clave (workspace_id, dia):** se llena solo al aplicar la retención (resumir y luego borrar lo de más de 30 días). `historial` mezcla esos promedios diarios con las métricas crudas cuando el rango los incluye.
  <!-- item {"id":6,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Snapshot de entorno solo si cambia el hash de kernel + driver GPU + lista de paquetes (apt, flatpak, snap)","modulos":["datos"]} -->
- **Snapshot de entorno solo si cambia el hash** de kernel + driver GPU + lista de paquetes (apt, flatpak, snap). Evita llenar la base con copias idénticas de ~2500 paquetes cada 15 minutos.

### Recolector
_2026-10-28 · nota_
<!-- entrada {"id":3,"seccion":"Construcción inicial (2026-10-28)","titulo":"Recolector","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":7,"tipo":"invariante","vigencia":"vigente","fecha":"2026-10-28","resumen":"Cada paso del recolector está aislado y los comandos externos pasan por db.ejecutar(): si falla, se loguea y se sigue","modulos":["datos"]} -->
- **Cada paso está aislado:** si falla uno (por ejemplo `journalctl`), se loguea y siguen los demás. Los comandos externos pasan por `db.ejecutar()`, que devuelve `None` si el comando no existe, falla o excede el timeout.
  **(invariante)**
  <!-- item {"id":8,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Eventos del journal: `journalctl -p err \u002d\u002dsince @\u003cúltimo ts\u003e -n 50`. La primera corrida mira solo la última hora","modulos":["datos"]} -->
- **Eventos del journal:** `journalctl -p err --since @<último ts> -n 50`. La primera corrida mira solo la última hora.

### Servidor MCP
_2026-10-28 · nota_
<!-- entrada {"id":4,"seccion":"Construcción inicial (2026-10-28)","titulo":"Servidor MCP","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":9,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"`mcp` fijado a `\u003c2`: `uv` resolvía mcp 2.x, donde `FastMCP` pasó a llamarse `MCPServer` y `mcp.server.fastmcp` ya no…","modulos":["mcp"]} -->
- **`mcp` fijado a `<2`:** `uv` resolvía mcp 2.x, donde `FastMCP` pasó a llamarse `MCPServer` y `mcp.server.fastmcp` ya no existe. Se pineó 1.x para usar FastMCP como se pidió.
  <!-- item {"id":10,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Respuestas compactas: las listas se recortan a 20 elementos y `historial` pasa a resumen (mín, máx, promedio…","modulos":["datos"]} -->
- **Respuestas compactas:** las listas se recortan a 20 elementos y `historial` pasa a resumen (mín, máx, promedio, tendencia) con más de 60 puntos.
  <!-- item {"id":11,"tipo":"invariante","vigencia":"vigente","fecha":"2026-10-28","resumen":"La cuarentena nunca borra: solo mueve archivos regulares de Descargas y no sigue symlinks","modulos":["mcp"],"prueba":"tests/test_cuarentena.py::test_ejecutar_nunca_borra_ningun_archivo"} -->
- **Seguridad de la cuarentena:**
  - Solo se mueven archivos regulares dentro de la carpeta de descargas.
  - Se ignoran los symlinks y se comprueba que la ruta real siga dentro de esa carpeta.
  - Nunca se borra nada.
  - Restaurar no pisa un archivo que ya exista en la ruta original.
  **(invariante · prueba: tests/test_cuarentena.py::test_ejecutar_nunca_borra_ningun_archivo)**

### Hardware agnóstico a fabricante (pedido del usuario)
_2026-10-28 · nota_
<!-- entrada {"id":5,"seccion":"Construcción inicial (2026-10-28)","titulo":"Hardware agnóstico a fabricante (pedido del usuario)","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":12,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"GPU: se detecta con `lspci -nnk` y el proveedor sale del ID PCI (NVIDIA 10de, AMD 1002/1022, Intel 8086, más virtuales…","modulos":["datos"]} -->
- **GPU:** se detecta con `lspci -nnk` y el proveedor sale del ID PCI (NVIDIA 10de, AMD 1002/1022, Intel 8086, más virtuales y ARM), no del texto de la descripción. Un ID desconocido se informa como `desconocido (xxxx)`.
  <!-- item {"id":13,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Versión del driver, por fabricante: NVIDIA: `nvidia-smi` si existe; si no, el módulo","modulos":["datos"]} -->
- **Versión del driver, por fabricante:**
  - NVIDIA: `nvidia-smi` si existe; si no, el módulo.
  - AMD e Intel: versión del módulo si la expone. Si es in-tree se informa `kernel X (in-tree)`.
  - Mesa: se agrega la versión de `libgl1-mesa-dri` para drivers que no son `nvidia`.
  <!-- item {"id":14,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"CPU: se usa `vendor_id` de `/proc/cpuinfo` y, si falta (ARM), `lscpu`. Se guarda también la arquitectura","modulos":["datos"]} -->
- **CPU:** se usa `vendor_id` de `/proc/cpuinfo` y, si falta (ARM), `lscpu`. Se guarda también la arquitectura.
  <!-- item {"id":15,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Probado en esta máquina: Ryzen 5 5600X + AMD Navi 33 (`amdgpu`, in-tree), 3 discos y placa ASUS PRIME B550-PLUS","modulos":["datos"]} -->
- Probado en esta máquina: Ryzen 5 5600X + AMD Navi 33 (`amdgpu`, in-tree), 3 discos y placa ASUS PRIME B550-PLUS.

### Visibilidad total en el explorador de archivos (pedido del usuario)
_2026-10-28 · nota_
<!-- entrada {"id":6,"seccion":"Construcción inicial (2026-10-28)","titulo":"Visibilidad total en el explorador de archivos (pedido del usuario)","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":16,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Lo único oculto era `.venv`. Se agregó el symlink visible `venv -\u003e .venv`","modulos":["mcp"]} -->
- Lo único oculto era `.venv`. Se agregó el symlink visible `venv -> .venv`. No se renombró, para que el comando de registro del MCP y `uv` sigan funcionando sin variables de entorno extra.
  <!-- item {"id":17,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Se agregó el symlink `datos -\u003e ~/.local/share/pc-doctor` para ver la base y la cuarentena desde el proyecto","modulos":["datos"]} -->
- Se agregó el symlink `datos -> ~/.local/share/pc-doctor` para ver la base y la cuarentena desde el proyecto. Los datos siguen físicamente fuera del repo.
  <!-- item {"id":18,"tipo":"nota","vigencia":"superada","fecha":"2026-10-28","resumen":"Convención: no crear archivos ni carpetas con punto dentro del proyecto","modulos":["datos"],"reemplazada_por":270,"motivo":"El proyecto sube a git: se autorizó la excepción para .gitignore, .git/, .github/ y lo que git necesite."} -->
- Convención: no crear archivos ni carpetas con punto dentro del proyecto.
  (superada por #270: El proyecto sube a git: se autorizó la excepción para .gitignore, .git/, .github/ y lo que git necesite.)

### systemd (archivos creados, **todavía sin instalar**)
_2026-10-28 · nota_
<!-- entrada {"id":7,"seccion":"Construcción inicial (2026-10-28)","titulo":"systemd (archivos creados, **todavía sin instalar**)","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":19,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"`systemd/pc-doctor.service`: `Type=oneshot`, ejecuta `uv run \u002d\u002ddirectory %h/Desktop/Practicas-IA/pc-doctor…","modulos":["infra"],"archivos":["systemd/pc-doctor.service"]} -->
- `systemd/pc-doctor.service`: `Type=oneshot`, ejecuta `uv run --directory %h/Desktop/Practicas-IA/pc-doctor collector.py`. Se usa la ruta absoluta de `uv` porque systemd --user no hereda el PATH del shell. Se agregaron `Nice=10` (que no moleste al trabajar) y `TimeoutStartSec=120`.
  <!-- item {"id":20,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"`systemd/pc-doctor.timer`: `OnBootSec=2min`, `OnUnitActiveSec=15min`, `Persistent=true`","modulos":["infra"],"archivos":["systemd/pc-doctor.timer"]} -->
- `systemd/pc-doctor.timer`: `OnBootSec=2min`, `OnUnitActiveSec=15min`, `Persistent=true`.
  <!-- item {"id":21,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Nota: `Persistent=true` solo tiene efecto con `OnCalendar=`","modulos":["datos"]} -->
- Nota: `Persistent=true` solo tiene efecto con `OnCalendar=`. Con los disparadores actuales es inofensivo y se dejó porque se pidió.
  <!-- item {"id":22,"tipo":"nota","vigencia":"superada","fecha":"2026-10-28","resumen":"Los archivos viven en el proyecto. La instalación a `~/.config/systemd/user/` espera la aprobación del usuario","modulos":["infra","sistema"],"archivos":["~/.config/systemd/user/"],"reemplazada_por":23,"motivo":"Las unidades se instalaron y el timer se activó con la aprobación del usuario."} -->
- Los archivos viven en el proyecto. La instalación a `~/.config/systemd/user/` espera la aprobación del usuario.
  (superada por #23: Las unidades se instalaron y el timer se activó con la aprobación del usuario.)

### Instalación y activación (Paso 6, aprobada por el usuario)
_2026-10-28 · nota_
<!-- entrada {"id":8,"seccion":"Construcción inicial (2026-10-28)","titulo":"Instalación y activación (Paso 6, aprobada por el usuario)","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":23,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Se copiaron las unidades a `~/.config/systemd/user/` y se ejecutó `enable \u002d\u002dnow pc-doctor.timer`","modulos":["infra","sistema"],"archivos":["~/.config/systemd/user/"]} -->
- Se copiaron las unidades a `~/.config/systemd/user/` y se ejecutó `enable --now pc-doctor.timer`.
  <!-- item {"id":24,"tipo":"nota","vigencia":"historica","fecha":"2026-10-28","resumen":"Al activarse, el timer disparó una corrida inmediata (12:56). La siguiente quedó a +15 min","modulos":["datos"]} -->
- Al activarse, el timer disparó una corrida inmediata (12:56). La siguiente quedó a +15 min. La corrida manual de verificación fue la segunda.

### Registro del MCP (Paso 7)
_2026-10-28 · nota_
<!-- entrada {"id":9,"seccion":"Construcción inicial (2026-10-28)","titulo":"Registro del MCP (Paso 7)","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":25,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"`claude mcp add pc-doctor -s user \u002d\u002d uv run \u002d\u002ddirectory ~/Desktop/Practicas-IA/pc-doctor server.py`","modulos":["mcp"]} -->
- `claude mcp add pc-doctor -s user -- uv run --directory ~/Desktop/Practicas-IA/pc-doctor server.py`. `claude mcp list` lo muestra como ✔ Connected.

### Verificación (Paso 8)
_2026-10-28 · prueba_
<!-- entrada {"id":10,"seccion":"Construcción inicial (2026-10-28)","titulo":"Verificación (Paso 8)","fecha":"2026-10-28","tipo":"prueba"} -->

<!-- item {"id":26,"tipo":"prueba","vigencia":"historica","fecha":"2026-10-28","resumen":"Corrida manual del recolector: 1,9 s","modulos":["datos"]} -->
- Corrida manual del recolector: 1,9 s. Filas resultantes: workspace 1, snapshot_entorno 1, hardware 7, software 2448, metricas 2, top_procesos 10, eventos 0, acciones 0, cuarentena 0, metricas_diarias 0.
  <!-- item {"id":27,"tipo":"prueba","vigencia":"historica","fecha":"2026-10-28","resumen":"La segunda corrida no creó snapshot porque el hash no cambió: la lógica de deduplicación funciona","modulos":["datos"]} -->
- La segunda corrida no creó snapshot porque el hash no cambió: la lógica de deduplicación funciona.
  <!-- item {"id":28,"tipo":"prueba","vigencia":"historica","fecha":"2026-10-28","resumen":"Eventos = 0 se contrastó con `journalctl -p err \u002d\u002dsince -24h`, que también da 0 líneas. No es un bug","modulos":["datos"]} -->
- Eventos = 0 se contrastó con `journalctl -p err --since -24h`, que también da 0 líneas. No es un bug.
  <!-- item {"id":29,"tipo":"prueba","vigencia":"historica","fecha":"2026-10-28","resumen":"Detectado: la máquina es Zorin OS 18.1 (kernel 7.0), no 17 como se supuso","modulos":["sistema"],"archivos":["/etc/os-release"]} -->
- Detectado: la máquina es **Zorin OS 18.1** (kernel 7.0), no 17 como se supuso. No afecta al código, que lee `/etc/os-release`.
  <!-- item {"id":30,"tipo":"prueba","vigencia":"historica","fecha":"2026-10-28","resumen":"Detectado: `Tctl` de la CPU marcó ~85 °C justo después de correr el recolector (la GPU estaba a 55 °C)","modulos":["datos"]} -->
- Detectado: `Tctl` de la CPU marcó ~85 °C justo después de correr el recolector (la GPU estaba a 55 °C). Probablemente fue un pico por la carga de `uv`. Queda para vigilar con `historial("temp_cpu", ...)` cuando haya más datos.

### Ajuste a `limpiar_descargas_viejas` tras la primera simulación
_2026-10-28 · nota_
<!-- entrada {"id":11,"seccion":"Construcción inicial (2026-10-28)","titulo":"Ajuste a `limpiar_descargas_viejas` tras la primera simulación","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":31,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Problema: la simulación listó 20.768 archivos, casi todos de una carpeta descomprimida de drivers, con rutas…","modulos":["datos"]} -->
- Problema: la simulación listó 20.768 archivos, casi todos de una carpeta descomprimida de drivers, con rutas larguísimas.
  <!-- item {"id":32,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Decisión 1: la salida se agrupa por elemento de primer nivel (archivos y MB por carpeta o archivo suelto)","modulos":["datos"]} -->
- Decisión 1: la salida se agrupa **por elemento de primer nivel** (archivos y MB por carpeta o archivo suelto). Se mantiene el movimiento archivo por archivo y el registro individual en `cuarentena` y `acciones`, como pidió el usuario.
  <!-- item {"id":33,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Decisión 2: la edad del archivo es `max(mtime, ctime)`","modulos":["datos"]} -->
- Decisión 2: la edad del archivo es `max(mtime, ctime)`. Un archivo recién descomprimido o copiado conserva un `mtime` viejo, pero su `ctime` es reciente. Así no se marca como "viejo" algo que llegó hace poco. La regla solo puede excluir más archivos, nunca menos, por lo que es más conservadora.
  <!-- item {"id":34,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"En esta máquina el resultado no cambió: 20.768 archivos (424 MB) son viejos también por `ctime`","modulos":["datos"]} -->
- En esta máquina el resultado no cambió: 20.768 archivos (424 MB) son viejos también por `ctime`.
  <!-- item {"id":35,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"Advertencia: una ejecución real sobre este resultado movería esos archivos uno por uno y generaría ~20.000 filas en…","modulos":["datos"]} -->
- Advertencia: una ejecución real sobre este resultado movería esos archivos uno por uno y generaría ~20.000 filas en `cuarentena` y en `acciones`. Antes de ejecutar conviene revisar la simulación.

### Documentación
_2026-10-28 · nota_
<!-- entrada {"id":12,"seccion":"Construcción inicial (2026-10-28)","titulo":"Documentación","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":36,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Se escribió `README.md`: qué es, instalación, cómo desactivar el timer y cómo restaurar la cuarentena","modulos":["datos"],"archivos":["README.md"]} -->
- Se escribió `README.md`: qué es, instalación, cómo desactivar el timer y cómo restaurar la cuarentena.

### Regla de changelog de la PC (pedido del usuario)
_2026-10-28 · nota_
<!-- entrada {"id":13,"seccion":"Construcción inicial (2026-10-28)","titulo":"Regla de changelog de la PC (pedido del usuario)","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":37,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Pedido: que cada vez que se revise algo del funcionamiento de la PC (errores, soluciones, cambios) se registre en un…","modulos":["memoria"]} -->
- Pedido: que cada vez que se revise algo del funcionamiento de la PC (errores, soluciones, cambios) se registre en un changelog dentro de pc-doctor, para mantener el contexto del equipo y su identidad siempre actualizados.
  <!-- item {"id":38,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Se creó `CHANGELOG.md` con dos partes: la tabla Identidad actual, que se reescribe cuando algo cambia (SO, kernel…","modulos":["memoria"],"archivos":["CHANGELOG.md"]} -->
- Se creó `CHANGELOG.md` con dos partes: la tabla **Identidad actual**, que se reescribe cuando algo cambia (SO, kernel, GPU/driver, RAM, discos, paquetes), y **Entradas**, cronológicas (de la más nueva a la más vieja) con tipo, detalle y estado (abierto o resuelto). Se sembró con los datos reales de esta máquina y la observación de la temperatura de CPU.
  <!-- item {"id":39,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Se agregó la regla como instrucción en dos lugares: `~/.claude/CLAUDE.md` (nivel usuario, archivo nuevo): como el MCP…","modulos":["memoria"],"archivos":["CLAUDE.md","~/.claude/CLAUDE.md"]} -->
- Se agregó la regla como instrucción en dos lugares:
  - `~/.claude/CLAUDE.md` (nivel usuario, archivo nuevo): como el MCP se usa desde cualquier carpeta, la regla debe cargarse en cualquier sesión de Claude Code y no solo dentro de pc-doctor.
  - `CLAUDE.md` del proyecto: para que quede documentada junto al código.
  <!-- item {"id":40,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Interpretación: \"rule en el modelo local\" se entendió como una instrucción persistente de Claude Code (CLAUDE.md)","modulos":["memoria"]} -->
- Interpretación: "rule en el modelo local" se entendió como una instrucción persistente de Claude Code (CLAUDE.md). La regla usa la ruta absoluta del changelog.
  <!-- item {"id":41,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Diferencia con la bitácora: `BITACORA.md` registra decisiones de diseño del proyecto","modulos":["memoria"],"archivos":["BITACORA.md","CHANGELOG.md"]} -->
- Diferencia con la bitácora: `BITACORA.md` registra decisiones de diseño del proyecto; `CHANGELOG.md` registra el estado y la historia de la PC.

### Perfil de energía en lugar de `schedutil` (pedido del usuario)
_2026-10-28 · nota_
<!-- entrada {"id":14,"seccion":"Construcción inicial (2026-10-28)","titulo":"Perfil de energía en lugar de `schedutil` (pedido del usuario)","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":42,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Pedido: pasar el governor a `schedutil`","modulos":["datos"]} -->
- Pedido: pasar el governor a `schedutil`. Verificado: con `amd-pstate-epp` el kernel solo ofrece `performance` y `powersave`, así que `schedutil` no es posible en este equipo.
  <!-- item {"id":43,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Decisión: aplicar el equivalente de la intención (dejar de forzar frecuencias máximas) con `powerprofilesctl set…","modulos":["sistema"]} -->
- Decisión: aplicar el equivalente de la intención (dejar de forzar frecuencias máximas) con `powerprofilesctl set balanced`. El governor lo fijaba el perfil de energía del sistema. No requiere `sudo`, persiste entre reinicios y se revierte con `powerprofilesctl set performance`. Resultado: governor `powersave` + EPP `balance_performance`.

### Módulo de seguridad: mineros, keyloggers, fantasmas y red (pedido del usuario)
_2026-10-28 · nota_
<!-- entrada {"id":15,"seccion":"Construcción inicial (2026-10-28)","titulo":"Módulo de seguridad: mineros, keyloggers, fantasmas y red (pedido del usuario)","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":44,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Pedido: saber si hay procesos de minería de criptomonedas, keyloggers, procesos fantasma o escuchas raras","modulos":["datos","seguridad"]} -->
- Pedido: saber si hay procesos de minería de criptomonedas, keyloggers, procesos fantasma o escuchas raras; guardarlo en tablas e incluirlo en el chequeo de cada 15 minutos junto con alguna base de datos online.
  <!-- item {"id":45,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Nuevo `seguridad.py`, usado por el recolector y por el servidor MCP","modulos":["seguridad"],"archivos":["seguridad.py"]} -->
- **Nuevo `seguridad.py`**, usado por el recolector y por el servidor MCP. Se agregaron tres tablas al esquema: `hallazgos_seguridad`, `escuchas` y `listas_seguridad`.
  <!-- item {"id":46,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Detecciones: Mineros: nombres conocidos (xmrig, minerd, kinsing, etc.), argumentos típicos (`stratum+tcp://`…","modulos":["seguridad"]} -->
- **Detecciones:**
  - Mineros: nombres conocidos (xmrig, minerd, kinsing, etc.), argumentos típicos (`stratum+tcp://`, `--donate-level`, randomx), dominios de pools en la línea de comandos y conexiones a puertos de pool.
  - Fantasmas: ejecutables en `/tmp` o `/dev/shm`, binarios borrados que siguen vivos, procesos que imitan hilos del kernel, nombres ocultos y `LD_PRELOAD` hacia rutas temporales.
  - Keyloggers: nombres conocidos y procesos que tienen abierto `/dev/input/event*` fuera de una lista de lectores legítimos.
  - Red: puertos TCP accesibles desde la red, terminales web sin autenticación y conexiones a IPs de botnets.
  <!-- item {"id":47,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Listas online usadas: Feodo Tracker (IPs de C2, `abuse.ch`) y NoCoin (312 dominios de minado, GitHub)","modulos":["git","seguridad"]} -->
- **Listas online usadas:** Feodo Tracker (IPs de C2, `abuse.ch`) y NoCoin (312 dominios de minado, GitHub). Descubierto al probar: las listas de CoinBlocker en GitLab piden login, algunas URLs de GitHub y de URLhaus devuelven 404/410, y ThreatFox/MalwareBazaar exigen clave de API. Por eso las firmas de pools y mineros también viven en el código.
  <!-- item {"id":48,"tipo":"decision","vigencia":"superada","fecha":"2026-10-28","resumen":"Privacidad: las listas solo se descargan (máximo 1 vez cada 24 h, timeout de 10 s, tope de 5 MB, con copia previa si…","modulos":["datos"],"reemplazada_por":64,"motivo":"Solo la parte «no se consultan hashes online»: ahora se consulta online únicamente el hash de ejecutables sospechosos."} -->
- **Privacidad:** las listas solo se descargan (máximo 1 vez cada 24 h, timeout de 10 s, tope de 5 MB, con copia previa si falla). No se envía nada de esta máquina a ningún servicio; no se consultan hashes de ejecutables online por ese motivo.
  (superada por #64: Solo la parte «no se consultan hashes online»: ahora se consulta online únicamente el hash de ejecutables sospechosos.)
  <!-- item {"id":49,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Deduplicación: cada hallazgo tiene una huella (categoría, regla, nombre y ruta o puerto, sin el pid) y se guarda una…","modulos":["seguridad"]} -->
- **Deduplicación:** cada hallazgo tiene una huella (categoría, regla, nombre y ruta o puerto, sin el pid) y se guarda una sola fila con `veces` y `ultima_vez`. Así el timer no genera ~96 filas por día por el mismo hallazgo. El estado `falso_positivo` o `revisado` se conserva si reaparece.
  <!-- item {"id":50,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Corre sin root: no ve los descriptores de archivo de procesos de otros usuarios (45 de 450 en esta máquina) ni detecta…","modulos":["datos"]} -->
- **Corre sin root:** no ve los descriptores de archivo de procesos de otros usuarios (45 de 450 en esta máquina) ni detecta rootkits. Queda documentado en las respuestas de las tools y en el README.
  <!-- item {"id":51,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Validación: se simularon un `sleep` renombrado como `xmrig` en `/tmp`, otro con argumentos…","modulos":["datos"]} -->
- **Validación:** se simularon un `sleep` renombrado como `xmrig` en `/tmp`, otro con argumentos `stratum+tcp://pool.minexmr.com` y se detectaron los tres casos. Los procesos y archivos de prueba se eliminaron y no se guardaron en la base.
  <!-- item {"id":52,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Ajustes tras el primer escaneo real: falso positivo del overlay de Steam (`LD_PRELOAD` desde `/tmp`) excluido","modulos":["seguridad"]} -->
- **Ajustes tras el primer escaneo real:** falso positivo del overlay de Steam (`LD_PRELOAD` desde `/tmp`) excluido. Se agregó la regla `shell_web_sin_auth` al descubrir que `ttyd` expone un `bash` sin credenciales en `0.0.0.0:7681`.
  <!-- item {"id":53,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Nuevas tools MCP (13 en total): `revision_seguridad()`, `hallazgos_seguridad(estado, dias)`, `marcar_hallazgo(id…","modulos":["mcp","seguridad"]} -->
- **Nuevas tools MCP (13 en total):** `revision_seguridad()`, `hallazgos_seguridad(estado, dias)`, `marcar_hallazgo(id, estado)` y `puertos_en_escucha()`.
  <!-- item {"id":54,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Costo en el recolector: la corrida completa pasó de 1,9 s a ~2,0 s","modulos":["datos"]} -->
- Costo en el recolector: la corrida completa pasó de 1,9 s a ~2,0 s.
  <!-- item {"id":55,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"No se tocó ningún servicio: la exposición de `ttyd` y `fluidsynth` se informa en `CHANGELOG.md` y la decisión es del…","modulos":["memoria","sistema"],"archivos":["CHANGELOG.md"]} -->
- No se tocó ningún servicio: la exposición de `ttyd` y `fluidsynth` se informa en `CHANGELOG.md` y la decisión es del usuario.

### ttyd y fluidsynth fuera de la LAN (pedido del usuario)
_2026-10-28 · nota_
<!-- entrada {"id":16,"seccion":"Construcción inicial (2026-10-28)","titulo":"ttyd y fluidsynth fuera de la LAN (pedido del usuario)","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":56,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Pedido: dejar `ttyd` y `fluidsynth` solo en localhost","modulos":["sistema"]} -->
- Pedido: dejar `ttyd` y `fluidsynth` solo en localhost.
  <!-- item {"id":57,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"ttyd: servicio de usuario `centro-hogar-ttyd.service`","modulos":["infra","sistema"]} -->
- **ttyd:** servicio de usuario `centro-hogar-ttyd.service`; se cambió `-i 0.0.0.0` por `-i 127.0.0.1` (se respaldó el original fuera del proyecto). Antes de reiniciar se comprobó que no hubiera conexiones activas a los puertos. Consecuencia: el portal ya no es accesible desde otros equipos.
  <!-- item {"id":58,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"fluidsynth: su unit viene del paquete (`/usr/lib/systemd/user`), así que no se editó","modulos":["infra","sistema"],"archivos":["/usr/lib/systemd/user"]} -->
- **fluidsynth:** su unit viene del paquete (`/usr/lib/systemd/user`), así que no se editó. La versión 2.3.4 no tiene ninguna opción para limitar la dirección del servidor (no existe `shell.address`), por lo que "solo localhost" **no es posible**.
  <!-- item {"id":59,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Primer intento, fallido: quitar el servidor (`-s`) con un override","modulos":["sistema"]} -->
- Primer intento, **fallido**: quitar el servidor (`-s`) con un override. El proceso terminaba al instante porque ese servidor es lo que lo mantiene vivo, y el servicio quedó caído unos 30 segundos por mi cambio. Se detectó al verificar y se corrigió en el acto.
  <!-- item {"id":60,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Solución final: override de usuario `fluidsynth.service.d/sin-servidor-red.conf` con `PrivateNetwork=yes`","modulos":["infra","sistema"]} -->
- Solución final: override de usuario `fluidsynth.service.d/sin-servidor-red.conf` con `PrivateNetwork=yes`. El proceso conserva su comando original, pero su red es privada, así que el puerto 9800 no se alcanza desde la LAN ni desde el host. Es más estricto que localhost. Antes de aplicarlo se comprobó que nada usaba ese puerto (MIDI va por ALSA y el audio por PipeWire, ambos verificados después).
  <!-- item {"id":61,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Verificación desde la red real: `ttyd` en 192.168.0.9:7681 no responde (HTTP 000) y en 127.0.0.1 devuelve 200","modulos":["sistema"]} -->
- Verificación desde la red real: `ttyd` en 192.168.0.9:7681 no responde (HTTP 000) y en 127.0.0.1 devuelve 200; el puerto 9800 está cerrado en la LAN.
  <!-- item {"id":62,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Los tres hallazgos de seguridad viejos de esos servicios se marcaron como `revisado` (queda registro en la tabla…","modulos":["seguridad"]} -->
- Los tres hallazgos de seguridad viejos de esos servicios se marcaron como `revisado` (queda registro en la tabla `acciones`).

### Reputación online de procesos sospechosos: local primero (pedido del usuario)
_2026-10-28 · nota_
<!-- entrada {"id":17,"seccion":"Construcción inicial (2026-10-28)","titulo":"Reputación online de procesos sospechosos: local primero (pedido del usuario)","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":63,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Pedido (corrige mi planteo anterior de no consultar nada): los datos se guardan en la PC","modulos":["seguridad"]} -->
- Pedido (corrige mi planteo anterior de no consultar nada): los datos se guardan en la PC; online solo se consultan los procesos **sospechosos**, para alertar si alguno figura como malicioso. Las alertas en sí se trabajan después; ahora importa que el flujo funcione.
  <!-- item {"id":64,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Nuevo `reputacion.py` y tabla `reputacion` (sha256, sha1, ruta, veredicto, fuente, detalle, fecha)","modulos":["seguridad"],"archivos":["reputacion.py"]} -->
- **Nuevo `reputacion.py`** y tabla `reputacion` (sha256, sha1, ruta, veredicto, fuente, detalle, fecha). Flujo: el escaneo local marca un hallazgo de severidad alta o media con ejecutable en disco, se calculan sus hashes **localmente**, se guardan y recién entonces se consulta online **únicamente ese hash**.
  <!-- item {"id":65,"tipo":"invariante","vigencia":"vigente","fecha":"2026-10-28","resumen":"Privacidad: no sale de la PC ningún archivo ni hash de procesos no sospechosos; online solo el hash de los sospechosos","modulos":["seguridad"],"archivos":["~/.local/share/pc-doctor/config.json"]} -->
- **Qué no sale de la PC:** archivos (nunca se sube nada binario), hashes de procesos no sospechosos y cualquier otro dato del sistema. Hallazgos de red o sin ejecutable no generan consultas. Se puede apagar todo con `"consulta_online": false` en `~/.local/share/pc-doctor/config.json` (el archivo se crea con los valores por defecto).
  **(invariante)**
  <!-- item {"id":66,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Fuentes (probadas, sin clave): Team Cymru Malware Hash Registry, por DNS con SHA-1: detecta malware","modulos":["seguridad"]} -->
- **Fuentes (probadas, sin clave):**
  - Team Cymru Malware Hash Registry, por DNS con SHA-1: detecta malware. Verificado con EICAR (100 %) y con un binario normal (sin registro).
  - CIRCL hashlookup, por HTTPS con SHA-256: base de archivos conocidos. Solo sirve para descartar, no para detectar.
  - MalwareBazaar: requiere una clave gratuita de abuse.ch en `config.json`. Implementada pero **sin probar** porque no hay clave; sin clave devuelve `Unauthorized` y no se usa.
  - Descartado: un SHA-256 no cabe en una etiqueta DNS (64 > 63 caracteres), de ahí el SHA-1 para Cymru.
  <!-- item {"id":67,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Error corregido en la primera prueba: EICAR no daba alerta porque CIRCL lo conoce como archivo existente (`eicar.com`)…","modulos":["seguridad"]} -->
- **Error corregido en la primera prueba:** EICAR no daba alerta porque CIRCL lo conoce como archivo existente (`eicar.com`) y mi lógica se detenía ahí. "Conocido" no es "limpio". Ahora se consultan todos los proveedores y un veredicto de malware siempre gana.
  <!-- item {"id":68,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Control de costo: máximo 3 consultas nuevas por corrida, los veredictos se reutilizan por hash durante 7 días y los…","modulos":["seguridad"]} -->
- **Control de costo:** máximo 3 consultas nuevas por corrida, los veredictos se reutilizan por hash durante 7 días y los hallazgos que comparten ejecutable hacen una sola consulta. Los pendientes pasan a la corrida siguiente.
  <!-- item {"id":69,"tipo":"nota","vigencia":"superada","fecha":"2026-10-28","resumen":"Un veredicto `malicioso` o `sospechoso` sube el hallazgo a severidad alta y queda en la lista `alertas` de…","modulos":["alertas","seguridad"],"reemplazada_por":74,"motivo":"Las alertas de escritorio (notificaciones) ya están hechas."} -->
- Un veredicto `malicioso` o `sospechoso` sube el hallazgo a severidad alta y queda en la lista `alertas` de `revision_seguridad()`. El aviso al usuario (notificación) queda pendiente.
  (superada por #74: Las alertas de escritorio (notificaciones) ya están hechas.)
  <!-- item {"id":70,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Pruebas en una base temporal (la real no se tocó): falso minero real en `/tmp` -\u003e `sin_registro`, 1 sola consulta para…","modulos":["seguridad"]} -->
- **Pruebas en una base temporal** (la real no se tocó): falso minero real en `/tmp` -> `sin_registro`, 1 sola consulta para 2 hallazgos; EICAR -> `malicioso` con alerta; segunda pasada -> 0 consultas (caché); con la consulta desactivada -> `sin_consultar`. Los archivos de prueba se eliminaron.
  <!-- item {"id":71,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"`hallazgos_seguridad()` ahora muestra la reputación de cada hallazgo. Costo en el recolector: ~2,0 s en total","modulos":["datos","seguridad"]} -->
- `hallazgos_seguridad()` ahora muestra la reputación de cada hallazgo. Costo en el recolector: ~2,0 s en total.

### Alertas de escritorio (pedido del usuario)
_2026-10-28 · nota_
<!-- entrada {"id":18,"seccion":"Construcción inicial (2026-10-28)","titulo":"Alertas de escritorio (pedido del usuario)","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":72,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Decisiones del usuario: las alertas son notificaciones de escritorio, y MalwareBazaar queda desactivado (sin clave de…","modulos":["alertas","seguridad"]} -->
- Decisiones del usuario: las alertas son **notificaciones de escritorio**, y MalwareBazaar queda **desactivado** (sin clave de abuse.ch por ahora; `malwarebazaar_key` sigue vacío en `config.json`).
  <!-- item {"id":73,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Nuevo `alertas.py` y tabla `notificaciones` (huella, fecha, título). Usa `notify-send`","modulos":["alertas"],"archivos":["alertas.py"]} -->
- **Nuevo `alertas.py`** y tabla `notificaciones` (huella, fecha, título). Usa `notify-send`.
  <!-- item {"id":74,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Qué avisa: hallazgos de severidad alta con estado `nuevo` vistos en la corrida actual","modulos":["seguridad"]} -->
- **Qué avisa:** hallazgos de severidad alta con estado `nuevo` vistos en la corrida actual. Incluye lo que la reputación online marcó como malware (que sube a alta) y las reglas graves locales (minero por nombre, ejecución desde `/tmp`, terminal web sin contraseña, etc.). Los hallazgos de severidad baja o media no generan aviso.
  <!-- item {"id":75,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Una vez por hallazgo: se registra en `notificaciones` para no repetir el aviso cada 15 minutos","modulos":["alertas","seguridad"]} -->
- **Una vez por hallazgo:** se registra en `notificaciones` para no repetir el aviso cada 15 minutos. Los hallazgos marcados `revisado` o `falso_positivo` no avisan.
  <!-- item {"id":76,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Un solo aviso agrupado por corrida: detalla hasta 3 hallazgos y resume el resto","modulos":["seguridad"]} -->
- **Un solo aviso agrupado por corrida:** detalla hasta 3 hallazgos y resume el resto. Es de urgencia crítica si hay veredicto de malware y normal en el resto de los casos.
  <!-- item {"id":77,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Los fallos se reintentan: un hallazgo solo se marca como avisado si la notificación realmente se envió","modulos":["alertas","datos","seguridad"]} -->
- **Los fallos se reintentan:** un hallazgo solo se marca como avisado si la notificación realmente se envió; si falla (por ejemplo, sin sesión gráfica) se vuelve a intentar en la próxima corrida y nunca rompe el recolector.
  <!-- item {"id":78,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Funciona desde el timer: se verificó con `systemd-run \u002d\u002duser`, que reproduce el entorno de un servicio de usuario","modulos":["infra"]} -->
- **Funciona desde el timer:** se verificó con `systemd-run --user`, que reproduce el entorno de un servicio de usuario. El bus de D-Bus es visible y, si faltara la variable, el módulo la reconstruye a partir del UID.
  <!-- item {"id":79,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Interruptor: `\"notificaciones\": false` en `config.json` (visible en `datos/config.json`)","modulos":["alertas"]} -->
- **Interruptor:** `"notificaciones": false` en `config.json` (visible en `datos/config.json`).
  <!-- item {"id":80,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"`uv run alertas.py \u002d\u002dprobar` envía una notificación de prueba","modulos":["alertas"]} -->
- `uv run alertas.py --probar` envía una notificación de prueba.
  <!-- item {"id":81,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Pruebas en base temporal: EICAR + falso minero -\u003e 1 aviso con 2 hallazgos; repetir -\u003e 0; falso positivo -\u003e 0","modulos":["seguridad"]} -->
- Pruebas en base temporal: EICAR + falso minero -> 1 aviso con 2 hallazgos; repetir -> 0; falso positivo -> 0; con la opción apagada -> 0. El recolector real no avisó porque no hay hallazgos graves nuevos. Ya no quedan hallazgos sin revisar con severidad alta.

### Alertas de salud del equipo (pedido del usuario)
_2026-10-28 · nota_
<!-- entrada {"id":19,"seccion":"Construcción inicial (2026-10-28)","titulo":"Alertas de salud del equipo (pedido del usuario)","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":82,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Pedido: avisar con notificación de escritorio cada vez que algo salga de sus valores normales (temperatura de CPU…","modulos":["alertas","salud"]} -->
- Pedido: avisar con notificación de escritorio cada vez que algo salga de sus valores normales (temperatura de CPU, velocidad y estado de discos, memoria, estado de GPU y CPU, voltaje; todo lo que diagnostica pc-doctor).
  <!-- item {"id":83,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Inventario antes de diseñar (lo que esta máquina expone sin root): temperaturas de CPU (`k10temp`), GPU (edge…","modulos":["salud"]} -->
- **Inventario antes de diseñar** (lo que esta máquina expone sin root): temperaturas de CPU (`k10temp`), GPU (edge, junction, memoria) y NVMe; ventilador, voltaje del núcleo (`vddgfx`), potencia, uso y VRAM de la GPU; E/S, espacio y modo solo-lectura de los discos; RAM, carga y uso de CPU; mensajes del kernel (el usuario está en el grupo `adm`).
  <!-- item {"id":84,"tipo":"decision","vigencia":"superada","fecha":"2026-10-28","resumen":"No disponible, y se informa en lugar de inventarlo: voltajes de la placa (el sensor `asus` no expone ninguno y no hay…","modulos":["salud"],"reemplazada_por":113,"motivo":"El usuario ejecutó habilitar-sensores.sh: nct6775, drivetemp y SMART funcionan."} -->
- **No disponible, y se informa en lugar de inventarlo:** voltajes de la placa (el sensor `asus` no expone ninguno y no hay un chip tipo `nct6775` cargado) y temperatura o SMART de los discos SATA `sda` y `sdb` (falta `smartmontools`, el módulo `drivetemp` y permisos). Ambos requieren `sudo`, así que quedan pendientes de aprobación.
  (superada por #113: El usuario ejecutó habilitar-sensores.sh: nct6775, drivetemp y SMART funcionan.)
  <!-- item {"id":85,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Nuevo `salud.py`, con tres tablas: `lecturas` (sensores por corrida, con el límite crítico que informa el hardware)…","modulos":["salud"],"archivos":["salud.py"]} -->
- **Nuevo `salud.py`**, con tres tablas: `lecturas` (sensores por corrida, con el límite crítico que informa el hardware), `alertas_salud` (estado de cada alerta: activa o resuelta, última notificación) y la configuración en `config.json`.
  <!-- item {"id":86,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Lectura agnóstica al fabricante: recorre `/sys/class/hwmon` (cualquier chip: `k10temp`, `coretemp`, `amdgpu`, `nvme`…","modulos":["salud"]} -->
- **Lectura agnóstica al fabricante:** recorre `/sys/class/hwmon` (cualquier chip: `k10temp`, `coretemp`, `amdgpu`, `nvme`, `drivetemp`, `nct*`...), `sysfs` de AMD para uso y VRAM, y `nvidia-smi` si existe. El parser de NVIDIA se probó con datos simulados (incluido `[N/A]`), pero no con una GPU NVIDIA real.
  <!-- item {"id":87,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Reglas de \"valores normales\": 15 reglas con umbrales de aviso y crítico, y un número de lecturas consecutivas (una…","modulos":["salud"]} -->
- **Reglas de "valores normales":** 15 reglas con umbrales de aviso y crítico, y un número de lecturas consecutivas (una cada 15 min) para evitar avisar por picos: temperatura de CPU (85/92), GPU, disco y placa, uso de GPU y CPU sostenidos, VRAM, voltaje de GPU, carga, RAM, swap, espacio libre, saturación y solo-lectura de discos, y desviación de rieles de la placa.
  - GPU y disco usan **el límite crítico que informa el propio hardware** (aviso a 20 y 18 grados por debajo, crítico a 8), con valores por defecto si no lo informa.
  - El crítico salta con una sola lectura; el aviso necesita varias seguidas (por ejemplo, 2 para temperaturas y 8 para GPU al máximo, es decir 2 horas).
  - Decisión: el uso alto de GPU o CPU **solo avisa si es sostenido** (jugar a pleno es normal).
  - Una alerta no parpadea: tiene histéresis (por ejemplo, un aviso de 85 °C no se resuelve hasta bajar de 81).
  - Ventilador detenido con el chip caliente (75 °C aviso, 80 °C crítico). A 0 RPM con el chip frío se considera modo silencioso normal, como en esta GPU.
  <!-- item {"id":88,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Eventos del kernel y del journal: patrones específicos de errores de disco o sistema de archivos, fallos de GPU…","modulos":["salud"]} -->
- **Eventos del kernel y del journal:** patrones específicos de errores de disco o sistema de archivos, fallos de GPU, memoria agotada o con errores (OOM, MCE), limitación térmica y problemas de PCIe o energía. Descubierto al revisar los últimos 7 días: mi primer patrón genérico (`thermal`, `EDAC`, `MCE`, `amdgpu ring`) coincidía con mensajes normales del arranque, así que se reescribió y se probó con esos mensajes reales para comprobar que no producen alertas.
  <!-- item {"id":89,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Control de ruido: una sola notificación agrupada por corrida (4 detalladas y el resto resumidas)","modulos":["alertas"]} -->
- **Control de ruido:** una sola notificación agrupada por corrida (4 detalladas y el resto resumidas). Alertas que persisten: se repiten cada 6 h (aviso) o 2 h (crítico). Un evento nuevo avisa de nuevo. Las resueltas se cierran en silencio. Si el envío falla, se reintenta en la siguiente corrida.
  <!-- item {"id":90,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Configurable en `config.json` (visible en `datos/config.json`): `\"salud\": false` apaga estas alertas, y `\"umbrales\"…","modulos":["salud"]} -->
- **Configurable** en `config.json` (visible en `datos/config.json`): `"salud": false` apaga estas alertas, y `"umbrales": {"temp_cpu": {"aviso": 80, "muestras": 1}}` cambia cualquier límite.
  <!-- item {"id":91,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Nuevas tools MCP (15 en total): `estado_salud()` (lecturas en vivo, lo que está fuera de lo normal y lo que no se…","modulos":["mcp","salud"]} -->
- **Nuevas tools MCP (15 en total):** `estado_salud()` (lecturas en vivo, lo que está fuera de lo normal y lo que no se puede medir) y `alertas_salud(solo_activas, dias)`.
  <!-- item {"id":92,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Pruebas: 40 comprobaciones en una base temporal con un notificador falso (sostenido, persistencia, escalada…","modulos":["salud"]} -->
- **Pruebas:** 40 comprobaciones en una base temporal con un notificador falso (sostenido, persistencia, escalada, histéresis, límites del hardware, ventilador, discos, memoria, voltajes, config, eventos reales y benignos, agrupación y parser NVIDIA); todas pasaron sin enviar notificaciones reales. En la máquina real: 30 lecturas por corrida y nada fuera de lo normal. El recolector completo pasó de 2,0 s a 2,5 s.
  <!-- item {"id":93,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Aviso previo antes de probar notificaciones reales: se envió una única notificación marcada como [PRUEBA], con valores…","modulos":["alertas"]} -->
- **Aviso previo antes de probar notificaciones reales:** se envió una única notificación marcada como [PRUEBA], con valores inventados y sin escribir nada en la base.
  <!-- item {"id":94,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Retención: las lecturas se borran a los 30 días junto con las métricas crudas, sin resumen diario","modulos":["datos","salud"]} -->
- Retención: las lecturas se borran a los 30 días junto con las métricas crudas, sin resumen diario. Las alertas resueltas se borran a los 90 días.
  <!-- item {"id":95,"tipo":"limitacion","vigencia":"superada","fecha":"2026-10-28","resumen":"Limitaciones: umbrales fijos, no aprendidos del historial de esta PC","modulos":["salud"],"reemplazada_por":107,"motivo":"Hoy hay umbrales aprendidos (anomalía y deriva) y historial() acepta cualquier sensor."} -->
- Limitaciones: umbrales fijos, no aprendidos del historial de esta PC. Los voltajes de placa se evalúan solo si el kernel los expone con etiquetas de riel conocidas (+12 V, +5 V, +3,3 V). Las lecturas nuevas aún no se consultan desde `historial()`.
  (superada por #107: Hoy hay umbrales aprendidos (anomalía y deriva) y historial() acepta cualquier sensor.)

### Habilitar voltajes y SMART (pedido del usuario) - preparado, pendiente de ejecutar
_2026-10-28 · nota_
<!-- entrada {"id":20,"seccion":"Construcción inicial (2026-10-28)","titulo":"Habilitar voltajes y SMART (pedido del usuario) - preparado, pendiente de ejecutar","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":96,"tipo":"nota","vigencia":"superada","fecha":"2026-10-28","resumen":"Pedido: habilitar los voltajes y el SMART","modulos":["infra","salud"],"archivos":["habilitar-sensores.sh"],"reemplazada_por":113,"motivo":"El usuario ejecutó el script y se verificó que los voltajes y el SMART funcionan."} -->
- Pedido: habilitar los voltajes y el SMART. Requiere `sudo` y modifica `/etc`, por lo que **no se ejecutó**: se dejó el script `habilitar-sensores.sh` en el proyecto para que el usuario lo revise y lo ejecute.
  (superada por #113: El usuario ejecutó el script y se verificó que los voltajes y el SMART funcionan.)
  <!-- item {"id":97,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Investigación previa (sin sudo): `smartmontools` está en los repositorios y `drivetemp` existe en el kernel","modulos":["salud"]} -->
- **Investigación previa (sin sudo):** `smartmontools` está en los repositorios y `drivetemp` existe en el kernel. Para los voltajes, ni `asus_ec_sensors` ni `asus_wmi_sensors` declaran la placa PRIME B550-PLUS; la única vía es `nct6775` (familia NCT679x), cuyo soporte para esta placa **no está confirmado**. Descubierto al revisar la lista de placas de cada driver.
  <!-- item {"id":98,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"El script (idempotente): instala `smartmontools`","modulos":["salud","sistema"],"archivos":["/etc/modules-load.d/pc-doctor.conf","/etc/sudoers.d/pc-doctor"]} -->
- **El script (idempotente):** instala `smartmontools`; carga `drivetemp` y lo deja permanente en `/etc/modules-load.d/pc-doctor.conf`; prueba `nct6775` y solo lo deja permanente si aparece un sensor real (si no carga, informa el motivo y no toca el arranque; el parámetro `acpi_enforce_resources=lax` queda como decisión del usuario); crea `/etc/sudoers.d/pc-doctor`.
  <!-- item {"id":99,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Permiso mínimo para el SMART: una regla de sudoers que permite únicamente `smartctl -j -H -A` sobre cada disco, con…","modulos":["salud"]} -->
- **Permiso mínimo para el SMART:** una regla de sudoers que permite únicamente `smartctl -j -H -A` sobre cada disco, con esos argumentos exactos y sin contraseña. No permite otras opciones ni otros dispositivos. Se descartó añadir al usuario al grupo `disk` (da lectura cruda a todos los discos) y `setcap` sobre `smartctl` (cualquier proceso podría usarlo con sus capacidades). La regla se valida con `visudo -cf` antes de instalarse; el script generado se probó sin privilegios (sintaxis y regla válidas).
  <!-- item {"id":100,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Lector de SMART en `salud.py`: `parsear_smart` y `_smart`, que llaman a `sudo -n smartctl ...`","modulos":["salud"],"archivos":["salud.py"]} -->
- **Lector de SMART en `salud.py`:** `parsear_smart` y `_smart`, que llaman a `sudo -n smartctl ...`; si falta el permiso se omite sin romper y `estado_salud()` lo informa como no disponible. Cubre salud general, sectores realocados, pendientes e incorregibles, errores CRC, desgaste y reserva (SATA y NVMe), con 9 reglas nuevas. El parser se probó con salidas JSON de ejemplo en el formato de `smartctl` 7.4, **no con un disco real** hasta que se habilite el permiso.
  <!-- item {"id":101,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Para deshacerlo todo: `sudo rm /etc/sudoers.d/pc-doctor /etc/modules-load.d/pc-doctor.conf && sudo apt remove…","modulos":["sistema"]} -->
- Para deshacerlo todo: `sudo rm /etc/sudoers.d/pc-doctor /etc/modules-load.d/pc-doctor.conf && sudo apt remove smartmontools`.

### Umbrales aprendidos y registro histórico (pedido del usuario)
_2026-10-28 · nota_
<!-- entrada {"id":21,"seccion":"Construcción inicial (2026-10-28)","titulo":"Umbrales aprendidos y registro histórico (pedido del usuario)","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":102,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Pedido: por sostenibilidad en el tiempo, un registro de los valores y las medias de cada componente, con umbrales que…","modulos":["salud"]} -->
- Pedido: por sostenibilidad en el tiempo, un registro de los valores y las medias de cada componente, con umbrales que se aprendan de esta PC.
  <!-- item {"id":103,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Contexto reposo/carga en cada lectura (nueva columna `lecturas.contexto`, con migración automática de la base…","modulos":["salud"]} -->
- **Contexto reposo/carga en cada lectura** (nueva columna `lecturas.contexto`, con migración automática de la base existente): reposo si la CPU está bajo 25 % y la GPU bajo 20 %. Es necesario porque una GPU a 70 °C jugando es normal y a 70 °C en reposo no; sin separar contextos, la media mezclaría ambas situaciones.
  <!-- item {"id":104,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Tres niveles de memoria: `lecturas`: lecturas crudas, 30 días (sin cambios)","modulos":["salud"]} -->
- **Tres niveles de memoria:**
  1. `lecturas`: lecturas crudas, 30 días (sin cambios).
  2. `lecturas_diarias` (nueva, **permanente**): por día, sensor y contexto: muestras, media, mínimo y máximo. Se completa al cerrar cada día y antes de borrar las crudas. Hace posible comparar contra meses atrás aunque las lecturas ya no existan. Resumir lecturas viejas se habría podido hacer solo al borrarlas, pero así el registro existe desde el primer día completo.
  3. `linea_base` (nueva): lo que es normal hoy, por sensor y contexto, con los últimos 30 días: n, media, desviación, mínimo, máximo, mediana, MAD, p95 y p99. Se recalcula cada 6 h.
  <!-- item {"id":105,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Estadística robusta: las anomalías se miden con mediana y MAD (desvío absoluto mediano) en vez de media y desviación…","modulos":["salud"]} -->
- **Estadística robusta:** las anomalías se miden con mediana y MAD (desvío absoluto mediano) en vez de media y desviación, porque resisten datos atípicos (un día de mucho calor no corre la línea base). La media y la desviación se guardan igual para consulta.
  <!-- item {"id":106,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Madurez: un sensor solo genera avisos aprendidos con al menos 200 muestras en ese contexto (unos 2 días)","modulos":["salud"]} -->
- **Madurez:** un sensor solo genera avisos aprendidos con al menos 200 muestras en ese contexto (unos 2 días). Mientras tanto, `estado_salud()` informa "aprendiendo". Los avisos de límites absolutos siguen funcionando desde el primer momento.
  <!-- item {"id":107,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Anomalía aprendida (siempre `aviso`, nunca crítico): valor a 4 o más desvíos robustos de la mediana y con un cambio…","modulos":["salud"]} -->
- **Anomalía aprendida** (siempre `aviso`, nunca crítico): valor a 4 o más desvíos robustos de la mediana **y** con un cambio mínimo que importa (por ejemplo, 8 °C o 30 % en RPM), **dos lecturas seguidas**. Temperatura, potencia, RAM y VRAM solo hacia arriba; espacio libre solo hacia abajo; ventiladores y voltajes hacia ambos lados (un ventilador mucho más lento que lo habitual puede ser una falla).
  <!-- item {"id":108,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Deriva lenta: compara los últimos 7 días contra los 14 a 45 días anteriores, solo en reposo y solo sobre el registro…","modulos":["salud"]} -->
- **Deriva lenta:** compara los últimos 7 días contra los 14 a 45 días anteriores, solo en reposo y solo sobre el registro diario: temperatura +6 °C, ventilador +30 % o espacio libre -8 puntos. Es lo que detecta un desgaste gradual (polvo, pasta térmica, disco llenándose). Se avisa como mucho una vez por semana. Necesita al menos 3 semanas de datos (7 recientes y 14 de referencia).
  <!-- item {"id":109,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Errores encontrados y corregidos durante las pruebas: Las alertas de anomalía y deriva nunca se habrían resuelto: la…","modulos":["salud"]} -->
- **Errores encontrados y corregidos durante las pruebas:**
  - Las alertas de anomalía y deriva nunca se habrían resuelto: la comprobación usaba una parte de la clave que no coincide con el sensor. Ahora usa el nombre guardado.
  - Los mensajes mostraban `52.0563` con decimales sin sentido; ahora un decimal.
  - La deriva se activaba con solo 13 días de referencia, una base débil que daría falsas alarmas por variaciones normales; ahora exige 14.
  <!-- item {"id":110,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Pruebas: historial sintético de 10 días (reposo ~52 °C, carga ~72 °C): la base aprende cada contexto por separado","modulos":["salud"]} -->
- **Pruebas:** historial sintético de 10 días (reposo ~52 °C, carga ~72 °C): la base aprende cada contexto por separado; 70 °C bajo carga es normal y 70-71 °C en reposo avisa; +3 °C no avisa; una temperatura más fría no avisa; un ventilador a 300 RPM cuando suele estar en 900 avisa; la alerta se resuelve al volver a lo normal; el registro diario es idempotente; la deriva se detecta con 45 días y no con 20; migración de una base con el esquema anterior; y regresión de las alertas de límites (sostenido, persistencia, escalada, histéresis). Todas pasaron. En el equipo real el aprendizaje arrancó con 0 sensores maduros.
  <!-- item {"id":111,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Nuevas tools MCP (17 en total): `linea_base_aprendida(categoria, contexto)` y `medias_diarias(sensor, dias)`","modulos":["mcp","salud"]} -->
- **Nuevas tools MCP (17 en total):** `linea_base_aprendida(categoria, contexto)` y `medias_diarias(sensor, dias)`. `estado_salud()` ahora incluye el estado del aprendizaje.
  <!-- item {"id":112,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"Limitaciones: la línea base no distingue franja horaria ni estación del año (el calor de verano puede mover la…","modulos":["datos","salud"]} -->
- Limitaciones: la línea base no distingue franja horaria ni estación del año (el calor de verano puede mover la mediana, por eso la deriva compara contra un mes y avisa como máximo semanalmente). La CPU medida en cada corrida incluye el propio arranque del recolector, así que algunas corridas se clasifican como carga sin serlo; no afecta a la mediana porque son pocas.

### Verificación de los sensores habilitados (el usuario ejecutó el script)
_2026-10-28 · prueba_
<!-- entrada {"id":22,"seccion":"Construcción inicial (2026-10-28)","titulo":"Verificación de los sensores habilitados (el usuario ejecutó el script)","fecha":"2026-10-28","tipo":"prueba"} -->

<!-- item {"id":113,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"`nct6775` reconoció la placa (chip `nct6798`), `drivetemp` creó un chip por disco y el permiso de SMART funciona sin…","modulos":["salud"]} -->
- `nct6775` reconoció la placa (chip `nct6798`), `drivetemp` creó un chip por disco y el permiso de SMART funciona sin contraseña. Se leen SMART de los tres discos y 15 voltajes.
  <!-- item {"id":114,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Errores encontrados en la primera corrida real: Las entradas `AUXTIN*` (termistores sin conectar) daban 84 °C y -61…","modulos":["salud"]} -->
- **Errores encontrados en la primera corrida real:**
  - Las entradas `AUXTIN*` (termistores sin conectar) daban 84 °C y -61 °C, y la regla de ventilador detenido usaba esa temperatura: 5 alertas críticas falsas y una notificación real. Decisión: ignorar por etiqueta las entradas sin sensor (`AUXTIN*`, `PECI ... Calibration`, `PCH_*`) y exigir, para la regla de ventilador detenido, que ese ventilador haya girado alguna vez (un conector vacío marca 0 siempre).
  - Los dos `drivetemp` se llamaban igual (`drivetemp/temp1`) y habrían mezclado sus líneas base. Decisión: si el chip hwmon pertenece a un disco, el nombre lleva el disco (`drivetemp_sda`, `drivetemp_sdb`).
  - Se borraron de la base las lecturas basura de esa primera corrida; el resto de las pruebas usó un notificador falso.
  <!-- item {"id":115,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Voltajes sin etiqueta: el kernel entrega `in0`–`in14` sin nombre de rail y el mapeo depende de cada placa, así que no…","modulos":["salud"]} -->
- **Voltajes sin etiqueta:** el kernel entrega `in0`–`in14` sin nombre de rail y el mapeo depende de cada placa, así que no se inventó ninguno: se registran y se aprenden por línea base, sin regla de desviación fija.
  <!-- item {"id":116,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Hallazgo real: SMART de `sdb` con sectores realocados, pendientes e incorregibles y errores CRC (ver CHANGELOG)","modulos":["salud"]} -->
- **Hallazgo real:** SMART de `sdb` con sectores realocados, pendientes e incorregibles y errores CRC (ver CHANGELOG).

## Nivel nuevo 1: perfil por actividad (pedido del usuario, en fases)

<!-- entrada {"id":23,"seccion":"Nivel nuevo 1: perfil por actividad (pedido del usuario, en fases)","titulo":"Introducción","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":117,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"El usuario pidió cuatro fases con parada y OK al final de cada una. Esta es la Fase 1: contexto `juego`","modulos":["actividad"]} -->
El usuario pidió cuatro fases con parada y OK al final de cada una. Esta es la **Fase 1: contexto `juego`**.

### Decisiones
_2026-10-28 · decision_
<!-- entrada {"id":24,"seccion":"Nivel nuevo 1: perfil por actividad (pedido del usuario, en fases)","titulo":"Decisiones","fecha":"2026-10-28","tipo":"decision"} -->

<!-- item {"id":118,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Contexto `juego`: además de `reposo` y `carga`, una lectura se etiqueta `juego` si hay un juego en ejecución","modulos":["actividad","salud"]} -->
- **Contexto `juego`:** además de `reposo` y `carga`, una lectura se etiqueta `juego` si hay un juego en ejecución. Tiene prioridad sobre los otros dos, porque una GPU a 80 °C jugando es normal. Se aprende por separado (línea base, anomalías y registro diario funcionan igual con cualquier contexto).
  <!-- item {"id":119,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Qué cuenta como juego (decisión del usuario): solo la ejecución directa del juego","modulos":["actividad"],"archivos":["actividad.py"]} -->
- **Qué cuenta como juego (decisión del usuario):** solo la ejecución directa del juego. El cliente de Steam siempre está abierto, así que ni `steam` ni `steamwebhelper` cuentan. Las firmas están todas en `FIRMAS` (`actividad.py`), en un solo lugar:
  1. `reaper SteamLaunch AppId=N`: el lanzador que Steam crea por cada juego; el nombre sale del `appmanifest`.
  2. Primer argumento dentro de `steamapps/common/<juego>/` (juegos nativos y el proceso de Proton). Las carpetas de herramientas (Proton, SteamLinuxRuntime, GE-Proton) no cuentan. Si el primer argumento es un intérprete (bash, java, python), se mira el programa que ejecuta.
  3. Un `.exe` como primer argumento (wine/Proton renombran el proceso), o `wine`/`wine64` con un `.exe`. Se ignoran los `.exe` auxiliares (services, winedevice, explorer, steam, crashhandler, etc.).
  4. `gamescope` y los clientes de `gamemode` son **genéricos**: solo valen si no se identificó un juego concreto, para no duplicar la sesión de un juego que corre dentro de gamescope.
  <!-- item {"id":120,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Desvío respecto del pedido: `wineserver` solo no cuenta","modulos":["actividad"]} -->
- **Desvío respecto del pedido:** `wineserver` solo **no** cuenta. Un wineserver puede quedar vivo con `winecfg` o `winetricks` y no tiene `.exe` en su línea de comandos; se detecta el juego por su propio proceso.
  <!-- item {"id":121,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Se leen los procesos con psutil (primeros 3 argumentos de cada línea de comandos, sin permisos especiales)","modulos":["actividad"]} -->
- **Se leen los procesos con psutil** (primeros 3 argumentos de cada línea de comandos, sin permisos especiales). Los appmanifest de Steam solo se leen cuando algo coincide. Costo medido: 30 ms (máximo 62 ms).
  <!-- item {"id":122,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Sesiones (`sesiones_actividad`: tipo, detalle, inicio, fin, ultima_vez, origen): el recolector abre una sesión al ver…","modulos":["actividad","datos"]} -->
- **Sesiones (`sesiones_actividad`: tipo, detalle, inicio, fin, ultima_vez, origen):** el recolector abre una sesión al ver un juego, la extiende en cada corrida y la cierra cuando desaparece (`fin` = la última vez que se lo vio). El inicio es la hora real de arranque del proceso, no la de la primera corrida. Si una sesión abierta no se vio en 45 min (equipo apagado), se cierra y la siguiente es otra. El paso `actividad` va **antes** de `salud` en el recolector, porque el contexto de las lecturas depende de él.
  <!-- item {"id":123,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Base temporal para pruebas: `PC_DOCTOR_DATOS` cambia la carpeta de datos (`db.py`)","modulos":["actividad","datos"],"archivos":["db.py"]} -->
- **Base temporal para pruebas:** `PC_DOCTOR_DATOS` cambia la carpeta de datos (`db.py`). Las pruebas la usan y parchean el notificador; la base real no se toca para probar.

### Migración del historial (opción B, elegida por el usuario)
_2026-10-28 · nota_
<!-- entrada {"id":25,"seccion":"Nivel nuevo 1: perfil por actividad (pedido del usuario, en fases)","titulo":"Migración del historial (opción B, elegida por el usuario)","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":124,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Una función de una sola vez (`uv run actividad.py \u002d\u002dreclasificar`, simula","modulos":["actividad"]} -->
- Una función de una sola vez (`uv run actividad.py --reclasificar`, simula; con `--aplicar` aplica) pasa a `juego` las lecturas `reposo` o `carga` de las corridas donde había un juego entre los procesos de `top_procesos`. Se une por `metrica_id`, exacto, sin la ventana de ±60 s que había propuesto. Los juegos se reconocen por la carpeta de instalación y los ejecutables sin extensión de sus bibliotecas de Steam.
  <!-- item {"id":125,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Seguridad de la migración: simula por defecto","modulos":["actividad","salud"]} -->
- **Seguridad de la migración:** simula por defecto; al aplicar guarda una copia (`VACUUM INTO`) junto a la base, rehace los resúmenes diarios de los días afectados, reconstruye las sesiones (origen `reconstruida`), recalcula la línea base y deja registro en `acciones`. Es idempotente: si no hay nada que cambiar, no toca ni copia nada.
  <!-- item {"id":126,"tipo":"decision","vigencia":"historica","fecha":"2026-10-28","resumen":"Resultado en la base real: 26 corridas con `SlayTheSpire`; 636 lecturas `carga` y 150 `reposo` pasaron a `juego`","modulos":["actividad","salud"]} -->
- **Resultado en la base real:** 26 corridas con `SlayTheSpire`; 636 lecturas `carga` y 150 `reposo` pasaron a `juego`; 1 sesión reconstruida (12:56 a 17:27). Copia: `datos/doctor.db.antes-de-juego-1793220248`. Todas las lecturas `reposo` de ese período también cambiaron: el juego estuvo abierto todo el rato, y por la regla nueva eso es `juego`.
  <!-- item {"id":127,"tipo":"nota","vigencia":"historica","fecha":"2026-10-28","resumen":"La línea base de `juego` quedó vacía: cada sensor tiene 19 lecturas y el mínimo para mostrar algo es 20. Lo esperado","modulos":["actividad","salud"]} -->
- La línea base de `juego` quedó vacía: cada sensor tiene 19 lecturas y el mínimo para mostrar algo es 20. Lo esperado.

### Errores encontrados y corregidos
_2026-10-28 · error_
<!-- entrada {"id":26,"seccion":"Nivel nuevo 1: perfil por actividad (pedido del usuario, en fases)","titulo":"Errores encontrados y corregidos","fecha":"2026-10-28","tipo":"error"} -->

<!-- item {"id":128,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"La copia de seguridad se llamaba igual si la migración se aplicaba dos veces en el mismo segundo y fallaba","modulos":["actividad"]} -->
- La copia de seguridad se llamaba igual si la migración se aplicaba dos veces en el mismo segundo y fallaba; además una migración sin nada que cambiar igual creaba copia. Ahora no hace nada si no hay cambios.
  <!-- item {"id":129,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Mi prueba esperaba que `java -jar .../SlayTheSpire/...jar` no fuera un juego","modulos":["actividad"]} -->
- Mi prueba esperaba que `java -jar .../SlayTheSpire/...jar` no fuera un juego; sí lo es (intérprete con el programa en los argumentos) y se detecta bien. Era un error de la expectativa.

### Pruebas (base temporal, notificador falso)
_2026-10-28 · prueba_
<!-- entrada {"id":27,"seccion":"Nivel nuevo 1: perfil por actividad (pedido del usuario, en fases)","titulo":"Pruebas (base temporal, notificador falso)","fecha":"2026-10-28","tipo":"prueba"} -->

<!-- item {"id":130,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"20 casos de firmas (cliente de Steam, helpers de pressure-vessel, Proton y runtimes, editores con la ruta de un juego…","modulos":["actividad"]} -->
20 casos de firmas (cliente de Steam, helpers de pressure-vessel, Proton y runtimes, editores con la ruta de un juego, `.exe` auxiliares, wine, gamescope), unificación de varios procesos en un juego, concreto sobre genérico, ciclo de vida de sesiones (abrir, extender, cerrar, vencer), contexto `juego` de punta a punta con `salud.ciclo`, migración sobre una copia de la base real (simulacro, aplicación, idempotencia, copia) y tiempo del recolector: 2,7 a 3,1 s (antes ~2,5 s; el límite pedido es 4 s).

### Limitaciones
_2026-10-28 · limitacion_
<!-- entrada {"id":28,"seccion":"Nivel nuevo 1: perfil por actividad (pedido del usuario, en fases)","titulo":"Limitaciones","fecha":"2026-10-28","tipo":"limitacion"} -->

<!-- item {"id":131,"tipo":"limitacion","vigencia":"superada","fecha":"2026-10-28","resumen":"No verificado con un juego real en ejecución: las firmas se probaron con líneas de comandos sintéticas","modulos":["actividad"],"reemplazada_por":251,"motivo":"Se probó con un juego real (Crimson Desert bajo Proton) y se corrigió la detección."} -->
- **No verificado con un juego real en ejecución:** las firmas se probaron con líneas de comandos sintéticas. En especial, no sé cómo se ve exactamente el `argv` de un proceso de Proton, y el formato de `gamemodelist` es una suposición (no había gamemode con clientes).
  (superada por #251: Se probó con un juego real (Crimson Desert bajo Proton) y se corrigió la detección.)
  <!-- item {"id":132,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"La migración solo ve los 5 procesos que más CPU usaban por corrida: un juego fuera de ese top queda con el contexto…","modulos":["actividad"]} -->
- La migración solo ve los 5 procesos que más CPU usaban por corrida: un juego fuera de ese top queda con el contexto viejo.
  <!-- item {"id":133,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"Cualquier `.exe` bajo wine que no esté en la lista de auxiliares cuenta como juego (un Notepad++ en wine, por ejemplo)","modulos":["actividad"]} -->
- Cualquier `.exe` bajo wine que no esté en la lista de auxiliares cuenta como juego (un Notepad++ en wine, por ejemplo). Un editor o gestor de archivos no cuenta porque se excluye por nombre, pero un programa no listado que tenga como primer argumento la ruta de un juego sí.
  <!-- item {"id":134,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"Resolución de sesiones: ±15 min. Un juego abierto y cerrado entre dos corridas no se ve","modulos":["actividad"]} -->
- Resolución de sesiones: ±15 min. Un juego abierto y cerrado entre dos corridas no se ve.
  <!-- item {"id":135,"tipo":"pendiente","vigencia":"vigente","fecha":"2026-10-28","resumen":"Pendiente: decidir si se baja el mínimo de 200 muestras del contexto `juego` (unas 50 horas de juego)","modulos":["actividad","salud"]} -->
- Madurez: `juego` necesita 200 muestras por sensor y hay una por corrida, es decir unas **50 horas de juego** para que se activen las anomalías (reposo y carga tardan unos 2 días de reloj). Queda pendiente decidir si se baja ese mínimo para este contexto.
  <!-- item {"id":136,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"La deriva lenta solo mira `reposo`","modulos":["actividad","salud"]} -->
- La deriva lenta solo mira `reposo`. Con las lecturas de `reposo` de hoy convertidas a `juego`, tardará en tener referencia suficiente.

## Nivel nuevo 2: correlación de eventos y línea de tiempo (Fase 2)

### Decisiones
_2026-10-28 · decision_
<!-- entrada {"id":29,"seccion":"Nivel nuevo 2: correlación de eventos y línea de tiempo (Fase 2)","titulo":"Decisiones","fecha":"2026-10-28","tipo":"decision"} -->

<!-- item {"id":137,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"`correlacion.py` junta en una lista común lo que pc-doctor ya registra: cambios de entorno (diferencia entre snapshots…","modulos":["actividad","correlacion","seguridad"],"archivos":["correlacion.py"]} -->
- **`correlacion.py`** junta en una lista común lo que pc-doctor ya registra: cambios de entorno (diferencia entre snapshots consecutivos: kernel, driver de GPU y paquetes instalados, quitados o actualizados), eventos del sistema, alertas de salud, hallazgos de seguridad, sesiones de actividad y acciones de pc-doctor. No agrega tablas ni recolección nueva.
  <!-- item {"id":138,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Ventana: 48 h antes y 2 h después del inicio de la alerta, configurable en `config.json` (`\"correlacion\"…","modulos":["correlacion"]} -->
- **Ventana:** 48 h antes y 2 h después del inicio de la alerta, configurable en `config.json` (`"correlacion": {"horas_antes": N, "horas_despues": N}`) o por llamada.
  <!-- item {"id":139,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Puntaje = afinidad × cercanía","modulos":["correlacion"]} -->
- **Puntaje = afinidad × cercanía.** Afinidad: cuánto se relaciona el elemento con la categoría de la alerta (un driver de GPU con una alerta de GPU: 1,0; con una de disco: 0,25 del valor base). Las listas (paquetes por categoría, herramientas de monitoreo, categoría de eventos) están al principio del módulo. Cercanía: baja a la mitad cada 12 h; lo ocurrido *después* de la alerta baja a la mitad cada 1 h y parte del 50 %, porque no puede ser causa.
  <!-- item {"id":140,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"No se afirma causalidad: el resultado se llama `posibles_causas`, lleva la etiqueta alta, media o baja y el aviso…","modulos":["correlacion"]} -->
- **No se afirma causalidad:** el resultado se llama `posibles_causas`, lleva la etiqueta alta, media o baja y el aviso "coincidencias en el tiempo, no causas demostradas".
  <!-- item {"id":141,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Herramientas de monitoreo (smartmontools, lm-sensors, nvtop...): instalarlas suele *destapar* un problema que ya…","modulos":["correlacion","salud"]} -->
- **Herramientas de monitoreo (smartmontools, lm-sensors, nvtop...):** instalarlas suele *destapar* un problema que ya existía; tienen afinidad baja y el texto lo aclara. Caso real: `smartmontools` quedó instalado un minuto antes de las alertas de SMART de `sdb`, pero los sectores defectuosos ya estaban.
  <!-- item {"id":142,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Kernel y driver de GPU fusionados: `amdgpu` viene dentro del kernel (`version_driver` = \"kernel X (in-tree)\"), así que…","modulos":["correlacion"]} -->
- **Kernel y driver de GPU fusionados:** `amdgpu` viene dentro del kernel (`version_driver` = "kernel X (in-tree)"), así que cada kernel nuevo se veía además como un "cambio de driver". Ahora es un solo elemento, con afinidad máxima para alertas de GPU.
  <!-- item {"id":143,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Variedad: como mucho 3 candidatos del mismo tipo entre los primeros","modulos":["correlacion","salud"]} -->
- **Variedad:** como mucho 3 candidatos del mismo tipo entre los primeros. Sin esto, un origen ruidoso (`smartd` repetido) tapaba al resto.
  <!-- item {"id":144,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Notificación: se agrega `↳ posible relación: ...` solo si hay un cambio de entorno (driver de GPU, kernel que trae el…","modulos":["actividad","alertas","salud"]} -->
- **Notificación:** se agrega `↳ posible relación: ...` solo si hay un **cambio de entorno** (driver de GPU, kernel que trae el driver de GPU, o paquete de la misma categoría) con afinidad mínima 0,8 en las 24 h anteriores al inicio de la alerta. No se citan eventos, alertas ni sesiones (darían ruido) ni herramientas de monitoreo. El kernel solo supera el umbral cuando trae el driver de la GPU: un kernel nuevo no se cita en una alerta de SMART. Sin candidato fuerte, el texto es idéntico al de antes. La búsqueda va dentro de un `try`: si falla, el aviso sale igual.
  <!-- item {"id":145,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Orden del recolector: `snapshot` pasa antes de `salud`","modulos":["correlacion","datos"]} -->
- **Orden del recolector:** `snapshot` pasa antes de `salud`. Antes quedaba segundos *después* de la alerta, así que el aviso de la corrida en que cambiaba un driver nunca podía citarlo.
  <!-- item {"id":146,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Tools nuevas (ya son 20): `linea_de_tiempo(desde, hasta)` y `correlacionar(alerta_id)` (acepta el `id` de…","modulos":["correlacion","mcp","seguridad"]} -->
- **Tools nuevas (ya son 20):** `linea_de_tiempo(desde, hasta)` y `correlacionar(alerta_id)` (acepta el `id` de `alertas_salud()`, que ahora se muestra, o `hallazgo:N`).
  <!-- item {"id":147,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"`historial()` ampliado: además de las métricas de siempre, acepta el nombre de cualquier sensor (`k10temp/Tctl`…","modulos":["correlacion","salud"]} -->
- **`historial()` ampliado:** además de las métricas de siempre, acepta el nombre de cualquier sensor (`k10temp/Tctl`, `sda/errores_crc`...). Usa las lecturas crudas (30 días) y completa lo más antiguo con el promedio diario ponderado de `lecturas_diarias`; el parámetro `contexto` filtra reposo, carga o juego. Si el sensor no existe, sugiere nombres parecidos.

### Errores encontrados y corregidos
_2026-10-28 · error_
<!-- entrada {"id":30,"seccion":"Nivel nuevo 2: correlación de eventos y línea de tiempo (Fase 2)","titulo":"Errores encontrados y corregidos","fecha":"2026-10-28","tipo":"error"} -->

<!-- item {"id":148,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Driver de GPU y kernel duplicados (ver arriba)","modulos":["correlacion"]} -->
- Driver de GPU y kernel duplicados (ver arriba).
  <!-- item {"id":149,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"El kernel aparecía como \"posible relación\" de una alerta de SMART de disco: ruido","modulos":["correlacion"]} -->
- El kernel aparecía como "posible relación" de una alerta de SMART de disco: ruido. Bajé su afinidad base de 0,8 a 0,7 (bajo el umbral de "fuerte") y quité los paquetes `linux-image` de las categorías disco, memoria y placa.
  <!-- item {"id":150,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"La acción `limpiar_descargas_viejas` puntuaba alto para una alerta de disco; bajé su afinidad de 0,9 a 0,5","modulos":["correlacion"]} -->
- La acción `limpiar_descargas_viejas` puntuaba alto para una alerta de disco; bajé su afinidad de 0,9 a 0,5.
  <!-- item {"id":151,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"`historial()` comparaba una fecha en texto con un epoch y fallaba al mezclar crudas y diarias","modulos":["correlacion","datos"]} -->
- `historial()` comparaba una fecha en texto con un epoch y fallaba al mezclar crudas y diarias.
  <!-- item {"id":152,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"`parecidos` buscaba en `linea_base`, vacía por ahora; ahora busca en `lecturas`","modulos":["correlacion","salud"]} -->
- `parecidos` buscaba en `linea_base`, vacía por ahora; ahora busca en `lecturas`.
  <!-- item {"id":153,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Un escenario de mi prueba ponía la alerta *antes* de instalar `smartmontools`","modulos":["correlacion"]} -->
- Un escenario de mi prueba ponía la alerta *antes* de instalar `smartmontools`; el módulo lo descartó bien (no puede ser causa).

### Pruebas (base temporal, notificador falso)
_2026-10-28 · prueba_
<!-- entrada {"id":31,"seccion":"Nivel nuevo 2: correlación de eventos y línea de tiempo (Fase 2)","titulo":"Pruebas (base temporal, notificador falso)","fecha":"2026-10-28","tipo":"prueba"} -->

<!-- item {"id":154,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Escenario sintético con 4 snapshots (kernel, mesa, fuentes, smartmontools), eventos repetidos, sesión de juego…","modulos":["correlacion","datos","salud"]} -->
Escenario sintético con 4 snapshots (kernel, mesa, fuentes, smartmontools), eventos repetidos, sesión de juego, hallazgo de minero y acción: orden, agrupación de eventos repetidos, observadores, alerta que no se cita a sí misma, ventana configurable, ids inexistentes, línea de tiempo en orden. Notificación con candidato, sin candidato (texto idéntico al anterior) y con la correlación rota (el aviso sale igual). `historial` con sensor crudo, mezcla con diario, filtro de contexto, sensor inexistente y métricas viejas. Sobre la base real, solo lectura: `correlacionar` de la alerta real de `sdb` y `linea_de_tiempo("6h")`. Tiempo de la búsqueda de relación sobre la base real: 5 ms. Recolector completo: 2,7 a 3,3 s.

### Limitaciones
_2026-10-28 · limitacion_
<!-- entrada {"id":32,"seccion":"Nivel nuevo 2: correlación de eventos y línea de tiempo (Fase 2)","titulo":"Limitaciones","fecha":"2026-10-28","tipo":"limitacion"} -->

<!-- item {"id":155,"tipo":"limitacion","vigencia":"historica","fecha":"2026-10-28","resumen":"Los snapshots solo se guardan cuando cambia algo y la hora es la de la corrida (±15 min)","modulos":["correlacion","datos"]} -->
- Los snapshots solo se guardan cuando cambia algo y la hora es la de la corrida (±15 min). Hoy hay 2, así que las comparaciones de entorno son pobres hasta que pase tiempo.
  <!-- item {"id":156,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"Es una heurística: las listas de afinidad son nuestras y se ajustan a ojo","modulos":["correlacion"]} -->
- Es una heurística: las listas de afinidad son nuestras y se ajustan a ojo. Puede sugerir coincidencias sin relación real o pasar por alto una causa que no esté registrada (por ejemplo, un cambio de BIOS o de hardware).
  <!-- item {"id":157,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"Los eventos sólo incluyen lo que `eventos` ya guarda (errores del journal)","modulos":["correlacion"]} -->
- Los eventos sólo incluyen lo que `eventos` ya guarda (errores del journal); no hay línea de tiempo de lo que no se registró.
  <!-- item {"id":158,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"Si el recolector estuvo apagado, el cambio se registra al volver a correr, no cuando ocurrió","modulos":["correlacion","datos"]} -->
- Si el recolector estuvo apagado, el cambio se registra al volver a correr, no cuando ocurrió.

## Nivel nuevo 3: reporte semanal con Claude (Fase 3)

### Decisiones
_2026-10-28 · decision_
<!-- entrada {"id":33,"seccion":"Nivel nuevo 3: reporte semanal con Claude (Fase 3)","titulo":"Decisiones","fecha":"2026-10-28","tipo":"decision"} -->

<!-- item {"id":159,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"`reporte.py` ejecuta `claude -p` en modo no interactivo, toma su texto y lo guarda él (Claude no escribe nada)","modulos":["reporte"],"archivos":["reporte.py"]} -->
- **`reporte.py`** ejecuta `claude -p` en modo no interactivo, toma su texto y **lo guarda él** (Claude no escribe nada). Archivo: `datos/reportes/AAAA-MM-DD.md` (si ya existe, `-2`, `-3`...). Cada reporte queda también en la tabla nueva `reportes` (fecha, ruta, modo, motivo del plan B, duración, resumen) y se consulta con las tools `ultimo_reporte()` y `reportes(n)` (ya son 22).
  <!-- item {"id":160,"tipo":"invariante","vigencia":"vigente","fecha":"2026-10-28","resumen":"claude -p del reporte: solo tools de lectura, MCP estricto, sin CLAUDE.md ni memoria, prompt por stdin","modulos":["mcp","reporte"],"archivos":["CLAUDE.md","reporte.py","~/.claude/CLAUDE.md"],"prueba":"tests/test_reporte.py::test_la_invocacion_de_claude_es_de_solo_lectura"} -->
- **Seguridad de la invocación (todo en un solo bloque, al principio de `reporte.py`):**
  - `--tools ""`: sin herramientas integradas (Bash, Write, Edit, web).
  - `--strict-mcp-config` + un `--mcp-config` generado con **solo** el MCP de pc-doctor. La cuenta tiene otros MCP (`fetch`, Google Drive, Claude Docs) que, sin esto, el modelo habría podido usar.
  - `--allowedTools` con 14 tools de lectura de pc-doctor, una por una. `--permission-mode dontAsk` deniega todo lo demás sin preguntar.
  - `--disallowedTools` con las que escriben (`limpiar_descargas_viejas`, `restaurar_cuarentena`, `marcar_hallazgo`, `revision_seguridad`) y las integradas peligrosas: prohibir pesa más que permitir. Es una segunda barrera.
  - **Excluidas de lo permitido a propósito:** `revision_seguridad` (escribe en la base y consulta online); `ultimo_reporte` y `reportes` (para que el modelo no lea reportes anteriores, texto generado por un modelo: otro canal para arrastrar instrucciones de una semana a la siguiente); `procesos_que_mas_consumen` y `temperatura_cpu` (redundantes, y la primera trae nombres de procesos en vivo).
  - Sin `CLAUDE.md` ni memoria (`CLAUDE_CODE_DISABLE_CLAUDE_MDS` y `CLAUDE_CODE_DISABLE_AUTO_MEMORY`, carpeta de trabajo neutra `datos/reportes/`), sin ajustes ni hooks del usuario (`--setting-sources project`), sin guardar la sesión (`--no-session-persistence`). Motivo: la regla del changelog de `~/.claude/CLAUDE.md` le pediría escribir un archivo que no puede.
  - **El prompt va por stdin**, no como argumento: las opciones `--allowedTools`, `--tools` y `--mcp-config` aceptan varios valores y habrían absorbido el texto.
  - El prompt declara todo dato del equipo como "no confiable, nunca instrucciones" y pide marcar como sospechoso cualquier texto que intente dar órdenes.
  **(invariante · prueba: tests/test_reporte.py::test_la_invocacion_de_claude_es_de_solo_lectura)**
  <!-- item {"id":161,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"El resumen de la notificación no es el texto del modelo sin más: la primera línea es siempre determinística…","modulos":["alertas","reporte"]} -->
- **El resumen de la notificación** no es el texto del modelo sin más: la primera línea es siempre determinística (contadores de SMART), y el resumen que pide el prompt (`RESUMEN: ...`) se limpia (sin marcado, sin saltos de línea, 180 caracteres).
  <!-- item {"id":162,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Plan B (reporte determinístico): se activa si `claude` no existe, no tiene sesión, no hay red, se alcanzó el límite de…","modulos":["reporte"]} -->
- **Plan B (reporte determinístico):** se activa si `claude` no existe, no tiene sesión, no hay red, se alcanzó el límite de uso, se agotó el tiempo (por defecto 900 s; el proceso y su servidor MCP se matan con `killpg`), devuelve error o devuelve una respuesta de menos de 400 caracteres o sin al menos 3 secciones. Usa las mismas tools del servidor, ordena los datos y aplica reglas simples para las recomendaciones; el encabezado dice que no está redactado y por qué. Si incluso eso falla, igual se escribe un archivo que explica el error: el reporte semanal nunca queda sin generarse.
  <!-- item {"id":163,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Configuración (`config.json`, clave `reporte`): `habilitado`, `modelo` (por defecto `sonnet`, para no heredar el…","modulos":["reporte","sistema"],"archivos":["~/.local/bin/claude"]} -->
- **Configuración (`config.json`, clave `reporte`):** `habilitado`, `modelo` (por defecto `sonnet`, para no heredar el esfuerzo alto de los ajustes del usuario), `max_turns` (30), `timeout_s` (900), `claude` (ruta). `"reporte": false` lo apaga. `claude` se busca por ruta absoluta en `~/.local/bin/claude` (el enlace estable que usa el instalador, sin resolver a la versión).
  <!-- item {"id":164,"tipo":"decision","vigencia":"superada","fecha":"2026-10-28","resumen":"systemd: `systemd/pc-doctor-reporte.service` (oneshot, `Nice=10`, `TimeoutStartSec=1200`, rutas absolutas con `%h`) y…","modulos":["infra","reporte"],"archivos":["systemd/pc-doctor-reporte.service"],"reemplazada_por":179,"motivo":"El timer del reporte se instaló y se habilitó."} -->
- **systemd:** `systemd/pc-doctor-reporte.service` (oneshot, `Nice=10`, `TimeoutStartSec=1200`, rutas absolutas con `%h`) y `.timer` (`OnCalendar=Sun *-*-* 20:00:00`, `Persistent=true`). Verificados con `systemd-analyze --user verify`; próximo disparo calculado: domingo 2026-11-01 20:00. **Sin instalar, esperando la revisión del usuario.**
  (superada por #179: El timer del reporte se instaló y se habilitó.)

### Errores encontrados y corregidos
_2026-10-28 · error_
<!-- entrada {"id":34,"seccion":"Nivel nuevo 3: reporte semanal con Claude (Fase 3)","titulo":"Errores encontrados y corregidos","fecha":"2026-10-28","tipo":"error"} -->

<!-- item {"id":165,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Bug de la fase anterior: `estado_salud()` seguía diciendo que faltaba `drivetemp` aunque estaba activo","modulos":["reporte","salud"]} -->
- **Bug de la fase anterior:** `estado_salud()` seguía diciendo que faltaba `drivetemp` aunque estaba activo. Buscaba nombres que empiezan con `drivetemp/` y desde el renombre por disco son `drivetemp_sda/`. Ahora comprueba cada disco SATA.
  <!-- item {"id":166,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"El prompt le pedía al modelo `historial(\"temp_gpu\")`, métrica vieja que en este equipo (GPU `amdgpu`) viene vacía: la…","modulos":["reporte","salud"]} -->
- El prompt le pedía al modelo `historial("temp_gpu")`, métrica vieja que en este equipo (GPU `amdgpu`) viene vacía: la temperatura real está en las lecturas de salud (`amdgpu/edge`, `junction`...). El prompt y el plan B usan ahora los sensores reales, separados por contexto (reposo, carga, juego).
  <!-- item {"id":167,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Plan B: sublistas sin sangría, línea vacía en \"Cambios de entorno\" y el mismo origen repetido en \"Errores del sistema\"","modulos":["reporte"]} -->
- Plan B: sublistas sin sangría, línea vacía en "Cambios de entorno" y el mismo origen repetido en "Errores del sistema".
  <!-- item {"id":168,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Mi prueba esperaba \"datos no confiables\" en minúsculas y el prompt lo dice en mayúsculas (error de la prueba)","modulos":["reporte"]} -->
- Mi prueba esperaba "datos no confiables" en minúsculas y el prompt lo dice en mayúsculas (error de la prueba).

### Pruebas (base temporal, `claude` falso, notificador falso)
_2026-10-28 · prueba_
<!-- entrada {"id":35,"seccion":"Nivel nuevo 3: reporte semanal con Claude (Fase 3)","titulo":"Pruebas (base temporal, `claude` falso, notificador falso)","fecha":"2026-10-28","tipo":"prueba"} -->

<!-- item {"id":169,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Invocación: 14 tools permitidas, todas existen en el servidor; ninguna de las que escriben está permitida","modulos":["mcp","reporte"]} -->
- Invocación: 14 tools permitidas, todas existen en el servidor; ninguna de las que escriben está permitida; solo el MCP de pc-doctor; sin integradas; prompt por stdin; carpeta neutra; variables de entorno puestas.
  <!-- item {"id":170,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Plan B ante: sin sesión, límite de uso, sin red, código de error desconocido, respuesta corta, tiempo agotado (el…","modulos":["reporte"]} -->
- Plan B ante: sin sesión, límite de uso, sin red, código de error desconocido, respuesta corta, tiempo agotado (el proceso queda muerto), `claude` inexistente. Modos `--sin-claude`, `--sin-notificar` y reporte desactivado.
  <!-- item {"id":171,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Resumen malicioso (`\u003cb\u003e`, escape ANSI, salto de línea con una \"orden\"): el resumen guardado y el de la notificación…","modulos":["alertas","reporte"]} -->
- Resumen malicioso (`<b>`, escape ANSI, salto de línea con una "orden"): el resumen guardado y el de la notificación quedan limpios; la línea con la "orden" queda en el cuerpo del archivo como texto.
  <!-- item {"id":172,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Sin costo, con el `claude` real: el comando exacto contra el binario real, con una carpeta de usuario vacía y una…","modulos":["reporte"]} -->
- **Sin costo, con el `claude` real:** el comando exacto contra el binario real, con una carpeta de usuario vacía y una clave de API inválida, termina con `Invalid API key`: acepta todas las opciones y el clasificador lo reconoce como "sin sesión".
  <!-- item {"id":173,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Desde un servicio (`systemd-run \u002d\u002duser`): (A) `claude` falso: reporte en modo `claude`","modulos":["alertas","infra","reporte"]} -->
- **Desde un servicio (`systemd-run --user`):** (A) `claude` falso: reporte en modo `claude`; (B) `claude` real con clave inválida: cae al plan B con el motivo correcto. En ambos, rutas absolutas y entorno funcionan. Sin notificaciones reales (ya se probaron desde un servicio en fases anteriores).

### Limitaciones
_2026-10-28 · limitacion_
<!-- entrada {"id":36,"seccion":"Nivel nuevo 3: reporte semanal con Claude (Fase 3)","titulo":"Limitaciones","fecha":"2026-10-28","tipo":"limitacion"} -->

<!-- item {"id":174,"tipo":"limitacion","vigencia":"superada","fecha":"2026-10-28","resumen":"Sin verificar: una ejecución real de `claude -p` con tu sesión iniciada desde un servicio","modulos":["reporte"],"reemplazada_por":180,"motivo":"La primera ejecución real desde un servicio, con la sesión del usuario, resolvió las tres dudas."} -->
- **Sin verificar:** una ejecución real de `claude -p` con tu sesión iniciada desde un servicio. Falta confirmar que el login está disponible fuera del terminal y que el modelo usa las tools como se espera. Costo: una consulta con varias llamadas a tools.
  (superada por #180: La primera ejecución real desde un servicio, con la sesión del usuario, resolvió las tres dudas.)
  <!-- item {"id":175,"tipo":"limitacion","vigencia":"superada","fecha":"2026-10-28","resumen":"Los nombres exactos de las tools MCP (`mcp__pc-doctor__\u003ctool\u003e`) se infirieron de la convención de Claude Code","modulos":["mcp","reporte"],"reemplazada_por":180,"motivo":"La ejecución real confirmó que los nombres mcp__pc-doctor__\u003ctool\u003e son correctos."} -->
- Los nombres exactos de las tools MCP (`mcp__pc-doctor__<tool>`) se infirieron de la convención de Claude Code; si estuvieran mal, `dontAsk` denegaría todo y el reporte caería al plan B con el modelo sin datos útiles. La prueba real lo confirma.
  (superada por #180: La ejecución real confirmó que los nombres mcp__pc-doctor__<tool> son correctos.)
  <!-- item {"id":176,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"Texto malicioso en los datos del equipo puede terminar en el archivo del reporte (no se filtra el contenido que…","modulos":["reporte"]} -->
- Texto malicioso en los datos del equipo puede terminar en el archivo del reporte (no se filtra el contenido que redacta el modelo); el límite es que el modelo no puede ejecutar nada ni salir de pc-doctor.
  <!-- item {"id":177,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"Con `Persistent=true`, si la PC arranca después del domingo, el reporte puede correr apenas se enciende y antes de…","modulos":["reporte"]} -->
- Con `Persistent=true`, si la PC arranca después del domingo, el reporte puede correr apenas se enciende y antes de tener red: en ese caso queda el plan B de esa semana.
  <!-- item {"id":178,"tipo":"limitacion","vigencia":"historica","fecha":"2026-10-28","resumen":"La línea base todavía no es madura: las \"tendencias contra la línea base\" serán pobres durante semanas","modulos":["reporte","salud"]} -->
- La línea base todavía no es madura: las "tendencias contra la línea base" serán pobres durante semanas.

### Cierre de la fase 3: instalación y primera ejecución real (autorizadas por el usuario)
_2026-10-28 · nota_
<!-- entrada {"id":37,"seccion":"Nivel nuevo 3: reporte semanal con Claude (Fase 3)","titulo":"Cierre de la fase 3: instalación y primera ejecución real (autorizadas por el usuario)","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":179,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Timer instalado y habilitado (`~/.config/systemd/user/pc-doctor-reporte.{service,timer}`, copias de `systemd/`)","modulos":["datos","infra","reporte"]} -->
- **Timer instalado y habilitado** (`~/.config/systemd/user/pc-doctor-reporte.{service,timer}`, copias de `systemd/`). Próximo disparo: domingo 2026-11-01 20:00. El timer del recolector sigue activo.
  <!-- item {"id":180,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Primera ejecución real con la sesión del usuario, desde `systemd-run \u002d\u002duser`, sin notificaciones: 27 s, modo `claude`…","modulos":["reporte"]} -->
- **Primera ejecución real** con la sesión del usuario, desde `systemd-run --user`, sin notificaciones: 27 s, modo `claude`, sin plan B. Las tres dudas quedaron resueltas: el login funciona desde un servicio, los nombres `mcp__pc-doctor__<tool>` son correctos y el modelo usó las tools (el contenido coincide con la base: contadores de `sdb`, sesión de juego, único paquete nuevo, `ttyd`, aviso de correo de `smartd`). Declaró que la línea base no es madura y que solo hay 5 horas de datos, en vez de inventar tendencias. Archivo: `datos/reportes/2026-10-28.md`.
  <!-- item {"id":181,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Problema detectado en esa ejecución: el reporte recomendaba revisar a mano los ventiladores `fan1/3/4/5/6`","modulos":["reporte","salud"]} -->
- **Problema detectado en esa ejecución:** el reporte recomendaba revisar a mano los ventiladores `fan1/3/4/5/6`. Eran las 5 alertas críticas falsas de la primera corrida con los sensores nuevos (conectores vacíos, bug ya corregido), que seguían en `alertas_salud`. El modelo no tiene forma de saber que eran falsas. Se borraron esas 5 filas (todas ya resueltas) y quedó registro en `acciones` (`limpieza_falsos_positivos`). Esa recomendación del primer reporte es errónea; el archivo se dejó tal cual salió.
  <!-- item {"id":182,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Observación sobre el modelo: señaló una diferencia entre el máximo de CPU de la sesión (81,75 °C, sensor `Tccd1`) y…","modulos":["reporte"]} -->
- **Observación sobre el modelo:** señaló una diferencia entre el máximo de CPU de la sesión (81,75 °C, sensor `Tccd1`) y las lecturas listadas (72,9 °C, `Tctl`). No es un error: son sensores distintos, y el resumen de sesiones usa el máximo de todos los de CPU.

## Nivel nuevo 4: dashboard interactivo (pedido del usuario, en fases)

<!-- entrada {"id":38,"seccion":"Nivel nuevo 4: dashboard interactivo (pedido del usuario, en fases)","titulo":"Introducción","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":183,"tipo":"pendiente","vigencia":"vigente","fecha":"2026-10-28","resumen":"Pendiente: diagnóstico automático por alertas (la tabla `diagnosticos` aún no existe)","modulos":["dashboard"]} -->
El usuario pidió una app web local (FastAPI + React/Vite/TypeScript + Recharts) para ver y gestionar lo que pc-doctor diagnostica, en 5 fases con parada y OK al final de cada una. La Fase 4 original del nivel anterior (diagnóstico automático por alertas) queda **pendiente**; mientras tanto la sección "diagnósticos" del dashboard mostrará "no disponible todavía" porque la tabla `diagnosticos` no existe.
  <!-- item {"id":378,"tipo":"pendiente","vigencia":"vigente","fecha":"2026-10-29","resumen":"Pendiente: fases 4 y 5 del dashboard (acciones y pantalla de configuración); hoy es de solo lectura","modulos":["dashboard"]} -->
- **Pendiente:** las fases 4 y 5 del dashboard (las acciones y la pantalla de configuración). Hoy es de solo lectura: la edición de los hechos conocidos y el botón de las notificaciones (`boton_dashboard`) esperan a esa fase.

### Fase 0: prerequisitos
_2026-10-28 · nota_
<!-- entrada {"id":39,"seccion":"Nivel nuevo 4: dashboard interactivo (pedido del usuario, en fases)","titulo":"Fase 0: prerequisitos","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":184,"tipo":"decision","vigencia":"superada","fecha":"2026-10-28","resumen":"Node y npm no están instalados (`node`, `npm`, `npx` no existen; tampoco fnm, volta, nvm, bun ni pnpm)","modulos":["dashboard","infra"],"reemplazada_por":189,"motivo":"Node 24.22.2 se instaló aislado en datos/node (opción A, elegida por el usuario)."} -->
- **Node y npm no están instalados** (`node`, `npm`, `npx` no existen; tampoco fnm, volta, nvm, bun ni pnpm). Por pedido del usuario no se instaló nada y se le presentaron opciones. El repositorio de Ubuntu ofrece `nodejs 18.19.1` y `npm 9.2.0`; Node 18 terminó su soporte en abril de 2025, así que no sirve para versiones actuales de Vite.
  (superada por #189: Node 24.22.2 se instaló aislado en datos/node (opción A, elegida por el usuario).)
  <!-- item {"id":185,"tipo":"decision","vigencia":"historica","fecha":"2026-10-28","resumen":"Puerto 8787: libre (nada escucha). El servicio irá solo en `127.0.0.1`","modulos":["dashboard"]} -->
- **Puerto 8787:** libre (nada escucha). El servicio irá solo en `127.0.0.1`.
  <!-- item {"id":186,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Dependencias de Python: `fastapi 0.162.0` y `uvicorn 0.54.0` agregadas con `uv add` (solo el entorno del proyecto, sin…","modulos":["dashboard","datos","mcp"]} -->
- **Dependencias de Python:** `fastapi 0.162.0` y `uvicorn 0.54.0` agregadas con `uv add` (solo el entorno del proyecto, sin sudo). Compatibilidad: el MCP sigue cargando sus 22 tools y el recolector importa bien.
  <!-- item {"id":187,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Convención de archivos con punto: `package.json`, `tsconfig.json` y `vite.config.ts` no llevan punto, así que no hace…","modulos":["dashboard","git"],"archivos":[".gitignore"]} -->
- **Convención de archivos con punto:** `package.json`, `tsconfig.json` y `vite.config.ts` no llevan punto, así que no hace falta preguntar nada por ahora. Se arma el proyecto de Vite a mano para evitar el `.gitignore` que genera la plantilla (el proyecto no es un repositorio git). `node_modules/` será visible y grande (cientos de MB) dentro de `web/frontend/`.
  <!-- item {"id":188,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Tablas existentes que alimentan el dashboard: `lecturas`, `lecturas_diarias`, `linea_base`, `metricas`…","modulos":["dashboard","datos"]} -->
- **Tablas existentes que alimentan el dashboard:** `lecturas`, `lecturas_diarias`, `linea_base`, `metricas`, `alertas_salud`, `hallazgos_seguridad`, `escuchas`, `eventos`, `snapshot_entorno`/`hardware`/`software`, `sesiones_actividad`, `reportes`, `acciones`, `cuarentena`, `notificaciones`. No existe `diagnosticos`.

### Node instalado (opción A, elegida por el usuario)
_2026-10-28 · nota_
<!-- entrada {"id":40,"seccion":"Nivel nuevo 4: dashboard interactivo (pedido del usuario, en fases)","titulo":"Node instalado (opción A, elegida por el usuario)","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":189,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Tarball oficial `node-v24.22.2-linux-x64.tar.xz` (32 MB) de nodejs.org","modulos":["dashboard"]} -->
- Tarball oficial `node-v24.22.2-linux-x64.tar.xz` (32 MB) de nodejs.org. SHA-256 verificado contra `SHASUMS256.txt` (coincide: `48cc0e21...aaf75`). Limitación honesta: el checksum viene del mismo sitio, así que protege contra una descarga corrupta, no contra un compromiso del sitio; no se verificó la firma GPG.
  <!-- item {"id":190,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Instalado en `~/.local/share/pc-doctor/node/` (visible desde `datos/node/`, 208 MB). Node 24.22.2 y npm 11.19.1","modulos":["dashboard","infra","sistema"],"archivos":["web/construir.sh","~/.local/share/pc-doctor/node/"]} -->
- Instalado en `~/.local/share/pc-doctor/node/` (visible desde `datos/node/`, 208 MB). Node 24.22.2 y npm 11.19.1. **No está en el PATH global**: solo lo usará `web/construir.sh`, que lo agrega al PATH de su propio proceso. Se desinstala borrando esa carpeta.

### Fase 1 del dashboard: API de solo lectura (`web/api.py`)

#### Decisiones
_2026-10-28 · decision_
<!-- entrada {"id":41,"seccion":"Nivel nuevo 4: dashboard interactivo (pedido del usuario, en fases) / Fase 1 del dashboard: API de solo lectura (`web/api.py`)","titulo":"Decisiones","fecha":"2026-10-28","tipo":"decision"} -->

<!-- item {"id":191,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Un módulo compartido, `consultas.py`, para que el dashboard y el MCP muestren exactamente lo mismo","modulos":["dashboard","datos","mcp"],"archivos":["consultas.py","server.py"]} -->
- **Un módulo compartido, `consultas.py`, para que el dashboard y el MCP muestren exactamente lo mismo.** Las funciones de consulta (alertas, hallazgos, sesiones, estado en vivo, componentes, series, bandas, aprendizaje) salieron de las tools de `server.py` a este módulo, sin dependencias de FastMCP ni de FastAPI. Las tools ahora son envoltorios finos que recortan el resultado para el chat. Comprobado: la salida de las tools antes y después del refactor es idéntica (14 de 16 consultas iguales; las dos que diferían eran un dato nuevo del recolector y el orden de elementos con la misma hora, ya desempatado), y una prueba compara la API contra las tools sobre la misma base (12 comparaciones, 0 diferencias).
  <!-- item {"id":192,"tipo":"invariante","vigencia":"vigente","fecha":"2026-10-28","resumen":"La API de lectura abre la base con mode=ro (db.SOLO_LECTURA) y no toca el esquema","modulos":["dashboard","datos"],"prueba":"tests/test_api.py::test_la_conexion_de_la_api_rechaza_cualquier_escritura"} -->
- **Solo lectura de verdad, no por convención.** `db.SOLO_LECTURA` hace que `db.conectar()` abra la base con `mode=ro` y no toque el esquema; la API lo activa al importarse. Las acciones de la Fase 4 deberán pedir `escribir=True` de forma explícita. Comprobado: `INSERT`, `UPDATE`, `DELETE`, `DROP` y `CREATE` a través de la conexión de la API fallan con "attempt to write a readonly database", y el hash de la base no cambió tras ejecutar todas las pruebas.
  **(invariante · prueba: tests/test_api.py::test_la_conexion_de_la_api_rechaza_cualquier_escritura)**
  <!-- item {"id":193,"tipo":"invariante","vigencia":"vigente","fecha":"2026-10-28","resumen":"El dashboard escucha solo en 127.0.0.1 y rechaza todo Host que no sea localhost:PUERTO o 127.0.0.1:PUERTO","modulos":["dashboard"],"prueba":"tests/test_api.py::test_solo_se_aceptan_los_host_locales_contra_dns_rebinding"} -->
- **Seguridad desde el primer día, no recién en la Fase 4:** solo `127.0.0.1`; se rechaza toda petición cuyo `Host` no sea `localhost:PUERTO` o `127.0.0.1:PUERTO` (421), lo que evita que una página externa lea los datos por DNS rebinding; solo se acepta `GET` (cualquier otro método da 405); `Cache-Control: no-store`, `X-Content-Type-Options`, `X-Frame-Options: DENY` y `Referrer-Policy`; sin cabeceras CORS. `/docs` y `/openapi.json` desactivados. El puerto se puede cambiar con `PC_DOCTOR_PUERTO` (las pruebas lo usan).
  **(invariante · prueba: tests/test_api.py::test_solo_se_aceptan_los_host_locales_contra_dns_rebinding)**
  <!-- item {"id":194,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Bandas coherentes con las alarmas","modulos":["dashboard","salud"]} -->
- **Bandas coherentes con las alarmas.** `linea_base.limites()` es ahora la única definición de "fuera de lo habitual" y la usan la detección de anomalías y el gráfico. Comprobado contra la implementación anterior con 24.000 casos aleatorios: 0 diferencias (en el borde exacto el resultado depende de la coma flotante, de forma irrelevante). La banda que devuelve la API tiene dos niveles: la zona típica (mediana ± 2 desvíos robustos) y los límites de anomalía (los que realmente disparan un aviso, que además exigen un cambio mínimo según el tipo de sensor). Los puntos de la serie traen `f` (fuera de los límites de su contexto) solo si esa línea base es madura.
  <!-- item {"id":195,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Series: hasta 30 días usa las lecturas crudas, agrupadas en intervalos si pasan de 800 puntos (con mínimo y máximo de…","modulos":["actividad","salud"]} -->
- **Series:** hasta 30 días usa las lecturas crudas, agrupadas en intervalos si pasan de 800 puntos (con mínimo y máximo de cada intervalo); sobre 30 días usa `lecturas_diarias` y solo las crudas de hoy. Cada punto lleva el contexto (`c`) y el juego en curso (`a`) para el tooltip.
  <!-- item {"id":196,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Componentes: las lecturas se agrupan en cpu, gpu, ram, un componente por disco físico (más \"Particiones\")…","modulos":["dashboard","salud"]} -->
- **Componentes:** las lecturas se agrupan en cpu, gpu, ram, un componente por disco físico (más "Particiones"), ventiladores y voltajes por chip, y placa. El título de los discos sale del hardware del último snapshot; el de la GPU se extrae de la descripción de `lspci` para cualquier fabricante (`nombre_gpu`). Cada sensor trae estado (normal, aviso, crítico), referencia (aprendida, aprendiendo, fija o ninguna) y si está dentro de la banda de su contexto actual. Cada tarjeta resume `segun_linea_base` (dentro, fuera, aprendiendo, sin referencia).
  <!-- item {"id":197,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Fuentes ausentes: una sección cuya tabla no existe, o una instalación sin base, devuelve `{\"disponible\": false…","modulos":["correlacion","dashboard"]} -->
- **Fuentes ausentes:** una sección cuya tabla no existe, o una instalación sin base, devuelve `{"disponible": false, "mensaje": "No disponible todavía: ..."}` con HTTP 200 en vez de un error. La línea de tiempo sigue funcionando si falta alguna de sus fuentes. `diagnosticos` siempre responde así hasta que exista esa función.
  <!-- item {"id":198,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Lectura en vivo con caché de 20 s: `/estado`, `/componentes/*` y `/limitaciones` comparten una sola lectura de…","modulos":["dashboard","salud"]} -->
- **Lectura en vivo con caché de 20 s:** `/estado`, `/componentes/*` y `/limitaciones` comparten una sola lectura de sensores (incluye SMART por `sudo`), para que varias pestañas o el refresco automático no la repitan.
  <!-- item {"id":199,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Configuración: `/api/config` devuelve `config.json` sin secretos (los campos cuyo nombre sugiere clave, token o…","modulos":["dashboard"]} -->
- **Configuración:** `/api/config` devuelve `config.json` sin secretos (los campos cuyo nombre sugiere clave, token o contraseña salen como `{"cargada": true|false}`), más la configuración efectiva del reporte. `reputacion.cargar_config(crear=False)` evita que una consulta cree el archivo.
  <!-- item {"id":200,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Datos de prueba: `web/datos_de_prueba.py CARPETA` genera una base sintética (120 días de lecturas, 30 crudos y el…","modulos":["actividad","dashboard","salud"]} -->
- **Datos de prueba:** `web/datos_de_prueba.py CARPETA` genera una base sintética (120 días de lecturas, 30 crudos y el resto como registro diario, línea base madura, 60 sesiones de juego, alertas, hallazgos, eventos, reportes, 3 snapshots y una configuración con un secreto falso). Se niega a escribir en la carpeta de datos real o en una base existente. Sirve para probar la API ahora y para desarrollar el frontend.

#### Errores encontrados y corregidos
_2026-10-28 · error_
<!-- entrada {"id":42,"seccion":"Nivel nuevo 4: dashboard interactivo (pedido del usuario, en fases) / Fase 1 del dashboard: API de solo lectura (`web/api.py`)","titulo":"Errores encontrados y corregidos","fecha":"2026-10-28","tipo":"error"} -->

<!-- item {"id":201,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Título de la GPU `AMD/ATI` (tomaba el primer grupo entre corchetes) y RAM de 33,5 GB (GB decimales","modulos":["dashboard"]} -->
- Título de la GPU `AMD/ATI` (tomaba el primer grupo entre corchetes) y RAM de 33,5 GB (GB decimales; el equipo informa 31,2 GiB).
  <!-- item {"id":202,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"La tarjeta no decía si el valor era normal según la línea base del contexto actual","modulos":["dashboard","salud"]} -->
- La tarjeta no decía si el valor era normal según la línea base del contexto actual.
  <!-- item {"id":203,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Un ventilador a 0 RPM con historia de giro se mostraba como \"gira\"; ahora `giro` es `gira`, `parado` o `vacio`","modulos":["dashboard","salud"]} -->
- Un ventilador a 0 RPM con historia de giro se mostraba como "gira"; ahora `giro` es `gira`, `parado` o `vacio`.
  <!-- item {"id":204,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"La estimación de \"días para madurar\" no tenía sentido para `carga` y `juego` (depende del uso): se quitó, con…","modulos":["actividad","dashboard"]} -->
- La estimación de "días para madurar" no tenía sentido para `carga` y `juego` (depende del uso): se quitó, con `depende_del_uso`.
  <!-- item {"id":205,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Dos tarjetas \"Ventiladores\" idénticas (GPU y placa): el título ahora lleva el chip","modulos":["dashboard","salud"]} -->
- Dos tarjetas "Ventiladores" idénticas (GPU y placa): el título ahora lleva el chip.
  <!-- item {"id":206,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"`correlacion/{id}` sin base daba 503 en lugar de \"no disponible\"","modulos":["correlacion","dashboard"]} -->
- `correlacion/{id}` sin base daba 503 en lugar de "no disponible".
  <!-- item {"id":207,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Línea de tiempo: los elementos con la misma hora salían en orden variable; se agregó un desempate","modulos":["correlacion","dashboard"]} -->
- Línea de tiempo: los elementos con la misma hora salían en orden variable; se agregó un desempate.
  <!-- item {"id":208,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Mi propio `pkill -f` coincidió con el texto del comando y cerró mi shell; ahora se apaga por PID","modulos":["dashboard"]} -->
- Mi propio `pkill -f` coincidió con el texto del comando y cerró mi shell; ahora se apaga por PID.

#### Pruebas (base temporal; la real solo se leyó)
_2026-10-28 · prueba_
<!-- entrada {"id":43,"seccion":"Nivel nuevo 4: dashboard interactivo (pedido del usuario, en fases) / Fase 1 del dashboard: API de solo lectura (`web/api.py`)","titulo":"Pruebas (base temporal; la real solo se leyó)","fecha":"2026-10-28","tipo":"prueba"} -->

<!-- item {"id":209,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"27 endpoints con HTTP 200; 9 casos de `Host`, 6 métodos, 23 parámetros inválidos, inyección SQL en el nombre del…","modulos":["dashboard"]} -->
27 endpoints con HTTP 200; 9 casos de `Host`, 6 métodos, 23 parámetros inválidos, inyección SQL en el nombre del sensor, recorrido de rutas en reportes (`../`, `%2f`), cabeceras; base de una versión anterior (sin 3 tablas) y carpeta sin base; 384 peticiones en paralelo (8 hilos) mientras otro proceso escribía, sin errores (mediana 17 ms, p95 208 ms); lectura de la base real con datos verdaderos y base real intacta (hash y fecha idénticos). Consumo del servidor en reposo: 61 MB de RAM al arrancar (69 MB tras usar los endpoints) y 0,05 % de un núcleo. Las pruebas de las fases anteriores del MCP siguen pasando.

#### Limitaciones
_2026-10-28 · limitacion_
<!-- entrada {"id":44,"seccion":"Nivel nuevo 4: dashboard interactivo (pedido del usuario, en fases) / Fase 1 del dashboard: API de solo lectura (`web/api.py`)","titulo":"Limitaciones","fecha":"2026-10-28","tipo":"limitacion"} -->

<!-- item {"id":210,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"La primera lectura en vivo tarda ~1,5 s (SMART por `sudo` más el muestreo de E/S)","modulos":["dashboard","salud"]} -->
- La primera lectura en vivo tarda ~1,5 s (SMART por `sudo` más el muestreo de E/S); las siguientes, dentro de los 20 s, son inmediatas.
  <!-- item {"id":211,"tipo":"limitacion","vigencia":"historica","fecha":"2026-10-28","resumen":"Con la base real, la línea base todavía no es madura: todas las tarjetas dicen \"aprendiendo\" y las bandas aparecerán…","modulos":["actividad","salud"]} -->
- Con la base real, la línea base todavía no es madura: todas las tarjetas dicen "aprendiendo" y las bandas aparecerán con los días. En `juego` hacen falta unas 50 horas de juego.
  <!-- item {"id":212,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"Un disco se identifica por su nombre de dispositivo (`sda`, `sdb`): si el sistema reasigna los nombres tras un…","modulos":["dashboard","salud"]} -->
- Un disco se identifica por su nombre de dispositivo (`sda`, `sdb`): si el sistema reasigna los nombres tras un reinicio, el historial de sensores seguirá con el nombre anterior.
  <!-- item {"id":213,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"La API no tiene autenticación en las lecturas: cualquier proceso local del mismo equipo puede leerlas","modulos":["dashboard","salud"]} -->
- La API no tiene autenticación en las lecturas: cualquier proceso local del mismo equipo puede leerlas. La protección es de red (solo localhost) y de navegador (Host, sin CORS).

### Fase 2 del dashboard: frontend (`web/frontend/`)

#### Decisiones
_2026-10-28 · decision_
<!-- entrada {"id":45,"seccion":"Nivel nuevo 4: dashboard interactivo (pedido del usuario, en fases) / Fase 2 del dashboard: frontend (`web/frontend/`)","titulo":"Decisiones","fecha":"2026-10-28","tipo":"decision"} -->

<!-- item {"id":214,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Stack y versiones (fijadas por `package-lock.json`): React 19.3.1, Recharts 3.10.1, react-markdown 10.1 con remark-gfm…","modulos":["dashboard"]} -->
- **Stack y versiones** (fijadas por `package-lock.json`): React 19.3.1, Recharts 3.10.1, react-markdown 10.1 con remark-gfm 4.0, Vite 7.3.7, `@vitejs/plugin-react` 5.2, TypeScript 5.9.3. Elegí Vite 7 y TypeScript 5.9 en vez de lo último de npm (Vite 8, TypeScript 7 con compilador nuevo) por ser lo más probado, y comprobé que los rangos de dependencias de pares encajan. `npm audit`: 0 vulnerabilidades (también solo producción).
  <!-- item {"id":215,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Proyecto armado a mano: sin la plantilla de Vite, que trae un `.gitignore`","modulos":["dashboard","git"],"archivos":[".gitignore"]} -->
- **Proyecto armado a mano**: sin la plantilla de Vite, que trae un `.gitignore`. No se creó ningún archivo con punto, así que no hizo falta preguntar. npm 11 bloqueó el script de instalación de `esbuild` (no figura en `allowScripts`) y la compilación funciona igual, así que no se habilitó. `node_modules/` ocupa 122 MB y es visible dentro de `web/frontend/`.
  <!-- item {"id":216,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Una sola página con 8 secciones: encabezado, tarjetas de estado, vista de detalle, alertas y hallazgos, línea de…","modulos":["dashboard"]} -->
- **Una sola página con 8 secciones**: encabezado, tarjetas de estado, vista de detalle, alertas y hallazgos, línea de tiempo (con la tabla de sesiones de juego), reportes y diagnósticos, limitaciones y sensores, entorno. Enrutado propio mínimo con la API de historial (`/`, `/componente/{tipo}?id=&sensor=` y `/alerta/{id}`): el servidor ya devuelve la misma página para esas rutas, así que los enlaces directos de la Fase 3 funcionan desde ahora.
  <!-- item {"id":217,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Un reloj de 60 s (`tick`) que reactiva todos los pedidos sin recargar la página","modulos":["dashboard"]} -->
- **Un reloj de 60 s** (`tick`) que reactiva todos los pedidos sin recargar la página. Con la pestaña oculta no se pide nada, y al volver se actualiza si pasó más de un minuto. La hora de la última actualización exitosa figura en el encabezado, con un botón "Actualizar". Si un pedido falla se conservan los últimos datos y se avisa una sola vez, arriba.
  <!-- item {"id":218,"tipo":"invariante","vigencia":"vigente","fecha":"2026-10-28","resumen":"En el dashboard el color nunca va solo: siempre con ícono y texto","modulos":["dashboard"]} -->
- **Colores con significado, nunca solos**: cada estado lleva color, ícono (círculo con tilde, triángulo, octógono con cruz) y texto; los puntos fuera de lo habitual son rombos, no solo un color distinto. Modo claro y oscuro según el sistema (variables CSS). Foco visible, enlace para saltar al contenido, `aria-pressed` en los selectores y descripción de texto del gráfico.
  **(invariante)**
  <!-- item {"id":219,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Gráfico: línea medida; detrás, la zona habitual aprendida (mediana ± 2 desvíos robustos) según el contexto de cada…","modulos":["actividad","dashboard"]} -->
- **Gráfico**: línea medida; detrás, la zona habitual aprendida (mediana ± 2 desvíos robustos) **según el contexto de cada punto** (por eso en "Todos" la banda cambia de altura entre reposo, carga y juego); con un contexto elegido, además, líneas punteadas con los límites de aviso. Rombos para lo que cae fuera de esos límites. El globo muestra valor, hora, contexto, juego en curso, mínimo y máximo si es un promedio diario, y lo habitual de ese contexto. Rangos: 24 h, 7, 30 días y 6 meses.
  <!-- item {"id":220,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Reportes: el Markdown se renderiza con react-markdown, que no interpreta HTML crudo, y los enlaces se abren en otra…","modulos":["dashboard","reporte"]} -->
- **Reportes**: el Markdown se renderiza con react-markdown, que no interpreta HTML crudo, y los enlaces se abren en otra pestaña con `noopener noreferrer nofollow`. Importa porque el texto lo redacta un modelo a partir de datos del equipo.
  <!-- item {"id":221,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Carga diferida: Recharts y el renderizador de Markdown pesaban casi todo el JavaScript (825 KB)","modulos":["dashboard","reporte"]} -->
- **Carga diferida**: Recharts y el renderizador de Markdown pesaban casi todo el JavaScript (825 KB). Con `React.lazy` el paquete inicial quedó en 251 KB (78 KB comprimido); el detalle (404 KB) y los reportes (168 KB) se bajan al usarlos.
  <!-- item {"id":222,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"`web/construir.sh`: usa el Node aislado de `datos/node` (o `PC_DOCTOR_NODE`), instala con `npm ci` si falta…","modulos":["dashboard"],"archivos":["web/construir.sh"]} -->
- **`web/construir.sh`**: usa el Node aislado de `datos/node` (o `PC_DOCTOR_NODE`), instala con `npm ci` si falta `node_modules` y compila a `web/frontend/dist/`. Sin sudo.
  <!-- item {"id":223,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Textos: español rioplatense, con mayúscula solo al inicio de cada frase (salvo nombres propios y de sensores)","modulos":["dashboard","salud"]} -->
- **Textos**: español rioplatense, con mayúscula solo al inicio de cada frase (salvo nombres propios y de sensores).

#### Errores encontrados y corregidos
_2026-10-28 · error_
<!-- entrada {"id":46,"seccion":"Nivel nuevo 4: dashboard interactivo (pedido del usuario, en fases) / Fase 2 del dashboard: frontend (`web/frontend/`)","titulo":"Errores encontrados y corregidos","fecha":"2026-10-28","tipo":"error"} -->

<!-- item {"id":224,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Con React 19 ya no existe el espacio de nombres global `JSX` (error de tipos); se usa `ReactElement`","modulos":["dashboard"]} -->
- Con React 19 ya no existe el espacio de nombres global `JSX` (error de tipos); se usa `ReactElement`.
  <!-- item {"id":225,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Choque de nombres entre un componente y un tipo `Estado`; el componente pasó a llamarse `Contenido`","modulos":["dashboard"]} -->
- Choque de nombres entre un componente y un tipo `Estado`; el componente pasó a llamarse `Contenido`.
  <!-- item {"id":226,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Un estado sin uso en la vista de detalle","modulos":["dashboard"]} -->
- Un estado sin uso en la vista de detalle.
  <!-- item {"id":227,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Dos errores de redacción que vi en las capturas: \"1 paquetes más\" (plural en `correlacion.py`) y \"salió sin redactar…","modulos":["correlacion","dashboard"],"archivos":["correlacion.py"]} -->
- Dos errores de redacción que vi en las capturas: "1 paquetes más" (plural en `correlacion.py`) y "salió sin redactar porque límite de uso…" (ahora "Motivo: …"); y un "todavía" repetido en el aviso de diagnósticos.
  <!-- item {"id":228,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Con la API caída cada sección repetía su propio aviso amarillo y el mensaje salía en inglés (\"Failed to fetch\")","modulos":["dashboard"]} -->
- Con la API caída cada sección repetía su propio aviso amarillo y el mensaje salía en inglés ("Failed to fetch"); ahora hay un solo aviso global en español y las secciones no lo repiten.
  <!-- item {"id":229,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"La banda del gráfico se veía tenue en el modo oscuro: subí su opacidad","modulos":["dashboard"]} -->
- La banda del gráfico se veía tenue en el modo oscuro: subí su opacidad.
  <!-- item {"id":230,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Brave sin interfaz (`\u002d\u002dheadless=new \u002d\u002dscreenshot`) se colgaba en este equipo","modulos":["dashboard"]} -->
- Brave sin interfaz (`--headless=new --screenshot`) se colgaba en este equipo; las capturas se sacaron con la extensión de Chrome sobre los datos de prueba. Mi `pkill -f` volvió a cerrar mi propia shell (coincidía con el texto del comando) hasta que usé el truco `[p]atrón`.

#### Pruebas
_2026-10-28 · prueba_
<!-- entrada {"id":47,"seccion":"Nivel nuevo 4: dashboard interactivo (pedido del usuario, en fases) / Fase 2 del dashboard: frontend (`web/frontend/`)","titulo":"Pruebas","fecha":"2026-10-28","tipo":"prueba"} -->

<!-- item {"id":231,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Compilación con `tsc` estricto sin errores; carga en el navegador real sin errores de consola","modulos":["dashboard"]} -->
- Compilación con `tsc` estricto sin errores; carga en el navegador real sin errores de consola.
  <!-- item {"id":232,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Recorrido visual con datos de prueba: tarjetas, detalle con gráfico (rangos y contextos), globo, rombos de fuera de lo…","modulos":["dashboard"]} -->
- Recorrido visual con datos de prueba: tarjetas, detalle con gráfico (rangos y contextos), globo, rombos de fuera de lo habitual, enlace directo `/alerta/4` (baja a la sección y abre las causas), línea de tiempo, reportes con tabla, código, cita y enlace, limitaciones y entorno.
  <!-- item {"id":233,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Actualización automática: sin recargar, pasó de 18:44 a 18:45 con un segundo pedido a `/api/estado`","modulos":["dashboard"]} -->
- **Actualización automática**: sin recargar, pasó de 18:44 a 18:45 con un segundo pedido a `/api/estado`.
  <!-- item {"id":234,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Servidor caído y recuperación: con la API apagada se conservan los datos y aparece un único aviso","modulos":["dashboard"]} -->
- **Servidor caído y recuperación**: con la API apagada se conservan los datos y aparece un único aviso; al volver y pulsar "Actualizar" desaparece y se actualiza la hora.
  <!-- item {"id":235,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Fuentes ausentes: con la base de una versión anterior (sin 3 tablas) las secciones afectadas dicen \"No disponible…","modulos":["dashboard"]} -->
- **Fuentes ausentes**: con la base de una versión anterior (sin 3 tablas) las secciones afectadas dicen "No disponible todavía" y el resto funciona; sin base, todas lo dicen; ninguna rompe la página.
  <!-- item {"id":236,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Diseño angosto y modo oscuro: se comprobaron aplicando a mano las reglas `@media` de la hoja de estilos (la extensión…","modulos":["dashboard"]} -->
- **Diseño angosto y modo oscuro**: se comprobaron aplicando a mano las reglas `@media` de la hoja de estilos (la extensión no pudo achicar la ventana real: su viewport era de 2560 px). Es una simulación fiel del CSS, pero no una ventana real de 420 px.
  <!-- item {"id":237,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Regresión: pruebas de las fases anteriores, API (0 fallos), API contra MCP (0 diferencias) y 384 peticiones…","modulos":["dashboard"]} -->
- Regresión: pruebas de las fases anteriores, API (0 fallos), API contra MCP (0 diferencias) y 384 peticiones concurrentes con escrituras simultáneas, todo sin errores.

#### Limitaciones
_2026-10-28 · limitacion_
<!-- entrada {"id":48,"seccion":"Nivel nuevo 4: dashboard interactivo (pedido del usuario, en fases) / Fase 2 del dashboard: frontend (`web/frontend/`)","titulo":"Limitaciones","fecha":"2026-10-28","tipo":"limitacion"} -->

<!-- item {"id":238,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"Las capturas de `web/capturas/` son de los datos sintéticos, no de los reales (con los reales todas las tarjetas…","modulos":["dashboard"]} -->
- Las capturas de `web/capturas/` son de los datos sintéticos, no de los reales (con los reales todas las tarjetas dirían "aprendiendo"); la 05 y la 06 son anteriores a la corrección de dos textos.
  <!-- item {"id":239,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"No se probó en una pantalla táctil ni con lector de pantalla; solo se revisó la estructura accesible por código","modulos":["dashboard"]} -->
- No se probó en una pantalla táctil ni con lector de pantalla; solo se revisó la estructura accesible por código.
  <!-- item {"id":240,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"Cada actualización de 60 s vuelve a pedir todas las secciones (unas 8 peticiones baratas), y la lectura en vivo con…","modulos":["dashboard"]} -->
- Cada actualización de 60 s vuelve a pedir todas las secciones (unas 8 peticiones baratas), y la lectura en vivo con SMART se repite cada minuto con la página abierta (la caché es de 20 s). Es poco, pero es más que el recolector (cada 15 min).
  <!-- item {"id":241,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"Sin base de datos, ocho secciones repiten el mismo aviso; es correcto pero redundante","modulos":["dashboard","datos"]} -->
- Sin base de datos, ocho secciones repiten el mismo aviso; es correcto pero redundante.
  <!-- item {"id":242,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"La banda con el contexto \"Todos\" tiene escalones cuando el equipo cambia de contexto: es fiel a los datos, pero puede…","modulos":["dashboard"]} -->
- La banda con el contexto "Todos" tiene escalones cuando el equipo cambia de contexto: es fiel a los datos, pero puede parecer discontinua.

### Fase 3 del dashboard: acceso (servicio, lanzador, PWA, enlaces directos, notificaciones con botón, tool del MCP)

#### Decisiones
_2026-10-28 · decision_
<!-- entrada {"id":49,"seccion":"Nivel nuevo 4: dashboard interactivo (pedido del usuario, en fases) / Fase 3 del dashboard: acceso (servicio, lanzador, PWA, enlaces directos, notificaciones con botón, tool del MCP)","titulo":"Decisiones","fecha":"2026-10-28","tipo":"decision"} -->

<!-- item {"id":243,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"`dashboard.py` es el único lugar que sabe armar la URL de una sección, comprobar si el dashboard responde, arrancarlo…","modulos":["dashboard"],"archivos":["dashboard.py"]} -->
- **`dashboard.py`** es el único lugar que sabe armar la URL de una sección, comprobar si el dashboard responde, arrancarlo y abrirlo. Lo usan el lanzador del menú, los botones de las notificaciones y la tool `abrir_dashboard` del MCP (ya son 23 tools). Acepta solo formas conocidas (`estado`, `alertas`, `linea-de-tiempo`, `reportes`, `limitaciones`, `entorno`, `alerta:N`, `hallazgo:N`, `componente:TIPO[:ID]`); cualquier otra cosa se rechaza, nunca se abre una URL arbitraria. Si el dashboard está apagado, lo arranca con `systemctl --user start pc-doctor-web.service` y espera hasta 15 s.
  <!-- item {"id":244,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Servicio `systemd/pc-doctor-web.service` (de usuario, `WantedBy=default.target` para que arranque con la sesión…","modulos":["dashboard","infra"],"archivos":["systemd/pc-doctor-web.service"]} -->
- **Servicio `systemd/pc-doctor-web.service`** (de usuario, `WantedBy=default.target` para que arranque con la sesión, `Restart=on-failure`, `RestartSec=5`, `Nice=10`, `MemoryMax=400M`; en reposo usa ~65 MB). Usa `uv run --frozen` para no resolver ni descargar nada al arrancar. **No** lleva `NoNewPrivileges` porque la lectura de SMART usa `sudo -n smartctl`. Validado con `systemd-analyze --user verify`. **No instalado: pendiente de aprobación del usuario.**
  <!-- item {"id":245,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Lanzador `web/pc-doctor.desktop` (con acciones \"Ver las alertas\" y \"Ver los reportes\"): su `Exec` llama a…","modulos":["alertas","dashboard","reporte","sistema"],"archivos":["web/pc-doctor.desktop","~/.local/share/applications/"]} -->
- **Lanzador `web/pc-doctor.desktop`** (con acciones "Ver las alertas" y "Ver los reportes"): su `Exec` llama a `dashboard.py abrir`, así que arranca el servicio si hace falta y después abre el navegador; si no puede, avisa con una notificación (sin terminal no habría otra forma de enterarse). Ruta absoluta de `/home/v` (los `Exec` no expanden `~` ni `%h`). Validado con `desktop-file-validate`. Se copiará a `~/.local/share/applications/` junto con el ícono. **No instalado.**
  <!-- item {"id":246,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Ícono propio: un pulso blanco sobre un cuadrado azul","modulos":["dashboard"],"archivos":["web/generar_iconos.py"]} -->
- **Ícono propio:** un pulso blanco sobre un cuadrado azul. `web/generar_iconos.py` (necesita Pillow) genera el SVG y los PNG de 180, 192 y 512 px, más una versión enmascarable de 512 con el pulso dentro de la zona segura.
  <!-- item {"id":247,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"PWA: `manifest.webmanifest` (nombre, `display: standalone`, `start_url` y `scope` `/`, íconos de 192 y 512 px, uno…","modulos":["dashboard","reporte"]} -->
- **PWA:** `manifest.webmanifest` (nombre, `display: standalone`, `start_url` y `scope` `/`, íconos de 192 y 512 px, uno enmascarable y el SVG, y atajos a alertas y reportes) con el tipo MIME correcto (`application/manifest+json`), `theme-color` para claro y oscuro e ícono en la cabecera. **Sin service worker, a propósito:** los datos tienen que ser siempre frescos y un caché los volvería viejos sin avisar. Si el navegador ofrece instalarla no depende de eso en Chrome y Edge actuales (no lo pude comprobar: ver limitaciones).
  <!-- item {"id":248,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Enlaces directos: además de `/alerta/{id}` y `/componente/{tipo}` (que ya funcionaban), se agregó `/hallazgo/{id}`…","modulos":["dashboard"]} -->
- **Enlaces directos:** además de `/alerta/{id}` y `/componente/{tipo}` (que ya funcionaban), se agregó `/hallazgo/{id}`, que abre la pestaña de hallazgos con ese hallazgo expandido (busca en 365 días).
  <!-- item {"id":249,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Notificaciones con botón \"Ver en el dashboard\": Comprobé que GNOME Shell 46 soporta acciones (anuncia `actions` y…","modulos":["alertas","dashboard"]} -->
- **Notificaciones con botón "Ver en el dashboard":**
  - Comprobé que GNOME Shell 46 soporta acciones (anuncia `actions` y `persistence`) y que `notify-send` 0.8.3 tiene `--action`.
  - Para recibir el clic hace falta un proceso vivo. El recolector termina enseguida y systemd mata lo que quede en su servicio, así que el escucha corre en una **unidad transitoria** (`systemd-run --user --collect`) con `RuntimeMaxSec=21600` (6 h): si nadie atiende la notificación, el escucha se cierra solo y el botón deja de funcionar. Tope de 10 escuchas vivos a la vez; pasado eso, las notificaciones salen sin botón.
  - Cada fuente pide su sección: salud abre **la alerta más grave** del aviso (`alerta:N`), seguridad el primer hallazgo (`hallazgo:N`), el reporte semanal `reportes`.
  - Al hacer clic, si el dashboard está apagado se arranca; si el servicio no está instalado o no arranca, sale una notificación simple que lo explica.
  - **Las notificaciones siguen funcionando igual con el dashboard apagado:** el botón es un extra. Se ofrece solo si la opción está activa, el escritorio lo soporta y hay cupo; en cualquier otro caso (o si `systemd-run` falla) sale la notificación de siempre, con el mismo contrato de retorno (False si no se pudo enviar, para reintentar).
  - Si la versión con botón falla dentro del escucha, este manda la simple: nunca se pierde un aviso por el botón.
  - **El botón está apagado por defecto** (`"boton_dashboard": false`) hasta que el usuario lo pruebe en su escritorio real; `uv run alertas.py --probar-boton` lo fuerza (esa prueba es real y se ve en pantalla).
  <!-- item {"id":250,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Alternativa si el botón no sirviera en el escritorio real: poner la dirección en el cuerpo de la notificación","modulos":["alertas","dashboard"]} -->
- **Alternativa si el botón no sirviera en el escritorio real:** poner la dirección en el cuerpo de la notificación. GNOME no anuncia `body-hyperlinks`, así que habría que comprobar si la hace clicable.

#### Errores encontrados y corregidos
_2026-10-28 · error_
<!-- entrada {"id":50,"seccion":"Nivel nuevo 4: dashboard interactivo (pedido del usuario, en fases) / Fase 3 del dashboard: acceso (servicio, lanzador, PWA, enlaces directos, notificaciones con botón, tool del MCP)","titulo":"Errores encontrados y corregidos","fecha":"2026-10-28","tipo":"error"} -->

<!-- item {"id":251,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Detección de juegos con un juego real (Crimson Desert bajo Proton), que las pruebas sintéticas no podían mostrar: el…","modulos":["actividad","dashboard"]} -->
- **Detección de juegos con un juego real (Crimson Desert bajo Proton), que las pruebas sintéticas no podían mostrar:** el recolector veía **tres juegos en vez de uno**. `CrimsonDesert` salía de un `sh -c "…steam-launch-wrapper… CrimsonDesert.exe…"` (el envoltorio con toda la línea de lanzamiento en un argumento), `xalia` es un ayudante de Steam Input que corre dentro de Proton, y `Crimson Desert Enhanced` era el nombre correcto. Correcciones: un `sh -c "…"` se trata como envoltorio y no como programa; un proceso de Wine descendiente de `reaper` pertenece a un juego de Steam ya identificado; `xalia` se agregó a los ejecutables auxiliares. Comprobado con el juego real en ejecución (devuelve exactamente uno) y con los argumentos reales como pruebas nuevas. La base real no recibió sesiones falsas: el juego arrancó justo después de la corrida de las 19:01 y el código se corrigió antes de la siguiente.
  <!-- item {"id":252,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Riesgo de pérdida de avisos: el código del botón ya estaba en producción (el recolector usa el código del proyecto)…","modulos":["dashboard","datos"]} -->
- **Riesgo de pérdida de avisos:** el código del botón ya estaba en producción (el recolector usa el código del proyecto) antes de probarlo en el escritorio real, y con la temperatura alta era probable una alerta real. Se agregó el respaldo del escucha y se apagó el botón por defecto.
  <!-- item {"id":253,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Un `pkill` de las pruebas coincidió con mi propio comando (ya conocido); se usa por PID","modulos":["dashboard"]} -->
- Un `pkill` de las pruebas coincidió con mi propio comando (ya conocido); se usa por PID.
  <!-- item {"id":254,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Carrera en una prueba de la tool: `xdg-open` se lanza sin esperarlo y se leyó su registro antes de tiempo","modulos":["dashboard"]} -->
- Carrera en una prueba de la tool: `xdg-open` se lanza sin esperarlo y se leyó su registro antes de tiempo.

#### Pruebas (reemplazos de `notify-send`, `xdg-open`, `gdbus`, `systemd-run` y `systemctl`; un servidor HTTP mínimo hace de dashboard; nada se ve en pantalla)
_2026-10-28 · prueba_
<!-- entrada {"id":51,"seccion":"Nivel nuevo 4: dashboard interactivo (pedido del usuario, en fases) / Fase 3 del dashboard: acceso (servicio, lanzador, PWA, enlaces directos, notificaciones con botón, tool del MCP)","titulo":"Pruebas (reemplazos de `notify-send`, `xdg-open`, `gdbus`, `systemd-run` y `systemctl`; un servidor HTTP mínimo hace de dashboard; nada se ve en pantalla)","fecha":"2026-10-28","tipo":"prueba"} -->

<!-- item {"id":255,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"16 comprobaciones de `url_de` (8 válidas, 8 inválidas: URL externas, `javascript:`, `//evil`, inyección, números…","modulos":["dashboard"]} -->
- 16 comprobaciones de `url_de` (8 válidas, 8 inválidas: URL externas, `javascript:`, `//evil`, inyección, números enormes, ids largos).
  <!-- item {"id":256,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Notificaciones: botón y clic con el dashboard activo (abre `/alerta/4`, urgencia crítica conservada, una sola unidad…","modulos":["alertas","dashboard"]} -->
- Notificaciones: botón y clic con el dashboard activo (abre `/alerta/4`, urgencia crítica conservada, una sola unidad con tope de vida); sin clic (no abre nada); el escritorio no anuncia acciones; `gdbus` falla; opción apagada; 10 escuchas vivos (y 9 todavía permiten el botón); `systemd-run` falla; sección inválida; sin sección (comportamiento de siempre, sin costo extra); `notify-send` roto (devuelve False); dashboard apagado al hacer clic (lo arranca, 0,9 s); servicio no instalado (avisa); título y mensaje con comillas, `$()`, saltos de línea, `%s`, HTML y caracteres no latinos llegan idénticos; la versión con botón falla (sale la simple); botón apagado por defecto y forzado.
  <!-- item {"id":257,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Cada fuente pide la sección correcta: salud → la alerta crítica entre dos; seguridad → el hallazgo","modulos":["dashboard"]} -->
- Cada fuente pide la sección correcta: salud → la alerta crítica entre dos; seguridad → el hallazgo.
  <!-- item {"id":258,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Tool `abrir_dashboard`: arranca el servicio, abre la URL correcta y rechaza secciones inválidas","modulos":["dashboard"]} -->
- Tool `abrir_dashboard`: arranca el servicio, abre la URL correcta y rechaza secciones inválidas.
  <!-- item {"id":259,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Manifest: tipo MIME, 4 íconos con tamaños reales iguales a los declarados, requisitos de instalación (192, 512 y…","modulos":["dashboard"]} -->
- Manifest: tipo MIME, 4 íconos con tamaños reales iguales a los declarados, requisitos de instalación (192, 512 y enmascarable) y `start_url` dentro del alcance. `/hallazgo/2` en el navegador: abre la pestaña y el hallazgo.
  <!-- item {"id":260,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Regresión: pruebas de las fases anteriores, API (0 fallos), API contra MCP (0 diferencias)","modulos":["dashboard"]} -->
- Regresión: pruebas de las fases anteriores, API (0 fallos), API contra MCP (0 diferencias).

#### Limitaciones
_2026-10-28 · limitacion_
<!-- entrada {"id":52,"seccion":"Nivel nuevo 4: dashboard interactivo (pedido del usuario, en fases) / Fase 3 del dashboard: acceso (servicio, lanzador, PWA, enlaces directos, notificaciones con botón, tool del MCP)","titulo":"Limitaciones","fecha":"2026-10-28","tipo":"limitacion"} -->

<!-- item {"id":261,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"El botón no se probó todavía en el escritorio real (requiere hacer clic en una notificación verdadera): por eso está…","modulos":["alertas","dashboard"]} -->
- **El botón no se probó todavía en el escritorio real** (requiere hacer clic en una notificación verdadera): por eso está apagado por defecto. Tampoco sé cómo se comporta GNOME con el escucha: con `persistence` la notificación queda en la bandeja y el escucha espera hasta 6 h; si GNOME cerrara la notificación al vencer el aviso, el botón dejaría de responder antes.
  <!-- item {"id":262,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"Un escucha vivo por notificación sin atender (hasta 6 h, ~20 MB cada uno, máximo 10)","modulos":["alertas","dashboard"]} -->
- Un escucha vivo por notificación sin atender (hasta 6 h, ~20 MB cada uno, máximo 10).
  <!-- item {"id":263,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"La instalación como app (PWA) no se pudo comprobar: la extensión de Chrome no permite disparar ni observar el aviso de…","modulos":["dashboard"]} -->
- La instalación como app (PWA) no se pudo comprobar: la extensión de Chrome no permite disparar ni observar el aviso de instalación. El manifest cumple los requisitos; la instalación se hace desde el menú del navegador.
  <!-- item {"id":264,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"El ícono del lanzador se tomará del SVG instalado en `~/.local/share/icons/hicolor/scalable/apps/`","modulos":["dashboard","sistema"],"archivos":["~/.local/share/icons/hicolor/scalable/apps/"]} -->
- El ícono del lanzador se tomará del SVG instalado en `~/.local/share/icons/hicolor/scalable/apps/`; algunos escritorios necesitan reiniciar la sesión para mostrarlo.

#### Instalación (aprobada por el usuario) y estado final de la Fase 3
_2026-10-28 · nota_
<!-- entrada {"id":53,"seccion":"Nivel nuevo 4: dashboard interactivo (pedido del usuario, en fases) / Fase 3 del dashboard: acceso (servicio, lanzador, PWA, enlaces directos, notificaciones con botón, tool del MCP)","titulo":"Instalación (aprobada por el usuario) y estado final de la Fase 3","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":265,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Instalados: `~/.config/systemd/user/pc-doctor-web.service` (habilitado y activo)…","modulos":["infra","sistema"],"archivos":["~/.config/systemd/user/pc-doctor-web.service","~/.local/share/applications/pc-doctor.desktop","~/.local/share/icons/hicolor/scalable/apps/pc-doctor.svg"]} -->
- Instalados: `~/.config/systemd/user/pc-doctor-web.service` (habilitado y activo), `~/.local/share/applications/pc-doctor.desktop` y el ícono en `~/.local/share/icons/hicolor/scalable/apps/pc-doctor.svg` (con `update-desktop-database` y `gtk-update-icon-cache`).
  <!-- item {"id":266,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Verificado: escucha solo en `127.0.0.1:8787` (desde la IP de la LAN no responde), `Host` ajeno da 421, `/`…","modulos":["dashboard"]} -->
- Verificado: escucha solo en `127.0.0.1:8787` (desde la IP de la LAN no responde), `Host` ajeno da 421, `/`, `/api/estado`, el manifest y `/alerta/1` responden 200, y con tus datos reales devuelve el estado en vivo. Consumo del servicio: 58 MB de RAM en total (cgroup).
  <!-- item {"id":267,"tipo":"pendiente","vigencia":"vigente","fecha":"2026-10-28","resumen":"Pendiente: el usuario prueba el botón de las notificaciones con `alertas.py \u002d\u002dprobar-boton` y lo activa","modulos":["alertas","dashboard"]} -->
- **No se hizo la prueba real del botón: la hace el usuario.** `uv run alertas.py --probar-boton` envía una notificación real con el botón. Si funciona, se activa con `"boton_dashboard": true` en `config.json` (o la pantalla de configuración de la Fase 4). Hasta entonces las notificaciones salen simples, como siempre.
  <!-- item {"id":268,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"No se abrió el lanzador desde mi lado, para no abrir ventanas en tu pantalla sin que lo pidieras","modulos":["dashboard"]} -->
- No se abrió el lanzador desde mi lado, para no abrir ventanas en tu pantalla sin que lo pidieras.

#### Ícono en el escritorio (pedido del usuario)
_2026-10-28 · nota_
<!-- entrada {"id":54,"seccion":"Nivel nuevo 4: dashboard interactivo (pedido del usuario, en fases) / Fase 3 del dashboard: acceso (servicio, lanzador, PWA, enlaces directos, notificaciones con botón, tool del MCP)","titulo":"Ícono en el escritorio (pedido del usuario)","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":269,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Copia del lanzador en `~/Desktop/pc-doctor.desktop`, ejecutable y marcado como confiable (`gio set","modulos":["dashboard","sistema"],"archivos":["web/pc-doctor.desktop","~/Desktop/pc-doctor.desktop"]} -->
- Copia del lanzador en `~/Desktop/pc-doctor.desktop`, ejecutable y marcado como confiable (`gio set ... metadata::trusted true`; sin eso GNOME no deja abrirlo con doble clic). Usa la ruta absoluta del ícono SVG, que el escritorio resuelve con más seguridad que el nombre del tema. Es una copia de `web/pc-doctor.desktop`: si ese archivo cambia, hay que volver a copiarlo.

## Nivel nuevo 5: flujo de git automatizado (pedido del usuario, en fases)

<!-- entrada {"id":55,"seccion":"Nivel nuevo 5: flujo de git automatizado (pedido del usuario, en fases)","titulo":"Introducción","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":270,"tipo":"invariante","vigencia":"vigente","fecha":"2026-10-28","resumen":"Sin archivos con punto (salvo .gitignore, .git/, .github/ y lo que git necesite), sin sudo y sin tocar la base real","modulos":["git"],"archivos":[".gitignore","CLAUDE.md"]} -->
El usuario subió el proyecto a GitHub (`origin/main`, un commit inicial) y pidió automatizar el flujo de cambios en 4 fases con parada y OK al final de cada una: suite de pruebas permanente, hook pre-commit, regla de commits en `CLAUDE.md` y GitHub Actions. **Excepción a la convención de archivos con punto, autorizada por el usuario:** `.gitignore`, `.git/`, `.github/` y lo que git necesite. Además: no usar `sudo`, no tocar la base real ni los servicios instalados.
**(invariante)**

### Fase 1: suite de pruebas permanente (`tests/`)

#### Decisiones
_2026-10-28 · decision_
<!-- entrada {"id":56,"seccion":"Nivel nuevo 5: flujo de git automatizado (pedido del usuario, en fases) / Fase 1: suite de pruebas permanente (`tests/`)","titulo":"Decisiones","fecha":"2026-10-28","tipo":"decision"} -->

<!-- item {"id":271,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"pytest 9.2 y pytest-cov 7.1 como dependencias de desarrollo (`uv add \u002d\u002ddev`)","modulos":["git","infra"],"archivos":["pyproject.toml"]} -->
- **pytest 9.2 y pytest-cov 7.1** como dependencias de desarrollo (`uv add --dev`); `httpx` ya estaba (lo trae `mcp`) y lo usa el cliente de pruebas de FastAPI. Configuración en `pyproject.toml`: `testpaths`, `pythonpath`, dos marcadores y la cobertura. `uv run pytest` corre todo.
  <!-- item {"id":272,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Se rescataron las pruebas de verdad, no se reescribieron de cero. Las de las fases recientes estaban en el scratchpad","modulos":["actividad","git","salud"]} -->
- **Se rescataron las pruebas de verdad, no se reescribieron de cero.** Las de las fases recientes estaban en el scratchpad; las de las primeras etapas (reglas de salud, línea base, deriva, SMART, migración, regresión) ya no existían como archivos, pero cada script que se ejecutó quedó en la transcripción de la conversación, así que se extrajeron de ahí. Las pruebas pasaron de scripts con `print` a funciones de pytest con fixtures y parámetros (los casos repetidos son ahora parametrizados: por ejemplo, 25 líneas de comandos de juegos o 23 parámetros inválidos de la API).
  <!-- item {"id":273,"tipo":"invariante","vigencia":"vigente","fecha":"2026-10-28","resumen":"Las pruebas nunca tocan la base ni la configuración reales ni el hardware (salvo @pytest.mark.local)","modulos":["git"],"archivos":["tests/conftest.py","~/.local/bin/claude","~/.steam"],"prueba":"tests/conftest.py::pytest_sessionstart"} -->
- **Aislamiento total, en `tests/conftest.py`, antes de importar cualquier módulo del proyecto:** carpeta de datos y `HOME` temporales (así `Path.home()` apunta a una carpeta vacía y nada lee `~/.steam`, `~/.local/bin/claude` ni la base real), `PATH` con los reemplazos de `tests/falsos/` al principio (`notify-send`, `systemd-run`, `systemctl`, `gdbus`, `xdg-open`, `claude`), puerto de pruebas 8795 (nunca el 8787 del dashboard real) y una barrera al iniciar la sesión que aborta todo si la carpeta de datos apuntara a la real. En cada prueba, `salud.leer_lecturas`, `actividad.detectar` y los juegos de Steam están reemplazados por datos sintéticos, salvo en las marcadas `local`.
  **(invariante · prueba: tests/conftest.py::pytest_sessionstart)**
  <!-- item {"id":274,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Marcadores: `local` (4 pruebas que leen sensores y procesos reales de esta PC","modulos":["git","salud"]} -->
- **Marcadores:** `local` (4 pruebas que leen sensores y procesos reales de esta PC; se saltean en CI con `-m "not local"`) y `lento` (189 pruebas que levantan procesos, esperan, crean repositorios git temporales o generan los datos sintéticos grandes; el pre-commit las saltea con `-m "not lento"`).
  <!-- item {"id":275,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Datos sintéticos compartidos: las pruebas de la API usan `web/datos_de_prueba.py`, que ahora acepta un segundo…","modulos":["dashboard","git"],"archivos":["web/datos_de_prueba.py"]} -->
- **Datos sintéticos compartidos:** las pruebas de la API usan `web/datos_de_prueba.py`, que ahora acepta un segundo argumento con la cantidad de días (45 en las pruebas, 120 por defecto).
  <!-- item {"id":276,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Una prueba específica contra regresiones de seguridad del reporte: inspecciona el código fuente de cada tool que se le…","modulos":["git","reporte"]} -->
- **Una prueba específica contra regresiones de seguridad del reporte:** inspecciona el código fuente de cada tool que se le permite a `claude -p` y falla si alguna tiene un efecto (escribir, mover archivos, consultar online); y verifica que toda tool permitida exista en el servidor.

#### Qué quedó
_2026-10-28 · nota_
<!-- entrada {"id":57,"seccion":"Nivel nuevo 5: flujo de git automatizado (pedido del usuario, en fases) / Fase 1: suite de pruebas permanente (`tests/`)","titulo":"Qué quedó","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":277,"tipo":"nota","vigencia":"historica","fecha":"2026-10-28","resumen":"385 pruebas en 15 archivos: API (81), hook pre-commit (65), actividad (40), salud (30), dashboard (29), línea base…","modulos":["git"]} -->
- **385 pruebas** en 15 archivos: API (81), hook pre-commit (65), actividad (40), salud (30), dashboard (29), línea base (25), cuarentena (22), reporte (19), notificaciones (18), correlación (16), consultas y retención (15), SMART (9), historial (7), API contra MCP (6) y local (3; hay una cuarta marcada `local` dentro de las de actividad).
  <!-- item {"id":278,"tipo":"nota","vigencia":"historica","fecha":"2026-10-28","resumen":"Tiempos: suite completa 25,9 s; subconjunto rápido (`-m \"not lento\"`, el del pre-commit) 9,4 s con 196 pruebas","modulos":["git"]} -->
- **Tiempos:** suite completa 25,9 s; subconjunto rápido (`-m "not lento"`, el del pre-commit) 9,4 s con 196 pruebas; como en CI (`-m "not local"`) 381 pruebas en ~22 s. Cinco corridas completas seguidas (cuando eran 298): 5 de 5 sin fallar.
  <!-- item {"id":279,"tipo":"nota","vigencia":"historica","fecha":"2026-10-28","resumen":"Cobertura total: 72 % (2817 líneas, 780 sin cubrir)","modulos":["git"]} -->
- **Cobertura total: 72 %** (2817 líneas, 780 sin cubrir). Muy bien cubiertos: `linea_base` 98 %, `correlacion` 96 %, `consultas` 95 %, `salud` 95 %, `web/api` 94 %, `reporte` 90 %, `server` 80 %.
  <!-- item {"id":280,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"No se tocó nada real: después de la suite, los reportes y las copias de migración reales siguen en 1 y 1, no hay…","modulos":["git"]} -->
- **No se tocó nada real:** después de la suite, los reportes y las copias de migración reales siguen en 1 y 1, no hay escuchas de notificaciones vivos, el dashboard y los timers siguen activos y no quedan carpetas temporales.

#### Errores del código que las pruebas encontraron y se corrigieron
_2026-10-28 · error_
<!-- entrada {"id":58,"seccion":"Nivel nuevo 5: flujo de git automatizado (pedido del usuario, en fases) / Fase 1: suite de pruebas permanente (`tests/`)","titulo":"Errores del código que las pruebas encontraron y se corrigieron","fecha":"2026-10-28","tipo":"error"} -->

<!-- item {"id":281,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"`parsear_smart` fallaba con JSON válido que no es un objeto (`null`, una lista): se perdían las lecturas de SMART de…","modulos":["git","salud"]} -->
- `parsear_smart` fallaba con JSON válido que no es un objeto (`null`, una lista): se perdían las lecturas de SMART de todos los discos en esa corrida.
  <!-- item {"id":282,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"El dashboard mostraba un ventilador a 0 RPM sin historia como \"parado: giraba antes\", sin evidencia de que hubiera…","modulos":["dashboard","salud"]} -->
- El dashboard mostraba un ventilador a 0 RPM **sin historia** como "parado: giraba antes", sin evidencia de que hubiera girado; ahora es "parado" solo si hay registro de que giró, y si no, "conector sin ventilador".
  <!-- item {"id":283,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Una prueba de la regla del ventilador detenido, escrita antes del arreglo de los conectores vacíos, ya no valía: se…","modulos":["git","salud"]} -->
- Una prueba de la regla del ventilador detenido, escrita antes del arreglo de los conectores vacíos, ya no valía: se adaptó y se agregó el caso del conector vacío.

#### Problemas de las pruebas mismas
_2026-10-28 · error_
<!-- entrada {"id":59,"seccion":"Nivel nuevo 5: flujo de git automatizado (pedido del usuario, en fases) / Fase 1: suite de pruebas permanente (`tests/`)","titulo":"Problemas de las pruebas mismas","fecha":"2026-10-28","tipo":"error"} -->

<!-- item {"id":284,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Carrera entre pruebas: el servidor HTTP falso de una prueba seguía muriéndose cuando la siguiente lanzaba el suyo en…","modulos":["git"]} -->
- Carrera entre pruebas: el servidor HTTP falso de una prueba seguía muriéndose cuando la siguiente lanzaba el suyo en el mismo puerto; la limpieza ahora espera a que el puerto quede libre.
  <!-- item {"id":285,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"`httpx` normaliza los `..` de una URL antes de enviarla, así que `/api/reportes/../../etc/passwd` llegaba como…","modulos":["dashboard","git"],"archivos":["","/etc/passwd"]} -->
- `httpx` normaliza los `..` de una URL antes de enviarla, así que `/api/reportes/../../etc/passwd` llegaba como `/etc/passwd`; la prueba ahora verifica que ninguna ruta filtre contenido del sistema.
  <!-- item {"id":286,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Mi propia comprobación usaba `grep` sobre la línea de resumen con `-q` doble y daba falsos fallos","modulos":["git"]} -->
- Mi propia comprobación usaba `grep` sobre la línea de resumen con `-q` doble y daba falsos fallos; se usa el código de salida.

#### Limitaciones (lo que la suite NO cubre)
_2026-10-28 · limitacion_
<!-- entrada {"id":60,"seccion":"Nivel nuevo 5: flujo de git automatizado (pedido del usuario, en fases) / Fase 1: suite de pruebas permanente (`tests/`)","titulo":"Limitaciones (lo que la suite NO cubre)","fecha":"2026-10-28","tipo":"limitacion"} -->

<!-- item {"id":287,"tipo":"pendiente","vigencia":"vigente","fecha":"2026-10-28","resumen":"Pendiente: poca cobertura de pruebas en `seguridad.py` (18 %), `reputacion.py` (25 %) y `collector.py` (21 %)","modulos":["datos","seguridad"],"archivos":["collector.py","reputacion.py","seguridad.py"]} -->
- **`seguridad.py` 18 %, `reputacion.py` 25 % y `collector.py` 21 %:** el escáner de procesos y puertos, las consultas de reputación online y el hilo principal del recolector no tienen pruebas permanentes. Hay que dar datos de procesos y de red sintéticos y simular las consultas HTTP.
  <!-- item {"id":288,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"`server.py` 80 %: sin pruebas siguen `revision_seguridad` y `marcar_hallazgo`","modulos":["mcp","seguridad"],"archivos":["server.py"]} -->
- **`server.py` 80 %:** sin pruebas siguen `revision_seguridad` y `marcar_hallazgo`. (`limpiar_descargas_viejas` y `restaurar_cuarentena`, las que mueven archivos del usuario, se cubrieron después: ver más abajo.)
  <!-- item {"id":289,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"`db.py` 55 % (ayudas de hardware), `alertas.py` 58 % (la línea de comandos), `dashboard.py` 79 %","modulos":["alertas","dashboard","datos"],"archivos":["alertas.py","dashboard.py","db.py"]} -->
- `db.py` 55 % (ayudas de hardware), `alertas.py` 58 % (la línea de comandos), `dashboard.py` 79 %.
  <!-- item {"id":290,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"Las pruebas del recolector, de la lectura real de sensores y de SMART por `sudo` solo corren localmente (`local`)","modulos":["datos","salud"]} -->
- Las pruebas del recolector, de la lectura real de sensores y de SMART por `sudo` solo corren localmente (`local`).
  <!-- item {"id":291,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"El aviso de deprecación de `starlette.testclient` con `httpx` está silenciado en `pyproject.toml`","modulos":["git","infra"],"archivos":["pyproject.toml"]} -->
- El aviso de deprecación de `starlette.testclient` con `httpx` está silenciado en `pyproject.toml`; hay que revisarlo cuando haya un reemplazo estable.

#### Pruebas de las tools que mueven archivos (a pedido del usuario, tras el resumen de la Fase 1)
_2026-10-28 · prueba_
<!-- entrada {"id":61,"seccion":"Nivel nuevo 5: flujo de git automatizado (pedido del usuario, en fases) / Fase 1: suite de pruebas permanente (`tests/`)","titulo":"Pruebas de las tools que mueven archivos (a pedido del usuario, tras el resumen de la Fase 1)","fecha":"2026-10-28","tipo":"prueba"} -->

<!-- item {"id":292,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"`tests/test_cuarentena.py`, 22 pruebas de `limpiar_descargas_viejas` y `restaurar_cuarentena`, en un `HOME` temporal…","modulos":["git","mcp"],"archivos":["tests/test_cuarentena.py"]} -->
- `tests/test_cuarentena.py`, 22 pruebas de `limpiar_descargas_viejas` y `restaurar_cuarentena`, en un `HOME` temporal: la simulación (el valor por defecto) no mueve nada; un archivo recién copiado no cuenta como viejo aunque su `mtime` sea de hace un año (la edad es el máximo de `mtime` y `ctime`); se agrupa por elemento de primer nivel y se acota a 20; al ejecutar se mueve a cuarentena con el contenido idéntico y queda registro en `cuarentena` y `acciones`; nunca se borra nada; dos corridas el mismo día no se pisan (`a.txt` y `a.1.txt`); nunca se tocan archivos fuera de Descargas (ni los de una carpeta de nombre parecido); los enlaces simbólicos no se siguen ni se mueven; restaurar devuelve el archivo idéntico, no pisa uno existente, recrea la carpeta si ya no está y da error con ids inexistentes, ya restaurados o sin archivo; el ciclo completo deja todo como estaba.
  <!-- item {"id":293,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Como el `ctime` no se puede falsear, para volver \"viejos\" a archivos recién creados se adelanta el reloj que usa solo…","modulos":["git"]} -->
- Como el `ctime` no se puede falsear, para volver "viejos" a archivos recién creados se adelanta el reloj que usa solo el módulo del servidor, sin tocar el reloj del resto del programa.
  <!-- item {"id":294,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Prueba de las pruebas: se rompió el código a propósito de cuatro maneras y las pruebas detectaron tres (restaurar…","modulos":["git"]} -->
- **Prueba de las pruebas:** se rompió el código a propósito de cuatro maneras y las pruebas detectaron tres (restaurar pisando lo existente, ejecutar en simulación, ignorar el `ctime`). La cuarta, seguir enlaces simbólicos, no se detectaba porque el código tiene **dos** barreras (`followlinks=False` y comprobar que la ruta real esté dentro de Descargas) y con una sola rota la otra protege; rompiendo las dos, la prueba falla.
  <!-- item {"id":295,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"`conftest.py` ahora también vacía el `HOME` temporal antes de cada prueba (antes solo vaciaba la carpeta de datos)","modulos":["git"]} -->
- `conftest.py` ahora también vacía el `HOME` temporal antes de cada prueba (antes solo vaciaba la carpeta de datos).

### Fase 2: hook pre-commit (`scripts/pre-commit` y `scripts/instalar-hooks.sh`)

#### Decisiones
_2026-10-28 · decision_
<!-- entrada {"id":62,"seccion":"Nivel nuevo 5: flujo de git automatizado (pedido del usuario, en fases) / Fase 2: hook pre-commit (`scripts/pre-commit` y `scripts/instalar-hooks.sh`)","titulo":"Decisiones","fecha":"2026-10-28","tipo":"decision"} -->

<!-- item {"id":296,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Hook en Python (más fácil de probar y de leer que en shell), versionado en `scripts/pre-commit`","modulos":["git"],"archivos":["scripts/instalar-hooks.sh","scripts/pre-commit"]} -->
- **Hook en Python** (más fácil de probar y de leer que en shell), versionado en `scripts/pre-commit`. `scripts/instalar-hooks.sh` lo enlaza en `.git/hooks/pre-commit` con un enlace relativo, se puede repetir sin problema y, si ya había otro hook, lo guarda como `pre-commit.antes`. Ya está instalado en este repositorio.
  <!-- item {"id":297,"tipo":"invariante","vigencia":"vigente","fecha":"2026-10-28","resumen":"El hook pre-commit bloquea .db, config.json, web_token, datos/ y secretos por su nombre","modulos":["git"],"prueba":"tests/test_hook.py::test_bloquea_datos_y_secretos_por_su_nombre"} -->
- **Bloquea por nombre:** cualquier archivo `.db` (y `-wal`, `-shm`, copias como `doctor.db.antes-de-juego-…`, `.sqlite`), `config.json`, `web_token` y todo lo que esté bajo `datos/` (incluido el enlace simbólico `datos`).
  **(invariante · prueba: tests/test_hook.py::test_bloquea_datos_y_secretos_por_su_nombre)**
  <!-- item {"id":298,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Bloquea por contenido: tokens de GitHub (`ghp_`, `gho_`…, `github_pat_`), claves de Anthropic, OpenAI, AWS, Slack y…","modulos":["git"]} -->
- **Bloquea por contenido:** tokens de GitHub (`ghp_`, `gho_`…, `github_pat_`), claves de Anthropic, OpenAI, AWS, Slack y Google, claves privadas (`-----BEGIN … PRIVATE KEY-----`), `password=` (y `passwd`, `pwd`, `contraseña`) con un valor, y claves de API, secretos o tokens de 32 caracteres o más asignados a un nombre clave.
  <!-- item {"id":299,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Bloquea por tamaño: más de 1 MiB (1.048.576 bytes; justo 1 MiB pasa)","modulos":["git"]} -->
- **Bloquea por tamaño:** más de 1 MiB (1.048.576 bytes; justo 1 MiB pasa).
  <!-- item {"id":300,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Bloquea si fallan las pruebas rápidas (`uv run pytest -m \"not lento\"`, ~9 s)","modulos":["git"]} -->
- **Bloquea si fallan las pruebas rápidas** (`uv run pytest -m "not lento"`, ~9 s). Si `uv` no está, bloquea con un mensaje claro. Los problemas de archivos se informan sin correr las pruebas.
  <!-- item {"id":301,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Se revisa lo que realmente va al commit: el contenido indexado (no el archivo de trabajo) y solo las líneas agregadas…","modulos":["git"]} -->
- **Se revisa lo que realmente va al commit:** el contenido indexado (no el archivo de trabajo) y solo las líneas **agregadas**, con su número de línea, para no bloquear por cosas que ya estaban. Las bajas no se revisan (sacar un `.db` del repositorio es justo lo que hay que poder hacer). Los renombres cuentan como agregado.
  <!-- item {"id":302,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Los secretos se muestran enmascarados (los primeros 4 caracteres y el largo): el mensaje del hook no filtra el secreto…","modulos":["git"]} -->
- **Los secretos se muestran enmascarados** (los primeros 4 caracteres y el largo): el mensaje del hook no filtra el secreto a la terminal ni a los registros.
  <!-- item {"id":303,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Ejemplos falsos a propósito: una línea con `permitir-secreto` en un comentario se ignora, y solo esa línea","modulos":["git"]} -->
- **Ejemplos falsos a propósito:** una línea con `permitir-secreto` en un comentario se ignora, y solo esa línea.
  <!-- item {"id":304,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Salida de emergencia: `git commit \u002d\u002dno-verify` sigue funcionando; `CLAUDE.md` pide no usarlo sin preguntar","modulos":["git"],"archivos":["CLAUDE.md"]} -->
- **Salida de emergencia:** `git commit --no-verify` sigue funcionando; `CLAUDE.md` pide no usarlo sin preguntar. La variable `PC_DOCTOR_HOOK_SIN_PRUEBAS=1` omite solo el paso de las pruebas y la usan las pruebas del propio hook.
  <!-- item {"id":305,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Las 65 pruebas del hook (`tests/test_hook.py`) usan repositorios git temporales: 13 nombres bloqueados, 10 formas de…","modulos":["git"],"archivos":["tests/test_hook.py"]} -->
- **Las 65 pruebas del hook** (`tests/test_hook.py`) usan repositorios git temporales: 13 nombres bloqueados, 10 formas de secreto, 13 casos que no deben bloquearse (código normal y nombres parecidos), solo líneas agregadas, enmascarado, índice contra árbol de trabajo, tamaño en el límite exacto, bajas, varios problemas juntos, pruebas rápidas que fallan o pasan (con un `uv` falso), sin `uv`, el instalador (idempotente, respalda otro hook) y `git commit` de punta a punta (bloquea lo malo, deja pasar lo bueno, `--no-verify`). Están marcadas `lento` (crean repositorios): corren en la suite completa y en CI, no en cada commit.

#### Errores encontrados y corregidos
_2026-10-28 · error_
<!-- entrada {"id":63,"seccion":"Nivel nuevo 5: flujo de git automatizado (pedido del usuario, en fases) / Fase 2: hook pre-commit (`scripts/pre-commit` y `scripts/instalar-hooks.sh`)","titulo":"Errores encontrados y corregidos","fecha":"2026-10-28","tipo":"error"} -->

<!-- item {"id":306,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"La prueba de autorrevisión (el hook revisa su propio código y las pruebas del hook) falló: el hook bloqueaba mi propio…","modulos":["git"]} -->
- La prueba de autorrevisión (el hook revisa su propio código y las pruebas del hook) falló: **el hook bloqueaba mi propio archivo de pruebas**, que tiene contraseñas falsas a propósito. Se marcaron esas líneas con `permitir-secreto`.
  <!-- item {"id":307,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Esa misma prueba reveló un falso positivo real: en `\"password: str\\n\"` la secuencia `\\n` de un string de Python…","modulos":["git"]} -->
- Esa misma prueba reveló un falso positivo real: en `"password: str\n"` la secuencia `\n` de un string de Python contaba como parte del valor. Ahora la barra invertida no forma parte del valor.

#### Limitaciones
_2026-10-28 · limitacion_
<!-- entrada {"id":64,"seccion":"Nivel nuevo 5: flujo de git automatizado (pedido del usuario, en fases) / Fase 2: hook pre-commit (`scripts/pre-commit` y `scripts/instalar-hooks.sh`)","titulo":"Limitaciones","fecha":"2026-10-28","tipo":"limitacion"} -->

<!-- item {"id":308,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"Las pruebas rápidas corren sobre el árbol de trabajo, no sobre el índice: con un commit parcial (`git add -p`) pueden…","modulos":["git"]} -->
- Las pruebas rápidas corren sobre el **árbol de trabajo**, no sobre el índice: con un commit parcial (`git add -p`) pueden pasar por cambios que no están en el commit. Es la limitación habitual de los hooks sin `git stash`.
  <!-- item {"id":309,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"Solo conoce las formas de secreto de la lista; un secreto con otra forma (o dividido en partes) no se detecta","modulos":["git"]} -->
- Solo conoce las formas de secreto de la lista; un secreto con otra forma (o dividido en partes) no se detecta. No reemplaza revisar lo que se sube.
  <!-- item {"id":310,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"El hook se instala por clon: cada clon nuevo necesita `bash scripts/instalar-hooks.sh`","modulos":["git"]} -->
- El hook se instala por clon: cada clon nuevo necesita `bash scripts/instalar-hooks.sh`.

### Fase 3: regla de commits en `CLAUDE.md`
_2026-10-28 · nota_
<!-- entrada {"id":65,"seccion":"Nivel nuevo 5: flujo de git automatizado (pedido del usuario, en fases)","titulo":"Fase 3: regla de commits en `CLAUDE.md`","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":311,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Se agregó la sección \"Flujo de git\" con las reglas pedidas (correr `uv run pytest` al terminar un cambio coherente","modulos":["git"],"archivos":["BITACORA.md"]} -->
- Se agregó la sección "Flujo de git" con las reglas pedidas (correr `uv run pytest` al terminar un cambio coherente; commit en español, imperativo, primera línea corta y, si hace falta, un párrafo con el porqué; prefijos `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`; el commit incluye la entrada de `BITACORA.md`; `git push` después; sin commit si las pruebas fallan; nunca `push --force`, `reset --hard` ni reescribir historial sin preguntar; mostrar `git log --oneline origin/main..HEAD` antes de cada push). Agregué por mi cuenta la línea `Co-Authored-By` al final del mensaje (la instrucción de atribución de las sesiones de Claude Code) y la mención del hook y de no usar `--no-verify` sin preguntar.
  <!-- item {"id":312,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Además se actualizó el resto de `CLAUDE.md`, que había quedado viejo: describía dos partes del sistema y 4 módulos","modulos":["dashboard","git"],"archivos":["CLAUDE.md"]} -->
- Además se actualizó el resto de `CLAUDE.md`, que había quedado viejo: describía dos partes del sistema y 4 módulos; ahora lista las tres partes, todos los módulos, las convenciones del dashboard, la sección "Pruebas" (marcadores y las reglas de aislamiento que debe seguir una prueba nueva) y la excepción de los archivos con punto para git.

### Fase 4: GitHub Actions (`.github/workflows/pruebas.yml`)

<!-- entrada {"id":66,"seccion":"Nivel nuevo 5: flujo de git automatizado (pedido del usuario, en fases) / Fase 4: GitHub Actions (`.github/workflows/pruebas.yml`)","titulo":"Introducción","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":313,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Dos trabajos en paralelo, en `ubuntu-24.04`, con `permissions: contents: read`, `persist-credentials: false`, límite…","modulos":["dashboard","git","infra"],"archivos":["uv.lock"]} -->
- Dos trabajos en paralelo, en `ubuntu-24.04`, con `permissions: contents: read`, `persist-credentials: false`, límite de tiempo y cancelación de corridas viejas de la misma rama. Se dispara en cada push y pull request a `main`.
  - **Python:** instala `uv` 0.13.6 (la de desarrollo) con Python 3.12, `uv sync --frozen` (exactamente `uv.lock`) y `uv run pytest -m "not local"`.
  - **Frontend:** Node 24.22.2 (la de desarrollo), `npm ci` (exactamente `package-lock.json`) y `npm run build` (`tsc` estricto y `vite build`).
  <!-- item {"id":314,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Actions fijadas por SHA de commit, resuelto desde la API de GitHub y verificado contra el repositorio de cada action…","modulos":["git"]} -->
- **Actions fijadas por SHA de commit**, resuelto desde la API de GitHub y verificado contra el repositorio de cada action: `actions/checkout` v7.0.1 (`3d3c42e5…`, 17/07/2026), `astral-sh/setup-uv` v10.3.0 (`1c37ad07…`, 09/10/2026) y `actions/setup-node` v7.1.0 (`949feb24…`, 08/10/2026). Todas con más de 2 semanas; `setup-uv` v10.3.3 es de hoy y se descartó por reciente.
  <!-- item {"id":315,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"Simulación previa de CI: copia limpia con solo los archivos que git versionaría, entorno mínimo (`env -i`), zona…","modulos":["git","infra"]} -->
- **Simulación previa de CI:** copia limpia con solo los archivos que git versionaría, entorno mínimo (`env -i`), zona horaria UTC (la de GitHub; esta PC está en UTC-3) y `HOME` vacío: 381 pruebas pasan, y `npm ci` + `npm run build` compilan. Sin esto no habría forma de saber, antes de subir, si alguna prueba dependía de la máquina.
  <!-- item {"id":316,"tipo":"nota","vigencia":"superada","fecha":"2026-10-28","resumen":"Limitación: no se pudo probar en GitHub antes de subirlo; la verificación real es `gh run watch` tras el push","modulos":["git"],"reemplazada_por":317,"motivo":"Se verificó en GitHub: el primer push dejó main en rojo y se corrigió."} -->
- **Limitación:** no se pudo probar en GitHub antes de subirlo; la verificación real es `gh run watch` tras el push.
  (superada por #317: Se verificó en GitHub: el primer push dejó main en rojo y se corrigió.)

#### Primera corrida de CI: falló una prueba (carrera entre pruebas) y su corrección
_2026-10-28 · nota_
<!-- entrada {"id":67,"seccion":"Nivel nuevo 5: flujo de git automatizado (pedido del usuario, en fases) / Fase 4: GitHub Actions (`.github/workflows/pruebas.yml`)","titulo":"Primera corrida de CI: falló una prueba (carrera entre pruebas) y su corrección","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":317,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Qué pasó: el primer push con el workflow dejó `main` en rojo: el frontend compiló, pero…","modulos":["alertas","git"]} -->
- **Qué pasó:** el primer push con el workflow dejó `main` en rojo: el frontend compiló, pero `test_sin_seccion_es_el_comportamiento_de_siempre…` vio 2 llamadas a `notify-send` en vez de 1. En esta PC pasaba siempre (385 de 385, y 5 corridas seguidas).
  <!-- item {"id":318,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Causa: una prueba anterior (`…se_puede_forzar`) lanza un escucha de notificación en segundo plano mediante el…","modulos":["alertas","git"]} -->
- **Causa:** una prueba anterior (`…se_puede_forzar`) lanza un escucha de notificación en segundo plano mediante el `systemd-run` falso; ese escucha escribía en el registro compartido *después* de que su prueba había terminado, y en un runner lento caía dentro de la prueba siguiente.
  <!-- item {"id":319,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Reproducción antes de corregir: con la CPU saturada (24 procesos de carga) la falla aparece sola: 1 de 12 corridas…","modulos":["git"]} -->
- **Reproducción antes de corregir:** con la CPU saturada (24 procesos de carga) la falla aparece sola: 1 de 12 corridas, con el mismo `assert (2 == 1)`.
  <!-- item {"id":320,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Corrección: `tests/conftest.py` mata y espera a cualquier proceso en segundo plano que una prueba haya dejado (el…","modulos":["git"],"archivos":["tests/conftest.py"]} -->
- **Corrección:** `tests/conftest.py` mata y espera a cualquier proceso en segundo plano que una prueba haya dejado (el escucha `--con-boton` y los `notify-send` falsos), antes de vaciar el registro y al terminar cada prueba. Con la misma carga: 0 de 24 corridas fallan.
  <!-- item {"id":321,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Lección: la simulación previa de CI (copia limpia, entorno mínimo, UTC) no atrapó esto porque no simulaba un equipo…","modulos":["git"]} -->
- **Lección:** la simulación previa de CI (copia limpia, entorno mínimo, UTC) no atrapó esto porque no simulaba un equipo lento; la verificación real es la corrida en GitHub. Un runner de CI es un buen detector de carreras.

## Nivel nuevo 6: memoria en tablas (pedido del usuario, en fases)

<!-- entrada {"id":68,"seccion":"Nivel nuevo 6: memoria en tablas (pedido del usuario, en fases)","titulo":"Introducción","fecha":"2026-10-28","tipo":"nota"} -->

<!-- item {"id":322,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-28","resumen":"El usuario pidió mover la memoria dispersa (`CLAUDE.md`, `CHANGELOG.md`, `BITACORA.md`) a tablas de `doctor.db`…","modulos":["memoria"],"archivos":["BITACORA.md","CHANGELOG.md","CLAUDE.md"]} -->
El usuario pidió mover la memoria dispersa (`CLAUDE.md`, `CHANGELOG.md`, `BITACORA.md`) a tablas de `doctor.db` consultables por el MCP, en 4 fases con parada y OK al final de cada una. Reglas: sin `sudo`, pruebas en base temporal, la base real solo se toca en la migración (Fase 3) y con copia previa, y no se borra ningún markdown hasta que el usuario confirme la migración.

### Fase 1: esquema y tools

#### Decisiones
_2026-10-28 · decision_
<!-- entrada {"id":69,"seccion":"Nivel nuevo 6: memoria en tablas (pedido del usuario, en fases) / Fase 1: esquema y tools","titulo":"Decisiones","fecha":"2026-10-28","tipo":"decision"} -->

<!-- item {"id":323,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"`memoria.py` concentra el esquema y la lógica de las cuatro tablas (`memoria`, `hechos_conocidos`, `bitacora`…","modulos":["mcp","memoria"],"archivos":["memoria.py","server.py"]} -->
- **`memoria.py`** concentra el esquema y la lógica de las cuatro tablas (`memoria`, `hechos_conocidos`, `bitacora`, `changelog`); `server.py` solo envuelve. Son 12 tools nuevas (ya son 35).
  <!-- item {"id":324,"tipo":"invariante","vigencia":"vigente","fecha":"2026-10-28","resumen":"Las tablas de memoria no están en db.ESQUEMA: el recolector nunca las crea; solo las escrituras","modulos":["datos","memoria"],"prueba":"tests/test_memoria.py::test_la_base_normal_no_trae_las_tablas_de_memoria"} -->
- **Las tablas no están en `db.ESQUEMA`:** `db.conectar()` lo aplica en cada corrida del recolector (cada 15 min, con el código del proyecto), y la base real no debe cambiar antes de la migración. Las tablas se crean al **escribir** (`asegurar()`); las lecturas devuelven vacío si no existen. Una prueba verifica que ninguna lectura crea tablas.
  **(invariante · prueba: tests/test_memoria.py::test_la_base_normal_no_trae_las_tablas_de_memoria)**
  <!-- item {"id":325,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Búsqueda FTS5 (`unicode61 remove_diacritics 2`, tablas de contenido externo con triggers de sincronización) para…","modulos":["memoria"]} -->
- **Búsqueda FTS5** (`unicode61 remove_diacritics 2`, tablas de contenido externo con triggers de sincronización) para `memoria` y también para `bitacora`. La consulta del usuario nunca llega cruda a FTS5: se reduce a palabras, cada una entre comillas y como prefijo; primero se exigen todas y, si no hay resultados, alcanza con alguna. Orden por relevancia (bm25) con más peso al tema/título.
  <!-- item {"id":326,"tipo":"invariante","vigencia":"vigente","fecha":"2026-10-28","resumen":"Los hechos conocidos solo se escriben cuando el usuario lo pide de forma explícita","modulos":["mcp","memoria"],"prueba":"tests/test_memoria.py::test_los_hechos_conocidos_solo_se_escriben_con_la_intervencion_del_usuario_y_el_docstring_lo_dice"} -->
- **Hechos conocidos:** `agregar_hecho_conocido` y `retirar_hecho_conocido` dicen en el docstring que solo se usan si el usuario lo pide en la conversación, y dejan constancia en `acciones`. `vence` es AAAA-MM-DD (no puede ser pasada); un hecho vencido deja de contar como activo. `aplica_a` se compara por segmentos (`sdb` aplica a `smart_crc:sdb/errores_crc`, pero `fan1` no aplica a `fan10`).
  **(invariante · prueba: tests/test_memoria.py::test_los_hechos_conocidos_solo_se_escriben_con_la_intervencion_del_usuario_y_el_docstring_lo_dice)**
  <!-- item {"id":327,"tipo":"invariante","vigencia":"vigente","fecha":"2026-10-28","resumen":"Nada se borra de la memoria: olvidar y retirar_hecho_conocido solo marcan como inactivo","modulos":["mcp","memoria"],"prueba":"tests/test_memoria.py::test_olvidar_lo_saca_de_las_busquedas_sin_borrarlo"} -->
- **Nada se borra:** `olvidar` y `retirar_hecho_conocido` marcan como inactivo.
  **(invariante · prueba: tests/test_memoria.py::test_olvidar_lo_saca_de_las_busquedas_sin_borrarlo)**
  <!-- item {"id":328,"tipo":"decision","vigencia":"superada","fecha":"2026-10-28","resumen":"El reporte semanal (`claude -p`) no puede usar ninguna de las tools nuevas todavía: las de escritura y las de memoria…","modulos":["mcp","reporte"],"reemplazada_por":338,"motivo":"A claude -p se le agregó únicamente hechos_conocidos (lectura)."} -->
- **El reporte semanal** (`claude -p`) no puede usar ninguna de las tools nuevas todavía: las de escritura y las de memoria quedaron en `HERRAMIENTAS_PROHIBIDAS`. La Fase 2 le permitirá solo `hechos_conocidos`.
  (superada por #338: A claude -p se le agregó únicamente hechos_conocidos (lectura).)
  <!-- item {"id":329,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Desvíos pequeños respecto al pedido: `changelog` tiene una columna opcional `titulo` (las entradas del archivo tienen…","modulos":["memoria"]} -->
- **Desvíos pequeños respecto al pedido:** `changelog` tiene una columna opcional `titulo` (las entradas del archivo tienen título y no cabía en otro campo), `registrar_changelog` acepta ese `titulo` opcional y `recordar` acepta un `origen` opcional (por defecto `agente`).

#### Pruebas
_2026-10-28 · prueba_
<!-- entrada {"id":70,"seccion":"Nivel nuevo 6: memoria en tablas (pedido del usuario, en fases) / Fase 1: esquema y tools","titulo":"Pruebas","fecha":"2026-10-28","tipo":"prueba"} -->

<!-- item {"id":330,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"`tests/test_memoria.py`: esquema idempotente y perezoso, FTS sincronizado en insert/update/delete, búsqueda sin…","modulos":["memoria"],"archivos":["tests/test_memoria.py"]} -->
- `tests/test_memoria.py`: esquema idempotente y perezoso, FTS sincronizado en insert/update/delete, búsqueda sin acentos ni mayúsculas, consultas hostiles (comillas, `NEAR`, inyección SQL, 5000 caracteres), validación de cada enumeración y largo, hechos por `aplica_a` y vencimiento, flujo del changelog y de punta a punta por las tools.

#### Errores encontrados
_2026-10-28 · error_
<!-- entrada {"id":71,"seccion":"Nivel nuevo 6: memoria en tablas (pedido del usuario, en fases) / Fase 1: esquema y tools","titulo":"Errores encontrados","fecha":"2026-10-28","tipo":"error"} -->

<!-- item {"id":331,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"FTS5 no admite un alias de tabla en `MATCH` ni en `bm25()`; se usa el nombre real de la tabla","modulos":["memoria"]} -->
- FTS5 no admite un alias de tabla en `MATCH` ni en `bm25()`; se usa el nombre real de la tabla.

#### Limitaciones
_2026-10-28 · limitacion_
<!-- entrada {"id":72,"seccion":"Nivel nuevo 6: memoria en tablas (pedido del usuario, en fases) / Fase 1: esquema y tools","titulo":"Limitaciones","fecha":"2026-10-28","tipo":"limitacion"} -->

<!-- item {"id":332,"tipo":"limitacion","vigencia":"superada","fecha":"2026-10-28","resumen":"Todavía nada usa los hechos conocidos (Fase 2) y la base real no tiene las tablas (Fase 3)","modulos":["memoria"],"reemplazada_por":333,"motivo":"Los hechos conocidos ya tienen efecto sobre las alertas y la base real tiene las tablas."} -->
- Todavía nada usa los hechos conocidos (Fase 2) y la base real no tiene las tablas (Fase 3).
  (superada por #333: Los hechos conocidos ya tienen efecto sobre las alertas y la base real tiene las tablas.)

### Fase 2: los hechos conocidos tienen efecto

#### Decisiones
_2026-10-28 · decision_
<!-- entrada {"id":73,"seccion":"Nivel nuevo 6: memoria en tablas (pedido del usuario, en fases) / Fase 2: los hechos conocidos tienen efecto","titulo":"Decisiones","fecha":"2026-10-28","tipo":"decision"} -->

<!-- item {"id":333,"tipo":"invariante","vigencia":"vigente","fecha":"2026-10-28","resumen":"Un hecho conocido silencia lo conocido, no lo nuevo: si la alerta empeora, vuelve a avisar","modulos":["memoria","salud"],"prueba":"tests/test_hechos_efecto.py::test_un_contador_de_smart_que_sube_avisa_aclarando_el_hecho_conocido"} -->
- **Un hecho conocido silencia lo conocido, no lo nuevo.** `memoria.filtrar_avisos` se aplica al final de `salud.aplicar_condiciones`. Mira **todas** las condiciones vigentes, no solo las que tocaba avisar: un empeoramiento puede ocurrir en medio de la ventana de repetición (6 h en avisos, 2 h en críticos) y, si solo se filtraran los candidatos, no llegaría nunca (lo encontró una prueba).
  **(invariante · prueba: tests/test_hechos_efecto.py::test_un_contador_de_smart_que_sube_avisa_aclarando_el_hecho_conocido)**
  <!-- item {"id":334,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Qué cubre un hecho: `aplica_a` se compara por segmentos (`:` y `/`) con la clave de la alerta…","modulos":["memoria","salud"],"archivos":[""]} -->
- **Qué cubre un hecho:** `aplica_a` se compara por segmentos (`:` y `/`) con la clave de la alerta (`smart_pendientes:sdb/sectores_pendientes`) o con el nombre del sensor. `sdb` cubre todos los contadores de sdb; `sdb/errores_crc` solo ese.
  <!-- item {"id":335,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Qué es \"empeorar\": se anota el estado con el que quedó silenciada cada alerta (tabla `hechos_referencia`: severidad y…","modulos":["memoria","salud"]} -->
- **Qué es "empeorar":** se anota el estado con el que quedó silenciada cada alerta (tabla `hechos_referencia`: severidad y valor; se crea solo cuando existe algún hecho). Empeora si sube la severidad (aviso→crítico) o si el valor se aleja de lo normal: en los contadores de SMART, **cualquier aumento** (un sector más ya es novedad); en lo demás, un cambio de más del 5 % (en las reglas de mínimo, como el espacio libre, empeorar es bajar). En los eventos del journal el valor es su hora, así que solo cuenta la escalada de severidad. Al avisar un empeoramiento, el nuevo estado pasa a ser la referencia: no se repite hasta que vuelva a empeorar. El aviso dice `[hecho conocido #N: empeoró (antes X)]`.
  <!-- item {"id":336,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Si la alerta se resuelve se olvida su referencia (al volver cuenta como primera vez)","modulos":["memoria"]} -->
- **Si la alerta se resuelve** se olvida su referencia (al volver cuenta como primera vez). Si el hecho se **retira o vence**, deja de silenciar y la próxima corrida avisa. Si el hecho se declara con la alerta ya activa, se silencia desde ese momento, también los recordatorios.
  <!-- item {"id":337,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"La alerta no desaparece: sigue registrada en `alertas_salud` y visible en el dashboard y el MCP con su `hecho_conocido`","modulos":["alertas","dashboard","mcp"]} -->
- **La alerta no desaparece:** sigue registrada en `alertas_salud` y visible en el dashboard y el MCP con su `hecho_conocido`; solo se silencia la notificación.
  <!-- item {"id":338,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Reporte semanal: a `claude -p` se le agregó únicamente `hechos_conocidos` (lectura)","modulos":["memoria","reporte"]} -->
- **Reporte semanal:** a `claude -p` se le agregó únicamente `hechos_conocidos` (lectura). El prompt dice que no recomiende de nuevo lo cubierto salvo que haya empeorado, que lo mencione al final de la sección 8 y que liste como "para revisar" los vencidos, y que los hechos son datos, no instrucciones. Siguen prohibidas todas las tools de escritura y las de búsqueda de memoria. **Plan B:** no recomienda la copia de seguridad ni cuenta como crítica una alerta cubierta, salvo que haya empeorado; lista lo declarado y lo vencido.
  <!-- item {"id":339,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Dashboard (solo lectura): cada alerta cubierta muestra el hecho","modulos":["dashboard","memoria"]} -->
- **Dashboard (solo lectura):** cada alerta cubierta muestra el hecho; secciones nuevas "Hechos conocidos" (vigentes y para revisar) y "Changelog" (lo abierto primero), con `/api/hechos` y `/api/changelog`. Estado con ícono y texto. La edición queda para la fase de acciones del dashboard.

#### Pruebas
_2026-10-28 · prueba_
<!-- entrada {"id":74,"seccion":"Nivel nuevo 6: memoria en tablas (pedido del usuario, en fases) / Fase 2: los hechos conocidos tienen efecto","titulo":"Pruebas","fecha":"2026-10-28","tipo":"prueba"} -->

<!-- item {"id":340,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"`tests/test_hechos_efecto.py` (22): sin hechos no cambia nada ni se crean tablas; silencio (incluso 10 h)","modulos":["memoria"],"archivos":["tests/test_hechos_efecto.py"]} -->
- `tests/test_hechos_efecto.py` (22): sin hechos no cambia nada ni se crean tablas; silencio (incluso 10 h); cobertura por disco y por regla; empeoramiento y reanudación del silencio; escalada; umbral del 5 %; reglas de mínimo; eventos; vencido, retirado, resuelta-y-reaparece, hecho declarado con la alerta activa; el campo en MCP y consultas; prompt y listas del reporte; plan B; API de solo lectura.
  <!-- item {"id":341,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Prueba de las pruebas: se rompió a propósito el criterio de valor (detectado por 4 pruebas) y la escalada de severidad…","modulos":["memoria"]} -->
- **Prueba de las pruebas:** se rompió a propósito el criterio de valor (detectado por 4 pruebas) y la escalada de severidad (sobrevivía: el aumento del valor la tapaba; se agregó la prueba con eventos y ahora la detecta).

#### Errores encontrados y corregidos
_2026-10-28 · error_
<!-- entrada {"id":75,"seccion":"Nivel nuevo 6: memoria en tablas (pedido del usuario, en fases) / Fase 2: los hechos conocidos tienen efecto","titulo":"Errores encontrados y corregidos","fecha":"2026-10-28","tipo":"error"} -->

<!-- item {"id":342,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"El aviso de empeoramiento de un evento mostraba la hora del evento como valor anterior (\"antes 100\")","modulos":["memoria"]} -->
- El aviso de empeoramiento de un evento mostraba la hora del evento como valor anterior ("antes 100"); ahora muestra la severidad.
  <!-- item {"id":343,"tipo":"error","vigencia":"vigente","fecha":"2026-10-28","resumen":"Empeoramientos dentro de la ventana de repetición no se avisaban (ver Decisiones)","modulos":["memoria"]} -->
- Empeoramientos dentro de la ventana de repetición no se avisaban (ver Decisiones).

#### Limitaciones
_2026-10-28 · limitacion_
<!-- entrada {"id":76,"seccion":"Nivel nuevo 6: memoria en tablas (pedido del usuario, en fases) / Fase 2: los hechos conocidos tienen efecto","titulo":"Limitaciones","fecha":"2026-10-28","tipo":"limitacion"} -->

<!-- item {"id":344,"tipo":"pendiente","vigencia":"vigente","fecha":"2026-10-28","resumen":"Pendiente: reconstruir `dist/`, reiniciar el servicio y ver en un navegador Hechos conocidos y Changelog","modulos":["dashboard","memoria"]} -->
- **El dashboard no se vio en un navegador:** el frontend compila (`tsc` y `vite build` a una carpeta temporal) y la API está probada, pero el servicio instalado sigue con el código viejo hasta reiniciarlo y reconstruir `dist/`.
  <!-- item {"id":345,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"La referencia de un valor con tolerancia del 5 % puede dejar pasar un empeoramiento lento y gradual (cada paso menor…","modulos":["memoria","salud"]} -->
- La referencia de un valor con tolerancia del 5 % puede dejar pasar un empeoramiento lento y gradual (cada paso menor al 5 % del valor anotado); los contadores de SMART no tienen ese problema.
  <!-- item {"id":346,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"Los hechos se declaran solo desde la conversación (tools del MCP); el dashboard todavía no edita","modulos":["dashboard","mcp"]} -->
- Los hechos se declaran solo desde la conversación (tools del MCP); el dashboard todavía no edita.
  <!-- item {"id":347,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"No hay hechos cargados en la base real (Fase 3: se proponen, los elegís vos)","modulos":["memoria"]} -->
- No hay hechos cargados en la base real (Fase 3: se proponen, los elegís vos).

### Fase 3

#### Migración a las tablas
_2026-10-28 · decision_
<!-- entrada {"id":77,"seccion":"Nivel nuevo 6: memoria en tablas (pedido del usuario, en fases) / Fase 3","titulo":"Migración a las tablas","fecha":"2026-10-28","tipo":"decision"} -->

<!-- item {"id":348,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Copia previa: `VACUUM INTO` de la base real a `doctor.db.antes-de-memoria-1793240795` (integridad ok)","modulos":["datos","memoria"]} -->
- **Copia previa:** `VACUUM INTO` de la base real a `doctor.db.antes-de-memoria-1793240795` (integridad ok). Antes se ensayó todo sobre una copia en la carpeta temporal de la sesión. La migración real corre con `uv run migrar_memoria.py --ejecutar`, que se niega sin copia previa o si las tablas ya tienen datos, y escribe todo en una sola transacción.
  <!-- item {"id":349,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Bitácora: una fila por sección hoja de `BITACORA.md` (76 filas)","modulos":["memoria"],"archivos":["BITACORA.md"]} -->
- **Bitácora:** una fila por sección hoja de `BITACORA.md` (76 filas). `seccion` = el `##` (o `## / ###` cuando hay `####`), `titulo` = el encabezado más profundo, `contenido` = su texto tal cual; `tipo` según el título (Decisiones, Errores, Pruebas, Limitaciones; el resto, nota). El texto que estaba antes de los subtítulos pasó a una fila "Introducción". El bloque `## 2026-10-28` se llama "Construcción inicial (2026-10-28)". Los archivos solo tenían una fecha, así que todo lleva 2026-10-28.
  <!-- item {"id":350,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Changelog: 21 entradas (13 resueltas, 8 abiertas), de la más vieja (id 1) a la más nueva","modulos":["memoria"]} -->
- **Changelog:** 21 entradas (13 resueltas, 8 abiertas), de la más vieja (id 1) a la más nueva. `tipo` y `estado` se normalizan a los valores de la tabla; lo que traían de más (por ejemplo "error (hardware, a confirmar)" o "abierto (vigilando)") queda en el detalle como "Tipo original" y "Estado original". "en curso" cuenta como abierto. El `componente` se deduce del título con una lista de palabras (ninguna cayó en "general").
  <!-- item {"id":351,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Memoria: 6 recuerdos: las cuatro filas de \"Identidad actual\" que no se pueden recalcular con el snapshot (energía, red…","modulos":["memoria"],"archivos":["CLAUDE.md"]} -->
- **Memoria:** 6 recuerdos: las cuatro filas de "Identidad actual" que no se pueden recalcular con el snapshot (energía, red expuesta, sensores extra, Node.js) y dos hechos de `CLAUDE.md` (dónde están los datos y la regla de privacidad). Las filas calculables (SO, kernel, CPU, GPU, RAM, discos, placa, paquetes) se generarán al exportar.
  <!-- item {"id":352,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Hechos conocidos: ninguno cargado; se proponen al usuario para que elija","modulos":["memoria"]} -->
- **Hechos conocidos:** ninguno cargado; se proponen al usuario para que elija.

#### Verificación de la migración
_2026-10-28 · prueba_
<!-- entrada {"id":78,"seccion":"Nivel nuevo 6: memoria en tablas (pedido del usuario, en fases) / Fase 3","titulo":"Verificación de la migración","fecha":"2026-10-28","tipo":"prueba"} -->

<!-- item {"id":353,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Conteos: 21 entradas del changelog en el archivo, 21 en la tabla","modulos":["memoria"]} -->
- Conteos: 21 entradas del changelog en el archivo, 21 en la tabla; 76 filas de bitácora (79 subsecciones en el archivo, de las cuales algunas solo agrupan a otras).
  <!-- item {"id":354,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Sin pérdida: las 400 líneas con texto de `BITACORA.md` están en las filas, idénticas y en el mismo orden","modulos":["memoria"],"archivos":["BITACORA.md"]} -->
- Sin pérdida: las 400 líneas con texto de `BITACORA.md` están en las filas, idénticas y en el mismo orden; las 76 filas aparecen literales en el archivo; todos los encabezados quedan reflejados como sección o título. Comparación al azar de 3 filas de bitácora y 2 del changelog contra los originales: coinciden.
  <!-- item {"id":355,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"La base real: integridad ok, las 21 tablas previas intactas, el recolector y el dashboard siguen activos","modulos":["datos","memoria"]} -->
- La base real: integridad ok, las 21 tablas previas intactas, el recolector y el dashboard siguen activos. Ningún markdown se tocó ni se borró.
  <!-- item {"id":356,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"12 pruebas nuevas del migrador (`tests/test_migracion_memoria.py`) con textos sintéticos: partición por encabezado…","modulos":["memoria"],"archivos":["tests/test_migracion_memoria.py"]} -->
- 12 pruebas nuevas del migrador (`tests/test_migracion_memoria.py`) con textos sintéticos: partición por encabezado, bloques de código, fechas, normalización del changelog, sin pérdida de líneas, ids en orden cronológico, no se repite, rollback si algo falla, negativa sin copia previa.

#### Limitaciones de la migración
_2026-10-28 · limitacion_
<!-- entrada {"id":79,"seccion":"Nivel nuevo 6: memoria en tablas (pedido del usuario, en fases) / Fase 3","titulo":"Limitaciones de la migración","fecha":"2026-10-28","tipo":"limitacion"} -->

<!-- item {"id":357,"tipo":"pendiente","vigencia":"vigente","fecha":"2026-10-28","resumen":"Pendiente: resolver las entradas viejas del changelog que siguen abiertas (`resolver_changelog`)","modulos":["dashboard","memoria"]} -->
- Las entradas viejas del changelog se migraron como estaban: "Dashboard de pc-doctor: API y interfaz listas (fases 1 y 2 de 5)" figura abierta ("en curso") aunque el dashboard ya está instalado; ya no refleja la realidad y conviene resolverla con `resolver_changelog`. Lo mismo, en menor medida, con "Aprendizaje de valores normales activado" y "Alertas de salud: lo que se puede y no se puede vigilar".
  <!-- item {"id":358,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"El `componente` del changelog es una deducción por palabras del título, no un dato del archivo original","modulos":["memoria"]} -->
- El `componente` del changelog es una deducción por palabras del título, no un dato del archivo original.
  <!-- item {"id":359,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-28","resumen":"Las fechas de la bitácora son todas 2026-10-28 porque los archivos solo tenían esa fecha","modulos":["memoria"]} -->
- Las fechas de la bitácora son todas 2026-10-28 porque los archivos solo tenían esa fecha.
  <!-- item {"id":360,"tipo":"limitacion","vigencia":"superada","fecha":"2026-10-28","resumen":"Durante esta fase se escribió en `bitacora` y no en `BITACORA.md`: el archivo no tiene lo de la Fase 3 hasta que la…","modulos":["memoria"],"archivos":["BITACORA.md"],"reemplazada_por":374,"motivo":"BITACORA.md y CHANGELOG.md se reemplazaron por lo exportado."} -->
- Durante esta fase se escribió en `bitacora` y no en `BITACORA.md`: el archivo no tiene lo de la Fase 3 hasta que la Fase 4 lo regenere desde la tabla.
  (superada por #374: BITACORA.md y CHANGELOG.md se reemplazaron por lo exportado.)

### Fase 4

#### Exportación a markdown y hook
_2026-10-28 · decision_
<!-- entrada {"id":80,"seccion":"Nivel nuevo 6: memoria en tablas (pedido del usuario, en fases) / Fase 4","titulo":"Exportación a markdown y hook","fecha":"2026-10-28","tipo":"decision"} -->

<!-- item {"id":361,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"`uv run memoria.py \u002d\u002dexportar` regenera `BITACORA.md` y `CHANGELOG.md` desde las tablas, con un aviso de que son…","modulos":["memoria"],"archivos":["BITACORA.md","CHANGELOG.md"]} -->
- **`uv run memoria.py --exportar`** regenera `BITACORA.md` y `CHANGELOG.md` desde las tablas, con un aviso de que son generados y no se editan a mano. `--destino CARPETA` escribe en otro lado para poder revisar antes de reemplazar. Abre la base en solo lectura, no toca el archivo si no cambió y no hace nada (ni crea tablas) si no existen.
  <!-- item {"id":362,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Formato: la bitácora conserva la jerarquía (`##` = sección, `###` = entrada, `####` si la sección trae ` / `) y agrega…","modulos":["memoria"]} -->
- **Formato:** la bitácora conserva la jerarquía (`##` = sección, `###` = entrada, `####` si la sección trae ` / `) y agrega bajo cada entrada una línea con su fecha y tipo (la tabla guarda más que el archivo original). El changelog va de lo más nuevo a lo más viejo, con tipo acentuado, componente y estado (con fecha de resolución).
  <!-- item {"id":363,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"\"Identidad actual\" ya no se guarda: se calcula al exportar desde el último `snapshot_entorno` y su `hardware`…","modulos":["memoria"]} -->
- **"Identidad actual"** ya no se guarda: se calcula al exportar desde el último `snapshot_entorno` y su `hardware` (hostname, SO, kernel, CPU, GPU, RAM, discos, placa, paquetes). Las filas que no se pueden recalcular (energía, red expuesta, sensores extra, Node.js) quedaron como recuerdos en `memoria`, que **no se exporta**, igual que `hechos_conocidos`.
  <!-- item {"id":364,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Hook pre-commit: regenera ambos archivos y los agrega al commit antes de revisar secretos y tamaño, así que lo…","modulos":["git","memoria"],"archivos":["memoria.py"]} -->
- **Hook pre-commit:** regenera ambos archivos y los agrega al commit antes de revisar secretos y tamaño, así que lo exportado pasa por las mismas revisiones. Si la exportación falla, avisa y sigue (no bloquea el commit). Solo actúa en un repositorio que tiene `memoria.py`. `PC_DOCTOR_HOOK_SIN_EXPORTAR=1` lo saltea.
  <!-- item {"id":365,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"El commit de código de esta fase se hizo con `PC_DOCTOR_HOOK_SIN_EXPORTAR=1` a propósito: con el hook nuevo activo…","modulos":["git","memoria"]} -->
- **El commit de código de esta fase se hizo con `PC_DOCTOR_HOOK_SIN_EXPORTAR=1` a propósito:** con el hook nuevo activo, ese mismo commit habría reemplazado los markdown originales antes de que el usuario aprobara.
  <!-- item {"id":366,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Los `CLAUDE.md` se purgan solo después de mostrar el antes y el después y recibir el OK del usuario","modulos":["memoria"],"archivos":["CLAUDE.md"]} -->
- **Los `CLAUDE.md` se purgan solo después de mostrar el antes y el después y recibir el OK del usuario**; lo mismo el reemplazo de los markdown originales por los exportados.

#### Pruebas de la exportación
_2026-10-28 · prueba_
<!-- entrada {"id":81,"seccion":"Nivel nuevo 6: memoria en tablas (pedido del usuario, en fases) / Fase 4","titulo":"Pruebas de la exportación","fecha":"2026-10-28","tipo":"prueba"} -->

<!-- item {"id":367,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"`tests/test_exportar_memoria.py` (17): la bitácora exportada conserva cada línea del original en el mismo orden (más…","modulos":["datos","memoria"],"archivos":["memoria.py","tests/test_exportar_memoria.py"]} -->
- `tests/test_exportar_memoria.py` (17): la bitácora exportada conserva cada línea del original en el mismo orden (más fecha y tipo); niveles de encabezado; entrada nueva con fecha y tipo; identidad calculada desde un snapshot sintético y que cambia si cambia el snapshot; sin snapshot lo dice; orden y estado del changelog; título faltante; **`memoria` y `hechos_conocidos` no salen de la base**; no reescribe lo que no cambió; sin tablas o sin base no crea nada; línea de comandos en solo lectura; el hook regenera y agrega al commit, lo exportado pasa por la revisión de secretos, una exportación que falla avisa sin bloquear, y la variable y la falta de `memoria.py` lo desactivan.
  <!-- item {"id":368,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Prueba de las pruebas: quitando a propósito el `git add` del hook, 2 pruebas fallan","modulos":["git","memoria"]} -->
- **Prueba de las pruebas:** quitando a propósito el `git add` del hook, 2 pruebas fallan.
  <!-- item {"id":369,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Sobre los datos reales (exportando a una carpeta temporal): las líneas con texto del `BITACORA.md` original quedan…","modulos":["memoria"],"archivos":["BITACORA.md"]} -->
- Sobre los datos reales (exportando a una carpeta temporal): las líneas con texto del `BITACORA.md` original quedan idénticas y en orden; el único encabezado que cambia es `## 2026-10-28`, que ahora es "Construcción inicial (2026-10-28)".

#### Identidad manual exportable y cierre de la fase
_2026-10-28 · decision_
<!-- entrada {"id":82,"seccion":"Nivel nuevo 6: memoria en tablas (pedido del usuario, en fases) / Fase 4","titulo":"Identidad manual exportable y cierre de la fase","fecha":"2026-10-28","tipo":"decision"} -->

<!-- item {"id":370,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Tabla `identidad_manual` (campo, valor, actualizado): las cuatro filas de \"Identidad actual\" que no se pueden…","modulos":["memoria"]} -->
- **Tabla `identidad_manual` (campo, valor, actualizado):** las cuatro filas de "Identidad actual" que no se pueden recalcular (Energía, Red expuesta, Sensores extra, Node.js) son identidad de la PC y no datos personales, así que **sí se exportan a git**, a diferencia de `memoria` y `hechos_conocidos`. Se editan con la tool `registrar_identidad(campo, valor)` (crea o actualiza; rechaza los campos que se calculan solos desde el snapshot). Salen después de las filas calculadas, con una nota de que son declaradas a mano y de cuándo se actualizaron. Un `|` o un salto de línea en el valor no rompe la tabla.
  <!-- item {"id":371,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Cambio sobre lo migrado en la Fase 3: esas cuatro filas estaban como recuerdos en `memoria`","modulos":["memoria"],"archivos":["CHANGELOG.md","migrar_memoria.py"]} -->
- **Cambio sobre lo migrado en la Fase 3:** esas cuatro filas estaban como recuerdos en `memoria`; se pasaron a `identidad_manual` conservando su fecha y se desactivaron (no se borraron) los 4 recuerdos duplicados. Antes se tomó una copia nueva de la base (`doctor.db.antes-de-identidad-*`, integridad ok). `migrar_memoria.py` ahora escribe ahí esas filas. Las 4 filas exportadas son idénticas, carácter por carácter, a las del `CHANGELOG.md` original.
  <!-- item {"id":372,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Tag `pre-migracion-memoria` sobre el commit `31c3269` (con los markdown y los `CLAUDE.md` originales), pusheado…","modulos":["git","memoria"],"archivos":["CLAUDE.md"]} -->
- **Tag `pre-migracion-memoria`** sobre el commit `31c3269` (con los markdown y los `CLAUDE.md` originales), pusheado: permite volver atrás con `git show pre-migracion-memoria:BITACORA.md`.
  <!-- item {"id":373,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"`CLAUDE.md` purgados (aprobados por el usuario): el del proyecto pasó de 6564 a 3930 bytes (−40 %) y el global de 884…","modulos":["memoria","sistema"],"archivos":["CLAUDE.md","~/.claude/CLAUDE.md.antes-de-memoria"]} -->
- **`CLAUDE.md` purgados** (aprobados por el usuario): el del proyecto pasó de 6564 a 3930 bytes (−40 %) y el global de 884 a 789 (la copia del original quedó en `~/.claude/CLAUDE.md.antes-de-memoria`). Quedan solo reglas de comportamiento: consultar la memoria antes de suponer, registrar con `registrar_bitacora` / `registrar_changelog` / `registrar_identidad`, hechos conocidos solo a pedido explícito, y una línea que remite al README para la arquitectura y los módulos. Se quitó la descripción de módulos del `CLAUDE.md` del proyecto (está en el README) y la regla de editar el changelog a mano.
  <!-- item {"id":374,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Reemplazo de los markdown: `BITACORA.md` y `CHANGELOG.md` pasaron a ser los exportados","modulos":["git","memoria"],"archivos":["BITACORA.md","CHANGELOG.md"]} -->
- **Reemplazo de los markdown:** `BITACORA.md` y `CHANGELOG.md` pasaron a ser los exportados; el hook pre-commit los regenera desde ahora.
  <!-- item {"id":375,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-28","resumen":"Hechos conocidos cargados: ninguno (la lista propuesta quedó a elección del usuario)","modulos":["memoria"]} -->
- **Hechos conocidos cargados: ninguno** (la lista propuesta quedó a elección del usuario).

#### Verificación del cierre
_2026-10-28 · prueba_
<!-- entrada {"id":83,"seccion":"Nivel nuevo 6: memoria en tablas (pedido del usuario, en fases) / Fase 4","titulo":"Verificación del cierre","fecha":"2026-10-28","tipo":"prueba"} -->

<!-- item {"id":376,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Suite completa con la identidad manual: ver el commit de cierre","modulos":["memoria"]} -->
- Suite completa con la identidad manual: ver el commit de cierre. Pruebas nuevas: crear, actualizar y rechazar campos calculados, orden y nota en la tabla exportada, identidad manual sin snapshot, tool del MCP, `|` y saltos de línea, y que `memoria` y `hechos_conocidos` siguen sin salir de la base mientras `identidad_manual` sí.
  <!-- item {"id":377,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-28","resumen":"Resultado de la migración completa: 76 entradas de bitácora (más las de la Fase 3 y 4 registradas después), 21 del…","modulos":["memoria"]} -->
- Resultado de la migración completa: 76 entradas de bitácora (más las de la Fase 3 y 4 registradas después), 21 del changelog (13 resueltas, 8 abiertas), 2 recuerdos y 4 filas de identidad.

## Nivel nuevo 7: bitácora en ítems por módulo (pedido del usuario, en fases)

### Decisiones
_2026-10-29 · decision_
<!-- entrada {"id":84,"seccion":"Nivel nuevo 7: bitácora en ítems por módulo (pedido del usuario, en fases)","titulo":"Decisiones","fecha":"2026-10-29","tipo":"decision"} -->

<!-- item {"id":379,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-29","resumen":"El ítem es la unidad de la bitácora; `bitacora` queda como agrupación (sección y título)","modulos":["memoria"],"archivos":["memoria.py"]} -->
- **El ítem es la unidad:** un bullet de primer nivel con sus subbullets, o un párrafo. Tiene tipo (incluye `invariante` y `pendiente`), vigencia (`vigente`, `superada`, `historica`), módulos, archivos, resumen de una línea (máximo 120 caracteres) y, si lo protege un test, su nombre. `bitacora` solo agrupa por sección y título.
  <!-- item {"id":380,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-29","resumen":"`modulos.py` mapea archivos a módulos y una prueba falla si un archivo de código queda sin módulo","modulos":["memoria"],"archivos":["modulos.py"],"prueba":"tests/test_bitacora_items.py::test_todo_archivo_versionado_de_codigo_cae_en_algun_modulo"} -->
- **Mapa de archivos a módulos en el código, no en la base:** `modulos.py` (`MODULOS`, `modulos_de`). Lo de fuera del repo es el módulo `sistema`. Una prueba exige que todo archivo versionado de código caiga en algún módulo y otra que cada patrón coincida con algún archivo.
  <!-- item {"id":381,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-29","resumen":"`contexto` devuelve resúmenes y siempre incluye las invariantes vigentes, aunque se pase de `n`","modulos":["mcp","memoria"],"archivos":["memoria.py","server.py"],"prueba":"tests/test_bitacora_items.py::test_las_invariantes_se_incluyen_siempre_aunque_se_pase_de_n"} -->
- **`contexto(archivo, modulo, tipo, incluir_superadas, n)`:** solo resúmenes (id, tipo, módulos, resumen), vigentes por defecto. Orden: invariantes, pendientes, limitaciones, decisiones, errores, pruebas, notas. Las invariantes vigentes entran siempre; el resto llena hasta `n` y se informa cuántos quedaron afuera (`omitidos`). Con `tipo="invariante"` no hay tope.
  <!-- item {"id":382,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-29","resumen":"Las tools de la bitácora quedan prohibidas por nombre en el `claude -p` del reporte","modulos":["mcp","reporte"],"archivos":["reporte.py"],"prueba":"tests/test_bitacora_items.py::test_las_tools_nuevas_estan_registradas_y_el_reporte_semanal_no_las_usa"} -->
- **La bitácora es del proyecto, no de la PC:** `buscar_bitacora`, `contexto`, `detalle_bitacora`, `pendientes`, `marcar_superada` y `registrar_bitacora` están en `HERRAMIENTAS_PROHIBIDAS` y fuera de las de lectura.
  <!-- item {"id":383,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-29","resumen":"`marcar_superada` exige un reemplazo vigente y un motivo, no borra nada y deja constancia en `acciones`","modulos":["memoria"],"archivos":["memoria.py"],"prueba":"tests/test_bitacora_items.py::test_marcar_superada_rechaza_lo_incoherente"} -->
- **Reemplazo explícito:** un ítem solo se marca superado por otro ítem vigente, con motivo. El ítem queda como historia (se exporta con la marca `(superada por #N: motivo)`). Una invariante solo se reemplaza si el usuario lo pidió (está en el docstring, no lo impone el código).
  <!-- item {"id":384,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-29","resumen":"`buscar_bitacora` cae a la búsqueda por sección mientras la base no tenga ítems","modulos":["memoria"],"archivos":["memoria.py"],"prueba":"tests/test_memoria.py::test_sin_items_la_busqueda_cae_a_las_secciones_de_antes"} -->
- **Transición sin cegar la búsqueda:** si `bitacora_items` no existe o está vacía, `buscar_bitacora` busca sobre las secciones como antes. El exportador también usa el `contenido` de las entradas que no tienen ítems.

### Exportación y respaldo
_2026-10-29 · decision_
<!-- entrada {"id":85,"seccion":"Nivel nuevo 7: bitácora en ítems por módulo (pedido del usuario, en fases)","titulo":"Exportación y respaldo","fecha":"2026-10-29","tipo":"decision"} -->

<!-- item {"id":385,"tipo":"invariante","vigencia":"vigente","fecha":"2026-10-29","resumen":"El `BITACORA.md` exportado conserva cada línea del anterior, en el mismo orden; las marcas son líneas nuevas","modulos":["memoria"],"archivos":["memoria.py"],"prueba":"tests/test_bitacora_items.py::test_las_marcas_son_lineas_nuevas_y_no_pierden_ni_reordenan_ninguna_linea_del_original"} -->
- **Nada se pierde ni se reordena al exportar:** las marcas `**(invariante)**` (con la prueba) y `(superada por #N: motivo)` van en líneas aparte después del ítem, sangradas si el ítem es una viñeta. El texto del ítem no se toca.
  **(invariante · prueba: tests/test_bitacora_items.py::test_las_marcas_son_lineas_nuevas_y_no_pierden_ni_reordenan_ninguna_linea_del_original)**
  <!-- item {"id":386,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-29","resumen":"Los metadatos van en comentarios HTML de una línea con JSON, con `\u002d\u002d`, `\u003c` y `\u003e` escapados","modulos":["memoria"],"archivos":["memoria.py"],"prueba":"tests/test_importar_memoria.py::test_cada_comentario_de_metadatos_es_una_linea_html_valida_que_no_se_puede_cerrar_antes"} -->
- **Respaldo completo:** cada entrada, ítem, entrada del changelog y fila de `identidad_manual` lleva `<!-- clave {json} -->`. GitHub no los muestra. Dentro de una viñeta el comentario va sangrado para que la lista siga siendo una. `registrar_bitacora` rechaza líneas con `#` o con forma de comentario fuera de un bloque de código.
  <!-- item {"id":387,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-29","resumen":"`memoria.py \u002d\u002dimportar` se niega sobre tablas con datos; `\u002d\u002dreemplazar` hace antes una copia de la base","modulos":["memoria"],"archivos":["memoria.py"],"prueba":"tests/test_importar_memoria.py::test_no_pisa_tablas_con_datos"} -->
- **Importar:** reconstruye `bitacora`, `bitacora_items` (con módulos y archivos), `changelog` e `identidad_manual` con los mismos ids de ítems y de entradas, en una sola transacción. Con `--reemplazar` vacía esas tablas después de `VACUUM INTO doctor.db.antes-de-importar-*`. `memoria` y `hechos_conocidos` no se exportan ni se importan.

### Migración de la bitácora real
_2026-10-29 · decision_
<!-- entrada {"id":86,"seccion":"Nivel nuevo 7: bitácora en ítems por módulo (pedido del usuario, en fases)","titulo":"Migración de la bitácora real","fecha":"2026-10-29","tipo":"decision"} -->

<!-- item {"id":388,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-29","resumen":"La migración a ítems valida que los ítems de cada entrada, unidos, den su texto exacto; el id es el `n`","modulos":["memoria"],"archivos":["migrar_memoria.py"],"prueba":"tests/test_bitacora_items.py::test_una_propuesta_invalida_no_escribe_nada"} -->
- **`migrar_memoria.py --items PROPUESTA.json [--ejecutar]`:** simula por defecto, exige `doctor.db.antes-de-items-*`, se niega si ya hay ítems y escribe en una sola transacción con los ids iguales al número de la propuesta. Resultado en esta PC: 378 ítems (15 invariantes, 16 superadas, 16 históricas, 7 pendientes).

### Errores encontrados
_2026-10-29 · error_
<!-- entrada {"id":87,"seccion":"Nivel nuevo 7: bitácora en ítems por módulo (pedido del usuario, en fases)","titulo":"Errores encontrados","fecha":"2026-10-29","tipo":"error"} -->

<!-- item {"id":389,"tipo":"error","vigencia":"vigente","fecha":"2026-10-29","resumen":"Dos sesiones de pytest a la vez comparten el puerto 8795 y rompen `test_notificaciones`","modulos":["git"],"archivos":["tests/conftest.py"]} -->
- **Nunca correr dos pytest en paralelo:** el agente de una bifurcación y la sesión principal corrieron la suite a la vez y fallaron 4 a 7 pruebas de `test_notificaciones` sin que el código tuviera la culpa. Pasa limpia al correrla sola.
  <!-- item {"id":390,"tipo":"error","vigencia":"vigente","fecha":"2026-10-29","resumen":"Una prueba de ida y vuelta con ids consecutivos no detecta que el import ignore el id","modulos":["memoria"],"archivos":["tests/test_importar_memoria.py"],"prueba":"tests/test_importar_memoria.py::test_la_importacion_restaura_las_tablas_con_los_mismos_ids_y_valores"} -->
- **Mutación que sobrevivía:** hacer que `--importar` ignorara el id del ítem pasaba las pruebas sintéticas, porque los ids eran 1..N. Se agregaron huecos de ids (en ítems y en entradas). SQLite reutiliza el id más alto al borrar el último, así que el hueco se crea borrando uno del medio.

### Limitaciones
_2026-10-29 · limitacion_
<!-- entrada {"id":88,"seccion":"Nivel nuevo 7: bitácora en ítems por módulo (pedido del usuario, en fases)","titulo":"Limitaciones","fecha":"2026-10-29","tipo":"limitacion"} -->

<!-- item {"id":391,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-29","resumen":"Tipos, módulos y resúmenes de los ítems migrados salieron de reglas automáticas: hay etiquetas imperfectas","modulos":["memoria"],"archivos":["migrar_memoria.py"]} -->
- **Etiquetas aproximadas:** de los 378 ítems migrados, el usuario revisó solo invariantes, superadas, pendientes y los conteos. El resto (tipo, módulos, archivos, resumen) salió de reglas automáticas con unas 60 correcciones a mano. Si una etiqueta estorba, se corrige con una nueva entrada y `marcar_superada`.
  <!-- item {"id":392,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-29","resumen":"La parte calculada de \"Identidad actual\" no está en el markdown: tras importar reaparece con el próximo snapshot","modulos":["memoria"],"archivos":["memoria.py"],"prueba":"tests/test_importar_memoria.py::test_con_los_markdown_reales_del_repo_la_ida_y_vuelta_es_identica"} -->
- **El respaldo no incluye el snapshot de entorno:** la ida y vuelta es idéntica byte a byte, salvo las filas calculadas de la identidad (hostname, SO, kernel, CPU, GPU, RAM, discos, placa, paquetes). Las filas declaradas a mano sí vuelven.
  <!-- item {"id":393,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-29","resumen":"`contexto` sobre un módulo grande (salud tiene 72 ítems) muestra pocos: hay que filtrar por `tipo`","modulos":["memoria"],"archivos":["memoria.py"]} -->
- **Los módulos grandes no caben en `n`:** `contexto(archivo="salud.py")` con `n=12` muestra las invariantes, el pendiente y las limitaciones, y avisa cuántos omite. Las decisiones se piden con `tipo="decision"`.

### Pruebas y medición
_2026-10-29 · prueba_
<!-- entrada {"id":89,"seccion":"Nivel nuevo 7: bitácora en ítems por módulo (pedido del usuario, en fases)","titulo":"Pruebas y medición","fecha":"2026-10-29","tipo":"prueba"} -->

<!-- item {"id":394,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-29","resumen":"Ida y vuelta byte a byte con datos difíciles y con los markdown reales; cuatro mutaciones detectadas","modulos":["memoria"],"archivos":["tests/test_importar_memoria.py"]} -->
- **Pruebas:** exportar, importar en una base vacía y exportar da archivos idénticos (`-->`, comillas, separadores unicode, bloques de código con `#`, ids con huecos, entradas sin dividir). Mutaciones detectadas: cupo de invariantes en `contexto`, sangría de las marcas, escape de `--` y el id al importar. La suite pasó de 541 a 650 pruebas.
  <!-- item {"id":395,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-29","resumen":"Ahorro medido: 40 % menos caracteres con `contexto(n=6)` y 2 detalles que con secciones enteras","modulos":["memoria"],"archivos":["memoria.py"]} -->
- **Medición en tres tareas** (regla de temperatura en `salud.py`, tools permitidas del reporte, bug en el frontend), con las mismas consultas. Antes (`buscar_bitacora` con `completo`, secciones enteras): 4855, 9240 y 1296 caracteres. Ahora (`contexto(archivo, n=6)` más 2 `detalle_bitacora`): 2629, 4088 y 2490, es decir 46 %, 56 % y −92 %: 40 % en total. Con `n=12` por defecto el total baja solo 19 %. En el frontend la búsqueda vieja encontró una sola sección chica y ganó; lo que `contexto` agrega es que las invariantes y los pendientes del módulo aparecen siempre.

## Windows: fase 1, capa de plataforma y lectura de hardware

### Capa de plataforma
_2026-10-29 · decision_
<!-- entrada {"id":90,"seccion":"Windows: fase 1, capa de plataforma y lectura de hardware","titulo":"Capa de plataforma","fecha":"2026-10-29","tipo":"decision"} -->

<!-- item {"id":396,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-29","resumen":"`plataforma/linux.py` es un adaptador sobre el código existente, no el código movido","modulos":["datos","plataforma","salud"],"archivos":["plataforma/__init__.py","plataforma/linux.py"],"prueba":"tests/test_plataforma.py::test_los_dos_backends_ofrecen_toda_la_interfaz"} -->
- **Linux delega en las funciones originales** (`collector._recolectar_hardware_linux`, `db._temperatura_cpu_linux`, `alertas._notificar_linux`...): mover el código habría roto las pruebas que las reemplazan por nombre de módulo.
  - El resto del programa llama a `plataforma.actual().<función>`; una prueba exige que `linux` y `windows` ofrezcan toda la `INTERFAZ`.
  - `plataforma/` no importa `db` ni los demás módulos al cargarse (solo adentro de las funciones).

### Lecturas en Windows
_2026-10-29 · decision_
<!-- entrada {"id":91,"seccion":"Windows: fase 1, capa de plataforma y lectura de hardware","titulo":"Lecturas en Windows","fecha":"2026-10-29","tipo":"decision"} -->

<!-- item {"id":397,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-29","resumen":"Contadores de GPU y disco por clases CIM y no por `Get-Counter`: los nombres se traducen al idioma","modulos":["windows"],"archivos":["plataforma/windows.py","plataforma/windows_sensores.py"],"prueba":"tests/test_windows_sensores.py::test_los_motores_de_gpu_se_usan_solo_si_nadie_mas_trae_el_uso"} -->
- **CIM en lugar de `Get-Counter`:** `\GPU Engine(*)` y `\PhysicalDisk(*)` cambian de nombre en Windows en español. Se usan `Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine` y `..._PerfDisk_PhysicalDisk`, leídas una vez, 1 s de espera y otra vez (las tasas necesitan dos muestras).
  - Una llamada a PowerShell (`-EncodedCommand`, sin ventana) para el hardware y otra para los sensores; los pasos de una corrida reusan la lectura de sensores 30 s.
  - El uso de GPU por contadores solo se emite si ni LibreHardwareMonitor ni `nvidia-smi` lo traen (si no, la alerta se duplicaría).

### Lo que Windows no mide no se inventa
_2026-10-29 · decision_
<!-- entrada {"id":92,"seccion":"Windows: fase 1, capa de plataforma y lectura de hardware","titulo":"Lo que Windows no mide no se inventa","fecha":"2026-10-29","tipo":"decision"} -->

<!-- item {"id":398,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-29","resumen":"Sin carga promedio (None), sin CPU desde ACPI y `Warning` de un disco sin traducir a SMART","modulos":["salud","windows"],"archivos":["plataforma/windows_sensores.py","plataforma/windows_sistema.py"],"prueba":"tests/test_windows_sensores.py::test_la_temperatura_de_la_cpu_prefiere_el_paquete_y_sin_sensor_es_none"} -->
- **Carga:** `plataforma.carga()` devuelve None en Windows y la regla de carga no aplica.
  - **Temperatura de CPU:** solo de LibreHardwareMonitor; las zonas térmicas ACPI se guardan como `placa` (`acpi/...`) y no se usan como CPU.
  - **Discos:** `HealthStatus` Healthy/Unhealthy → `smart_ok` 1/0; Warning no se traduce. Temperatura y desgaste de `Get-StorageReliabilityCounter` solo si Windows los da (0 °C = no informado).
  - **Eventos:** el registro System, críticos/errores/advertencias, con el id en el mensaje (`[41 crit] ...`); `DistributedCOM 10016` se descarta como ruido conocido.

### Cuarentena, esquema y notificaciones en Windows
_2026-10-29 · decision_
<!-- entrada {"id":93,"seccion":"Windows: fase 1, capa de plataforma y lectura de hardware","titulo":"Cuarentena, esquema y notificaciones en Windows","fecha":"2026-10-29","tipo":"decision"} -->

<!-- item {"id":399,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-29","resumen":"Cuarentena por mtime solo en Windows; `software.origen` admite registro y winget; toast con botón por protocolo","modulos":["alertas","datos","mcp","windows"],"archivos":["db.py","plataforma/windows.py","plataforma/windows_notificaciones.py","server.py"],"prueba":"tests/test_plataforma.py::test_el_esquema_acepta_los_origenes_de_windows"} -->
- **Cuarentena:** en Windows `st_ctime` es la creación; la edad usa solo `st_mtime` (decisión del usuario). Linux sigue con el mayor de mtime y ctime.
  - **Esquema:** el `CHECK` de `software.origen` suma `registro` y `winget` en las bases nuevas; las bases de Linux ya creadas conservan el viejo y no insertan esos orígenes.
  - **Toast:** XML con `activationType="protocol"` y la URL del dashboard; sin proceso residente. Viene activo salvo `"boton_dashboard": false` explícito (en Linux viene apagado hasta probarlo). La identidad `pc-doctor` se registra en HKCU, sin administrador y sin dependencias.

### Sin verificar en un Windows real
_2026-10-29 · limitacion_
<!-- entrada {"id":94,"seccion":"Windows: fase 1, capa de plataforma y lectura de hardware","titulo":"Sin verificar en un Windows real","fecha":"2026-10-29","tipo":"limitacion"} -->

<!-- item {"id":400,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-29","resumen":"Todo lo de Windows se probó solo con salidas simuladas en Linux; nada corrió en un Windows real","modulos":["windows"],"archivos":["plataforma/windows.py"]} -->
- **No verificado:** los scripts de PowerShell (sintaxis y nombres de clases CIM), el espacio WMI de LibreHardwareMonitor, `winreg`, `ctypes` de la ventana en primer plano, el toast y la tarea programada.
  - El formato real de `winget list` (tabla por columnas) se supuso; si cambia, `paquetes_winget` devuelve vacío sin romper.

### Pendientes de Windows
_2026-10-29 · nota_
<!-- entrada {"id":95,"seccion":"Windows: fase 1, capa de plataforma y lectura de hardware","titulo":"Pendientes de Windows","fecha":"2026-10-29","tipo":"nota"} -->

<!-- item {"id":401,"tipo":"pendiente","vigencia":"vigente","fecha":"2026-10-29","resumen":"Pendiente: seguridad (fase 2) y `reporte.py` (killpg, rename, `~/.local/bin`, PATH con `:`) no portados","modulos":["reporte","seguridad","windows"],"archivos":["reporte.py","seguridad.py"]} -->
- **Seguridad:** `revisar_y_guardar` devuelve "omitido" en Windows hasta la fase 2.
  - **Reporte:** `reporte.py` usa `os.killpg`, `tmp.rename`, `~/.local/bin/claude` y un PATH con `:`; se porta con el instalador (fase 6).
  - **Reclasificar historial** (`actividad.nombres_de_proceso_de_juegos`) sigue siendo de Steam en Linux.

## Windows: fase 2, seguridad

### Categorías y reglas de seguridad en Windows
_2026-10-29 · decision_
<!-- entrada {"id":96,"seccion":"Windows: fase 2, seguridad","titulo":"Categorías y reglas de seguridad en Windows","fecha":"2026-10-29","tipo":"decision"} -->

<!-- item {"id":402,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-29","resumen":"Suplantación = `fantasma`; categorías nuevas `persistencia`, `postura` y `vulnerabilidad`","modulos":["datos","seguridad","windows"],"archivos":["db.py","plataforma/windows_seguridad.py"],"prueba":"tests/test_windows_seguridad.py::test_si_windows_no_deja_leer_la_ruta_no_se_acusa_a_nadie"} -->
- **Mismo esquema de hallazgos:** huellas con `seguridad._h`, deduplicación, estados y notificación de los `alta` nuevos.
  - La suplantación de procesos del sistema (`svchost` fuera de `System32`, nombres parecidos, padres anómalos, `lsass` duplicado) usa `fantasma`: es lo que en Linux son los procesos que se hacen pasar por otra cosa.
  - El `CHECK` de `hallazgos_seguridad.categoria` suma `persistencia`, `postura` y `vulnerabilidad` solo en bases nuevas; las de Linux ya creadas no los usan.
  - Si Windows no deja leer la ruta de un proceso (los del sistema), no se lo acusa de nada.

### Lecturas de seguridad sin depender del idioma
_2026-10-29 · decision_
<!-- entrada {"id":97,"seccion":"Windows: fase 2, seguridad","titulo":"Lecturas de seguridad sin depender del idioma","fecha":"2026-10-29","tipo":"decision"} -->

<!-- item {"id":403,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-29","resumen":"Tareas programadas con `Get-ScheduledTask` y no con `schtasks /fo csv /v`: las columnas se traducen","modulos":["seguridad","windows"],"archivos":["plataforma/windows_lecturas_seguridad.py"],"prueba":"tests/test_windows_seguridad.py::test_los_servicios_y_tareas_de_microsoft_no_se_siguen"} -->
- **Sin administrador y sin depender del idioma:** `schtasks /query /fo csv /v` devuelve los títulos de columna en el idioma del sistema; `Get-ScheduledTask` da objetos.
  - Servicios por CIM (`Win32_Service`), carpetas de Inicio con `.lnk` resueltos por `WScript.Shell`, claves `Run`/`RunOnce`, `Winlogon`, IFEO y `AppInit_DLLs` por registro, suscripciones WMI por `root/subscription` (si piden administrador se informa en `no_disponible`).
  - Los servicios y tareas de Microsoft (en la carpeta de Windows o con su firma) no se siguen.

### Firmas digitales con caché por hash
_2026-10-29 · decision_
<!-- entrada {"id":98,"seccion":"Windows: fase 2, seguridad","titulo":"Firmas digitales con caché por hash","fecha":"2026-10-29","tipo":"decision"} -->

<!-- item {"id":404,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-29","resumen":"Las firmas se verifican en lote, una vez por hash, y el hash se recalcula solo si cambia el archivo","modulos":["seguridad","windows"],"archivos":["plataforma/windows_lecturas_seguridad.py"],"prueba":"tests/test_windows_lecturas_seguridad.py::test_cada_ejecutable_se_verifica_una_sola_vez_por_hash"} -->
- **Caché de dos niveles** en `firmas.cache.json` (carpeta de datos): `ruta|tamaño|fecha` → SHA-256 y SHA-256 → firma (30 días). Un archivo copiado a otra ruta reusa la firma.
  - Una sola llamada a `Get-AuthenticodeSignature` por corrida con las rutas codificadas, hasta 60 archivos nuevos (el resto, en la siguiente). Un error de verificación no se guarda ni se toma por firma.
  - Solo se verifican los candidatos: carpetas del usuario, uso alto, conexiones sin ventana y arranque. Lo que está en la carpeta de Windows se da por del sistema.

### Estado del escaneo en la base
_2026-10-29 · decision_
<!-- entrada {"id":99,"seccion":"Windows: fase 2, seguridad","titulo":"Estado del escaneo en la base","fecha":"2026-10-29","tipo":"decision"} -->

<!-- item {"id":405,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-29","resumen":"Tablas `persistencia` y `seguridad_estado` creadas solo en Windows; la primera corrida es la base del arranque","modulos":["datos","seguridad","windows"],"archivos":["plataforma/windows_lecturas_seguridad.py"],"prueba":"tests/test_windows_lecturas_seguridad.py::test_la_primera_corrida_es_la_base_y_despues_solo_se_avisa_de_lo_que_aparece"} -->
- **Persistencia:** la primera corrida registra todo sin avisar de lo nuevo (pero sí de lo sospechoso por su contenido); después, algo que aparece se avisa una sola vez, con su firma.
  - **Rachas:** el uso alto sin ventana ni juego necesita 4 corridas (~1 h) y la conexión saliente sin ventana, 3; una corrida solo suma si pasaron 10 min (una revisión manual no la infla).
  - **Postura:** una vez por día (`postura_ultima`). Las tablas se crean con `CREATE TABLE IF NOT EXISTS` desde el código de Windows: `db.ESQUEMA` y las bases de Linux no cambian.

### Reputación sin `dig`
_2026-10-29 · decision_
<!-- entrada {"id":100,"seccion":"Windows: fase 2, seguridad","titulo":"Reputación sin `dig`","fecha":"2026-10-29","tipo":"decision"} -->

<!-- item {"id":406,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-29","resumen":"`consultar_txt` en la plataforma: `dig` en Linux, `Resolve-DnsName` en Windows, con el nombre validado","modulos":["plataforma","seguridad","windows"],"archivos":["plataforma/windows_lecturas_seguridad.py","reputacion.py"],"prueba":"tests/test_windows_lecturas_seguridad.py::test_team_cymru_da_el_mismo_veredicto_con_dig_y_con_resolve_dnsname"} -->
- **Team Cymru:** `reputacion._cymru` pide el TXT a la plataforma y da el mismo veredicto en las dos. En Windows el nombre debe ser exactamente `<40 hex>.hash.cymru.com` antes de ir dentro del script.
  - **Privacidad:** igual que en Linux, solo el hash de hallazgos `alta` o `media` con ejecutable; ahora también los de `persistencia`. Los de postura no tienen ejecutable.
  - **KEV de CISA:** opcional (`"kev": true`), solo se descarga el catálogo; la coincidencia es por nombre y se informa como "revisar".

### Qué no detecta la seguridad de Windows
_2026-10-29 · limitacion_
<!-- entrada {"id":101,"seccion":"Windows: fase 2, seguridad","titulo":"Qué no detecta la seguridad de Windows","fecha":"2026-10-29","tipo":"limitacion"} -->

<!-- item {"id":407,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-29","resumen":"Sin ganchos de teclado, sin BitLocker/Secure Boot/exclusiones de Defender y sin pools por nombre de servidor","modulos":["seguridad","windows"],"archivos":["plataforma/windows_seguridad.py","plataforma/windows_sistema.py"]} -->
- **Keyloggers:** Windows no deja enumerar los ganchos de teclado sin un driver; se detectan por nombre, por estar sin firma en una carpeta del usuario con arranque o conexiones salientes, o por conexiones sostenidas sin ventana.
  - **Con administrador (ayudante, fase 3):** BitLocker, Secure Boot, exclusiones de Defender y, si lo piden, las suscripciones WMI.
  - **SMBv1** solo si está activado de forma explícita; el **fin de soporte** usa una tabla propia de Home/Pro (`FIN_SOPORTE_HOME_PRO`) que hay que mantener a mano.
  - **Pools:** se reconocen por argumentos, puertos e IP conocidas; resolver los nombres de las conexiones obligaría a consultar al DNS por cada destino.

### Seguridad de Windows sin verificar en un Windows real
_2026-10-29 · limitacion_
<!-- entrada {"id":102,"seccion":"Windows: fase 2, seguridad","titulo":"Seguridad de Windows sin verificar en un Windows real","fecha":"2026-10-29","tipo":"limitacion"} -->

<!-- item {"id":408,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-29","resumen":"Reglas probadas con datos simulados; PowerShell, `ctypes`, `winreg` y el DNS no corrieron en Windows","modulos":["seguridad","windows"],"archivos":["plataforma/windows_lecturas_seguridad.py"]} -->
- **No verificado:** `Get-MpComputerStatus`/`Get-MpThreatDetection` (pueden pedir administrador), `Get-StorageReliabilityCounter`, `Resolve-DnsName` y su manejo de NXDOMAIN, la enumeración de ventanas con `EnumWindows`, y el formato de `winget upgrade`.
  - **Riesgo de falsos positivos:** programas sin firma en carpetas del usuario con arranque propio y servicios de terceros nuevos; el primer informe de un equipo real va a servir para ajustar.

### Linux no cambió
_2026-10-29 · prueba_
<!-- entrada {"id":103,"seccion":"Windows: fase 2, seguridad","titulo":"Linux no cambió","fecha":"2026-10-29","tipo":"prueba"} -->

<!-- item {"id":409,"tipo":"prueba","vigencia":"vigente","fecha":"2026-10-29","resumen":"El escaneo real de Linux dio los mismos hallazgos y escuchas antes y después de pasar por la plataforma","modulos":["plataforma","seguridad"],"archivos":["tests/test_seguridad.py"],"prueba":"tests/test_seguridad.py::test_el_escaneo_completo_suma_lo_extra_de_la_plataforma_y_ordena_por_severidad"} -->
- **Foto antes/después** de `seguridad.escanear()` en esta PC (hallazgos con su huella y escuchas): idénticas. Como el módulo casi no tenía pruebas, se agregaron `tests/test_seguridad.py` (procesos, escuchas con IPv6 por `socket.AF_INET6`, orden por severidad, deduplicación) y las de `_cymru` con `dig` falso.

## Windows: fase 3, ayudante con privilegios

### LibreHardwareMonitor v0.9.6 verificado
_2026-10-29 · nota_
<!-- entrada {"id":104,"seccion":"Windows: fase 3, ayudante con privilegios","titulo":"LibreHardwareMonitor v0.9.6 verificado","fecha":"2026-10-29","tipo":"nota"} -->

<!-- item {"id":410,"tipo":"nota","vigencia":"vigente","fecha":"2026-10-29","resumen":"LibreHardwareMonitor v0.9.6: zip verificado contra el hash de GitHub, build .NET Framework, sin el driver PawnIO","modulos":["instalador","windows"]} -->
- **Verificado (2026-10-29):** `LibreHardwareMonitor.zip` de la release v0.9.6 (2026-02-14) tiene SHA-256 `086d9f1b5a99e643edc2cfaaac16051685b551e4c5ac0b32a57c58c0e529c001`, igual al que publica GitHub.
  - Es la build para .NET Framework (`LibreHardwareMonitor.exe` + `.exe.config`, sin runtime aparte); la otra, `.NET.10.zip`, pide el runtime de .NET 10.
  - **No trae el driver PawnIO** (los módulos de CPU y placa dependen de él desde la 0.9.5, con instalador aparte): qué sensores funcionan sin él está sin verificar.

### Lo que corre con privilegios hace lo mínimo
_2026-10-29 · decision_
<!-- entrada {"id":105,"seccion":"Windows: fase 3, ayudante con privilegios","titulo":"Lo que corre con privilegios hace lo mínimo","fecha":"2026-10-29","tipo":"decision"} -->

<!-- item {"id":411,"tipo":"invariante","vigencia":"vigente","fecha":"2026-10-29","resumen":"`ayudante.ps1` no tiene parámetros ni red, solo lee y solo escribe `estado.json` con comandos de una lista fija","modulos":["instalador","windows"],"archivos":["instalador/ayudante.ps1"],"prueba":"tests/test_instalador.py::test_el_ayudante_solo_usa_los_comandos_permitidos"} -->
- **Única pieza elevada** (tarea `pc-doctor-ayudante`, SYSTEM, cada 15 min): lee SMART, contadores de fiabilidad, BitLocker (nunca claves), Secure Boot, exclusiones de Defender y suscripciones WMI.
  - Una prueba lee el archivo y exige que use solo los comandos permitidos, sin `Invoke-*`, red, `Start-Process`, rutas de usuario ni parámetros, y con un solo `WriteAllText` y un solo `Move-Item`.
  - Cualquier cambio que amplíe lo elevado rompe esa prueba y obliga a registrar la decisión.
  **(invariante · prueba: tests/test_instalador.py::test_el_ayudante_solo_usa_los_comandos_permitidos)**

### Dónde vive lo elevado
_2026-10-29 · decision_
<!-- entrada {"id":106,"seccion":"Windows: fase 3, ayudante con privilegios","titulo":"Dónde vive lo elevado","fecha":"2026-10-29","tipo":"decision"} -->

<!-- item {"id":412,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-29","resumen":"Salida del ayudante en `%ProgramData%` de solo lectura para usuarios, no en la carpeta de datos del usuario","modulos":["instalador","windows"],"archivos":["instalador/habilitar-sensores.ps1"],"prueba":"tests/test_instalador.py::test_las_carpetas_con_privilegios_solo_se_escriben_por_system_y_administradores_y_se_verifica"} -->
- **Por qué:** una tarea SYSTEM que escribe en una carpeta que el usuario controla se puede engañar con un enlace simbólico para pisar archivos del sistema. El script, LibreHardwareMonitor y smartctl viven en `%ProgramFiles%\pc-doctor-ayudante` y la salida en `%ProgramData%\pc-doctor\ayudante`; en las dos solo escriben SYSTEM y Administradores (permisos por SID, verificados después de fijarlos).
  - Solo hay dos tareas con privilegios: `pc-doctor-ayudante` (SYSTEM) y `pc-doctor-lhm` (el usuario, al iniciar sesión, que tiene que ser administrador). El recolector, el dashboard y el reporte siguen sin privilegios.
  - Decisión del usuario (2026-10-29): se aprobó esta ubicación en lugar de la carpeta de datos.

### Descargas verificadas y opcionales
_2026-10-29 · decision_
<!-- entrada {"id":107,"seccion":"Windows: fase 3, ayudante con privilegios","titulo":"Descargas verificadas y opcionales","fecha":"2026-10-29","tipo":"decision"} -->

<!-- item {"id":413,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-29","resumen":"Cada descarga se verifica por SHA-256 contra `versiones.toml`; smartctl y el driver PawnIO son opcionales","modulos":["instalador","windows"],"archivos":["instalador/habilitar-sensores.ps1","instalador/versiones.toml"],"prueba":"tests/test_instalador.py::test_cada_descarga_se_verifica_contra_versiones_toml_antes_de_usarla"} -->
- **versiones.toml** fija LibreHardwareMonitor 0.9.6 (hash verificado contra GitHub), smartmontools 7.5 (el MD5 coincide con el publicado; el SHA-256 lo calculamos acá porque GitHub no lo da; la firma GPG no se verificó) y PawnIO 2.2.0 (hash verificado contra GitHub). Solo se aceptan direcciones `https://github.com/`; si el hash no coincide se borra y se corta.
  - **smartctl** (`-ConSmartctl`) es lo único que da los sectores realocados, pendientes y errores CRC; el instalador se verifica también por su firma Authenticode.
  - **PawnIO** (`-InstalarPawnIO`) es un driver de kernel: se abre su asistente (sin parámetros silenciosos) tras una confirmación aparte y `-Deshacer` nunca lo desinstala porque otros programas pueden usarlo.

### Lectura del estado del ayudante
_2026-10-29 · decision_
<!-- entrada {"id":108,"seccion":"Windows: fase 3, ayudante con privilegios","titulo":"Lectura del estado del ayudante","fecha":"2026-10-29","tipo":"decision"} -->

<!-- item {"id":414,"tipo":"decision","vigencia":"vigente","fecha":"2026-10-29","resumen":"`estado.json` se valida (tamaño, versión, campos conocidos) y el SMART crudo pasa por `salud.parsear_smart`","modulos":["salud","windows"],"archivos":["plataforma/windows_ayudante.py"],"prueba":"tests/test_windows_ayudante.py::test_solo_pasan_los_campos_conocidos_con_la_forma_esperada"} -->
- **Validación:** hasta 1 MB, versión 1, solo campos conocidos con la forma esperada y textos acotados; si tiene más de 2 h se avisa en vez de usarlo; nunca se ejecuta nada que venga del archivo.
  - **Mismos nombres que Linux:** el `smartctl -j` entra por el parser de Linux, así `sectores_pendientes` o `errores_crc` activan las reglas existentes; los contadores de fiabilidad aportan temperatura y desgaste si el SMART no los trae, y el ayudante manda sobre lo que ya había.
  - **Postura:** BitLocker suspendido, Secure Boot apagado y exclusiones de Defender (riesgosas = carpeta temporal o del usuario, unidad entera o tipo ejecutable). Las suscripciones WMI del ayudante alimentan la persistencia de la fase 2.

### Scripts de PowerShell sin ejecutar
_2026-10-29 · limitacion_
<!-- entrada {"id":109,"seccion":"Windows: fase 3, ayudante con privilegios","titulo":"Scripts de PowerShell sin ejecutar","fecha":"2026-10-29","tipo":"limitacion"} -->

<!-- item {"id":415,"tipo":"limitacion","vigencia":"vigente","fecha":"2026-10-29","resumen":"Los `.ps1` solo se validaron con un parser de sintaxis y pruebas estáticas; ninguno corrió en Windows","modulos":["instalador","windows"],"archivos":["instalador/ayudante.ps1","instalador/habilitar-sensores.ps1"]} -->
- **Verificado:** sintaxis con un parser de PowerShell (tree-sitter, de uso puntual y no una dependencia del proyecto, que detectó un script roto a propósito), archivos en UTF-8 con BOM (Windows PowerShell 5.1 lee un `.ps1` sin BOM como ANSI y rompe los acentos) y las reglas de seguridad por prueba estática.
  - **Sin verificar:** nombres de los ajustes de LibreHardwareMonitor (`startMinMenuItem`...), `smartmontools-setup.exe /S /D=` y el desinstalador `/S _?=`, `Get-LocalGroupMember` (puede fallar con cuentas huérfanas), `-RepetitionDuration` de 3650 días, el nombre de dispositivo `/dev/sdX` de smartctl en Windows, y qué sensores necesitan el driver PawnIO.
  - **Requisito:** el usuario de la sesión tiene que ser administrador para la tarea de LibreHardwareMonitor; si no, quedan sin medir las temperaturas, ventiladores y voltajes.

### Cierre de la fase 3
_2026-10-29 · nota_
<!-- entrada {"id":110,"seccion":"Windows: fase 3, ayudante con privilegios","titulo":"Cierre de la fase 3","fecha":"2026-10-29","tipo":"nota"} -->

<!-- item {"id":416,"tipo":"pendiente","vigencia":"vigente","fecha":"2026-10-29","resumen":"Pendiente: `instalar.ps1` ofrece el ayudante, `empaquetar.py` incluye `instalador/` y la guía lo explica","modulos":["instalador","windows"]} -->
- **Fase 5:** el paquete lleva `instalador/ayudante.ps1`, `habilitar-sensores.ps1` y `versiones.toml` (en la raíz del zip, como pidió el usuario) y `empaquetar.py` falla si algún `.ps1` perdió el BOM.
  - **Fase 6:** `instalar.ps1` ofrece el ayudante al final y `-Verificar` informa si hay datos recientes de `estado.json`.
  - **Fase 7:** documentar en lenguaje simple qué agrega el ayudante, cómo verlo y cómo deshacerlo.
