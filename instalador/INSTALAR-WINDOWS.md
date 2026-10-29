# Instalar pc-doctor en Windows (v1.0)

pc-doctor vigila la salud de tu PC: temperaturas, discos, memoria, programas raros y errores del sistema. Te avisa con una notificación cuando algo anda mal y tiene un panel que se abre en el navegador. **Todo queda en tu PC.** No hace falta ser administrador.

## Qué necesitás
- Windows 10 u 11 de 64 bits.
- Conexión a internet durante la instalación (baja Python y las librerías).
- *Opcional:* [Claude Code](https://claude.com/claude-code). Con él, pc-doctor te escribe un reporte semanal en lenguaje común y podés preguntarle cosas sobre tu PC. En Windows, Claude Code necesita [Git for Windows](https://git-scm.com). Sin Claude Code, todo lo demás funciona.

## Instalar
1. Hacé clic derecho en el archivo `.zip` → **Extraer todo…** y elegí una carpeta (por ejemplo, Descargas).
2. (Recomendado) Comprobá que el archivo no se dañó. En PowerShell: `Get-FileHash pc-doctor-Win-v1.0.zip` y comparalo con el número del archivo `.sha256`.
3. Abrí la carpeta extraída, hacé clic en la barra de direcciones, escribí `powershell` y apretá Enter.
4. Escribí:
   ```
   powershell -ExecutionPolicy Bypass -File instalar.ps1
   ```
5. Leé el plan que muestra y escribí `SI` para seguir. Tarda unos minutos.

Si algo falla, el instalador te dice qué pasó. Podés volver a correrlo: retoma sin duplicar nada.

Para ver qué haría **sin cambiar nada**, agregá `-Simular` al final.

## Qué instala y dónde
| Qué | Dónde |
|---|---|
| El programa | `%LOCALAPPDATA%\Programs\pc-doctor` |
| Tus datos (mediciones, configuración, reportes) | `%LOCALAPPDATA%\pc-doctor` |
| Tareas programadas (sin ventana): medición cada 15 minutos, panel, reporte de los domingos | Programador de tareas: `pc-doctor-recolector`, `pc-doctor-web`, `pc-doctor-reporte` |
| Acceso directo **pc-doctor** | Escritorio y menú Inicio |

El panel solo se puede abrir desde tu propia PC (`http://localhost:8787`). pc-doctor **nunca borra archivos**: lo que limpia lo manda a una carpeta de cuarentena. A internet solo sale la huella (hash) de un archivo que ya parecía sospechoso, nunca el archivo.

## Usarlo
Abrí el acceso directo **pc-doctor**. Si el panel estaba apagado, lo enciende y abre el navegador.

## Comprobar que anda
```
powershell -ExecutionPolicy Bypass -File "%LOCALAPPDATA%\Programs\pc-doctor\instalar.ps1" -Verificar
```
Muestra qué está funcionando, qué se puede medir y qué no. Si instalaste Claude Code, también podés abrirlo y pegarle el texto de `PROMPT-VERIFICACION.md` (está en la carpeta del programa): revisa la instalación y deja un informe.

## Lo que Windows no deja medir sin administrador
Sin permisos de administrador, **no se pueden leer** las temperaturas de procesador y placa, los ventiladores, los voltajes, el detalle SMART de los discos (sectores dañados), ni el estado de BitLocker y Secure Boot. pc-doctor no inventa esos números: los muestra como «no disponible» y en la pantalla de limitaciones.

Si querés medirlos, hay un paso **opcional y aparte**. Se hace una sola vez, como administrador:
```
powershell -ExecutionPolicy Bypass -File "%LOCALAPPDATA%\Programs\pc-doctor\habilitar-sensores.ps1" -Simular
```
Con `-Simular` solo muestra qué instalaría (LibreHardwareMonitor y, si querés, smartmontools), con direcciones y huellas SHA-256. Cuando lo hayas leído, ejecutalo sin `-Simular` desde una ventana de PowerShell abierta como administrador. Para quitarlo: `-Deshacer`.

## Desinstalar
```
powershell -ExecutionPolicy Bypass -File "%LOCALAPPDATA%\Programs\pc-doctor\instalar.ps1" -Desinstalar
```
Quita las tareas, los accesos directos y el programa. **No borra tus datos**: quedan en `%LOCALAPPDATA%\pc-doctor`; si no los querés, borrá esa carpeta a mano. Si instalaste el ayudante, quitalo antes con `habilitar-sensores.ps1 -Deshacer`.

## Si Windows Defender protesta
El instalador no descarga ni ejecuta nada que no esté fijado y verificado por su huella. Si Defender o SmartScreen avisan sobre `instalar.ps1`, es porque el archivo no está firmado por una empresa: podés leerlo (es texto) antes de ejecutarlo.

## Qué todavía no está probado
Esta versión se armó en una PC con Linux y **todavía no corrió en un Windows real**. Es probable que aparezcan detalles al instalarla. Si algo falla, el instalador se detiene con un mensaje y se puede volver a correr. Lo más delicado sin probar: las tareas programadas, el acceso directo, el registro en Claude Code y todo el paso opcional de sensores. Por eso conviene correr `-Verificar` al terminar y, si tenés Claude Code, usar `PROMPT-VERIFICACION.md`: deja un informe (`informe-instalacion.md`) con lo que encontró.
