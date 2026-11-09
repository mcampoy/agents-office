import './app.css';

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { loadResources } from './data.ts';
import { Office } from './Office.tsx';

const root = createRoot(document.getElementById('root')!);

loadResources()
  .then((resources) =>
    root.render(
      <StrictMode>
        <Office resources={resources} />
      </StrictMode>,
    ),
  )
  .catch((error: unknown) => {
    console.error(error);
    root.render(
      <div className="p-24">
        <h1>No se pudo cargar la oficina</h1>
        <p className="ao-muted">{String(error)}</p>
        <p className="ao-muted">¿Está corriendo el servidor (py -3 -m server) y existe el layout.json del perfil?</p>
      </div>,
    );
  });
