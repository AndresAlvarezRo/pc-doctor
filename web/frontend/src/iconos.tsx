import type { ReactNode } from 'react'

// Íconos en SVG, con el color del texto que los rodea. Decorativos: el significado siempre va también en texto.

const base = { width: 16, height: 16, viewBox: '0 0 16 16', fill: 'none', stroke: 'currentColor', strokeWidth: 1.6, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true } as const
const Icono = ({ children, tam = 16 }: { children: ReactNode; tam?: number }) => (
  <svg {...base} width={tam} height={tam}>
    {children}
  </svg>
)

export const IconoNormal = ({ tam }: { tam?: number }) => (
  <Icono tam={tam}>
    <circle cx="8" cy="8" r="6.2" />
    <path d="M5.2 8.2 7.1 10l3.7-4" />
  </Icono>
)
export const IconoAviso = ({ tam }: { tam?: number }) => (
  <Icono tam={tam}>
    <path d="M8 2 14.2 13H1.8z" />
    <path d="M8 6.4v3.2M8 11.4v.1" />
  </Icono>
)
export const IconoCritico = ({ tam }: { tam?: number }) => (
  <Icono tam={tam}>
    <path d="M5.2 1.8h5.6l3.4 3.4v5.6l-3.4 3.4H5.2L1.8 10.8V5.2z" />
    <path d="m5.8 5.8 4.4 4.4M10.2 5.8l-4.4 4.4" />
  </Icono>
)
export const IconoAprendiendo = ({ tam }: { tam?: number }) => (
  <Icono tam={tam}>
    <path d="M4 1.8h8M4 14.2h8M4.6 1.8c0 3 3.4 3.6 3.4 6.2S4.6 11.2 4.6 14.2M11.4 1.8c0 3-3.4 3.6-3.4 6.2s3.4 3.2 3.4 6.2" />
  </Icono>
)
export const IconoInfo = ({ tam }: { tam?: number }) => (
  <Icono tam={tam}>
    <circle cx="8" cy="8" r="6.2" />
    <path d="M8 7.2v4M8 4.9v.1" />
  </Icono>
)
export const IconoActualizar = ({ tam }: { tam?: number }) => (
  <Icono tam={tam}>
    <path d="M13.4 8A5.4 5.4 0 1 1 11.8 4.2M13.6 2.2v2.8h-2.8" />
  </Icono>
)
export const IconoVolver = ({ tam }: { tam?: number }) => (
  <Icono tam={tam}>
    <path d="M9.6 3.2 4.8 8l4.8 4.8" />
  </Icono>
)
export const IconoRelacion = ({ tam }: { tam?: number }) => (
  <Icono tam={tam}>
    <path d="M3.6 14V2.4M3.6 3h8.2l-1.8 2.8 1.8 2.8H3.6" />
  </Icono>
)
export const IconoCerrar = ({ tam }: { tam?: number }) => (
  <Icono tam={tam}>
    <path d="m4 4 8 8M12 4l-8 8" />
  </Icono>
)
export const IconoJuego = ({ tam }: { tam?: number }) => (
  <Icono tam={tam}>
    <rect x="1.6" y="4.6" width="12.8" height="6.8" rx="3.2" />
    <path d="M5 6.6v2.8M3.6 8h2.8M10.6 7.2v.1M12 8.8v.1" />
  </Icono>
)
