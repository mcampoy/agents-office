// Forma de la foto que arma el servidor (servidor/oficina.py → /api/estado y /api/stream).
// Solo se tipan los campos que usa el piso; el resto viaja igual para las pestañas (fase 4).

export type Estado =
  | 'trabajando'
  | 'esperando'
  | 'error'
  | 'entregando'
  | 'esperando_subagentes'
  | 'terminado'
  | 'ocioso';

export type Animacion = 'lee' | 'escribe' | 'espera' | 'error' | 'idle' | 'se_retira' | 'entrega' | 'espera_subagentes';

export interface Instancia {
  clave: string;
  sesion: string;
  tipo: string;
  principal: boolean;
  general: boolean;
  numero: number;
  etiqueta: string | null;
  etiqueta_historial: string;
  estado: Estado;
  desde: string | null;
  segundos_en_estado: number | null;
  animacion: Animacion;
  modelo: string | null;
  fuente_modelo: string | null;
  effort: string | null;
  herramienta: string | null;
  recurso: string | null;
  documento: string | null;
  espera: { herramienta?: string; recurso?: string; desde?: string | null } | null;
  skills: string[];
  inicio: string | null;
  fin: string | null;
  origen: string | null;
  zona: string;
  sin_zona: boolean;
  rol: string | null;
}

export interface Objeto {
  ts: string;
  instancia: string;
  canal?: string;
  script?: string;
  ruta?: string;
  herramienta?: string;
}

export interface Foto {
  generado: string;
  version: number;
  principal: (Instancia & { aviso_reinicio: string | null }) | null;
  instancias: Instancia[];
  aprobaciones: unknown[];
  objetos: { buzon: Objeto[]; controles: Objeto[]; memoria: Objeto[] };
  resumen_cruces: Record<string, number>;
  avisos: Array<{ sesion: string; texto: string }>;
  vacantes: string[];
  responsable: {
    pendientes: number;
    aprobaciones: number;
    ultimo_prompt: string | null;
    esperas: Array<{ ruta: string; espera: string }>;
  };
  reloj: { proxima: string; ultima: string | null; en_curso: boolean };
  salud: { errores_hook_24h: number; lineas_descartadas: number };
}

export interface Personajes {
  avatar: number;
  asignables: number[];
}

export interface ConfigSprites {
  agentes?: Record<string, { sprite?: number }>;
}
