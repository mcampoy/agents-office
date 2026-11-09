// What the floor knows about the team: comes from /api/profile (the active profile's profile.json, see docs/profile.md).
// Loaded once, before drawing, and then read with profile().

export interface WebProfile {
  name: string;
  main_agent: string;
  verifier: string | null;
  owner_label: string;
  scheduled_run: { agent?: string; weekday?: number; hour?: number } | null;
  floor: {
    /** Layout zone → visible room name. */
    rooms: Record<string, string>;
    /** Agent → short name for the floor label. */
    short_names: Record<string, string>;
    /** Agent pattern (with '*') → accessory it carries on the floor ('magnifier'). */
    accessories: Record<string, string>;
    /** Agent → icon shown when it works outside the area, and regex of the tools that trigger it. */
    external_work: Record<string, { icon: string; tools: string }>;
    /** Agent that sits next to the scheduled-run clock (the others leave that spot to it). */
    next_to_clock: string | null;
    /** Zones shown in the dark while nobody is active in them. */
    lights_off?: string[];
  };
}

const DEFAULT: WebProfile = {
  name: 'Oficina',
  main_agent: 'main',
  verifier: null,
  owner_label: 'responsable',
  scheduled_run: null,
  floor: { rooms: {}, short_names: {}, accessories: {}, external_work: {}, next_to_clock: null, lights_off: [] },
};

let current: WebProfile = DEFAULT;

export function setProfile(p: Partial<WebProfile> | null): void {
  current = { ...DEFAULT, ...(p ?? {}), floor: { ...DEFAULT.floor, ...(p?.floor ?? {}) } };
  document.title = current.name;
}

export function profile(): WebProfile {
  return current;
}

export function matches(name: string, pattern: string): boolean {
  if (!pattern.includes('*')) return name === pattern;
  const re = new RegExp('^' + pattern.split('*').map((p) => p.replace(/[.+?^${}()|[\]\\]/g, '\\$&')).join('.*') + '$');
  return re.test(name);
}

/** The agent's accessory according to the profile ('magnifier' or null). */
export function accessoryOf(type: string): string | null {
  const rule = Object.entries(current.floor.accessories).find(([pattern]) => matches(type, pattern));
  return rule ? rule[1] : null;
}

/** External work icon if the agent is using one of those tools. */
export function externalWork(type: string, tool: string | null): string | null {
  const rule = current.floor.external_work[type];
  if (!rule || !tool) return null;
  try {
    return new RegExp(rule.tools, 'i').test(tool) ? rule.icon : null;
  } catch {
    return null;
  }
}
