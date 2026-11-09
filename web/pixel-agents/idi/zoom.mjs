// Amplía cuadros sueltos de una hoja para revisar el avatar: node idi/zoom.mjs <hoja.png> <salida.png> f,dir f,dir ...
import fs from 'node:fs';
import pngjs from 'pngjs';
const { PNG } = pngjs;
const [, , entrada, salida, ...cuadros] = process.argv;
const p = PNG.sync.read(fs.readFileSync(entrada));
const S = 14;
const out = new PNG({ width: cuadros.length * 18 * S, height: 34 * S });
cuadros.forEach((c, i) => {
  const [f, d] = c.split(',').map(Number);
  for (let y = 0; y < 32; y++) for (let x = 0; x < 16; x++) {
    const k = ((d * 32 + y) * p.width + f * 16 + x) * 4;
    const a = p.data[k + 3] > 1;
    for (let dy = 0; dy < S; dy++) for (let dx = 0; dx < S; dx++) {
      const o = (((y + 1) * S + dy) * out.width + (i * 18 + 1) * S + x * S + dx) * 4;
      const grid = dx === 0 || dy === 0;
      out.data[o] = a ? p.data[k] : grid ? 190 : 215; out.data[o + 1] = a ? p.data[k + 1] : grid ? 205 : 228; out.data[o + 2] = a ? p.data[k + 2] : grid ? 190 : 215; out.data[o + 3] = 255;
    }
  }
});
fs.writeFileSync(salida, PNG.sync.write(out));
