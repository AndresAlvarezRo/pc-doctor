import { createContext, useContext, type ReactNode } from 'react'
import { esNoDisponible } from './api'
import type { Carga } from './api'
import { estadoTexto } from './formato'
import { IconoAviso, IconoCritico, IconoInfo, IconoNormal } from './iconos'
import type { Estado, NoDisponible } from './tipos'

/** Estado de un sensor o componente: color, ícono y texto juntos. */
export function InsigniaEstado({ estado }: { estado: Estado }) {
  const Icono = estado === 'critico' ? IconoCritico : estado === 'aviso' ? IconoAviso : IconoNormal
  return (
    <span className={`insignia insignia-${estado}`}>
      <Icono />
      {estadoTexto(estado)}
    </span>
  )
}

/** Severidad de los hallazgos de seguridad: alta se muestra como crítico, media como aviso y baja como informativa. */
export function InsigniaSeveridad({ severidad }: { severidad: 'alta' | 'media' | 'baja' | 'aviso' | 'critico' }) {
  const nivel = severidad === 'alta' || severidad === 'critico' ? 'critico' : severidad === 'media' || severidad === 'aviso' ? 'aviso' : 'info'
  const Icono = nivel === 'critico' ? IconoCritico : nivel === 'aviso' ? IconoAviso : IconoInfo
  const texto = { alta: 'Alta', media: 'Media', baja: 'Baja', aviso: 'Aviso', critico: 'Crítico' }[severidad]
  return (
    <span className={`insignia insignia-${nivel}`}>
      <Icono />
      {texto}
    </span>
  )
}

/** Verdadero cuando falla la conexión con el servidor: el encabezado lo avisa una sola vez y las secciones no lo repiten. */
export const SinConexion = createContext(false)

export function Seccion({ id, titulo, ayuda, children }: { id: string; titulo: string; ayuda?: string; children: ReactNode }) {
  return (
    <section className="seccion" id={id} aria-labelledby={`${id}-titulo`}>
      <header className="seccion-cabecera">
        <h2 id={`${id}-titulo`}>{titulo}</h2>
        {ayuda && <p className="ayuda">{ayuda}</p>}
      </header>
      {children}
    </section>
  )
}

export function Aviso({ tipo = 'info', children }: { tipo?: 'info' | 'aviso' | 'error'; children: ReactNode }) {
  const Icono = tipo === 'error' ? IconoCritico : tipo === 'aviso' ? IconoAviso : IconoInfo
  return (
    <p className={`aviso aviso-${tipo}`} role={tipo === 'error' ? 'alert' : undefined}>
      <Icono />
      <span>{children}</span>
    </p>
  )
}

/**
 * Muestra una carga con sus tres casos comunes: cargando, error y "no disponible todavía".
 * `hijos` recibe los datos ya validados.
 */
export function Contenido<T>({ carga, hijos }: { carga: Carga<T | NoDisponible>; hijos: (d: T) => ReactNode }) {
  const sinConexion = useContext(SinConexion)
  if (carga.datos === null) {
    if (carga.error) return <Aviso tipo="error">No se pudo cargar esta sección: {carga.error}</Aviso>
    return <p className="cargando" role="status">Cargando…</p>
  }
  if (esNoDisponible(carga.datos)) return <Aviso>{carga.datos.mensaje}</Aviso>
  return (
    <>
      {carga.error && !sinConexion && <Aviso tipo="aviso">No se pudo actualizar ({carga.error}). Se muestran los últimos datos.</Aviso>}
      {hijos(carga.datos as T)}
    </>
  )
}
