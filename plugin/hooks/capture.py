"""Capture hook of the agents office.

Claude Code calls it on every event with the event JSON on stdin.
If the session belongs to a registered project (CLAUDE_PROJECT_DIR inside its folder), it appends a redacted line,
tagged with the project id, to <data>/events/YYYY-MM-DD.jsonl. The event cwd is stored only as data:
it changes if Claude changes directory, CLAUDE_PROJECT_DIR stays at the session root.

<data> comes as `--data <folder>` (the installer writes it in hooks.json); otherwise AGENTS_OFFICE_DATA
or ~/.agents-office. The team specifics (folder, scripts, channels, scheduled-run variable) live in
<data>/config.json, which the installer generates from the profile. Without config, nothing is captured.

Rules:
- Standard library only. No network. Never writes to stdout or stderr.
- A foreign session leaves nothing: neither events nor errors. The filter runs before reading the payload.
- Always exits with code 0. Errors go to <data>/errors.log,
  only with event, exception type and line: never the payload nor a tool response.
- Never stores content: no prompts, messages, file texts or responses.
- Whole lines with parallel writes: inter-process lock and, on Windows, a handle
  opened only with FILE_APPEND_DATA, with which the system appends each WriteFile at once.
"""
import datetime as dt
import json
import os
import re
import sys
import time


def data_folder(argv):
    if "--data" in argv[:-1]:
        return argv[argv.index("--data") + 1]
    return os.environ.get("AGENTS_OFFICE_DATA") or os.path.join(os.path.expanduser("~"), ".agents-office")


DATA = data_folder(sys.argv)
RETENTION_DAYS = 14
COMMAND_LENGTH = 120
TEXT_LENGTH = 200

# Team scripts (from config.json): the name is stored and, at most, its path or channel argument.
PATH_FLAGS = ("-ruta", "--ruta", "-path", "--path")
FILE_TOOLS = {"Write", "Edit", "MultiEdit", "Read", "NotebookEdit"}
LAUNCHERS = {"Agent", "Task"}
DRIVE_FILE_KEYS = ("fileId", "file_id", "documentId", "document_id", "presentationId",
                   "presentation_id", "spreadsheetId", "spreadsheet_id", "id", "title", "name")
LOCK_WAIT_S = 3


def now():
    return dt.datetime.now().astimezone()


_CONFIG = None


def load_registry():
    try:
        with open(os.path.join(DATA, "config.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def project_of(registry, folder):
    """The registered project that contains the session folder (the most specific one), or None."""
    candidates = [p for p in registry.get("projects", []) if p.get("dir") and inside(folder, p["dir"])]
    return max(candidates, key=lambda p: len(p["dir"])) if candidates else None


def load_config():
    """The config of this session's project (scripts, channels, scheduled-run variable). Empty if none."""
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = project_of(load_registry(), os.environ.get("CLAUDE_PROJECT_DIR")) or {}
    return _CONFIG


def normalize(path):
    return os.path.normcase(os.path.normpath(path))


def inside(path, base):
    if not path:
        return False
    p, b = normalize(path), normalize(base)
    return p == b or p.startswith(b.rstrip("\\/") + os.sep)


def is_team_session():
    return bool(load_config())


def short(value, length=TEXT_LENGTH):
    return value[:length] if isinstance(value, str) and value else None


# --- Summaries ----------------------------------------------------------------

def summarize_command(command):
    """Team scripts: name and path or channel argument. Any other command: the first 120 characters."""
    if not isinstance(command, str):
        return {}
    config = load_config()
    known = {n.lower() for n in config.get("scripts", [])}
    mailbox = (config.get("mailbox") or "").lower()
    checks = {n.lower() for n in config.get("checks", [])}
    names = [n.lower() for n in re.findall(r"[\w.+-]+\.(?:py|ps1|sh|js|mjs)\b", command, flags=re.IGNORECASE)]
    match = next((n for n in names if n in known or n == mailbox or n in checks), None)
    if match is None:
        mailbox_stem = mailbox.rsplit(".", 1)[0]
        if mailbox_stem and mailbox_stem in command.lower():
            # Something naming the notice script without being recognized: the text is never stored (it may be the message).
            return {"script": mailbox}
        return {"command": command[:COMMAND_LENGTH]}

    summary = {"script": match}
    tokens = split(command)
    index = next((i for i, t in enumerate(tokens) if t.lower().replace("\\", "/").endswith(match)), None)
    rest = tokens[index + 1:] if index is not None else []
    if match == mailbox:
        channel = value_of(rest, "--canal") or value_of(rest, "--channel")
        channels = set(config.get("channels", []))
        summary["channel"] = channel if channel in channels else config.get("default_channel", "avisos")
    elif match in checks:
        path = next((value_of(rest, f) for f in PATH_FLAGS if value_of(rest, f)), None) \
            or next((t for t in rest if not t.startswith("-")), None)
        if path:
            summary["path"] = short(path)
    else:
        flags = [t for t in rest if re.fullmatch(r"--?[A-Za-z][\w-]*", t)]
        if flags:
            summary["flags"] = flags[:6]
    return summary


def split(command):
    import shlex
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return command.split()


def value_of(tokens, flag):
    for i, t in enumerate(tokens[:-1]):
        if t.lower() == flag:
            return tokens[i + 1]
    return None


def summarize_tool(tool, tool_input):
    if not isinstance(tool_input, dict) or not tool:
        return {}
    if tool in FILE_TOOLS:
        return clean({"path": short(tool_input.get("file_path") or tool_input.get("notebook_path"))})
    if tool in ("Grep", "Glob"):
        return clean({"pattern": short(tool_input.get("pattern")), "path": short(tool_input.get("path"))})
    if tool in ("Bash", "PowerShell"):
        return summarize_command(tool_input.get("command"))
    if tool in LAUNCHERS:
        background = tool_input.get("run_in_background")
        return clean({
            "subagent_type": short(tool_input.get("subagent_type")),
            "description": short(tool_input.get("description")),
            "model": short(tool_input.get("model")),
            "background": background if isinstance(background, bool) else None,
        })
    if tool == "Skill":
        return clean({"skill": short(tool_input.get("skill") or tool_input.get("name"))})
    if tool == "WebFetch" or (tool.startswith("mcp__playwright") and tool.endswith("navigate")):
        return clean({"domain": domain(tool_input.get("url"))})
    if tool == "TaskCreate":
        return clean({"title": short(tool_input.get("subject"))})
    if tool == "TaskUpdate":
        return clean({"task_id": short(tool_input.get("taskId")), "status": short(tool_input.get("status"), 30)})
    if tool == "SendMessage":
        return clean({"to": short(tool_input.get("to"), 80)})
    if tool.startswith("mcp__"):
        name = tool.lower()
        if any(p in name for p in ("drive", "docs", "slides", "sheets")):
            for key in DRIVE_FILE_KEYS:
                value = tool_input.get(key)
                if isinstance(value, str) and value:
                    return {"file": value[:TEXT_LENGTH]}
        return {}
    # Any other tool (WebSearch, ToolSearch, Playwright, etc.): only its name.
    return {}


def domain(url):
    """Only the host name, as plain text: no scheme, user, password, port, path or query."""
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
    return host[:TEXT_LENGTH] if host and re.fullmatch(r"[a-z0-9.-]+", host) else None


def summarize_launch_response(response):
    """From the Agent response, only the link to the subagent. Nothing of the text."""
    if not isinstance(response, dict):
        return {}
    return clean({
        "launched_agent": short(response.get("agentId"), 64),
        "resolved_model": short(response.get("resolvedModel"), 64),
        "launch_status": short(response.get("status"), 30),
    })


def prompt_origin(prompt):
    """A prompt that arrives as a system message (<agent-message …>) was not written by the owner."""
    if not isinstance(prompt, str):
        return None
    m = re.match(r"\s*<([a-z][a-z0-9-]{0,40})[\s>]", prompt)
    return m.group(1) if m else "user"


def clean(d):
    return {k: v for k, v in d.items() if v is not None and v != "" and v != {}}


def record(payload):
    event = payload.get("hook_event_name")
    effort = payload.get("effort")
    if isinstance(effort, dict):
        effort = effort.get("level")
    r = {
        "ts": now().isoformat(timespec="milliseconds"),
        "event": event,
        "session_id": payload.get("session_id"),
        "prompt_id": payload.get("prompt_id"),
        "agent_id": payload.get("agent_id"),
        "agent_type": payload.get("agent_type"),
        "tool_name": payload.get("tool_name"),
        "tool_use_id": payload.get("tool_use_id"),
        "permission_mode": payload.get("permission_mode"),
        "effort": effort if isinstance(effort, (str, int)) else None,
        "cwd": short(payload.get("cwd"), 260),
        "project": short(load_config().get("id"), 80),
    }
    summary = {}
    tool = payload.get("tool_name")
    if event == "SessionStart":
        summary = {"source": short(payload.get("source"), 30), "model": short(payload.get("model"), 64)}
        variable = load_config().get("origin_variable") or {}
        if variable.get("name") and os.environ.get(variable["name"]) == str(variable.get("value", "1")):
            summary["origin"] = "scheduled-run"
    elif event == "SessionEnd":
        summary = {"reason": short(payload.get("reason"), 40)}
    elif event == "UserPromptSubmit":
        prompt = payload.get("prompt")
        summary = {"length": len(prompt) if isinstance(prompt, str) else None, "origin": prompt_origin(prompt)}
    elif event in ("PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest", "PermissionDenied"):
        summary = summarize_tool(tool, payload.get("tool_input"))
        if event == "PostToolUse" and tool in LAUNCHERS:
            summary.update(summarize_launch_response(payload.get("tool_response")))
        if event in ("PostToolUse", "PostToolUseFailure") and isinstance(payload.get("duration_ms"), (int, float)):
            summary["duration_ms"] = int(payload["duration_ms"])
        if event == "PostToolUseFailure" and isinstance(payload.get("is_interrupt"), bool):
            summary["interrupted"] = payload["is_interrupt"]
    elif event == "Notification":
        summary = {"notification_type": short(payload.get("notification_type"), 40)}
    elif event == "StopFailure":
        for key in ("error_type", "error", "reason"):
            value = payload.get(key)
            if isinstance(value, str) and re.fullmatch(r"[a-z_]{1,40}", value):
                summary = {"error_type": value}
                break
    elif event in ("TaskCreated", "TaskCompleted"):
        summary = {"task_id": short(payload.get("task_id"), 64), "title": short(payload.get("task_subject"))}
    # SubagentStart, SubagentStop and Stop: only the common fields. Never last_assistant_message.
    summary = clean(summary)
    if summary:
        r["summary"] = summary
    return clean(r)


# --- Writing --------------------------------------------------------------------

def append_line(path, line):
    """One whole line per call, even with many processes writing at once.

    1. Inter-process lock on `<path>.lock`: serializes the writes.
    2. On Windows it writes with a handle opened only with FILE_APPEND_DATA: the system
       positions at the end and writes each WriteFile at once. With Python's open("ab"), the
       CRT emulates append mode (seeks to the end, then writes), and two processes could overlap.
    If the lock is not acquired within LOCK_WAIT_S, point 2 still guarantees whole lines.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = line.encode("utf-8")
    with open(path + ".lock", "a+b") as lock:
        taken = acquire(lock)
        try:
            write_at_end(path, data)
        finally:
            if taken:
                release(lock)


def write_at_end(path, data):
    if os.name != "nt":
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, data)
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
    FILE_APPEND_DATA, SHARE_ALL, OPEN_ALWAYS, NORMAL = 0x4, 0x7, 4, 0x80
    handle = k32.CreateFileW(path, FILE_APPEND_DATA, SHARE_ALL, None, OPEN_ALWAYS, NORMAL, None)
    if handle in (None, wintypes.HANDLE(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        written = wintypes.DWORD(0)
        if not k32.WriteFile(handle, data, len(data), ctypes.byref(written), None) or written.value != len(data):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        k32.CloseHandle(handle)


def acquire(lock):
    """Inter-process lock, at most LOCK_WAIT_S."""
    try:
        import msvcrt
    except ImportError:
        import fcntl
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        return True
    lock.seek(0)
    limit = time.monotonic() + LOCK_WAIT_S
    while True:
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            if time.monotonic() > limit:
                return False
            time.sleep(0.003)


def release(lock):
    try:
        import msvcrt
    except ImportError:
        import fcntl
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        return
    lock.seek(0)
    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def prune(folder, today):
    limit = today - dt.timedelta(days=RETENTION_DAYS)
    for name in os.listdir(folder):
        m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\.jsonl(\.lock)?", name)
        if m and dt.date.fromisoformat(m.group(1)) < limit:
            os.remove(os.path.join(folder, name))


def log_error(event, error):
    """Only event, type and line: an exception message may carry part of the payload."""
    try:
        line = None
        tb = error.__traceback__
        while tb is not None:
            if tb.tb_frame.f_code.co_filename == __file__:
                line = tb.tb_lineno
            tb = tb.tb_next
        event = event if isinstance(event, str) and re.fullmatch(r"[A-Za-z]{1,40}", event) else "?"
        path = os.path.join(DATA, "errors.log")
        os.makedirs(DATA, exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > 1_000_000:
            os.replace(path, path + ".1")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{now().isoformat(timespec='seconds')}\t{event}\t{type(error).__name__}\tline {line}\n")
    except Exception:
        pass


def process(payload):
    today = now().date()
    folder = os.path.join(DATA, "events")
    append_line(os.path.join(folder, f"{today.isoformat()}.jsonl"),
                json.dumps(record(payload), ensure_ascii=False) + "\n")
    if payload.get("hook_event_name") == "SessionStart":
        prune(folder, today)
    try:
        announce(payload)
    except Exception as error:
        log_error("notice", error)


# --- Windows notices -------------------------------------------------------------
#
# Two moments the owner hears about even with the office closed: the main session ended its turn (review or
# assign another task) and someone waits for them (a permission or an answer). Each with its own sound. Off
# unless <data>/notifications.json says {"windows": true} (the installer writes it). The text never carries
# prompts, messages or commands: only the project, the kind and the tool name.

WAIT_NOTIFICATIONS = {"permission_prompt", "agent_needs_input"}
# Claude Code sends PermissionRequest and Notification(permission_prompt) for the same dialog
SAME_WAIT_S = 15
SOUNDS = {"done": "ms-winsoundevent:Notification.Default", "waiting": "ms-winsoundevent:Notification.Reminder"}
POWERSHELL_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"


def notices_enabled():
    try:
        with open(os.path.join(DATA, "notifications.json"), encoding="utf-8") as f:
            return json.load(f).get("windows") is True
    except (OSError, ValueError, AttributeError):
        return False


def notice_for(payload):
    """The notice for this event, or None."""
    event = payload.get("hook_event_name")
    if event == "Stop" and not payload.get("agent_id"):
        return {"kind": "done"}
    if event == "PermissionRequest":
        return {"kind": "waiting", "tool": short(payload.get("tool_name"), 60)}
    if event == "Notification" and payload.get("notification_type") in WAIT_NOTIFICATIONS:
        return {"kind": "waiting", "answer": payload.get("notification_type") == "agent_needs_input"}
    return None


def announce(payload):
    notice = notice_for(payload)
    if not notice or not notices_enabled():
        return
    session = str(payload.get("session_id") or "")
    state_path = os.path.join(DATA, "notices.json")
    try:
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    moment = time.time()
    last = state.get(session) or {}
    if notice["kind"] == "waiting" and last.get("kind") == "waiting" and moment - last.get("ts", 0) < SAME_WAIT_S:
        return
    state = {k: v for k, v in state.items() if moment - v.get("ts", 0) < 86400}
    state[session] = {"kind": notice["kind"], "ts": moment}
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f)
    notice = clean({**notice, "project": load_config().get("id"), "subagent": bool(payload.get("agent_id")) or None})
    test_log = os.environ.get("AGENTS_OFFICE_NOTICE_LOG")
    if test_log:
        with open(test_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(notice) + "\n")
        return
    show_toast(notice)


def toast_text(notice):
    who = "Un subagente" if notice.get("subagent") else "La sesión principal"
    if notice["kind"] == "done":
        return "Terminó el turno", "Revisá el resultado o asigná otra tarea."
    if notice.get("answer"):
        return "Espera tu respuesta", f"{who} necesita que le contestes."
    tool = notice.get("tool")
    return "Espera tu aprobación", f"{who} pide permiso" + (f" para {tool}." if tool else ".")


def show_toast(notice):
    """A Windows notification through Windows PowerShell (its WinRT bridge), detached: the hook does not wait."""
    if os.name != "nt":
        return
    from xml.sax.saxutils import escape
    title, body = toast_text(notice)
    project = notice.get("project") or "oficina"
    long = ' duration="long"' if notice["kind"] == "waiting" else ""
    xml = (f'<toast{long}><visual><binding template="ToastGeneric">'
           f'<text>{escape(title)}</text><text>{escape(body)}</text><text placement="attribution">{escape(project)}</text>'
           f'</binding></visual><audio src="{SOUNDS[notice["kind"]]}"/></toast>')
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null;"
        "$x = New-Object Windows.Data.Xml.Dom.XmlDocument;"
        f"$x.LoadXml('{xml.replace(chr(39), chr(39) * 2)}');"
        f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{POWERSHELL_APP_ID}')"
        ".Show([Windows.UI.Notifications.ToastNotification]::new($x))"
    )
    import base64
    import subprocess
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                      "-EncodedCommand", encoded], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=flags, close_fds=True)


def main():
    # A foreign session leaves no trace: its payload is not even parsed.
    try:
        mine = is_team_session()
    except Exception:
        mine = False
    raw = sys.stdin.buffer.read()
    if not mine:
        return 0
    event = None
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            event = payload.get("hook_event_name")
            process(payload)
    except Exception as error:
        log_error(event, error)
    return 0


if __name__ == "__main__":
    try:
        main()
    finally:
        os._exit(0)
