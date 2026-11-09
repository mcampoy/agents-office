// URLs de la API con el proyecto elegido. El proyecto va en la URL de la página (?p=<id>), así cada pestaña
// del navegador queda fija en un proyecto y se puede guardar como favorito.

let proyecto: string | null = new URLSearchParams(window.location.search).get('p');

export interface ProyectoListado {
  id: string;
  nombre: string;
  ultimo_evento: string | null;
  activos: number;
}

export function proyectoActual(): string | null {
  return proyecto;
}

/** Ruta de la API con ?proyecto= (o &proyecto=) si hay uno elegido. */
export function api(ruta: string): string {
  if (!proyecto) return `./api/${ruta}`;
  return `./api/${ruta}${ruta.includes('?') ? '&' : '?'}proyecto=${encodeURIComponent(proyecto)}`;
}

/** Lista de proyectos. Si la URL no elige ninguno, fija el de actividad más reciente (el primero). */
export async function cargarProyectos(): Promise<ProyectoListado[]> {
  try {
    const r = await fetch('./api/proyectos', { cache: 'no-store' });
    const lista = ((await r.json()) as { proyectos: ProyectoListado[] }).proyectos ?? [];
    if (!proyecto && lista.length > 0) proyecto = lista[0].id;
    return lista;
  } catch {
    return [];
  }
}

/** Cambia de proyecto recargando la página con ?p=<id> (todo el estado del piso es por proyecto). */
export function irAProyecto(id: string): void {
  const url = new URL(window.location.href);
  url.searchParams.set('p', id);
  window.location.href = url.toString();
}
