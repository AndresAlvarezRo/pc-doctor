# Changelog de la PC

Historial de diagnósticos, errores, soluciones y cambios del equipo. Lo mantiene Claude según la regla de `CLAUDE.md`.
La sección **Identidad actual** siempre refleja el estado vigente: se reescribe cuando algo cambia. Debajo, las entradas van de la más nueva a la más vieja.

## Identidad actual
_Última actualización: 2026-10-28_

| Campo | Valor |
|---|---|
| Hostname | v-System-Product-Name |
| SO | Zorin OS 18.1 (base Ubuntu), escritorio zorin:GNOME |
| Kernel | 7.0.0-38-generic |
| CPU | AMD Ryzen 5 5600X (6 núcleos, 12 hilos, x86_64) |
| GPU | AMD Navi 33 (Radeon RX 7600 / 7700S, `1002:7480`), driver `amdgpu` in-tree del kernel, Mesa 26.2.5 (kisak) |
| RAM | 31,2 GB (sin swap) |
| Discos | Kingston SA400 447 GB (sda), Patriot Burst Elite 223 GB (sdb), CT1000P310SSD8 931 GB NVMe (nvme0n1) |
| Placa madre | ASUS PRIME B550-PLUS, BIOS 3404 |
| Energía | Perfil `balanced` (governor `powersave` + EPP `balance_performance`, driver `amd-pstate-epp`); antes `performance` |
| Red expuesta | Solo Steam `27036` y el DNS de libvirt `192.168.122.1:53` accesibles desde la LAN. `ttyd` (`centro-hogar-ttyd`) en `127.0.0.1:7681`; `fluidsynth` aislado en red privada. IP LAN 192.168.0.9 |
| Sensores extra | `smartmontools`, módulos `drivetemp` (sda, sdb) y `nct6775` (chip `nct6798`: voltajes, ventiladores fan2/fan7 conectados) activos, permanentes vía `/etc/modules-load.d/pc-doctor.conf`; permiso SMART en `/etc/sudoers.d/pc-doctor` |
| Node.js | 24.22.2 con npm 11.19.1, aislado en `~/.local/share/pc-doctor/node/` (fuera del PATH global); solo para compilar el dashboard |
| Paquetes | 2448 (apt + flatpak + snap) al 2026-10-28 |
| pc-doctor | Timer systemd cada 15 min + MCP `pc-doctor`; datos en `~/.local/share/pc-doctor/doctor.db`; incluye escaneo de seguridad en cada corrida |

## Entradas

### 2026-10-28 — Dashboard instalado: servicio, lanzador del menú y enlaces directos (fase 3 de 5)
- **Tipo:** cambio
- **Detalle:** `pc-doctor-web.service` (usuario, arranca con la sesión, solo `127.0.0.1:8787`, ~58 MB) y el lanzador "pc-doctor" en el menú, con ícono propio. La tool `abrir_dashboard` abre una sección desde Claude Code. El botón "Ver en el dashboard" de las notificaciones está implementado pero apagado hasta que el usuario lo pruebe.
- **Estado:** en curso (falta la prueba del botón)

### 2026-10-28 — Procesador y GPU a 95-96 °C jugando a Crimson Desert
- **Tipo:** error (térmico, a confirmar)
- **Detalle:** durante una sesión de Crimson Desert (Steam, bajo Proton) con 75-85 % de uso de CPU, el procesador marcó 95-96 °C (Tctl) y la GPU 92-96 °C (junction), con el perfil de energía `balanced`. El máximo que había registrado antes era de 78,75 °C. El procesador funcionaba a ~3990 MHz de 4654 MHz máximos: ya estaba reduciendo la frecuencia para protegerse. `fan2` estaba al máximo (~2480 RPM) y `fan7` seguía errático (entre ~680 y ~1460 RPM). Tctl a 95 °C es el límite de este procesador.
- **Hipótesis (sin confirmar):** con CPU y GPU calientes a la vez, el problema parece más de flujo de aire de la caja que de un solo ventilador; `fan7` puede estar empeorándolo. Relacionada con las entradas abiertas de `fan7` y de la temperatura en reposo.
- **Para confirmar:** limpiar el polvo de ventiladores y disipadores, revisar el flujo de aire, ver a qué conector va `fan7` y revisar la pasta térmica del procesador.
- **Estado:** abierto

### 2026-10-28 — Detección de juegos corregida con un juego real (Proton)
- **Tipo:** solución
- **Detalle:** con Crimson Desert, el recolector veía tres juegos en vez de uno (un envoltorio `sh -c` de Steam y el ayudante `xalia` de Proton). Ahora los reconoce como parte del juego de Steam y detecta exactamente uno.
- **Estado:** resuelto

### 2026-10-28 — Dashboard de pc-doctor: API y interfaz listas (fases 1 y 2 de 5)
- **Tipo:** cambio
- **Detalle:** nueva API en `web/api.py` (puerto 8787, solo `127.0.0.1`, solo lectura) y su interfaz en `web/frontend/` (se compila con `bash web/construir.sh`). Muestra lo mismo que las tools del MCP. Todavía no hay servicio instalado ni lanzador. Con los datos reales, todas las tarjetas figuran como "aprendiendo" porque la línea base aún no es madura.
- **Estado:** en curso

### 2026-10-28 — Ventilador fan7 con velocidad errática (0 a 1760 RPM)
- **Tipo:** error (hardware, a confirmar)
- **Detalle:** medido durante 45 s con el procesador a 71-79 °C: `nct6798/fan7` varió entre 0 y 1762 RPM (mediana 631), con 10 lecturas en 0 y 14 por debajo de 500 RPM, cambiando cada ~2 s. `fan2`, en cambio, se mantuvo estable (1610 a 2109 RPM). La base ya tenía tres ceros de `fan7` entre las últimas ocho corridas. `fan7` no expone control PWM (no existe `pwm7`) y no se sabe en qué conector de la placa está enchufado.
- **Hipótesis (sin confirmar):** podría ser el ventilador del procesador y explicar la temperatura alta en reposo de la entrada abierta más abajo; o un ventilador con falla intermitente, un conector flojo o una lectura de tacómetro poco fiable.
- **Para confirmar:** mirar a qué conector va `fan7` y si el ventilador se frena a simple vista. El sistema avisará si lo ve en 0 RPM con el procesador a 75 °C o más.
- **Estado:** abierto

### 2026-10-28 — Node.js instalado en una carpeta aislada para compilar el dashboard
- **Tipo:** cambio
- **Detalle:** Node 24.22.2 (tarball oficial, SHA-256 verificado) en `~/.local/share/pc-doctor/node/`, sin `sudo` y sin tocar el PATH. Lo usa solo `web/construir.sh`. Se quita borrando la carpeta.
- **Estado:** resuelto

### 2026-10-28 — Reporte semanal preparado (timer sin instalar)
- **Tipo:** cambio
- **Detalle:** `reporte.py` genera un reporte de salud cada domingo a las 20:00 (timer `pc-doctor-reporte.timer`, instalado), redactado por Claude con herramientas de solo lectura; si Claude falla, un reporte determinístico. La primera ejecución real (27 s) funcionó. Su recomendación de revisar los ventiladores fan1/3/4/5/6 era errónea: venía de las alertas falsas de los conectores vacíos, que se borraron. Se corrigió además `estado_salud()`, que decía que faltaba `drivetemp` pese a estar activo.
- **Estado:** resuelto

### 2026-10-28 — smartd registra errores de correo cada vez que avisa del disco
- **Tipo:** observación
- **Detalle:** al instalar `smartmontools` quedó activo el servicio `smartd`, que intenta avisar por correo de los sectores defectuosos de `sdb` y falla porque no existe `/usr/bin/mail`. Genera eventos `crit` repetidos en el journal ("Your system does not have /usr/bin/mail"). Es ruido; los avisos de SMART reales llegan por las notificaciones de pc-doctor.
- **Estado:** abierto (decisión del usuario: dejarlo, o desactivar `smartd`, o instalar un cliente de correo)

### 2026-10-28 — pc-doctor distingue cuando estás jugando
- **Tipo:** cambio
- **Detalle:** nuevo contexto `juego` para las lecturas (el cliente de Steam abierto no cuenta, solo el juego en ejecución) y registro de sesiones de juego. Las 786 lecturas de hoy, tomadas con `SlayTheSpire` abierto, pasaron de `reposo`/`carga` a `juego` (copia de seguridad en `datos/`). Con eso, las líneas base de `reposo` y `carga` empiezan limpias.
- **Estado:** resuelto

### 2026-10-28 — SMART de `sdb` (Patriot Burst Elite): sectores defectuosos
- **Tipo:** error (hardware)
- **Detalle:** al activar SMART, `sdb` muestra 1 sector realocado, 1 pendiente de realocar, 2 incorregibles offline y 10 errores CRC, con 21125 h encendido. El estado general SMART es PASSED y el desgaste 0 %. `sda` y el NVMe están sin errores. Los contadores son bajos, pero en un SSD indican celdas defectuosas.
- **Acción sugerida:** respaldar lo importante de `sdb`; los errores CRC pueden ser también el cable SATA. Si los contadores siguen subiendo, reemplazar el disco. pc-doctor avisa si cambian.
- **Estado:** abierto (vigilando)

### 2026-10-28 — Sensores habilitados: voltajes, SMART y temperatura SATA
- **Tipo:** solución
- **Detalle:** el usuario ejecutó `habilitar-sensores.sh`. `nct6775` sí reconoce la placa (chip `nct6798`, 15 voltajes), `drivetemp` da la temperatura de sda/sdb y `smartctl` se lee sin contraseña. Los voltajes `in0`–`in14` no traen etiqueta del fabricante, así que no tienen regla fija y quedan para la línea base aprendida. Corregido en pc-doctor: se ignoran las temperaturas de entradas sin sensor (`AUXTIN*`, calibración, `PCH_*`, daban 84 y -61 °C), los ventiladores en 0 RPM que nunca giraron (conectores vacíos fan1/3/4/5/6) y los dos `drivetemp` se distinguen por disco.
- **Incidente:** la primera corrida mandó una notificación real con 5 alertas críticas falsas de "ventilador detenido", por esas entradas sin ventilador. Ya resueltas.
- **Estado:** resuelto

### 2026-10-28 — Aprendizaje de valores normales activado
- **Tipo:** cambio
- **Detalle:** pc-doctor empezó a registrar cada lectura con su contexto (reposo o carga), a guardar un registro diario permanente por sensor y a calcular una línea base. Los avisos aprendidos se activarán solos cuando un sensor tenga ~200 muestras (alrededor de 2 días); la deriva lenta, con ~3 semanas de datos.
- **Estado inicial:** 0 sensores con base madura; los límites fijos funcionan desde ya.
- **Estado:** en curso (aprendiendo)

### 2026-10-28 — Alertas de salud: lo que se puede y no se puede vigilar
- **Tipo:** observación
- **Se vigila hoy (sin root):** temperatura de CPU (`Tctl`), GPU (edge, junction, memoria) y NVMe; ventilador, voltaje del núcleo, potencia, uso y VRAM de la GPU; E/S, espacio libre y solo-lectura de discos; RAM, carga; errores del kernel. Lectura inicial normal: CPU 66 °C, GPU 53 °C, NVMe 49 °C, RAM 38 %, espacios libres 66–80 %.
- **Sin cobertura (pendiente, requiere `sudo`, no se ejecutó nada):**
  - **Voltajes de la placa:** el sensor `asus` de la ASUS PRIME B550-PLUS no expone lecturas. Podría probarse `sudo sensors-detect` y `sudo modprobe nct6775`; si el kernel rechaza el chip por un conflicto con ACPI, hará falta `acpi_enforce_resources=lax`. Sin confirmar que esta placa lo soporte.
  - **Temperatura y SMART de los discos SATA** (Kingston `sda`, Patriot `sdb`): `sudo apt install smartmontools` y `sudo modprobe drivetemp` (para que persista, `drivetemp` en `/etc/modules-load.d/`); el SMART completo además requiere permisos de administrador. El NVMe sí tiene temperatura, pero no SMART.
  - **Sin swap:** el equipo no tiene swap configurada, así que la regla de swap no aplica y si la RAM se agota el kernel mata procesos directamente (OOM). La RAM (31 GB) está al 38 %.
- **Actualización:** se dejó `habilitar-sensores.sh` listo (instala smartmontools, activa `drivetemp`, prueba `nct6775` y crea un permiso de sudoers mínimo para leer SMART). Pendiente de que el usuario lo ejecute; ni `asus_ec_sensors` ni `asus_wmi_sensors` declaran la PRIME B550-PLUS, así que los voltajes dependen de que `nct6775` reconozca el chip y no están garantizados.
- **Estado:** abierto (voltajes y SMART de SATA)

### 2026-10-28 — Búsqueda de xmrig: no está instalado (la alerta vista era una prueba)
- **Tipo:** observación
- **Origen de la consulta:** el usuario vio una notificación que nombraba `xmrig` y supuso que había uno instalado.
- **Causa:** esa notificación salió de la prueba de extremo a extremo de las alertas, con un `sleep` renombrado como `xmrig` y un archivo EICAR, en una base temporal. Ya se eliminaron y no existen en la base real: 0 hallazgos de minero y 0 notificaciones registradas.
- **Búsqueda (solo lectura, sin root):** procesos, apt, snap, flatpak, pip, binarios en PATH, archivos por nombre (`xmrig`, `xmr-stak`, `minerd`, `cpuminer`, `kdevtmpfsi`, `kinsing`) en `/`, `/home` y `/home/v/storage`, cron del usuario, unidades de systemd y autostart, contenido de Downloads, `~/.local` y `~/.config`, imágenes de Docker y historial de shell. Sin resultados en ninguno.
- **Limitaciones:** sin root no se inspeccionan directorios restringidos, el cron del sistema ni los contenedores o volúmenes de Docker ajenos. El disco Patriot (`sdb`) no aparece montado, así que no se pudo revisar.
- **Estado:** resuelto (sin amenaza encontrada)

### 2026-10-28 — ttyd y fluidsynth dejan de ser accesibles desde la LAN
- **Tipo:** solución
- **ttyd:** `centro-hogar-ttyd.service` ahora usa `-i 127.0.0.1` (antes `0.0.0.0`). Verificado: desde `192.168.0.9:7681` no responde y en `127.0.0.1:7681` devuelve HTTP 200. Efecto: el portal Centro-Hogar ya no se puede abrir desde otros equipos de la red. Original respaldado fuera del proyecto; para revertir, volver a `-i 0.0.0.0`.
- **fluidsynth:** la versión 2.3.4 no permite limitar su servidor a localhost y sin ese servidor el proceso termina. Se creó el override `~/.config/systemd/user/fluidsynth.service.d/sin-servidor-red.conf` con `PrivateNetwork=yes`: el puerto 9800 ya no es alcanzable ni desde la LAN ni desde el host. MIDI (ALSA) y audio (PipeWire) siguen funcionando (cliente MIDI presente).
- **Incidente durante el cambio:** el primer intento (quitar `-s`) hizo que `fluidsynth` terminara y el servicio quedó caído unos 30 s hasta aplicar `PrivateNetwork`. Ya está activo.
- **Revertir fluidsynth:** borrar el override y `systemctl --user daemon-reload && systemctl --user restart fluidsynth`.
- **Estado:** resuelto (las entradas de exposición de más abajo quedan como historial)

### 2026-10-28 — Terminal web sin autenticación expuesta en la LAN (ttyd)
- **Tipo:** error (exposición de seguridad)
- **Datos:** el servicio de usuario `centro-hogar-ttyd.service` lanza `ttyd -i 0.0.0.0 -p 7681 -W --url-arg bash`: escucha en todas las interfaces, es escribible (`-W`), no tiene credenciales (`-c`) y ofrece `bash` como usuario `v`. Activo desde 2026-10-26. IP LAN: 192.168.0.9.
- **Riesgo:** cualquier equipo de la red local puede abrir `http://192.168.0.9:7681` y ejecutar comandos como `v`. `--url-arg` permite además pasar argumentos al programa por la URL.
- **Resolución:** limitado a `127.0.0.1` (ver la entrada de arriba).
- **Estado:** resuelto

### 2026-10-28 — Búsqueda de mineros, keyloggers y procesos fantasma (sin hallazgos)
- **Tipo:** observación
- **Resultado:** 450 procesos revisados (45 sin acceso por ser de otros usuarios). No hay mineros, procesos que se ejecuten desde `/tmp`, binarios que imiten hilos del kernel, lectores sospechosos de `/dev/input` ni conexiones a IPs de botnets (Feodo, 5 IPs) ni dominios de la lista NoCoin (312).
- **Puertos accesibles desde la red:** Steam `27036` (esperable), DNS de libvirt `192.168.122.1:53` (virbr0), `fluidsynth` `:::9800` (servidor de comandos en todas las interfaces, servicio `fluidsynth.service`, conviene limitarlo a localhost; ya resuelto) y el `ttyd` anterior (ya resuelto).
- **Falso positivo resuelto:** el overlay de Steam usa `LD_PRELOAD` desde `/tmp/pressure-vessel-libs-*`; se excluyó `gameoverlayrenderer.so`.
- **Limitación:** el escaneo corre sin root; no detecta rootkits ni ve los descriptores de otros usuarios.
- **Estado:** resuelto (se vigila en cada corrida)

### 2026-10-28 — Perfil de energía cambiado de `performance` a `balanced`
- **Tipo:** solución
- **Detalle:** se pidió `schedutil`, pero no existe en este equipo: con `amd-pstate-epp` activo solo hay `performance` y `powersave`. El governor lo fijaba el perfil de energía del sistema (`performance`), así que se ejecutó `powerprofilesctl set balanced` (sin sudo): governor `powersave`, EPP `balance_performance`.
- **Efecto inicial:** `Tctl` 77 °C → ~66 °C a los 20 s (aún sin estabilizar). `fan1` pasó a 0 RPM, probablemente el modo de ventilador detenido a baja temperatura; a confirmar.
- **Revertir:** `powerprofilesctl set performance`.
- **Estado:** resuelto la causa probable de la entrada de temperatura; confirmar con más datos.

### 2026-10-28 — Temperatura de CPU elevada (Tctl 73–85 °C con carga baja)
- **Tipo:** observación
- **Datos:** `Tctl` 77 °C en vivo (`Tccd1` 69 °C, GPU `edge` 50 °C). Historial: 76,6 °C y 73,0 °C en las dos corridas del recolector, con CPU al 4–13 % y load 0,28. Pico previo de ~85 °C. Ventilador `fan1` a 682 RPM (máx. 3200).
- **Contexto:** había un juego (Slay the Spire) y Steam abiertos. El governor de la CPU es `performance`, que mantiene las frecuencias altas incluso en reposo.
- **Evaluación:** no es crítico (el límite de throttling del Ryzen 5000 ronda los 90 °C), pero es alto para una carga ligera. Causas probables, sin confirmar: governor `performance`, curva de ventilador conservadora o pasta térmica/flujo de aire. Hay solo 2 muestras, no hay tendencia todavía.
- **Pendiente:** volver a revisar con `historial("temp_cpu", "7d")` cuando haya más datos y comparar en reposo real.
- **Seguimiento:** el governor se cambió a `balanced` (ver entrada de perfil de energía).
- **Estado:** abierto (a confirmar tras el cambio de perfil)

### 2026-10-28 — Instalación de pc-doctor
- **Tipo:** cambio
- **Detalle:** se instaló el recolector (timer de usuario) y se registró el MCP `pc-doctor`.
- **Observación:** `Tctl` llegó a ~85 °C tras correr el recolector; se sigue en la entrada "Temperatura de CPU elevada".
- **Estado:** resuelto
