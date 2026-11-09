// The office tabs. Everything is read-only: the web does not approve permissions, launch
// agents or change documents. If an agent is selected (card or character), the tabs are filtered.
// Visible texts are the UI, so they are Spanish.
import { useEffect, useMemo, useState } from 'react';

import { api } from './api.ts';
import { profile } from './profile.ts';
import { STATE_COLOR, duration } from './states.ts';
import type { Activity, AuditItem, BoardItem, Document, Entries, Instance, Snapshot, Team } from './types.ts';

const TABS = [
  { id: 'approvals', text: 'Aprobaciones' },
  { id: 'tasks', text: 'Pendientes' },
  { id: 'audits', text: 'Auditorías' },
  { id: 'flows', text: 'Flujos' },
  { id: 'activity', text: 'Actividad' },
  { id: 'memory', text: 'Memoria' },
  { id: 'runs', text: 'Corridas' },
  { id: 'catalog', text: 'Catálogo' },
] as const;
export type TabName = (typeof TABS)[number]['id'];
const STORAGE_KEY = 'agents-office.tab';

// --- Utilities ------------------------------------------------------------------------------------

function time(ts: string | null | undefined): string {
  return ts ? ts.slice(11, 19) : '';
}

function date(ts: string | null | undefined): string {
  if (!ts) return '';
  const [y, m, d] = ts.slice(0, 10).split('-');
  return `${d}/${m}/${y}`;
}

function ago(ts: string | null | undefined): string {
  if (!ts) return '';
  return `hace ${duration(Math.max(0, Math.round((Date.now() - Date.parse(ts)) / 1000)))}`;
}

function shortFile(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts.length > 2 ? `${parts[parts.length - 2]}/${parts[parts.length - 1]}` : path;
}

/** Team file data changes little: requested when the panel opens and every minute. */
function useTeam(): Team | null {
  const [team, setTeam] = useState<Team | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () =>
      fetch(api('team'), { cache: 'no-store' })
        .then((r) => (r.ok ? r.json() : null))
        .then((t) => alive && t && setTeam(t as Team))
        .catch(() => undefined);
    load();
    const timer = window.setInterval(load, 60_000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);
  return team;
}

// --- File viewer ------------------------------------------------------------------------------------

function Viewer({ path, onClose }: { path: string; onClose: () => void }) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setText(null);
    setError(null);
    fetch(api(`file?path=${encodeURIComponent(path)}`), { cache: 'no-store' })
      .then(async (r) => {
        const body = (await r.json()) as { text?: string; error?: string };
        if (!r.ok) throw new Error(body.error ?? `HTTP ${r.status}`);
        setText(body.text ?? '');
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [path]);
  return (
    <div className="ao-viewer">
      <div className="ao-viewer-bar">
        <button className="ao-button" onClick={onClose}>
          Volver
        </button>
        <span className="ao-muted truncate" title={path}>
          {path}
        </span>
      </div>
      {error && <p className="ao-notice">No se pudo abrir: {error}</p>}
      {text === null && !error && <p className="ao-muted">Cargando…</p>}
      {text !== null && <pre className="ao-text">{text}</pre>}
    </div>
  );
}

function FileLink({ path, onOpen, children }: { path: string; onOpen: (p: string) => void; children?: React.ReactNode }) {
  return (
    <button className="ao-link" onClick={() => onOpen(path)} title={`Abrir ${path}`}>
      {children ?? shortFile(path)}
    </button>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="ao-empty">{children}</p>;
}

// --- Panels ---------------------------------------------------------------------------------------------

function Approvals({ snapshot, filter, who }: { snapshot: Snapshot; filter: string | null; who: (key: string) => string }) {
  const list = snapshot.approvals.filter((a) => !filter || a.instance === filter);
  return (
    <>
      <p className="ao-note">Solo lectura: los permisos se aprueban o rechazan en la terminal de Claude Code.</p>
      {list.length === 0 && <Empty>No hay permisos pendientes.</Empty>}
      {list.map((a) => (
        <article key={a.instance} className="ao-item" style={{ borderLeftColor: STATE_COLOR.waiting }}>
          <div className="ao-item-title">
            <span>{who(a.instance)}</span>
            <span className="ao-muted">{ago(a.since)}</span>
          </div>
          <div>
            {a.notice === 'agent_needs_input' ? 'pide una respuesta' : 'pide permiso'}
            {a.tool ? ` para ${a.tool}` : ''}
          </div>
          {a.resource && <div className="ao-muted truncate">{a.resource}</div>}
          {a.mode && <div className="ao-muted">modo de permisos: {a.mode}</div>}
        </article>
      ))}
    </>
  );
}

function Flows({ snapshot, filter, onOpen }: { snapshot: Snapshot; filter: string | null; onOpen: (p: string) => void }) {
  const docs = snapshot.documents.filter((d) => !filter || d.history.some((h) => h.instance === filter));
  const color = (d: Document) => (d.blocked ? STATE_COLOR.error : d.owner_wait ? STATE_COLOR.waiting : STATE_COLOR.working);
  return (
    <>
      {docs.length === 0 && <Empty>Hoy no hay documentos en curso{filter ? ' para este agente' : ''}.</Empty>}
      {docs.map((d) => (
        <article key={d.path} className="ao-item" style={{ borderLeftColor: color(d) }}>
          <div className="ao-item-title">
            {d.path.startsWith('drive:') ? <span>{d.path.slice(6)}</span> : <FileLink path={d.path} onOpen={onOpen} />}
            <span className="ao-muted">{time(d.last_write)}</span>
          </div>
          <div className="ao-chip-row">
            <span className="ao-chip">{d.type}</span>
            <span className="ao-chip" style={{ borderColor: color(d), color: color(d) }}>
              {d.stage}
            </span>
            {d.header?.status && (
              <span className="ao-chip">
                {d.header.status}
                {d.header.version ? ` v${d.header.version}` : ''}
              </span>
            )}
            {d.external_pending && <span className="ao-chip">lo hace alguien de afuera</span>}
          </div>
          {d.owner_wait && (
            <div style={{ color: STATE_COLOR.waiting }}>
              {d.owner_wait === 'tasks' ? 'Bloqueado: quedó en pendientes.md' : `Te espera: ${d.owner_wait}`}
            </div>
          )}
          {d.verifications.length > 0 && (
            <div className="ao-muted">
              Verificación: {d.verifications.map((v) => `ronda ${v.label} (${time(v.ts)})`).join(', ')}
            </div>
          )}
          {d.tasks.length > 0 && <div className="ao-muted">En pendientes: {d.tasks.map((t) => t.title).join('; ')}</div>}
        </article>
      ))}
    </>
  );
}

const ACTIVITY_KINDS: Record<string, { text: string; events: string[] }> = {
  tools: { text: 'Herramientas', events: ['PreToolUse', 'PostToolUseFailure'] },
  permissions: { text: 'Permisos', events: ['PermissionRequest', 'PermissionDenied', 'Notification'] },
  lifecycle: { text: 'Inicio y fin', events: ['SessionStart', 'SessionEnd', 'SubagentStart', 'SubagentStop', 'Stop', 'StopFailure'] },
  prompts: { text: 'Pedidos', events: ['UserPromptSubmit'] },
  tasks: { text: 'Tareas', events: ['TaskCreated', 'TaskCompleted'] },
};

const EVENT_TEXT: Record<string, string> = {
  PreToolUse: 'usa',
  PostToolUseFailure: 'falla con',
  PermissionRequest: 'pide permiso para',
  PermissionDenied: 'no recibe permiso para',
  Notification: 'avisa',
  SessionStart: 'abre la sesión',
  SessionEnd: 'cierra la sesión',
  SubagentStart: 'empieza',
  SubagentStop: 'termina',
  Stop: 'termina el turno',
  StopFailure: 'termina con error',
  UserPromptSubmit: 'recibe un pedido',
  TaskCreated: 'crea una tarea',
  TaskCompleted: 'completa una tarea',
};

function ActivityPanel({ snapshot, filter, instances }: { snapshot: Snapshot; filter: string | null; instances: Instance[] }) {
  const [agent, setAgent] = useState<string>('');
  const [kind, setKind] = useState<string>('');
  const chosen = filter ?? (agent || null);
  const events = useMemo(() => {
    const allowed = kind ? new Set(ACTIVITY_KINDS[kind].events) : null;
    return [...snapshot.activity]
      .reverse()
      .filter((a: Activity) => (!chosen || a.instance === chosen) && (!allowed || allowed.has(a.event)))
      .slice(0, 300);
  }, [snapshot.activity, chosen, kind]);
  return (
    <>
      <div className="ao-filters">
        {!filter && (
          <label>
            Agente{' '}
            <select value={agent} onChange={(e) => setAgent(e.target.value)}>
              <option value="">todos</option>
              {instances.map((i) => (
                <option key={i.key} value={i.key}>
                  {i.history_label}
                </option>
              ))}
            </select>
          </label>
        )}
        <label>
          Tipo{' '}
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">todos</option>
            {Object.entries(ACTIVITY_KINDS).map(([k, v]) => (
              <option key={k} value={k}>
                {v.text}
              </option>
            ))}
          </select>
        </label>
      </div>
      {events.length === 0 && <Empty>Sin actividad con estos filtros.</Empty>}
      <ol className="ao-line">
        {events.map((a, k) => (
          <li key={`${a.ts}-${k}`} className={a.event === 'PostToolUseFailure' || a.event === 'StopFailure' ? 'ao-line-error' : ''}>
            <span className="ao-muted">{time(a.ts)}</span> <strong>{a.who}</strong> {EVENT_TEXT[a.event] ?? a.event}
            {a.tool ? ` ${a.tool}` : ''}
            {a.resource && <span className="ao-muted"> · {shortFile(a.resource)}</span>}
          </li>
        ))}
      </ol>
    </>
  );
}

function Column({ title, color, items, empty, details, onOpen }: {
  title: string;
  color: string;
  items: BoardItem[];
  empty: string;
  details: (title: string) => Entries['entries'][number] | undefined;
  onOpen: (p: string) => void;
}) {
  return (
    <section className="ao-column" style={{ borderTopColor: color }}>
      <h3 className="ao-subtitle" style={{ color }}>
        {title} <span className="ao-muted">{items.length}</span>
      </h3>
      {items.length === 0 && <Empty>{empty}</Empty>}
      {items.map((it, k) => {
        const d = it.source === 'file' ? details(it.title) : undefined;
        const head = (
          <span className="ao-item-title">
            <span>{it.title}</span>
            <span className="ao-muted">{it.source === 'session' ? `sesión ${time(it.ts)}` : it.date ? date(it.date) : ''}</span>
          </span>
        );
        return d && (Object.keys(d.fields).length > 0 || d.paths.length > 0) ? (
          <details key={k} className="ao-item">
            <summary>{head}</summary>
            {Object.entries(d.fields).map(([f, v]) => (
              <p key={f}>
                <strong>{f}:</strong> {v}
              </p>
            ))}
            {d.paths.length > 0 && (
              <p className="ao-chip-row">
                {d.paths.map((p) => (
                  <FileLink key={p} path={p} onOpen={onOpen} />
                ))}
              </p>
            )}
          </details>
        ) : (
          <div key={k} className="ao-item">
            {head}
          </div>
        );
      })}
    </section>
  );
}

function Tasks({ snapshot, team, filter, onOpen }: { snapshot: Snapshot; team: Team | null; filter: string | null; onOpen: (p: string) => void }) {
  const t = snapshot.boards.tasks;
  const ofSelection = (items: BoardItem[]) => items.filter((i) => !filter || i.source !== 'session' || i.instance === filter);
  const details = (title: string) => team?.tasks.entries.find((e) => e.title === title);
  return (
    <>
      <p className="ao-note">
        Tu bandeja: lo que está en curso, lo que sigue y lo hecho. Sale de las tareas de la sesión
        {t.path ? (
          <>
            {' '}y de <FileLink path={t.path} onOpen={onOpen} />
          </>
        ) : null}
        .
      </p>
      <div className="ao-columns">
        <Column title="En curso" color={STATE_COLOR.working} items={ofSelection(t.in_progress)} empty="Nada en curso." details={details} onOpen={onOpen} />
        <Column title="Siguen" color={STATE_COLOR.waiting} items={ofSelection(t.next)} empty="No hay nada anotado para después." details={details} onOpen={onOpen} />
        <Column title="Hechas" color={STATE_COLOR.done} items={ofSelection(t.done)} empty="Todavía nada terminado." details={details} onOpen={onOpen} />
      </div>
    </>
  );
}

function Audits({ snapshot, onOpen }: { snapshot: Snapshot; onOpen: (p: string) => void }) {
  const a = snapshot.boards.audits;
  const entry = (f: AuditItem, k: number) => (
    <details key={k} className="ao-item" style={{ borderLeftColor: f.resolved ? STATE_COLOR.done : STATE_COLOR.error }}>
      <summary className="ao-item-title">
        <span>{f.title}</span>
        <span className="ao-muted">{f.date ? date(f.date) : ''}</span>
      </summary>
      {Object.entries(f.details).map(([field, v]) => (
        <p key={field}>
          <strong>{field}:</strong> {v}
        </p>
      ))}
    </details>
  );
  return (
    <>
      <p className="ao-note">
        Fricciones detectadas en el trabajo: lo que trabó, falló o se repite
        {a.path ? (
          <>
            {' '}(<FileLink path={a.path} onOpen={onOpen} />)
          </>
        ) : null}
        .
      </p>
      <h3 className="ao-subtitle" style={{ color: STATE_COLOR.error }}>
        Abiertas <span className="ao-muted">{a.open.length}</span>
      </h3>
      {a.open.length === 0 && <Empty>No hay fricciones abiertas.</Empty>}
      {a.open.map((f, k) => entry({ ...f, resolved: false }, k))}
      {a.resolved.length > 0 && (
        <details className="ao-resolved">
          <summary className="ao-subtitle" style={{ color: STATE_COLOR.done }}>
            Resueltas <span className="ao-muted">{a.resolved.length}</span>
          </summary>
          {a.resolved.map((f, k) => entry({ ...f, resolved: true }, k))}
        </details>
      )}
    </>
  );
}

type SearchResult = { path: string; line: number; text: string };

function Memory({ team, typeFilter, onOpen }: { team: Team | null; typeFilter: string | null; onOpen: (p: string) => void }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const search = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim().length < 2) return;
    fetch(api(`search?q=${encodeURIComponent(query.trim())}`), { cache: 'no-store' })
      .then((r) => r.json())
      .then((d: { results: SearchResult[] }) => setResults(d.results))
      .catch(() => setResults([]));
  };
  const agents = (team?.catalog.agents ?? []).filter((a) => !typeFilter || a.name === typeFilter);
  return (
    <>
      <form className="ao-search" onSubmit={search} role="search">
        <label htmlFor="ao-q" className="ao-subtitle">
          Buscar en los archivos del equipo
        </label>
        <div className="ao-row">
          <input id="ao-q" type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="por ejemplo: retención de datos" />
          <button className="ao-button" type="submit">
            Buscar
          </button>
        </div>
      </form>
      {results && results.length === 0 && <Empty>Sin coincidencias en lo que la oficina ya leyó.</Empty>}
      {results?.map((r, k) => (
        <div key={k} className="ao-result">
          <FileLink path={r.path} onOpen={onOpen}>
            {shortFile(r.path)}:{r.line}
          </FileLink>
          <div className="ao-muted">{r.text}</div>
        </div>
      ))}
      <h3 className="ao-subtitle">Definición de cada agente</h3>
      {agents.map((a) => (
        <div key={a.name} className="ao-result">
          <FileLink path={a.file} onOpen={onOpen}>
            {a.name}
          </FileLink>
          {a.vacant && <span className="ao-notice"> vacante</span>}
        </div>
      ))}
      {team && team.remember.length > 0 && (
        <>
          <h3 className="ao-subtitle">Notas de .remember</h3>
          {team.remember.map((r) => (
            <div key={r.path} className="ao-result">
              <FileLink path={r.path} onOpen={onOpen} />
              <span className="ao-muted"> {r.entries.length} entradas</span>
            </div>
          ))}
        </>
      )}
    </>
  );
}

const STATUS_KIND_TEXT: Record<string, string> = { run: 'corrida', changes: 'cambios', other: 'otro' };

function Runs({ snapshot, team, onOpen }: { snapshot: Snapshot; team: Team | null; onOpen: (p: string) => void }) {
  const run = profile().scheduled_run;
  const status = team?.status ?? [];
  return (
    <>
      {run ? (
        <article className="ao-item" style={{ borderLeftColor: snapshot.clock.running ? STATE_COLOR.working : STATE_COLOR.idle }}>
          <div className="ao-item-title">
            <span>Corrida programada{run.agent ? ` (${run.agent})` : ''}</span>
            {snapshot.clock.running && <span style={{ color: STATE_COLOR.working }}>en curso</span>}
          </div>
          <div>Próxima: {snapshot.clock.next ? `${date(snapshot.clock.next)} ${snapshot.clock.next.slice(11, 16)}` : '—'}</div>
          <div>Última: {snapshot.clock.last ? date(snapshot.clock.last) : 'sin registro'}</div>
        </article>
      ) : (
        <Empty>El perfil no define una corrida programada.</Empty>
      )}
      <h3 className="ao-subtitle">Informes de corridas y cambios</h3>
      {team && status.length === 0 && <Empty>No hay informes en la carpeta de status.</Empty>}
      {status.slice(0, 40).map((s) => (
        <div key={s.path} className="ao-result">
          <span className="ao-muted">{s.date ? date(s.date) : ''}</span> <span className="ao-chip">{STATUS_KIND_TEXT[s.kind] ?? s.kind}</span>{' '}
          <FileLink path={s.path} onOpen={onOpen}>
            {s.title ?? shortFile(s.path)}
          </FileLink>
        </div>
      ))}
    </>
  );
}

function Catalog({ snapshot, team, typeFilter, onOpen }: { snapshot: Snapshot; team: Team | null; typeFilter: string | null; onOpen: (p: string) => void }) {
  const agents = team?.catalog.agents ?? [];
  return (
    <>
      {snapshot.candidates.length > 0 && (
        <>
          <h3 className="ao-subtitle">Posibles agentes nuevos</h3>
          <p className="ao-note">
            Lanzamientos de agentes generales con descripciones parecidas (3 o más en 14 días). Si se repiten, puede convenir un agente propio.
          </p>
          {snapshot.candidates.map((c, k) => (
            <article key={k} className="ao-item" style={{ borderLeftColor: '#e0b050' }}>
              <div className="ao-item-title">
                <span>{c.words.join(' · ')}</span>
                <span className="ao-muted">{c.launches} veces</span>
              </div>
              {c.descriptions.map((d) => (
                <div key={d} className="ao-muted">
                  “{d}”
                </div>
              ))}
              <div className="ao-muted">
                con {c.types.join(', ')} · último {date(c.last)}
              </div>
            </article>
          ))}
        </>
      )}
      <h3 className="ao-subtitle">Agentes ({agents.length})</h3>
      {!team && <Empty>Cargando…</Empty>}
      {agents.map((a) => (
        <article
          key={a.name}
          className={`ao-item ${typeFilter === a.name ? 'ao-item-selected' : ''}`}
          style={{ borderLeftColor: a.vacant ? STATE_COLOR.error : a.unzoned ? STATE_COLOR.waiting : STATE_COLOR.idle }}
        >
          <div className="ao-item-title">
            <FileLink path={a.file} onOpen={onOpen}>
              {a.name}
            </FileLink>
            <span className="ao-muted">
              {[a.model, a.effort].filter(Boolean).join(' · ')}
            </span>
          </div>
          {a.description && <div className="ao-muted ao-two-lines">{a.description}</div>}
          <div className="ao-chip-row">
            <span className="ao-chip">{a.unzoned ? 'sin zona' : (profile().floor.rooms[a.zone] ?? a.zone)}</span>
            {a.vacant && <span className="ao-chip" style={{ color: STATE_COLOR.error }}>vacante: se borró su definición</span>}
          </div>
        </article>
      ))}
      <h3 className="ao-subtitle">Skills ({team?.catalog.skills.length ?? 0})</h3>
      {(team?.catalog.skills ?? []).map((s) => (
        <div key={s.name} className="ao-result">
          <FileLink path={s.file} onOpen={onOpen}>
            {s.name}
          </FileLink>
          {s.description && <div className="ao-muted ao-two-lines">{s.description}</div>}
        </div>
      ))}
    </>
  );
}

// --- Container --------------------------------------------------------------------------------------------

export function Tabs({ selection, snapshot, onClear, requested }: {
  selection: string | null;
  snapshot: Snapshot | null;
  onClear: () => void;
  /** Tab another part of the screen asked to open (for example, tapping a board on the floor). */
  requested?: { tab: TabName; n: number } | null;
}) {
  const [active, setActive] = useState<TabName>(() => {
    try {
      const saved = window.localStorage.getItem(STORAGE_KEY) as TabName | null;
      return saved && TABS.some((t) => t.id === saved) ? saved : 'approvals';
    } catch {
      return 'approvals';
    }
  });
  const [open, setOpen] = useState<string | null>(null);
  const team = useTeam();
  useEffect(() => {
    if (requested) {
      setActive(requested.tab);
      setOpen(null);
    }
  }, [requested]);
  const choose = (t: TabName) => {
    setActive(t);
    setOpen(null);
    try {
      window.localStorage.setItem(STORAGE_KEY, t);
    } catch {
      /* without local storage the tab is not remembered */
    }
  };
  const inst = snapshot?.instances.find((i) => i.key === selection) ?? null;
  const who = (key: string) => snapshot?.instances.find((i) => i.key === key)?.history_label ?? key;
  const counters: Partial<Record<TabName, number>> = {
    approvals: snapshot?.approvals.length ?? 0,
    tasks: snapshot?.boards.tasks.in_progress.length ?? 0,
    audits: snapshot?.boards.audits.open.length ?? 0,
    flows: snapshot?.documents.filter((d) => d.owner_wait).length ?? 0,
    catalog: snapshot?.candidates.length ?? 0,
  };
  return (
    <aside className="ao-tabs">
      <nav className="ao-tabs-nav" role="tablist" aria-label="Paneles">
        {TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={t.id === active} className={`ao-tab ${t.id === active ? 'ao-tab-selected' : ''}`} onClick={() => choose(t.id)}>
            {t.text}
            {(counters[t.id] ?? 0) > 0 && <span className="ao-counter">{counters[t.id]}</span>}
          </button>
        ))}
      </nav>
      {inst && (
        <div className="ao-filter">
          Filtrado por <strong>{inst.history_label}</strong>
          <button className="ao-link" onClick={onClear}>
            ver todos
          </button>
        </div>
      )}
      <div className="ao-panel" role="tabpanel">
        {open ? (
          <Viewer path={open} onClose={() => setOpen(null)} />
        ) : !snapshot ? (
          <Empty>Cargando…</Empty>
        ) : active === 'approvals' ? (
          <Approvals snapshot={snapshot} filter={selection} who={who} />
        ) : active === 'flows' ? (
          <Flows snapshot={snapshot} filter={selection} onOpen={setOpen} />
        ) : active === 'activity' ? (
          <ActivityPanel snapshot={snapshot} filter={selection} instances={snapshot.instances} />
        ) : active === 'tasks' ? (
          <Tasks snapshot={snapshot} team={team} filter={selection} onOpen={setOpen} />
        ) : active === 'audits' ? (
          <Audits snapshot={snapshot} onOpen={setOpen} />
        ) : active === 'memory' ? (
          <Memory team={team} typeFilter={inst?.type ?? null} onOpen={setOpen} />
        ) : active === 'runs' ? (
          <Runs snapshot={snapshot} team={team} onOpen={setOpen} />
        ) : (
          <Catalog snapshot={snapshot} team={team} typeFilter={inst?.type ?? null} onOpen={setOpen} />
        )}
      </div>
    </aside>
  );
}
