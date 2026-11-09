# Perfil de equipo

El código de la oficina no sabe nada de un equipo concreto. Todo lo específico vive en una **carpeta de perfil**, que conviene versionar aparte (normalmente en un repo privado):

| Archivo | Para qué | Obligatorio |
|---|---|---|
| `profile.json` | Rutas, roles, scripts, corrida programada y textos del piso | Sí |
| `zones.json` | Zona del piso de cada agente | No (todos van a la recepción) |
| `flows.json` | Reglas ruta → tipo → etapa de los documentos | No (sin él no hay flujos) |
| `layout.json` | Plano del piso. Lo escribe el editor de la web | No (piso vacío) |
| `sprites.json` | Sprite de cada agente | No (asignación determinística) |

Las claves de los JSON están en inglés, como el resto del código. Los valores que se ven en pantalla (nombres de salas, tipos y etapas de documentos, textos de espera) van en el idioma del equipo.

`profiles/example/` es un perfil completo de un equipo de investigación ficticio: sirve de plantilla y es el que usan las pruebas.

## Proyectos registrados

Lo normal es registrar cada proyecto con `/oficina:configurar` (`scripts/configure.py`). El registro queda en `~/.agents-office/projects.json` (`id`, carpeta y perfil de cada uno), y el servidor arma una oficina por proyecto, con un selector en la cabecera. Los perfiles generados quedan en `~/.agents-office/profiles/<id>/` y se pueden editar como cualquier otro.

## Perfil suelto (sin proyectos registrados)

Si no hay proyectos registrados, el servidor muestra un solo perfil. Se elige en este orden:

1. `--profile CARPETA` (servidor).
2. La variable `AGENTS_OFFICE_PROFILE`.
3. `local.json` en la raíz del repo: `{"profile": "../mi-perfil"}` (no se versiona).
4. `profiles/example`.

## `profile.json`

```jsonc
{
  "name": "Oficina de ejemplo",            // título de la web
  "area_root": "C:\\ruta\\al\\area",       // carpeta que la oficina lee (solo lectura). Sin valor: <perfil>/area
  "team_dir": "equipo",                    // carpeta del proyecto de Claude Code del equipo (relativa a la raíz o absoluta).
                                           // Solo se capturan las sesiones abiertas dentro de ella
  "port": 8765,
  "roots": ["equipo", "radar"],            // lista blanca: carpetas de primer nivel que la web puede leer (.md).
                                           // "." = todo el proyecto (salvo build, node_modules, .git y ocultas)
  "files": {                               // archivos del equipo que se muestran (cualquiera puede faltar)
    "tasks": "equipo/pendientes.md",       // tablón de pendientes (ver abajo)
    "frictions": "equipo/fricciones.md",   // tablón de auditorías
    "decisions": "equipo/decisiones.md",
    "remember": "equipo/.remember",
    "status": "equipo/status"
  },
  "main_agent": "partner",                 // agente principal de la sesión (el de la cabecera)
  "verifier": "verificador",               // agente que verifica documentos (o null)
  "owner_label": "responsable",            // etiqueta del avatar de la persona
  "scripts": {
    "known": ["detector-cambios.py"],      // scripts del equipo: se guarda solo el nombre y sus banderas
    "mailbox": "notificar.py",             // el script de avisos enciende el buzón (nunca se guarda el mensaje)
    "channels": ["radar"],                 // valores válidos de --canal (o --channel)
    "default_channel": "avisos",
    "checks": ["comprobar-citas.py"]       // controles previos a presentar: se guarda la ruta que revisan
  },
  "memory_mcp": ["mcp__engram__"],         // prefijos de herramientas MCP que encienden el archivo
  "scheduled_run": {                       // corrida programada (o null): reloj de pared
    "agent": "radar",                      // agente que se sienta junto al reloj
    "weekday": 2,                          // lunes = 0
    "hour": 10,
    "origin_variable": { "name": "OFICINA_CORRIDA", "value": "1" }  // así se reconoce la sesión de la corrida
  },
  "thresholds": {},                        // ver THRESHOLDS en server/model.py
  "floor": {
    "rooms": { "reading": "Lectura" },     // zona del layout → nombre visible
    "short_names": { "investigador-proveedor": "investigador" },
    "accessories": { "lente-*": "magnifier" },
    "external_work": { "maquetador": { "icon": "google", "tools": "drive|docs|slides" } },
    "next_to_clock": "radar",
    "lights_off": ["communication"]        // salas a oscuras mientras no hay nadie activo
  }
}
```

## Zonas con significado propio

El layout puede tener cualquier zona (área) para las salas. Hay cinco que la oficina usa por nombre:

| Zona | Uso |
|---|---|
| `owner` | Escritorio del avatar de la persona y los tablones |
| `lounge` | Sillones adonde van los subagentes que terminan |
| `reception` | Agentes sin zona en `zones.json` |
| `floating` | Agentes generales y desborde de las salas llenas |
| `verification` | Donde se muestran los cruces del verificador |

El perfil de ejemplo usa además `coordination`, `exploration`, `reading`, `base` y `communication`. El nombre que se ve en el piso sale de `floor.rooms`.

## `zones.json`

```json
{
  "rules": [{ "agent": "lente-*", "zone": "reading" }],
  "generic": ["general-purpose", "Explore", "Plan"],
  "generic_zone": "floating",
  "unzoned_zone": "reception"
}
```

Gana la primera regla que coincide. Los agentes de `generic` no tienen definición propia en `.claude/agents` y usan un escritorio flotante temporal.

## `flows.json`

Reglas glob (`*` no cruza `/`, `**` sí) que dan tipo y etapa a cada documento escrito por un agente: `rules` es una lista de `{ "pattern", "type", "stage" }`, e `ignore` una lista de patrones que no cuentan. El tipo `verification` marca los informes de verificación. Además define las convenciones del equipo:

- `mirror`: qué documento verifica cada informe de verificación (`report`, `document`, `type`).
- `layout_work`: agentes que trabajan fuera del área (`agents`, `type`, `stage`).
- `owner_waits`: textos de las esperas (`review`, `final`).
- `max_rounds`: tope de rondas de verificación.
- `external_pending_type`: documentos que hace alguien fuera del equipo.
- `initial_review_types`: el responsable los revisa antes de que pasen por el verificador.
- `final_review_types`: después de verificados esperan una "revisión final".
- `closed_states`: estados del encabezado que dan el documento por terminado.

Los flujos asumen dos convenciones de documento:
- Una tabla de encabezado `| Estado | Versión | Última revisión |` en las primeras líneas.
- Los informes de verificación con secciones `## Ronda N` (o `## Ciclo C, ronda N`).

Si tu equipo no las usa, dejá `flows.json` sin reglas y la pestaña Flujos queda vacía.

## `sprites.json`

`{ "agents": { "partner": { "sprite": 0 } } }`. El índice es el de `web/dist/assets/decoded/cast.json` (ver [avatar.md](avatar.md)). Los patrones con `*` valen.

## Tablones

**`pendientes.md`.** El formato estándar (el que crea `/oficina:configurar`) tiene tres secciones con una línea por tarea:

```markdown
## En curso
- [ ] tarea que se está haciendo
## Siguen
- [ ] tarea para después
## Hechas
- [x] tarea terminada
```

Un archivo sin esas secciones (por ejemplo, con entradas `## fecha · título`) también sirve: cada entrada va a "siguen". Las tareas que los agentes crean y completan en la sesión se suman solas a "en curso" y "hechas".

**`fricciones.md`.** Una entrada `## AAAA-MM-DD · título` por fricción, con campos en negrita (`**Estado:** abierta`, `**Qué pasó:**`, `**Propuesta:**`). Un estado que dice "resuelta" o "cerrada" la pasa a resueltas. Los comentarios HTML (`<!-- -->`) se ignoran: ahí va la guía de formato.
