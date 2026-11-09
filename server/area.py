"""Read-only access to the area root, through an allowlist.

Nothing in this module writes to the area. Paths it receives are relative to the root, with '/'.

Read policy (the area may live on Google Drive in streaming mode): reading a cloud-only file forces a
download, and Drive does not let us tell those files apart (the volume shows up as FAT32 without
"cloud-only" attributes). So every file is treated as possibly cloud-only and is read only:
  - with `refresh(path)`, which the server calls when an event names that path;
  - with `sweep()`, every 5 minutes;
  - with `read(path)`, when the owner opens that file from the web.
The first two only read if the modification time changed. Everything else (headers, rounds, search,
tasks, .remember, status) works on the cache, without touching the area.
Listing folders and reading modification times does not download content.

The team documents follow Spanish conventions (header columns "Estado", "Versión", "Última revisión";
verification sections "## Ronda N"); those literals are matched here on purpose.
"""
import os
import re
from pathlib import Path

from .util import header_table

EXTENSIONS = (".md",)
EXCLUDED = {".git", "__pycache__", "node_modules", "pages", "logs", "tmp", ".playwright-mcp", ".venv", "venv",
            "dist", "build", ".next", ".cache"}
# With "." among the roots the allowlist is the whole project (except EXCLUDED and hidden folders),
# down to this depth: code projects can be large.
WHOLE_PROJECT_DEPTH = 4
MAX_BYTES = 2_000_000
HEADER_LINES = 15


class OutsideAllowlist(PermissionError):
    pass


class Area:
    def __init__(self, root, roots=(), extensions=EXTENSIONS, remember=None, status=None):
        """roots: first-level folders of the allowlist (from the profile). remember and status: relative
        folders with the .remember notes and the run reports, if the team has them."""
        self.root = Path(root)
        self.roots = tuple(roots)
        self.remember_folder = remember.strip("/") + "/" if remember else None
        self.status_folder = status.strip("/") + "/" if status else None
        self.extensions = tuple(e.lower() for e in extensions)
        self._cache = {}  # relative path -> (mtime_ns, text)
        self.reads = 0    # how many files were read from the area (for tests and diagnostics)

    # --- Allowlist ---------------------------------------------------------------

    def safe_path(self, relative):
        if not isinstance(relative, str) or not relative.strip():
            raise OutsideAllowlist("empty path")
        rel = relative.replace("\\", "/").strip("/")
        parts = rel.split("/")
        if any(p in ("", ".", "..") for p in parts) or ":" in rel:
            raise OutsideAllowlist("path not allowed")
        whole = "." in self.roots
        if not whole and parts[0] not in self.roots:
            raise OutsideAllowlist("outside the allowed roots")
        if whole and any(p in EXCLUDED for p in parts[:-1]):
            raise OutsideAllowlist("excluded folder")
        if not rel.lower().endswith(self.extensions):
            raise OutsideAllowlist("extension not allowed")
        absolute = (self.root / rel).resolve()
        allowed = self.root.resolve() if whole else (self.root / parts[0]).resolve()
        if allowed not in absolute.parents:
            raise OutsideAllowlist("the path leaves its root")
        return absolute

    # --- The only reads from the area ---------------------------------------------

    def refresh(self, relative):
        """Reads the file if it changed since the last read. Returns True if it read it."""
        try:
            path = self.safe_path(relative)
            st = path.stat()
        except OutsideAllowlist:
            return False
        except OSError:
            self._cache.pop(relative, None)
            return False
        cached = self._cache.get(relative)
        if cached and cached[0] == st.st_mtime_ns:
            return False
        if st.st_size > MAX_BYTES:
            return False
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        self.reads += 1
        self._cache[relative] = (st.st_mtime_ns, text)
        return True

    def sweep(self):
        """Full sweep: lists the allowlist and refreshes what changed. Forgets deleted files."""
        present = set(self.files())
        read = sum(1 for rel in sorted(present) if self.refresh(rel))
        for rel in list(self._cache):
            if rel not in present:
                del self._cache[rel]
        return read

    def read(self, relative):
        """For the web: the owner opens a file. Refreshes it and returns its text."""
        self.safe_path(relative)
        self.refresh(relative)
        if relative not in self._cache:
            raise FileNotFoundError(relative)
        return self._cache[relative][1]

    # --- Cache ---------------------------------------------------------------------

    def text(self, relative):
        cached = self._cache.get(relative)
        return cached[1] if cached else None

    def cached(self):
        return sorted(self._cache)

    def exists(self, relative):
        return relative in self._cache

    def _lines(self, relative, n=HEADER_LINES):
        text = self.text(relative)
        return text.splitlines()[:n] if text is not None else None

    # --- Documents: only the header ----------------------------------------------------

    def header(self, relative):
        """Title and header table. Nothing else from the content is used."""
        lines = self._lines(relative)
        if lines is None:
            return None
        title = next((l[2:].strip() for l in lines if l.startswith("# ")), None)
        table = header_table(lines)
        status = table.get("Estado")
        return {
            "title": title,
            "status": status.lower() if status else None,
            "version": table.get("Versión"),
            "last_review": table.get("Última revisión") or table.get("Fecha"),
            "columns": table,
        }

    def rounds(self, relative):
        """Rounds of a verification report, from its section titles or, failing that, from its header.

        Returns {"cycle", "round", "header_total", "source": titles|header|assumed}.
        Only title lines and the header table are used.
        """
        text = self.text(relative)
        if text is None:
            return None
        cycle, round_ = 1, 0
        for line in text.splitlines():
            if not line.startswith("#"):
                continue
            m = re.match(r"^#{2,3}\s+(?:Ciclo\s+(\d+),\s*)?[Rr]onda\s+(\d+)\b", line)
            if m:
                n = int(m.group(2))
                if m.group(1):
                    cycle = int(m.group(1))
                elif round_ and n <= round_:
                    cycle += 1
                round_ = n
        header = header_table(text.splitlines()[:HEADER_LINES])
        numbers = re.findall(r"\d+", header.get("Rondas", ""))
        total = int(numbers[-1]) if numbers else None
        if round_:
            source = "titles"
        elif total:
            round_, source = total, "header"
        else:
            round_, source = 1, "assumed"
        return {"cycle": cycle, "round": round_, "header_total": total, "source": source}

    def named_documents(self, relative):
        """Paths between backticks in the "verified document" column of the header."""
        head = self.header(relative) or {}
        paths = []
        for column, value in head.get("columns", {}).items():
            if "verificad" in column.lower():
                paths += re.findall(r"`([^`]+\.md)`", value)
        return paths

    # --- Listing and search --------------------------------------------------------------

    def files(self):
        """Lists the allowlist (does not read content)."""
        for root in self.roots:
            base = self.root / root
            if not base.is_dir():
                continue
            for folder, subfolders, names in os.walk(base):
                if root == ".":
                    level = len(Path(folder).relative_to(base).parts)
                    subfolders[:] = [] if level >= WHOLE_PROJECT_DEPTH else [
                        s for s in subfolders if s not in EXCLUDED and not s.startswith(".") or s == ".claude"]
                else:
                    subfolders[:] = [s for s in subfolders if s not in EXCLUDED]
                for name in names:
                    if name.lower().endswith(self.extensions):
                        yield (Path(folder) / name).relative_to(self.root).as_posix()

    def search(self, query, limit=100):
        """Over the cache: whatever the sweep or the events already read."""
        query = (query or "").strip()
        if len(query) < 2:
            return []
        needle = query.lower()
        results = []
        for rel in self.cached():
            for n, line in enumerate(self.text(rel).splitlines(), 1):
                if needle in line.lower():
                    results.append({"path": rel, "line": n, "text": line.strip()[:200]})
                    if len(results) >= limit:
                        return results
        return results

    # --- Team files (from the cache) ---------------------------------------------------------

    def entries(self, relative):
        """'## date · title' entries with their bold fields. If that fails, the raw text."""
        text = self.text(relative)
        if text is None:
            return {"path": relative, "entries": [], "unread": True}
        entries, current = [], None
        # HTML comments (for example, the format guide in the templates) are not entries
        for line in re.sub(r"<!--.*?-->", "", text, flags=re.S).splitlines():
            m = re.match(r"^##\s+(.+)$", line)
            if m:
                title = m.group(1).strip()
                d = re.match(r"^(\d{4}-\d{2}-\d{2})\s*[·\-–]\s*(.+)$", title)
                current = {"date": d.group(1) if d else None, "title": d.group(2) if d else title,
                           "fields": {}, "text": []}
                entries.append(current)
                continue
            if current is None:
                continue
            current["text"].append(line)
            f = re.match(r"^\*\*([^*]+?):?\*\*:?\s*(.*)$", line)
            if f:
                current["fields"][f.group(1).strip().rstrip(":")] = f.group(2).strip()
            r = re.match(r"^(Repeticiones|Propuesta|Riesgo):\s*(.*)$", line)
            if r:
                current["fields"][r.group(1)] = r.group(2).strip()
        for e in entries:
            e["text"] = "\n".join(e["text"]).strip()
            e["paths"] = sorted(set(re.findall(r"`([^`\s]+\.md)`", e["text"])))
        result = {"path": relative, "header": self.header(relative), "entries": entries}
        if not entries:
            result["raw"] = text
        return result

    def remember(self):
        prefix = self.remember_folder
        files = []
        if not prefix:
            return files
        for rel in self.cached():
            if not rel.startswith(prefix) or "/" in rel[len(prefix):]:
                continue
            text = self.text(rel)
            entries = [{"title": t.strip(), "text": c.strip()}
                       for t, c in re.findall(r"^##\s+(.+)\n((?:(?!^##\s).*\n?)*)", text, flags=re.M)]
            files.append({"path": rel, "entries": entries, **({} if entries else {"raw": text})})
        return files

    def status(self):
        prefix = self.status_folder
        files = []
        if not prefix:
            return files
        kinds = {"corrida": "run", "cambios": "changes"}
        for rel in sorted(self.cached(), reverse=True):
            if not rel.startswith(prefix) or "/" in rel[len(prefix):]:
                continue
            name = rel[len(prefix):]
            m = re.match(r"^(\d{4}-\d{2}-\d{2})-(corrida|cambios)(.*)\.md$", name)
            lines = self._lines(rel, 12) or []
            files.append({
                "path": rel,
                "date": m.group(1) if m else None,
                "kind": kinds[m.group(2)] if m else "other",
                "variant": m.group(3).strip("-") if m and m.group(3) else None,
                "title": (lines[0].lstrip("# ").strip() if lines else None),
                "table": header_table(lines),
            })
        return files
