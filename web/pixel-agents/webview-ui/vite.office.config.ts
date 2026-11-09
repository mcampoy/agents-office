// Office build. Compiles src/app/ to web/dist, which the Python server serves.
//
// Assets are decoded at build time to JSON (assets/decoded/*.json): the browser does not decode PNG
// and daily use does not run Node. The characters come from .build/ (tools/sprites.mjs: variants + avatar).
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
const GENERATED = path.resolve(import.meta.dirname, '../.build/assets');
const OUTPUT = path.resolve(import.meta.dirname, '../../dist');

function decoded(): Record<string, unknown> {
  const catalog = buildFurnitureCatalog(ASSETS);
  return {
    'characters.json': decodeAllCharacters(GENERATED),
    'floors.json': decodeAllFloors(ASSETS),
    'walls.json': decodeAllWalls(ASSETS),
    'furniture-catalog.json': catalog,
    'furniture.json': decodeAllFurniture(ASSETS, catalog),
    'cast.json': JSON.parse(fs.readFileSync(path.join(GENERATED, 'cast.json'), 'utf8')),
  };
}

function decodedAssets(): Plugin {
  let cache: Record<string, unknown> | null = null;
  return {
    name: 'office-decoded-assets',
    configureServer(server) {
      server.middlewares.use('/assets/decoded/', (req, res, next) => {
        cache ??= decoded();
        const name = (req.url ?? '').replace(/^\//, '').split('?')[0];
        if (!(name in cache)) return next();
        res.setHeader('Content-Type', 'application/json');
        res.end(JSON.stringify(cache[name]));
      });
    },
    closeBundle() {
      // The entry is office.html so it does not clash with upstream's index.html; the server serves index.html
      const html = path.join(OUTPUT, 'office.html');
      if (fs.existsSync(html)) fs.renameSync(html, path.join(OUTPUT, 'index.html'));
      const target = path.join(OUTPUT, 'assets', 'decoded');
      fs.mkdirSync(target, { recursive: true });
      for (const [name, data] of Object.entries(decoded())) {
        fs.writeFileSync(path.join(target, name), JSON.stringify(data));
      }
    },
  };
}

/** Redirects upstream's transport (WebSocket / VS Code) to a null one: see src/app/transport.ts. */
function nullTransport(): Plugin {
  const original = path.resolve(import.meta.dirname, 'src/transport/index');
  const ours = path.resolve(import.meta.dirname, 'src/app/transport.ts');
  return {
    name: 'office-null-transport',
    enforce: 'pre',
    async resolveId(source, importer) {
      if (!importer || !source.includes('transport/index')) return null;
      const resolved = path.resolve(path.dirname(importer), source).replace(/\.(js|ts)$/, '');
      return resolved === original ? ours : null;
    },
  };
}

export default defineConfig({
  root: import.meta.dirname,
  publicDir: path.resolve(import.meta.dirname, 'public-app'),
  plugins: [nullTransport(), tailwindcss(), react(), decodedAssets()],
  server: {
    // In development, the API is served by the Python server (py -3 -m server)
    proxy: { '/api': { target: 'http://127.0.0.1:8765', changeOrigin: true } },
  },
  build: {
    outDir: OUTPUT,
    emptyOutDir: true,
    rollupOptions: { input: path.resolve(import.meta.dirname, 'office.html') },
  },
  base: './',
});
