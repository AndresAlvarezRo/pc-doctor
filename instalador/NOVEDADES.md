# pc-doctor 1.1.0: novedades

Lo nuevo respecto de la 1.0. Si ya tenés la 1.0, **actualizá corriendo `instalar.ps1`**: no hay que desinstalar nada y tus datos se conservan.

## Se actualiza sin perder nada
- `instalar.ps1` detecta la versión instalada y actualiza en el lugar.
- Antes de tocar nada hace una copia de la base y de `config.json` en `copias\antes-de-1.0-<fecha>` (dentro de la carpeta de datos).
- Conserva toda tu carpeta de datos: la base, los valores normales aprendidos, los hechos conocidos, el changelog, la memoria, `config.json` y `web_token`.
- Agrega a `config.json` las opciones nuevas y no cambia las que ya tenías.
- Actualiza el bloque de pc-doctor de tu `CLAUDE.md` sin tocar lo que escribiste vos.
- `instalar.ps1 -Simular` muestra el plan: versión actual → nueva, cambios en la base y opciones nuevas.

## Remediación asistida
- Cuando salta una alerta seria, pc-doctor la diagnostica y arma un **plan** con pasos de un catálogo cerrado. Vos lo aprobás o lo rechazás desde el dashboard («Diagnósticos y planes»). Nada se ejecuta sin tu aprobación, salvo que subas el nivel de autonomía.
- Después de aplicar un plan comprueba si funcionó y aprende de los que salieron bien.
- En Windows, el catálogo trae solo lo que se puede hacer ahí sin riesgo: mover a cuarentena descargas viejas, temporales del usuario (`%TEMP%`) y las cachés de uv y pip; y cambiar el plan de energía (con `powercfg`). Todo es reversible y nada se borra.
- No están en Windows: la caché de miniaturas (la bloquea el Explorador), cerrar procesos y reiniciar servicios.

## Notificaciones sin molestar
- Nuevo `mostrar_en_pantalla` en `config.json`: `"nunca"` (el valor por defecto), `"fuera_de_juego"` o `"siempre"`.
- Con `"nunca"` los avisos no saltan en pantalla: van directo al Centro de actividades. Siguen llegando todos y el botón «Ver en el dashboard» sigue andando.

## Otros cambios
- Tras actualizar, las tareas programadas y el dashboard se vuelven a registrar y arrancar solos.
- Los controles del paquete son más estrictos: el armado falla si lleva bases, claves, pruebas, datos de prueba o rutas de la PC del autor.

## Todavía sin probar en un Windows real
Igual que la 1.0, esta versión se armó y se probó en Linux (pruebas, simulaciones y un parser de PowerShell). Después de actualizar conviene revisar la lista de «Qué todavía no está probado» de `INSTALAR-WINDOWS.md`.
