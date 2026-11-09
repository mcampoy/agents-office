// Las siete pestañas de la oficina (fase 4). Todo es de solo lectura: la web no aprueba permisos, no lanza
// agentes ni cambia documentos. Si hay un agente seleccionado (tarjeta o personaje), las pestañas se filtran.
import { useEffect, useMemo, useState } from 'react';

import { api } from './api.ts';
import { COLOR_ESTADO, duracion } from './estados.ts';
import { perfil } from './perfil.ts';
import type { Actividad, Bloques, Documento, Equipo, Foto, Instancia, TablonAuditoria, TablonItem } from './tipos.ts';

const PESTANAS = ['Aprobaciones', 'Pendientes', 'Auditorías', 'Flujos', 'Actividad', 'Memoria', 'Corridas', 'Catálogo'] as const;
export type Pestana = (typeof PESTANAS)[number];

// --- Utilidades -----------------------------------------------------------------------------------

function hora(ts: string | null | undefined): string {
  return ts ? ts.slice(11, 19) : '';
}

function fecha(ts: string | null | undefined): string {
  if (!ts) return '';
  const [a, m, d] = ts.slice(0, 10).split('-');
  return `${d}/${m}/${a}`;
}

function hace(ts: string | null | undefined): string {
  if (!ts) return '';
  return `hace ${duracion(Math.max(0, Math.round((Date.now() - Date.parse(ts)) / 1000)))}`;
}

function archivoCorto(ruta: string): string {
  const partes = ruta.split(/[\\/]/);
  return partes.length > 2 ? `${partes[partes.length - 2]}/${partes[partes.length - 1]}` : ruta;
}

/** Los datos de los archivos del equipo cambian poco: se piden al abrir el panel y cada minuto. */
function useEquipo(): Equipo | null {
  const [equipo, setEquipo] = useState<Equipo | null>(null);
  useEffect(() => {
    let vivo = true;
    const cargar = () =>
      fetch(api('equipo'), { cache: 'no-store' })
        .then((r) => (r.ok ? r.json() : null))
        .then((e) => vivo && e && setEquipo(e as Equipo))
        .catch(() => undefined);
    cargar();
    const t = window.setInterval(cargar, 60_000);
    return () => {
      vivo = false;
      window.clearInterval(t);
    };
  }, []);
  return equipo;
}

// --- Visor de archivos -------------------------------------------------------------------------------

function Visor({ ruta, onCerrar }: { ruta: string; onCerrar: () => void }) {
  const [texto, setTexto] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setTexto(null);
    setError(null);
    fetch(api(`archivo?ruta=${encodeURIComponent(ruta)}`), { cache: 'no-store' })
      .then(async (r) => {
        const cuerpo = (await r.json()) as { texto?: string; error?: string };
        if (!r.ok) throw new Error(cuerpo.error ?? `HTTP ${r.status}`);
        setTexto(cuerpo.texto ?? '');
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [ruta]);
  return (
    <div className="idi-visor">
      <div className="idi-visor-barra">
        <button className="idi-boton" onClick={onCerrar}>
          Volver
        </button>
        <span className="idi-tenue truncate" title={ruta}>
          {ruta}
        </span>
      </div>
      {error && <p className="idi-aviso">No se pudo abrir: {error}</p>}
      {texto === null && !error && <p className="idi-tenue">Cargando…</p>}
      {texto !== null && <pre className="idi-texto">{texto}</pre>}
    </div>
  );
}

function Enlace({ ruta, onAbrir, children }: { ruta: string; onAbrir: (r: string) => void; children?: React.ReactNode }) {
  return (
    <button className="idi-enlace" onClick={() => onAbrir(ruta)} title={`Abrir ${ruta}`}>
      {children ?? archivoCorto(ruta)}
    </button>
  );
}

function Vacio({ children }: { children: React.ReactNode }) {
  return <p className="idi-vacio">{children}</p>;
}

// --- Paneles --------------------------------------------------------------------------------------------

function Aprobaciones({ foto, filtro, quien }: { foto: Foto; filtro: string | null; quien: (c: string) => string }) {
  const lista = foto.aprobaciones.filter((a) => !filtro || a.instancia === filtro);
  return (
    <>
      <p className="idi-nota">Solo lectura: los permisos se aprueban o rechazan en la terminal de Claude Code.</p>
      {lista.length === 0 && <Vacio>No hay permisos pendientes.</Vacio>}
      {lista.map((a) => (
        <article key={a.instancia} className="idi-item" style={{ borderLeftColor: COLOR_ESTADO.esperando }}>
          <div className="idi-item-titulo">
            <span>{quien(a.instancia)}</span>
            <span className="idi-tenue">{hace(a.desde)}</span>
          </div>
          <div>
            {a.aviso === 'agent_needs_input' ? 'pide una respuesta' : 'pide permiso'}
            {a.herramienta ? ` para ${a.herramienta}` : ''}
          </div>
          {a.recurso && <div className="idi-tenue truncate">{a.recurso}</div>}
          {a.modo && <div className="idi-tenue">modo de permisos: {a.modo}</div>}
        </article>
      ))}
    </>
  );
}

function Flujos({ foto, filtro, onAbrir }: { foto: Foto; filtro: string | null; onAbrir: (r: string) => void }) {
  const docs = foto.documentos.filter((d) => !filtro || d.historial.some((h) => h.instancia === filtro));
  const color = (d: Documento) =>
    d.bloqueado ? COLOR_ESTADO.error : d.espera_responsable ? COLOR_ESTADO.esperando : COLOR_ESTADO.trabajando;
  return (
    <>
      {docs.length === 0 && <Vacio>Hoy no hay documentos en curso{filtro ? ' para este agente' : ''}.</Vacio>}
      {docs.map((d) => (
        <article key={d.ruta} className="idi-item" style={{ borderLeftColor: color(d) }}>
          <div className="idi-item-titulo">
            {d.ruta.startsWith('drive:') ? <span>{d.ruta.slice(6)}</span> : <Enlace ruta={d.ruta} onAbrir={onAbrir} />}
            <span className="idi-tenue">{hora(d.ultima_escritura)}</span>
          </div>
          <div className="idi-fila-chips">
            <span className="idi-chip">{d.tipo}</span>
            <span className="idi-chip" style={{ borderColor: color(d), color: color(d) }}>
              {d.etapa}
            </span>
            {d.encabezado?.estado && (
              <span className="idi-chip">
                {d.encabezado.estado}
                {d.encabezado.version ? ` v${d.encabezado.version}` : ''}
              </span>
            )}
            {d.pendiente_codex && <span className="idi-chip">lo hace alguien de afuera</span>}
          </div>
          {d.espera_responsable && (
            <div style={{ color: COLOR_ESTADO.esperando }}>
              {d.espera_responsable === 'pendientes' ? 'Bloqueado: quedó en pendientes.md' : `Te espera: ${d.espera_responsable}`}
            </div>
          )}
          {d.cruces.length > 0 && (
            <div className="idi-tenue">
              Verificación: {d.cruces.map((c) => `ronda ${c.etiqueta} (${hora(c.ts)})`).join(', ')}
            </div>
          )}
          {d.pendientes.length > 0 && <div className="idi-tenue">En pendientes: {d.pendientes.map((p) => p.titulo).join('; ')}</div>}
        </article>
      ))}
    </>
  );
}

const TIPOS_ACTIVIDAD: Record<string, { texto: string; eventos: string[] }> = {
  herramientas: { texto: 'Herramientas', eventos: ['PreToolUse', 'PostToolUseFailure'] },
  permisos: { texto: 'Permisos', eventos: ['PermissionRequest', 'PermissionDenied', 'Notification'] },
  agentes: { texto: 'Inicio y fin', eventos: ['SessionStart', 'SessionEnd', 'SubagentStart', 'SubagentStop', 'Stop', 'StopFailure'] },
  prompts: { texto: 'Pedidos', eventos: ['UserPromptSubmit'] },
  tareas: { texto: 'Tareas', eventos: ['TaskCreated', 'TaskCompleted'] },
};

const DESCRIPCION_EVENTO: Record<string, string> = {
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

function ActividadPanel({ foto, filtro, instancias }: { foto: Foto; filtro: string | null; instancias: Instancia[] }) {
  const [agente, setAgente] = useState<string>('');
  const [tipo, setTipo] = useState<string>('');
  const elegido = filtro ?? (agente || null);
  const eventos = useMemo(() => {
    const permitidos = tipo ? new Set(TIPOS_ACTIVIDAD[tipo].eventos) : null;
    return [...foto.actividad]
      .reverse()
      .filter((a: Actividad) => (!elegido || a.instancia === elegido) && (!permitidos || permitidos.has(a.evento)))
      .slice(0, 300);
  }, [foto.actividad, elegido, tipo]);
  return (
    <>
      <div className="idi-filtros">
        {!filtro && (
          <label>
            Agente{' '}
            <select value={agente} onChange={(e) => setAgente(e.target.value)}>
              <option value="">todos</option>
              {instancias.map((i) => (
                <option key={i.clave} value={i.clave}>
                  {i.etiqueta_historial}
                </option>
              ))}
            </select>
          </label>
        )}
        <label>
          Tipo{' '}
          <select value={tipo} onChange={(e) => setTipo(e.target.value)}>
            <option value="">todos</option>
            {Object.entries(TIPOS_ACTIVIDAD).map(([k, v]) => (
              <option key={k} value={k}>
                {v.texto}
              </option>
            ))}
          </select>
        </label>
      </div>
      {eventos.length === 0 && <Vacio>Sin actividad con estos filtros.</Vacio>}
      <ol className="idi-linea">
        {eventos.map((a, k) => (
          <li key={`${a.ts}-${k}`} className={a.evento === 'PostToolUseFailure' || a.evento === 'StopFailure' ? 'idi-linea-error' : ''}>
            <span className="idi-tenue">{hora(a.ts)}</span> <strong>{a.quien}</strong> {DESCRIPCION_EVENTO[a.evento] ?? a.evento}
            {a.herramienta ? ` ${a.herramienta}` : ''}
            {a.recurso && <span className="idi-tenue"> · {archivoCorto(a.recurso)}</span>}
          </li>
        ))}
      </ol>
    </>
  );
}

function Columna({ titulo, color, items, vacio, detalle, onAbrir }: {
  titulo: string;
  color: string;
  items: TablonItem[];
  vacio: string;
  detalle: (titulo: string) => Bloques['entradas'][number] | undefined;
  onAbrir: (r: string) => void;
}) {
  return (
    <section className="idi-columna" style={{ borderTopColor: color }}>
      <h3 className="idi-subtitulo" style={{ color }}>
        {titulo} <span className="idi-tenue">{items.length}</span>
      </h3>
      {items.length === 0 && <Vacio>{vacio}</Vacio>}
      {items.map((it, k) => {
        const d = it.fuente === 'archivo' ? detalle(it.titulo) : undefined;
        const cabeza = (
          <span className="idi-item-titulo">
            <span>{it.titulo}</span>
            <span className="idi-tenue">{it.fuente === 'sesion' ? `sesión ${hora(it.ts)}` : it.fecha ? fecha(it.fecha) : ''}</span>
          </span>
        );
        return d && (Object.keys(d.campos).length > 0 || d.rutas.length > 0) ? (
          <details key={k} className="idi-item">
            <summary>{cabeza}</summary>
            {Object.entries(d.campos).map(([c, v]) => (
              <p key={c}>
                <strong>{c}:</strong> {v}
              </p>
            ))}
            {d.rutas.length > 0 && (
              <p className="idi-fila-chips">
                {d.rutas.map((r) => (
                  <Enlace key={r} ruta={r} onAbrir={onAbrir} />
                ))}
              </p>
            )}
          </details>
        ) : (
          <div key={k} className="idi-item">
            {cabeza}
          </div>
        );
      })}
    </section>
  );
}

function Pendientes({ foto, equipo, filtro, onAbrir }: { foto: Foto; equipo: Equipo | null; filtro: string | null; onAbrir: (r: string) => void }) {
  const t = foto.tablones.pendientes;
  const deLaSeleccion = (items: TablonItem[]) => items.filter((i) => !filtro || i.fuente !== 'sesion' || i.instancia === filtro);
  const detalle = (titulo: string) => equipo?.pendientes.entradas.find((e) => e.titulo === titulo);
  return (
    <>
      <p className="idi-nota">
        Tu bandeja: lo que está en curso, lo que sigue y lo hecho. Sale de las tareas de la sesión
        {t.ruta ? (
          <>
            {' '}y de <Enlace ruta={t.ruta} onAbrir={onAbrir} />
          </>
        ) : null}
        .
      </p>
      <div className="idi-columnas">
        <Columna titulo="En curso" color={COLOR_ESTADO.trabajando} items={deLaSeleccion(t.en_curso)} vacio="Nada en curso." detalle={detalle} onAbrir={onAbrir} />
        <Columna titulo="Siguen" color={COLOR_ESTADO.esperando} items={deLaSeleccion(t.siguen)} vacio="No hay nada anotado para después." detalle={detalle} onAbrir={onAbrir} />
        <Columna titulo="Hechas" color={COLOR_ESTADO.terminado} items={deLaSeleccion(t.hechas)} vacio="Todavía nada terminado." detalle={detalle} onAbrir={onAbrir} />
      </div>
    </>
  );
}

function Auditorias({ foto, onAbrir }: { foto: Foto; onAbrir: (r: string) => void }) {
  const a = foto.tablones.auditorias;
  const entrada = (f: TablonAuditoria, k: number) => (
    <details key={k} className="idi-item" style={{ borderLeftColor: f.resuelta ? COLOR_ESTADO.terminado : COLOR_ESTADO.error }}>
      <summary className="idi-item-titulo">
        <span>{f.titulo}</span>
        <span className="idi-tenue">{f.fecha ? fecha(f.fecha) : ''}</span>
      </summary>
      {Object.entries(f.detalle).map(([c, v]) => (
        <p key={c}>
          <strong>{c}:</strong> {v}
        </p>
      ))}
    </details>
  );
  return (
    <>
      <p className="idi-nota">
        Fricciones detectadas en el trabajo: lo que trabó, falló o se repite
        {a.ruta ? (
          <>
            {' '}(<Enlace ruta={a.ruta} onAbrir={onAbrir} />)
          </>
        ) : null}
        .
      </p>
      <h3 className="idi-subtitulo" style={{ color: COLOR_ESTADO.error }}>
        Abiertas <span className="idi-tenue">{a.abiertas.length}</span>
      </h3>
      {a.abiertas.length === 0 && <Vacio>No hay fricciones abiertas.</Vacio>}
      {a.abiertas.map((f, k) => entrada({ ...f, resuelta: false }, k))}
      {a.resueltas.length > 0 && (
        <details className="idi-resueltas">
          <summary className="idi-subtitulo" style={{ color: COLOR_ESTADO.terminado }}>
            Resueltas <span className="idi-tenue">{a.resueltas.length}</span>
          </summary>
          {a.resueltas.map((f, k) => entrada({ ...f, resuelta: true }, k))}
        </details>
      )}
    </>
  );
}

function Memoria({ equipo, filtroTipo, onAbrir }: { equipo: Equipo | null; filtroTipo: string | null; onAbrir: (r: string) => void }) {
  const [consulta, setConsulta] = useState('');
  const [resultados, setResultados] = useState<Array<{ ruta: string; linea: number; texto: string }> | null>(null);
  const buscar = (e: React.FormEvent) => {
    e.preventDefault();
    if (consulta.trim().length < 2) return;
    fetch(api(`buscar?q=${encodeURIComponent(consulta.trim())}`), { cache: 'no-store' })
      .then((r) => r.json())
      .then((d: { resultados: Array<{ ruta: string; linea: number; texto: string }> }) => setResultados(d.resultados))
      .catch(() => setResultados([]));
  };
  const agentes = (equipo?.catalogo.agentes ?? []).filter((a) => !filtroTipo || a.nombre === filtroTipo);
  return (
    <>
      <form className="idi-busqueda" onSubmit={buscar} role="search">
        <label htmlFor="idi-q" className="idi-subtitulo">
          Buscar en los archivos del equipo
        </label>
        <div className="idi-fila">
          <input id="idi-q" type="search" value={consulta} onChange={(e) => setConsulta(e.target.value)} placeholder="por ejemplo: retención de datos" />
          <button className="idi-boton" type="submit">
            Buscar
          </button>
        </div>
      </form>
      {resultados && resultados.length === 0 && <Vacio>Sin coincidencias en lo que la oficina ya leyó.</Vacio>}
      {resultados?.map((r, k) => (
        <div key={k} className="idi-resultado">
          <Enlace ruta={r.ruta} onAbrir={onAbrir}>
            {archivoCorto(r.ruta)}:{r.linea}
          </Enlace>
          <div className="idi-tenue">{r.texto}</div>
        </div>
      ))}
      <h3 className="idi-subtitulo">Definición de cada agente</h3>
      {agentes.map((a) => (
        <div key={a.nombre} className="idi-resultado">
          <Enlace ruta={a.archivo} onAbrir={onAbrir}>
            {a.nombre}
          </Enlace>
          {a.vacante && <span className="idi-aviso"> vacante</span>}
        </div>
      ))}
      {equipo && equipo.remember.length > 0 && (
        <>
          <h3 className="idi-subtitulo">Notas de .remember</h3>
          {equipo.remember.map((r) => (
            <div key={r.ruta} className="idi-resultado">
              <Enlace ruta={r.ruta} onAbrir={onAbrir} />
              <span className="idi-tenue"> {r.entradas.length} entradas</span>
            </div>
          ))}
        </>
      )}
    </>
  );
}

function Corridas({ foto, equipo, onAbrir }: { foto: Foto; equipo: Equipo | null; onAbrir: (r: string) => void }) {
  const corrida = perfil().corrida;
  const status = equipo?.status ?? [];
  return (
    <>
      {corrida ? (
        <article className="idi-item" style={{ borderLeftColor: foto.reloj.en_curso ? COLOR_ESTADO.trabajando : COLOR_ESTADO.ocioso }}>
          <div className="idi-item-titulo">
            <span>Corrida programada{corrida.agente ? ` (${corrida.agente})` : ''}</span>
            {foto.reloj.en_curso && <span style={{ color: COLOR_ESTADO.trabajando }}>en curso</span>}
          </div>
          <div>Próxima: {foto.reloj.proxima ? `${fecha(foto.reloj.proxima)} ${foto.reloj.proxima.slice(11, 16)}` : '—'}</div>
          <div>Última: {foto.reloj.ultima ? fecha(foto.reloj.ultima) : 'sin registro'}</div>
        </article>
      ) : (
        <Vacio>El perfil no define una corrida programada.</Vacio>
      )}
      <h3 className="idi-subtitulo">Informes de corridas y cambios</h3>
      {equipo && status.length === 0 && <Vacio>No hay informes en la carpeta de status.</Vacio>}
      {status.slice(0, 40).map((s) => (
        <div key={s.ruta} className="idi-resultado">
          <span className="idi-tenue">{s.fecha ? fecha(s.fecha) : ''}</span> <span className="idi-chip">{s.tipo}</span>{' '}
          <Enlace ruta={s.ruta} onAbrir={onAbrir}>
            {s.titulo ?? archivoCorto(s.ruta)}
          </Enlace>
        </div>
      ))}
    </>
  );
}

function Catalogo({ foto, equipo, filtroTipo, onAbrir }: { foto: Foto; equipo: Equipo | null; filtroTipo: string | null; onAbrir: (r: string) => void }) {
  const agentes = equipo?.catalogo.agentes ?? [];
  return (
    <>
      {foto.candidatos.length > 0 && (
        <>
          <h3 className="idi-subtitulo">Posibles agentes nuevos</h3>
          <p className="idi-nota">
            Lanzamientos de agentes generales con descripciones parecidas (3 o más en 14 días). Si se repiten, puede convenir un agente propio.
          </p>
          {foto.candidatos.map((c, k) => (
            <article key={k} className="idi-item" style={{ borderLeftColor: '#e0b050' }}>
              <div className="idi-item-titulo">
                <span>{c.palabras.join(' · ')}</span>
                <span className="idi-tenue">{c.lanzamientos} veces</span>
              </div>
              {c.descripciones.map((d) => (
                <div key={d} className="idi-tenue">
                  “{d}”
                </div>
              ))}
              <div className="idi-tenue">
                con {c.tipos.join(', ')} · último {fecha(c.ultimo)}
              </div>
            </article>
          ))}
        </>
      )}
      <h3 className="idi-subtitulo">Agentes ({agentes.length})</h3>
      {!equipo && <Vacio>Cargando…</Vacio>}
      {agentes.map((a) => (
        <article
          key={a.nombre}
          className={`idi-item ${filtroTipo === a.nombre ? 'idi-item-sel' : ''}`}
          style={{ borderLeftColor: a.vacante ? COLOR_ESTADO.error : a.sin_zona ? COLOR_ESTADO.esperando : COLOR_ESTADO.ocioso }}
        >
          <div className="idi-item-titulo">
            <Enlace ruta={a.archivo} onAbrir={onAbrir}>
              {a.nombre}
            </Enlace>
            <span className="idi-tenue">
              {[a.model, a.effort].filter(Boolean).join(' · ')}
            </span>
          </div>
          {a.descripcion && <div className="idi-tenue idi-dos-lineas">{a.descripcion}</div>}
          <div className="idi-fila-chips">
            <span className="idi-chip">{a.sin_zona ? 'sin zona' : (perfil().piso.salas[a.zona] ?? a.zona)}</span>
            {a.vacante && <span className="idi-chip" style={{ color: COLOR_ESTADO.error }}>vacante: se borró su definición</span>}
          </div>
        </article>
      ))}
      <h3 className="idi-subtitulo">Skills ({equipo?.catalogo.skills.length ?? 0})</h3>
      {(equipo?.catalogo.skills ?? []).map((s) => (
        <div key={s.nombre} className="idi-resultado">
          <Enlace ruta={s.archivo} onAbrir={onAbrir}>
            {s.nombre}
          </Enlace>
          {s.descripcion && <div className="idi-tenue idi-dos-lineas">{s.descripcion}</div>}
        </div>
      ))}
    </>
  );
}

// --- Contenedor -------------------------------------------------------------------------------------------

export function Pestanas({ seleccion, foto, onLimpiar, pedida }: {
  seleccion: string | null;
  foto: Foto | null;
  onLimpiar: () => void;
  /** Pestaña que pidió abrir otra parte de la pantalla (por ejemplo, tocar un tablón del piso). */
  pedida?: { pestana: Pestana; n: number } | null;
}) {
  const [activa, setActiva] = useState<Pestana>(() => {
    try {
      const guardada = window.localStorage.getItem('oficina.pestana') as Pestana | null;
      return guardada && (PESTANAS as readonly string[]).includes(guardada) ? guardada : 'Aprobaciones';
    } catch {
      return 'Aprobaciones';
    }
  });
  const [abierto, setAbierto] = useState<string | null>(null);
  const equipo = useEquipo();
  useEffect(() => {
    if (pedida) {
      setActiva(pedida.pestana);
      setAbierto(null);
    }
  }, [pedida]);
  const elegir = (p: Pestana) => {
    setActiva(p);
    setAbierto(null);
    try {
      window.localStorage.setItem('oficina.pestana', p);
    } catch {
      /* sin almacenamiento local: la pestaña no se recuerda */
    }
  };
  const inst = foto?.instancias.find((i) => i.clave === seleccion) ?? null;
  const quien = (clave: string) => foto?.instancias.find((i) => i.clave === clave)?.etiqueta_historial ?? clave;
  const contadores: Partial<Record<Pestana, number>> = {
    Aprobaciones: foto?.aprobaciones.length ?? 0,
    Pendientes: foto?.tablones.pendientes.en_curso.length ?? 0,
    Auditorías: foto?.tablones.auditorias.abiertas.length ?? 0,
    Flujos: foto?.documentos.filter((d) => d.espera_responsable).length ?? 0,
    Catálogo: foto?.candidatos.length ?? 0,
  };
  return (
    <aside className="idi-pestanas">
      <nav className="idi-pestanas-nav" role="tablist" aria-label="Paneles">
        {PESTANAS.map((p) => (
          <button key={p} role="tab" aria-selected={p === activa} className={`idi-pestana ${p === activa ? 'idi-pestana-sel' : ''}`} onClick={() => elegir(p)}>
            {p}
            {(contadores[p] ?? 0) > 0 && <span className="idi-contador">{contadores[p]}</span>}
          </button>
        ))}
      </nav>
      {inst && (
        <div className="idi-filtro">
          Filtrado por <strong>{inst.etiqueta_historial}</strong>
          <button className="idi-enlace" onClick={onLimpiar}>
            ver todos
          </button>
        </div>
      )}
      <div className="idi-panel" role="tabpanel">
        {abierto ? (
          <Visor ruta={abierto} onCerrar={() => setAbierto(null)} />
        ) : !foto ? (
          <Vacio>Cargando…</Vacio>
        ) : activa === 'Aprobaciones' ? (
          <Aprobaciones foto={foto} filtro={seleccion} quien={quien} />
        ) : activa === 'Flujos' ? (
          <Flujos foto={foto} filtro={seleccion} onAbrir={setAbierto} />
        ) : activa === 'Actividad' ? (
          <ActividadPanel foto={foto} filtro={seleccion} instancias={foto.instancias} />
        ) : activa === 'Pendientes' ? (
          <Pendientes foto={foto} equipo={equipo} filtro={seleccion} onAbrir={setAbierto} />
        ) : activa === 'Auditorías' ? (
          <Auditorias foto={foto} onAbrir={setAbierto} />
        ) : activa === 'Memoria' ? (
          <Memoria equipo={equipo} filtroTipo={inst?.tipo ?? null} onAbrir={setAbierto} />
        ) : activa === 'Corridas' ? (
          <Corridas foto={foto} equipo={equipo} onAbrir={setAbierto} />
        ) : (
          <Catalogo foto={foto} equipo={equipo} filtroTipo={inst?.tipo ?? null} onAbrir={setAbierto} />
        )}
      </div>
    </aside>
  );
}
