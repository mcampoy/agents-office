// Sound and vibration alerts for the phone: the main session ended its turn, or someone waits for the owner.
//
// On the computer, Windows shows these (the capture hook): here they only play when the office is opened from
// another device of the network. Browsers only let a page play sound after a tap, and over plain http the phone
// does not allow system notifications: the alerts work while the office is open and on screen.
import { useEffect, useRef, useState } from 'react';

import type { Snapshot } from './types.ts';

const PREFERENCE = 'ao-alerts';
const BUSY = new Set(['working', 'thinking', 'waiting_subagents', 'waiting', 'handing_off']);

/** Opened from another device (the phone), not from this computer. */
export function isRemote(): boolean {
  return !['127.0.0.1', 'localhost', '::1', '[::1]'].includes(window.location.hostname);
}

let audio: AudioContext | null = null;

function context(): AudioContext | null {
  try {
    audio ??= new AudioContext();
    if (audio.state === 'suspended') void audio.resume();
    return audio;
  } catch {
    return null;
  }
}

/** One note: frequency (Hz), start and length (s) from now. */
function note(ctx: AudioContext, freq: number, at: number, length: number, type: OscillatorType, volume: number) {
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.type = type;
  osc.frequency.value = freq;
  const t = ctx.currentTime + at;
  gain.gain.setValueAtTime(0, t);
  gain.gain.linearRampToValueAtTime(volume, t + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.0001, t + length);
  osc.connect(gain).connect(ctx.destination);
  osc.start(t);
  osc.stop(t + length + 0.05);
}

/** Turn ended: two soft rising notes. Someone waits: three short insistent beeps, and a longer vibration. */
export function play(kind: 'done' | 'waiting'): void {
  const ctx = context();
  if (ctx) {
    if (kind === 'done') {
      note(ctx, 659, 0, 0.35, 'sine', 0.25);
      note(ctx, 988, 0.18, 0.5, 'sine', 0.25);
    } else {
      for (const at of [0, 0.22, 0.44]) note(ctx, 1175, at, 0.16, 'square', 0.12);
    }
  }
  try {
    navigator.vibrate?.(kind === 'done' ? 150 : [250, 120, 250, 120, 250]);
  } catch {
    /* without vibration */
  }
}

function readPreference(): boolean {
  try {
    return window.localStorage.getItem(PREFERENCE) === 'on';
  } catch {
    return false;
  }
}

function writePreference(on: boolean): void {
  try {
    window.localStorage.setItem(PREFERENCE, on ? 'on' : 'off');
  } catch {
    /* the switch still works for this visit */
  }
}

/** The switch (stays on in this browser) and the watcher of the snapshots. */
export function useAlerts(snapshot: Snapshot | null): { on: boolean; toggle: () => void } {
  const [on, setOn] = useState(readPreference);
  const previous = useRef<Map<string, string> | null>(null);
  const lastWait = useRef(0);

  // After a reload the sound stays locked until the first tap anywhere on the page
  useEffect(() => {
    if (!on) return;
    const unlock = () => context();
    window.addEventListener('pointerdown', unlock, { once: true });
    return () => window.removeEventListener('pointerdown', unlock);
  }, [on]);

  useEffect(() => {
    if (!snapshot) return;
    const states = new Map(snapshot.instances.map((i) => [i.key, i.state]));
    const before = previous.current;
    previous.current = states;
    if (!before || !on) return; // the first snapshot only sets the starting point
    let done = false;
    let waiting = false;
    for (const i of snapshot.instances) {
      const was = before.get(i.key);
      if (i.state === 'waiting' && was !== 'waiting') waiting = true;
      if (i.main && i.state === 'done' && was !== undefined && BUSY.has(was)) done = true;
    }
    // A wait matters more than a turn end; one sound per moment
    if (waiting && Date.now() - lastWait.current > 3000) {
      lastWait.current = Date.now();
      play('waiting');
    } else if (done) {
      play('done');
    }
  }, [snapshot, on]);

  const toggle = () => {
    const next = !on;
    setOn(next);
    writePreference(next);
    if (next) play('done'); // the tap unlocks the sound, and confirms it works
  };
  return { on, toggle };
}
