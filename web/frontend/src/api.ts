import { useEffect, useRef, useState } from 'react'
import type { NoDisponible } from './tipos'

export class ErrorApi extends Error {
  constructor(public estado: number, mensaje: string) {
    super(mensaje)
  }
}

export async function pedir<T>(ruta: string, senal?: AbortSignal): Promise<T> {
  const r = await fetch(ruta, { signal: senal, headers: { Accept: 'application/json' } })
  if (!r.ok) {
    let mensaje = `Error ${r.status}`
    try {
      mensaje = (await r.json()).error ?? mensaje
    } catch {
      /* sin cuerpo JSON */
    }
    throw new ErrorApi(r.status, mensaje)
  }
  return r.json() as Promise<T>
}

export const esNoDisponible = (x: unknown): x is NoDisponible =>
  typeof x === 'object' && x !== null && (x as NoDisponible).disponible === false

export interface Carga<T> {
  datos: T | null
  error: string | null
  cargando: boolean
  /** Momento (ms) del último pedido exitoso. */
  actualizado: number | null
}

/**
 * Pide `ruta` al montar, cuando cambia y cada vez que cambia `tick` (el reloj de 60 s de la página).
 * Si un pedido falla conserva los últimos datos y reporta el error, para que la pantalla no se vacíe.
 */
export function useApi<T>(ruta: string | null, tick = 0): Carga<T> {
  const [estado, setEstado] = useState<Carga<T>>({ datos: null, error: null, cargando: ruta !== null, actualizado: null })
  const rutaAnterior = useRef<string | null>(null)

  useEffect(() => {
    if (ruta === null) {
      setEstado({ datos: null, error: null, cargando: false, actualizado: null })
      return
    }
    const control = new AbortController()
    const cambioDeRuta = rutaAnterior.current !== ruta
    rutaAnterior.current = ruta
    setEstado((e) => ({ datos: cambioDeRuta ? null : e.datos, error: null, cargando: cambioDeRuta || e.datos === null, actualizado: e.actualizado }))
    pedir<T>(ruta, control.signal)
      .then((datos) => setEstado({ datos, error: null, cargando: false, actualizado: Date.now() }))
      .catch((e) => {
        if (control.signal.aborted) return
        // "Failed to fetch" es el mensaje del navegador cuando el servidor no responde
        const mensaje = e instanceof TypeError ? 'el servidor no responde' : e instanceof Error ? e.message : String(e)
        setEstado((anterior) => ({ ...anterior, error: mensaje, cargando: false }))
      })
    return () => control.abort()
  }, [ruta, tick])

  return estado
}
