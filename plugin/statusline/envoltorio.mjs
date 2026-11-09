#!/usr/bin/env node
// Envoltorio de la statusline para la oficina de agentes.
//
// Claude Code le pasa por stdin el JSON de la statusline. Este script:
//   1. corre la statusline original (la que estaba configurada antes de instalar la oficina) con el mismo
//      stdin y devuelve su salida tal cual, así la terminal se ve igual que siempre;
//   2. si la sesión es de un proyecto registrado en la oficina, guarda en <datos>/statusline/<sesión>.json
//      una foto mínima: modelo, esfuerzo, uso de la ventana de contexto, límites de 5 h y 7 días, costo,
//      líneas y el texto de la línea (sin colores). Nunca guarda prompts ni contenido.
//
// Uso (lo escribe scripts/instalar.py --statusline en ~/.claude/settings.json):
//   node envoltorio.mjs --datos <carpeta común de la oficina>
// La statusline original sale de <datos>/config.json → statusline_original.
// Ante cualquier error en la parte de la oficina, la statusline original se muestra igual.

import { spawnSync } from 'node:child_process';
import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join, normalize, sep } from 'node:path';

function argumento(nombre) {
  const i = process.argv.indexOf(nombre);
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : null;
}

const DATOS = argumento('--datos') || process.env.AGENTS_OFFICE_DATOS || join(homedir(), '.agents-office');

function leerStdin() {
  try {
    return readFileSync(0, 'utf8');
  } catch {
    return '';
  }
}

function leerConfig() {
  try {
    return JSON.parse(readFileSync(join(DATOS, 'config.json'), 'utf8'));
  } catch {
    return {};
  }
}

const norm = (r) => normalize(r).toLowerCase().replace(/[\\/]+$/, '');
function dentroDe(ruta, base) {
  if (!ruta || !base) return false;
  const r = norm(ruta);
  const b = norm(base);
  return r === b || r.startsWith(b + sep) || r.startsWith(b + '/');
}

function proyectoDe(config, carpeta) {
  const candidatos = (config.proyectos || []).filter((p) => p.dir && dentroDe(carpeta, p.dir));
  candidatos.sort((a, b) => b.dir.length - a.dir.length);
  return candidatos[0] || null;
}

function correrOriginal(comando, entrada) {
  if (!comando) return '';
  const r = spawnSync(comando, { input: entrada, shell: true, encoding: 'utf8', timeout: 8000, windowsHide: true });
  return r.stdout || '';
}

const sinColores = (t) => t.replace(/\x1b\[[0-9;?]*[A-Za-z]/g, '').replace(/\x1b\][^\x07]*\x07/g, '');
const numero = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const texto = (v) => (typeof v === 'string' && v.trim() ? v.trim().slice(0, 120) : null);

function foto(d, linea, proyecto) {
  const cw = d.context_window || {};
  const limite = (l) => (l ? { usado: numero(l.used_percentage), reinicia: l.resets_at ?? null } : null);
  return {
    ts: new Date().toISOString(),
    proyecto: proyecto.id,
    sesion: texto(d.session_id),
    modelo: texto(d.model?.display_name) || texto(d.model?.id),
    modelo_id: texto(d.model?.id),
    esfuerzo: texto(d.effort?.level) || texto(d.model?.effort?.level),
    contexto: {
      usado: numero(cw.used_percentage),
      ventana: numero(cw.context_window_size),
      entrada: numero(cw.total_input_tokens) ?? numero(cw.current_usage?.input_tokens),
    },
    limites: { cinco_horas: limite(d.rate_limits?.five_hour), siete_dias: limite(d.rate_limits?.seven_day) },
    costo: numero(d.cost?.total_cost_usd),
    lineas: { agregadas: numero(d.cost?.total_lines_added), quitadas: numero(d.cost?.total_lines_removed) },
    linea: sinColores(linea).replace(/\s+$/, '').slice(0, 400),
  };
}

const entrada = leerStdin();
const config = leerConfig();
const salida = correrOriginal(config.statusline_original, entrada);
process.stdout.write(salida);

try {
  const d = JSON.parse(entrada || '{}');
  const carpeta = d.workspace?.project_dir || d.workspace?.current_dir || d.cwd;
  const proyecto = proyectoDe(config, carpeta);
  const sesion = typeof d.session_id === 'string' && /^[A-Za-z0-9_-]{1,80}$/.test(d.session_id) ? d.session_id : null;
  if (proyecto && sesion) {
    const carpetaFotos = join(DATOS, 'statusline');
    mkdirSync(carpetaFotos, { recursive: true });
    const destino = join(carpetaFotos, `${sesion}.json`);
    writeFileSync(destino + '.tmp', JSON.stringify(foto(d, salida, proyecto)));
    renameSync(destino + '.tmp', destino);
  }
} catch {
  // la statusline ya se mostró: la parte de la oficina nunca la rompe
}
