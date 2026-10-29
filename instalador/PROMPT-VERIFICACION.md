# Prompt de verificación de la instalación

Abrí Claude Code en esta PC y pegale todo lo que está debajo de la línea.

---

Acabo de instalar pc-doctor en esta PC con Windows. Tu tarea es **verificar que funciona y documentar lo que encuentres**. No es una tarea de programación.

**Reglas**
- NO modifiques el código de pc-doctor (nada dentro de `%LOCALAPPDATA%\Programs\pc-doctor`). Si algo está mal, lo documentás para que se corrija en la PC de desarrollo.
- No instales ni desinstales nada, no ejecutes `habilitar-sensores.ps1` y no pidas administrador.
- No inventes datos: si algo no se puede medir, anotá que no se pudo y por qué.

**Pasos**
1. Ejecutá `powershell -ExecutionPolicy Bypass -File "%LOCALAPPDATA%\Programs\pc-doctor\instalar.ps1" -Verificar` y anotá cada línea que no diga `[ok]`.
2. Usá las herramientas del MCP pc-doctor: `perfil_entorno()`, `estado_salud()`, `revision_seguridad()`, `puertos_en_escucha()` y `alertas_salud()`.
3. Revisá que los datos tengan sentido:
   - el hardware que informa coincide con esta PC (procesador, memoria, discos, placa de video);
   - no hay valores imposibles en los sensores (temperaturas negativas o de más de 110 °C, ventiladores vacíos, voltajes en cero);
   - no hay alertas que sean claramente falsos positivos (por ejemplo, programas de Windows o de uso normal señalados como sospechosos).
4. Registrá lo que encuentres con `registrar_changelog` (solo hechos verificados).
5. Escribí `informe-instalacion.md` en `%LOCALAPPDATA%\pc-doctor` con:
   - qué pasó y qué no con la instalación y con cada paso de `-Verificar`;
   - los nombres exactos de los sensores y sus valores tal como los devuelve pc-doctor;
   - los posibles falsos positivos de seguridad (nombre, categoría, motivo que dio la herramienta);
   - lo que no se pudo medir.

Al terminar, decime la ruta del informe y un resumen de tres líneas.
