"""Document flows: type and stage (from the profile's flows.json), verifier passes and owner waits.

Documents are discovered from the agents' writes. Of each file only the header table is read and, in
verification reports, the round titles.

Round of each verification pass: there is one verification report per cycle and each round is a section.
If k verifier runs wrote it today and the file ends at round R, the i-th run (in order) was round
R - k + i. If there are not enough titles, the header's "Rondas" column is used and, failing that, round 1.

Stage texts ("verificación 1/2", "corrección", ...) are shown as-is in the web, so they are Spanish.
"""
import re

from .util import matches

VERIFICATION_TYPE = "verification"

# UI text (Spanish): stages and actions shown in the Flows tab
TEXT = {
    "unknown": "desconocido",
    "research": "investigación",
    "verification": "verificación {label}",
    "verification_unknown": "verificación ronda ?",
    "correction": "corrección",
    "blocked": "bloqueado tras {n} rondas",
    "verifies": "verifica (ronda {label})",
    "writes": "escribe",
    "lays_out": "maqueta",
    "owner_review": "revisión del responsable",
    "final_review": "revisión final",
    "round_unknown": "ronda ?",
    "layout_work": "maquetado",
}


class Flows:
    def __init__(self, config, area):
        self.config = config
        self.area = area
        self.max_rounds = config.get("max_rounds", 2)
        # Team conventions (the profile's flows.json):
        # - external_pending_type: documents made by someone outside the team (flagged as pending)
        # - initial_review_types: the owner reviews them before they go through the verifier
        # - final_review_types: once verified they wait for a "final review" instead of the usual one
        # - closed_states: header states that mark the document as finished
        self.external_type = config.get("external_pending_type")
        self.initial_review = set(config.get("initial_review_types", []))
        self.final_review = set(config.get("final_review_types", []))
        self.closed_states = set(config.get("closed_states", []))
        waits = config.get("owner_waits", {})
        self.review_wait = waits.get("review", TEXT["owner_review"])
        self.final_wait = waits.get("final", TEXT["final_review"])

    def classify(self, rel):
        if not rel or any(matches(rel, p) for p in self.config.get("ignore", [])):
            return None
        for rule in self.config.get("rules", []):
            if matches(rel, rule["pattern"]):
                return {"type": rule["type"], "stage": rule["stage"]}
        return None

    def is_document(self, rel):
        return self.classify(rel) is not None

    def mirror(self, report, known):
        """Documents a report verifies: the ones its header names, or the ones from the mirror rule."""
        named = self.area.named_documents(report) if self.area else []
        found = []
        for name in named:
            base = name.rsplit("/", 1)[-1].lower()
            found += [k for k in known if k.lower().endswith("/" + base) and k != report]
        if found:
            return sorted(set(found)), self._type_by_mirror(report)
        for rule in self.config.get("mirror", []):
            m = re.match(rule["report"], report)
            if not m:
                continue
            pattern = rule["document"].format(**{k: v for k, v in m.groupdict().items() if v is not None})
            docs = [k for k in known if matches(k, pattern) and k != report]
            if not docs and "*" not in pattern:
                docs = [pattern]
            return sorted(set(docs)), rule["type"]
        return [], None

    def _type_by_mirror(self, report):
        for rule in self.config.get("mirror", []):
            if re.match(rule["report"], report):
                return rule["type"]
        return None

    def build(self, model_snapshot, writes, drive_operations, tasks=None, known=None, labels=None):
        """Today's documents in progress, from the writes (already ordered by ts)."""
        instances = {i["key"]: i for i in model_snapshot["instances"]}
        labels = labels or {}
        if known is None:
            known = sorted(set(w["path"] for w in writes) | set(self.area.files() if self.area else []))
        documents = {}
        passes = []
        runs_by_report = {}

        def doc(rel, cls):
            d = documents.get(rel)
            if d is None:
                d = documents[rel] = {"path": rel, "type": cls["type"], "stage": cls["stage"], "history": [],
                                      "verifications": [], "last_write": None, "verified_at": None,
                                      "external_pending": bool(self.external_type) and cls["type"] == self.external_type}
            return d

        # First pass: verifier runs per report, to number their rounds.
        for w in writes:
            cls = self.classify(w["path"])
            if cls and cls["type"] == VERIFICATION_TYPE:
                runs = runs_by_report.setdefault(w["path"], [])
                if w["instance"] not in [r["instance"] for r in runs]:
                    runs.append(w)
        pass_of = {}
        for report, runs in runs_by_report.items():
            rounds = (self.area.rounds(report) if self.area else None) or {}
            final = rounds.get("round") or 1
            cycle = rounds.get("cycle") or 1
            source = rounds.get("source") or "assumed"
            docs, doc_type = self.mirror(report, known)
            k = len(runs)
            # Conclusive: the round comes from the titles or the header, and the report has at least as many
            # rounds as verifier runs today. Otherwise "round ?" instead of guessing.
            conclusive = source != "assumed" and k <= final
            for i, w in enumerate(runs, 1):
                round_ = final - k + i if conclusive else None
                verification = {"ts": w["ts"], "instance": w["instance"], "who": labels.get(w["instance"], w["instance"]),
                                "report": report, "documents": docs, "document_type": doc_type or TEXT["unknown"],
                                "round": round_, "cycle": cycle, "conclusive": conclusive, "round_source": source,
                                "label": f"{round_}/{self.max_rounds}" if conclusive else "?"}
                passes.append(verification)
                pass_of[(report, w["instance"])] = verification

        # Second pass, in time order: stages, corrections and verifications.
        for w in writes:
            cls = self.classify(w["path"])
            if cls is None:
                continue
            if cls["type"] == VERIFICATION_TYPE:
                verification = pass_of.get((w["path"], w["instance"]))
                if verification is None or verification["ts"] != w["ts"]:
                    continue  # the same verifier rewriting its report: a single pass
                for rel in verification["documents"]:
                    d = doc(rel, self.classify(rel) or {"type": verification["document_type"], "stage": TEXT["research"]})
                    d["verifications"].append(verification)
                    d["history"].append({"ts": w["ts"], "instance": w["instance"], "agent": w["agent"],
                                         "who": verification["who"], "action": TEXT["verifies"].format(label=verification["label"])})
                    d["stage"] = (TEXT["verification"].format(label=verification["label"]) if verification["conclusive"]
                                  else TEXT["verification_unknown"])
                    d["verified_at"] = w["ts"]
                continue
            d = doc(w["path"], cls)
            d["stage"] = TEXT["correction"] if d["verified_at"] and w["ts"] > d["verified_at"] else cls["stage"]
            d["history"].append({"ts": w["ts"], "instance": w["instance"], "agent": w["agent"],
                                 "who": labels.get(w["instance"], w["instance"]), "action": TEXT["writes"]})
            d["last_write"] = w["ts"]

        layout_work = self.config.get("layout_work", {})
        for op in drive_operations:
            if op["agent"] not in layout_work.get("agents", []):
                continue
            rel = f"drive:{op['file']}"
            d = doc(rel, {"type": layout_work.get("type", TEXT["layout_work"]), "stage": layout_work.get("stage", TEXT["layout_work"])})
            d["history"].append({"ts": op["ts"], "instance": op["instance"], "agent": op["agent"],
                                 "who": labels.get(op["instance"], op["instance"]), "action": TEXT["lays_out"]})
            d["last_write"] = op["ts"]

        task_entries = (tasks or {}).get("entries", [])
        out = []
        for d in documents.values():
            d["history"].sort(key=lambda h: h["ts"])
            d["verifications"].sort(key=lambda v: v["ts"])
            head = self.area.header(d["path"]) if self.area and not d["path"].startswith("drive:") else None
            d["header"] = {k: head[k] for k in ("title", "status", "version", "last_review")} if head else None
            active = any(instances.get(h["instance"], {}).get("state") in ("working", "waiting")
                         for h in d["history"][-1:])
            d["tasks"] = related(d["path"], task_entries)
            d["blocked"] = bool(d["verifications"] and (d["verifications"][-1]["round"] or 0) >= self.max_rounds and d["tasks"]
                                and (d["last_write"] is None or d["last_write"] <= d["verifications"][-1]["ts"]))
            d["owner_wait"] = None
            status = (d["header"] or {}).get("status")
            if not active and status in (None, "borrador"):
                if d["blocked"]:
                    d["stage"] = TEXT["blocked"].format(n=self.max_rounds)
                    d["owner_wait"] = "tasks"
                elif d["type"] in self.initial_review and not d["verifications"]:
                    d["owner_wait"] = self.review_wait
                elif d["type"] in self.final_review and d["verifications"]:
                    d["owner_wait"] = self.final_wait
                elif d["verifications"] and (d["last_write"] is None or d["verifications"][-1]["ts"] >= d["last_write"]):
                    d["owner_wait"] = self.review_wait
            if d["owner_wait"] and d["owner_wait"] != "tasks":
                d["stage"] = d["owner_wait"]
            if status in self.closed_states and not active:
                d["stage"] = status
            for h in d["history"]:
                h["ts"] = h["ts"].isoformat(timespec="seconds")
            d["last_write"] = d["last_write"].isoformat(timespec="seconds") if d["last_write"] else None
            d["verified_at"] = d["verified_at"].isoformat(timespec="seconds") if d["verified_at"] else None
            out.append(d)

        def serialize(v):
            return {**v, "ts": v["ts"].isoformat(timespec="seconds")}

        passes_out = [serialize(v) for v in sorted(passes, key=lambda v: v["ts"])]
        for d in out:
            d["verifications"] = [serialize(v) for v in d["verifications"]]
        out.sort(key=lambda d: d["last_write"] or d["verified_at"] or "", reverse=True)
        return {"documents": out, "verifications": passes_out, "verification_summary": summarize(passes_out)}


def related(path, entries):
    """Entries of the tasks file that name the document (path or file name)."""
    name = path.rsplit("/", 1)[-1].lower()
    out = []
    for e in entries:
        paths = [p.lower() for p in e.get("paths", [])]
        if any(p == path.lower() or p.endswith("/" + name) or p == name for p in paths) or name in e.get("text", "").lower():
            out.append({"date": e.get("date"), "title": e.get("title")})
    return out


def summarize(passes):
    """Today's verifier passes by document type and round, for the verifier on the floor."""
    summary = {}
    for v in passes:
        key = f"{v['document_type']} {v['label'] if v['conclusive'] else TEXT['round_unknown']}"
        summary[key] = summary.get(key, 0) + 1
    return summary
