// Pantalla de la oficina: cabecera (partner), piso a la izquierda, pestañas a la derecha y tarjetas abajo.
import { useEffect, useMemo, useRef, useState } from 'react';

import { OfficeState } from '../office/engine/officeState.js';
import type { Conexion, Recursos } from './datos.ts';
import { useFoto } from './datos.ts';
import { COLOR_ESTADO, duracion, grupo, modeloCorto, nombre, textoEstado } from './estados.ts';
import { perfil } from './perfil.ts';
import { Piso } from './Piso.tsx';
import { ControlPiso, visibleEnPiso } from './piso.ts';
import type { Foto, Instancia } from './tipos.ts';

const PESTANAS = ['Aprobaciones', 'Flujos', 'Actividad', 'Tareas', 'Memoria', 'Corridas', 'Catálogo'];

function subagentesActivos(foto: Foto, sesion: string): number {
  return foto.instancias.filter((x) => !x.principal && x.sesion === sesion && !['terminado', 'ocioso'].includes(x.estado)).length;
}

function tareaActual(i: Instancia): string {
  if (i.estado === 'esperando' && i.espera) return `pide permiso: ${i.espera.herramienta ?? ''} ${i.espera.recurso ?? ''}`.trim();
  const partes = [i.herramienta, i.recurso ?? i.documento].filter(Boolean);
  return partes.join(' · ') || '—';
}

function contar(foto: Foto | null) {
  const cuenta = { trabajan: 0, esperan: 0, error: 0, ociosos: 0 };
  for (const i of foto?.instancias ?? []) if (visibleEnPiso(i)) cuenta[grupo(i.estado)]++;
  return cuenta;
}

/** Pantalla angosta (teléfono en vertical). */
function useEsMovil(): boolean {
  const consulta = '(max-width: 760px)';
  const [movil, setMovil] = useState(() => window.matchMedia(consulta).matches);
  useEffect(() => {
    const mq = window.matchMedia(consulta);
    const cambio = () => setMovil(mq.matches);
    mq.addEventListener('change', cambio);
    return () => mq.removeEventListener('change', cambio);
  }, []);
  return movil;
}

type Vista = 'piso' | 'paneles';
const VISTAS: Array<{ id: Vista; texto: string }> = [
  { id: 'piso', texto: 'Piso' },
  { id: 'paneles', texto: 'Paneles' },
];

/** Vista activa en el teléfono, en el hash de la URL: el botón Atrás vuelve a la anterior. */
function useVista(): [Vista, (v: Vista) => void] {
  const leer = (): Vista => {
    const h = window.location.hash.replace('#', '');
    return VISTAS.some((v) => v.id === h) ? (h as Vista) : 'piso';
  };
  const [vista, setVista] = useState<Vista>(leer);
  useEffect(() => {
    const cambio = () => setVista(leer());
    window.addEventListener('hashchange', cambio);
    return () => window.removeEventListener('hashchange', cambio);
  }, []);
  const ir = (v: Vista) => {
    if (v !== leer()) window.location.hash = v;
  };
  return [vista, ir];
}

function CabeceraMovil({ foto, conexion }: { foto: Foto | null; conexion: Conexion }) {
  const p = foto?.principal ?? null;
  const cuenta = contar(foto);
  return (
    <header className="idi-cabecera-movil">
      <div className="idi-fila">
        <span className="idi-nombre-grande">{perfil().principal}</span>
        {p ? (
          <>
            <span className="idi-pildora" style={{ background: COLOR_ESTADO[p.estado] }}>
              {textoEstado(p, foto ? subagentesActivos(foto, p.sesion) : 0)}
            </span>
            <span className="idi-tenue">{duracion(p.segundos_en_estado)}</span>
          </>
        ) : (
          <span className="idi-tenue">{foto ? 'sin sesión abierta' : 'cargando…'}</span>
        )}
        <span className={`idi-conexion ${conexion === 'en vivo' ? 'idi-tenue' : 'idi-aviso'}`} title={conexion}>
          ●
        </span>
      </div>
      <div className="idi-fila idi-cuentas">
        <span style={{ color: COLOR_ESTADO.trabajando }}>{cuenta.trabajan} trabajan</span>
        <span style={{ color: COLOR_ESTADO.esperando }}>{cuenta.esperan} esperan</span>
        <span style={{ color: COLOR_ESTADO.error }}>{cuenta.error} error</span>
        <span style={{ color: COLOR_ESTADO.ocioso }}>{cuenta.ociosos} en pausa</span>
      </div>
      {p?.aviso_reinicio && <div className="idi-aviso idi-banda">{p.aviso_reinicio}</div>}
      {foto && foto.salud.errores_hook_24h > 0 && (
        <div className="idi-aviso idi-banda">El hook de captura falló {foto.salud.errores_hook_24h} veces en 24 h</div>
      )}
    </header>
  );
}

function Cabecera({ foto, conexion }: { foto: Foto | null; conexion: Conexion }) {
  const p = foto?.principal ?? null;
  const cuenta = contar(foto);
  return (
    <header className="idi-cabecera">
      <div className="flex items-center gap-12 min-w-0">
        <div className="idi-marca">{perfil().nombre}</div>
        {p ? (
          <div className="flex items-center gap-10 min-w-0">
            <span className="idi-nombre-grande">{perfil().principal}</span>
            <span className="idi-pildora" style={{ background: COLOR_ESTADO[p.estado] }}>
              {textoEstado(p, foto ? subagentesActivos(foto, p.sesion) : 0)}
            </span>
            <span className="idi-tenue">hace {duracion(p.segundos_en_estado)}</span>
            <span className="truncate" title={tareaActual(p)}>
              {tareaActual(p)}
            </span>
            {p.aviso_reinicio && <span className="idi-aviso">{p.aviso_reinicio}</span>}
          </div>
        ) : (
          <span className="idi-tenue">{foto ? `Sin sesión de ${perfil().principal} abierta` : 'Cargando…'}</span>
        )}
      </div>
      <div className="flex items-center gap-12 shrink-0">
        <span style={{ color: COLOR_ESTADO.trabajando }}>{cuenta.trabajan} trabajan</span>
        <span style={{ color: COLOR_ESTADO.esperando }}>{cuenta.esperan} esperan</span>
        <span style={{ color: COLOR_ESTADO.error }}>{cuenta.error} con error</span>
        <span style={{ color: COLOR_ESTADO.ocioso }}>{cuenta.ociosos} ociosos o terminados</span>
        {foto && foto.salud.errores_hook_24h > 0 && (
          <span className="idi-aviso" title="Errores del hook de captura en las últimas 24 h (<datos>/errores.log)">
            hook: {foto.salud.errores_hook_24h} errores
          </span>
        )}
        <span className={conexion === 'en vivo' ? 'idi-tenue' : 'idi-aviso'}>● {conexion}</span>
      </div>
    </header>
  );
}

function Tarjetas({
  foto,
  seleccion,
  onSeleccion,
  modo = 'barra',
}: {
  foto: Foto | null;
  seleccion: string | null;
  onSeleccion: (c: string | null) => void;
  /** barra: fila horizontal (escritorio y tira del piso en el teléfono); lista: columna a pantalla completa */
  modo?: 'barra' | 'lista';
}) {
  const instancias = (foto?.instancias ?? []).filter(visibleEnPiso);
  const porTipo = new Map<string, number>();
  for (const i of instancias) porTipo.set(i.tipo, (porTipo.get(i.tipo) ?? 0) + 1);
  // Lo que necesita atención primero
  const orden = { esperando: 0, error: 1, entregando: 2, trabajando: 3, pensando: 4, esperando_subagentes: 5, terminado: 6, ocioso: 7 };
  const ordenadas = [...instancias].sort((a, b) => Number(b.principal) - Number(a.principal) || orden[a.estado] - orden[b.estado]);
  return (
    <footer className={modo === 'lista' ? 'idi-lista' : 'idi-tarjetas'}>
      {ordenadas.length === 0 && <span className="idi-tenue px-12">Sin agentes en la oficina.</span>}
      {ordenadas.map((i) => (
        <button
          key={i.clave}
          className={`idi-tarjeta ${seleccion === i.clave ? 'idi-tarjeta-sel' : ''}`}
          style={{ borderColor: COLOR_ESTADO[i.estado] }}
          onClick={() => onSeleccion(seleccion === i.clave ? null : i.clave)}
          title={i.rol ?? undefined}
        >
          <div className="flex items-center justify-between gap-6">
            <span className="idi-nombre truncate">{nombre(i, porTipo.get(i.tipo) ?? 1)}</span>
            <span className="idi-modelo" title={`modelo (${i.fuente_modelo ?? '?'})`}>
              {modeloCorto(i.modelo)}
            </span>
          </div>
          <div className="idi-rol truncate">{i.etiqueta && !i.principal ? i.etiqueta : (i.rol ?? (i.general ? 'agente general' : ''))}</div>
          <div className="flex items-center justify-between gap-6">
            <span className="idi-estado" style={{ color: COLOR_ESTADO[i.estado] }}>
              ■ {textoEstado(i, i.principal && foto ? subagentesActivos(foto, i.sesion) : 0)}
            </span>
            <span className="idi-tenue">{duracion(i.segundos_en_estado)}</span>
          </div>
        </button>
      ))}
    </footer>
  );
}

function Pestanas({ seleccion, foto }: { seleccion: string | null; foto: Foto | null }) {
  const [activa, setActiva] = useState(0);
  const inst = foto?.instancias.find((i) => i.clave === seleccion);
  return (
    <aside className="idi-pestanas">
      <nav className="flex flex-wrap">
        {PESTANAS.map((p, k) => (
          <button key={p} className={`idi-pestana ${k === activa ? 'idi-pestana-sel' : ''}`} onClick={() => setActiva(k)}>
            {p}
          </button>
        ))}
      </nav>
      <div className="p-12 idi-tenue">
        {inst && (
          <p className="mb-8" style={{ color: 'var(--color-text)' }}>
            Filtro: {inst.etiqueta_historial}
          </p>
        )}
        <p>Las pestañas se implementan en la fase 4.</p>
      </div>
    </aside>
  );
}

export function Oficina({ recursos }: { recursos: Recursos }) {
  const { foto, conexion } = useFoto();
  const [seleccion, setSeleccion] = useState<string | null>(null);
  const movil = useEsMovil();
  const [vista, irA] = useVista();
  const os = useMemo(() => new OfficeState(recursos.layout), [recursos]);
  const control = useMemo(() => new ControlPiso(os, recursos.personajes, recursos.sprites), [os, recursos]);
  const primera = useRef(true);

  useEffect(() => {
    if (!foto) return;
    control.sincronizar(foto, primera.current);
    primera.current = false;
  }, [foto, control]);

  if (movil) {
    return (
      <div className="idi-pantalla-movil">
        <CabeceraMovil foto={foto} conexion={conexion} />
        <main className="idi-vista">
          {vista === 'piso' && (
            <>
              {/* Arriba el plano con la altura justa; abajo los agentes. Tocar uno lo enfoca en el plano */}
              <section className="idi-piso idi-piso-movil">
                <Piso os={os} control={control} foto={foto} muebles={recursos.muebles} seleccion={seleccion} onSeleccion={setSeleccion} movil />
              </section>
              <Tarjetas foto={foto} seleccion={seleccion} onSeleccion={setSeleccion} modo="lista" />
            </>
          )}
          {vista === 'paneles' && <Pestanas seleccion={seleccion} foto={foto} />}
        </main>
        <nav className="idi-nav" aria-label="Vistas" style={{ gridTemplateColumns: `repeat(${VISTAS.length}, 1fr)` }}>
          {VISTAS.map((v) => (
            <button key={v.id} className={`idi-nav-boton ${vista === v.id ? 'idi-nav-sel' : ''}`} aria-current={vista === v.id ? 'page' : undefined} onClick={() => irA(v.id)}>
              {v.texto}
            </button>
          ))}
        </nav>
      </div>
    );
  }

  return (
    <div className="idi-pantalla">
      <Cabecera foto={foto} conexion={conexion} />
      <main className="idi-centro">
        <section className="idi-piso">
          <Piso os={os} control={control} foto={foto} muebles={recursos.muebles} seleccion={seleccion} onSeleccion={setSeleccion} />
        </section>
        <Pestanas seleccion={seleccion} foto={foto} />
      </main>
      <Tarjetas foto={foto} seleccion={seleccion} onSeleccion={setSeleccion} />
    </div>
  );
}
