import { useApi } from '../api'
import { Aviso, Contenido, Seccion } from '../comunes'
import { IconoAviso, IconoInfo, IconoNormal } from '../iconos'
import type { EntradaChangelog, HechoConocido, RespuestaChangelog, RespuestaHechos } from '../tipos'

const TIPOS: Record<EntradaChangelog['tipo'], string> = { error: 'Error', solucion: 'Solución', cambio: 'Cambio', observacion: 'Observación' }

function FilaHecho({ h, vencido }: { h: HechoConocido; vencido: boolean }) {
  return (
    <li className={`fila ${vencido ? 'fila-aviso' : 'fila-info'}`}>
      <div className="fila-cabecera">
        <span className={`insignia insignia-${vencido ? 'aviso' : 'info'}`}>
          {vencido ? <IconoAviso /> : <IconoInfo />}
          {vencido ? 'Para revisar' : 'Vigente'}
        </span>
        <span className="fila-estado">#{h.id}</span>
      </div>
      <p className="fila-mensaje">{h.texto}</p>
      <p className="fila-meta">
        {h.aplica_a ? `Aplica a: ${h.aplica_a}` : 'Sin un sensor o disco en particular'} · Declarado el {h.creado}
        {h.vence ? ` · ${vencido ? 'Venció' : 'Se revisa'} el ${h.vence}` : ' · Sin fecha de revisión'}
      </p>
    </li>
  )
}

export function HechosConocidos({ tick }: { tick: number }) {
  const carga = useApi<RespuestaHechos>('/api/hechos', tick)
  return (
    <Seccion
      id="hechos-conocidos"
      titulo="Hechos conocidos"
      ayuda="Lo que declaraste como sabido: no se vuelve a avisar ni a recomendar mientras no empeore. Por ahora se declaran desde la conversación con Claude."
    >
      <Contenido
        carga={carga}
        hijos={(r) => (
          <>
            {r.activos.length + r.para_revisar.length === 0 && <Aviso>Todavía no declaraste ningún hecho conocido.</Aviso>}
            {r.para_revisar.length > 0 && (
              <>
                <h3 className="subtitulo">Para revisar ({r.para_revisar.length})</h3>
                <p className="ayuda">Su fecha de revisión ya pasó: dejaron de silenciar las alertas.</p>
                <ul className="filas">{r.para_revisar.map((h) => <FilaHecho key={h.id} h={h} vencido />)}</ul>
              </>
            )}
            {r.activos.length > 0 && (
              <>
                <h3 className="subtitulo">Vigentes ({r.activos.length})</h3>
                <ul className="filas">{r.activos.map((h) => <FilaHecho key={h.id} h={h} vencido={false} />)}</ul>
              </>
            )}
          </>
        )}
      />
    </Seccion>
  )
}

function FilaChangelog({ e }: { e: EntradaChangelog }) {
  const abierto = e.estado === 'abierto'
  return (
    <li className={`fila ${abierto ? 'fila-aviso' : 'fila-resuelta'}`}>
      <div className="fila-cabecera">
        <span className={`insignia insignia-${abierto ? 'aviso' : 'normal'}`}>
          {abierto ? <IconoAviso /> : <IconoNormal />}
          {abierto ? 'Abierto' : 'Resuelto'}
        </span>
        <span className="fila-estado">{TIPOS[e.tipo]} · {e.componente}</span>
      </div>
      <p className="fila-mensaje">{e.titulo ?? e.detalle.split('\n')[0]}</p>
      <p className="fila-meta">{e.fecha}{e.resuelto_en ? ` · Resuelto el ${e.resuelto_en}` : ''}</p>
      <details>
        <summary>Ver el detalle</summary>
        <p className="detalle-texto">{e.detalle}</p>
      </details>
    </li>
  )
}

export function Changelog({ tick }: { tick: number }) {
  const carga = useApi<RespuestaChangelog>('/api/changelog?n=100', tick)
  return (
    <Seccion id="changelog" titulo="Changelog" ayuda="La historia de la PC: errores, soluciones y cambios. Lo abierto aparece primero.">
      <Contenido
        carga={carga}
        hijos={(r) =>
          r.entradas.length === 0 ? (
            <Aviso>El changelog todavía no tiene entradas en la base.</Aviso>
          ) : (
            <>
              <p className="ayuda">{r.abiertos} {r.abiertos === 1 ? 'entrada abierta' : 'entradas abiertas'}.</p>
              <ul className="filas">{r.entradas.map((e) => <FilaChangelog key={e.id} e={e} />)}</ul>
            </>
          )
        }
      />
    </Seccion>
  )
}
