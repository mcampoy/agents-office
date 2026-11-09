// Genera las hojas de personajes de la oficina a partir de los sprites base de Pixel Agents.
//
// Corre solo en build (`npm run build` en web/pixel-agents). En uso diario no hace falta Node.
//
// Salida (web/pixel-agents/.build/assets/characters/):
//   char_0..5    los seis sprites base, sin cambios
//   char_6..23   variantes de ropa: recolor por máscara de paleta (decisión 7). Solo cambian los colores
//                de la ropa listados en ROPA; piel, pelo y ojos quedan intactos
//   char_24      avatar del responsable, derivado de char_4 por capas (pelo, anteojos, barba, infinito,
//                zapatillas). Ver docs/avatar.md
//   personajes.json  qué índice es cada cosa
//
// Formato de cada hoja: 112×96, cuadros de 16×32, 7 por fila (walk ×3, type ×2, read ×2),
// filas: abajo, arriba, derecha (la izquierda es la derecha espejada).
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import pngjs from 'pngjs';

const { PNG } = pngjs;
const AQUI = path.dirname(fileURLToPath(import.meta.url));
const BASE = path.resolve(AQUI, '../webview-ui/public/assets/characters');
const SALIDA = path.resolve(AQUI, '../.build/assets/characters');

const W = 16;
const H = 32;
const CUADROS = 7;
const DIRS = ['abajo', 'arriba', 'derecha'];

// --- Colores ------------------------------------------------------------------------------

const hex = (r, g, b) => '#' + [r, g, b].map((v) => v.toString(16).padStart(2, '0')).join('');
const rgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const luz = (h) => {
  const [r, g, b] = rgb(h);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};

function hslAHex(h, s, l) {
  const k = (n) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n) => Math.round(255 * (l - a * Math.max(-1, Math.min(k(n) - 3, 9 - k(n), 1))));
  return hex(f(0), f(8), f(4));
}

// Colores de ropa de cada sprite base (máscara de paleta). Leídos del cuadro 0 de cada hoja.
// Si la ropa comparte paleta con el pantalón (char_0), cambia el conjunto entero.
const ROPA = {
  0: ['#071c2e', '#0f406a', '#114978', '#1164a9'],
  1: ['#101010', '#1a1a1a', '#252525', '#2b2b2b'],
  2: ['#56110e', '#741713', '#8b1a16', '#a91d18', '#e87218', '#e8741b', '#f67d20'],
  3: ['#bdbdbd', '#d4d4d4', '#eeeeee'],
  4: ['#bdbdbd', '#d4d4d4', '#eeeeee'],
  5: ['#640026', '#9f3f31', '#b24737', '#e16451'],
};

// Tonos de las variantes (matiz en grados, saturación). Tres por sprite base, lejos de su color original.
const TONOS = {
  verde: [140, 0.45],
  violeta: [270, 0.45],
  mostaza: [42, 0.6],
  turquesa: [180, 0.5],
  rosa: [335, 0.5],
  azul: [218, 0.55],
};
const VARIANTES = {
  0: ['verde', 'mostaza', 'rosa'],
  1: ['turquesa', 'violeta', 'mostaza'],
  2: ['azul', 'verde', 'violeta'],
  3: ['verde', 'violeta', 'rosa'],
  4: ['azul', 'mostaza', 'turquesa'],
  5: ['azul', 'verde', 'mostaza'],
};

// --- Hojas ------------------------------------------------------------------------------

function leer(i) {
  return PNG.sync.read(fs.readFileSync(path.join(BASE, `char_${i}.png`)));
}

function copiar(png) {
  const otro = new PNG({ width: png.width, height: png.height });
  png.data.copy(otro.data);
  return otro;
}

function color(png, x, y) {
  const k = (y * png.width + x) * 4;
  if (png.data[k + 3] < 2) return null;
  return hex(png.data[k], png.data[k + 1], png.data[k + 2]);
}

function pintar(png, x, y, h) {
  const k = (y * png.width + x) * 4;
  const [r, g, b] = rgb(h);
  png.data[k] = r;
  png.data[k + 1] = g;
  png.data[k + 2] = b;
  png.data[k + 3] = 255;
}

/** Reemplaza colores exactos en toda la hoja, opcionalmente solo en un rango de filas locales del cuadro. */
function reemplazar(png, mapa, filaDesde = 0, filaHasta = H - 1) {
  for (let y = 0; y < png.height; y++) {
    const local = y % H;
    if (local < filaDesde || local > filaHasta) continue;
    for (let x = 0; x < png.width; x++) {
      const c = color(png, x, y);
      if (c && mapa[c]) pintar(png, x, y, mapa[c]);
    }
  }
}

/** Mapa de recolor: los colores de la máscara, ordenados por luz, pasan a una rampa del tono elegido. */
function rampa(colores, [matiz, sat]) {
  const orden = [...colores].sort((a, b) => luz(a) - luz(b));
  const mapa = {};
  orden.forEach((c, i) => {
    const t = orden.length === 1 ? 0.5 : i / (orden.length - 1);
    mapa[c] = hslAHex(matiz, sat, 0.24 + t * 0.44);
  });
  return mapa;
}

// --- Avatar del responsable -------------------------------------------------------------

const AV = {
  // Pelo castaño oscuro: se oscurece la paleta de pelo de char_4
  pelo: {
    '#2f160f': '#1e100b',
    '#432415': '#2c180f',
    '#442414': '#2c180f',
    '#421b19': '#2a1610',
    '#57351a': '#3d2416',
    '#69451b': '#553420',
  },
  anteojos: '#151515',
  barba: '#3a2317',
  barbaLuz: '#4a2e1e',
  infinitoA: '#2f6fd6',
  infinitoB: '#22c1b4',
  infinitoC: '#3aa0d8',
  // Zapatillas blancas (solo filas de los pies, para no tocar el brillo de los ojos)
  zapatillas: { '#353535': '#e6e6e6', '#595959': '#ffffff', '#1a1a1a': '#9a9a9a' },
};

const PIEL = new Set(['#e9a384', '#c5896e', '#e29878', '#fbbf97', '#ffd8b2', '#bd8068']);
const NEGRO = '#000000';
const REMERA = new Set(['#eeeeee', '#d4d4d4', '#bdbdbd']);

/** Fila de los ojos en un cuadro mirando abajo: primera fila con negro en las columnas 5 y 10. */
function filaOjosAbajo(png, ox, oy) {
  for (let y = 6; y < 26; y++) {
    if (color(png, ox + 5, oy + y) === NEGRO && color(png, ox + 10, oy + y) === NEGRO) return y;
  }
  return null;
}

/** Ojo en un cuadro mirando a la derecha: primer par negro horizontal en la mitad derecha de la cabeza. */
function ojoDerecha(png, ox, oy) {
  for (let y = 8; y < 24; y++) {
    for (let x = 9; x < 14; x++) {
      if (color(png, ox + x, oy + y) === NEGRO && color(png, ox + x + 1, oy + y) === NEGRO) return { x, y };
    }
  }
  return null;
}

function filaRemera(png, ox, oy, desde) {
  for (let y = desde; y < H; y++) {
    for (let x = 0; x < W; x++) if (REMERA.has(color(png, ox + x, oy + y))) return y;
  }
  return null;
}

function barbaEn(png, ox, oy, filas, columnas) {
  for (const y of filas) {
    for (const x of columnas) {
      const c = color(png, ox + x, oy + y);
      if (c && PIEL.has(c)) pintar(png, ox + x, oy + y, (x + y) % 3 === 0 ? AV.barbaLuz : AV.barba);
    }
  }
}

function avatar() {
  const png = copiar(leer(4));
  reemplazar(png, AV.pelo);
  reemplazar(png, AV.zapatillas, 24, 31);
  for (let f = 0; f < CUADROS; f++) {
    // Abajo
    {
      const ox = f * W;
      const oy = 0;
      const r = filaOjosAbajo(png, ox, oy);
      if (r !== null) {
        const yaTiene = color(png, ox + 4, oy + r) === NEGRO && color(png, ox + 11, oy + r) === NEGRO;
        if (!yaTiene) {
          // Marco: borde superior sobre los ojos (columnas 4, 7, 8 y 11, entre los ojos negros) y
          // patillas laterales. La fila de la frente queda con piel, para que no se funda con el pelo
          for (const x of [4, 7, 8, 11]) pintar(png, ox + x, oy + r, AV.anteojos);
          for (const x of [3, 12]) {
            if (color(png, ox + x, oy + r) !== null) pintar(png, ox + x, oy + r, AV.anteojos);
          }
        }
        // Barba: mandíbula (la fila de piel más baja de la cara) y patillas a los costados
        barbaEn(png, ox, oy, [r + 3], [4, 5, 6, 7, 8, 9, 10, 11]);
        barbaEn(png, ox, oy, [r + 2], [3, 4, 11, 12]);
        // Infinito en el pecho (5×3), solo si la remera está a la vista (no en lectura, que tapa con la hoja)
        const t = filaRemera(png, ox, oy, r + 3);
        if (t !== null && f < 5) {
          const y0 = t + 2;
          const forma = [
            [0, 1, 'A'], [0, 3, 'B'],
            [1, 0, 'A'], [1, 2, 'C'], [1, 4, 'B'],
            [2, 1, 'A'], [2, 3, 'B'],
          ];
          for (const [dy, dx, k] of forma) {
            const x = ox + 5 + dx;
            const y = oy + y0 + dy;
            if (REMERA.has(color(png, x, y))) pintar(png, x, y, AV[`infinito${k}`]);
          }
        }
      }
    }
    // Derecha (la izquierda se espeja en el renderer)
    {
      const ox = f * W;
      const oy = 2 * H;
      const ojo = ojoDerecha(png, ox, oy);
      if (ojo) {
        const yaTiene = color(png, ox + ojo.x - 1, oy + ojo.y) === NEGRO;
        if (!yaTiene) {
          for (let x = ojo.x - 1; x <= ojo.x + 2; x++) pintar(png, ox + x, oy + ojo.y - 1, AV.anteojos);
          pintar(png, ox + ojo.x - 1, oy + ojo.y, AV.anteojos);
          // Patilla de los anteojos hacia la oreja, sobre la piel de la sien
          for (let x = ojo.x - 4; x < ojo.x - 1; x++) {
            const c = color(png, ox + x, oy + ojo.y);
            if (c && PIEL.has(c)) pintar(png, ox + x, oy + ojo.y, AV.anteojos);
          }
        }
        const cols = Array.from({ length: 9 }, (_, i) => ojo.x - 6 + i);
        barbaEn(png, ox, oy, [ojo.y + 3, ojo.y + 4], cols);
        barbaEn(png, ox, oy, [ojo.y + 1, ojo.y + 2], [ojo.x - 4, ojo.x - 3]);
      }
    }
  }
  return png;
}

// --- Vista previa ampliada (para revisar y documentar) -----------------------------------

function vistaPrevia(hojas, escala = 4) {
  const ancho = 112 * escala;
  const alto = 96 * escala;
  const png = new PNG({ width: ancho, height: alto * hojas.length });
  hojas.forEach((h, i) => {
    for (let y = 0; y < 96; y++) {
      for (let x = 0; x < 112; x++) {
        const c = color(h, x, y);
        const fondo = ((x >> 4) + (y >> 5)) % 2 ? '#c8d8c8' : '#dce8dc';
        for (let dy = 0; dy < escala; dy++) {
          for (let dx = 0; dx < escala; dx++) pintar(png, x * escala + dx, i * alto + y * escala + dy, c ?? fondo);
        }
      }
    }
  });
  return png;
}

// --- Principal ------------------------------------------------------------------------------

function main() {
  fs.mkdirSync(SALIDA, { recursive: true });
  for (const f of fs.readdirSync(SALIDA)) fs.rmSync(path.join(SALIDA, f));
  const hojas = [];
  const personajes = [];
  for (let i = 0; i < 6; i++) {
    hojas.push(leer(i));
    personajes.push({ indice: i, base: i, variante: 'original' });
  }
  for (let i = 0; i < 6; i++) {
    for (const tono of VARIANTES[i]) {
      const png = copiar(leer(i));
      reemplazar(png, rampa(ROPA[i], TONOS[tono]));
      personajes.push({ indice: hojas.length, base: i, variante: tono });
      hojas.push(png);
    }
  }
  const indiceAvatar = hojas.length;
  hojas.push(avatar());
  personajes.push({ indice: indiceAvatar, base: 4, variante: 'avatar del responsable' });

  hojas.forEach((png, i) => fs.writeFileSync(path.join(SALIDA, `char_${i}.png`), PNG.sync.write(png)));
  const meta = {
    generado_por: 'web/pixel-agents/idi/sprites.mjs',
    avatar: indiceAvatar,
    // Pool para asignar a agentes: todo menos el avatar y char_4 original, que se le parece demasiado
    asignables: personajes.filter((p) => p.indice !== indiceAvatar && p.indice !== 4).map((p) => p.indice),
    personajes,
  };
  fs.writeFileSync(path.join(SALIDA, '..', 'personajes.json'), JSON.stringify(meta, null, 2));
  fs.writeFileSync(path.join(SALIDA, '..', '..', 'vista-avatar.png'), PNG.sync.write(vistaPrevia([leer(4), hojas[indiceAvatar]], 6)));
  fs.writeFileSync(path.join(SALIDA, '..', '..', 'vista-variantes.png'), PNG.sync.write(vistaPrevia(hojas.slice(0, indiceAvatar), 2)));
  console.log(`[sprites] ${hojas.length} hojas en ${SALIDA} (avatar = char_${indiceAvatar})`);
}

main();
