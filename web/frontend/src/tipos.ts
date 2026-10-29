// Tipos de las respuestas de la API (web/api.py). Solo lo que usa la interfaz.

export type Estado = 'normal' | 'aviso' | 'critico'
export type SegunLineaBase = 'dentro' | 'fuera' | 'aprendiendo' | 'sin_referencia'
export type Contexto = 'reposo' | 'carga' | 'juego'

/** Una sección cuya fuente de datos todavía no existe responde así en vez de fallar. */
export interface NoDisponible {
  disponible: false
  mensaje: string
}

export interface Banda {
  contexto: Contexto
  n: number
  madura: boolean
  mediana: number
  escala: number
  p95: number
  p99: number
  tipica: [number, number]
  limite: [number | null, number | null]
}

export interface Principal {
  nombre: string
  etiqueta: string
  valor: number
  unidad: string
  dentro_de_banda: boolean | null
  referencia: 'aprendida' | 'aprendiendo' | 'fija' | 'ninguna'
}

export interface Tarjeta {
  tipo: string
  id: string
  titulo: string
  estado: Estado
  principal: Principal | null
  aprendiendo: boolean
  sensores: number
  segun_linea_base: SegunLineaBase
}

export interface EstadoGeneral {
  hora: number
  contexto: Contexto | null
  actividad: { tipo: string; detalle: string; desde: number }[]
  equipo: { cpu?: string; gpu?: string; ram_gb?: number; placa?: string; so?: string; kernel?: string; escritorio?: string }
  alertas: { critico: number; aviso: number; total: number }
  fuera_de_lo_normal: { severidad: Estado; mensaje: string; categoria?: string; nombre?: string }[]
  tarjetas: Tarjeta[]
  no_disponible: string[]
  aprendizaje: { sensores_con_base: number; maduros: number; minimo_muestras: number; dias_registrados: number; estado: string }
}

export interface Sensor {
  nombre: string
  etiqueta: string
  valor: number
  unidad: string
  estado: Estado
  mensaje: string | null
  referencia: 'aprendida' | 'aprendiendo' | 'fija' | 'ninguna'
  dentro_de_banda: boolean | null
  banda: Banda | null
  conector_vacio?: boolean
  giro?: 'gira' | 'parado' | 'vacio'
}

export interface Componente {
  tipo: string
  id: string
  titulo: string
  estado: Estado
  principal: Principal | null
  aprendiendo: boolean
  sensores: Sensor[]
}

export interface RespuestaComponentes {
  tipo: string
  titulo: string
  contexto: Contexto | null
  componentes: Componente[]
}

export interface Punto {
  t: number
  v: number
  min?: number
  max?: number
  c: Contexto | null
  a: string | null
  f: boolean
}

export interface Serie {
  sensor: string
  etiqueta: string
  unidad: string | null
  desde: number
  hasta: number
  contexto: Contexto | null
  resolucion: string
  puntos: Punto[]
  bandas: Partial<Record<Contexto, Banda>>
  n_diarios: number
}

export interface Alerta {
  id: number
  clave: string
  categoria: string | null
  nombre: string | null
  severidad: 'aviso' | 'critico'
  mensaje: string
  valor: number | null
  desde: number
  ultima_vez: number
  resuelta_en: number | null
  veces: number
  activa: number
  estado: 'activa' | 'resuelta'
  relacion: string | null
  /** Hecho que el usuario declaró como conocido y cubre esta alerta (no se avisa de nuevo mientras no empeore). */
  hecho_conocido: HechoAlerta | null
}

export interface HechoAlerta {
  id: number
  texto: string
  aplica_a: string | null
  vence: string | null
}

export interface HechoConocido extends HechoAlerta {
  creado: string
}

export interface RespuestaHechos {
  activos: HechoConocido[]
  para_revisar: HechoConocido[]
}

export interface EntradaChangelog {
  id: number
  fecha: string
  tipo: 'error' | 'solucion' | 'cambio' | 'observacion'
  componente: string
  titulo: string | null
  detalle: string
  estado: 'abierto' | 'resuelto'
  resuelto_en: string | null
}

export interface RespuestaChangelog {
  total: number
  abiertos: number
  entradas: EntradaChangelog[]
}

export interface Hallazgo {
  id: number
  severidad: 'alta' | 'media' | 'baja'
  categoria: string
  regla: string
  proceso: string | null
  detalle: string
  estado: 'nuevo' | 'revisado' | 'falso_positivo'
  veces: number
  primera_vez: number
  ultima_vez: number
  reputacion: { veredicto: string; fuente: string | null; detalle: string | null } | null
}

export interface Causa {
  puntaje: number
  relevancia: 'alta' | 'media' | 'baja'
  cuando: string
  tipo: string
  que: string
}

export interface Correlacion {
  alerta: { tipo: string; categoria?: string; mensaje?: string; nombre?: string; momento: string }
  posibles_causas: Causa[]
  otros_candidatos: number
  aviso: string
}

export interface ElementoLinea {
  ts: number
  fin: number | null
  tipo: string
  titulo: string
  ref: string | null
}

export interface LineaDeTiempo {
  desde: string
  hasta: string
  total: number
  items: ElementoLinea[]
  nota?: string
}

export interface ResumenReporte {
  fecha: string
  ts: number
  modo: 'claude' | 'determinista'
  motivo: string | null
  duracion_s: number | null
  resumen: string | null
}

export interface Reporte extends ResumenReporte {
  contenido: string
}

export interface SesionJuego {
  id: number
  tipo: string
  detalle: string
  inicio: number
  fin: number
  duracion_min: number
  en_curso: boolean
  origen: string
  cpu_max_c: number | null
  gpu_max_c: number | null
}

export interface RespuestaSesiones {
  sesiones: SesionJuego[]
  por_juego: Record<string, { sesiones: number; minutos: number; cpu_max_c: number | null; gpu_max_c: number | null }>
}

export interface SensorAprendizaje {
  sensor: string
  contexto: Contexto
  muestras: number
  minimo: number
  falta: number
  madura: boolean
  ritmo_por_dia: number
  dias_estimados: number | null
  depende_del_uso: boolean
}

export interface RespuestaLimitaciones {
  no_disponible: string[]
  fijas: { tema: string; que: string; por_que: string }[]
  aprendizaje: {
    resumen: EstadoGeneral['aprendizaje']
    por_contexto: Partial<Record<Contexto, { sensores: number; maduros: number }>>
    sensores: SensorAprendizaje[]
  }
}

export interface HardwareItem {
  tipo: string
  marca?: string
  modelo?: string
  dev?: string
  tamano?: string
  total_gb?: number
  swap_gb?: number
  bios?: string
  nucleos_fisicos?: number
  hilos?: number
  driver?: string
  version_driver?: string
  mesa?: string
}

export interface RespuestaEntorno {
  perfil: {
    tomado_en?: string
    distro?: string
    kernel?: string
    escritorio?: string
    hardware?: HardwareItem[]
    paquetes?: Record<string, number>
    error?: string
  }
  cambios: {
    desde_snapshot?: string
    hasta_snapshot?: string
    agregados?: { total: number; muestra: string[] }
    quitados?: { total: number; muestra: string[] }
    cambiados?: { total: number; muestra: string[] }
    kernel?: string
    mensaje?: string
    error?: string
  }
}

export interface ResumenPlan {
  id: number
  diagnostico_id: number
  ts: number
  estado: 'propuesto' | 'aprobado' | 'rechazado' | 'aplicado' | 'verificado' | 'fallido' | 'escalado'
  firma: string
  componente: string | null
  disparador: string
  modo: 'modelo' | 'sin_redactar' | null
  confianza: 'baja' | 'media' | 'alta' | null
  acciones: string[]
  pasos_manuales_n: number
  resultado: string | null
  corridas: number
  aplicado_en: number | null
}

export interface AccionPlan {
  accion: string
  parametros: Record<string, string | number>
  porque: string
  simulacion: string
}

export interface EjecucionPlan {
  id: number
  accion: string
  parametros: Record<string, string | number>
  estado: 'aplicada' | 'fallida' | 'rechazada'
  resumen: string | null
  reversible: boolean
  deshecha_en: number | null
}

export interface DetallePlan extends Omit<ResumenPlan, 'acciones'> {
  hipotesis: string | null
  evidencia: { referencia: string; dato: string }[]
  sospechoso: string[]
  acciones: AccionPlan[]
  pasos_manuales: string[]
  como_verificar: string | null
  descartes: string[]
  motivo: string | null
  duracion_s: number | null
  ejecuciones: EjecucionPlan[]
}
