// Formatos de números, fechas y textos para la interfaz (español rioplatense).

const num = (d: number) => new Intl.NumberFormat('es-AR', { minimumFractionDigits: d, maximumFractionDigits: d })
const decimales: Record<string, number> = { '°C': 1, '%': 1, W: 1, 'MB/s': 1, RPM: 0, mV: 0, h: 0, n: 0, carga: 2 }

/** Valor con su unidad: "71,9 °C", "1.548 RPM". Los booleanos se muestran como texto. */
export function valorConUnidad(v: number, unidad: string | null): string {
  if (unidad === 'bool') return v ? 'Sí' : 'No'
  const u = unidad ?? ''
  const texto = num(decimales[u] ?? 1).format(v)
  return `${texto} ${u}`.trim()
}

export const numero = (v: number, d = 1) => num(d).format(v)

const horaCorta = new Intl.DateTimeFormat('es-AR', { hour: '2-digit', minute: '2-digit', hour12: false })
const diaCorto = new Intl.DateTimeFormat('es-AR', { day: '2-digit', month: '2-digit' })
const diaLargo = new Intl.DateTimeFormat('es-AR', { weekday: 'long', day: 'numeric', month: 'long' })
const fechaHora = new Intl.DateTimeFormat('es-AR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })

export const hora = (ms: number) => horaCorta.format(ms)
export const dia = (ms: number) => diaCorto.format(ms)
export const fechaYHora = (ms: number) => fechaHora.format(ms)
/** "miércoles, 28 de octubre" con la primera letra en mayúscula (es el inicio de la frase). */
export const diaCompleto = (ms: number) => {
  const t = diaLargo.format(ms)
  return t.charAt(0).toUpperCase() + t.slice(1)
}
export const claveDia = (ms: number) => new Date(ms).toLocaleDateString('sv-SE')

/** "hace 5 min", "hace 3 h", "hace 2 días". */
export function hace(ts: number, ahora = Date.now() / 1000): string {
  const s = Math.max(0, ahora - ts)
  if (s < 90) return 'hace un momento'
  if (s < 3600) return `hace ${Math.round(s / 60)} min`
  if (s < 86400) return `hace ${Math.round(s / 3600)} h`
  const d = Math.round(s / 86400)
  return `hace ${d} ${d === 1 ? 'día' : 'días'}`
}

export function duracion(min: number): string {
  if (min < 60) return `${min} min`
  const h = Math.floor(min / 60)
  const m = min % 60
  return m ? `${h} h ${m} min` : `${h} h`
}

export const contextoTexto = (c: string | null | undefined) =>
  c === 'reposo' ? 'Reposo' : c === 'carga' ? 'Carga' : c === 'juego' ? 'Juego' : 'Sin clasificar'

export const estadoTexto = (e: string) => (e === 'critico' ? 'Crítico' : e === 'aviso' ? 'Aviso' : 'Normal')
