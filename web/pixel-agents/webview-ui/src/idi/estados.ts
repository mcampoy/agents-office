// Texto y color de cada estado. El estado siempre se muestra en texto, no solo en color.
import { perfil } from './perfil.ts';
import type { Estado, Instancia } from './tipos.ts';

export const COLOR_ESTADO: Record<Estado, string> = {
  trabajando: '#4aa3ff',
  esperando: '#ffc233',
  error: '#ff5c5c',
  entregando: '#b98cff',
  esperando_subagentes: '#7fd6e8',
  pensando: '#8fb3e0',
  terminado: '#8fd48a',
  ocioso: '#b4b4c8',
};

export function textoEstado(i: Instancia, subagentesActivos = 0): string {
  switch (i.estado) {
    case 'trabajando':
      return i.animacion === 'lee' ? 'trabajando · lee' : 'trabajando · escribe';
    case 'esperando':
      return 'espera aprobación';
    case 'error':
      return 'error';
    case 'entregando':
      return 'entregando';
    case 'esperando_subagentes':
      return subagentesActivos > 0 ? `espera ${subagentesActivos} subagente${subagentesActivos > 1 ? 's' : ''}` : 'espera subagentes';
    case 'terminado':
      return i.principal ? 'turno terminado' : 'terminado';
    case 'pensando':
      return 'pensando';
    case 'ocioso':
      return 'ocioso';
  }
}

/** Grupo para el resumen de la cabecera: lo que el responsable necesita ver primero. */
export function grupo(e: Estado): 'trabajan' | 'esperan' | 'error' | 'ociosos' {
  if (e === 'esperando') return 'esperan';
  if (e === 'error') return 'error';
  if (e === 'ocioso' || e === 'terminado') return 'ociosos';
  return 'trabajan';
}

export function duracion(seg: number | null | undefined): string {
  if (seg === null || seg === undefined) return '';
  if (seg < 60) return `${seg}s`;
  const m = Math.floor(seg / 60);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}

export function nombre(i: Instancia, totalDelTipo: number): string {
  return totalDelTipo > 1 || i.numero > 1 ? `${i.tipo} #${i.numero}` : i.tipo;
}

/** Nombre corto para la etiqueta del piso (el completo va en la tarjeta). Los cortos salen del perfil. */
export function nombreCorto(i: Instancia, totalDelTipo: number): string {
  const base = perfil().piso.nombres_cortos[i.tipo] ?? i.tipo;
  return totalDelTipo > 1 || i.numero > 1 ? `${base} #${i.numero}` : base;
}

export function modeloCorto(m: string | null): string {
  if (!m) return '?';
  const s = m.toLowerCase();
  if (s.includes('opus')) return 'opus';
  if (s.includes('sonnet')) return 'sonnet';
  if (s.includes('haiku')) return 'haiku';
  if (s.includes('fable')) return 'fable';
  return m.length > 10 ? m.slice(0, 10) : m;
}

/** Insignia de una letra para el piso: O (opus), S (sonnet), H (haiku), F (fable). */
export function insigniaModelo(m: string | null): { letra: string; color: string } {
  const c = modeloCorto(m);
  const tabla: Record<string, { letra: string; color: string }> = {
    opus: { letra: 'O', color: '#c58cff' },
    sonnet: { letra: 'S', color: '#ff9a4a' },
    haiku: { letra: 'H', color: '#6fd08c' },
    fable: { letra: 'F', color: '#ffd84a' },
  };
  return tabla[c] ?? { letra: '?', color: '#9a9aae' };
}

/** Estado abreviado para la etiqueta del piso, donde el ancho es poco. */
export function textoEstadoCorto(i: Instancia, subagentesActivos = 0): string {
  if (i.estado === 'trabajando') return i.animacion === 'lee' ? 'lee' : 'escribe';
  if (i.estado === 'esperando_subagentes') return subagentesActivos > 0 ? `espera ${subagentesActivos} sub.` : 'espera sub.';
  return textoEstado(i, subagentesActivos);
}
