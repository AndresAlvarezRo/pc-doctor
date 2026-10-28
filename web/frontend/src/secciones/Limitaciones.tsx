import { useState } from 'react'
import { useApi } from '../api'
import { Aviso, Contenido, Seccion } from '../comunes'
import { IconoAprendiendo, IconoNormal } from '../iconos'
import { contextoTexto, numero } from '../formato'
import type { Contexto, RespuestaLimitaciones, SensorAprendizaje } from '../tipos'

function Progreso({ s }: { s: SensorAprendizaje }) {
  const pct = Math.min(100, Math.round((s.muestras / s.minimo) * 100))
  return (
    <div className="progreso" role="img" aria-label={`${s.muestras} de ${s.minimo} muestras`}>
      <div className="progreso-barra"><div style={{ width: `${pct}%` }} className={s.madura ? 'progreso-lleno progreso-listo' : 'progreso-lleno'} /></div>
      <span>{s.muestras} / {s.minimo}</span>
    </div>
  )
}

function Faltante({ s }: { s: SensorAprendizaje }) {
  if (s.madura) return <span className="base base-dentro"><IconoNormal /> Listo</span>
  if (s.depende_del_uso) return <span className="base"><IconoAprendiendo /> Depende de cuánto se use el equipo</span>
  return <span className="base"><IconoAprendiendo /> {s.dias_estimados !== null ? `Faltan unos ${numero(s.dias_estimados, s.dias_estimados < 10 ? 1 : 0)} días` : 'Faltan muestras'}</span>
}

export function Limitaciones({ tick }: { tick: number }) {
  const carga = useApi<RespuestaLimitaciones>('/api/limitaciones', tick)
  const [verTodos, setVerTodos] = useState(false)
  const [contexto, setContexto] = useState<'' | Contexto>('')
  return (
    <Seccion id="limitaciones" titulo="Limitaciones y sensores" ayuda="Qué se mide, qué no y por qué, y cuánto le falta a cada sensor para tener sus valores normales aprendidos.">
      <Contenido
        carga={carga}
        hijos={(l) => {
          const sensores = l.aprendizaje.sensores.filter((s) => !contexto || s.contexto === contexto)
          const mostrados = verTodos ? sensores : sensores.slice(0, 12)
          return (
            <>
              <h3 className="subtitulo">Lo que hoy no se puede medir</h3>
              {l.no_disponible.length === 0 ? (
                <Aviso>Todo lo que pc-doctor sabe medir está disponible en este equipo.</Aviso>
              ) : (
                <ul className="lista-simple">{l.no_disponible.map((m) => <li key={m}>{m}</li>)}</ul>
              )}

              <h3 className="subtitulo">Limitaciones conocidas</h3>
              <ul className="limitaciones">
                {l.fijas.map((f) => (
                  <li key={f.tema}>
                    <strong>{f.tema}</strong>
                    <span className="lim-que">{f.que}.</span>
                    <span className="lim-porque">{f.por_que}</span>
                  </li>
                ))}
              </ul>

              <h3 className="subtitulo">Aprendizaje de los valores normales</h3>
              <p className="ayuda">
                {l.aprendizaje.resumen.maduros} de {l.aprendizaje.resumen.sensores_con_base} sensores tienen su línea base madura (mínimo {l.aprendizaje.resumen.minimo_muestras} muestras por contexto). Hay {l.aprendizaje.resumen.dias_registrados} días en el registro diario.
              </p>
              <ul className="contextos-resumen">
                {(Object.entries(l.aprendizaje.por_contexto) as [Contexto, { sensores: number; maduros: number }][]).map(([c, d]) => (
                  <li key={c}><strong>{contextoTexto(c)}</strong> {d.maduros} de {d.sensores} listos</li>
                ))}
              </ul>
              <div className="controles">
                <div className="segmentos" role="group" aria-label="Contexto">
                  {([['', 'Todos'], ['reposo', 'Reposo'], ['carga', 'Carga'], ['juego', 'Juego']] as const).map(([id, texto]) => (
                    <button key={id} type="button" aria-pressed={contexto === id} onClick={() => setContexto(id)}>{texto}</button>
                  ))}
                </div>
              </div>
              {sensores.length === 0 ? (
                <Aviso>Todavía no hay lecturas con contexto para mostrar.</Aviso>
              ) : (
                <div className="tabla-envoltorio">
                  <table className="tabla">
                    <caption className="solo-lectores">Sensores ordenados por lo que les falta para aprender</caption>
                    <thead><tr><th>Sensor</th><th>Contexto</th><th>Muestras</th><th>Falta</th></tr></thead>
                    <tbody>
                      {mostrados.map((s) => (
                        <tr key={`${s.sensor}-${s.contexto}`}>
                          <th scope="row">{s.sensor}</th>
                          <td>{contextoTexto(s.contexto)}</td>
                          <td><Progreso s={s} /></td>
                          <td><Faltante s={s} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {sensores.length > 12 && (
                <button type="button" className="boton" onClick={() => setVerTodos(!verTodos)}>
                  {verTodos ? 'Ver menos' : `Ver los ${sensores.length} sensores`}
                </button>
              )}
            </>
          )
        }}
      />
    </Seccion>
  )
}
