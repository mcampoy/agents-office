// Replaces upstream's src/transport/index.ts in the office build (alias in vite.office.config.ts).
//
// The office does not talk to an extension or open a WebSocket: data arrives over SSE (data.ts) and the web
// is read-only. The only thing handled is the floor editor's `saveLayout`, which goes by
// POST /api/layout to the profile's layout.json. Everything else upstream sends (focus terminal, save
// seats, etc.) is dropped.
import type { MessageTransport } from '../../../core/src/transport.js';

import { api } from './api.ts';

export type SaveStatus = { status: 'saving' | 'saved' | 'error'; detail?: string };
const listeners = new Set<(s: SaveStatus) => void>();

/** Layout save notices (to show "guardado" or the error in the editor). */
export function onSave(fn: (s: SaveStatus) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function notify(s: SaveStatus): void {
  for (const fn of listeners) fn(s);
}

async function saveLayout(layout: unknown): Promise<void> {
  notify({ status: 'saving' });
  try {
    const r = await fetch(api('layout'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(layout),
    });
    if (!r.ok) {
      const body = (await r.json().catch(() => ({}))) as { error?: string };
      notify({ status: 'error', detail: body.error ?? `HTTP ${r.status}` });
      return;
    }
    notify({ status: 'saved' });
  } catch (error) {
    notify({ status: 'error', detail: String(error) });
  }
}

const ours = {
  send(message: { type: string; layout?: unknown }) {
    if (message.type === 'saveLayout' && message.layout) void saveLayout(message.layout);
  },
  onMessage: () => () => undefined,
  onStateChange: () => () => undefined,
  ready: Promise.resolve(),
  state: 'connected',
  dispose: () => undefined,
} as unknown as MessageTransport;

export const transport: MessageTransport = ours;
export type { MessageTransport } from '../../../core/src/transport.js';
