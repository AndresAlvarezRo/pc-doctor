# Operación

Instalar, usar, configurar y desactivar pc-doctor. Cómo está hecho: [ARQUITECTURA.md](ARQUITECTURA.md).

## Instalación
Requisitos: `uv`, `python3`, `lm-sensors` y `lshw` (opcionales: `nvidia-smi`, `flatpak`, `snap`).

```bash
cd <carpeta-del-proyecto>
uv sync                                   # crea el entorno (.venv, visible como venv/)

# Recolector, reporte semanal y dashboard (servicios de usuario de systemd)
mkdir -p ~/.config/systemd/user
cp systemd/*.service systemd/*.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now pc-doctor.timer pc-doctor-reporte.timer pc-doctor-web.service

# Servidor MCP en Claude Code
claude mcp add pc-doctor -s user -- uv run --directory <carpeta-del-proyecto> server.py
```

Verificación: `systemctl --user list-timers 'pc-doctor*'`, `systemctl --user status pc-doctor-web` y `claude mcp list`. Corrida manual del recolector: `uv run collector.py`.

Opcional: `bash web/construir.sh` (compila el frontend; necesita Node, ver [Desarrollo](DESARROLLO.md)), el lanzador de `web/pc-doctor.desktop` (copiarlo a `~/.local/share/applications/`, con el ícono `web/frontend/public/icono.svg` en `~/.local/share/icons/hicolor/scalable/apps/pc-doctor.svg`) y `bash scripts/instalar-hooks.sh` si vas a desarrollar.

## Dashboard
- **Abrir:** desde el menú de aplicaciones ("pc-doctor"), el ícono del escritorio, `http://localhost:8787`, `uv run dashboard.py abrir [seccion]` o la tool `abrir_dashboard` desde Claude Code. Si el servicio estaba apagado, se arranca solo.
- **Enlaces directos:** `/alerta/{id}`, `/hallazgo/{id}`, `/componente/{tipo}` y las secciones `#alertas`, `#reportes`, `#linea-de-tiempo`, `#limitaciones` y `#entorno`.
- **Apagar:** `systemctl --user disable --now pc-doctor-web.service`. **Reiniciar tras recompilar:** `systemctl --user restart pc-doctor-web`.
- **Seguridad:** escucha solo en `127.0.0.1`, rechaza cualquier `Host` que no sea `localhost:8787` o `127.0.0.1:8787` (contra DNS rebinding), acepta `GET` y solo tres `POST` (aprobar, rechazar y deshacer un plan de remediación), que exigen además `Origin` propio, `Content-Type: application/json` y el token local de `web_token`. Abre la base en modo de solo lectura salvo en esos tres casos.
- **Notificaciones con botón:** "Ver en el dashboard" abre la alerta o el hallazgo del aviso. Se activa con `"boton_dashboard": true` en `config.json` (apagado por defecto); si el escritorio no lo soporta, la notificación sale igual, sin botón. Probar: `uv run alertas.py --probar-boton` (envía una notificación real).
- **Instalar como app:** en Chrome o Edge, desde el menú del navegador ("Instalar pc-doctor").

## Configuración
`datos/config.json` (se crea solo; las claves que falten usan su valor por defecto):

| Clave | Para qué |
|---|---|
| `notificaciones` | Apaga todas las notificaciones de escritorio con `false` |
| `salud` | Apaga las alertas de salud con `false` |
| `umbrales` | Cambia límites de las reglas, por ejemplo `{"temp_cpu": {"aviso": 80, "muestras": 1}}` |
| `consulta_online` | Permite consultar la reputación de hashes sospechosos |
| `malwarebazaar_key` | Clave de abuse.ch (vacía: ese proveedor queda apagado) |
| `mostrar_en_pantalla` | `"nunca"` (defecto: las notificaciones van directo a la bandeja, sin banner), `"fuera_de_juego"` (sin banner mientras hay un juego en curso) o `"siempre"`. Ver «Notificaciones sin banner» |
| `boton_dashboard` | Botón "Ver en el dashboard" en las notificaciones (apagado por defecto) |
| `reporte` | `false` o un objeto con `habilitado`, `modelo`, `max_turns`, `timeout_s` y `claude` (ruta) |
| `remediacion` | Autonomía y límites de la remediación (ver [REMEDIACION.md](REMEDIACION.md)) |
| `correlacion` | `horas_antes` y `horas_despues` de la ventana de posibles causas (48 y 2 por defecto) |

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
- La remediación no libera espacio en disco (cuarentena en el mismo disco): contra una alerta de espacio sus planes terminan `fallido`. «Empeoró» sin un hecho conocido compara con el diagnóstico anterior y no conoce el sentido de cada regla. Cualquier proceso con `pc-doctor` o `claude` en su línea de comandos está protegido contra `cerrar_proceso`.
- El reporte semanal puede quedar sin redactar (plan B) si Claude no está disponible; texto malicioso en los datos del equipo puede terminar en el archivo del reporte (el modelo no puede ejecutar nada ni salir de pc-doctor).

## Notificaciones sin banner
`mostrar_en_pantalla` cambia solo cómo se muestran los avisos; se evalúan, registran y deduplican igual y quedan en el centro de notificaciones.
- **Linux (GNOME):** las notificaciones se identifican como la app `pc-doctor` (`desktop-entry`, igual al `.desktop`), no son transitorias; GNOME 46 muestra en pantalla las críticas aunque los banners estén apagados, así que sin banner todo se envía con urgencia normal (queda en la bandeja); y, para "sin banner", se ajusta únicamente la clave `show-banners` de pc-doctor (nunca la configuración global, otras apps ni "No molestar"). El recolector la sincroniza en cada corrida (resolución de la detección de juegos: unos 15 min). Si cambiás esa clave a mano en Configuración de GNOME, pc-doctor lo respeta (`banners.json` en la carpeta de datos guarda lo último que escribió) hasta que cambies `mostrar_en_pantalla`.
- **Windows:** el toast lleva `SuppressPopup` y va directo al Centro de actividades.
