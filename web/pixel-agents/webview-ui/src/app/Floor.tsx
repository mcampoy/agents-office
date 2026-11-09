// The floor: the Pixel Agents engine canvas + a DOM layer with labels, bubbles and objects.
// Visible texts are the UI, so they are Spanish.
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
import type { FloorController } from './floorController.ts';
import { AVATAR_ID } from './floorController.ts';
import {
  ERROR_BUBBLE,
  GOOGLE,
  HANDOFF_BUBBLE,
  PROMPT_BUBBLE,
  MAGNIFIER,
  MAILBOX,
  MAILBOX_LIT,
  STAR,
  THINK_BUBBLE,
  TICK,
  TRAY,
  WAIT_BUBBLE,
  ZZZ,
} from './icons.ts';
import { accessoryOf, externalWork, profile } from './profile.ts';
import { STATE_COLOR, displayName, modelBadge, shortModel, shortName, shortStateText } from './states.ts';
import type { TabName } from './Tabs.tsx';
import type { SaveStatus } from './transport.ts';
import { onSave } from './transport.ts';
import type { Instance, Snapshot } from './types.ts';

const editorState = new EditorState();
/** An object (mailbox, archive, checks) stays lit this long after being used. */
const LIT_S = 90;

// Layout zones the floor places objects in
const LOUNGE = 'lounge';
const OWNER = 'owner';
const RECEPTION = 'reception';
const VERIFICATION = 'verification';

function Icon({ sprite, scale, title }: { sprite: SpriteData; scale: number; title?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const dpr = window.devicePixelRatio || 1;
  const cache = getCachedSprite(sprite, scale);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    c.width = cache.width;
    c.height = cache.height;
    const ctx = c.getContext('2d');
    ctx?.clearRect(0, 0, c.width, c.height);
    ctx?.drawImage(cache, 0, 0);
  }, [cache]);
  return <canvas ref={ref} title={title} className="block" style={{ width: cache.width / dpr, height: cache.height / dpr }} />;
}

function recent(ts: string | undefined, now: number): boolean {
  return !!ts && now - Date.parse(ts) < LIT_S * 1000;
}


interface Props {
  os: OfficeState;
  controller: FloorController;
  snapshot: Snapshot | null;
  furniture: LoadedAssetData;
  selection: string | null;
  onSelect: (key: string | null) => void;
  /** Phone screen: no editor, compact labels and the camera follows the selected one. */
  mobile?: boolean;
  /** Tapping a board on the floor opens its tab. */
  onOpenBoard?: (board: TabName) => void;
}

/** Tile size (CSS px) of the zoom when the camera follows someone on the phone. */
const FOLLOW_TILE_CSS = 26;
/** Below this tile size (CSS px) labels become a colored dot. */
const COMPACT_TILE_CSS = 13;

export function Floor({ os, controller, snapshot, furniture, selection, onSelect, mobile = false, onOpenBoard }: Props) {
  const container = useRef<HTMLDivElement>(null);
  // Upstream editor: tools, undo and save. Saving goes to the profile's layout.json (transport.ts)
  const editor = useEditorActions(() => os, editorState);
  const panRef = editor.panRef;
  const [saveStatus, setSaveStatus] = useState<SaveStatus | null>(null);
  useEffect(() => onSave(setSaveStatus), []);
  useEffect(() => editor.setLastSavedLayout(os.getLayout()), [editor.setLastSavedLayout, os]);
  const editing = editor.isEditMode;
  const [zoom, setZoom] = useState(2);
  const [fitZoom, setFitZoom] = useState(2);
  const [, setTick] = useState(0);

  // Zoom that fits the whole floor. Only recomputed when the width changes: on the phone the browser bar
  // changes the height on scroll and must not undo the zoom the person chose.
  useEffect(() => {
    const el = container.current;
    if (!el) return;
    let key = '';
    const fit = () => {
      const dpr = window.devicePixelRatio || 1;
      if (`${el.clientWidth}x${dpr}` === key) return;
      key = `${el.clientWidth}x${dpr}`;
      const l = os.getLayout();
      const exact = Math.min((el.clientWidth * dpr) / (l.cols * TILE_SIZE), (el.clientHeight * dpr) / (l.rows * TILE_SIZE));
      // Integer when it fits (even pixels); otherwise the one that fits, in tenths
      // Below 1 only to see everything on small low-density screens (pinching brings it back to ≥ 1)
      const z = Math.max(0.5, exact >= 2 ? Math.floor(exact) : Math.floor(exact * 10) / 10);
      setZoom(z);
      setFitZoom(z);
      panRef.current = { x: 0, y: 0 };
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => ro.disconnect();
  }, [os]);

  const showAll = () => {
    os.cameraFollowId = null;
    panRef.current = { x: 0, y: 0 };
    setZoom(fitZoom);
  };

  // The DOM layer redraws every frame, like upstream's ToolOverlay
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      setTick((n) => (n + 1) % 1e6);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  // Selection: from the floor to the app and from the app to the floor
  useEffect(() => {
    const id = selection ? controller.idOf(selection) : null;
    os.selectedAgentId = id;
    if (!mobile) return;
    if (id === null) {
      os.cameraFollowId = null;
      return;
    }
    // On the phone, selecting zooms in and centers the camera on the agent
    const dpr = window.devicePixelRatio || 1;
    os.cameraFollowId = id;
    setZoom((z) => Math.max(z, Math.round(((FOLLOW_TILE_CSS * dpr) / TILE_SIZE) * 10) / 10));
  }, [os, controller, selection, mobile]);

  const byType = useMemo(() => {
    const m = new Map<string, number>();
    for (const i of snapshot?.instances ?? []) m.set(i.type, (m.get(i.type) ?? 0) + 1);
    return m;
  }, [snapshot]);

  const el = container.current;
  const dpr = window.devicePixelRatio || 1;
  const proj = el ? overlayProjection(os.getLayout(), el.getBoundingClientRect(), zoom, panRef.current, dpr) : null;
  const iconScale = Math.max(1, Math.round(zoom));
  // Labels are never wider than the space between two neighboring desks (4 tiles)
  const labelWidth = (4 * TILE_SIZE * zoom) / dpr - 6;
  const compact = (TILE_SIZE * zoom) / dpr < COMPACT_TILE_CSS;
  const zoomedIn = zoom > fitZoom + 0.05 || os.cameraFollowId !== null;
  const now = Date.now();
  const atTile = (c: number, r: number) => (proj ? { left: proj.toScreenX(c * TILE_SIZE), top: proj.toScreenY(r * TILE_SIZE) } : { left: 0, top: 0 });

  const activeSubagents = (session: string) =>
    (snapshot?.instances ?? []).filter((x) => !x.main && x.session === session && !['done', 'idle'].includes(x.state)).length;

  function label(id: number, inst: Instance | null) {
    const ch = os.characters.get(id);
    if (!ch || !proj || ch.matrixEffect === 'despawn') return null;
    const seated = ch.state === CharacterState.TYPE;
    const x = proj.toScreenX(ch.x);
    const yFeet = proj.toScreenY(ch.y + (seated ? 2 : 8));
    const yHead = proj.toScreenY(ch.y + (seated ? 10 : 0) - 26);
    const selected = os.selectedAgentId === id;

    if (!inst) {
      // The owner's avatar
      const asking = controller.prompted(id);
      if (compact && !asking) return null;
      return (
        <div key={id}>
          {asking && (
            <div className="absolute -translate-x-1/2 -translate-y-full pointer-events-none" style={{ left: x, top: yHead, zIndex: 40 }} title="Nuevo pedido">
              <Icon sprite={PROMPT_BUBBLE} scale={iconScale} />
            </div>
          )}
          {!compact && (
            <div className="absolute -translate-x-1/2 pointer-events-none" style={{ left: x, top: yFeet, zIndex: 30 }}>
              <div className="ao-label" style={{ borderColor: '#e0b050' }}>
                <span className="ao-name">{profile().owner_label}</span>
              </div>
            </div>
          )}
        </div>
      );
    }

    const color = STATE_COLOR[inst.state];
    let bubble: SpriteData | null = null;
    if (inst.state === 'waiting') bubble = WAIT_BUBBLE;
    else if (inst.state === 'error') bubble = ERROR_BUBBLE;
    else if (inst.state === 'handing_off') bubble = HANDOFF_BUBBLE;
    else if (inst.state === 'thinking') bubble = THINK_BUBBLE;
    else if (inst.state === 'idle') bubble = ZZZ;
    // The owner's new request takes the place of the calm bubbles, never of waiting or error
    if (controller.prompted(id) && inst.state !== 'waiting' && inst.state !== 'error') bubble = PROMPT_BUBBLE;
    const n = shortName(inst, byType.get(inst.type) ?? 1);
    const full = displayName(inst, byType.get(inst.type) ?? 1);
    const extra = inst.label && !inst.main ? inst.label : null;
    const google = inst.state === 'working' && externalWork(inst.type, inst.tool) === 'google';
    const dimmed = inst.state === 'idle' || inst.state === 'done';
    // What asks for attention is never cut, even if it covers a neighbor a bit
    const urgent = inst.state === 'waiting' || inst.state === 'error';
    // With small tiles (phone, full view) each agent is a dot of its state color;
    // the detail is in the cards and shows up when selecting it
    const dot = compact && !selected && !urgent;

    return (
      <div key={id}>
        {bubble && (
          <div
            className={`absolute -translate-x-1/2 -translate-y-full pointer-events-none ${inst.state === 'waiting' ? 'ao-pulse' : ''}`}
            style={{ left: x, top: yHead, zIndex: 40 }}
          >
            <Icon sprite={bubble} scale={iconScale} />
          </div>
        )}
        {dot ? (
          <div className="absolute -translate-x-1/2 pointer-events-none ao-dot" style={{ left: x, top: yFeet, background: color, zIndex: 30 }} title={full} />
        ) : (
        <div className="absolute -translate-x-1/2 pointer-events-none" style={{ left: x, top: yFeet, zIndex: selected || urgent ? 35 : 30, opacity: dimmed ? 0.75 : 1 }}>
          <div className="ao-label" title={full} style={{ borderColor: color, outline: selected ? '2px solid #fff' : undefined, maxWidth: urgent ? undefined : labelWidth }}>
            <div className="flex items-center gap-3">
              {accessoryOf(inst.type) === 'magnifier' && <Icon sprite={MAGNIFIER} scale={Math.max(1, iconScale - 1)} title="lupa" />}
              {google && <Icon sprite={GOOGLE} scale={Math.max(1, iconScale - 1)} title="trabaja en Google Drive" />}
              <span className="ao-name truncate">{n}</span>
              <span className="ao-badge" style={{ background: modelBadge(inst.model).color }} title={`modelo: ${shortModel(inst.model)}`}>
                {modelBadge(inst.model).letter}
              </span>
              {inst.skills.length > 0 && <Icon sprite={STAR} scale={Math.max(1, iconScale - 1)} title={`skills: ${inst.skills.join(', ')}`} />}
            </div>
            {extra && <div className="ao-extra truncate">{extra}</div>}
            <div className="ao-state truncate" style={{ color }}>
              {shortStateText(inst, inst.main ? activeSubagents(inst.session) : 0)}
              {inst.unzoned ? ' · sin zona' : ''}
            </div>
          </div>
        </div>
        )}
      </div>
    );
  }

  // --- Objects ---------------------------------------------------------------
  const objects: React.ReactNode[] = [];
  if (snapshot && proj) {
    const last = <T,>(a: T[]) => a[a.length - 1];
    // The owner's tray on their desk
    const av = os.characters.get(AVATAR_ID);
    const avatarSeat = av?.seatId ? os.seats.get(av.seatId) : null;
    if (avatarSeat) {
      const p = atTile(avatarSeat.seatCol + 2.2, avatarSeat.seatRow + 0.4);
      const o = snapshot.owner;
      objects.push(
        <div key="tray" className="absolute pointer-events-auto" style={{ ...p, zIndex: 32 }} title="Pendientes (pendientes.md) y aprobaciones en espera">
          <div className="ao-object" style={{ borderColor: o.approvals > 0 ? STATE_COLOR.waiting : '#e0b050' }}>
            <Icon sprite={TRAY} scale={iconScale} />
            <span>{o.tasks} pend.</span>
            <span style={{ color: o.approvals > 0 ? STATE_COLOR.waiting : undefined }}>{o.approvals} aprob.</span>
          </div>
        </div>,
      );
    }
    // Wall clock: scheduled run (only if the profile defines one)
    const clock = controller.furniture('CLOCK');
    const run = profile().scheduled_run;
    if (clock && run && snapshot.clock.next) {
      const next = new Date(snapshot.clock.next);
      const days = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'];
      const runAgent = run.agent ?? '';
      const active = snapshot.instances.some((i) => i.type === runAgent && i.state !== 'idle' && i.state !== 'done');
      objects.push(
        <div key="clock" className="absolute -translate-x-1/2" style={{ ...atTile(clock.col + 0.5, clock.row + 2.1), zIndex: 31 }}>
          <div className="ao-object ao-small">
            {snapshot.clock.running ? (
              <span style={{ color: STATE_COLOR.working }}>corrida programada en curso</span>
            ) : (
              <span>
                {active || !runAgent ? '' : `${runAgent} · `}próxima: {days[next.getDay()]} {next.toTimeString().slice(0, 5)}
              </span>
            )}
            <span className="ao-muted">última: {snapshot.clock.last ?? '—'}</span>
          </div>
        </div>,
      );
    }
    // Mailbox (the profile's notice script): on the corridor wall, next to the lounge
    const mail = last(snapshot.objects.mailbox);
    const lit = recent(mail?.ts, now);
    const lounge = controller.rectangle(LOUNGE);
    if (lounge) {
      objects.push(
        <div key="mailbox" className="absolute" style={{ ...atTile(lounge.c1 - 1, lounge.r0 - 0.6), zIndex: 31 }} title="Buzón: avisos del equipo">
          <div className={`ao-object ${lit ? 'ao-glow' : ''}`}>
            <Icon sprite={lit ? MAILBOX_LIT : MAILBOX} scale={iconScale} />
            {mail && <span className={lit ? '' : 'ao-muted'}>{mail.channel ?? 'avisos'}</span>}
          </div>
        </div>,
      );
    }
    // Archive (engram): the bookshelf on the lounge wall
    const archive = os.getLayout().furniture.find((f) => f.type === 'DOUBLE_BOOKSHELF' && os.getLayout().areaTiles?.[(f.row + 2) * os.getLayout().cols + f.col] === LOUNGE);
    const memory = last(snapshot.objects.memory);
    if (archive) {
      const on = recent(memory?.ts, now);
      objects.push(
        <div
          key="archive"
          className={`absolute pointer-events-auto ${on ? 'ao-archive-on' : ''}`}
          style={{ ...atTile(archive.col, archive.row), width: 2 * TILE_SIZE * zoom / dpr, height: 2 * TILE_SIZE * zoom / dpr, zIndex: 29 }}
          title={memory ? `Archivo (engram): última consulta ${memory.tool ?? ''} ${memory.ts.slice(11, 16)}` : 'Archivo (engram y .remember)'}
        />,
      );
    }
    // Main agent checks: tick on its desk
    const check = last(snapshot.objects.checks);
    const main = controller.visibleTokens().find((t) => t.inst.main);
    const mainCh = main ? os.characters.get(main.id) : undefined;
    const mainSeat = mainCh?.seatId ? os.seats.get(mainCh.seatId) : null;
    if (mainSeat && check && recent(check.ts, now)) {
      objects.push(
        <div key="check" className="absolute" style={{ ...atTile(mainSeat.seatCol + 2.2, mainSeat.seatRow + 0.4), zIndex: 33 }}>
          <div className="ao-object ao-small">
            <Icon sprite={TICK} scale={iconScale} />
            <span>{(check.script ?? '').replace(/\.(py|ps1)$/, '')}</span>
          </div>
        </div>,
      );
    }
    // Rooms with the lights off while nobody is active (the ones the profile says)
    for (const zone of profile().floor.lights_off ?? []) {
      const room = controller.rectangle(zone);
      if (room && !controller.zoneActive(zone)) {
        const a = atTile(room.c0, room.r0 - 1);
        const b = atTile(room.c1 + 1, room.r1 + 1);
        objects.push(
          <div key={`lights-${zone}`} className="absolute pointer-events-none" style={{ left: a.left, top: a.top, width: b.left - a.left, height: b.top - a.top, background: 'rgba(5,5,20,0.55)', zIndex: 5 }}>
            <span className="ao-room-off">luces apagadas</span>
          </div>,
        );
      }
    }
    // The project's fixed boards, on the wall of the owner's office: tasks and audits
    const office = controller.rectangle(OWNER);
    if (office && snapshot.boards) {
      const b = snapshot.boards;
      // One column with both boards: fixed spacing in pixels, so they do not overlap with small tiles
      const boards: React.ReactNode[] = [];
      const board = (key: string, name: TabName, content: React.ReactNode, title: string) =>
        boards.push(
          <button key={key} className="ao-board pointer-events-auto" onClick={() => onOpenBoard?.(name)} title={title}>
            {content}
          </button>,
        );
      board(
        'board-tasks',
        'tasks',
        <>
          <span className="ao-board-title">Pendientes</span>
          <span className="ao-board-counts">
            <span style={{ color: STATE_COLOR.working }}>{b.tasks.in_progress.length} en curso</span>
            {!compact && <span style={{ color: STATE_COLOR.waiting }}>{b.tasks.next.length} siguen</span>}
            {!compact && <span style={{ color: STATE_COLOR.done }}>{b.tasks.done.length} hechas</span>}
          </span>
        </>,
        `Tablón de pendientes: ${b.tasks.in_progress.length} en curso, ${b.tasks.next.length} siguen, ${b.tasks.done.length} hechas`,
      );
      board(
        'board-audits',
        'audits',
        <>
          <span className="ao-board-title">Auditorías</span>
          <span className="ao-board-counts">
            <span style={{ color: b.audits.open.length ? STATE_COLOR.error : STATE_COLOR.idle }}>{b.audits.open.length} abiertas</span>
          </span>
        </>,
        `Tablón de auditorías: ${b.audits.open.length} fricciones abiertas, ${b.audits.resolved.length} resueltas`,
      );
      objects.push(
        <div key="boards" className="absolute ao-boards" style={{ ...atTile(office.c0 + 0.15, office.r0 + 1.6), zIndex: 33 }}>
          {boards}
        </div>,
      );
    }
    // Agents deleted from .claude/agents: their spot stays vacant (the server keeps the history)
    const reception = controller.rectangle(RECEPTION);
    if (reception && snapshot.vacancies.length) {
      objects.push(
        <div key="vacancies" className="absolute" style={{ ...atTile(reception.c0 + 0.2, reception.r1 - 0.2), zIndex: 31 }} title="Agentes cuya definición se borró">
          <div className="ao-object ao-small">
            <span>vacantes:</span>
            {snapshot.vacancies.map((v) => (
              <span key={v}>{v}</span>
            ))}
          </div>
        </div>,
      );
    }
    // Today's verifier passes, next to the verification room
    const ver = controller.rectangle(VERIFICATION);
    const passes = Object.entries(snapshot.verification_summary ?? {});
    if (ver && passes.length) {
      objects.push(
        <div key="verifications" className="absolute" style={{ ...atTile(ver.c0 + 4.3, ver.r0 + 0.3), zIndex: 31 }} title="Cruces del verificador hoy, por tipo de documento y ronda">
          <div className="ao-object ao-small">
            <span>cruces hoy:</span>
            {passes.map(([k, v]) => (
              <span key={k}>
                {k} ×{v}
              </span>
            ))}
          </div>
        </div>,
      );
    }
  }

  // Room names
  const rooms: React.ReactNode[] = [];
  if (proj) {
    for (const [zone, text] of Object.entries(profile().floor.rooms)) {
      const r = controller.rectangle(zone);
      if (!r) continue;
      rooms.push(
        <div key={zone} className="absolute ao-room" style={{ ...atTile(r.c0 + 0.2, r.r0 + 0.1), zIndex: 6 }}>
          {text}
        </div>,
      );
    }
  }

  return (
    <div ref={container} className="relative w-full h-full overflow-hidden" style={{ background: '#11111b' }}>
      <OfficeCanvas
        officeState={os}
        onClick={(id) => onSelect(id === AVATAR_ID ? null : controller.keyOf(id))}
        isEditMode={editing}
        editorState={editorState}
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
        showAreas={editing}
        activeAreaLabel={editor.selectedAreaLabel}
      />
      {!editing && (
        <div className="absolute inset-0 pointer-events-none">
          {!compact && rooms}
          {compact ? objects.filter((o) => /^(mailbox|archive|lights|boards)/.test(String((o as { key?: string }).key))) : objects}
          {controller.visibleTokens().map(({ id, inst }) => label(id, inst))}
          {label(AVATAR_ID, null)}
        </div>
      )}
      {mobile && zoomedIn && (
        <button className="ao-button ao-floating" onClick={showAll}>
          Ver todo el piso
        </button>
      )}
      {!mobile && (
      <div className="absolute right-8 bottom-8 z-50 flex items-center gap-8">
        {saveStatus && editing && (
          <span className={saveStatus.status === 'error' ? 'ao-notice' : 'ao-muted'}>
            {saveStatus.status === 'saving'
              ? 'guardando…'
              : saveStatus.status === 'saved'
                ? 'guardado en el layout.json del perfil'
                : `no se guardó: ${saveStatus.detail}`}
          </span>
        )}
        <button className="ao-button" onClick={editor.handleToggleEditMode} title="Editar el piso (se guarda en el layout.json del perfil)">
          {editing ? 'Salir del editor' : 'Editar piso'}
        </button>
      </div>
      )}
      {editing && editor.isDirty && <EditActionBar editor={editor} editorState={editorState} />}
      {editing && (
        <EditorToolbar
          activeTool={editorState.activeTool}
          selectedTileType={editorState.selectedTileType}
          selectedFurnitureType={editorState.placingType}
          selectedFurnitureUid={editorState.selectedFurnitureUid}
          selectedFurnitureColor={
            editorState.selectedFurnitureUid
              ? (os.getLayout().furniture.find((f) => f.uid === editorState.selectedFurnitureUid)?.color ?? null)
              : null
          }
          floorColor={editorState.floorColor}
          wallColor={editorState.wallColor}
          selectedWallSet={editorState.selectedWallSet}
          onToolChange={editor.handleToolChange}
          onTileTypeChange={editor.handleTileTypeChange}
          onFloorColorChange={editor.handleFloorColorChange}
          onWallColorChange={editor.handleWallColorChange}
          onWallSetChange={editor.handleWallSetChange}
          onSelectedFurnitureColorChange={editor.handleSelectedFurnitureColorChange}
          pickedFurnitureColor={editorState.pickedFurnitureColor}
          onPickedFurnitureColorChange={editor.handlePickedFurnitureColorChange}
          onColorPickToggle={editor.handleColorPickToggle}
          onFurnitureTypeChange={editor.handleFurnitureTypeChange}
          loadedAssets={furniture}
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
