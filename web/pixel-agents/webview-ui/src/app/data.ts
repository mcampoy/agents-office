// Loads the assets (JSON decoded at build time), layout and config, and subscribes to the snapshot over SSE.
import { useEffect, useState } from 'react';

import type { CatalogEntry, CharacterDirectionSprites } from '../../../core/src/assets/types.ts';
import { setFloorSprites } from '../office/floorTiles.js';
import type { LoadedAssetData } from '../office/layout/furnitureCatalog.js';
import { buildDynamicCatalog } from '../office/layout/furnitureCatalog.js';
import { migrateLayoutColors } from '../office/layout/layoutSerializer.js';
import { setCharacterTemplates } from '../office/sprites/spriteData.js';
import type { OfficeLayout } from '../office/types.js';
import { setWallSprites } from '../office/wallTiles.js';
import { api, loadProjects, type ProjectListing } from './api.ts';
import { setProfile, type WebProfile } from './profile.ts';
import type { Characters, Snapshot, SpritesConfig } from './types.ts';

async function json<T>(url: string): Promise<T> {
  const r = await fetch(url, { cache: 'no-store' });
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return (await r.json()) as T;
}

export interface Resources {
  layout: OfficeLayout;
  /** Furniture catalog and sprites, for the floor editor palette. */
  furniture: LoadedAssetData;
  characters: Characters;
  sprites: SpritesConfig;
  /** Registered projects (for the header selector). */
  projects: ProjectListing[];
}

/** Loads sprites, furniture, layout and config. Registers the sprites in the engine modules. */
export async function loadResources(): Promise<Resources> {
  const base = './assets/decoded/';
  const projects = await loadProjects();
  const [characterSprites, floors, walls, catalog, furnitureSprites, characters, layout, sprites, profile] = await Promise.all([
    json<CharacterDirectionSprites[]>(`${base}characters.json`),
    json<string[][][]>(`${base}floors.json`),
    json<string[][][][]>(`${base}walls.json`),
    json<CatalogEntry[]>(`${base}furniture-catalog.json`),
    json<Record<string, string[][]>>(`${base}furniture.json`),
    json<Characters>(`${base}cast.json`),
    json<OfficeLayout>(api('layout')),
    json<SpritesConfig>(api('sprites')).catch(() => ({}) as SpritesConfig),
    json<WebProfile>(api('profile')).catch(() => null),
  ]);
  setProfile(profile);
  setCharacterTemplates(characterSprites);
  setFloorSprites(floors);
  setWallSprites(walls);
  const furniture = { catalog, sprites: furnitureSprites } as unknown as LoadedAssetData;
  buildDynamicCatalog(furniture);
  return { layout: migrateLayoutColors(layout), furniture, characters, sprites, projects };
}

/** Connection label, shown as is in the header. */
export type Connection = 'conectando' | 'en vivo' | 'sin conexión';

/** Live snapshot: first /api/state, then every `state` event of the stream. EventSource reconnects by itself. */
export function useSnapshot(): { snapshot: Snapshot | null; connection: Connection } {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [connection, setConnection] = useState<Connection>('conectando');
  useEffect(() => {
    let alive = true;
    json<Snapshot>(api('state'))
      .then((s) => alive && s && setSnapshot(s))
      .catch(() => undefined);
    const es = new EventSource(api('stream'));
    es.addEventListener('state', (ev) => {
      try {
        setSnapshot(JSON.parse((ev as MessageEvent<string>).data) as Snapshot);
        setConnection('en vivo');
      } catch {
        /* a malformed snapshot does not break the view */
      }
    });
    es.onopen = () => setConnection('en vivo');
    es.onerror = () => setConnection('sin conexión');
    return () => {
      alive = false;
      es.close();
    };
  }, []);
  return { snapshot, connection };
}
