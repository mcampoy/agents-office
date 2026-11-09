// Reconciliador: lleva la foto del servidor al motor de Pixel Agents (OfficeState).
//
// El motor sabe caminar, sentarse, tipear y leer. Acá se decide, por instancia, qué personaje es,
// en qué asiento se sienta (por zona) y cómo se comporta según su estado. Los estados salen de los
// hooks (servidor/modelo.py); el motor no adivina nada.
import { getCatalogEntry } from '../office/layout/furnitureCatalog.js';
import type { OfficeState } from '../office/engine/officeState.js';
import { CharacterState } from '../office/types.js';
import { perfil } from './perfil.ts';
import type { ConfigSprites, Foto, Instancia, Personajes } from './tipos.ts';

export const ID_AVATAR = 100000;
/** Un subagente terminado descansa en la zona común este tiempo y después se va del piso. */
export const DESCANSO_TERMINADOS_S = 180;
/** El avatar se queda junto al agente principal este tiempo después de un prompt. */
const VISITA_AVATAR_S = 6;

type Modo = 'trabaja' | 'sentado' | 'parado' | 'camina' | 'sofa';

interface Ficha {
  id: number;
  clave: string;
  inst: Instancia;
  modo: Modo | null;
  destino: string | null;
}

export function visibleEnPiso(i: Instancia): boolean {
  if (i.estado === 'terminado' && !i.principal && (i.segundos_en_estado ?? 0) > DESCANSO_TERMINADOS_S) return false;
  return true;
}

function coincide(nombre: string, patron: string): boolean {
  if (!patron.includes('*')) return nombre === patron;
  const re = new RegExp('^' + patron.split('*').map((p) => p.replace(/[.+?^${}()|[\]\\]/g, '\\$&')).join('.*') + '$');
  return re.test(nombre);
}

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export class ControlPiso {
  private fichas = new Map<string, Ficha>();
  private porId = new Map<number, Ficha>();
  private siguiente = 1;
  private spritePorTipo = new Map<string, number>();
  private ultimoPrompt: string | null | undefined = undefined;
  private visitaHasta = 0;
  private avatarVisitando = false;
  private reloj = 0;

  private os: OfficeState;
  private personajes: Personajes;
  private sprites: ConfigSprites;

  constructor(os: OfficeState, personajes: Personajes, sprites: ConfigSprites) {
    this.os = os;
    this.personajes = personajes;
    this.sprites = sprites;
    // Los ajustes por cuadro van después de la actualización del motor
    const original = os.update.bind(os);
    os.update = (dt: number) => {
      original(dt);
      this.porCuadro(dt);
    };
  }

  /** Clave de la instancia dueña de un personaje (para el clic en el piso). */
  claveDe(id: number): string | null {
    return this.porId.get(id)?.clave ?? null;
  }

  idDe(clave: string): number | null {
    return this.fichas.get(clave)?.id ?? null;
  }

  // --- Sprites -------------------------------------------------------------------------

  private spriteDe(tipo: string): number {
    const ya = this.spritePorTipo.get(tipo);
    if (ya !== undefined) return ya;
    const reglas = this.sprites.agentes ?? {};
    const regla = Object.entries(reglas).find(([patron]) => coincide(tipo, patron));
    let elegido: number;
    if (regla && typeof regla[1].sprite === 'number') {
      elegido = regla[1].sprite;
    } else {
      // Determinístico por nombre; si choca con otro tipo presente, el siguiente libre del pool
      const pool = this.personajes.asignables;
      const usados = new Set(this.spritePorTipo.values());
      const reservados = new Set(Object.values(reglas).map((r) => r.sprite));
      const inicio = hash(tipo) % pool.length;
      elegido = pool[inicio];
      for (let k = 0; k < pool.length; k++) {
        const c = pool[(inicio + k) % pool.length];
        if (!usados.has(c) && !reservados.has(c)) {
          elegido = c;
          break;
        }
      }
    }
    this.spritePorTipo.set(tipo, elegido);
    return elegido;
  }

  // --- Asientos ------------------------------------------------------------------------

  private libres(zona: string): string[] {
    const out: string[] = [];
    for (const [uid, s] of this.os.seats) {
      if (!s.assigned && this.os.seatZone(uid) === zona) out.push(uid);
    }
    // Orden estable: de arriba hacia abajo y de izquierda a derecha
    return out.sort((a, b) => {
      const sa = this.os.seats.get(a)!;
      const sb = this.os.seats.get(b)!;
      return sa.seatRow - sb.seatRow || sa.seatCol - sb.seatCol;
    });
  }

  /** Posición del primer mueble de un tipo (por ejemplo el reloj de pared). */
  mueble(prefijo: string): { col: number; row: number } | null {
    const m = this.os.getLayout().furniture.find((f) => f.type.startsWith(prefijo));
    return m ? { col: m.col, row: m.row } : null;
  }

  private asientoPara(i: Instancia): string | null {
    // Un subagente que ya terminó (por ejemplo al recargar la página) aparece directo en la zona común
    if (i.estado === 'terminado' && !i.principal && !i.general) {
      const sillon = this.libres('comun')[0];
      if (sillon) return sillon;
    }
    let candidatos = this.libres(i.zona);
    const delReloj = perfil().piso.junto_al_reloj;
    if (delReloj && i.tipo === delReloj) {
      // El agente de la corrida programada se sienta junto al reloj
      const reloj = this.mueble('CLOCK');
      if (reloj) {
        candidatos = candidatos.sort((a, b) => {
          const sa = this.os.seats.get(a)!;
          const sb = this.os.seats.get(b)!;
          return Math.abs(sa.seatCol - reloj.col) - Math.abs(sb.seatCol - reloj.col);
        });
      }
    } else if (delReloj) {
      // Los demás le dejan libre ese escritorio (el más cercano al reloj) mientras queden otros
      const reloj = this.mueble('CLOCK');
      if (reloj && candidatos.length > 1) {
        const cerca = [...candidatos].sort(
          (a, b) => Math.abs(this.os.seats.get(a)!.seatCol - reloj.col) - Math.abs(this.os.seats.get(b)!.seatCol - reloj.col),
        )[0];
        candidatos = candidatos.filter((c) => c !== cerca).concat(cerca);
      }
    }
    if (candidatos.length) return candidatos[0];
    // Sala llena: escritorio flotante; si tampoco hay, recepción
    return this.libres('flotante')[0] ?? this.libres('recepcion')[0] ?? null;
  }

  // --- Sincronización con la foto -----------------------------------------------------------

  sincronizar(foto: Foto, inicial: boolean): void {
    const presentes = new Set<string>();
    for (const inst of foto.instancias) {
      if (!visibleEnPiso(inst)) continue;
      presentes.add(inst.clave);
      let f = this.fichas.get(inst.clave);
      if (!f) {
        const id = this.siguiente++;
        const asiento = this.asientoPara(inst);
        this.os.addAgent(id, this.spriteDe(inst.tipo), 0, asiento ?? undefined, inicial);
        f = { id, clave: inst.clave, inst, modo: null, destino: null };
        this.fichas.set(inst.clave, f);
        this.porId.set(id, f);
      }
      f.inst = inst;
    }
    for (const [clave, f] of this.fichas) {
      if (!presentes.has(clave)) {
        this.os.removeAgent(f.id);
        this.fichas.delete(clave);
        this.porId.delete(f.id);
      }
    }
    for (const f of this.fichas.values()) this.aplicarEstado(f, foto);
    this.avatar(foto, inicial);
  }

  private principalDe(sesion: string): Ficha | undefined {
    for (const f of this.fichas.values()) if (f.inst.principal && f.inst.sesion === sesion) return f;
    return undefined;
  }

  private activo(id: number, valor: boolean): void {
    const ch = this.os.characters.get(id);
    if (ch && ch.isActive !== valor) this.os.setAgentActive(id, valor);
  }

  private aplicarEstado(f: Ficha, foto: Foto): void {
    const i = f.inst;
    const ch = this.os.characters.get(f.id);
    if (!ch) return;
    let modo: Modo;
    switch (i.estado) {
      case 'trabajando':
        modo = 'trabaja';
        break;
      case 'esperando':
      case 'error':
      case 'esperando_subagentes':
        modo = 'sentado';
        break;
      case 'entregando':
        modo = 'camina';
        break;
      case 'terminado':
        modo = i.principal ? 'sentado' : i.general ? 'camina' : 'sofa';
        break;
      case 'ocioso':
      default:
        modo = 'parado';
    }
    const cambio = modo !== f.modo;
    f.modo = modo;
    if (modo === 'trabaja') {
      this.activo(f.id, true);
      this.os.setAgentTool(f.id, i.animacion === 'lee' ? 'Read' : 'Write');
    } else {
      this.os.setAgentTool(f.id, null);
    }
    if (modo === 'sentado') this.activo(f.id, true);
    if (modo === 'parado') this.activo(f.id, false);
    if (modo === 'sofa' && cambio) {
      // Libera el escritorio y va a un sillón de la zona común (si no está ya en uno)
      if (ch.seatId && this.os.seatZone(ch.seatId) === 'comun') {
        this.activo(f.id, true);
        return;
      }
      const sillon = this.libres('comun')[0];
      if (sillon) {
        this.os.reassignSeat(f.id, sillon);
        this.activo(f.id, true);
      } else {
        this.activo(f.id, false);
        this.caminarA(f.id, this.baldosaLibre('comun'));
      }
    }
    if (modo === 'camina' && cambio) {
      this.activo(f.id, false);
      if (i.estado === 'entregando') {
        // Lleva el resultado al escritorio de partner
        const p = this.principalDe(i.sesion);
        this.caminarA(f.id, p ? this.junto(p.id) : null);
      } else {
        // General que terminó: se va hacia la recepción (la salida) hasta que el servidor lo retira
        this.caminarA(f.id, this.baldosaLibre('recepcion'));
      }
    }
    void foto;
  }

  private caminarA(id: number, destino: { col: number; row: number } | null): void {
    if (destino) this.os.walkToTile(id, destino.col, destino.row);
  }

  /** Una baldosa caminable libre al lado del asiento de un personaje. */
  private junto(id: number): { col: number; row: number } | null {
    const ch = this.os.characters.get(id);
    const seat = ch?.seatId ? this.os.seats.get(ch.seatId) : null;
    if (!seat) return null;
    const ocupadas = new Set([...this.os.characters.values()].map((c) => `${c.tileCol},${c.tileRow}`));
    const caminables = new Set(this.os.walkableTiles.map((t) => `${t.col},${t.row}`));
    for (const [dc, dr] of [[1, 0], [-1, 0], [0, 1], [2, 0], [-2, 0], [1, 1], [-1, 1]]) {
      const k = `${seat.seatCol + dc},${seat.seatRow + dr}`;
      if (caminables.has(k) && !ocupadas.has(k)) return { col: seat.seatCol + dc, row: seat.seatRow + dr };
    }
    return null;
  }

  private baldosaLibre(zona: string): { col: number; row: number } | null {
    const layout = this.os.getLayout();
    const ocupadas = new Set([...this.os.characters.values()].map((c) => `${c.tileCol},${c.tileRow}`));
    const enZona = this.os.walkableTiles.filter(
      (t) => layout.areaTiles?.[t.row * layout.cols + t.col] === zona && !ocupadas.has(`${t.col},${t.row}`),
    );
    return enZona.length ? enZona[Math.floor(Math.random() * enZona.length)] : null;
  }

  // --- Avatar del responsable ------------------------------------------------------------------

  private avatar(foto: Foto, inicial: boolean): void {
    if (!this.os.characters.has(ID_AVATAR)) {
      const asiento = this.libres('responsable')[0];
      this.os.addAgent(ID_AVATAR, this.personajes.avatar, 0, asiento, true);
      this.activo(ID_AVATAR, true);
    }
    const prompt = foto.responsable.ultimo_prompt;
    if (this.ultimoPrompt !== undefined && prompt && prompt !== this.ultimoPrompt) {
      // Un prompt nuevo del responsable: camina hasta el escritorio de partner un momento
      const sesion = foto.principal?.sesion;
      const p = sesion ? this.principalDe(sesion) : undefined;
      const destino = p ? this.junto(p.id) : null;
      if (destino) {
        this.activo(ID_AVATAR, false);
        this.caminarA(ID_AVATAR, destino);
        this.avatarVisitando = true;
        this.visitaHasta = this.reloj + VISITA_AVATAR_S + 4;
      }
    }
    if (this.ultimoPrompt === undefined || !inicial) this.ultimoPrompt = prompt;
  }

  // --- Por cuadro ---------------------------------------------------------------------------------

  private porCuadro(dt: number): void {
    this.reloj += dt;
    for (const f of this.fichas.values()) {
      const ch = this.os.characters.get(f.id);
      if (!ch) continue;
      this.quieto(ch, f.modo);
    }
    const av = this.os.characters.get(ID_AVATAR);
    if (av) {
      if (this.avatarVisitando && this.reloj > this.visitaHasta) {
        this.avatarVisitando = false;
        this.activo(ID_AVATAR, true); // vuelve a su escritorio
      }
      this.quieto(av, this.avatarVisitando ? 'camina' : 'sentado');
    }
  }

  /** Congela la animación de los que están sentados sin trabajar y frena el deambular de los demás. */
  private quieto(ch: { state: string; frame: number; frameTimer: number; wanderTimer: number }, modo: Modo | null): void {
    if ((modo === 'sentado' || modo === 'sofa') && ch.state === CharacterState.TYPE) {
      ch.frame = 0;
      ch.frameTimer = 0;
    }
    if ((modo === 'parado' || modo === 'camina') && ch.state === CharacterState.IDLE) {
      ch.wanderTimer = 1e9;
    }
  }

  /** Zonas sin nadie activo (para apagar las luces de comunicación). */
  zonaActiva(zona: string): boolean {
    for (const f of this.fichas.values()) {
      if (f.inst.zona === zona && f.inst.estado !== 'ocioso' && f.inst.estado !== 'terminado') return true;
    }
    return false;
  }

  /** Rectángulo de un área en baldosas. */
  rectangulo(zona: string): { c0: number; r0: number; c1: number; r1: number } | null {
    const l = this.os.getLayout();
    let c0 = Infinity, r0 = Infinity, c1 = -1, r1 = -1;
    l.areaTiles?.forEach((a, k) => {
      if (a !== zona) return;
      const c = k % l.cols, r = Math.floor(k / l.cols);
      c0 = Math.min(c0, c); r0 = Math.min(r0, r); c1 = Math.max(c1, c); r1 = Math.max(r1, r);
    });
    return c1 < 0 ? null : { c0, r0, c1, r1 };
  }

  fichasVisibles(): Array<{ id: number; inst: Instancia }> {
    return [...this.fichas.values()].map((f) => ({ id: f.id, inst: f.inst }));
  }
}

export function esMueble(tipo: string): boolean {
  return !!getCatalogEntry(tipo);
}
