// Íconos pixel art propios. Cada uno es una grilla de caracteres con su paleta ('.' = transparente).
import type { SpriteData } from '../office/types.js';

function sprite(paleta: Record<string, string>, filas: string[]): SpriteData {
  return filas.map((f) => [...f].map((c) => (c === '.' ? '' : (paleta[c] ?? ''))));
}

const BORDE = '#2a2030';

/** Espera aprobación: burbuja ámbar llena con "!" (fija, más llamativa que la de upstream). */
export const BURBUJA_ESPERA = sprite({ B: BORDE, F: '#ffc233', T: '#2a2030', L: '#ffe28a' }, [
  'BBBBBBBBBBB',
  'BLLFFFFFFFB',
  'BLFFFTFFFFB',
  'BFFFFTFFFFB',
  'BFFFFTFFFFB',
  'BFFFFTFFFFB',
  'BFFFFFFFFFB',
  'BFFFFTFFFFB',
  'BFFFFFFFFFB',
  'BBBBBBBBBBB',
  '....BBB....',
  '.....B.....',
]);

/** Error: burbuja roja con una cruz blanca. */
export const BURBUJA_ERROR = sprite({ B: BORDE, F: '#e5484d', X: '#ffffff', L: '#ff8a8d' }, [
  'BBBBBBBBBBB',
  'BLLFFFFFFFB',
  'BLXFFFFFXFB',
  'BFFXFFFXFFB',
  'BFFFXFXFFFB',
  'BFFFFXFFFFB',
  'BFFFXFXFFFB',
  'BFFXFFFXFFB',
  'BFXFFFFFXFB',
  'BBBBBBBBBBB',
  '....BBB....',
  '.....B.....',
]);

/** Entregando: burbuja violeta con una hoja. */
export const BURBUJA_ENTREGA = sprite({ B: BORDE, F: '#b98cff', H: '#ffffff', G: '#9a9aae' }, [
  'BBBBBBBBBBB',
  'BFFFFFFFFFB',
  'BFFHHHHFFFB',
  'BFFHGGHHFFB',
  'BFFHHHHHFFB',
  'BFFHGGGHFFB',
  'BFFHHHHHFFB',
  'BFFFFFFFFFB',
  'BBBBBBBBBBB',
  '....BBB....',
  '.....B.....',
]);

/** Pensando: burbuja con tres puntos (sin herramienta abierta, el modelo está razonando). */
export const BURBUJA_PIENSA = sprite({ B: BORDE, F: '#e8eefa', P: '#5a78a8' }, [
  '.BBBBBBBBB.',
  'BFFFFFFFFFB',
  'BFFFFFFFFFB',
  'BFPFFPFFPFB',
  'BFFFFFFFFFB',
  '.BBBBBBBBB.',
  '..BB.......',
  '.B.........',
]);

/** Ocioso: "z" chiquitas. */
export const ZZZ = sprite({ Z: '#c8c8e0' }, [
  '.....ZZZZ',
  '.......Z.',
  'ZZZ...Z..',
  '..Z..ZZZZ',
  '.Z.......',
  'ZZZ......',
]);

/** Lupa de las lentes. */
export const LUPA = sprite({ M: '#3a3a4a', V: '#bfe6ff', W: '#ffffff', C: '#8a5a2b' }, [
  '.MMMM...',
  'MVWVVM..',
  'MWVVVM..',
  'MVVVVM..',
  'MVVVVM..',
  '.MMMMC..',
  '.....CC.',
  '......CC',
]);

/** Buzón (avisos por Discord). Encendido: sobre amarillo. */
export const BUZON = sprite({ R: '#c0392b', D: '#7b241c', S: '#ffffff', P: '#555566' }, [
  '.RRRRRR.',
  'RRRRRRRR',
  'RSSSSSSR',
  'RSDSSDSR',
  'RSSDDSSR',
  'RRRRRRRR',
  '...PP...',
  '...PP...',
]);
export const BUZON_ENCENDIDO = sprite({ R: '#ff6b5a', D: '#c0392b', S: '#fff3a0', P: '#555566' }, [
  '.RRRRRR.',
  'RRRRRRRR',
  'RSSSSSSR',
  'RSDSSDSR',
  'RSSDDSSR',
  'RRRRRRRR',
  '...PP...',
  '...PP...',
]);

/** Bandeja del responsable. */
export const BANDEJA = sprite({ M: '#8a5a2b', L: '#c08850', H: '#ffffff', G: '#d8d8e8' }, [
  '..HHHH..',
  '.HGGGGH.',
  'MHHHHHHM',
  'MLLLLLLM',
  '.MMMMMM.',
]);

/** Ícono de Google: trabajo fuera del área en Drive, Docs o Slides (trabajo_externo del perfil). */
export const GOOGLE = sprite({ B: '#4285f4', R: '#ea4335', Y: '#fbbc05', G: '#34a853' }, [
  '..RRRR..',
  '.R....R.',
  'Y.......',
  'Y...BBBB',
  'Y......B',
  '.G....B.',
  '..GGGG..',
]);

/** Skill: estrella. */
export const ESTRELLA = sprite({ Y: '#ffd84a', O: '#c99a00' }, ['...Y...', '..YYY..', 'YYYYYYY', '.OYYYO.', '.YY.YY.', 'Y.....Y']);

/** Control del agente principal (scripts.controles del perfil): tilde. */
export const TILDE = sprite({ G: '#8fd48a', D: '#3d7a3a' }, ['......G', '.....GD', 'G...GD.', 'DG.GD..', '.DGD...', '..D....']);
