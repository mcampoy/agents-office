"""Shows the captured events of a day, one per line.

Usage: py -3 scripts/view_events.py [YYYY-MM-DD]
"""
import datetime as dt
import json
import os
import sys
from pathlib import Path

DATA = Path(os.environ.get("AGENTS_OFFICE_DATA") or Path.home() / ".agents-office")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    day = sys.argv[1] if len(sys.argv) > 1 else dt.date.today().isoformat()
    path = DATA / "events" / f"{day}.jsonl"
    if not path.exists():
        print(f"No hay eventos en {path}")
        return 1
    for line in path.read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        who = e.get("agent_type") or "?"
        if e.get("agent_id"):
            who += f"#{e['agent_id'][:8]}"
        print(f"{e['ts'][11:19]}  {e['event']:18} {who:32} {e.get('tool_name', ''):24} "
              f"{json.dumps(e.get('summary', {}), ensure_ascii=False)}")
    errors = DATA / "errors.log"
    if errors.exists():
        print(f"\nerrors.log:\n{errors.read_text(encoding='utf-8')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
