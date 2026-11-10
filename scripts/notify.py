"""Turns on or off the Windows notices: the main session ended its turn, or someone waits for you.

Usage: py -3 scripts/notify.py [--enable | --disable | --test] [--data FOLDER]

The capture hook shows them (plugin/hooks/capture.py, "Windows notices"); the change applies to the next event,
without restarting anything. The output is read by the user, so it is Spanish.
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from server.profile import data_folder  # noqa: E402

SETTINGS = "notifications.json"


def load(data):
    try:
        return json.loads((Path(data) / SETTINGS).read_text(encoding="utf-8")).get("windows") is True
    except (OSError, ValueError, AttributeError):
        return False


def save(data, on):
    path = Path(data) / SETTINGS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"windows": on}) + "\n", encoding="utf-8")


def enable_by_default(data):
    """For the installer: on, unless the user already chose."""
    if not (Path(data) / SETTINGS).exists():
        save(data, True)
    return load(data)


def show_examples():
    spec = importlib.util.spec_from_file_location("capture", REPO / "plugin" / "hooks" / "capture.py")
    capture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(capture)
    capture.show_toast({"kind": "done", "project": "prueba"})
    capture.show_toast({"kind": "waiting", "project": "prueba", "tool": "Bash"})


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = p.add_mutually_exclusive_group()
    group.add_argument("--enable", action="store_true")
    group.add_argument("--disable", action="store_true")
    group.add_argument("--test", action="store_true")
    p.add_argument("--data")
    args = p.parse_args()
    data = data_folder(args.data)
    if args.enable:
        save(data, True)
    elif args.disable:
        save(data, False)
    elif args.test:
        show_examples()
        print("Mostré dos avisos de ejemplo: «Terminó el turno» y «Espera tu aprobación», cada uno con su sonido.")
        print("Si no aparecen, revisá en Windows: Configuración > Sistema > Notificaciones (y que no esté activo No molestar).")
    if load(data):
        print("Avisos de Windows: activados (fin de turno y esperas). Para apagarlos: py -3 scripts/notify.py --disable")
    else:
        print("Avisos de Windows: desactivados. Para activarlos: py -3 scripts/notify.py --enable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
