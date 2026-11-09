# agents-office

Una oficina en pixel art, local, para ver qué hace un equipo de agentes de Claude Code: quién trabaja, quién espera una aprobación, en qué etapa está cada documento y dónde se traba el trabajo.

Los estados no se adivinan desde las transcripciones: salen de los **hooks** de Claude Code. Un plugin captura los eventos de las sesiones del equipo, sin guardar contenido: ni prompts, ni mensajes, ni textos de archivos. Un servidor local los convierte en una foto de la oficina, que se dibuja sobre el motor de [Pixel Agents](https://github.com/pixel-agents-hq/pixel-agents).

```
Claude Code ──hook (python)──► <datos>/eventos/AAAA-MM-DD.jsonl
                                        │ lectura incremental
                                        ▼
                         servidor local (Python, 127.0.0.1) ──SSE──► web (estáticos)
                                        ▲
                     lectura del área del equipo (solo lectura, lista blanca)
```

## Base y perfil

Este repo es la **base**, genérica. Lo propio de cada equipo va en un **perfil**: una carpeta con su `perfil.json` (rutas, roles, scripts), sus zonas, flujos, layout y sprites. Ver [docs/perfil.md](docs/perfil.md). `perfiles/ejemplo/` es un perfil de muestra y la plantilla para uno propio.

## Uso

Requisitos: Windows, Python 3.12+ (solo librería estándar) y Node 20+ únicamente para compilar la web.

```
# 1. Compilar la web (una vez, o después de cambiarla)
cd web/pixel-agents && npm install && npm run build

# 2. Elegir el perfil: local.json en la raíz -> {"perfil": "../mi-perfil"}
# 3. Instalar el plugin de captura para ese perfil
py -3 scripts/instalar.py

# 4. Levantar la oficina
py -3 -m servidor            # http://127.0.0.1:8765/
```

Para probar sin un equipo real, el simulador escribe eventos ficticios en una carpeta aparte:

```
py -3 scripts/simular.py --datos %TEMP%\agents-office-sim
set AGENTS_OFFICE_DATOS=%TEMP%\agents-office-sim
py -3 -m servidor
```

Pruebas: `py -3 -m unittest discover -s tests` (siempre con el perfil de ejemplo).

## Qué garantiza

- Los hooks nunca bloquean ni frenan a los agentes: salen siempre con código 0 y los no críticos son async.
- Una sesión ajena al equipo no deja rastro.
- El servidor escucha solo en `127.0.0.1`, rechaza otro `Host`, no habilita CORS y lee el área en solo lectura. Su única escritura es el `layout.json` del perfil, desde el editor del piso.

## Licencias

- Código propio: ver `LICENSE` (pendiente de definir).
- Motor y assets de Pixel Agents (`web/pixel-agents/core`, `web/pixel-agents/webview-ui`): MIT, © 2026 Pablo De Lucca. Ver `web/pixel-agents/LICENSE` y `web/pixel-agents/ORIGEN.md`.
- Personajes: basados en el pack MetroCity de JIK-A-4 (CC0). Las variantes y el avatar se generan en build: ver [docs/avatar.md](docs/avatar.md).
- Fuente VT323: SIL Open Font License 1.1 (`web/pixel-agents/webview-ui/public-idi/fonts/OFL-VT323.txt`).
