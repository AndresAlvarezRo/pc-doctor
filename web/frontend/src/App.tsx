import { Suspense, lazy, useCallback, useEffect, useState } from 'react'
import { useApi } from './api'
import { useRuta } from './ruta'
import type { EstadoGeneral, NoDisponible, Tarjeta } from './tipos'
import { Alertas } from './secciones/Alertas'
import { Encabezado } from './secciones/Encabezado'
import { Entorno } from './secciones/Entorno'
import { LineaDeTiempo } from './secciones/LineaDeTiempo'
import { Limitaciones } from './secciones/Limitaciones'
import { Tarjetas } from './secciones/Tarjetas'
import { Seccion, SinConexion } from './comunes'

const INTERVALO_MS = 60_000
// Los gráficos (Recharts) y el renderizador de Markdown pesan casi todo el JavaScript: se cargan recién cuando se usan.
const Detalle = lazy(() => import('./secciones/Detalle').then((m) => ({ default: m.Detalle })))
const Reportes = lazy(() => import('./secciones/Reportes').then((m) => ({ default: m.Reportes })))
const Cargando = () => <p className="cargando" role="status">Cargando…</p>

export default function App() {
  const [ruta, ir] = useRuta()
  const [tick, setTick] = useState(0)
  const estado = useApi<EstadoGeneral | NoDisponible>('/api/estado', tick)

  // Se actualiza solo cada 60 s sin recargar la página. Con la pestaña oculta no se pide nada, y al volver se actualiza si pasó más de un minuto.
  useEffect(() => {
    let ultimo = Date.now()
    const avanzar = () => {
      ultimo = Date.now()
      setTick((t) => t + 1)
    }
    const reloj = window.setInterval(() => !document.hidden && avanzar(), INTERVALO_MS)
    const alVolver = () => !document.hidden && Date.now() - ultimo > INTERVALO_MS && avanzar()
    document.addEventListener('visibilitychange', alVolver)
    return () => {
      window.clearInterval(reloj)
      document.removeEventListener('visibilitychange', alVolver)
    }
  }, [])

  const alertas = estado.datos && !('disponible' in estado.datos) ? estado.datos.alertas.total : 0
  useEffect(() => {
    document.title = alertas > 0 ? `(${alertas}) pc-doctor` : 'pc-doctor'
  }, [alertas])

  const actualizar = useCallback(() => setTick((t) => t + 1), [])
  const abrirTarjeta = (t: Tarjeta) => ir(`/componente/${encodeURIComponent(t.tipo)}?id=${encodeURIComponent(t.id)}`)
  const alertaAbierta = ruta.vista === 'alerta' ? ruta.id : null
  const hallazgoAbierto = ruta.vista === 'hallazgo' ? ruta.id : null

  // Un enlace directo a una alerta baja hasta su sección una vez cargada la página.
  useEffect(() => {
    if (alertaAbierta || hallazgoAbierto) window.setTimeout(() => document.getElementById('alertas')?.scrollIntoView({ behavior: 'smooth' }), 300)
  }, [alertaAbierta, hallazgoAbierto])

  return (
    <SinConexion.Provider value={estado.error !== null}>
      <a className="salto" href="#contenido">Saltar al contenido</a>
      <div className="pagina">
        <Encabezado carga={estado} alActualizar={actualizar} />
        {ruta.vista === 'componente' ? (
          <main id="contenido">
            <Suspense fallback={<Cargando />}><Detalle
              tipo={ruta.tipo}
              id={ruta.id}
              sensor={ruta.sensor}
              tick={tick}
              alVolver={() => ir('/')}
              alElegir={(id, sensor) => ir(`/componente/${encodeURIComponent(ruta.tipo)}?id=${encodeURIComponent(id)}&sensor=${encodeURIComponent(sensor)}`)}
            /></Suspense>
          </main>
        ) : (
          <>
            <nav className="secciones" aria-label="Secciones">
              <a href="#estado">Estado</a>
              <a href="#alertas">Alertas y hallazgos</a>
              <a href="#linea-de-tiempo">Línea de tiempo</a>
              <a href="#reportes">Reportes</a>
              <a href="#limitaciones">Limitaciones</a>
              <a href="#entorno">Entorno</a>
            </nav>
            <main id="contenido">
              <Seccion id="estado" titulo="Estado del equipo" ayuda="Tocá una tarjeta para ver el detalle y la historia de ese componente.">
                <Tarjetas carga={estado} alAbrir={abrirTarjeta} />
              </Seccion>
              <Alertas tick={tick} abrirAlerta={alertaAbierta} abrirHallazgo={hallazgoAbierto} />
              <LineaDeTiempo tick={tick} alAbrirAlerta={(id) => ir(`/alerta/${id}`)} />
              <Suspense fallback={<Cargando />}><Reportes tick={tick} /></Suspense>
              <Limitaciones tick={tick} />
              <Entorno tick={tick} />
            </main>
          </>
        )}
        <footer className="pie">pc-doctor · Los datos se guardan y se leen solo en este equipo.</footer>
      </div>
    </SinConexion.Provider>
  )
}
