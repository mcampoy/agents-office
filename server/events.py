"""Incremental reading of <data>/events/YYYY-MM-DD.jsonl.

On start it loads today's file (and yesterday's, for sessions that cross midnight). Afterwards it only
reads what is new since the last byte read. A line without a trailing '\\n' is still being written: it is
left for the next read. A line that is not JSON is discarded and counted.
"""
import datetime as dt
import json
from pathlib import Path


class EventReader:
    def __init__(self, folder, days=2):
        self.folder = Path(folder)
        self.days = days
        self.positions = {}
        self.events = []
        self.discarded = 0

    def files(self, today):
        return [self.folder / f"{(today - dt.timedelta(days=d)).isoformat()}.jsonl" for d in range(self.days - 1, -1, -1)]

    def read_new(self, today=None):
        """Returns how many new events were read."""
        today = today or dt.date.today()
        new = 0
        current = set()
        for path in self.files(today):
            current.add(path)
            if not path.exists():
                continue
            position = self.positions.get(path, 0)
            size = path.stat().st_size
            if size < position:  # the file was recreated
                position = 0
            if size == position:
                continue
            with open(path, "rb") as f:
                f.seek(position)
                chunk = f.read()
            end = chunk.rfind(b"\n")
            if end < 0:
                continue
            for line in chunk[:end].split(b"\n"):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    self.discarded += 1
                    continue
                if isinstance(event, dict):
                    self.events.append(event)
                    new += 1
            self.positions[path] = position + end + 1
        # Day change: whatever leaves the window is forgotten.
        if any(p not in current for p in self.positions):
            names = {p.stem for p in current}
            self.events = [e for e in self.events if (e.get("ts") or "")[:10] in names]
            self.positions = {p: v for p, v in self.positions.items() if p in current}
            new += 1
        return new
