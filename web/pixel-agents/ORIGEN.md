# Origen

Copia de `pixel-agents-hq/pixel-agents`, commit `b1bafd0` (v1.5.0, 16/10/2026), licencia MIT (ver `LICENSE`).

- `core/` y `webview-ui/` se copiaron sin cambios. Se dejaron afuera `node_modules`, `test/`, `e2e/`, la extensión de VS Code y la fuente `webview-ui/public/fonts/FSPixelSansUnicode-Regular.ttf`, cuya procedencia no está documentada (se usa VT323, ver `webview-ui/public-idi/fonts/`).
- El código propio de la oficina vive en:
  - `webview-ui/src/idi/`: la app (cabecera, piso, tarjetas), el reconciliador foto → `OfficeState` y el transporte propio.
  - `webview-ui/idi.html`, `webview-ui/vite.idi.config.ts` y `webview-ui/tsconfig.idi.json`: la entrada y el build.
  - `webview-ui/public-idi/`: la fuente VT323 (OFL), en lugar de `public/fonts/FSPixelSansUnicode-Regular.ttf`, que no se distribuye.
  - `idi/sprites.mjs`: las variantes de ropa y el avatar (ver `docs/avatar.md`).
- Los archivos de upstream no se tocan, salvo los que lista la sección "Cambios" de abajo.
- `src/transport/index.ts` de upstream no entra en el build: un plugin de Vite lo reemplaza por `src/idi/transporte.ts`, sin WebSocket, que solo atiende el guardado del layout del editor.
- El build (`npm run build`) escribe en `web/dist`, que es lo que sirve el servidor Python.
- Para actualizar: volver a copiar desde un commit nuevo, revisar `src/idi/` contra las APIs que usa (`OfficeState`, `OfficeCanvas`, sprites) y actualizar el commit fijado en este archivo.

## Cambios sobre upstream

Ninguno por ahora.
