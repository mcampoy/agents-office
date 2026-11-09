"""Event simulator to try the floor without a real partner session.

Writes, in real time, events with the same format as plugin/hooks/capture.py into a separate data folder
(never into the real data folder). Then start the server pointing at that folder:

    py -3 scripts/simulate.py                      # writes to %TEMP%/agents-office-sim
    set AGENTS_OFFICE_DATA=%TEMP%\\agents-office-sim
    py -3 -m server

The script covers every floor state: working (reads and writes), waiting for approval, error,
handing off, done, idle, waiting for subagents, a general agent that leaves, an unzoned agent,
the mailbox, the archive (engram) and the main agent's checks.

    --speed N    divides the times by N (default 1)
    --data DIR   data folder (default %TEMP%/agents-office-sim)
"""
import argparse
import datetime as dt
import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from server.profile import Profile, data_folder  # noqa: E402

# The script uses the roles and scripts of the active profile (by default, the example one)
PROFILE = Profile()
ROOT = PROFILE.root
TEAM = PROFILE.team
MAIN = PROFILE["main_agent"]
MAILBOX = PROFILE["scripts"]["mailbox"] or "notificar.py"
CHECK = (PROFILE["scripts"]["checks"] or ["comprobar-citas.py"])[0]
TASKS = PROFILE["files"]["tasks"] or "pendientes.md"


def script():
    """List of (second, event). Ids are generated on every run."""
    s = f"sim-{uuid.uuid4().hex[:8]}"
    ids = {}

    def aid(name):
        return ids.setdefault(name, f"a{uuid.uuid4().hex[:15]}")

    def tu():
        return f"toolu_sim{uuid.uuid4().hex[:16]}"

    def area(rel):
        return str(Path(ROOT) / rel)

    steps = []

    def e(t, event, agent=None, type_=MAIN, **fields):
        d = {"event": event, "session_id": s, "agent_type": type_, "cwd": TEAM, "permission_mode": "auto"}
        if agent:
            d["agent_id"] = aid(agent)
        d.update({k: v for k, v in fields.items() if v is not None})
        steps.append((t, d))

    def tool(t0, dur, name, agent=None, type_=MAIN, summary=None, fails=False):
        u = tu()
        e(t0, "PreToolUse", agent, type_, tool_name=name, tool_use_id=u, summary=summary)
        end = "PostToolUseFailure" if fails else "PostToolUse"
        e(t0 + dur, end, agent, type_, tool_name=name, tool_use_id=u,
          summary={**(summary or {}), "duration_ms": int(dur * 1000)})

    def launch(t, type_, description, model, agent):
        u = tu()
        r = {"subagent_type": type_, "description": description, "model": model}
        e(t, "PreToolUse", tool_name="Agent", tool_use_id=u, summary=r)
        e(t + 0.5, "PostToolUse", tool_name="Agent", tool_use_id=u,
          summary={**r, "launched_agent": aid(agent), "launch_status": "async_launched"})
        e(t + 0.6, "SubagentStart", agent, type_)

    # Partner starts and gets the request
    e(0, "SessionStart", summary={"source": "startup"})
    e(2, "UserPromptSubmit", summary={"length": 420, "origin": "user"})
    tool(3, 2, "Read", summary={"path": area(TASKS)})
    tool(5, 1.5, "mcp__engram__mem_search")

    # Two research tasks in parallel
    launch(7, "investigador-proveedor", "Mistral", "sonnet", "inv1")
    launch(8, "investigador-proveedor", "Cohere", "sonnet", "inv2")
    for k in range(6):
        tool(9 + k * 6, 4, "WebFetch", "inv1", "investigador-proveedor", {"domain": "mistral.ai"})
    tool(46, 3, "Write", "inv1", "investigador-proveedor",
         {"path": area("data-security-governance/registry/providers/mistral.md")})
    e(52, "PreToolUse", "inv1", "investigador-proveedor", tool_name="SubagentHandback", tool_use_id="toolu_simhb1")
    e(58, "PostToolUse", "inv1", "investigador-proveedor", tool_name="SubagentHandback", tool_use_id="toolu_simhb1")
    e(59, "SubagentStop", "inv1", "investigador-proveedor")

    tool(10, 5, "mcp__playwright__browser_navigate", "inv2", "investigador-proveedor", {"domain": "cohere.com"})
    # Asks permission for a command and waits for the owner's approval
    u = tu()
    e(17, "PreToolUse", "inv2", "investigador-proveedor", tool_name="Bash", tool_use_id=u,
      summary={"command": "curl -s https://docs.cohere.com/"})
    e(17.2, "PermissionRequest", "inv2", "investigador-proveedor", tool_name="Bash", tool_use_id=u,
      summary={"command": "curl -s https://docs.cohere.com/"})
    e(70, "PostToolUse", "inv2", "investigador-proveedor", tool_name="Bash", tool_use_id=u,
      summary={"command": "curl -s https://docs.cohere.com/", "duration_ms": 900})
    for k in range(4):
        tool(72 + k * 5, 3, "Read", "inv2", "investigador-proveedor",
             {"path": area("data-security-governance/registry/providers/cohere.md")})

    # Verifier cross-checking a record
    launch(12, "verificador", "verificar ficha OpenAI", "opus", "ver")
    for k in range(5):
        tool(13 + k * 7, 5, "WebSearch", "ver", "verificador")
    tool(50, 3, "Write", "ver", "verificador",
         {"path": area("data-security-governance/research/registry/providers/openai/2026-11-09-verificacion.md")})

    # A lens reading
    launch(14, "lente-normativa", "mapa de referencias", "sonnet", "len")
    for k in range(12):
        tool(15 + k * 6, 4, "Read", "len", "lente-normativa",
             {"path": area("data-security-governance/regulatory/mapa-de-referencias.md")})

    # Writer that fails to write (error) and does nothing else
    launch(16, "redactor", "borrador interno", "sonnet", "red")
    tool(17, 3, "Read", "red", "redactor", {"path": area("data-security-governance/registry/providers/openai.md")})
    tool(22, 2, "Write", "red", "redactor",
         {"path": area("data-security-governance/drafts/internal/borrador.md")}, fails=True)

    # Temporary general agent: works for a while and finishes (leaves after 2 min)
    launch(18, "general-purpose", "comparar precios de APIs", "haiku", "gen")
    for k in range(4):
        tool(19 + k * 5, 3, "WebSearch", "gen", "general-purpose")
    e(40, "SubagentStop", "gen", "general-purpose")

    # Agent without a zone in zones.json: goes to the reception
    launch(20, "auditor-costos", "revisar consumo", "haiku", "aud")
    for k in range(5):
        tool(21 + k * 6, 4, "Grep", "aud", "auditor-costos", {"pattern": "costo"})

    # Partner: checks, Discord notice and end of turn with subagents still active
    tool(24, 2, "Bash", summary={"script": CHECK,
                                 "path": area("data-security-governance/registry/providers/openai.md")})
    tool(27, 2, "Bash", summary={"script": MAILBOX, "channel": (PROFILE["scripts"]["channels"] or ["avisos"])[0]})
    tool(29, 1, "Skill", summary={"skill": "estilo-equipo"})
    e(32, "Stop")
    return sorted(steps, key=lambda p: p[0])


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--data", default=str(Path(tempfile.gettempdir()) / "agents-office-sim"))
    args = parser.parse_args()
    if Path(args.data).resolve() == data_folder().resolve():
        raise SystemExit(f"El simulador no escribe en {data_folder()}: usá otra carpeta de datos.")
    folder = Path(args.data) / "events"
    folder.mkdir(parents=True, exist_ok=True)
    steps = script()
    start = time.monotonic()
    print(f"Simulando {len(steps)} eventos en {folder} (AGENTS_OFFICE_DATA={args.data})")
    for t, d in steps:
        wait = start + t / args.speed - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        now = dt.datetime.now().astimezone()
        line = {"ts": now.isoformat(timespec="milliseconds"), **d}
        with open(folder / f"{now.date().isoformat()}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    print("Guion terminado. Los estados que dependen del reloj (ocioso, retiro) siguen cambiando solos.")


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    main()
