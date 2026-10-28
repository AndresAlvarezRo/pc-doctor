import { useApi } from '../api'
import { Aviso, Contenido, InsigniaEstado } from '../comunes'
import { IconoVolver } from '../iconos'
import { contextoTexto, numero, valorConUnidad } from '../formato'
import type { Componente, RespuestaComponentes, Sensor } from '../tipos'
import { Grafico } from './Grafico'

function Referencia({ s }: { s: Sensor }) {
  if (s.referencia === 'aprendida' && s.banda) {
    const [a, b] = s.banda.tipica
    return (
      <span className={s.dentro_de_banda === false ? 'ref ref-fuera' : 'ref'}>
        {s.dentro_de_banda === false ? 'Fuera de lo habitual. ' : ''}Habitual en {contextoTexto(s.banda.contexto).toLowerCase()}: {numero(a)} a {numero(b)}
      </span>
    )
  }
  if (s.referencia === 'aprendiendo') return <span className="ref">Aprendiendo lo normal ({s.banda ? `${s.banda.n} de 200 muestras` : 'sin muestras en este contexto'})</span>
  if (s.referencia === 'fija') return <span className="ref">Se compara contra un límite fijo</span>
  return <span className="ref ref-nada">Sin referencia</span>
}

function textoGiro(s: Sensor): string | null {
  if (s.giro === 'vacio') return 'Conector sin ventilador (nunca giró)'
  if (s.giro === 'parado') return 'Parado: giraba antes'
  return null
}

function VistaComponente({ c, sensorInicial, tick, alElegir }: { c: Componente; sensorInicial: string | null; tick: number; alElegir: (s: string) => void }) {
  const elegido = c.sensores.find((s) => s.nombre === sensorInicial) ?? c.sensores.find((s) => s.nombre === c.principal?.nombre) ?? c.sensores[0]
  const graficable = (s: Sensor) => s.unidad !== 'bool'
  return (
    <article className="componente">
      <header className="componente-cabecera">
        <h3>{c.titulo}</h3>
        <InsigniaEstado estado={c.estado} />
      </header>
      <div className="detalle-cuerpo">
        <ul className="sensores" aria-label="Sensores">
          {c.sensores.map((s) => (
            <li key={s.nombre}>
              <button type="button" className={`sensor${s.nombre === elegido?.nombre ? ' sensor-elegido' : ''}`} aria-pressed={s.nombre === elegido?.nombre} onClick={() => alElegir(s.nombre)}>
                <span className="sensor-nombre">{s.etiqueta}</span>
                <span className="sensor-valor">{valorConUnidad(s.valor, s.unidad)}</span>
                <span className="sensor-estado"><InsigniaEstado estado={s.estado} /></span>
                <span className="sensor-ref">{textoGiro(s) ?? <Referencia s={s} />}</span>
                {s.mensaje && <span className="sensor-mensaje">{s.mensaje}</span>}
              </button>
            </li>
          ))}
        </ul>
        <div className="detalle-grafico">
          {elegido && (
            <>
              <h4>{elegido.etiqueta}</h4>
              <p className="nombre-tecnico">{elegido.nombre}</p>
              {graficable(elegido) ? <Grafico key={elegido.nombre} sensor={elegido.nombre} tick={tick} /> : <Aviso>Este sensor es de tipo sí o no: no tiene gráfico.</Aviso>}
            </>
          )}
        </div>
      </div>
    </article>
  )
}

export function Detalle({ tipo, id, sensor, tick, alVolver, alElegir }: { tipo: string; id: string | null; sensor: string | null; tick: number; alVolver: () => void; alElegir: (id: string, sensor: string) => void }) {
  const carga = useApi<RespuestaComponentes>(`/api/componentes/${encodeURIComponent(tipo)}`, tick)
  return (
    <div className="detalle">
      <button type="button" className="boton boton-volver" onClick={alVolver}>
        <IconoVolver /> Volver al estado
      </button>
      <Contenido
        carga={carga}
        hijos={(r) => {
          const lista = id ? r.componentes.filter((c) => c.id === id) : r.componentes
          return (
            <>
              <h2>{r.titulo}</h2>
              <p className="ayuda">Contexto actual: {contextoTexto(r.contexto).toLowerCase()}. Elegí un sensor para ver su historia.</p>
              {lista.length === 0 && <Aviso>No hay lecturas de este componente en este momento.</Aviso>}
              {lista.map((c) => (
                <VistaComponente key={c.id} c={c} sensorInicial={sensor} tick={tick} alElegir={(s) => alElegir(c.id, s)} />
              ))}
            </>
          )
        }}
      />
    </div>
  )
}
