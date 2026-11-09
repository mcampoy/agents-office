// Own pixel art icons. Each one is a character grid with its palette ('.' = transparent).
import type { SpriteData } from '../office/types.js';

function sprite(palette: Record<string, string>, rows: string[]): SpriteData {
  return rows.map((f) => [...f].map((c) => (c === '.' ? '' : (palette[c] ?? ''))));
}

const BORDER = '#2a2030';

/** Waiting for approval: solid amber bubble with "!" (fixed, more striking than upstream's). */
export const WAIT_BUBBLE = sprite({ B: BORDER, F: '#ffc233', T: '#2a2030', L: '#ffe28a' }, [
  'BBBBBBBBBBB',
  'BLLFFFFFFFB',
  'BLFFFTFFFFB',
  'BFFFFTFFFFB',
  'BFFFFTFFFFB',
  'BFFFFTFFFFB',
  'BFFFFFFFFFB',
  'BFFFFTFFFFB',
  'BFFFFFFFFFB',
  'BBBBBBBBBBB',
  '....BBB....',
  '.....B.....',
]);

/** Error: red bubble with a white cross. */
export const ERROR_BUBBLE = sprite({ B: BORDER, F: '#e5484d', X: '#ffffff', L: '#ff8a8d' }, [
  'BBBBBBBBBBB',
  'BLLFFFFFFFB',
  'BLXFFFFFXFB',
  'BFFXFFFXFFB',
  'BFFFXFXFFFB',
  'BFFFFXFFFFB',
  'BFFFXFXFFFB',
  'BFFXFFFXFFB',
  'BFXFFFFFXFB',
  'BBBBBBBBBBB',
  '....BBB....',
  '.....B.....',
]);

/** Handing off: violet bubble with a sheet. */
export const HANDOFF_BUBBLE = sprite({ B: BORDER, F: '#b98cff', H: '#ffffff', G: '#9a9aae' }, [
  'BBBBBBBBBBB',
  'BFFFFFFFFFB',
  'BFFHHHHFFFB',
  'BFFHGGHHFFB',
  'BFFHHHHHFFB',
  'BFFHGGGHFFB',
  'BFFHHHHHFFB',
  'BFFFFFFFFFB',
  'BBBBBBBBBBB',
  '....BBB....',
  '.....B.....',
]);

/** The owner's new request: gold speech bubble with text lines (the owner's color). */
export const PROMPT_BUBBLE = sprite({ B: BORDER, F: '#e0b050', T: '#2a2030', L: '#f3d58a' }, [
  'BBBBBBBBBBB',
  'BLLFFFFFFFB',
  'BLTTTTTTFFB',
  'BFFFFFFFFFB',
  'BFTTTTTTTFB',
  'BFFFFFFFFFB',
  'BFTTTTFFFFB',
  'BFFFFFFFFFB',
  'BBBBBBBBBBB',
  '..BBB......',
  '..B........',
]);

/** Thinking: bubble with three dots (no open tool, the model is reasoning). */
export const THINK_BUBBLE = sprite({ B: BORDER, F: '#e8eefa', P: '#5a78a8' }, [
  '.BBBBBBBBB.',
  'BFFFFFFFFFB',
  'BFFFFFFFFFB',
  'BFPFFPFFPFB',
  'BFFFFFFFFFB',
  '.BBBBBBBBB.',
  '..BB.......',
  '.B.........',
]);

/** Idle: tiny "z". */
export const ZZZ = sprite({ Z: '#c8c8e0' }, [
  '.....ZZZZ',
  '.......Z.',
  'ZZZ...Z..',
  '..Z..ZZZZ',
  '.Z.......',
  'ZZZ......',
]);

/** The lenses' magnifier. */
export const MAGNIFIER = sprite({ M: '#3a3a4a', V: '#bfe6ff', W: '#ffffff', C: '#8a5a2b' }, [
  '.MMMM...',
  'MVWVVM..',
  'MWVVVM..',
  'MVVVVM..',
  'MVVVVM..',
  '.MMMMC..',
  '.....CC.',
  '......CC',
]);

/** Mailbox (Discord notices). Lit: yellow envelope. */
export const MAILBOX = sprite({ R: '#c0392b', D: '#7b241c', S: '#ffffff', P: '#555566' }, [
  '.RRRRRR.',
  'RRRRRRRR',
  'RSSSSSSR',
  'RSDSSDSR',
  'RSSDDSSR',
  'RRRRRRRR',
  '...PP...',
  '...PP...',
]);
export const MAILBOX_LIT = sprite({ R: '#ff6b5a', D: '#c0392b', S: '#fff3a0', P: '#555566' }, [
  '.RRRRRR.',
  'RRRRRRRR',
  'RSSSSSSR',
  'RSDSSDSR',
  'RSSDDSSR',
  'RRRRRRRR',
  '...PP...',
  '...PP...',
]);

/** The owner's tray. */
export const TRAY = sprite({ M: '#8a5a2b', L: '#c08850', H: '#ffffff', G: '#d8d8e8' }, [
  '..HHHH..',
  '.HGGGGH.',
  'MHHHHHHM',
  'MLLLLLLM',
  '.MMMMMM.',
]);

/** Google icon: work outside the area in Drive, Docs or Slides (the profile's external_work). */
export const GOOGLE = sprite({ B: '#4285f4', R: '#ea4335', Y: '#fbbc05', G: '#34a853' }, [
  '..RRRR..',
  '.R....R.',
  'Y.......',
  'Y...BBBB',
  'Y......B',
  '.G....B.',
  '..GGGG..',
]);

/** Skill: star. */
export const STAR = sprite({ Y: '#ffd84a', O: '#c99a00' }, ['...Y...', '..YYY..', 'YYYYYYY', '.OYYYO.', '.YY.YY.', 'Y.....Y']);

/** Main agent check (the profile's scripts.checks): tick. */
export const TICK = sprite({ G: '#8fd48a', D: '#3d7a3a' }, ['......G', '.....GD', 'G...GD.', 'DG.GD..', '.DGD...', '..D....']);
