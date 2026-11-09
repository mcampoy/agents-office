"""Usage: py -3 -m server [--profile FOLDER] [--port 8765] [--data FOLDER]

Without --profile: the projects registered in <data>/projects.json (scripts/configure.py). If there are none,
a single profile: AGENTS_OFFICE_PROFILE, local.json or profiles/example (see docs/profile.md)."""
import argparse
import sys

from .offices import Offices
from .web import run


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="server")
    p.add_argument("--port", type=int)
    p.add_argument("--data")
    p.add_argument("--profile")
    args = p.parse_args()
    offices = Offices(data=args.data, profile=args.profile)
    for ident, o in offices.offices.items():
        print(f"Project {ident}: profile {o.profile.folder}")
    first = next(iter(offices.offices.values()))
    print(f"Data: {first.data}")
    run(offices, args.port or first.config.get("port", 8765))


if __name__ == "__main__":
    main()
