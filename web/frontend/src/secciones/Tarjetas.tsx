import { InsigniaEstado } from '../comunes'
import { Contenido } from '../comunes'
import { IconoAprendiendo, IconoAviso, IconoNormal } from '../iconos'
import { contextoTexto, valorConUnidad } from '../formato'
import type { Carga } from '../api'
import type { EstadoGeneral, NoDisponible, Tarjeta } from '../tipos'

function LineaBase({ t, contexto }: { t: Tarjeta; contexto: string | null }) {
  const c = contextoTexto(contexto).toLowerCase()
  if (t.segun_linea_base === 'dentro') return <span className="base base-dentro"><IconoNormal /> Dentro de lo habitual en {c}</span>
  if (t.segun_linea_base === 'fuera') return <span className="base base-fuera"><IconoAviso /> Fuera de lo habitual en {c}</span>
  if (t.segun_linea_base === 'aprendiendo') return <span className="base"><IconoAprendiendo /> Aprendiendo lo normal en {c}</span>
  return <span className="base base-nada">Sin referencia aprendida</span>
}

export function Tarjetas({ carga, alAbrir }: { carga: Carga<EstadoGeneral | NoDisponible>; alAbrir: (t: Tarjeta) => void }) {
  return (
    <Contenido
      carga={carga}
      hijos={(e) => (
        <>
          {e.no_disponible.length > 0 && (
            <ul className="faltantes">
              {e.no_disponible.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          )}
          <ul className="tarjetas">
            {e.tarjetas.map((t) => (
              <li key={`${t.tipo}:${t.id}`}>
                <button type="button" className={`tarjeta tarjeta-${t.estado}`} onClick={() => alAbrir(t)} aria-label={`${t.titulo}: ver detalle`}>
                  <span className="tarjeta-titulo">{t.titulo}</span>
                  {t.principal ? (
                    <>
                      <span className="tarjeta-valor">{valorConUnidad(t.principal.valor, t.principal.unidad)}</span>
                      <span className="tarjeta-etiqueta">{t.principal.etiqueta}</span>
                    </>
                  ) : (
                    <span className="tarjeta-etiqueta">Sin lecturas</span>
                  )}
                  <span className="tarjeta-pie">
                    <InsigniaEstado estado={t.estado} />
                    <LineaBase t={t} contexto={e.contexto} />
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    />
  )
}
