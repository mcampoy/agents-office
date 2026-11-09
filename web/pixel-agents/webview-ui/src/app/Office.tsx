// Office screen: header (main agent), floor on the left, tabs on the right and cards at the bottom.
// Visible texts are the UI, so they are Spanish.
import { useEffect, useMemo, useRef, useState } from 'react';

import { OfficeState } from '../office/engine/officeState.js';
import { currentProject, goToProject, type ProjectListing } from './api.ts';
import type { Connection, Resources } from './data.ts';
import { useSnapshot } from './data.ts';
import { Floor } from './Floor.tsx';
import { FloorController, visibleOnFloor } from './floorController.ts';
import { profile } from './profile.ts';
import { STATE_COLOR, displayName, duration, group, shortModel, stateText } from './states.ts';
import { type TabName, Tabs } from './Tabs.tsx';
import type { Instance, Snapshot, Statusline } from './types.ts';

function activeSubagents(snapshot: Snapshot, session: string): number {
  return snapshot.instances.filter((x) => !x.main && x.session === session && !['done', 'idle'].includes(x.state)).length;
}

function currentTask(i: Instance): string {
  if (i.state === 'waiting' && i.wait) return `pide permiso: ${i.wait.tool ?? ''} ${i.wait.resource ?? ''}`.trim();
  const parts = [i.tool, i.resource ?? i.document].filter(Boolean);
  return parts.join(' · ') || '—';
}

function count(snapshot: Snapshot | null) {
  const counts = { working: 0, waiting: 0, error: 0, idle: 0 };
  for (const i of snapshot?.instances ?? []) if (visibleOnFloor(i)) counts[group(i.state)]++;
  return counts;
}

/** Text of the notice that agent definitions changed after the session started. */
function restartNotice(agents: string[] | null | undefined): string | null {
  return agents && agents.length ? `Reiniciar la sesión para aplicar los cambios en: ${agents.join(', ')}` : null;
}

/** Narrow screen (phone in portrait). */
function useIsMobile(): boolean {
  const query = '(max-width: 760px)';
  const [mobile, setMobile] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const change = () => setMobile(mq.matches);
    mq.addEventListener('change', change);
    return () => mq.removeEventListener('change', change);
  }, []);
  return mobile;
}

type View = 'floor' | 'panels';
const VIEWS: Array<{ id: View; text: string }> = [
  { id: 'floor', text: 'Piso' },
  { id: 'panels', text: 'Paneles' },
];

/** Active view on the phone, in the URL hash: the Back button returns to the previous one. */
function useView(): [View, (v: View) => void] {
  const read = (): View => {
    const h = window.location.hash.replace('#', '');
    return VIEWS.some((v) => v.id === h) ? (h as View) : 'floor';
  };
  const [view, setView] = useState<View>(read);
  useEffect(() => {
    const change = () => setView(read());
    window.addEventListener('hashchange', change);
    return () => window.removeEventListener('hashchange', change);
  }, []);
  const go = (v: View) => {
    if (v !== read()) window.location.hash = v;
  };
  return [view, go];
}

function MobileHeader({ snapshot, connection, projects }: { snapshot: Snapshot | null; connection: Connection; projects: ProjectListing[] }) {
  const p = snapshot?.main ?? null;
  const counts = count(snapshot);
  const notice = restartNotice(p?.restart_notice);
  return (
    <header className="ao-header-mobile">
      {projects.length > 1 && (
        <div className="ao-row">
          <ProjectSelector projects={projects} />
        </div>
      )}
      <div className="ao-row">
        <span className="ao-name-large">{profile().main_agent}</span>
        {p ? (
          <>
            <span className="ao-pill" style={{ background: STATE_COLOR[p.state] }}>
              {stateText(p, snapshot ? activeSubagents(snapshot, p.session) : 0)}
            </span>
            <span className="ao-muted">{duration(p.seconds_in_state)}</span>
          </>
        ) : (
          <span className="ao-muted">{snapshot ? 'sin sesión abierta' : 'cargando…'}</span>
        )}
        <span className={`ao-connection ${connection === 'en vivo' ? 'ao-muted' : 'ao-notice'}`} title={connection}>
          ●
        </span>
      </div>
      {snapshot?.statusline && (
        <div className="ao-row">
          <SessionInfo s={snapshot.statusline} compact />
        </div>
      )}
      <div className="ao-row ao-counts">
        <span style={{ color: STATE_COLOR.working }}>{counts.working} trabajan</span>
        <span style={{ color: STATE_COLOR.waiting }}>{counts.waiting} esperan</span>
        <span style={{ color: STATE_COLOR.error }}>{counts.error} error</span>
        <span style={{ color: STATE_COLOR.idle }}>{counts.idle} en pausa</span>
      </div>
      {notice && <div className="ao-notice ao-band">{notice}</div>}
      {snapshot && snapshot.health.hook_errors_24h > 0 && (
        <div className="ao-notice ao-band">El hook de captura falló {snapshot.health.hook_errors_24h} veces en 24 h</div>
      )}
    </header>
  );
}

function usageColor(p: number | null | undefined): string {
  if (p === null || p === undefined) return STATE_COLOR.idle;
  if (p >= 90) return STATE_COLOR.error;
  if (p >= 70) return STATE_COLOR.waiting;
  return STATE_COLOR.done;
}

/** The session's model, effort, context and limits, according to the statusline. */
function SessionInfo({ s, compact = false }: { s: Statusline | null; compact?: boolean }) {
  if (!s) return null;
  const ctx = s.context?.used;
  const stale = (s.seconds ?? 0) > 15 * 60;
  const title = `Statusline de la sesión, hace ${duration(s.seconds)}${stale ? ' (puede estar desactualizada)' : ''}`;
  return (
    <span className="ao-session" title={title} style={{ opacity: stale ? 0.6 : 1 }}>
      {s.model && <span>{s.model}</span>}
      {s.effort && <span className="ao-muted">{s.effort}</span>}
      {ctx !== null && ctx !== undefined && (
        <span className="ao-ctx" aria-label={`contexto usado ${Math.round(ctx)}%`}>
          ctx{' '}
          <span className="ao-bar" aria-hidden="true">
            <span style={{ width: `${Math.min(100, ctx)}%`, background: usageColor(ctx) }} />
          </span>{' '}
          <span style={{ color: usageColor(ctx) }}>{Math.round(ctx)}%</span>
        </span>
      )}
      {!compact && s.limits?.five_hour?.used != null && (
        <span>
          5h <span style={{ color: usageColor(s.limits.five_hour.used) }}>{Math.round(s.limits.five_hour.used)}%</span>
        </span>
      )}
      {!compact && s.limits?.seven_day?.used != null && (
        <span>
          7d <span style={{ color: usageColor(s.limits.seven_day.used) }}>{Math.round(s.limits.seven_day.used)}%</span>
        </span>
      )}
    </span>
  );
}

/** Project selector: only if the office follows more than one. Changing reloads the page with ?p=<id>. */
function ProjectSelector({ projects }: { projects: ProjectListing[] }) {
  if (projects.length < 2) return <div className="ao-mark">{profile().name}</div>;
  return (
    <select className="ao-selector" value={currentProject() ?? ''} onChange={(e) => goToProject(e.target.value)} aria-label="Proyecto">
      {projects.map((p) => (
        <option key={p.id} value={p.id}>
          {p.name}
          {p.active ? ` · ${p.active} activos` : ''}
        </option>
      ))}
    </select>
  );
}

function Header({ snapshot, connection, projects }: { snapshot: Snapshot | null; connection: Connection; projects: ProjectListing[] }) {
  const p = snapshot?.main ?? null;
  const counts = count(snapshot);
  const notice = restartNotice(p?.restart_notice);
  return (
    <header className="ao-header">
      <div className="flex items-center gap-12 min-w-0">
        <ProjectSelector projects={projects} />
        {p ? (
          <div className="flex items-center gap-10 min-w-0">
            <span className="ao-name-large">{profile().main_agent}</span>
            <span className="ao-pill" style={{ background: STATE_COLOR[p.state] }}>
              {stateText(p, snapshot ? activeSubagents(snapshot, p.session) : 0)}
            </span>
            <span className="ao-muted">hace {duration(p.seconds_in_state)}</span>
            <span className="truncate" title={currentTask(p)}>
              {currentTask(p)}
            </span>
            {notice && <span className="ao-notice">{notice}</span>}
            <SessionInfo s={snapshot?.statusline ?? null} />
          </div>
        ) : (
          <span className="ao-muted">{snapshot ? `Sin sesión de ${profile().main_agent} abierta` : 'Cargando…'}</span>
        )}
      </div>
      <div className="flex items-center gap-12 shrink-0">
        <span style={{ color: STATE_COLOR.working }}>{counts.working} trabajan</span>
        <span style={{ color: STATE_COLOR.waiting }}>{counts.waiting} esperan</span>
        <span style={{ color: STATE_COLOR.error }}>{counts.error} con error</span>
        <span style={{ color: STATE_COLOR.idle }}>{counts.idle} ociosos o terminados</span>
        {snapshot && snapshot.health.hook_errors_24h > 0 && (
          <span className="ao-notice" title="Errores del hook de captura en las últimas 24 h (errors.log en la carpeta de datos)">
            hook: {snapshot.health.hook_errors_24h} errores
          </span>
        )}
        <span className={connection === 'en vivo' ? 'ao-muted' : 'ao-notice'}>● {connection}</span>
      </div>
      {snapshot?.statusline?.line && (
        <div className="ao-statusline" title="Tu statusline, tal como se ve en la terminal">
          {snapshot.statusline.line}
        </div>
      )}
    </header>
  );
}

function Cards({
  snapshot,
  selection,
  onSelect,
  layout = 'bar',
}: {
  snapshot: Snapshot | null;
  selection: string | null;
  onSelect: (key: string | null) => void;
  /** bar: horizontal row (desktop and the floor strip on the phone); list: full-screen column */
  layout?: 'bar' | 'list';
}) {
  const instances = (snapshot?.instances ?? []).filter(visibleOnFloor);
  const byType = new Map<string, number>();
  for (const i of instances) byType.set(i.type, (byType.get(i.type) ?? 0) + 1);
  // What needs attention first
  const order = { waiting: 0, error: 1, handing_off: 2, working: 3, thinking: 4, waiting_subagents: 5, done: 6, idle: 7 };
  const sorted = [...instances].sort((a, b) => Number(b.main) - Number(a.main) || order[a.state] - order[b.state]);
  return (
    <footer className={layout === 'list' ? 'ao-list' : 'ao-cards'}>
      {sorted.length === 0 && <span className="ao-muted px-12">Sin agentes en la oficina.</span>}
      {sorted.map((i) => (
        <button
          key={i.key}
          className={`ao-card ${selection === i.key ? 'ao-card-selected' : ''}`}
          style={{ borderColor: STATE_COLOR[i.state] }}
          onClick={() => onSelect(selection === i.key ? null : i.key)}
          title={i.role ?? undefined}
        >
          <div className="flex items-center justify-between gap-6">
            <span className="ao-name truncate">{displayName(i, byType.get(i.type) ?? 1)}</span>
            <span className="ao-model" title={`modelo (${i.model_source ?? '?'})`}>
              {shortModel(i.model)}
            </span>
          </div>
          <div className="ao-role truncate">{i.label && !i.main ? i.label : (i.role ?? (i.general ? 'agente general' : ''))}</div>
          <div className="flex items-center justify-between gap-6">
            <span className="ao-state" style={{ color: STATE_COLOR[i.state] }}>
              ■ {stateText(i, i.main && snapshot ? activeSubagents(snapshot, i.session) : 0)}
            </span>
            <span className="ao-muted">{duration(i.seconds_in_state)}</span>
          </div>
        </button>
      ))}
    </footer>
  );
}

export function Office({ resources }: { resources: Resources }) {
  const { snapshot, connection } = useSnapshot();
  const [selection, setSelection] = useState<string | null>(null);
  const mobile = useIsMobile();
  const [view, goTo] = useView();
  const [requested, setRequested] = useState<{ tab: TabName; n: number } | null>(null);
  const openBoard = (tab: TabName) => {
    setRequested((r) => ({ tab, n: (r?.n ?? 0) + 1 }));
    if (mobile) goTo('panels');
  };
  const os = useMemo(() => new OfficeState(resources.layout), [resources]);
  const controller = useMemo(() => new FloorController(os, resources.characters, resources.sprites), [os, resources]);
  const first = useRef(true);

  useEffect(() => {
    if (!snapshot) return;
    controller.sync(snapshot, first.current);
    first.current = false;
  }, [snapshot, controller]);

  if (mobile) {
    return (
      <div className="ao-screen-mobile">
        <MobileHeader snapshot={snapshot} connection={connection} projects={resources.projects} />
        <main className="ao-view">
          {view === 'floor' && (
            <>
              {/* The plan on top with just the right height; the agents below. Tapping one focuses it on the plan */}
              <section className="ao-floor ao-floor-mobile">
                <Floor os={os} controller={controller} snapshot={snapshot} furniture={resources.furniture} selection={selection} onSelect={setSelection} mobile onOpenBoard={openBoard} />
              </section>
              <Cards snapshot={snapshot} selection={selection} onSelect={setSelection} layout="list" />
            </>
          )}
          {view === 'panels' && <Tabs selection={selection} snapshot={snapshot} onClear={() => setSelection(null)} requested={requested} />}
        </main>
        <nav className="ao-nav" aria-label="Vistas" style={{ gridTemplateColumns: `repeat(${VIEWS.length}, 1fr)` }}>
          {VIEWS.map((v) => (
            <button key={v.id} className={`ao-nav-button ${view === v.id ? 'ao-nav-selected' : ''}`} aria-current={view === v.id ? 'page' : undefined} onClick={() => goTo(v.id)}>
              {v.text}
            </button>
          ))}
        </nav>
      </div>
    );
  }

  return (
    <div className="ao-screen">
      <Header snapshot={snapshot} connection={connection} projects={resources.projects} />
      <main className="ao-center">
        <section className="ao-floor">
          <Floor os={os} controller={controller} snapshot={snapshot} furniture={resources.furniture} selection={selection} onSelect={setSelection} onOpenBoard={openBoard} />
        </section>
        <Tabs selection={selection} snapshot={snapshot} onClear={() => setSelection(null)} requested={requested} />
      </main>
      <Cards snapshot={snapshot} selection={selection} onSelect={setSelection} />
    </div>
  );
}
