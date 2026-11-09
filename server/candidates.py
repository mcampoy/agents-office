"""New-agent candidate signal (phase 0 heuristic, item 11).

If the main agent launches general agents (without their own definition) with similar descriptions several
times, it may be worth creating a specialized agent for that task.

- Looks at general-agent launches of the last 14 days (the daily event files).
- Each `description` is normalized: lowercase, no accents, no stopwords (Spanish and English), no numbers
  and no provider names (those of `*/registry/providers/*.md` in the area).
- Descriptions with fewer than 3 useful words are dropped: with 2 words any pair looks alike.
- Two descriptions are similar if their Jaccard similarity (shared words / total words) is >= 0.5.
- A group of 3 or more launches connected by similarity is a candidate.

It is deterministic, needs no network and is explainable: the panel shows the descriptions and the shared
words. Descriptions were already redacted by the hook (the prompt is never stored).
"""
import datetime as dt
import json
import re
import unicodedata
from pathlib import Path

DAYS = 14
THRESHOLD = 0.5
MIN_WORDS = 3
MIN_GROUP = 3
LAUNCHERS = {"Agent", "Task"}

# Stopwords: the descriptions are written in Spanish or English
STOPWORDS = set("""
a al algo algun alguna algunas alguno algunos ante antes bajo cada como con contra cual cuales cuando de del
desde donde durante e el ella ellas ellos en entre era es esa esas ese eso esos esta estas este esto estos
hacia hasta la las le les lo los mas me mi mis muy ni no nos o otra otras otro otros para pero por porque que
quien se segun ser si sin sobre su sus tal tambien te tu tus un una unas uno unos y ya
the a an and or of to in on for with from by at as is are be this that these those it its into about over
""".split())


def normalize(text, proper_names=frozenset()):
    text = unicodedata.normalize("NFKD", (text or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    words = re.findall(r"[a-z][a-z0-9-]*", text)
    out = set()
    for w in words:
        for part in w.split("-"):
            if len(part) > 2 and part not in STOPWORDS and part not in proper_names and not part.isdigit():
                out.add(part)
    return out


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def provider_names(paths):
    names = set()
    for p in paths:
        m = re.search(r"/registry/providers/([^/]+)\.md$", p)
        if m:
            names |= normalize(m.group(1).replace("-", " "))
    return frozenset(names)


class Candidates:
    def __init__(self, events_folder, keep=None):
        self.folder = Path(events_folder)
        self.keep = keep or (lambda e: True)
        self._cache = {}  # file -> (mtime_ns, launches)

    def _launches(self, path):
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            return []
        previous = self._cache.get(path)
        if previous and previous[0] == mtime:
            return previous[1]
        out = []
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"PreToolUse"' not in line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("event") != "PreToolUse" or e.get("tool_name") not in LAUNCHERS or not self.keep(e):
                    continue
                s = e.get("summary") or {}
                if s.get("subagent_type") and s.get("description"):
                    out.append({"ts": e.get("ts"), "type": s["subagent_type"], "description": s["description"]})
        self._cache[path] = (mtime, out)
        return out

    def compute(self, today, is_generic, known_paths=()):
        """Groups of general-agent launches with similar descriptions."""
        proper = provider_names(known_paths)
        launches = []
        for d in range(DAYS):
            path = self.folder / f"{(today - dt.timedelta(days=d)).isoformat()}.jsonl"
            if path.exists():
                launches += [l for l in self._launches(path) if is_generic(l["type"])]
        current = set(self._cache) & {self.folder / f"{(today - dt.timedelta(days=d)).isoformat()}.jsonl" for d in range(DAYS)}
        self._cache = {k: v for k, v in self._cache.items() if k in current}

        useful = [(l, normalize(l["description"], proper)) for l in launches]
        useful = [(l, w) for l, w in useful if len(w) >= MIN_WORDS]
        # Groups: connected components of the "looks alike" graph
        parent = list(range(len(useful)))

        def root(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in range(len(useful)):
            for j in range(i + 1, len(useful)):
                if jaccard(useful[i][1], useful[j][1]) >= THRESHOLD:
                    parent[root(i)] = root(j)
        groups = {}
        for i in range(len(useful)):
            groups.setdefault(root(i), []).append(useful[i])
        candidates = []
        for members in groups.values():
            if len(members) < MIN_GROUP:
                continue
            shared = set.intersection(*(w for _, w in members))
            frequent = {}
            for _, words in members:
                for w in words:
                    frequent[w] = frequent.get(w, 0) + 1
            top = sorted(frequent, key=lambda w: (-frequent[w], w))[:6]
            candidates.append({
                "launches": len(members),
                "types": sorted({l["type"] for l, _ in members}),
                "words": sorted(shared) or top,
                "descriptions": sorted({l["description"] for l, _ in members})[:10],
                "last": max(l["ts"] or "" for l, _ in members),
            })
        candidates.sort(key=lambda c: (-c["launches"], c["last"]))
        return candidates
