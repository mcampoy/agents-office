# agents-office

Una oficina en pixel art, local, para ver qué hace un equipo de agentes de Claude Code: quién trabaja, quién espera una aprobación, en qué etapa está cada documento y dónde se traba el trabajo.

Los estados no se adivinan desde las transcripciones: salen de los **hooks** de Claude Code. Un plugin captura los eventos de las sesiones del equipo, sin guardar contenido: ni prompts, ni mensajes, ni textos de archivos. Un servidor local los convierte en una foto de la oficina, que se dibuja sobre el motor de [Pixel Agents](https://github.com/pixel-agents-hq/pixel-agents).

```
Claude Code ──hook (python)──► <datos>/events/AAAA-MM-DD.jsonl
                                        │ lectura incremental
                                        ▼
                         servidor local (Python, 127.0.0.1) ──SSE──► web (estáticos)
                                        ▲
                     lectura del área del equipo (solo lectura, lista blanca)
```

## Proyectos y perfiles

La oficina sigue los proyectos que vos registrás, uno o varios. Cada proyecto tiene un **perfil**: su `profile.json` (rutas, roles, scripts), sus zonas, flujos, layout y sprites (ver [docs/profile.md](docs/profile.md)).
- Para un proyecto nuevo, `/oficina:configurar` arma el perfil solo.
- Un equipo con convenciones propias puede tener un perfil hecho a mano, en un repo aparte.

`profiles/example/` es un perfil de muestra: sirve de plantilla y lo usan las pruebas.

Siempre estás vos (el avatar del responsable) y en cada proyecto hay dos **tablones** fijos:
- **Pendientes**: tu bandeja. Muestra lo que está en curso, lo que sigue y lo hecho. Sale de las tareas de Claude Code de la sesión y de `pendientes.md`.
- **Auditorías**: las fricciones detectadas (`fricciones.md`), abiertas y resueltas.

Se ven como dos pizarras en tu despacho y como pestañas.

## Instalación

Requisitos: Windows, Claude Code, Python 3.12+ (solo librería estándar) y Node (para la statusline). La web ya viene compilada en `web/dist`.

1. Instalar el plugin una vez:
   ```
   py -3 scripts/install.py [--statusline]
   ```
   El instalador:
   - registra el `python.exe` real (rechaza el alias de la Microsoft Store);
   - genera los hooks y las skills `/oficina:abrir` y `/oficina:configurar`;
   - instala el plugin `oficina@agents-office` a nivel usuario.

   Con `--statusline` envuelve la statusline de `~/.claude/settings.json`: en la terminal se sigue viendo igual y la oficina recibe el modelo, el esfuerzo, el uso de la ventana de contexto y los límites de 5 h y 7 días. Deja un respaldo en `settings.json.antes-oficina`; `--remove-statusline` vuelve atrás.
2. En cada proyecto que quieras seguir, desde Claude Code: `/oficina:configurar`. Equivale a:
   ```
   py -3 scripts/configure.py <carpeta-del-proyecto>              # muestra el plan, no escribe nada
   py -3 scripts/configure.py <carpeta-del-proyecto> --apply [--claude-md]
   ```
   El script:
   - arma el perfil en `~/.agents-office/profiles/<id>/`, ubicando a cada agente de `.claude/agents` en una sala (las lentes en lectura, el verificador en el paso…);
   - crea `pendientes.md` y `fricciones.md` si no existen;
   - con `--claude-md`, les pide a los agentes del proyecto que mantengan los tablones.

   Para un perfil hecho a mano: `--profile <carpeta>`. Para dar de baja: `--remove`.

Solo se registran las sesiones de los proyectos configurados; el resto no deja rastro. Si se mueve o se renombra la carpeta de este repo, hay que volver a correr el instalador.

## Uso diario

- Desde Claude Code: `/oficina:abrir`.
- Desde PowerShell: `.\start-office.ps1`. Levanta el servidor en segundo plano, si no estaba corriendo, y abre `http://127.0.0.1:8765/`. Con `-Stop` lo apaga.
- A mano: `py -3 -m server [--profile CARPETA] [--port N]`.

La pantalla tiene cuatro partes:
- **Cabecera:** el selector de proyecto (si hay más de uno), el agente principal, el modelo, el esfuerzo, el contexto y los límites, y la línea de tu statusline.
- **Piso:** quién trabaja, espera, piensa, tiene un error o está ocioso.
- **Ocho pestañas** de solo lectura: aprobaciones, pendientes, auditorías, flujos, actividad, memoria, corridas y catálogo.
- **Barra de tarjetas:** una por agente. Al tocar una, la selección filtra las pestañas.

En el teléfono, el plano queda arriba, los agentes abajo y los paneles en otra vista.

## Desde el celular (mismo Wi-Fi)

Por defecto la oficina solo se ve desde la propia compu. Para abrirla desde el celular:

1. Activar el acceso: `py -3 scripts/lan.py --enable`. Genera una clave y muestra la dirección para el celular.
2. Reiniciar la oficina: `.\start-office.ps1 -Stop` y después `.\start-office.ps1`. La primera vez, Windows puede preguntar si deja que Python reciba conexiones: elegí **redes privadas**.
3. En el celular, conectado al mismo Wi-Fi, abrir la dirección con la clave (`http://<ip-de-la-compu>:8765/?key=…`). La clave queda guardada en el celular y sale de la URL.

En la compu, el botón **Celular** de la cabecera muestra esa dirección; `py -3 scripts/lan.py --show` también.

- Sin la clave no se ve nada, y tras 10 intentos fallidos esa dirección queda bloqueada 10 minutos.
- Desde el celular todo es de solo lectura: el editor del piso se usa desde la compu.
- El tráfico no va cifrado: usalo solo en un Wi-Fi de confianza (casa u oficina), nunca en uno público.
- `--new-key` cambia la clave (los celulares vuelven a pedirla) y `--disable` lo apaga.
- Si el celular no llega: la red Wi-Fi tiene que figurar como privada en Windows y el puerto tiene que estar permitido. En una PowerShell de administrador: `New-NetFirewallRule -DisplayName "agents-office" -Direction Inbound -Protocol TCP -LocalPort 8765 -Action Allow -Profile Private`. Algunas redes corporativas aíslan los dispositivos entre sí; ahí no hay forma de llegar.

## Datos

| Qué | Dónde |
|---|---|
| Eventos capturados (uno por día, se borran a los 14 días) | `<datos>/events/AAAA-MM-DD.jsonl` |
| Errores del hook (sin contenido) | `<datos>/errors.log` |
| Config del hook (la genera el instalador) | `<datos>/config.json` |
| Salida del servidor | `<datos>/server.log` |
| Acceso desde el celular (clave) | `<datos>/lan.json` |
| Proyectos registrados | `<datos>/projects.json` |
| Perfiles generados por `/oficina:configurar` | `<datos>/profiles/<id>/` |
| Última foto de la statusline de cada sesión (se borra a los 7 días) | `<datos>/statusline/` |

`<datos>` es la carpeta común de la oficina: `~/.agents-office`, o `AGENTS_OFFICE_DATA`. Borrarla da de baja todos los proyectos. Los eventos guardan nombres de herramientas, rutas y resúmenes cortos, nunca prompts, mensajes ni contenido de archivos.

## Agentes nuevos

Un agente nuevo en `.claude/agents/` aparece solo en la **recepción**, marcado "sin zona". Para darle lugar:
1. Agregar una regla en `zones.json` del perfil: `{ "agent": "mi-agente", "zone": "reading" }`. Los patrones como `lente-*` valen.
2. Opcional: fijar su sprite en `sprites.json` y su nombre corto en `profile.json` → `floor.short_names`.

Los cambios se toman al recargar la página. Si hace falta, se suman escritorios con el editor del piso (botón "Editar piso", en escritorio).

## Desinstalar

```
py -3 scripts/install.py --generate-only --remove-statusline
claude plugin uninstall oficina@agents-office
claude plugin marketplace remove agents-office
```

Después, opcionalmente, borrar la carpeta `<datos>`.

## Desarrollo

El código (carpetas, archivos, identificadores y claves de los JSON) está en inglés; la interfaz y la documentación, en español.


- **Recompilar la web** (después de cambiar `web/pixel-agents/webview-ui/src/app`):
  ```
  cd web/pixel-agents
  npm install
  npm run build
  ```
  Escribe en `web/dist`, que se versiona. Ver `web/pixel-agents/ORIGIN.md`.
- **Probar sin un equipo real:** el simulador escribe eventos ficticios en una carpeta aparte.
  ```
  py -3 scripts/simulate.py --data %TEMP%\agents-office-sim
  set AGENTS_OFFICE_DATA=%TEMP%\agents-office-sim
  py -3 -m server
  ```
- **Pruebas:** `py -3 -m unittest discover -s tests`. Usan siempre el perfil de ejemplo.

## Qué garantiza

- Los hooks nunca bloquean ni frenan a los agentes: salen siempre con código 0 y los no críticos son async.
- Una sesión ajena al equipo no deja rastro.
- El servidor escucha solo en `127.0.0.1` (salvo que actives el acceso desde el celular, que pide clave y es de solo lectura), rechaza otro `Host`, no habilita CORS y lee el área en solo lectura. Su única escritura es el `layout.json` del perfil, desde el editor del piso.

## Licencias

- Código propio: MIT, © 2026 Matías Campoy. Ver `LICENSE`.
- Motor y assets de Pixel Agents (`web/pixel-agents/core`, `web/pixel-agents/webview-ui`): MIT, © 2026 Pablo De Lucca. Ver `web/pixel-agents/LICENSE` y `web/pixel-agents/ORIGIN.md`.
- Personajes: basados en el pack MetroCity de JIK-A-4 (CC0). Las variantes y el avatar se generan en build: ver [docs/avatar.md](docs/avatar.md).
- Fuente VT323: SIL Open Font License 1.1 (`web/pixel-agents/webview-ui/public-app/fonts/OFL-VT323.txt`).
