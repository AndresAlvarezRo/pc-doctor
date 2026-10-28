import { useState, type ReactElement } from 'react'
import { useApi } from '../api'
import { Aviso, Contenido, Seccion } from '../comunes'
import { IconoAviso, IconoCritico, IconoInfo, IconoJuego, IconoNormal } from '../iconos'
import { claveDia, diaCompleto, duracion, hora, numero } from '../formato'
import type { LineaDeTiempo as Linea, RespuestaSesiones } from '../tipos'

const TIPOS = [
  { id: 'entorno', texto: 'Cambios de entorno' },
  { id: 'eventos', texto: 'Eventos del sistema' },
  { id: 'alertas', texto: 'Alertas' },
  { id: 'seguridad', texto: 'Seguridad' },
  { id: 'acciones', texto: 'Acciones' },
  { id: 'sesiones', texto: 'Sesiones' },
] as const
const RANGOS = [
  { id: '24h', texto: '24 horas' },
  { id: '48h', texto: '48 horas' },
  { id: '7d', texto: '7 días' },
  { id: '30d', texto: '30 días' },
] as const

const ETIQUETA_TIPO: Record<string, { texto: string; Icono: () => ReactElement }> = {
  kernel: { texto: 'Kernel', Icono: () => <IconoInfo /> },
  driver_gpu: { texto: 'Driver de video', Icono: () => <IconoInfo /> },
  paquete: { texto: 'Paquete', Icono: () => <IconoInfo /> },
  paquete_otros: { texto: 'Paquetes', Icono: () => <IconoInfo /> },
  evento: { texto: 'Evento', Icono: () => <IconoAviso /> },
  alerta: { texto: 'Alerta', Icono: () => <IconoCritico /> },
  hallazgo: { texto: 'Seguridad', Icono: () => <IconoAviso /> },
  accion: { texto: 'Acción', Icono: () => <IconoNormal /> },
  sesion: { texto: 'Sesión', Icono: () => <IconoJuego /> },
}

export function LineaDeTiempo({ tick, alAbrirAlerta }: { tick: number; alAbrirAlerta: (id: string) => void }) {
  const [tipos, setTipos] = useState<string[]>([])
  const [rango, setRango] = useState<(typeof RANGOS)[number]['id']>('48h')
  const carga = useApi<Linea>(`/api/linea_de_tiempo?desde=${rango}&limite=300${tipos.length ? `&tipos=${tipos.join(',')}` : ''}`, tick)
  const sesiones = useApi<RespuestaSesiones>('/api/sesiones?dias=30', tick)
  const alternar = (id: string) => setTipos((t) => (t.includes(id) ? t.filter((x) => x !== id) : [...t, id]))

  return (
    <Seccion id="linea-de-tiempo" titulo="Línea de tiempo" ayuda="Todo lo que pc-doctor registró, en orden. Sirve para ver qué pasó cerca de un problema.">
      <div className="controles">
        <div className="segmentos" role="group" aria-label="Tipos de elementos">
          {TIPOS.map((t) => (
            <button key={t.id} type="button" aria-pressed={tipos.includes(t.id)} onClick={() => alternar(t.id)}>{t.texto}</button>
          ))}
        </div>
        <div className="segmentos" role="group" aria-label="Período">
          {RANGOS.map((r) => (
            <button key={r.id} type="button" aria-pressed={rango === r.id} onClick={() => setRango(r.id)}>{r.texto}</button>
          ))}
        </div>
      </div>
      <p className="ayuda">{tipos.length ? 'Mostrando solo los tipos elegidos.' : 'Mostrando todos los tipos.'}</p>
      <Contenido
        carga={carga}
        hijos={(l) => {
          if (l.items.length === 0) return <Aviso>No se registró nada en este período con estos filtros.</Aviso>
          const dias = new Map<string, typeof l.items>()
          for (const it of [...l.items].reverse()) {
            const k = claveDia(it.ts * 1000)
            dias.set(k, [...(dias.get(k) ?? []), it])
          }
          return (
            <>
              {l.nota && <Aviso tipo="aviso">{l.nota}</Aviso>}
              {[...dias.entries()].map(([k, items]) => (
                <div key={k} className="dia">
                  <h3>{diaCompleto(items[0].ts * 1000)}</h3>
                  <ul className="cronologia">
                    {items.map((it, i) => {
                      const e = ETIQUETA_TIPO[it.tipo] ?? { texto: it.tipo, Icono: () => <IconoInfo /> }
                      const alertaId = it.ref?.startsWith('alerta:') ? it.ref.split(':')[1] : null
                      return (
                        <li key={`${it.ts}-${i}`} className={`hito hito-${it.tipo}`}>
                          <time dateTime={new Date(it.ts * 1000).toISOString()}>{hora(it.ts * 1000)}</time>
                          <span className="hito-tipo"><e.Icono /> {e.texto}</span>
                          <span className="hito-titulo">
                            {it.titulo}{' '}
                            {alertaId && (
                              <a href={`/alerta/${alertaId}`} onClick={(ev) => { ev.preventDefault(); alAbrirAlerta(alertaId) }}>Ver alerta</a>
                            )}
                          </span>
                        </li>
                      )
                    })}
                  </ul>
                </div>
              ))}
            </>
          )
        }}
      />
      <h3 className="subtitulo">Sesiones de juego de los últimos 30 días</h3>
      <Contenido
        carga={sesiones}
        hijos={(s) =>
          Object.keys(s.por_juego).length === 0 ? (
            <Aviso>No se detectó ninguna sesión de juego en los últimos 30 días.</Aviso>
          ) : (
            <div className="tabla-envoltorio">
              <table className="tabla">
                <thead>
                  <tr><th>Juego</th><th>Sesiones</th><th>Tiempo jugado</th><th>Temperatura máxima del procesador</th><th>Temperatura máxima de la GPU</th></tr>
                </thead>
                <tbody>
                  {Object.entries(s.por_juego).map(([juego, d]) => (
                    <tr key={juego}>
                      <th scope="row">{juego}</th>
                      <td>{d.sesiones}</td>
                      <td>{duracion(d.minutos)}</td>
                      <td>{d.cpu_max_c !== null ? `${numero(d.cpu_max_c)} °C` : 'Sin dato'}</td>
                      <td>{d.gpu_max_c !== null ? `${numero(d.gpu_max_c)} °C` : 'Sin dato'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
      />
    </Seccion>
  )
}
