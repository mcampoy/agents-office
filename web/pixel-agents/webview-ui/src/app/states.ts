// Text and color of each state. The state is always shown as text, not only as color.
// The texts are the UI, so they are Spanish.
import { profile } from './profile.ts';
import type { Instance, State } from './types.ts';

export const STATE_COLOR: Record<State, string> = {
  working: '#4aa3ff',
  waiting: '#ffc233',
  error: '#ff5c5c',
  handing_off: '#b98cff',
  waiting_subagents: '#7fd6e8',
  thinking: '#8fb3e0',
  done: '#8fd48a',
  idle: '#b4b4c8',
};

export function stateText(i: Instance, activeSubagents = 0): string {
  switch (i.state) {
    case 'working':
      return i.animation === 'read' ? 'trabajando · lee' : 'trabajando · escribe';
    case 'waiting':
      return 'espera aprobación';
    case 'error':
      return 'error';
    case 'handing_off':
      return 'entregando';
    case 'waiting_subagents':
      return activeSubagents > 0 ? `espera ${activeSubagents} subagente${activeSubagents > 1 ? 's' : ''}` : 'espera subagentes';
    case 'done':
      return i.main ? 'turno terminado' : 'terminado';
    case 'thinking':
      return 'pensando';
    case 'idle':
      return 'ocioso';
  }
}

/** Group for the header summary: what the owner needs to see first. */
export function group(s: State): 'working' | 'waiting' | 'error' | 'idle' {
  if (s === 'waiting') return 'waiting';
  if (s === 'error') return 'error';
  if (s === 'idle' || s === 'done') return 'idle';
  return 'working';
}

export function duration(sec: number | null | undefined): string {
  if (sec === null || sec === undefined) return '';
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}

export function displayName(i: Instance, totalOfType: number): string {
  return totalOfType > 1 || i.number > 1 ? `${i.type} #${i.number}` : i.type;
}

/** Short name for the floor label (the full one goes on the card). Short names come from the profile. */
export function shortName(i: Instance, totalOfType: number): string {
  const base = profile().floor.short_names[i.type] ?? i.type;
  return totalOfType > 1 || i.number > 1 ? `${base} #${i.number}` : base;
}

export function shortModel(m: string | null): string {
  if (!m) return '?';
  const s = m.toLowerCase();
  if (s.includes('opus')) return 'opus';
  if (s.includes('sonnet')) return 'sonnet';
  if (s.includes('haiku')) return 'haiku';
  if (s.includes('fable')) return 'fable';
  return m.length > 10 ? m.slice(0, 10) : m;
}

/** One-letter badge for the floor: O (opus), S (sonnet), H (haiku), F (fable). */
export function modelBadge(m: string | null): { letter: string; color: string } {
  const c = shortModel(m);
  const table: Record<string, { letter: string; color: string }> = {
    opus: { letter: 'O', color: '#c58cff' },
    sonnet: { letter: 'S', color: '#ff9a4a' },
    haiku: { letter: 'H', color: '#6fd08c' },
    fable: { letter: 'F', color: '#ffd84a' },
  };
  return table[c] ?? { letter: '?', color: '#9a9aae' };
}

/** Abbreviated state for the floor label, where width is scarce. */
export function shortStateText(i: Instance, activeSubagents = 0): string {
  if (i.state === 'working') return i.animation === 'read' ? 'lee' : 'escribe';
  if (i.state === 'waiting_subagents') return activeSubagents > 0 ? `espera ${activeSubagents} sub.` : 'espera sub.';
  return stateText(i, activeSubagents);
}
