// Reemplaza a src/transport/index.ts de upstream en el build de la oficina (alias en vite.idi.config.ts).
//
// La oficina no habla con una extensión ni abre WebSocket: los datos llegan por SSE (datos.ts) y la web
// es de solo lectura. Lo único que se atiende es el `saveLayout` del editor del piso, que va por
// POST /api/layout a config/layout.json. Todo lo demás que upstream envía (enfocar terminal, guardar
// asientos, etc.) se descarta.
import type { MessageTransport } from '../../../core/src/transport.js';

import { api } from './api.ts';

export type EstadoGuardado = { estado: 'guardando' | 'guardado' | 'error'; detalle?: string };
const oyentes = new Set<(e: EstadoGuardado) => void>();

/** Avisos del guardado del layout (para mostrar "guardado" o el error en el editor). */
export function alGuardar(fn: (e: EstadoGuardado) => void): () => void {
  oyentes.add(fn);
  return () => oyentes.delete(fn);
}

function avisar(e: EstadoGuardado): void {
  for (const fn of oyentes) fn(e);
}

async function guardarLayout(layout: unknown): Promise<void> {
  avisar({ estado: 'guardando' });
  try {
    const r = await fetch(api('layout'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(layout),
    });
    if (!r.ok) {
      const cuerpo = (await r.json().catch(() => ({}))) as { error?: string };
      avisar({ estado: 'error', detalle: cuerpo.error ?? `HTTP ${r.status}` });
      return;
    }
    avisar({ estado: 'guardado' });
  } catch (error) {
    avisar({ estado: 'error', detalle: String(error) });
  }
}

const propio = {
  send(mensaje: { type: string; layout?: unknown }) {
    if (mensaje.type === 'saveLayout' && mensaje.layout) void guardarLayout(mensaje.layout);
  },
  onMessage: () => () => undefined,
  onStateChange: () => () => undefined,
  ready: Promise.resolve(),
  state: 'connected',
  dispose: () => undefined,
} as unknown as MessageTransport;

export const transport: MessageTransport = propio;
export type { MessageTransport } from '../../../core/src/transport.js';
