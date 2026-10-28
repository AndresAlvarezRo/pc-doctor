import { IconoActualizar, IconoAviso, IconoCritico, IconoJuego, IconoNormal } from '../iconos'
import { Aviso } from '../comunes'
import { contextoTexto, hora } from '../formato'
import type { Carga } from '../api'
import type { EstadoGeneral, NoDisponible } from '../tipos'

interface Props {
  carga: Carga<EstadoGeneral | NoDisponible>
  alActualizar: () => void
}

export function Encabezado({ carga, alActualizar }: Props) {
  const e = carga.datos && !('disponible' in carga.datos) ? carga.datos : null
  const equipo = e?.equipo
  return (
    <header className="encabezado">
      <div className="encabezado-fila">
        <div>
          <h1>pc-doctor</h1>
          {equipo && (
            <p className="equipo">
              {[equipo.cpu, equipo.gpu, equipo.so].filter(Boolean).join(' · ')}
              {equipo.ram_gb ? ` · ${equipo.ram_gb} GB de RAM` : ''}
            </p>
          )}
        </div>
        <div className="actualizacion" aria-live="polite">
          <span>{carga.actualizado ? `Actualizado a las ${hora(carga.actualizado)}` : 'Sin datos todavía'}</span>
          <button type="button" className="boton" onClick={alActualizar}>
            <IconoActualizar /> Actualizar
          </button>
        </div>
      </div>
      {e && (
        <div className="resumen">
          <span className="chip" title="Con este contexto se comparan los valores contra lo normal aprendido">
            {e.contexto === 'juego' ? <IconoJuego /> : null}
            {e.actividad.length ? `Jugando: ${e.actividad.map((a) => a.detalle).join(', ')}` : `Contexto: ${contextoTexto(e.contexto).toLowerCase()}`}
          </span>
          {e.alertas.total === 0 ? (
            <span className="chip chip-normal"><IconoNormal /> Sin alertas activas</span>
          ) : (
            <>
              {e.alertas.critico > 0 && (
                <a className="chip chip-critico" href="#alertas"><IconoCritico /> {e.alertas.critico} {e.alertas.critico === 1 ? 'crítica' : 'críticas'}</a>
              )}
              {e.alertas.aviso > 0 && (
                <a className="chip chip-aviso" href="#alertas"><IconoAviso /> {e.alertas.aviso} {e.alertas.aviso === 1 ? 'aviso' : 'avisos'}</a>
              )}
            </>
          )}
        </div>
      )}
      {carga.error && <Aviso tipo="error">Sin conexión con pc-doctor ({carga.error}). Se muestran los últimos datos conocidos.</Aviso>}
    </header>
  )
}
