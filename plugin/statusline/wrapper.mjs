#!/usr/bin/env node
// Statusline wrapper for the agents office.
//
// Claude Code passes the statusline JSON on stdin. This script:
//   1. runs the original statusline (the one configured before installing the office) with the same
//      stdin and returns its output as is, so the terminal looks the same as always;
//   2. if the session belongs to a project registered in the office, saves in <data>/statusline/<session>.json
//      a minimal snapshot: model, effort, context window usage, 5 h and 7 day limits, cost,
//      lines and the line text (without colors). It never stores prompts or content.
//
// Usage (scripts/install.py --statusline writes it in ~/.claude/settings.json):
//   node wrapper.mjs --data <office common folder>
// The original statusline comes from <data>/config.json → original_statusline.
// On any error in the office part, the original statusline is shown anyway.

import { spawnSync } from 'node:child_process';
import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join, normalize, sep } from 'node:path';

function arg(name) {
  const i = process.argv.indexOf(name);
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : null;
}

const DATA = arg('--data') || process.env.AGENTS_OFFICE_DATA || join(homedir(), '.agents-office');

function readStdin() {
  try {
    return readFileSync(0, 'utf8');
  } catch {
    return '';
  }
}

function readConfig() {
  try {
    return JSON.parse(readFileSync(join(DATA, 'config.json'), 'utf8'));
  } catch {
    return {};
  }
}

const norm = (p) => normalize(p).toLowerCase().replace(/[\\/]+$/, '');
function inside(path, base) {
  if (!path || !base) return false;
  const p = norm(path);
  const b = norm(base);
  return p === b || p.startsWith(b + sep) || p.startsWith(b + '/');
}

function projectOf(config, folder) {
  const candidates = (config.projects || []).filter((p) => p.dir && inside(folder, p.dir));
  candidates.sort((a, b) => b.dir.length - a.dir.length);
  return candidates[0] || null;
}

function runOriginal(command, input) {
  if (!command) return '';
  const r = spawnSync(command, { input, shell: true, encoding: 'utf8', timeout: 8000, windowsHide: true });
  return r.stdout || '';
}

const stripColors = (t) => t.replace(/\x1b\[[0-9;?]*[A-Za-z]/g, '').replace(/\x1b\][^\x07]*\x07/g, '');
const number = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const text = (v) => (typeof v === 'string' && v.trim() ? v.trim().slice(0, 120) : null);

function snapshot(d, line, project) {
  const cw = d.context_window || {};
  const limit = (l) => (l ? { used: number(l.used_percentage), resets_at: l.resets_at ?? null } : null);
  return {
    ts: new Date().toISOString(),
    project: project.id,
    session: text(d.session_id),
    model: text(d.model?.display_name) || text(d.model?.id),
    model_id: text(d.model?.id),
    effort: text(d.effort?.level) || text(d.model?.effort?.level),
    context: {
      used: number(cw.used_percentage),
      window: number(cw.context_window_size),
      input: number(cw.total_input_tokens) ?? number(cw.current_usage?.input_tokens),
    },
    limits: { five_hour: limit(d.rate_limits?.five_hour), seven_day: limit(d.rate_limits?.seven_day) },
    cost: number(d.cost?.total_cost_usd),
    lines: { added: number(d.cost?.total_lines_added), removed: number(d.cost?.total_lines_removed) },
    line: stripColors(line).replace(/\s+$/, '').slice(0, 400),
  };
}

const input = readStdin();
const config = readConfig();
const output = runOriginal(config.original_statusline, input);
process.stdout.write(output);

try {
  const d = JSON.parse(input || '{}');
  const folder = d.workspace?.project_dir || d.workspace?.current_dir || d.cwd;
  const project = projectOf(config, folder);
  const session = typeof d.session_id === 'string' && /^[A-Za-z0-9_-]{1,80}$/.test(d.session_id) ? d.session_id : null;
  if (project && session) {
    const snapshots = join(DATA, 'statusline');
    mkdirSync(snapshots, { recursive: true });
    const target = join(snapshots, `${session}.json`);
    writeFileSync(target + '.tmp', JSON.stringify(snapshot(d, output, project)));
    renameSync(target + '.tmp', target);
  }
} catch {
  // the statusline was already shown: the office part never breaks it
}
