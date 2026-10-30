# Remediación asistida

Cuando salta una alerta grave (crítica nueva, una que empeoró, un hallazgo malicioso o un cambio de SMART), pc-doctor la diagnostica en un trabajo aparte (el recolector no espera) y arma un plan. **El modelo solo propone; lo ejecuta el código de pc-doctor.**

1. **Catálogo cerrado.** Solo existen estas acciones, con parámetros validados: `limpiar_cache_miniaturas`, `limpiar_cache_uv`, `limpiar_cache_pip`, `limpiar_descargas_viejas(dias)`, `reiniciar_servicio_usuario(nombre)` (solo los de `servicios_permitidos`), `cambiar_perfil_energia(perfil)` y `cerrar_proceso(pid, nombre_esperado)`. En Windows el catálogo es más corto (solo ve lo que tiene implementación allá): `limpiar_descargas_viejas`, `limpiar_temporales_usuario(dias)` (los temporales de tu perfil, sin lo que Windows tiene en uso), `limpiar_cache_uv`, `limpiar_cache_pip` y `cambiar_perfil_energia` con `powercfg` (solo los planes estándar que existan en esa PC). Quedan fuera la caché de miniaturas (la bloquea el Explorador), `cerrar_proceso` y los servicios. Todo lo demás es un paso manual para vos. Nada se borra: las limpiezas van a la cuarentena (en el mismo disco, así que no liberan espacio).
2. **Los datos son no confiables.** Nombres de procesos, logs y rutas pueden traer órdenes disfrazadas: el modelo no tiene herramientas de escritura, su respuesta se valida contra un esquema y cada acción se simula, y se vuelve a validar al aplicarla.
3. **Aprobás vos.** La notificación trae «Ver el plan» (nunca «Aplicar»). En la sección «Diagnósticos y planes» del dashboard aplicás (con confirmación), rechazás o deshacés. Las escrituras del dashboard exigen Host local, Origin propio, JSON y el token de `web_token`.
4. **Verificación.** Tras aplicar, el recolector comprueba en las próximas corridas (4 = 1 h) que la alerta se resolvió y que cada acción cumplió su efecto: `verificado` o `fallido`. Si falla, avisa con todo lo intentado y deja una entrada abierta en el changelog.
5. **Recetas.** Solo un plan `verificado` crea o refuerza una receta (alerta + acciones con parámetros); un `fallido` le baja la confianza. El próximo diagnóstico de la misma alerta las recibe como datos estructurados, nunca con la hipótesis ni texto de diagnósticos anteriores. Silenciar no es arreglar: declarar algo como conocido solo lo hacés vos.

**Niveles de autonomía** (`config.json`, clave `remediacion`; se muestran los valores por defecto):

| Clave | Por defecto | Qué hace |
|---|---|---|
| `nivel` | `1` | `0` solo diagnostica (no se aplica nada); `1` plan + tu aprobación; `2` aplica sola una acción preaprobada y te avisa después |
| `preaprobadas` | `[]` | Acciones que pueden aplicarse solas en el nivel 2. Solo las preaprobables del catálogo (las tres cachés); `cerrar_proceso`, los servicios, el perfil y Descargas nunca. Lo edita solo el usuario |
| `max_diagnosticos_dia` | `3` | Tope de diagnósticos por día |
| `max_intentos_por_firma` | `2` | Aplicaciones automáticas por alerta en 24 h |
| `espera_entre_intentos_min` | `60` | Minutos mínimos entre dos aplicaciones automáticas de la misma alerta |
| `usar_modelo` | `true` | Con `false` el diagnóstico es solo la correlación («plan sin redactar») |
| `modelo`, `max_turns`, `timeout_s` | `sonnet`, `20`, `300` | Límites del `claude -p` del diagnóstico |
| `servicios_permitidos`, `verificar_corridas`, `disparadores` | `[]`, `4`, los 4 | Servicios que se pueden reiniciar, corridas de verificación y qué dispara un diagnóstico |

En el nivel 2 una acción se aplica sola únicamente si está en `preaprobadas`, es preaprobable en el catálogo y viene de una receta con **2 éxitos o más** para esa alerta. **Anti-bucle:** si después de aplicar un plan aparece una alerta nueva, se corta todo lo automático de esa alerta durante 7 días, el plan queda `escalado` y se avisa; aprobar a mano sigue siendo posible.
