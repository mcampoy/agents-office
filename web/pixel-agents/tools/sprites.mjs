// Generates the office character sheets from the Pixel Agents base sprites.
//
// Runs only at build time (`npm run build` in web/pixel-agents). Daily use does not need Node.
//
// Output (web/pixel-agents/.build/assets/characters/):
//   char_0..5    the six base sprites, unchanged
//   char_6..23   clothing variants: recolor by palette mask. Only the clothing colors listed in CLOTHES
//                change; skin, hair and eyes stay intact
//   char_24      the owner's avatar, derived from char_4 by layers (hair, glasses, beard, infinity,
//                sneakers). See docs/avatar.md
//   cast.json    which index is what
//
// Format of each sheet: 112×96, 16×32 frames, 7 per row (walk ×3, type ×2, read ×2),
// rows: down, up, right (left is right mirrored).
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import pngjs from 'pngjs';

const { PNG } = pngjs;
const HERE = path.dirname(fileURLToPath(import.meta.url));
const BASE = path.resolve(HERE, '../webview-ui/public/assets/characters');
const OUTPUT = path.resolve(HERE, '../.build/assets/characters');

const W = 16;
const H = 32;
const FRAMES = 7;

// --- Colors ---------------------------------------------------------------------------------

const hex = (r, g, b) => '#' + [r, g, b].map((v) => v.toString(16).padStart(2, '0')).join('');
const rgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const lightness = (h) => {
  const [r, g, b] = rgb(h);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};

function hslToHex(h, s, l) {
  const k = (n) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n) => Math.round(255 * (l - a * Math.max(-1, Math.min(k(n) - 3, 9 - k(n), 1))));
  return hex(f(0), f(8), f(4));
}

// Clothing colors of each base sprite (palette mask). Read from frame 0 of each sheet.
// If the clothes share the palette with the trousers (char_0), the whole outfit changes.
const CLOTHES = {
  0: ['#071c2e', '#0f406a', '#114978', '#1164a9'],
  1: ['#101010', '#1a1a1a', '#252525', '#2b2b2b'],
  2: ['#56110e', '#741713', '#8b1a16', '#a91d18', '#e87218', '#e8741b', '#f67d20'],
  3: ['#bdbdbd', '#d4d4d4', '#eeeeee'],
  4: ['#bdbdbd', '#d4d4d4', '#eeeeee'],
  5: ['#640026', '#9f3f31', '#b24737', '#e16451'],
};

// Variant tones (hue in degrees, saturation). Three per base sprite, far from its original color.
const TONES = {
  green: [140, 0.45],
  violet: [270, 0.45],
  mustard: [42, 0.6],
  turquoise: [180, 0.5],
  pink: [335, 0.5],
  blue: [218, 0.55],
};
const VARIANTS = {
  0: ['green', 'mustard', 'pink'],
  1: ['turquoise', 'violet', 'mustard'],
  2: ['blue', 'green', 'violet'],
  3: ['green', 'violet', 'pink'],
  4: ['blue', 'mustard', 'turquoise'],
  5: ['blue', 'green', 'mustard'],
};

// --- Sheets ---------------------------------------------------------------------------------

function read(i) {
  return PNG.sync.read(fs.readFileSync(path.join(BASE, `char_${i}.png`)));
}

function copy(png) {
  const other = new PNG({ width: png.width, height: png.height });
  png.data.copy(other.data);
  return other;
}

function color(png, x, y) {
  const k = (y * png.width + x) * 4;
  if (png.data[k + 3] < 2) return null;
  return hex(png.data[k], png.data[k + 1], png.data[k + 2]);
}

function paint(png, x, y, h) {
  const k = (y * png.width + x) * 4;
  const [r, g, b] = rgb(h);
  png.data[k] = r;
  png.data[k + 1] = g;
  png.data[k + 2] = b;
  png.data[k + 3] = 255;
}

/** Replaces exact colors in the whole sheet, optionally only in a range of the frame's local rows. */
function replace(png, map, rowFrom = 0, rowTo = H - 1) {
  for (let y = 0; y < png.height; y++) {
    const local = y % H;
    if (local < rowFrom || local > rowTo) continue;
    for (let x = 0; x < png.width; x++) {
      const c = color(png, x, y);
      if (c && map[c]) paint(png, x, y, map[c]);
    }
  }
}

/** Recolor map: the mask colors, sorted by lightness, move to a ramp of the chosen tone. */
function ramp(colors, [hue, sat]) {
  const order = [...colors].sort((a, b) => lightness(a) - lightness(b));
  const map = {};
  order.forEach((c, i) => {
    const t = order.length === 1 ? 0.5 : i / (order.length - 1);
    map[c] = hslToHex(hue, sat, 0.24 + t * 0.44);
  });
  return map;
}

// --- Owner's avatar -------------------------------------------------------------------------

const AV = {
  // Dark brown hair: char_4's hair palette gets darker
  hair: {
    '#2f160f': '#1e100b',
    '#432415': '#2c180f',
    '#442414': '#2c180f',
    '#421b19': '#2a1610',
    '#57351a': '#3d2416',
    '#69451b': '#553420',
  },
  glasses: '#151515',
  beard: '#3a2317',
  beardLight: '#4a2e1e',
  infinityA: '#2f6fd6',
  infinityB: '#22c1b4',
  infinityC: '#3aa0d8',
  // White sneakers (only the feet rows, so the eye highlights are untouched)
  sneakers: { '#353535': '#e6e6e6', '#595959': '#ffffff', '#1a1a1a': '#9a9a9a' },
};

const SKIN = new Set(['#e9a384', '#c5896e', '#e29878', '#fbbf97', '#ffd8b2', '#bd8068']);
const BLACK = '#000000';
const SHIRT = new Set(['#eeeeee', '#d4d4d4', '#bdbdbd']);

/** Eye row in a frame facing down: first row with black in columns 5 and 10. */
function eyeRowDown(png, ox, oy) {
  for (let y = 6; y < 26; y++) {
    if (color(png, ox + 5, oy + y) === BLACK && color(png, ox + 10, oy + y) === BLACK) return y;
  }
  return null;
}

/** Eye in a frame facing right: first horizontal black pair in the right half of the head. */
function eyeRight(png, ox, oy) {
  for (let y = 8; y < 24; y++) {
    for (let x = 9; x < 14; x++) {
      if (color(png, ox + x, oy + y) === BLACK && color(png, ox + x + 1, oy + y) === BLACK) return { x, y };
    }
  }
  return null;
}

function shirtRow(png, ox, oy, from) {
  for (let y = from; y < H; y++) {
    for (let x = 0; x < W; x++) if (SHIRT.has(color(png, ox + x, oy + y))) return y;
  }
  return null;
}

function beardAt(png, ox, oy, rows, columns) {
  for (const y of rows) {
    for (const x of columns) {
      const c = color(png, ox + x, oy + y);
      if (c && SKIN.has(c)) paint(png, ox + x, oy + y, (x + y) % 3 === 0 ? AV.beardLight : AV.beard);
    }
  }
}

function avatar() {
  const png = copy(read(4));
  replace(png, AV.hair);
  replace(png, AV.sneakers, 24, 31);
  for (let f = 0; f < FRAMES; f++) {
    // Down
    {
      const ox = f * W;
      const oy = 0;
      const r = eyeRowDown(png, ox, oy);
      if (r !== null) {
        const already = color(png, ox + 4, oy + r) === BLACK && color(png, ox + 11, oy + r) === BLACK;
        if (!already) {
          // Frame: top edge over the eyes (columns 4, 7, 8 and 11, between the black eyes) and
          // side temples. The forehead row keeps the skin, so it does not merge with the hair
          for (const x of [4, 7, 8, 11]) paint(png, ox + x, oy + r, AV.glasses);
          for (const x of [3, 12]) {
            if (color(png, ox + x, oy + r) !== null) paint(png, ox + x, oy + r, AV.glasses);
          }
        }
        // Beard: jaw (the lowest skin row of the face) and sideburns
        beardAt(png, ox, oy, [r + 3], [4, 5, 6, 7, 8, 9, 10, 11]);
        beardAt(png, ox, oy, [r + 2], [3, 4, 11, 12]);
        // Infinity on the chest (5×3), only if the shirt is visible (not while reading, the sheet covers it)
        const t = shirtRow(png, ox, oy, r + 3);
        if (t !== null && f < 5) {
          const y0 = t + 2;
          const shape = [
            [0, 1, 'A'], [0, 3, 'B'],
            [1, 0, 'A'], [1, 2, 'C'], [1, 4, 'B'],
            [2, 1, 'A'], [2, 3, 'B'],
          ];
          for (const [dy, dx, k] of shape) {
            const x = ox + 5 + dx;
            const y = oy + y0 + dy;
            if (SHIRT.has(color(png, x, y))) paint(png, x, y, AV[`infinity${k}`]);
          }
        }
      }
    }
    // Right (left is mirrored by the renderer)
    {
      const ox = f * W;
      const oy = 2 * H;
      const eye = eyeRight(png, ox, oy);
      if (eye) {
        const already = color(png, ox + eye.x - 1, oy + eye.y) === BLACK;
        if (!already) {
          for (let x = eye.x - 1; x <= eye.x + 2; x++) paint(png, ox + x, oy + eye.y - 1, AV.glasses);
          paint(png, ox + eye.x - 1, oy + eye.y, AV.glasses);
          // Glasses temple towards the ear, over the skin of the temple
          for (let x = eye.x - 4; x < eye.x - 1; x++) {
            const c = color(png, ox + x, oy + eye.y);
            if (c && SKIN.has(c)) paint(png, ox + x, oy + eye.y, AV.glasses);
          }
        }
        const cols = Array.from({ length: 9 }, (_, i) => eye.x - 6 + i);
        beardAt(png, ox, oy, [eye.y + 3, eye.y + 4], cols);
        beardAt(png, ox, oy, [eye.y + 1, eye.y + 2], [eye.x - 4, eye.x - 3]);
      }
    }
  }
  return png;
}

// --- Enlarged preview (to review and document) ----------------------------------------------

function preview(sheets, scale = 4) {
  const width = 112 * scale;
  const height = 96 * scale;
  const png = new PNG({ width, height: height * sheets.length });
  sheets.forEach((h, i) => {
    for (let y = 0; y < 96; y++) {
      for (let x = 0; x < 112; x++) {
        const c = color(h, x, y);
        const background = ((x >> 4) + (y >> 5)) % 2 ? '#c8d8c8' : '#dce8dc';
        for (let dy = 0; dy < scale; dy++) {
          for (let dx = 0; dx < scale; dx++) paint(png, x * scale + dx, i * height + y * scale + dy, c ?? background);
        }
      }
    }
  });
  return png;
}

// --- Main -----------------------------------------------------------------------------------

function main() {
  fs.mkdirSync(OUTPUT, { recursive: true });
  for (const f of fs.readdirSync(OUTPUT)) fs.rmSync(path.join(OUTPUT, f));
  const sheets = [];
  const characters = [];
  for (let i = 0; i < 6; i++) {
    sheets.push(read(i));
    characters.push({ index: i, base: i, variant: 'original' });
  }
  for (let i = 0; i < 6; i++) {
    for (const tone of VARIANTS[i]) {
      const png = copy(read(i));
      replace(png, ramp(CLOTHES[i], TONES[tone]));
      characters.push({ index: sheets.length, base: i, variant: tone });
      sheets.push(png);
    }
  }
  const avatarIndex = sheets.length;
  sheets.push(avatar());
  characters.push({ index: avatarIndex, base: 4, variant: 'owner avatar' });

  sheets.forEach((png, i) => fs.writeFileSync(path.join(OUTPUT, `char_${i}.png`), PNG.sync.write(png)));
  const meta = {
    generated_by: 'web/pixel-agents/tools/sprites.mjs',
    avatar: avatarIndex,
    // Pool to assign to agents: everything but the avatar and the original char_4, which looks too similar
    assignable: characters.filter((p) => p.index !== avatarIndex && p.index !== 4).map((p) => p.index),
    characters,
  };
  fs.writeFileSync(path.join(OUTPUT, '..', 'cast.json'), JSON.stringify(meta, null, 2));
  fs.writeFileSync(path.join(OUTPUT, '..', '..', 'avatar-preview.png'), PNG.sync.write(preview([read(4), sheets[avatarIndex]], 6)));
  fs.writeFileSync(path.join(OUTPUT, '..', '..', 'variants-preview.png'), PNG.sync.write(preview(sheets.slice(0, avatarIndex), 2)));
  console.log(`[sprites] ${sheets.length} sheets in ${OUTPUT} (avatar = char_${avatarIndex})`);
}

main();
