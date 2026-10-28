import { useMemo, useState } from 'react'
import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from 'recharts'
import { useApi } from '../api'
import { Contenido } from '../comunes'
import { contextoTexto, dia, fechaYHora, hora, numero, valorConUnidad } from '../formato'
import type { Banda, Contexto, Punto, Serie } from '../tipos'

const RANGOS = [
  { id: '24h', texto: '24 h', horas: 24 },
  { id: '7d', texto: '7 días', horas: 168 },
  { id: '30d', texto: '30 días', horas: 720 },
  { id: '180d', texto: '6 meses', horas: 4320 },
] as const
const CONTEXTOS: { id: '' | Contexto; texto: string }[] = [
  { id: '', texto: 'Todos' },
  { id: 'reposo', texto: 'Reposo' },
  { id: 'carga', texto: 'Carga' },
  { id: 'juego', texto: 'Juego' },
]

interface Dato {
  t: number
  v: number
  banda: [number, number] | null
  fuera: number | null
  p: Punto
  contexto: Banda | null
}

/** Marcador de un punto fuera de lo habitual: un rombo (la forma, no solo el color, lo distingue de la línea). */
function Rombo({ cx, cy }: { cx?: number; cy?: number }) {
  if (cx === undefined || cy === undefined) return null
  return <path className="rombo" d={`M${cx} ${cy - 6}L${cx + 6} ${cy}L${cx} ${cy + 6}L${cx - 6} ${cy}Z`} />
}

function Globo({ active, payload, unidad }: { active?: boolean; payload?: { payload: Dato }[]; unidad: string | null }) {
  if (!active || !payload?.length) return null
  const { p, contexto } = payload[0].payload
  return (
    <div className="globo" role="tooltip">
      <strong>{valorConUnidad(p.v, unidad)}</strong>
      <span>{fechaYHora(p.t * 1000)} h</span>
      {p.min !== undefined && p.max !== undefined && <span>Promedio del día. Mínimo {valorConUnidad(p.min, unidad)}, máximo {valorConUnidad(p.max, unidad)}</span>}
      <span>Contexto: {contextoTexto(p.c)}</span>
      {p.a && <span>Jugando: {p.a}</span>}
      {contexto?.madura && (
        <span>
          Habitual en {contextoTexto(contexto.contexto).toLowerCase()}: {numero(contexto.tipica[0])} a {numero(contexto.tipica[1])}
        </span>
      )}
      {p.f && <span className="globo-fuera">◆ Fuera de lo habitual para {contextoTexto(p.c).toLowerCase()}</span>}
    </div>
  )
}

export function Grafico({ sensor, tick }: { sensor: string; tick: number }) {
  const [rango, setRango] = useState<(typeof RANGOS)[number]['id']>('24h')
  const [contexto, setContexto] = useState<'' | Contexto>('')
  const ruta = `/api/series?sensor=${encodeURIComponent(sensor)}&desde=${rango}${contexto ? `&contexto=${contexto}` : ''}`
  const carga = useApi<Serie>(ruta, tick)

  return (
    <div className="grafico">
      <div className="controles">
        <div className="segmentos" role="group" aria-label="Rango de tiempo">
          {RANGOS.map((r) => (
            <button key={r.id} type="button" aria-pressed={rango === r.id} onClick={() => setRango(r.id)}>
              {r.texto}
            </button>
          ))}
        </div>
        <div className="segmentos" role="group" aria-label="Contexto">
          {CONTEXTOS.map((c) => (
            <button key={c.id} type="button" aria-pressed={contexto === c.id} onClick={() => setContexto(c.id)}>
              {c.texto}
            </button>
          ))}
        </div>
      </div>
      <Contenido carga={carga} hijos={(s) => <Dibujo serie={s} contexto={contexto} rango={rango} />} />
    </div>
  )
}

function Dibujo({ serie, contexto, rango }: { serie: Serie; contexto: '' | Contexto; rango: string }) {
  const { datos, dominio, limites } = useMemo(() => {
    const filas: Dato[] = serie.puntos.map((p) => {
      const b = (p.c ? serie.bandas[p.c] : undefined) ?? (contexto ? serie.bandas[contexto] : undefined) ?? null
      return { t: p.t * 1000, v: p.v, banda: b && b.madura ? b.tipica : null, fuera: p.f ? p.v : null, p, contexto: b }
    })
    const valores = filas.flatMap((d) => [d.v, ...(d.banda ?? [])])
    const bajo = Math.min(...valores)
    const alto = Math.max(...valores)
    const margen = Math.max((alto - bajo) * 0.12, 0.5)
    const unico = contexto ? serie.bandas[contexto] : undefined // con un contexto elegido se dibujan sus límites de aviso
    return {
      datos: filas,
      dominio: [Math.floor(bajo - margen), Math.ceil(alto + margen)] as [number, number],
      limites: unico?.madura ? unico.limite.filter((x): x is number => x !== null) : [],
    }
  }, [serie, contexto])

  if (!datos.length) return <p className="vacio">No hay datos de este sensor en el rango elegido.</p>
  const largo = RANGOS.find((r) => r.id === rango)!.horas
  const formatoX = (ms: number) => (largo <= 24 ? hora(ms) : dia(ms))
  const hayBanda = datos.some((d) => d.banda)
  const b = contexto ? serie.bandas[contexto] : undefined
  const fuera = datos.filter((d) => d.p.f).length

  return (
    <>
      <div className="lienzo" role="img" aria-label={`Gráfico de ${serie.etiqueta}: ${datos.length} puntos, ${fuera} fuera de lo habitual`}>
        <ResponsiveContainer width="100%" height={320}>
          <ComposedChart data={datos} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--borde)" />
            <XAxis dataKey="t" type="number" scale="time" domain={[serie.desde * 1000, serie.hasta * 1000]} tickFormatter={formatoX} tickCount={6} stroke="var(--texto-suave)" fontSize={12} />
            <YAxis domain={dominio} tickFormatter={(v: number) => numero(v, 0)} width={44} stroke="var(--texto-suave)" fontSize={12} />
            <Tooltip content={(props) => <Globo active={props.active} payload={props.payload as unknown as { payload: Dato }[]} unidad={serie.unidad} />} isAnimationActive={false} />
            {hayBanda && <Area dataKey="banda" type="stepAfter" stroke="none" fill="var(--banda)" fillOpacity={0.9} isAnimationActive={false} connectNulls={false} legendType="none" tooltipType="none" />}
            {limites.map((y) => (
              <ReferenceLine key={y} y={y} stroke="var(--aviso)" strokeDasharray="5 4" ifOverflow="extendDomain" />
            ))}
            <Line dataKey="v" type="monotone" stroke="var(--linea)" strokeWidth={1.8} dot={false} activeDot={{ r: 4 }} isAnimationActive={false} legendType="none" />
            <Scatter dataKey="fuera" shape={<Rombo />} isAnimationActive={false} legendType="none" tooltipType="none" />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <ul className="leyenda" aria-label="Referencias del gráfico">
        <li><span className="muestra muestra-linea" aria-hidden="true" /> Valor medido</li>
        {hayBanda && <li><span className="muestra muestra-banda" aria-hidden="true" /> Rango habitual (mediana ± 2 desvíos)</li>}
        {limites.length > 0 && <li><span className="muestra muestra-limite" aria-hidden="true" /> Límite de aviso aprendido</li>}
        <li><span className="muestra muestra-rombo" aria-hidden="true">◆</span> Fuera de lo habitual ({fuera})</li>
      </ul>
      <p className="nota-grafico">
        {datos.length} puntos, {serie.resolucion}.
        {b && (b.madura ? ` En ${contextoTexto(b.contexto).toLowerCase()} lo habitual es de ${numero(b.tipica[0])} a ${numero(b.tipica[1])} (mediana ${numero(b.mediana)}).` : ` Todavía aprendiendo lo normal en ${contextoTexto(b.contexto).toLowerCase()}: ${b.n} de 200 muestras.`)}
        {!hayBanda && !b && ' No hay una banda aprendida todavía para este sensor o para estos contextos.'}
      </p>
    </>
  )
}
