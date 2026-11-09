// Build de la oficina. Compila src/idi/ a web/dist, que sirve el servidor Python.
//
// Los assets se decodifican en build a JSON (assets/decoded/*.json): el navegador no decodifica PNG
// y en uso diario no corre Node. Los personajes salen de .build/ (sprites.mjs: variantes + avatar).
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import * as fs from 'fs';
import * as path from 'path';
import type { Plugin } from 'vite';
import { defineConfig } from 'vite';

import { buildFurnitureCatalog } from '../core/src/assets/build.ts';
import {
  decodeAllCharacters,
  decodeAllFloors,
  decodeAllFurniture,
  decodeAllWalls,
} from '../core/src/assets/loader.ts';

const ASSETS = path.resolve(import.meta.dirname, 'public/assets');
const GENERADOS = path.resolve(import.meta.dirname, '../.build/assets');
const SALIDA = path.resolve(import.meta.dirname, '../../dist');

function decodificados(): Record<string, unknown> {
  const catalogo = buildFurnitureCatalog(ASSETS);
  return {
    'characters.json': decodeAllCharacters(GENERADOS),
    'floors.json': decodeAllFloors(ASSETS),
    'walls.json': decodeAllWalls(ASSETS),
    'furniture-catalog.json': catalogo,
    'furniture.json': decodeAllFurniture(ASSETS, catalogo),
    'personajes.json': JSON.parse(fs.readFileSync(path.join(GENERADOS, 'personajes.json'), 'utf8')),
  };
}

function assetsDecodificados(): Plugin {
  let cache: Record<string, unknown> | null = null;
  return {
    name: 'idi-assets-decodificados',
    configureServer(server) {
      server.middlewares.use('/assets/decoded/', (req, res, next) => {
        cache ??= decodificados();
        const nombre = (req.url ?? '').replace(/^\//, '').split('?')[0];
        if (!(nombre in cache)) return next();
        res.setHeader('Content-Type', 'application/json');
        res.end(JSON.stringify(cache[nombre]));
      });
    },
    closeBundle() {
      // La entrada se llama idi.html para no pisar el index.html de upstream; el servidor sirve index.html
      const html = path.join(SALIDA, 'idi.html');
      if (fs.existsSync(html)) fs.renameSync(html, path.join(SALIDA, 'index.html'));
      const destino = path.join(SALIDA, 'assets', 'decoded');
      fs.mkdirSync(destino, { recursive: true });
      for (const [nombre, datos] of Object.entries(decodificados())) {
        fs.writeFileSync(path.join(destino, nombre), JSON.stringify(datos));
      }
    },
  };
}

/** Redirige el transporte de upstream (WebSocket / VS Code) a uno nulo: ver src/idi/transporte.ts. */
function transporteNulo(): Plugin {
  const original = path.resolve(import.meta.dirname, 'src/transport/index');
  const propio = path.resolve(import.meta.dirname, 'src/idi/transporte.ts');
  return {
    name: 'idi-transporte-nulo',
    enforce: 'pre',
    async resolveId(fuente, importador) {
      if (!importador || !fuente.includes('transport/index')) return null;
      const resuelto = path.resolve(path.dirname(importador), fuente).replace(/\.(js|ts)$/, '');
      return resuelto === original ? propio : null;
    },
  };
}

export default defineConfig({
  root: import.meta.dirname,
  publicDir: path.resolve(import.meta.dirname, 'public-idi'),
  plugins: [transporteNulo(), tailwindcss(), react(), assetsDecodificados()],
  server: {
    // En desarrollo, la API la sirve el servidor Python (py -3 -m servidor)
    proxy: { '/api': { target: 'http://127.0.0.1:8765', changeOrigin: true } },
  },
  build: {
    outDir: SALIDA,
    emptyOutDir: true,
    rollupOptions: { input: path.resolve(import.meta.dirname, 'idi.html') },
  },
  base: './',
});
