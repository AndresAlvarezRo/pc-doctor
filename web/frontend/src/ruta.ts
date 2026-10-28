import { useCallback, useEffect, useState } from 'react'

// Enrutado mínimo con la API de historial: /, /componente/:tipo?id=&sensor=, /alerta/:id y /hallazgo/:id.
// El servidor devuelve la misma página para esas rutas, así que los enlaces directos funcionan.

export type Ruta =
  | { vista: 'inicio' }
  | { vista: 'componente'; tipo: string; id: string | null; sensor: string | null }
  | { vista: 'alerta'; id: string }
  | { vista: 'hallazgo'; id: string }

export function leerRuta(): Ruta {
  const partes = window.location.pathname.split('/').filter(Boolean)
  const q = new URLSearchParams(window.location.search)
  if (partes[0] === 'componente' && partes[1]) return { vista: 'componente', tipo: partes[1], id: q.get('id'), sensor: q.get('sensor') }
  if (partes[0] === 'alerta' && partes[1]) return { vista: 'alerta', id: partes[1] }
  if (partes[0] === 'hallazgo' && partes[1]) return { vista: 'hallazgo', id: partes[1] }
  return { vista: 'inicio' }
}

export function useRuta(): [Ruta, (destino: string) => void] {
  const [ruta, setRuta] = useState<Ruta>(leerRuta)
  useEffect(() => {
    const alVolver = () => setRuta(leerRuta())
    window.addEventListener('popstate', alVolver)
    return () => window.removeEventListener('popstate', alVolver)
  }, [])
  const ir = useCallback((destino: string) => {
    window.history.pushState(null, '', destino)
    setRuta(leerRuta())
    window.scrollTo({ top: 0 })
  }, [])
  return [ruta, ir]
}
