// Reconciler: brings the server snapshot into the Pixel Agents engine (OfficeState).
//
// The engine knows how to walk, sit, type and read. Here we decide, per instance, which character it is,
// which seat it takes (by zone) and how it behaves according to its state. States come from the
// hooks (server/model.py); the engine guesses nothing.
import { getCatalogEntry } from '../office/layout/furnitureCatalog.js';
import type { OfficeState } from '../office/engine/officeState.js';
import { CharacterState } from '../office/types.js';
import { profile } from './profile.ts';
import type { Characters, Instance, Snapshot, SpritesConfig } from './types.ts';

export const AVATAR_ID = 100000;
/** A finished subagent rests in the lounge this long and then leaves the floor. */
export const DONE_REST_S = 180;
/** The avatar stays next to the main agent this long after a prompt. */
const AVATAR_VISIT_S = 6;

// Fixed zones the floor relies on (layout area ids)
const LOUNGE = 'lounge';
const FLOATING = 'floating';
const RECEPTION = 'reception';
const OWNER = 'owner';

type Mode = 'works' | 'seated' | 'standing' | 'walks' | 'sofa';

interface Token {
  id: number;
  key: string;
  inst: Instance;
  mode: Mode | null;
  target: string | null;
}

export function visibleOnFloor(i: Instance): boolean {
  if (i.state === 'done' && !i.main && (i.seconds_in_state ?? 0) > DONE_REST_S) return false;
  return true;
}

function matches(name: string, pattern: string): boolean {
  if (!pattern.includes('*')) return name === pattern;
  const re = new RegExp('^' + pattern.split('*').map((p) => p.replace(/[.+?^${}()|[\]\\]/g, '\\$&')).join('.*') + '$');
  return re.test(name);
}

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export class FloorController {
  private tokens = new Map<string, Token>();
  private byId = new Map<number, Token>();
  private nextId = 1;
  private spriteByType = new Map<string, number>();
  private lastPrompt: string | null | undefined = undefined;
  private visitUntil = 0;
  private avatarVisiting = false;
  private clock = 0;

  private os: OfficeState;
  private characters: Characters;
  private sprites: SpritesConfig;

  constructor(os: OfficeState, characters: Characters, sprites: SpritesConfig) {
    this.os = os;
    this.characters = characters;
    this.sprites = sprites;
    // Per-frame adjustments run after the engine update
    const original = os.update.bind(os);
    os.update = (dt: number) => {
      original(dt);
      this.perFrame(dt);
    };
  }

  /** Key of the instance that owns a character (for the click on the floor). */
  keyOf(id: number): string | null {
    return this.byId.get(id)?.key ?? null;
  }

  idOf(key: string): number | null {
    return this.tokens.get(key)?.id ?? null;
  }

  // --- Sprites -------------------------------------------------------------------------------

  private spriteOf(type: string): number {
    const known = this.spriteByType.get(type);
    if (known !== undefined) return known;
    const rules = this.sprites.agents ?? {};
    const rule = Object.entries(rules).find(([pattern]) => matches(type, pattern));
    let chosen: number;
    if (rule && typeof rule[1].sprite === 'number') {
      chosen = rule[1].sprite;
    } else {
      // Deterministic by name; if it collides with another present type, the next free one in the pool
      const pool = this.characters.assignable;
      const used = new Set(this.spriteByType.values());
      const reserved = new Set(Object.values(rules).map((r) => r.sprite));
      const start = hash(type) % pool.length;
      chosen = pool[start];
      for (let k = 0; k < pool.length; k++) {
        const c = pool[(start + k) % pool.length];
        if (!used.has(c) && !reserved.has(c)) {
          chosen = c;
          break;
        }
      }
    }
    this.spriteByType.set(type, chosen);
    return chosen;
  }

  // --- Seats ---------------------------------------------------------------------------------

  private free(zone: string): string[] {
    const out: string[] = [];
    for (const [uid, s] of this.os.seats) {
      if (!s.assigned && this.os.seatZone(uid) === zone) out.push(uid);
    }
    // Stable order: top to bottom and left to right
    return out.sort((a, b) => {
      const sa = this.os.seats.get(a)!;
      const sb = this.os.seats.get(b)!;
      return sa.seatRow - sb.seatRow || sa.seatCol - sb.seatCol;
    });
  }

  /** Position of the first piece of furniture of a type (for example the wall clock). */
  furniture(prefix: string): { col: number; row: number } | null {
    const m = this.os.getLayout().furniture.find((f) => f.type.startsWith(prefix));
    return m ? { col: m.col, row: m.row } : null;
  }

  private seatFor(i: Instance): string | null {
    // A subagent that already finished (for example on page reload) shows up directly in the lounge
    if (i.state === 'done' && !i.main && !i.general) {
      const armchair = this.free(LOUNGE)[0];
      if (armchair) return armchair;
    }
    let candidates = this.free(i.zone);
    const clockAgent = profile().floor.next_to_clock;
    if (clockAgent && i.type === clockAgent) {
      // The scheduled-run agent sits next to the clock
      const clock = this.furniture('CLOCK');
      if (clock) {
        candidates = candidates.sort((a, b) => {
          const sa = this.os.seats.get(a)!;
          const sb = this.os.seats.get(b)!;
          return Math.abs(sa.seatCol - clock.col) - Math.abs(sb.seatCol - clock.col);
        });
      }
    } else if (clockAgent) {
      // The others leave that desk (the one closest to the clock) free while others remain
      const clock = this.furniture('CLOCK');
      if (clock && candidates.length > 1) {
        const closest = [...candidates].sort(
          (a, b) => Math.abs(this.os.seats.get(a)!.seatCol - clock.col) - Math.abs(this.os.seats.get(b)!.seatCol - clock.col),
        )[0];
        candidates = candidates.filter((c) => c !== closest).concat(closest);
      }
    }
    if (candidates.length) return candidates[0];
    // Room full: floating desk; if there is none either, reception
    return this.free(FLOATING)[0] ?? this.free(RECEPTION)[0] ?? null;
  }

  // --- Sync with the snapshot ----------------------------------------------------------------

  sync(snapshot: Snapshot, initial: boolean): void {
    const present = new Set<string>();
    for (const inst of snapshot.instances) {
      if (!visibleOnFloor(inst)) continue;
      present.add(inst.key);
      let t = this.tokens.get(inst.key);
      if (!t) {
        const id = this.nextId++;
        const seat = this.seatFor(inst);
        this.os.addAgent(id, this.spriteOf(inst.type), 0, seat ?? undefined, initial);
        t = { id, key: inst.key, inst, mode: null, target: null };
        this.tokens.set(inst.key, t);
        this.byId.set(id, t);
      }
      t.inst = inst;
    }
    for (const [key, t] of this.tokens) {
      if (!present.has(key)) {
        this.os.removeAgent(t.id);
        this.tokens.delete(key);
        this.byId.delete(t.id);
      }
    }
    for (const t of this.tokens.values()) this.applyState(t);
    this.avatar(snapshot, initial);
  }

  private mainOf(session: string): Token | undefined {
    for (const t of this.tokens.values()) if (t.inst.main && t.inst.session === session) return t;
    return undefined;
  }

  private active(id: number, value: boolean): void {
    const ch = this.os.characters.get(id);
    if (ch && ch.isActive !== value) this.os.setAgentActive(id, value);
  }

  private applyState(t: Token): void {
    const i = t.inst;
    const ch = this.os.characters.get(t.id);
    if (!ch) return;
    let mode: Mode;
    switch (i.state) {
      case 'working':
        mode = 'works';
        break;
      case 'waiting':
      case 'error':
      case 'waiting_subagents':
      case 'thinking':
        mode = 'seated';
        break;
      case 'handing_off':
        mode = 'walks';
        break;
      case 'done':
        mode = i.main ? 'seated' : i.general ? 'walks' : 'sofa';
        break;
      case 'idle':
      default:
        mode = 'standing';
    }
    const changed = mode !== t.mode;
    t.mode = mode;
    if (mode === 'works') {
      this.active(t.id, true);
      this.os.setAgentTool(t.id, i.animation === 'read' ? 'Read' : 'Write');
    } else {
      this.os.setAgentTool(t.id, null);
    }
    if (mode === 'seated') this.active(t.id, true);
    if (mode === 'standing') this.active(t.id, false);
    if (mode === 'sofa' && changed) {
      // Frees the desk and goes to a lounge armchair (unless already in one)
      if (ch.seatId && this.os.seatZone(ch.seatId) === LOUNGE) {
        this.active(t.id, true);
        return;
      }
      const armchair = this.free(LOUNGE)[0];
      if (armchair) {
        this.os.reassignSeat(t.id, armchair);
        this.active(t.id, true);
      } else {
        this.active(t.id, false);
        this.walkTo(t.id, this.freeTile(LOUNGE));
      }
    }
    if (mode === 'walks' && changed) {
      this.active(t.id, false);
      if (i.state === 'handing_off') {
        // Takes the result to the main agent's desk
        const p = this.mainOf(i.session);
        this.walkTo(t.id, p ? this.nextTo(p.id) : null);
      } else {
        // A general agent that finished: heads to the reception (the exit) until the server removes it
        this.walkTo(t.id, this.freeTile(RECEPTION));
      }
    }
  }

  private walkTo(id: number, target: { col: number; row: number } | null): void {
    if (target) this.os.walkToTile(id, target.col, target.row);
  }

  /** A free walkable tile next to a character's seat. */
  private nextTo(id: number): { col: number; row: number } | null {
    const ch = this.os.characters.get(id);
    const seat = ch?.seatId ? this.os.seats.get(ch.seatId) : null;
    if (!seat) return null;
    const occupied = new Set([...this.os.characters.values()].map((c) => `${c.tileCol},${c.tileRow}`));
    const walkable = new Set(this.os.walkableTiles.map((t) => `${t.col},${t.row}`));
    for (const [dc, dr] of [[1, 0], [-1, 0], [0, 1], [2, 0], [-2, 0], [1, 1], [-1, 1]]) {
      const k = `${seat.seatCol + dc},${seat.seatRow + dr}`;
      if (walkable.has(k) && !occupied.has(k)) return { col: seat.seatCol + dc, row: seat.seatRow + dr };
    }
    return null;
  }

  private freeTile(zone: string): { col: number; row: number } | null {
    const layout = this.os.getLayout();
    const occupied = new Set([...this.os.characters.values()].map((c) => `${c.tileCol},${c.tileRow}`));
    const inZone = this.os.walkableTiles.filter(
      (t) => layout.areaTiles?.[t.row * layout.cols + t.col] === zone && !occupied.has(`${t.col},${t.row}`),
    );
    return inZone.length ? inZone[Math.floor(Math.random() * inZone.length)] : null;
  }

  // --- Owner's avatar ------------------------------------------------------------------------

  private avatar(snapshot: Snapshot, initial: boolean): void {
    if (!this.os.characters.has(AVATAR_ID)) {
      const seat = this.free(OWNER)[0];
      this.os.addAgent(AVATAR_ID, this.characters.avatar, 0, seat, true);
      this.active(AVATAR_ID, true);
    }
    const prompt = snapshot.owner.last_prompt;
    if (this.lastPrompt !== undefined && prompt && prompt !== this.lastPrompt) {
      // A new prompt from the owner: walks to the main agent's desk for a moment
      const session = snapshot.main?.session;
      const p = session ? this.mainOf(session) : undefined;
      const target = p ? this.nextTo(p.id) : null;
      if (target) {
        this.active(AVATAR_ID, false);
        this.walkTo(AVATAR_ID, target);
        this.avatarVisiting = true;
        this.visitUntil = this.clock + AVATAR_VISIT_S + 4;
      }
    }
    if (this.lastPrompt === undefined || !initial) this.lastPrompt = prompt;
  }

  // --- Per frame -----------------------------------------------------------------------------

  private perFrame(dt: number): void {
    this.clock += dt;
    for (const t of this.tokens.values()) {
      const ch = this.os.characters.get(t.id);
      if (!ch) continue;
      this.still(ch, t.mode);
    }
    const av = this.os.characters.get(AVATAR_ID);
    if (av) {
      if (this.avatarVisiting && this.clock > this.visitUntil) {
        this.avatarVisiting = false;
        this.active(AVATAR_ID, true); // back to its desk
      }
      this.still(av, this.avatarVisiting ? 'walks' : 'seated');
    }
  }

  /** Freezes the animation of those seated without working and stops the others from wandering. */
  private still(ch: { state: string; frame: number; frameTimer: number; wanderTimer: number }, mode: Mode | null): void {
    if ((mode === 'seated' || mode === 'sofa') && ch.state === CharacterState.TYPE) {
      ch.frame = 0;
      ch.frameTimer = 0;
    }
    if ((mode === 'standing' || mode === 'walks') && ch.state === CharacterState.IDLE) {
      ch.wanderTimer = 1e9;
    }
  }

  /** Whether anyone is active in a zone (to turn off the lights of the profile's lights_off rooms). */
  zoneActive(zone: string): boolean {
    for (const t of this.tokens.values()) {
      if (t.inst.zone === zone && t.inst.state !== 'idle' && t.inst.state !== 'done') return true;
    }
    return false;
  }

  /** Rectangle of an area in tiles. */
  rectangle(zone: string): { c0: number; r0: number; c1: number; r1: number } | null {
    const l = this.os.getLayout();
    let c0 = Infinity, r0 = Infinity, c1 = -1, r1 = -1;
    l.areaTiles?.forEach((a, k) => {
      if (a !== zone) return;
      const c = k % l.cols, r = Math.floor(k / l.cols);
      c0 = Math.min(c0, c); r0 = Math.min(r0, r); c1 = Math.max(c1, c); r1 = Math.max(r1, r);
    });
    return c1 < 0 ? null : { c0, r0, c1, r1 };
  }

  visibleTokens(): Array<{ id: number; inst: Instance }> {
    return [...this.tokens.values()].map((t) => ({ id: t.id, inst: t.inst }));
  }
}

export function isFurniture(type: string): boolean {
  return !!getCatalogEntry(type);
}
