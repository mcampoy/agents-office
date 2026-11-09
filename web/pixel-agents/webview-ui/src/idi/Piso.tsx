// El piso: canvas del motor de Pixel Agents + una capa DOM con etiquetas, burbujas y objetos.
import { useEffect, useMemo, useRef, useState } from 'react';

import { EditActionBar } from '../components/EditActionBar.js';
import { useEditorActions } from '../hooks/useEditorActions.js';
import { OfficeCanvas } from '../office/components/OfficeCanvas.js';
import { EditorState } from '../office/editor/editorState.js';
import { EditorToolbar } from '../office/editor/EditorToolbar.js';
import type { LoadedAssetData } from '../office/layout/furnitureCatalog.js';
import type { OfficeState } from '../office/engine/officeState.js';
import { overlayProjection } from '../office/projection.js';
import { getCachedSprite } from '../office/sprites/spriteCache.js';
import type { SpriteData } from '../office/types.js';
import { CharacterState, TILE_SIZE } from '../office/types.js';
import { COLOR_ESTADO, insigniaModelo, modeloCorto, nombre, nombreCorto, textoEstadoCorto } from './estados.ts';
import {
  BANDEJA,
  BURBUJA_ENTREGA,
  BURBUJA_ERROR,
  BURBUJA_ESPERA,
  BURBUJA_PIENSA,
  BUZON,
  BUZON_ENCENDIDO,
  ESTRELLA,
  GOOGLE,
  LUPA,
  TILDE,
  ZZZ,
} from './iconos.ts';
import type { ControlPiso } from './piso.ts';
import { ID_AVATAR } from './piso.ts';
import { accesorioDe, perfil, trabajoExterno } from './perfil.ts';
import type { Foto, Instancia } from './tipos.ts';
import type { EstadoGuardado } from './transporte.ts';
import { alGuardar } from './transporte.ts';

const estadoEditor = new EditorState();
/** Un objeto (buzón, archivo, controles) queda encendido este tiempo después de usarse. */
const ENCENDIDO_S = 90;

function Icono({ sprite, escala, titulo }: { sprite: SpriteData; escala: number; titulo?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const dpr = window.devicePixelRatio || 1;
  const cache = getCachedSprite(sprite, escala);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    c.width = cache.width;
    c.height = cache.height;
    const ctx = c.getContext('2d');
    ctx?.clearRect(0, 0, c.width, c.height);
    ctx?.drawImage(cache, 0, 0);
  }, [cache]);
  return <canvas ref={ref} title={titulo} className="block" style={{ width: cache.width / dpr, height: cache.height / dpr }} />;
}

function reciente(ts: string | undefined, ahora: number): boolean {
  return !!ts && ahora - Date.parse(ts) < ENCENDIDO_S * 1000;
}


interface Props {
  os: OfficeState;
  control: ControlPiso;
  foto: Foto | null;
  muebles: LoadedAssetData;
  seleccion: string | null;
  onSeleccion: (clave: string | null) => void;
  /** Pantalla de teléfono: sin editor, etiquetas compactas y la cámara sigue al seleccionado. */
  movil?: boolean;
  /** Tocar un tablón del piso abre su pestaña. */
  onAbrirTablon?: (cual: 'Pendientes' | 'Auditorías') => void;
}

/** Tamaño de baldosa (px de CSS) que tiene el zoom cuando la cámara sigue a alguien en el teléfono. */
const BALDOSA_SEGUIR_CSS = 26;
/** Debajo de esta baldosa (px de CSS) las etiquetas pasan a un punto de color. */
const BALDOSA_COMPACTA_CSS = 13;

export function Piso({ os, control, foto, muebles, seleccion, onSeleccion, movil = false, onAbrirTablon }: Props) {
  const contenedor = useRef<HTMLDivElement>(null);
  // Editor de upstream: herramientas, deshacer y guardar. El guardado va a config/layout.json (transporte.ts)
  const editor = useEditorActions(() => os, estadoEditor);
  const panRef = editor.panRef;
  const [guardado, setGuardado] = useState<EstadoGuardado | null>(null);
  useEffect(() => alGuardar(setGuardado), []);
  useEffect(() => editor.setLastSavedLayout(os.getLayout()), [editor.setLastSavedLayout, os]);
  const editando = editor.isEditMode;
  const [zoom, setZoom] = useState(2);
  const [zoomTodo, setZoomTodo] = useState(2);
  const [, setTick] = useState(0);

  // Zoom que hace entrar todo el piso. Solo se recalcula si cambia el ancho: en el teléfono la barra del
  // navegador cambia el alto al hacer scroll y no tiene que deshacer el zoom que eligió la persona.
  useEffect(() => {
    const el = contenedor.current;
    if (!el) return;
    let clave = '';
    const ajustar = () => {
      const dpr = window.devicePixelRatio || 1;
      if (`${el.clientWidth}x${dpr}` === clave) return;
      clave = `${el.clientWidth}x${dpr}`;
      const l = os.getLayout();
      const exacto = Math.min((el.clientWidth * dpr) / (l.cols * TILE_SIZE), (el.clientHeight * dpr) / (l.rows * TILE_SIZE));
      // Entero cuando alcanza (píxeles parejos); si no, el que entra, de a décimos
      // Por debajo de 1 solo para ver todo en pantallas chicas de baja densidad (el pellizco vuelve a ≥ 1)
      const z = Math.max(0.5, exacto >= 2 ? Math.floor(exacto) : Math.floor(exacto * 10) / 10);
      setZoom(z);
      setZoomTodo(z);
      panRef.current = { x: 0, y: 0 };
    };
    ajustar();
    const ro = new ResizeObserver(ajustar);
    ro.observe(el);
    return () => ro.disconnect();
  }, [os]);

  const verTodo = () => {
    os.cameraFollowId = null;
    panRef.current = { x: 0, y: 0 };
    setZoom(zoomTodo);
  };

  // La capa DOM se redibuja en cada cuadro, igual que ToolOverlay de upstream
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      setTick((n) => (n + 1) % 1e6);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  // Selección: del piso a la app y de la app al piso
  useEffect(() => {
    const id = seleccion ? control.idDe(seleccion) : null;
    os.selectedAgentId = id;
    if (!movil) return;
    if (id === null) {
      os.cameraFollowId = null;
      return;
    }
    // En el teléfono, seleccionar acerca la cámara y la centra en el agente
    const dpr = window.devicePixelRatio || 1;
    os.cameraFollowId = id;
    setZoom((z) => Math.max(z, Math.round(((BALDOSA_SEGUIR_CSS * dpr) / TILE_SIZE) * 10) / 10));
  }, [os, control, seleccion, movil]);

  const porTipo = useMemo(() => {
    const m = new Map<string, number>();
    for (const i of foto?.instancias ?? []) m.set(i.tipo, (m.get(i.tipo) ?? 0) + 1);
    return m;
  }, [foto]);

  const el = contenedor.current;
  const dpr = window.devicePixelRatio || 1;
  const proy = el ? overlayProjection(os.getLayout(), el.getBoundingClientRect(), zoom, panRef.current, dpr) : null;
  const escalaIcono = Math.max(1, Math.round(zoom));
  // Las etiquetas no pasan del ancho entre dos escritorios vecinos (4 baldosas)
  const anchoEtiqueta = (4 * TILE_SIZE * zoom) / dpr - 6;
  const compacto = (TILE_SIZE * zoom) / dpr < BALDOSA_COMPACTA_CSS;
  const acercado = zoom > zoomTodo + 0.05 || os.cameraFollowId !== null;
  const ahora = Date.now();
  const enTiles = (c: number, r: number) => (proy ? { left: proy.toScreenX(c * TILE_SIZE), top: proy.toScreenY(r * TILE_SIZE) } : { left: 0, top: 0 });

  const subagentesActivos = (sesion: string) =>
    (foto?.instancias ?? []).filter((x) => !x.principal && x.sesion === sesion && !['terminado', 'ocioso'].includes(x.estado)).length;

  function etiqueta(id: number, inst: Instancia | null) {
    const ch = os.characters.get(id);
    if (!ch || !proy || ch.matrixEffect === 'despawn') return null;
    const sentado = ch.state === CharacterState.TYPE;
    const x = proy.toScreenX(ch.x);
    const yPies = proy.toScreenY(ch.y + (sentado ? 2 : 8));
    const yCabeza = proy.toScreenY(ch.y + (sentado ? 10 : 0) - 26);
    const seleccionado = os.selectedAgentId === id;

    if (!inst) {
      // Avatar del responsable
      if (compacto) return null;
      return (
        <div key={id} className="absolute -translate-x-1/2 pointer-events-none" style={{ left: x, top: yPies, zIndex: 30 }}>
          <div className="idi-etiqueta" style={{ borderColor: '#e0b050' }}>
            <span className="idi-nombre">{perfil().responsable}</span>
          </div>
        </div>
      );
    }

    const color = COLOR_ESTADO[inst.estado];
    let burbuja: SpriteData | null = null;
    if (inst.estado === 'esperando') burbuja = BURBUJA_ESPERA;
    else if (inst.estado === 'error') burbuja = BURBUJA_ERROR;
    else if (inst.estado === 'entregando') burbuja = BURBUJA_ENTREGA;
    else if (inst.estado === 'pensando') burbuja = BURBUJA_PIENSA;
    else if (inst.estado === 'ocioso') burbuja = ZZZ;
    const n = nombreCorto(inst, porTipo.get(inst.tipo) ?? 1);
    const completo = nombre(inst, porTipo.get(inst.tipo) ?? 1);
    const extra = inst.etiqueta && !inst.principal ? inst.etiqueta : null;
    const google = inst.estado === 'trabajando' && trabajoExterno(inst.tipo, inst.herramienta) === 'google';
    const atenuado = inst.estado === 'ocioso' || inst.estado === 'terminado';
    // Lo que pide atención nunca se corta, aunque tape un poco a un vecino
    const urgente = inst.estado === 'esperando' || inst.estado === 'error';
    // Con baldosas chicas (teléfono, vista completa) cada agente es un punto del color de su estado;
    // el detalle está en las tarjetas y aparece al seleccionarlo
    const punto = compacto && !seleccionado && !urgente;

    return (
      <div key={id}>
        {burbuja && (
          <div
            className={`absolute -translate-x-1/2 -translate-y-full pointer-events-none ${inst.estado === 'esperando' ? 'idi-latido' : ''}`}
            style={{ left: x, top: yCabeza, zIndex: 40 }}
          >
            <Icono sprite={burbuja} escala={escalaIcono} />
          </div>
        )}
        {punto ? (
          <div className="absolute -translate-x-1/2 pointer-events-none idi-punto" style={{ left: x, top: yPies, background: color, zIndex: 30 }} title={completo} />
        ) : (
        <div className="absolute -translate-x-1/2 pointer-events-none" style={{ left: x, top: yPies, zIndex: seleccionado || urgente ? 35 : 30, opacity: atenuado ? 0.75 : 1 }}>
          <div className="idi-etiqueta" title={completo} style={{ borderColor: color, outline: seleccionado ? '2px solid #fff' : undefined, maxWidth: urgente ? undefined : anchoEtiqueta }}>
            <div className="flex items-center gap-3">
              {accesorioDe(inst.tipo) === 'lupa' && <Icono sprite={LUPA} escala={Math.max(1, escalaIcono - 1)} titulo="lupa" />}
              {google && <Icono sprite={GOOGLE} escala={Math.max(1, escalaIcono - 1)} titulo="trabaja en Google Drive" />}
              <span className="idi-nombre truncate">{n}</span>
              <span className="idi-insignia" style={{ background: insigniaModelo(inst.modelo).color }} title={`modelo: ${modeloCorto(inst.modelo)}`}>
                {insigniaModelo(inst.modelo).letra}
              </span>
              {inst.skills.length > 0 && <Icono sprite={ESTRELLA} escala={Math.max(1, escalaIcono - 1)} titulo={`skills: ${inst.skills.join(', ')}`} />}
            </div>
            {extra && <div className="idi-extra truncate">{extra}</div>}
            <div className="idi-estado truncate" style={{ color }}>
              {textoEstadoCorto(inst, inst.principal ? subagentesActivos(inst.sesion) : 0)}
              {inst.sin_zona ? ' · sin zona' : ''}
            </div>
          </div>
        </div>
        )}
      </div>
    );
  }

  // --- Objetos ---------------------------------------------------------------
  const objetos: React.ReactNode[] = [];
  if (foto && proy) {
    const ultimo = <T,>(a: T[]) => a[a.length - 1];
    // Bandeja del responsable sobre su escritorio
    const av = os.characters.get(ID_AVATAR);
    const seatAv = av?.seatId ? os.seats.get(av.seatId) : null;
    if (seatAv) {
      const p = enTiles(seatAv.seatCol + 2.2, seatAv.seatRow + 0.4);
      const r = foto.responsable;
      objetos.push(
        <div key="bandeja" className="absolute pointer-events-auto" style={{ ...p, zIndex: 32 }} title="Pendientes (pendientes.md) y aprobaciones en espera">
          <div className="idi-objeto" style={{ borderColor: r.aprobaciones > 0 ? COLOR_ESTADO.esperando : '#e0b050' }}>
            <Icono sprite={BANDEJA} escala={escalaIcono} />
            <span>{r.pendientes} pend.</span>
            <span style={{ color: r.aprobaciones > 0 ? COLOR_ESTADO.esperando : undefined }}>{r.aprobaciones} aprob.</span>
          </div>
        </div>,
      );
    }
    // Reloj de pared: corrida programada (solo si el perfil la define)
    const reloj = control.mueble('CLOCK');
    const corrida = perfil().corrida;
    if (reloj && corrida && foto.reloj.proxima) {
      const prox = new Date(foto.reloj.proxima);
      const dias = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'];
      const agenteCorrida = corrida.agente ?? '';
      const activo = foto.instancias.some((i) => i.tipo === agenteCorrida && i.estado !== 'ocioso' && i.estado !== 'terminado');
      objetos.push(
        <div key="reloj" className="absolute -translate-x-1/2" style={{ ...enTiles(reloj.col + 0.5, reloj.row + 2.1), zIndex: 31 }}>
          <div className="idi-objeto idi-chico">
            {foto.reloj.en_curso ? (
              <span style={{ color: COLOR_ESTADO.trabajando }}>corrida programada en curso</span>
            ) : (
              <span>
                {activo || !agenteCorrida ? '' : `${agenteCorrida} · `}próxima: {dias[prox.getDay()]} {prox.toTimeString().slice(0, 5)}
              </span>
            )}
            <span className="idi-tenue">última: {foto.reloj.ultima ?? '—'}</span>
          </div>
        </div>,
      );
    }
    // Buzón (notificar.py): en la pared del pasillo, junto a la zona común
    const buzon = ultimo(foto.objetos.buzon);
    const encendido = reciente(buzon?.ts, ahora);
    const rc = control.rectangulo('comun');
    if (rc) {
      objetos.push(
        <div key="buzon" className="absolute" style={{ ...enTiles(rc.c1 - 1, rc.r0 - 0.6), zIndex: 31 }} title="Buzón: avisos por Discord (notificar.py)">
          <div className={`idi-objeto ${encendido ? 'idi-brilla' : ''}`}>
            <Icono sprite={encendido ? BUZON_ENCENDIDO : BUZON} escala={escalaIcono} />
            {buzon && <span className={encendido ? '' : 'idi-tenue'}>{buzon.canal ?? 'avisos'}</span>}
          </div>
        </div>,
      );
    }
    // Archivo (engram): la biblioteca de la pared de la zona común
    const archivo = os.getLayout().furniture.find((f) => f.type === 'DOUBLE_BOOKSHELF' && os.getLayout().areaTiles?.[(f.row + 2) * os.getLayout().cols + f.col] === 'comun');
    const memoria = ultimo(foto.objetos.memoria);
    if (archivo) {
      const on = reciente(memoria?.ts, ahora);
      objetos.push(
        <div
          key="archivo"
          className={`absolute pointer-events-auto ${on ? 'idi-archivo-on' : ''}`}
          style={{ ...enTiles(archivo.col, archivo.row), width: 2 * TILE_SIZE * zoom / dpr, height: 2 * TILE_SIZE * zoom / dpr, zIndex: 29 }}
          title={memoria ? `Archivo (engram): última consulta ${memoria.herramienta ?? ''} ${memoria.ts.slice(11, 16)}` : 'Archivo (engram y .remember)'}
        />,
      );
    }
    // Controles de partner: tilde sobre su escritorio
    const control_ = ultimo(foto.objetos.controles);
    const partner = control.fichasVisibles().find((f) => f.inst.principal);
    const chP = partner ? os.characters.get(partner.id) : undefined;
    const seatP = chP?.seatId ? os.seats.get(chP.seatId) : null;
    if (seatP && control_ && reciente(control_.ts, ahora)) {
      objetos.push(
        <div key="control" className="absolute" style={{ ...enTiles(seatP.seatCol + 2.2, seatP.seatRow + 0.4), zIndex: 33 }}>
          <div className="idi-objeto idi-chico">
            <Icono sprite={TILDE} escala={escalaIcono} />
            <span>{(control_.script ?? '').replace(/\.(py|ps1)$/, '')}</span>
          </div>
        </div>,
      );
    }
    // Salas con las luces apagadas mientras no hay nadie activo (las que diga el perfil)
    for (const zona of perfil().piso.luces_apagadas ?? []) {
    const com = control.rectangulo(zona);
    if (com && !control.zonaActiva(zona)) {
      const a = enTiles(com.c0, com.r0 - 1);
      const b = enTiles(com.c1 + 1, com.r1 + 1);
      objetos.push(
        <div key={`luces-${zona}`} className="absolute pointer-events-none" style={{ left: a.left, top: a.top, width: b.left - a.left, height: b.top - a.top, background: 'rgba(5,5,20,0.55)', zIndex: 5 }}>
          <span className="idi-sala-apagada">luces apagadas</span>
        </div>,
      );
    }
    }
    // Tablones fijos del proyecto, en la pared del despacho del responsable: pendientes y auditorías
    const desp = control.rectangulo('responsable');
    if (desp && foto.tablones) {
      const t = foto.tablones;
      // Una columna con las dos pizarras: separación fija en píxeles, para que no se pisen con baldosas chicas
      const pizarras: React.ReactNode[] = [];
      const tablon = (clave: string, cual: 'Pendientes' | 'Auditorías', _fila: number, contenido: React.ReactNode, titulo: string) =>
        pizarras.push(
          <button key={clave} className="idi-tablon pointer-events-auto" onClick={() => onAbrirTablon?.(cual)} title={titulo}>
            {contenido}
          </button>,
        );
      tablon(
        'tablon-pendientes',
        'Pendientes',
        1.6,
        <>
          <span className="idi-tablon-titulo">Pendientes</span>
          <span className="idi-tablon-cuentas">
            <span style={{ color: COLOR_ESTADO.trabajando }}>{t.pendientes.en_curso.length} en curso</span>
            {!compacto && <span style={{ color: COLOR_ESTADO.esperando }}>{t.pendientes.siguen.length} siguen</span>}
            {!compacto && <span style={{ color: COLOR_ESTADO.terminado }}>{t.pendientes.hechas.length} hechas</span>}
          </span>
        </>,
        `Tablón de pendientes: ${t.pendientes.en_curso.length} en curso, ${t.pendientes.siguen.length} siguen, ${t.pendientes.hechas.length} hechas`,
      );
      tablon(
        'tablon-auditorias',
        'Auditorías',
        compacto ? 3.2 : 4.4,
        <>
          <span className="idi-tablon-titulo">Auditorías</span>
          <span className="idi-tablon-cuentas">
            <span style={{ color: t.auditorias.abiertas.length ? COLOR_ESTADO.error : COLOR_ESTADO.ocioso }}>
              {t.auditorias.abiertas.length} abiertas
            </span>
          </span>
        </>,
        `Tablón de auditorías: ${t.auditorias.abiertas.length} fricciones abiertas, ${t.auditorias.resueltas.length} resueltas`,
      );
      objetos.push(
        <div key="tablones" className="absolute idi-tablones" style={{ ...enTiles(desp.c0 + 0.15, desp.r0 + 1.6), zIndex: 33 }}>
          {pizarras}
        </div>,
      );
    }
    // Agentes borrados de .claude/agents: su lugar queda vacante (el historial se conserva en el servidor)
    const rec = control.rectangulo('recepcion');
    if (rec && foto.vacantes.length) {
      objetos.push(
        <div key="vacantes" className="absolute" style={{ ...enTiles(rec.c0 + 0.2, rec.r1 - 0.2), zIndex: 31 }} title="Agentes cuya definición se borró">
          <div className="idi-objeto idi-chico">
            <span>vacantes:</span>
            {foto.vacantes.map((v) => (
              <span key={v}>{v}</span>
            ))}
          </div>
        </div>,
      );
    }
    // Cruces del verificador del día, junto al paso
    const pv = control.rectangulo('paso-verificacion');
    const cruces = Object.entries(foto.resumen_cruces ?? {});
    if (pv && cruces.length) {
      objetos.push(
        <div key="cruces" className="absolute" style={{ ...enTiles(pv.c0 + 4.3, pv.r0 + 0.3), zIndex: 31 }} title="Cruces del verificador hoy, por tipo de documento y ronda">
          <div className="idi-objeto idi-chico">
            <span>cruces hoy:</span>
            {cruces.map(([k, v]) => (
              <span key={k}>
                {k} ×{v}
              </span>
            ))}
          </div>
        </div>,
      );
    }
  }

  // Nombres de las salas
  const salas: React.ReactNode[] = [];
  const nombres = perfil().piso.salas;
  if (proy) {
    for (const [zona, texto] of Object.entries(nombres)) {
      const r = control.rectangulo(zona);
      if (!r) continue;
      salas.push(
        <div key={zona} className="absolute idi-sala" style={{ ...enTiles(r.c0 + 0.2, r.r0 + 0.1), zIndex: 6 }}>
          {texto}
        </div>,
      );
    }
  }

  return (
    <div ref={contenedor} className="relative w-full h-full overflow-hidden" style={{ background: '#11111b' }}>
      <OfficeCanvas
        officeState={os}
        onClick={(id) => onSeleccion(id === ID_AVATAR ? null : control.claveDe(id))}
        isEditMode={editando}
        editorState={estadoEditor}
        onEditorTileAction={editor.handleEditorTileAction}
        onEditorEraseAction={editor.handleEditorEraseAction}
        onEditorSelectionChange={editor.handleEditorSelectionChange}
        onDeleteSelected={editor.handleDeleteSelected}
        onRotateSelected={editor.handleRotateSelected}
        onDrop={editor.handleDrop}
        editorTick={editor.editorTick}
        zoom={zoom}
        onZoomChange={setZoom}
        panRef={panRef}
        showAreas={editando}
        activeAreaLabel={editor.selectedAreaLabel}
      />
      {!editando && (
        <div className="absolute inset-0 pointer-events-none">
          {!compacto && salas}
          {compacto ? objetos.filter((o) => /^(buzon|archivo|luces|tablon)/.test(String((o as { key?: string }).key))) : objetos}
          {control.fichasVisibles().map(({ id, inst }) => etiqueta(id, inst))}
          {etiqueta(ID_AVATAR, null)}
        </div>
      )}
      {movil && acercado && (
        <button className="idi-boton idi-flotante" onClick={verTodo}>
          Ver todo el piso
        </button>
      )}
      {!movil && (
      <div className="absolute right-8 bottom-8 z-50 flex items-center gap-8">
        {guardado && editando && (
          <span className={guardado.estado === 'error' ? 'idi-aviso' : 'idi-tenue'}>
            {guardado.estado === 'guardando'
              ? 'guardando…'
              : guardado.estado === 'guardado'
                ? 'guardado en config/layout.json'
                : `no se guardó: ${guardado.detalle}`}
          </span>
        )}
        <button className="idi-boton" onClick={editor.handleToggleEditMode} title="Editar el piso (se guarda en config/layout.json)">
          {editando ? 'Salir del editor' : 'Editar piso'}
        </button>
      </div>
      )}
      {editando && editor.isDirty && <EditActionBar editor={editor} editorState={estadoEditor} />}
      {editando && (
        <EditorToolbar
          activeTool={estadoEditor.activeTool}
          selectedTileType={estadoEditor.selectedTileType}
          selectedFurnitureType={estadoEditor.placingType}
          selectedFurnitureUid={estadoEditor.selectedFurnitureUid}
          selectedFurnitureColor={
            estadoEditor.selectedFurnitureUid
              ? (os.getLayout().furniture.find((f) => f.uid === estadoEditor.selectedFurnitureUid)?.color ?? null)
              : null
          }
          floorColor={estadoEditor.floorColor}
          wallColor={estadoEditor.wallColor}
          selectedWallSet={estadoEditor.selectedWallSet}
          onToolChange={editor.handleToolChange}
          onTileTypeChange={editor.handleTileTypeChange}
          onFloorColorChange={editor.handleFloorColorChange}
          onWallColorChange={editor.handleWallColorChange}
          onWallSetChange={editor.handleWallSetChange}
          onSelectedFurnitureColorChange={editor.handleSelectedFurnitureColorChange}
          pickedFurnitureColor={estadoEditor.pickedFurnitureColor}
          onPickedFurnitureColorChange={editor.handlePickedFurnitureColorChange}
          onColorPickToggle={editor.handleColorPickToggle}
          onFurnitureTypeChange={editor.handleFurnitureTypeChange}
          loadedAssets={muebles}
          activePetTypes={[]}
          petCount={0}
          onPetToggle={() => undefined}
          carpetVariant={editor.carpetVariant}
          carpetColor={editor.carpetColor}
          carpetAccentColor={editor.carpetAccentColor}
          onCarpetVariantChange={editor.handleCarpetVariantChange}
          onCarpetColorChange={editor.handleCarpetColorChange}
          onCarpetAccentColorChange={editor.handleCarpetAccentColorChange}
          areas={os.getLayout().areas ?? []}
          selectedAreaLabel={editor.selectedAreaLabel}
          directories={[]}
          areasAvailable={true}
          areaMappings={{}}
          onSelectArea={editor.handleSelectArea}
          onAddArea={editor.handleAddArea}
          onRemoveArea={editor.handleRemoveArea}
          onRenameArea={editor.handleRenameArea}
          onAreaColorChange={editor.handleAreaColorChange}
          onAreaMappingChange={() => undefined}
        />
      )}
    </div>
  );
}
