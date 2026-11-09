// Shape of the snapshot the server builds (server/office.py → /api/state and /api/stream).
// Only the fields the floor and the tabs use are typed; the rest travels anyway.

export type State =
  | 'working'
  | 'waiting'
  | 'error'
  | 'handing_off'
  | 'waiting_subagents'
  | 'thinking'
  | 'done'
  | 'idle';

export type Animation = 'read' | 'write' | 'wait' | 'error' | 'idle' | 'leave' | 'hand_off' | 'wait_subagents' | 'think';

export interface Instance {
  key: string;
  session: string;
  type: string;
  main: boolean;
  general: boolean;
  number: number;
  label: string | null;
  history_label: string;
  state: State;
  since: string | null;
  seconds_in_state: number | null;
  animation: Animation;
  model: string | null;
  model_source: string | null;
  effort: string | null;
  tool: string | null;
  resource: string | null;
  document: string | null;
  wait: { kind?: 'permission' | 'answer'; tool?: string; resource?: string; since?: string | null } | null;
  skills: string[];
  start: string | null;
  end: string | null;
  origin: string | null;
  zone: string;
  unzoned: boolean;
  role: string | null;
}

export interface FloorObject {
  ts: string;
  instance: string;
  channel?: string;
  script?: string;
  path?: string;
  tool?: string;
}

export interface Session {
  id: string;
  start: string | null;
  end: string | null;
  origin: string;
  model: string | null;
  last_event: string | null;
  last_user_prompt: string | null;
}

export interface Snapshot {
  generated: string;
  version: number;
  main: (Instance & { restart_notice: string[] | null }) | null;
  current_session: Session | null;
  sessions: Session[];
  instances: Instance[];
  approvals: Approval[];
  objects: { mailbox: FloorObject[]; checks: FloorObject[]; memory: FloorObject[] };
  verification_summary: Record<string, number>;
  notices: Array<{ session: string; agents: string[] }>;
  vacancies: string[];
  owner: {
    tasks: number;
    approvals: number;
    last_prompt: string | null;
    waits: Array<{ path: string; wait: string }>;
  };
  clock: { next: string | null; last: string | null; running: boolean };
  health: { hook_errors_24h: number; discarded_lines: number };
  documents: Document[];
  verifications: Verification[];
  activity: Activity[];
  session_tasks: SessionTask[];
  candidates: Candidate[];
  boards: Boards;
  statusline: Statusline | null;
}

/** What the session's statusline saw (plugin/statusline/wrapper.mjs). */
export interface Statusline {
  ts: string;
  seconds: number | null;
  session: string | null;
  model: string | null;
  effort: string | null;
  context: { used: number | null; window: number | null; input: number | null };
  limits: { five_hour: { used: number | null } | null; seven_day: { used: number | null } | null };
  cost: number | null;
  line: string;
}

export interface Characters {
  avatar: number;
  assignable: number[];
}

export interface SpritesConfig {
  agents?: Record<string, { sprite?: number }>;
}

// --- Tab data -----------------------------------------------------------------------------------

export interface Approval {
  instance: string;
  tool: string | null;
  resource: string | null;
  since: string | null;
  mode: string | null;
  notice?: string;
}

export interface Verification {
  ts: string;
  instance: string;
  who: string;
  report: string;
  documents: string[];
  document_type: string;
  round: number | null;
  label: string;
  conclusive: boolean;
}

export interface Document {
  path: string;
  type: string;
  stage: string;
  history: Array<{ ts: string; instance: string; agent: string; who: string; action: string }>;
  verifications: Verification[];
  last_write: string | null;
  external_pending: boolean;
  header: { title: string | null; status: string | null; version: string | null; last_review: string | null } | null;
  tasks: Array<{ title: string }>;
  blocked: boolean;
  owner_wait: string | null;
}

export interface Activity {
  ts: string;
  instance: string;
  event: string;
  tool: string | null;
  resource: string | null;
  who: string;
}

export interface SessionTask {
  session: string;
  title: string | null;
  created: string | null;
  completed: string | null;
  instance: string;
}

export interface Candidate {
  launches: number;
  types: string[];
  words: string[];
  descriptions: string[];
  last: string;
}

export interface Entries {
  path: string | null;
  entries: Array<{ date: string | null; title: string; fields: Record<string, string>; text: string; paths: string[] }>;
  raw?: string;
  unread?: boolean;
}

export interface Team {
  tasks: Entries;
  frictions: Entries;
  decisions: Entries;
  remember: Array<{ path: string; entries: Array<{ title: string; text: string }>; raw?: string }>;
  status: Array<{ path: string; date: string | null; kind: string; variant: string | null; title: string | null }>;
  catalog: {
    agents: Array<{
      name: string;
      file: string;
      description: string | null;
      model: string | null;
      effort: string | null;
      tools: string[] | null;
      zone: string;
      unzoned: boolean;
      vacant: boolean;
    }>;
    skills: Array<{ name: string; description: string | null; file: string }>;
  };
}

export interface BoardItem {
  title: string;
  source: 'session' | 'file';
  date?: string | null;
  instance?: string;
  ts?: string | null;
}

export interface AuditItem {
  title: string;
  date: string | null;
  status: string;
  details: Record<string, string>;
  resolved?: boolean;
}

export interface Boards {
  tasks: { path: string | null; in_progress: BoardItem[]; next: BoardItem[]; done: BoardItem[] };
  audits: { path: string | null; open: AuditItem[]; resolved: AuditItem[] };
}
