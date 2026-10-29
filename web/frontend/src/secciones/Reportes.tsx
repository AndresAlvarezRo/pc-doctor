import { useEffect, useState } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { esNoDisponible, useApi } from '../api'
import { Aviso, Contenido, Seccion } from '../comunes'
import { IconoAviso, IconoNormal } from '../iconos'
import { diaCompleto } from '../formato'
import type { Reporte, ResumenReporte } from '../tipos'

// Los reportes los redacta un modelo a partir de datos del equipo: se renderizan como texto, sin permitir HTML crudo
// (react-markdown no lo interpreta) y con los enlaces abiertos en otra pestaña sin pasar datos de referencia.
const componentes = {
  a: ({ href, children }: { href?: string; children?: React.ReactNode }) => (
    <a href={href} target="_blank" rel="noopener noreferrer nofollow">{children}</a>
  ),
}

function Insignia({ r }: { r: ResumenReporte }) {
  return r.modo === 'claude' ? (
    <span className="insignia insignia-normal"><IconoNormal /> Redactado por Claude</span>
  ) : (
    <span className="insignia insignia-aviso" title={r.motivo ?? undefined}><IconoAviso /> Sin redactar (plan B)</span>
  )
}

export function Reportes({ tick }: { tick: number }) {
  const lista = useApi<{ reportes: ResumenReporte[] }>('/api/reportes?n=30', tick)
  const [fecha, setFecha] = useState<string | null>(null)
  const primero = lista.datos && !esNoDisponible(lista.datos) ? lista.datos.reportes[0]?.fecha ?? null : null
  useEffect(() => {
    if (fecha === null && primero) setFecha(primero)
  }, [fecha, primero])
  const detalle = useApi<Reporte>(fecha ? `/api/reportes/${encodeURIComponent(fecha)}` : null, 0)

  return (
    <Seccion id="reportes" titulo="Reportes" ayuda="Un reporte de salud por semana, los domingos a las 20:00. Si Claude no está disponible, se genera uno sin redactar con los mismos datos.">
      <Contenido
        carga={lista}
        hijos={(l) =>
          l.reportes.length === 0 ? (
            <Aviso>Todavía no se generó ningún reporte. El primero sale el próximo domingo a las 20:00.</Aviso>
          ) : (
            <div className="reportes">
              <ul className="reportes-lista" aria-label="Reportes anteriores">
                {l.reportes.map((r) => (
                  <li key={r.fecha}>
                    <button type="button" className={`reporte-item${r.fecha === fecha ? ' reporte-elegido' : ''}`} aria-pressed={r.fecha === fecha} onClick={() => setFecha(r.fecha)}>
                      <span className="reporte-fecha">{diaCompleto(r.ts * 1000)}</span>
                      <Insignia r={r} />
                      {r.resumen && <span className="reporte-resumen">{r.resumen}</span>}
                    </button>
                  </li>
                ))}
              </ul>
              <article className="reporte-contenido">
                {detalle.datos ? (
                  <>
                    {detalle.datos.modo === 'determinista' && detalle.datos.motivo && <Aviso tipo="aviso">Este reporte salió sin redactar. Motivo: {detalle.datos.motivo}.</Aviso>}
                    <Markdown remarkPlugins={[remarkGfm]} components={componentes}>{detalle.datos.contenido}</Markdown>
                  </>
                ) : detalle.error ? (
                  <Aviso tipo="error">No se pudo abrir el reporte: {detalle.error}</Aviso>
                ) : (
                  <p className="cargando" role="status">Cargando…</p>
                )}
              </article>
            </div>
          )
        }
      />
    </Seccion>
  )
}
