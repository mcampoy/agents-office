// Lo que el piso sabe del equipo: sale de /api/perfil (perfil.json del perfil activo, ver docs/perfil.md).
// Se carga una vez, antes de dibujar, y después se lee con perfil().

export interface PerfilWeb {
  nombre: string;
  principal: string;
  verificador: string | null;
  responsable: string;
  corrida: { agente?: string; dia_semana?: number; hora?: number } | null;
  piso: {
    /** Zona del layout → nombre visible de la sala. */
    salas: Record<string, string>;
    /** Agente → nombre corto para la etiqueta del piso. */
    nombres_cortos: Record<string, string>;
    /** Patrón de agente (con '*') → accesorio que lleva en el piso ('lupa'). */
    accesorios: Record<string, string>;
    /** Agente → ícono que muestra cuando trabaja fuera del área, y regex de las herramientas que lo activan. */
    trabajo_externo: Record<string, { icono: string; herramientas: string }>;
    /** Agente que se sienta junto al reloj de la corrida programada (los demás le dejan ese lugar). */
    junto_al_reloj: string | null;
    /** Zonas que se ven a oscuras mientras no hay nadie activo en ellas. */
    luces_apagadas?: string[];
  };
}

const POR_DEFECTO: PerfilWeb = {
  nombre: 'Oficina',
  principal: 'principal',
  verificador: null,
  responsable: 'responsable',
  corrida: null,
  piso: { salas: {}, nombres_cortos: {}, accesorios: {}, trabajo_externo: {}, junto_al_reloj: null, luces_apagadas: [] },
};

let actual: PerfilWeb = POR_DEFECTO;

export function fijarPerfil(p: Partial<PerfilWeb> | null): void {
  actual = { ...POR_DEFECTO, ...(p ?? {}), piso: { ...POR_DEFECTO.piso, ...(p?.piso ?? {}) } };
  document.title = actual.nombre;
}

export function perfil(): PerfilWeb {
  return actual;
}

export function coincide(nombre: string, patron: string): boolean {
  if (!patron.includes('*')) return nombre === patron;
  const re = new RegExp('^' + patron.split('*').map((p) => p.replace(/[.+?^${}()|[\]\\]/g, '\\$&')).join('.*') + '$');
  return re.test(nombre);
}

/** Accesorio del agente según el perfil ('lupa' o null). */
export function accesorioDe(tipo: string): string | null {
  const regla = Object.entries(actual.piso.accesorios).find(([patron]) => coincide(tipo, patron));
  return regla ? regla[1] : null;
}

/** Ícono de trabajo externo si el agente está usando una de esas herramientas. */
export function trabajoExterno(tipo: string, herramienta: string | null): string | null {
  const regla = actual.piso.trabajo_externo[tipo];
  if (!regla || !herramienta) return null;
  try {
    return new RegExp(regla.herramientas, 'i').test(herramienta) ? regla.icono : null;
  } catch {
    return null;
  }
}
