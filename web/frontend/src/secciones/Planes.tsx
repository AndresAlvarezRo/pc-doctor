import { useEffect, useRef, useState } from 'react'
import { ErrorApi, escribir, useApi } from '../api'
import { Aviso, Contenido, Seccion } from '../comunes'
import { fechaYHora, hace } from '../formato'
import { IconoAviso, IconoCritico, IconoInfo, IconoNormal } from '../iconos'
import type { DetallePlan, ResumenPlan } from '../tipos'

// Todo el texto de la hipótesis, la evidencia y los «porqué» lo escribió un modelo a partir de datos del equipo: se muestra como
// texto (React no interpreta HTML) y rotulado como sin verificar. Nada de eso se ejecuta: las acciones salen de un catálogo cerrado.

const ESTADOS: Record<ResumenPlan['estado'], { texto: string; nivel: 'info' | 'aviso' | 'normal' | 'critico' }> = {
  propuesto: { texto: 'Esperando tu aprobación', nivel: 'info' },
  aprobado: { texto: 'Aprobado', nivel: 'aviso' },
  rechazado: { texto: 'Rechazado o deshecho', nivel: 'aviso' },
  aplicado: { texto: 'Aplicado, verificando', nivel: 'aviso' },
  verificado: { texto: 'Verificado: funcionó', nivel: 'normal' },
  fallido: { texto: 'No funcionó', nivel: 'critico' },
  escalado: { texto: 'Escalado', nivel: 'critico' },
}
const DISPARADORES: Record<string, string> = { critica_nueva: 'Alerta crítica nueva', empeoro: 'La alerta empeoró', smart: 'Cambio en SMART', malicioso: 'Hallazgo malicioso' }
const ICONOS = { info: IconoInfo, aviso: IconoAviso, normal: IconoNormal, critico: IconoCritico }

function InsigniaPlan({ estado }: { estado: ResumenPlan['estado'] }) {
  const { texto, nivel } = ESTADOS[estado]
  const Icono = ICONOS[nivel]
  return (
    <span className={`insignia insignia-${nivel}`}>
      <Icono />
      {texto}
    </span>
  )
}

const parametros = (p: Record<string, string | number>) => {
  const e = Object.entries(p)
  return e.length === 0 ? 'sin parámetros' : e.map(([k, v]) => `${k} = ${v}`).join(', ')
}

function Detalle({ id, tick, alCambiar }: { id: number; tick: number; alCambiar: () => void }) {
  const carga = useApi<DetallePlan>(`/api/planes/${id}`, tick)
  const [confirmando, setConfirmando] = useState(false)
  const [ocupado, setOcupado] = useState(false)
  const [resultado, setResultado] = useState<{ tipo: 'info' | 'error'; texto: string } | null>(null)

  async function hacer(accion: 'aprobar' | 'rechazar' | 'deshacer') {
    setOcupado(true)
    setConfirmando(false)
    try {
      const r = await escribir<{ estado: string; resultado?: string; pendiente?: string[] }>(`/api/planes/${id}/${accion}`)
      const extra = r.pendiente && r.pendiente.length > 0 ? ` Quedó sin deshacer: ${r.pendiente.join('; ')}.` : ''
      setResultado({ tipo: 'info', texto: `Listo: el plan quedó «${ESTADOS[r.estado as ResumenPlan['estado']]?.texto ?? r.estado}».${extra}` })
    } catch (e) {
      setResultado({ tipo: 'error', texto: e instanceof ErrorApi ? e.message : 'no se pudo completar la acción' })
    } finally {
      setOcupado(false)
      alCambiar()
    }
  }

  if (carga.datos === null) return carga.error ? <Aviso tipo="error">No se pudo abrir el plan: {carga.error}</Aviso> : <p className="cargando" role="status">Cargando…</p>
  const p = carga.datos
  const aplicable = p.estado === 'propuesto' && p.acciones.length > 0
  const deshacible = ['aplicado', 'verificado', 'fallido', 'escalado'].includes(p.estado) && p.ejecuciones.some((e) => e.estado === 'aplicada' && e.reversible && e.deshecha_en === null)

  return (
    <div className="plan-detalle">
      {p.modo === 'sin_redactar' && <Aviso tipo="aviso">Este plan salió sin redactar{p.motivo ? `: ${p.motivo}` : ''}. Solo muestra lo que coincidió en el tiempo con la alerta.</Aviso>}
      {p.sospechoso.length > 0 && (
        <Aviso tipo="error">
          El modelo marcó texto sospechoso en los datos (puede ser un intento de darle órdenes): {p.sospechoso.join(' · ')}. No lo tomes como instrucción.
        </Aviso>
      )}
      <h4 className="subtitulo">Hipótesis (texto de un modelo, sin verificar)</h4>
      <p className="plan-texto">{p.hipotesis}</p>
      <p className="fila-meta">Confianza: {p.confianza ?? 'sin dato'}{p.duracion_s !== null ? ` · El diagnóstico tardó ${Math.round(p.duracion_s)} s` : ''}</p>

      {p.evidencia.length > 0 && (
        <>
          <h4 className="subtitulo">Evidencia</h4>
          <ul className="plan-lista">
            {p.evidencia.map((e, i) => (
              <li key={i}><strong>{e.referencia}:</strong> {e.dato}</li>
            ))}
          </ul>
        </>
      )}

      <h4 className="subtitulo">Acciones propuestas</h4>
      {p.acciones.length === 0 ? (
        <p className="vacio">Este plan es solo diagnóstico: no propone acciones que pc-doctor pueda aplicar.</p>
      ) : (
        <ol className="plan-acciones">
          {p.acciones.map((a, i) => (
            <li key={i}>
              <strong>{a.accion}</strong> <span className="fila-meta">({parametros(a.parametros)})</span>
              <p className="plan-simulacion"><IconoInfo /> <span>Esto haría: {a.simulacion}</span></p>
              <p className="fila-meta">Por qué (según el modelo): {a.porque}</p>
            </li>
          ))}
        </ol>
      )}

      {p.pasos_manuales.length > 0 && (
        <>
          <h4 className="subtitulo">Pasos manuales (los hacés vos)</h4>
          <ul className="plan-lista">{p.pasos_manuales.map((m, i) => <li key={i}>{m}</li>)}</ul>
        </>
      )}
      {p.como_verificar && <p className="fila-meta">Cómo verificar: {p.como_verificar}</p>}

      {p.ejecuciones.length > 0 && (
        <>
          <h4 className="subtitulo">Lo que se ejecutó</h4>
          <ul className="plan-lista">
            {p.ejecuciones.map((e) => (
              <li key={e.id}>
                <strong>{e.accion}</strong> ({parametros(e.parametros)}): {e.estado === 'aplicada' ? 'aplicada' : e.estado === 'fallida' ? 'falló' : 'rechazada'}
                {e.resumen ? `, ${e.resumen}` : ''}{e.deshecha_en ? ' (deshecha)' : ''}
              </li>
            ))}
          </ul>
        </>
      )}
      {p.resultado && <p className="fila-meta">Resultado: {p.resultado}</p>}
      {p.descartes.length > 0 && (
        <details>
          <summary>Lo que se descartó de la respuesta del modelo ({p.descartes.length})</summary>
          <ul className="plan-lista">{p.descartes.map((d, i) => <li key={i}>{d}</li>)}</ul>
        </details>
      )}

      {resultado && <Aviso tipo={resultado.tipo}>{resultado.texto}</Aviso>}
      <div className="plan-botones">
        {aplicable && !confirmando && (
          <button type="button" className="boton" disabled={ocupado} onClick={() => setConfirmando(true)}>Aplicar</button>
        )}
        {aplicable && confirmando && (
          <div className="plan-confirmacion" role="group" aria-label="Confirmar">
            <p><strong>¿Aplicar {p.acciones.length === 1 ? 'esta acción' : `estas ${p.acciones.length} acciones`}?</strong> Cada una se vuelve a validar antes de correr. Si algo falla, se detiene.</p>
            <button type="button" className="boton" disabled={ocupado} onClick={() => hacer('aprobar')}>Sí, aplicar</button>
            <button type="button" className="boton" onClick={() => setConfirmando(false)}>Cancelar</button>
          </div>
        )}
        {p.estado === 'propuesto' && !confirmando && (
          <button type="button" className="boton" disabled={ocupado} onClick={() => hacer('rechazar')}>Rechazar</button>
        )}
        {deshacible && <button type="button" className="boton" disabled={ocupado} onClick={() => hacer('deshacer')}>Deshacer</button>}
      </div>
    </div>
  )
}

function FilaPlan({ p, abierto, alAlternar, tick, alCambiar }: { p: ResumenPlan; abierto: boolean; alAlternar: () => void; tick: number; alCambiar: () => void }) {
  const ref = useRef<HTMLLIElement>(null)
  useEffect(() => {
    if (abierto) ref.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [abierto])
  const nivel = ESTADOS[p.estado].nivel
  return (
    <li ref={ref} className={`fila fila-${nivel === 'critico' ? 'critico' : nivel === 'aviso' ? 'aviso' : 'info'}`} id={`plan-${p.id}`}>
      <div className="fila-cabecera">
        <InsigniaPlan estado={p.estado} />
        <span className="fila-estado">
          {p.modo === 'modelo' ? 'Redactado por el modelo' : 'Sin redactar'} · Confianza {p.confianza ?? 'sin dato'}
        </span>
      </div>
      <p className="fila-mensaje">Plan #{p.id}: {p.firma}</p>
      <p className="fila-meta">
        {DISPARADORES[p.disparador] ?? p.disparador} · {fechaYHora(p.ts * 1000)} ({hace(p.ts)}) ·{' '}
        {p.acciones.length === 0 ? 'Solo diagnóstico' : `${p.acciones.length} ${p.acciones.length === 1 ? 'acción' : 'acciones'}`}
      </p>
      <button type="button" className="boton boton-chico" aria-expanded={abierto} onClick={alAlternar}>
        {abierto ? 'Ocultar el plan' : 'Ver el plan'}
      </button>
      {abierto && <Detalle id={p.id} tick={tick} alCambiar={alCambiar} />}
    </li>
  )
}

export function Planes({ tick, abrirPlan, alCambiar }: { tick: number; abrirPlan: string | null; alCambiar: () => void }) {
  const carga = useApi<{ planes: ResumenPlan[] }>('/api/planes?dias=30', tick)
  const [abierto, setAbierto] = useState<number | null>(abrirPlan ? Number(abrirPlan) : null)
  useEffect(() => {
    if (abrirPlan) setAbierto(Number(abrirPlan))
  }, [abrirPlan])
  return (
    <Seccion
      id="diagnosticos"
      titulo="Diagnósticos y planes"
      ayuda="Cuando salta una alerta grave, pc-doctor la diagnostica y propone un plan. Nada se aplica sin tu aprobación, y las acciones salen de un catálogo cerrado."
    >
      <Contenido
        carga={carga}
        hijos={(d) =>
          d.planes.length === 0 ? (
            <Aviso>Todavía no hay planes. Aparecen cuando salta una alerta crítica, empeora una alerta, cambia el SMART o se marca un hallazgo como malicioso.</Aviso>
          ) : (
            <ul className="filas">
              {d.planes.map((p) => (
                <FilaPlan key={p.id} p={p} abierto={abierto === p.id} alAlternar={() => setAbierto(abierto === p.id ? null : p.id)} tick={tick} alCambiar={alCambiar} />
              ))}
            </ul>
          )
        }
      />
    </Seccion>
  )
}
