import './idi.css';

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { cargarRecursos } from './datos.ts';
import { Oficina } from './Oficina.tsx';

const raiz = createRoot(document.getElementById('root')!);

cargarRecursos()
  .then((recursos) =>
    raiz.render(
      <StrictMode>
        <Oficina recursos={recursos} />
      </StrictMode>,
    ),
  )
  .catch((error: unknown) => {
    console.error(error);
    raiz.render(
      <div className="p-24">
        <h1>No se pudo cargar la oficina</h1>
        <p className="idi-tenue">{String(error)}</p>
        <p className="idi-tenue">¿Está corriendo el servidor (py -3 -m servidor) y existe config/layout.json?</p>
      </div>,
    );
  });
