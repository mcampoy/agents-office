# Perfil de equipo

El código de la oficina no sabe nada de un equipo concreto. Todo lo específico vive en una **carpeta de perfil**, que conviene versionar aparte (normalmente en un repo privado):

| Archivo | Para qué | Obligatorio |
|---|---|---|
| `perfil.json` | Rutas, roles, scripts, corrida programada y textos del piso | Sí |
| `zonas.json` | Zona del piso de cada agente | No (todos van a la recepción) |
| `flujos.json` | Reglas ruta → tipo → etapa de los documentos | No (sin él no hay flujos) |
| `layout.json` | Plano del piso. Lo escribe el editor de la web | No (piso vacío) |
| `sprites.json` | Sprite de cada agente | No (asignación determinística) |

`perfiles/ejemplo/` es un perfil completo de un equipo de investigación ficticio: sirve de plantilla y es el que usan las pruebas.

## Proyectos registrados

Lo normal es registrar cada proyecto con `/oficina:configurar` (`scripts/configurar.py`). El registro queda en `~/.agents-office/proyectos.json` (`id`, carpeta y perfil de cada uno), y el servidor arma una oficina por proyecto, con un selector en la cabecera. Los perfiles generados quedan en `~/.agents-office/perfiles/<id>/` y se pueden editar como cualquier otro.

## Perfil suelto (sin proyectos registrados)

Si no hay proyectos registrados, el servidor muestra un solo perfil. Se elige en este orden:

1. `--perfil CARPETA` (servidor e instalador).
2. La variable `AGENTS_OFFICE_PERFIL`.
3. `local.json` en la raíz del repo: `{"perfil": "../mi-perfil"}` (no se versiona).
4. `perfiles/ejemplo`.

Después de cambiar de perfil, hay que volver a correr `py -3 scripts/instalar.py`: el hook de captura lee lo que necesita de `<datos>/config.json`, que genera el instalador.

## `perfil.json`

```jsonc
{
  "nombre": "Oficina de ejemplo",          // título de la web
  "raiz_area": "C:\\ruta\\al\\area",       // carpeta que la oficina lee (solo lectura). Sin valor: <perfil>/area
  "equipo_dir": "equipo",                  // carpeta del proyecto de Claude Code del equipo (relativa a la raíz o absoluta).
                                           // Solo se capturan las sesiones abiertas dentro de ella
  "puerto": 8765,
  "raices": ["equipo", "radar"],           // lista blanca: carpetas de primer nivel que la web puede leer (.md).
                                           // "." = todo el proyecto (salvo build, node_modules, .git y ocultas)
  "archivos": {                            // archivos del equipo que se muestran (cualquiera puede faltar)
    "pendientes": "equipo/pendientes.md",  // tablón de pendientes (ver abajo)
    "fricciones": "equipo/fricciones.md",  // tablón de auditorías
    "decisiones": "equipo/decisiones.md",
    "remember": "equipo/.remember",
    "status": "equipo/status"
  },
  "principal": "partner",                  // agente principal de la sesión (el de la cabecera)
  "verificador": "verificador",            // agente que verifica documentos (o null)
  "responsable": "responsable",            // etiqueta del avatar de la persona
  "scripts": {
    "conocidos": ["detector-cambios.py"],  // scripts del equipo: se guarda solo el nombre y sus banderas
    "buzon": "notificar.py",               // el script de avisos enciende el buzón (nunca se guarda el mensaje)
    "canales": ["radar"],                  // valores válidos de --canal
    "canal_por_defecto": "avisos",
    "controles": ["comprobar-citas.py"]    // controles previos a presentar: se guarda la ruta que revisan
  },
  "memoria_mcp": ["mcp__engram__"],        // prefijos de herramientas MCP que encienden el archivo
  "corrida": {                             // corrida programada (o null): reloj de pared
    "agente": "radar",                     // agente que se sienta junto al reloj
    "dia_semana": 2,                       // lunes = 0
    "hora": 10,
    "variable_origen": { "nombre": "OFICINA_CORRIDA", "valor": "1" }  // así se reconoce la sesión de la corrida
  },
  "umbrales": {},                          // ver UMBRALES en servidor/modelo.py
  "piso": {
    "salas": { "lectura": "Lectura" },     // zona del layout → nombre visible
    "nombres_cortos": { "investigador-proveedor": "investigador" },
    "accesorios": { "lente-*": "lupa" },
    "trabajo_externo": { "maquetador": { "icono": "google", "herramientas": "drive|docs|slides" } },
    "junto_al_reloj": "radar",
    "luces_apagadas": ["comunicacion"]     // salas a oscuras mientras no hay nadie activo
  }
}
```

## Zonas con significado propio

El layout puede tener cualquier zona (área) para las salas. Hay cinco que la oficina usa por nombre:

| Zona | Uso |
|---|---|
| `responsable` | Escritorio del avatar de la persona |
| `comun` | Sillones adonde van los subagentes que terminan |
| `recepcion` | Agentes sin zona en `zonas.json` |
| `flotante` | Agentes generales y desborde de las salas llenas |
| `paso-verificacion` | Donde se muestran los cruces del verificador |

## `flujos.json`

Reglas glob (`*` no cruza `/`, `**` sí) que dan tipo y etapa a cada documento escrito por un agente. Además define las convenciones del equipo:

- `espejo`: qué documento verifica cada informe de verificación.
- `maquetado`: agentes y herramientas que trabajan fuera del área.
- `esperas_del_responsable`: textos de las esperas.
- `rondas_maximas`: tope de rondas de verificación.
- `tipo_pendiente_externo`: documentos que hace alguien fuera del equipo.
- `tipos_con_revision_inicial`: el responsable los revisa antes de que pasen por el verificador.
- `tipos_con_revision_final`: después de verificados esperan una "revisión final".
- `estados_cerrados`: estados del encabezado que dan el documento por terminado.

Los flujos asumen dos convenciones de documento:
- Una tabla de encabezado `| Estado | Versión | Última revisión |` en las primeras líneas.
- Los informes de verificación con secciones `## Ronda N` (o `## Ciclo C, ronda N`).

Si tu equipo no las usa, dejá `flujos.json` sin reglas y la pestaña Flujos queda vacía.

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
