"""Hook de captura de la oficina de agentes.

Claude Code lo llama en cada evento con el JSON del evento por stdin.
Si la sesión es de un proyecto registrado (CLAUDE_PROJECT_DIR dentro de su carpeta), agrega una línea
redactada, marcada con el id del proyecto, a <datos>/eventos/AAAA-MM-DD.jsonl. El cwd del evento se guarda solo como dato:
cambia si Claude cambia de directorio, CLAUDE_PROJECT_DIR queda en la raíz de la sesión.

<datos> llega como `--datos <carpeta>` (lo escribe el instalador en hooks.json); si no, AGENTS_OFFICE_DATOS
o ~/.agents-office. Lo propio del equipo (carpeta, scripts, canales, variable de la corrida) está en
<datos>/config.json, que el instalador genera a partir del perfil. Sin config, no se captura nada.

Reglas:
- Solo librería estándar. Sin red. Nunca escribe en stdout ni en stderr.
- Una sesión ajena no deja nada: ni eventos ni errores. El filtro corre antes de leer el payload.
- Sale siempre con código 0. Los errores van a <datos>/errores.log,
  solo con evento, tipo de excepción y línea: nunca el payload ni la respuesta de una herramienta.
- Nunca guarda contenido: ni prompts, ni mensajes, ni textos de archivos, ni respuestas.
- Líneas enteras con escrituras en paralelo: cerrojo entre procesos y, en Windows, un handle
  abierto solo con FILE_APPEND_DATA, con el que el sistema agrega cada WriteFile al final de una vez.
"""
import datetime as dt
import json
import os
import re
import sys
import time



def carpeta_de_datos(argv):
    if "--datos" in argv[:-1]:
        return argv[argv.index("--datos") + 1]
    return os.environ.get("AGENTS_OFFICE_DATOS") or os.path.join(os.path.expanduser("~"), ".agents-office")


DATOS = carpeta_de_datos(sys.argv)
RETENCION_DIAS = 14
LARGO_COMANDO = 120
LARGO_TEXTO = 200

# Scripts del equipo (de config.json): se guarda el nombre y, como mucho, su argumento de ruta o de canal.
BANDERAS_DE_RUTA = ("-ruta", "--ruta", "-path", "--path")
ARCHIVOS = {"Write", "Edit", "MultiEdit", "Read", "NotebookEdit"}
LANZADORES = {"Agent", "Task"}
CLAVES_ARCHIVO_DRIVE = ("fileId", "file_id", "documentId", "document_id", "presentationId",
                        "presentation_id", "spreadsheetId", "spreadsheet_id", "id", "title", "name")
ESPERA_CERROJO_S = 3


def ahora():
    return dt.datetime.now().astimezone()


_CONFIG = None


def cargar_registro():
    try:
        with open(os.path.join(DATOS, "config.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def proyecto_de(registro, carpeta):
    """El proyecto registrado que contiene la carpeta de la sesión (el más específico), o None.
    Acepta el formato de varios proyectos ({"proyectos": [...]}) y el viejo, de un solo equipo ({"equipo_dir"})."""
    if "proyectos" in registro:
        candidatos = [p for p in registro["proyectos"] if p.get("dir") and dentro_de(carpeta, p["dir"])]
        return max(candidatos, key=lambda p: len(p["dir"])) if candidatos else None
    if registro.get("equipo_dir") and dentro_de(carpeta, registro["equipo_dir"]):
        return registro
    return None


def cargar_config():
    """La config del proyecto de esta sesión (scripts, canales, variable de la corrida). Vacía si no es de uno."""
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = proyecto_de(cargar_registro(), os.environ.get("CLAUDE_PROJECT_DIR")) or {}
    return _CONFIG


def normalizar(ruta):
    return os.path.normcase(os.path.normpath(ruta))


def dentro_de(ruta, base):
    if not ruta:
        return False
    r, b = normalizar(ruta), normalizar(base)
    return r == b or r.startswith(b.rstrip("\\/") + os.sep)


def es_sesion_del_equipo():
    return bool(cargar_config())


def corto(valor, largo=LARGO_TEXTO):
    return valor[:largo] if isinstance(valor, str) and valor else None


# --- Resúmenes ------------------------------------------------------------

def resumir_comando(comando):
    """Scripts del equipo: nombre y argumento de ruta o canal. Otro comando: los primeros 120 caracteres."""
    if not isinstance(comando, str):
        return {}
    config = cargar_config()
    conocidos = {n.lower() for n in config.get("scripts", [])}
    buzon = (config.get("buzon") or "").lower()
    controles = {n.lower() for n in config.get("controles", [])}
    nombres = [n.lower() for n in re.findall(r"[\w.+-]+\.(?:py|ps1|sh|js|mjs)\b", comando, flags=re.IGNORECASE)]
    conocido = next((n for n in nombres if n in conocidos or n == buzon or n in controles), None)
    if conocido is None:
        raiz_buzon = buzon.rsplit(".", 1)[0]
        if raiz_buzon and raiz_buzon in comando.lower():
            # Algo que nombra el script de avisos sin reconocerse: nunca se guarda el texto (puede ser el mensaje).
            return {"script": buzon}
        return {"comando": comando[:LARGO_COMANDO]}

    resumen = {"script": conocido}
    fichas = partir(comando)
    indice = next((i for i, t in enumerate(fichas) if t.lower().replace("\\", "/").endswith(conocido)), None)
    resto = fichas[indice + 1:] if indice is not None else []
    if conocido == buzon:
        canal = valor_de(resto, "--canal")
        canales = set(config.get("canales", []))
        resumen["canal"] = canal if canal in canales else config.get("canal_por_defecto", "avisos")
    elif conocido in controles:
        ruta = next((valor_de(resto, b) for b in BANDERAS_DE_RUTA if valor_de(resto, b)), None) \
            or next((t for t in resto if not t.startswith("-")), None)
        if ruta:
            resumen["ruta"] = corto(ruta)
    else:
        banderas = [t for t in resto if re.fullmatch(r"--?[A-Za-z][\w-]*", t)]
        if banderas:
            resumen["banderas"] = banderas[:6]
    return resumen


def partir(comando):
    import shlex
    try:
        return shlex.split(comando, posix=True)
    except ValueError:
        return comando.split()


def valor_de(fichas, bandera):
    for i, t in enumerate(fichas[:-1]):
        if t.lower() == bandera:
            return fichas[i + 1]
    return None


def resumir_herramienta(herramienta, entrada):
    if not isinstance(entrada, dict) or not herramienta:
        return {}
    if herramienta in ARCHIVOS:
        return limpiar({"ruta": corto(entrada.get("file_path") or entrada.get("notebook_path"))})
    if herramienta in ("Grep", "Glob"):
        return limpiar({"patron": corto(entrada.get("pattern")), "ruta": corto(entrada.get("path"))})
    if herramienta in ("Bash", "PowerShell"):
        return resumir_comando(entrada.get("command"))
    if herramienta in LANZADORES:
        return limpiar({
            "subagent_type": corto(entrada.get("subagent_type")),
            "description": corto(entrada.get("description")),
            "model": corto(entrada.get("model")),
            "en_segundo_plano": entrada.get("run_in_background") if isinstance(entrada.get("run_in_background"), bool) else None,
        })
    if herramienta == "Skill":
        return limpiar({"skill": corto(entrada.get("skill") or entrada.get("name"))})
    if herramienta == "WebFetch" or (herramienta.startswith("mcp__playwright") and herramienta.endswith("navigate")):
        return limpiar({"dominio": dominio(entrada.get("url"))})
    if herramienta in ("TaskCreate",):
        return limpiar({"titulo": corto(entrada.get("subject"))})
    if herramienta in ("TaskUpdate",):
        return limpiar({"task_id": corto(entrada.get("taskId")), "estado": corto(entrada.get("status"), 30)})
    if herramienta == "SendMessage":
        return limpiar({"para": corto(entrada.get("to"), 80)})
    if herramienta.startswith("mcp__"):
        nombre = herramienta.lower()
        if any(p in nombre for p in ("drive", "docs", "slides", "sheets")):
            for clave in CLAVES_ARCHIVO_DRIVE:
                valor = entrada.get(clave)
                if isinstance(valor, str) and valor:
                    return {"archivo": valor[:LARGO_TEXTO]}
        return {}
    # Cualquier otra herramienta (WebSearch, ToolSearch, Playwright, etc.): solo su nombre.
    return {}


def dominio(url):
    """Solo el nombre del host, en texto plano: sin esquema, usuario, clave, puerto, ruta ni consulta."""
    if not isinstance(url, str) or not url:
        return None
    from urllib.parse import urlsplit
    if "://" in url:
        if not url.lower().startswith(("http://", "https://")):
            return None
    elif re.match(r"^[A-Za-z0-9.-]+(?:[/?#]|$)", url):
        url = "//" + url
    else:
        return None
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    return host[:LARGO_TEXTO] if host and re.fullmatch(r"[a-z0-9.-]+", host) else None


def resumir_respuesta_lanzamiento(respuesta):
    """De la respuesta de Agent, solo el vínculo con el subagente. Nada del texto."""
    if not isinstance(respuesta, dict):
        return {}
    return limpiar({
        "agente_lanzado": corto(respuesta.get("agentId"), 64),
        "modelo_resuelto": corto(respuesta.get("resolvedModel"), 64),
        "estado_lanzamiento": corto(respuesta.get("status"), 30),
    })


def origen_del_prompt(prompt):
    """Un prompt que llega como mensaje del sistema (<agent-message …>) no lo escribió el responsable."""
    if not isinstance(prompt, str):
        return None
    m = re.match(r"\s*<([a-z][a-z0-9-]{0,40})[\s>]", prompt)
    return m.group(1) if m else "usuario"


def limpiar(d):
    return {k: v for k, v in d.items() if v is not None and v != "" and v != {}}


def registro(datos):
    evento = datos.get("hook_event_name")
    esfuerzo = datos.get("effort")
    if isinstance(esfuerzo, dict):
        esfuerzo = esfuerzo.get("level")
    r = {
        "ts": ahora().isoformat(timespec="milliseconds"),
        "evento": evento,
        "session_id": datos.get("session_id"),
        "prompt_id": datos.get("prompt_id"),
        "agent_id": datos.get("agent_id"),
        "agent_type": datos.get("agent_type"),
        "tool_name": datos.get("tool_name"),
        "tool_use_id": datos.get("tool_use_id"),
        "permission_mode": datos.get("permission_mode"),
        "effort": esfuerzo if isinstance(esfuerzo, (str, int)) else None,
        "cwd": corto(datos.get("cwd"), 260),
        "proyecto": corto(cargar_config().get("id"), 80),
    }
    resumen = {}
    herramienta = datos.get("tool_name")
    if evento == "SessionStart":
        resumen = {"source": corto(datos.get("source"), 30), "model": corto(datos.get("model"), 64)}
        variable = cargar_config().get("variable_origen") or {}
        if variable.get("nombre") and os.environ.get(variable["nombre"]) == str(variable.get("valor", "1")):
            resumen["origen"] = "corrida-semanal"
    elif evento == "SessionEnd":
        resumen = {"reason": corto(datos.get("reason"), 40)}
    elif evento == "UserPromptSubmit":
        prompt = datos.get("prompt")
        resumen = {"largo": len(prompt) if isinstance(prompt, str) else None, "origen": origen_del_prompt(prompt)}
    elif evento in ("PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest", "PermissionDenied"):
        resumen = resumir_herramienta(herramienta, datos.get("tool_input"))
        if evento == "PostToolUse" and herramienta in LANZADORES:
            resumen.update(resumir_respuesta_lanzamiento(datos.get("tool_response")))
        if evento in ("PostToolUse", "PostToolUseFailure") and isinstance(datos.get("duration_ms"), (int, float)):
            resumen["duracion_ms"] = int(datos["duration_ms"])
        if evento == "PostToolUseFailure" and isinstance(datos.get("is_interrupt"), bool):
            resumen["interrumpido"] = datos["is_interrupt"]
    elif evento == "Notification":
        resumen = {"tipo": corto(datos.get("notification_type"), 40)}
    elif evento == "StopFailure":
        for clave in ("error_type", "error", "reason"):
            valor = datos.get(clave)
            if isinstance(valor, str) and re.fullmatch(r"[a-z_]{1,40}", valor):
                resumen = {"tipo_error": valor}
                break
    elif evento in ("TaskCreated", "TaskCompleted"):
        resumen = {"task_id": corto(datos.get("task_id"), 64), "titulo": corto(datos.get("task_subject"))}
    # SubagentStart, SubagentStop y Stop: solo los campos comunes. Nunca last_assistant_message.
    resumen = limpiar(resumen)
    if resumen:
        r["resumen"] = resumen
    return limpiar(r)


# --- Escritura --------------------------------------------------------------

def agregar_linea(ruta, linea):
    """Una línea entera por llamada, aunque escriban muchos procesos a la vez.

    1. Cerrojo entre procesos sobre `<ruta>.lock`: serializa las escrituras.
    2. En Windows se escribe con un handle abierto solo con FILE_APPEND_DATA: el sistema
       posiciona al final y escribe cada WriteFile de una vez. Con open("ab") de Python, el
       CRT emula el modo append (busca el final y después escribe), y dos procesos podrían pisarse.
    Si el cerrojo no se consigue en ESPERA_CERROJO_S, el punto 2 sigue garantizando líneas enteras.
    """
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    datos = linea.encode("utf-8")
    with open(ruta + ".lock", "a+b") as cerrojo:
        tomado = tomar(cerrojo)
        try:
            escribir_al_final(ruta, datos)
        finally:
            if tomado:
                soltar(cerrojo)


def escribir_al_final(ruta, datos):
    if os.name != "nt":
        fd = os.open(ruta, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, datos)
        finally:
            os.close(fd)
        return
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    k32.WriteFile.argtypes = (wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD,
                              ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID)
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    FILE_APPEND_DATA, COMPARTIR_TODO, OPEN_ALWAYS, NORMAL = 0x4, 0x7, 4, 0x80
    handle = k32.CreateFileW(ruta, FILE_APPEND_DATA, COMPARTIR_TODO, None, OPEN_ALWAYS, NORMAL, None)
    if handle in (None, wintypes.HANDLE(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        escrito = wintypes.DWORD(0)
        if not k32.WriteFile(handle, datos, len(datos), ctypes.byref(escrito), None) or escrito.value != len(datos):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        k32.CloseHandle(handle)


def tomar(cerrojo):
    """Cerrojo entre procesos, como máximo ESPERA_CERROJO_S."""
    try:
        import msvcrt
    except ImportError:
        import fcntl
        fcntl.flock(cerrojo.fileno(), fcntl.LOCK_EX)
        return True
    cerrojo.seek(0)
    limite = time.monotonic() + ESPERA_CERROJO_S
    while True:
        try:
            msvcrt.locking(cerrojo.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            if time.monotonic() > limite:
                return False
            time.sleep(0.003)


def soltar(cerrojo):
    try:
        import msvcrt
    except ImportError:
        import fcntl
        fcntl.flock(cerrojo.fileno(), fcntl.LOCK_UN)
        return
    cerrojo.seek(0)
    msvcrt.locking(cerrojo.fileno(), msvcrt.LK_UNLCK, 1)


def podar(carpeta, hoy):
    limite = hoy - dt.timedelta(days=RETENCION_DIAS)
    for nombre in os.listdir(carpeta):
        m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\.jsonl(\.lock)?", nombre)
        if m and dt.date.fromisoformat(m.group(1)) < limite:
            os.remove(os.path.join(carpeta, nombre))


def registrar_error(evento, error):
    """Solo evento, tipo y línea: el mensaje de una excepción puede traer parte del payload."""
    try:
        linea = None
        tb = error.__traceback__
        while tb is not None:
            if tb.tb_frame.f_code.co_filename == __file__:
                linea = tb.tb_lineno
            tb = tb.tb_next
        evento = evento if isinstance(evento, str) and re.fullmatch(r"[A-Za-z]{1,40}", evento) else "?"
        ruta = os.path.join(DATOS, "errores.log")
        os.makedirs(DATOS, exist_ok=True)
        if os.path.exists(ruta) and os.path.getsize(ruta) > 1_000_000:
            os.replace(ruta, ruta + ".1")
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(f"{ahora().isoformat(timespec='seconds')}\t{evento}\t{type(error).__name__}\tlinea {linea}\n")
    except Exception:
        pass


def procesar(datos):
    hoy = ahora().date()
    carpeta = os.path.join(DATOS, "eventos")
    agregar_linea(os.path.join(carpeta, f"{hoy.isoformat()}.jsonl"),
                  json.dumps(registro(datos), ensure_ascii=False) + "\n")
    if datos.get("hook_event_name") == "SessionStart":
        podar(carpeta, hoy)


def main():
    # Una sesión ajena no deja rastro: ni siquiera se interpreta su payload.
    try:
        del_equipo = es_sesion_del_equipo()
    except Exception:
        del_equipo = False
    crudo = sys.stdin.buffer.read()
    if not del_equipo:
        return 0
    evento = None
    try:
        datos = json.loads(crudo)
        if isinstance(datos, dict):
            evento = datos.get("hook_event_name")
            procesar(datos)
    except Exception as error:
        registrar_error(evento, error)
    return 0


if __name__ == "__main__":
    try:
        main()
    finally:
        os._exit(0)
