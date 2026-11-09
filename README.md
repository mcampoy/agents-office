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

## Instalación

Requisitos: Windows, Claude Code y Python 3.12+ (solo librería estándar). La web ya viene compilada en `web/dist`: Node hace falta solo si se modifica la web.

1. Clonar el repo y armar el perfil del equipo, copiando `perfiles/ejemplo` a una carpeta propia (ver [docs/perfil.md](docs/perfil.md)). Como mínimo hay que cambiar `raiz_area`, `equipo_dir` y `principal` en `perfil.json`.
2. Apuntar la base al perfil con un `local.json` en la raíz del repo (no se versiona):
   ```json
   { "perfil": "../mi-perfil" }
   ```
3. Instalar el plugin de captura para ese perfil:
   ```
   py -3 scripts/instalar.py
   ```
   El instalador:
   - registra el `python.exe` real (rechaza el alias de la Microsoft Store);
   - genera `plugin/hooks/hooks.json` y la skill `/oficina:abrir`;
   - escribe `<datos>/config.json`;
   - instala el plugin `oficina@agents-office` a nivel usuario.

   Los hooks empiezan a capturar en las sesiones nuevas.

Si se mueve o se renombra la carpeta del repo, hay que volver a correr el instalador: el plugin se lee desde `plugin/` de esta carpeta.

## Uso diario

- Desde Claude Code: `/oficina:abrir`.
- Desde PowerShell: `.\iniciar-oficina.ps1`. Levanta el servidor en segundo plano, si no estaba corriendo, y abre `http://127.0.0.1:8765/`. Con `-Detener` lo apaga.
- A mano: `py -3 -m servidor [--perfil CARPETA] [--puerto N]`.

La pantalla tiene cuatro partes:
- **Cabecera:** el agente principal y el conteo de estados.
- **Piso:** quién trabaja, espera, piensa, tiene un error o está ocioso.
- **Siete pestañas** de solo lectura: aprobaciones, flujos, actividad, tareas, memoria, corridas y catálogo.
- **Barra de tarjetas:** una por agente. Al tocar una, la selección filtra las pestañas.

En el teléfono, el plano queda arriba, los agentes abajo y los paneles en otra vista.

## Datos

| Qué | Dónde |
|---|---|
| Eventos capturados (uno por día, se borran a los 14 días) | `<datos>/eventos/AAAA-MM-DD.jsonl` |
| Errores del hook (sin contenido) | `<datos>/errores.log` |
| Config del hook (la genera el instalador) | `<datos>/config.json` |
| Salida del servidor | `<datos>/servidor.log` |

`<datos>` es la carpeta `datos` del perfil (por defecto `~/.agents-office`). Se puede borrar entera en cualquier momento; el próximo `instalar.py` vuelve a crear la config. Los eventos guardan nombres de herramientas, rutas y resúmenes cortos, nunca prompts, mensajes ni contenido de archivos.

## Agentes nuevos

Un agente nuevo en `.claude/agents/` del equipo aparece solo en la **recepción**, marcado "sin zona". Para darle lugar:
1. Agregar una regla en `zonas.json` del perfil: `{ "agente": "mi-agente", "zona": "lectura" }`. Los patrones como `lente-*` valen.
2. Opcional: fijar su sprite en `sprites.json` y su nombre corto en `perfil.json` → `piso.nombres_cortos`.

Los cambios se toman al recargar la página. Si hace falta, se suman escritorios con el editor del piso (botón "Editar piso", en escritorio).

## Desinstalar

```
claude plugin uninstall oficina@agents-office
claude plugin marketplace remove agents-office
```

Después, opcionalmente, borrar la carpeta `<datos>`.

## Desarrollo

- **Recompilar la web** (después de cambiar `web/pixel-agents/webview-ui/src/idi`):
  ```
  cd web/pixel-agents
  npm install
  npm run build
  ```
  Escribe en `web/dist`, que se versiona. Ver `web/pixel-agents/ORIGEN.md`.
- **Probar sin un equipo real:** el simulador escribe eventos ficticios en una carpeta aparte.
  ```
  py -3 scripts/simular.py --datos %TEMP%\agents-office-sim
  set AGENTS_OFFICE_DATOS=%TEMP%\agents-office-sim
  py -3 -m servidor
  ```
- **Pruebas:** `py -3 -m unittest discover -s tests`. Usan siempre el perfil de ejemplo.

## Qué garantiza

- Los hooks nunca bloquean ni frenan a los agentes: salen siempre con código 0 y los no críticos son async.
- Una sesión ajena al equipo no deja rastro.
- El servidor escucha solo en `127.0.0.1`, rechaza otro `Host`, no habilita CORS y lee el área en solo lectura. Su única escritura es el `layout.json` del perfil, desde el editor del piso.

## Licencias

- Código propio: MIT, © 2026 Matías Campoy. Ver `LICENSE`.
- Motor y assets de Pixel Agents (`web/pixel-agents/core`, `web/pixel-agents/webview-ui`): MIT, © 2026 Pablo De Lucca. Ver `web/pixel-agents/LICENSE` y `web/pixel-agents/ORIGEN.md`.
- Personajes: basados en el pack MetroCity de JIK-A-4 (CC0). Las variantes y el avatar se generan en build: ver [docs/avatar.md](docs/avatar.md).
- Fuente VT323: SIL Open Font License 1.1 (`web/pixel-agents/webview-ui/public-idi/fonts/OFL-VT323.txt`).
