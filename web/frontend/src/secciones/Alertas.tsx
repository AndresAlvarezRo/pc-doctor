import { useEffect, useRef, useState } from 'react'
import { useApi } from '../api'
import { Aviso, Contenido, InsigniaSeveridad, Seccion } from '../comunes'
import { IconoInfo, IconoRelacion } from '../iconos'
import { fechaYHora, hace } from '../formato'
import type { Alerta, Correlacion, Hallazgo } from '../tipos'

const CATEGORIAS: Record<string, string> = { cpu: 'Procesador', gpu: 'Placa de video', disco: 'Disco', memoria: 'Memoria', placa: 'Placa madre', sistema: 'Sistema' }
const ESTADOS_HALLAZGO: Record<string, string> = { nuevo: 'Nuevo', revisado: 'Revisado', falso_positivo: 'Falso positivo' }

/** Posibles causas de una alerta o de un hallazgo. Son coincidencias en el tiempo, no causas demostradas. */
function PosiblesCausas({ id, tick }: { id: string; tick: number }) {
  const carga = useApi<Correlacion>(`/api/correlacion/${encodeURIComponent(id)}`, tick)
  return (
    <div className="causas">
      <Contenido
        carga={carga}
        hijos={(c) => (
          <>
            <p className="ayuda">Lo que pasó cerca de {c.alerta.momento}, ordenado por cercanía y afinidad. {c.aviso}</p>
            {c.posibles_causas.length === 0 ? (
              <p className="vacio">No hay nada registrado cerca de este momento.</p>
            ) : (
              <ol className="lista-causas">
                {c.posibles_causas.map((x, i) => (
                  <li key={i}>
                    <span className={`relevancia relevancia-${x.relevancia}`}>{x.relevancia === 'alta' ? 'Relevancia alta' : x.relevancia === 'media' ? 'Relevancia media' : 'Relevancia baja'}</span>
                    <span className="causa-cuando">{x.cuando}</span>
                    <span className="causa-que">{x.que}</span>
                  </li>
                ))}
              </ol>
            )}
            {c.otros_candidatos > 0 && <p className="ayuda">Y {c.otros_candidatos} coincidencias más de menor relevancia.</p>}
          </>
        )}
      />
    </div>
  )
}

function FilaAlerta({ a, abierta, alAlternar, tick }: { a: Alerta; abierta: boolean; alAlternar: () => void; tick: number }) {
  const ref = useRef<HTMLLIElement>(null)
  useEffect(() => {
    if (abierta) ref.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [abierta])
  return (
    <li ref={ref} className={`fila fila-${a.severidad}${a.estado === 'resuelta' ? ' fila-resuelta' : ''}`} id={`alerta-${a.id}`}>
      <div className="fila-cabecera">
        <InsigniaSeveridad severidad={a.severidad} />
        <span className="fila-estado">{a.estado === 'activa' ? 'Activa' : `Resuelta ${a.resuelta_en ? hace(a.resuelta_en) : ''}`}</span>
      </div>
      <p className="fila-mensaje">{a.mensaje}</p>
      <p className="fila-meta">
        {CATEGORIAS[a.categoria ?? ''] ?? a.categoria ?? 'General'} · Desde {fechaYHora(a.desde * 1000)} ({hace(a.desde)}) · {a.veces} {a.veces === 1 ? 'vez' : 'veces'}
      </p>
      {a.hecho_conocido && (
        <p className="relacion hecho-conocido">
          <IconoInfo /> <span><strong>Hecho conocido #{a.hecho_conocido.id}:</strong> {a.hecho_conocido.texto}{a.hecho_conocido.vence ? ` (a revisar el ${a.hecho_conocido.vence})` : ''}. No se vuelve a avisar mientras no empeore.</span>
        </p>
      )}
      {a.relacion && (
        <p className="relacion">
          <IconoRelacion /> <span><strong>Posible relación:</strong> {a.relacion}</span>
        </p>
      )}
      <button type="button" className="boton boton-chico" aria-expanded={abierta} onClick={alAlternar}>
        {abierta ? 'Ocultar posibles causas' : 'Ver posibles causas'}
      </button>
      {abierta && <PosiblesCausas id={String(a.id)} tick={tick} />}
    </li>
  )
}

function FilaHallazgo({ h, abierta, alAlternar, tick }: { h: Hallazgo; abierta: boolean; alAlternar: () => void; tick: number }) {
  return (
    <li className={`fila fila-h-${h.severidad}${h.estado === 'falso_positivo' ? ' fila-resuelta' : ''}`}>
      <div className="fila-cabecera">
        <InsigniaSeveridad severidad={h.severidad} />
        <span className="fila-estado">{ESTADOS_HALLAZGO[h.estado]}</span>
      </div>
      <p className="fila-mensaje">
        <strong>{h.proceso ?? 'Sin proceso'}</strong>: {h.detalle}
      </p>
      <p className="fila-meta">
        {h.categoria} · Primera vez {fechaYHora(h.primera_vez * 1000)} · Última {hace(h.ultima_vez)} · {h.veces} {h.veces === 1 ? 'vez' : 'veces'}
        {h.reputacion ? ` · Reputación: ${h.reputacion.veredicto.replace(/_/g, ' ')}${h.reputacion.fuente ? ` (${h.reputacion.fuente})` : ''}` : ''}
      </p>
      <button type="button" className="boton boton-chico" aria-expanded={abierta} onClick={alAlternar}>
        {abierta ? 'Ocultar posibles causas' : 'Ver posibles causas'}
      </button>
      {abierta && <PosiblesCausas id={`hallazgo:${h.id}`} tick={tick} />}
    </li>
  )
}

export function Alertas({ tick, abrirAlerta, abrirHallazgo }: { tick: number; abrirAlerta: string | null; abrirHallazgo: string | null }) {
  const [pestana, setPestana] = useState<'alertas' | 'hallazgos'>(abrirHallazgo ? 'hallazgos' : 'alertas')
  const [filtro, setFiltro] = useState<'activas' | 'resueltas' | 'todas'>(abrirAlerta ? 'todas' : 'activas')
  const [dias, setDias] = useState(abrirAlerta ? 30 : 7)
  const [filtroH, setFiltroH] = useState<'todos' | 'nuevo' | 'revisado' | 'falso_positivo'>('todos')
  const [abierta, setAbierta] = useState<string | null>(abrirAlerta ?? (abrirHallazgo ? `h${abrirHallazgo}` : null))
  const [diasH, setDiasH] = useState(abrirHallazgo ? 365 : 30)
  useEffect(() => {
    if (abrirAlerta) {
      setPestana('alertas')
      setFiltro('todas')
      setDias(30)
      setAbierta(abrirAlerta)
    }
  }, [abrirAlerta])
  useEffect(() => {
    if (abrirHallazgo) {
      setPestana('hallazgos')
      setFiltroH('todos')
      setDiasH(365)
      setAbierta(`h${abrirHallazgo}`)
    }
  }, [abrirHallazgo])
  const alertas = useApi<{ total: number; alertas: Alerta[] }>(pestana === 'alertas' ? `/api/alertas?estado=${filtro}&dias=${dias}` : null, tick)
  const hallazgos = useApi<{ total: number; hallazgos: Hallazgo[] }>(pestana === 'hallazgos' ? `/api/hallazgos?estado=${filtroH}&dias=${diasH}` : null, tick)

  return (
    <Seccion id="alertas" titulo="Alertas y hallazgos" ayuda="Las alertas vienen de las lecturas de salud; los hallazgos, del escaneo de seguridad.">
      <div className="controles">
        <div className="segmentos" role="group" aria-label="Tipo de lista">
          <button type="button" aria-pressed={pestana === 'alertas'} onClick={() => setPestana('alertas')}>Alertas de salud</button>
          <button type="button" aria-pressed={pestana === 'hallazgos'} onClick={() => setPestana('hallazgos')}>Hallazgos de seguridad</button>
        </div>
        {pestana === 'alertas' ? (
          <>
            <div className="segmentos" role="group" aria-label="Estado de las alertas">
              {(['activas', 'resueltas', 'todas'] as const).map((f) => (
                <button key={f} type="button" aria-pressed={filtro === f} onClick={() => setFiltro(f)}>{f === 'activas' ? 'Activas' : f === 'resueltas' ? 'Resueltas' : 'Todas'}</button>
              ))}
            </div>
            <div className="segmentos" role="group" aria-label="Período">
              {[7, 30, 90].map((d) => (
                <button key={d} type="button" aria-pressed={dias === d} onClick={() => setDias(d)}>{d} días</button>
              ))}
            </div>
          </>
        ) : (
          <div className="segmentos" role="group" aria-label="Estado de los hallazgos">
            {(['todos', 'nuevo', 'revisado', 'falso_positivo'] as const).map((f) => (
              <button key={f} type="button" aria-pressed={filtroH === f} onClick={() => setFiltroH(f)}>{f === 'todos' ? 'Todos' : ESTADOS_HALLAZGO[f]}</button>
            ))}
          </div>
        )}
      </div>
      {pestana === 'alertas' ? (
        <Contenido
          carga={alertas}
          hijos={(r) =>
            r.alertas.length === 0 ? (
              <Aviso>No hay alertas {filtro === 'activas' ? 'activas' : filtro === 'resueltas' ? 'resueltas' : ''} en este período.</Aviso>
            ) : (
              <ul className="filas">
                {r.alertas.map((a) => (
                  <FilaAlerta key={a.id} a={a} tick={tick} abierta={abierta === String(a.id)} alAlternar={() => setAbierta(abierta === String(a.id) ? null : String(a.id))} />
                ))}
              </ul>
            )
          }
        />
      ) : (
        <Contenido
          carga={hallazgos}
          hijos={(r) =>
            r.hallazgos.length === 0 ? (
              <Aviso>No hay hallazgos con este filtro.</Aviso>
            ) : (
              <ul className="filas">
                {r.hallazgos.map((h) => (
                  <FilaHallazgo key={h.id} h={h} tick={tick} abierta={abierta === `h${h.id}`} alAlternar={() => setAbierta(abierta === `h${h.id}` ? null : `h${h.id}`)} />
                ))}
              </ul>
            )
          }
        />
      )}
    </Seccion>
  )
}
