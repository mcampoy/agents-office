// Forma de la foto que arma el servidor (servidor/oficina.py → /api/estado y /api/stream).
// Solo se tipan los campos que usa el piso; el resto viaja igual para las pestañas (fase 4).

export type Estado =
  | 'trabajando'
  | 'esperando'
  | 'error'
  | 'entregando'
  | 'esperando_subagentes'
  | 'pensando'
  | 'terminado'
  | 'ocioso';

export type Animacion = 'lee' | 'escribe' | 'espera' | 'error' | 'idle' | 'se_retira' | 'entrega' | 'espera_subagentes' | 'piensa';

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
  aprobaciones: Aprobacion[];
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
  documentos: Documento[];
  cruces: Cruce[];
  actividad: Actividad[];
  tareas_sesion: TareaSesion[];
  candidatos: Candidato[];
}

export interface Personajes {
  avatar: number;
  asignables: number[];
}

export interface ConfigSprites {
  agentes?: Record<string, { sprite?: number }>;
}

// --- Datos de las pestañas (fase 4) -------------------------------------------------------------

export interface Aprobacion {
  instancia: string;
  herramienta: string | null;
  recurso: string | null;
  desde: string | null;
  modo: string | null;
  aviso?: string;
}

export interface Cruce {
  ts: string;
  instancia: string;
  quien: string;
  informe: string;
  documentos: string[];
  tipo_documento: string;
  ronda: number | null;
  etiqueta: string;
  concluyente: boolean;
}

export interface Documento {
  ruta: string;
  tipo: string;
  etapa: string;
  historial: Array<{ ts: string; instancia: string; agente: string; quien: string; accion: string }>;
  cruces: Cruce[];
  ultima_escritura: string | null;
  pendiente_codex: boolean;
  encabezado: { titulo: string | null; estado: string | null; version: string | null; ultima_revision: string | null } | null;
  pendientes: Array<{ titulo: string }>;
  bloqueado: boolean;
  espera_responsable: string | null;
}

export interface Actividad {
  ts: string;
  instancia: string;
  evento: string;
  herramienta: string | null;
  recurso: string | null;
  quien: string;
}

export interface TareaSesion {
  sesion: string;
  titulo: string | null;
  creada: string | null;
  completada: string | null;
  instancia: string;
}

export interface Candidato {
  lanzamientos: number;
  tipos: string[];
  palabras: string[];
  descripciones: string[];
  ultimo: string;
}

export interface Bloques {
  ruta: string | null;
  entradas: Array<{ fecha: string | null; titulo: string; campos: Record<string, string>; texto: string; rutas: string[] }>;
  crudo?: string;
  sin_leer?: boolean;
}

export interface Equipo {
  pendientes: Bloques;
  fricciones: Bloques;
  decisiones: Bloques;
  remember: Array<{ ruta: string; entradas: Array<{ titulo: string; texto: string }>; crudo?: string }>;
  status: Array<{ ruta: string; fecha: string | null; tipo: string; variante: string | null; titulo: string | null }>;
  catalogo: {
    agentes: Array<{
      nombre: string;
      archivo: string;
      descripcion: string | null;
      model: string | null;
      effort: string | null;
      tools: string[] | null;
      zona: string;
      sin_zona: boolean;
      vacante: boolean;
    }>;
    skills: Array<{ nombre: string; descripcion: string | null; archivo: string }>;
  };
}
