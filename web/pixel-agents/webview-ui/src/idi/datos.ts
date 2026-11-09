// Carga de assets (JSON decodificados en build), layout y config, y suscripción a la foto por SSE.
import { useEffect, useState } from 'react';

import type { CatalogEntry, CharacterDirectionSprites } from '../../../core/src/assets/types.ts';
import { setFloorSprites } from '../office/floorTiles.js';
import type { LoadedAssetData } from '../office/layout/furnitureCatalog.js';
import { buildDynamicCatalog } from '../office/layout/furnitureCatalog.js';
import { migrateLayoutColors } from '../office/layout/layoutSerializer.js';
import { setCharacterTemplates } from '../office/sprites/spriteData.js';
import type { OfficeLayout } from '../office/types.js';
import { setWallSprites } from '../office/wallTiles.js';
import { fijarPerfil, type PerfilWeb } from './perfil.ts';
import type { ConfigSprites, Foto, Personajes } from './tipos.ts';

async function json<T>(url: string): Promise<T> {
  const r = await fetch(url, { cache: 'no-store' });
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return (await r.json()) as T;
}

export interface Recursos {
  layout: OfficeLayout;
  /** Catálogo y sprites de muebles, para la paleta del editor del piso. */
  muebles: LoadedAssetData;
  personajes: Personajes;
  sprites: ConfigSprites;
}

/** Carga sprites, muebles, layout y config. Registra los sprites en los módulos del motor. */
export async function cargarRecursos(): Promise<Recursos> {
  const base = './assets/decoded/';
  const [characters, floors, walls, catalog, furniture, personajes, layout, sprites, perfil] = await Promise.all([
    json<CharacterDirectionSprites[]>(`${base}characters.json`),
    json<string[][][]>(`${base}floors.json`),
    json<string[][][][]>(`${base}walls.json`),
    json<CatalogEntry[]>(`${base}furniture-catalog.json`),
    json<Record<string, string[][]>>(`${base}furniture.json`),
    json<Personajes>(`${base}personajes.json`),
    json<OfficeLayout>('./api/layout'),
    json<ConfigSprites>('./api/sprites').catch(() => ({}) as ConfigSprites),
    json<PerfilWeb>('./api/perfil').catch(() => null),
  ]);
  fijarPerfil(perfil);
  setCharacterTemplates(characters);
  setFloorSprites(floors);
  setWallSprites(walls);
  const muebles = { catalog, sprites: furniture } as unknown as LoadedAssetData;
  buildDynamicCatalog(muebles);
  return { layout: migrateLayoutColors(layout), muebles, personajes, sprites };
}

export type Conexion = 'conectando' | 'en vivo' | 'sin conexión';

/** Foto en vivo: primero /api/estado, después cada evento `estado` del stream. EventSource reconecta solo. */
export function useFoto(): { foto: Foto | null; conexion: Conexion } {
  const [foto, setFoto] = useState<Foto | null>(null);
  const [conexion, setConexion] = useState<Conexion>('conectando');
  useEffect(() => {
    let vivo = true;
    json<Foto>('./api/estado')
      .then((f) => vivo && f && setFoto(f))
      .catch(() => undefined);
    const es = new EventSource('./api/stream');
    es.addEventListener('estado', (ev) => {
      try {
        setFoto(JSON.parse((ev as MessageEvent<string>).data) as Foto);
        setConexion('en vivo');
      } catch {
        /* una foto mal formada no rompe la vista */
      }
    });
    es.onopen = () => setConexion('en vivo');
    es.onerror = () => setConexion('sin conexión');
    return () => {
      vivo = false;
      es.close();
    };
  }, []);
  return { foto, conexion };
}
