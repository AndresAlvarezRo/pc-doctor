import { useApi } from '../api'
import { Aviso, Contenido, Seccion } from '../comunes'
import type { HardwareItem, RespuestaEntorno } from '../tipos'

const nombreHardware = (h: HardwareItem) =>
  h.tipo === 'cpu' ? 'Procesador' : h.tipo === 'gpu' ? 'Placa de video' : h.tipo === 'ram' ? 'Memoria RAM' : h.tipo === 'mother' ? 'Placa madre' : `Disco ${h.dev ?? ''}`.trim()

function descripcionHardware(h: HardwareItem): string {
  if (h.tipo === 'ram') return `${h.total_gb} GB${h.swap_gb ? `, swap ${h.swap_gb} GB` : ', sin swap'}`
  if (h.tipo === 'gpu') return [h.modelo?.replace(/\s*\(rev [0-9a-f]+\)/, ''), h.driver ? `driver ${h.driver}` : null, h.mesa ? `Mesa ${h.mesa.split('~')[0]}` : null].filter(Boolean).join(' · ')
  if (h.tipo === 'cpu') return `${h.modelo}${h.nucleos_fisicos ? ` · ${h.nucleos_fisicos} núcleos, ${h.hilos} hilos` : ''}`
  if (h.tipo === 'mother') return `${h.modelo}${h.bios ? ` · BIOS ${h.bios}` : ''}`
  return `${h.modelo ?? ''}${h.tamano ? ` · ${h.tamano}` : ''}`
}

function ListaCambios({ titulo, c }: { titulo: string; c?: { total: number; muestra: string[] } }) {
  if (!c) return null
  return (
    <div className="cambios">
      <h4>{titulo}: {c.total}</h4>
      {c.muestra.length > 0 && <ul className="lista-simple">{c.muestra.map((m) => <li key={m}>{m}</li>)}</ul>}
      {c.total > c.muestra.length && <p className="ayuda">Y {c.total - c.muestra.length} más.</p>}
    </div>
  )
}

export function Entorno({ tick }: { tick: number }) {
  const carga = useApi<RespuestaEntorno>('/api/entorno?desde=7d', tick)
  return (
    <Seccion id="entorno" titulo="Entorno" ayuda="La identidad del equipo según el último snapshot, y qué cambió en la última semana.">
      <Contenido
        carga={carga}
        hijos={(e) => (
          <>
            {e.perfil.error ? (
              <Aviso>{e.perfil.error}</Aviso>
            ) : (
              <dl className="datos">
                <div><dt>Sistema operativo</dt><dd>{e.perfil.distro} · {e.perfil.escritorio}</dd></div>
                <div><dt>Kernel</dt><dd>{e.perfil.kernel}</dd></div>
                {e.perfil.hardware?.map((h, i) => (
                  <div key={i}><dt>{nombreHardware(h)}</dt><dd>{descripcionHardware(h)}</dd></div>
                ))}
                {e.perfil.paquetes && <div><dt>Paquetes</dt><dd>{Object.entries(e.perfil.paquetes).map(([k, v]) => `${k} ${v}`).join(' · ')}</dd></div>}
                <div><dt>Snapshot</dt><dd>{e.perfil.tomado_en}</dd></div>
              </dl>
            )}
            <h3 className="subtitulo">Cambios de los últimos 7 días</h3>
            {e.cambios.error ? (
              <Aviso>{e.cambios.error}</Aviso>
            ) : e.cambios.mensaje ? (
              <Aviso>{e.cambios.mensaje}</Aviso>
            ) : (
              <>
                <p className="ayuda">Comparación entre el snapshot del {e.cambios.desde_snapshot} y el del {e.cambios.hasta_snapshot}.{e.cambios.kernel ? ` Kernel: ${e.cambios.kernel}.` : ''}</p>
                <div className="cambios-grilla">
                  <ListaCambios titulo="Paquetes agregados" c={e.cambios.agregados} />
                  <ListaCambios titulo="Paquetes quitados" c={e.cambios.quitados} />
                  <ListaCambios titulo="Paquetes actualizados" c={e.cambios.cambiados} />
                </div>
              </>
            )}
          </>
        )}
      />
    </Seccion>
  )
}
