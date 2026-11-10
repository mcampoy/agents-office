"""Office state model, built from the captured events.

It is a pure function: `Model(context).apply(events)` and then `snapshot(now)`.
Events are ordered by the hook timestamp (`ts`) and, for equal timestamps, by arrival order.
Async hooks can arrive out of order, so:
- Pre and Post are paired by `tool_use_id`; a Post that arrives before its Pre still closes the call.
- A subagent event that arrives before its SubagentStart creates the instance; the SubagentStart completes it.
- The launch -> subagent link uses an arrival-order queue (per session and type) until the exact link
  arrives (`launched_agent` in the PostToolUse of Agent), which fixes it if needed.
The server rebuilds the whole day with every new batch: the final order is always the `ts` order.
"""
import datetime as dt
import fnmatch
import re

WRITING = {"Write", "Edit", "MultiEdit", "NotebookEdit", "Bash", "PowerShell"}
READING = {"Read", "Grep", "Glob", "WebFetch", "WebSearch", "ToolSearch"}
LAUNCHERS = {"Agent", "Task"}
INTERNAL = {"SubagentHandback", "ToolSearch"}
FILE_WRITERS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
WAITING_NOTIFICATIONS = {"permission_prompt", "agent_needs_input"}

THRESHOLDS = {
    "recent_activity_s": 90,   # no open tool but recent events: still working; afterwards, thinking
    "idle_s": 300,             # N minutes without events with the session open
    "error_s": 120,            # how long the error bubble lasts
    "general_retire_s": 120,   # a general agent leaves the floor this long after finishing
    "closed_retire_s": 120,    # a closed session (SessionEnd) leaves the floor this long after closing
    "silent_retire_s": 3600,   # an open session without events this long leaves too, until its next event
}


def parse_ts(value):
    try:
        return dt.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def iso(moment):
    return moment.isoformat(timespec="seconds") if moment else None


def ordered(events):
    """By hook timestamp; events without a valid timestamp are left out."""
    stamped = []
    for i, e in enumerate(events):
        moment = parse_ts(e.get("ts"))
        if moment is not None:
            stamped.append((moment, i, e))
    stamped.sort(key=lambda t: (t[0], t[1]))
    return stamped


class Instance:
    def __init__(self, key, session, type_, is_main, agent_id=None):
        self.key = key
        self.session = session
        self.type = type_
        self.is_main = is_main
        self.agent_id = agent_id
        self.number = 1
        self.launch = None
        self.start = None
        self.end = None
        self.last_event = None
        self.streak_start = None
        self.open_calls = {}
        self.closed_early = set()
        self.last_tool = None
        self.last_resource = None
        self.wait = None
        self.error = None
        self.turn_ended = None
        self.handing_off_since = None
        self.effort = None
        self.document = None
        self.skills = []
        self.tool_count = 0


class Model:
    def __init__(self, context=None):
        context = context or {}
        self.root = context.get("area_root")
        self.relative = context.get("relative")        # function (path, cwd) -> relative path or None
        self.is_document = context.get("is_document")  # function (relative path) -> bool
        self.agents = context.get("agents", {})        # name -> frontmatter (model, effort, ...)
        self.generic = set(context.get("generic", []))
        self.thresholds = {**THRESHOLDS, **context.get("thresholds", {})}
        # From the profile: which script is the mailbox (notices), which are checks, which MCP is team memory
        scripts = context.get("scripts") or {}
        self.mailbox_script = scripts.get("mailbox")
        self.default_channel = scripts.get("default_channel", "avisos")
        self.team_checks = set(scripts.get("checks", []))
        self.memory_mcp = tuple(context.get("memory_mcp", ("mcp__engram__", "mcp__plugin_engram")))
        self.sessions = {}
        self.instances = {}
        self.launches = {}
        self.queue = {}
        self.activity = []
        self.approvals = {}
        self.tasks = {}
        self.writes = []
        self.drive_operations = []
        self.mailbox = []
        self.checks = []
        self.memory_queries = []
        self.general_launches = []

    # --- Input -------------------------------------------------------------------

    def apply(self, events):
        for moment, _, e in ordered(events):
            self._event(moment, e)
        return self

    def _session(self, sid, moment):
        s = self.sessions.get(sid)
        if s is None:
            s = self.sessions[sid] = {"id": sid, "agent": None, "start": moment, "end": None, "origin": "interactive",
                                      "model": None, "last_event": moment, "last_user_prompt": None, "cwd": None}
        s["last_event"] = max(s["last_event"], moment)
        return s

    def _instance(self, e, moment):
        sid = e.get("session_id") or "?"
        session = self._session(sid, moment)
        agent_id = e.get("agent_id")
        if agent_id:
            inst = self.instances.get(agent_id)
            if inst is None:
                inst = self.instances[agent_id] = Instance(agent_id, sid, e.get("agent_type") or "general-purpose", False, agent_id)
                inst.start = moment
                self._number(inst)
            elif e.get("agent_type") and inst.type != e["agent_type"]:
                inst.type = e["agent_type"]
        else:
            key = f"{sid}:main"
            inst = self.instances.get(key)
            type_ = e.get("agent_type") or session["agent"] or "main"
            if session["agent"] is None and e.get("agent_type"):
                session["agent"] = e["agent_type"]
            if inst is None:
                inst = self.instances[key] = Instance(key, sid, type_, True)
                inst.start = moment
            elif inst.type == "main" and type_ != "main":
                inst.type = type_
        # A finished instance that becomes active again (the main one after a Stop) starts a new streak.
        if inst.last_event is None or inst.turn_ended or \
                (moment - inst.last_event).total_seconds() > self.thresholds["idle_s"]:
            inst.streak_start = moment
        inst.last_event = moment
        if e.get("effort"):
            inst.effort = e["effort"]
        return session, inst

    def _number(self, inst):
        used = {i.number for i in self.instances.values()
                if i is not inst and i.session == inst.session and i.type == inst.type and not i.is_main and i.end is None}
        n = 1
        while n in used:
            n += 1
        inst.number = n

    def _event(self, moment, e):
        name = e.get("event")
        summary = e.get("summary") or {}
        session, inst = self._instance(e, moment)
        tool = e.get("tool_name")
        use = e.get("tool_use_id")
        resource = summary.get("path") or summary.get("pattern") or summary.get("domain") or summary.get("script") \
            or summary.get("file") or summary.get("description") or summary.get("command")
        if e.get("cwd"):
            session["cwd"] = e["cwd"]

        if name == "SessionStart":
            session["start"] = min(session["start"], moment)
            session["end"] = None
            if summary.get("origin"):
                session["origin"] = summary["origin"]
            if summary.get("model"):
                session["model"] = summary["model"]
            inst.end = None
        elif name == "SessionEnd":
            session["end"] = moment
            for i in self.instances.values():
                if i.session == session["id"] and i.end is None:
                    i.end = moment
                    i.open_calls.clear()
                    i.wait = None
        elif name == "UserPromptSubmit":
            inst.turn_ended = None
            inst.end = None
            if summary.get("origin", "user") == "user":
                session["last_user_prompt"] = moment
        elif name == "PreToolUse":
            self._pre(moment, e, session, inst, tool, use, resource, summary)
        elif name in ("PostToolUse", "PostToolUseFailure"):
            self._post(moment, e, session, inst, tool, use, resource, summary, name == "PostToolUseFailure")
        elif name == "PermissionRequest":
            inst.wait = {"kind": "permission", "tool": tool, "resource": resource, "since": moment}
            self.approvals[inst.key] = {"instance": inst.key, "tool": tool, "resource": resource,
                                        "since": moment, "mode": e.get("permission_mode")}
        elif name == "PermissionDenied":
            self._resolve_wait(inst)
        elif name == "Notification":
            kind = summary.get("notification_type")
            if kind in WAITING_NOTIFICATIONS and inst.wait is None:
                inst.wait = {"kind": "permission" if kind == "permission_prompt" else "answer",
                             "tool": inst.last_tool, "resource": inst.last_resource, "since": moment}
                self.approvals[inst.key] = {"instance": inst.key, "tool": inst.last_tool,
                                            "resource": inst.last_resource, "since": moment,
                                            "mode": e.get("permission_mode"), "notice": kind}
        elif name == "SubagentStart":
            self._subagent_starts(moment, session, inst)
        elif name == "SubagentStop":
            inst.end = moment
            inst.open_calls.clear()
            self._resolve_wait(inst)
        elif name == "Stop":
            inst.turn_ended = moment
            inst.open_calls.clear()
            self._resolve_wait(inst)
        elif name == "StopFailure":
            inst.error = {"since": moment, "kind": summary.get("error_type") or "turn"}
            inst.turn_ended = moment
        elif name in ("TaskCreated", "TaskCompleted"):
            key = (session["id"], summary.get("task_id") or summary.get("title"))
            t = self.tasks.setdefault(key, {"session": session["id"], "title": summary.get("title"),
                                            "created": None, "completed": None, "instance": inst.key})
            t["title"] = t["title"] or summary.get("title")
            t["created" if name == "TaskCreated" else "completed"] = moment

        if name not in ("PostToolUse",) and not (tool in INTERNAL):
            self.activity.append({"ts": moment, "instance": inst.key, "event": name,
                                  "tool": tool, "resource": resource, "origin": summary.get("origin")})

    def _pre(self, moment, e, session, inst, tool, use, resource, summary):
        if not tool:
            return
        if tool == "SubagentHandback":
            # The subagent hands back its result: "handing off" until its SubagentStop.
            if not inst.is_main and inst.end is None:
                inst.handing_off_since = inst.handing_off_since or moment
            return
        inst.last_tool = tool
        inst.last_resource = resource
        inst.turn_ended = None
        if tool not in INTERNAL:
            inst.tool_count += 1
        if use and use not in inst.closed_early:
            inst.open_calls[use] = {"tool": tool, "resource": resource, "since": moment}
        if tool in LAUNCHERS and use:
            self._launch(moment, session, inst, use, summary)
        if tool == "Skill" and summary.get("skill") and summary["skill"] not in inst.skills:
            inst.skills.append(summary["skill"])
        script = summary.get("script")
        if script and script == self.mailbox_script:
            self.mailbox.append({"ts": moment, "channel": summary.get("channel", self.default_channel), "instance": inst.key})
        elif script in self.team_checks:
            self.checks.append({"ts": moment, "script": script, "path": summary.get("path"), "instance": inst.key})
        if self.memory_mcp and tool.startswith(self.memory_mcp):
            self.memory_queries.append({"ts": moment, "tool": tool.split("__")[-1], "instance": inst.key})

    def _post(self, moment, e, session, inst, tool, use, resource, summary, failed):
        if use in inst.open_calls:
            del inst.open_calls[use]
        elif use:
            inst.closed_early.add(use)
        self._resolve_wait(inst)
        if failed:
            if not summary.get("interrupted"):
                inst.error = {"since": moment, "kind": "tool", "tool": tool}
            return
        if tool in LAUNCHERS and summary.get("launched_agent"):
            self._exact_link(use, summary)
        if tool in FILE_WRITERS and summary.get("path"):
            rel = self.relative(summary["path"], e.get("cwd")) if self.relative else None
            if rel:
                self.writes.append({"ts": moment, "instance": inst.key, "agent": inst.type, "path": rel})
                if self.is_document is None or self.is_document(rel):
                    inst.document = rel
        if tool and tool.startswith("mcp__") and summary.get("file"):
            self.drive_operations.append({"ts": moment, "instance": inst.key, "agent": inst.type,
                                          "tool": tool, "file": summary["file"]})
            inst.document = f"drive:{summary['file']}"

    def _resolve_wait(self, inst):
        inst.wait = None
        self.approvals.pop(inst.key, None)

    # --- Launches -----------------------------------------------------------------

    def _launch(self, moment, session, inst, use, summary):
        if use in self.launches:
            return
        type_ = summary.get("subagent_type") or "general-purpose"
        self.launches[use] = {"id": use, "session": session["id"], "parent": inst.key, "type": type_,
                              "description": summary.get("description"), "model": summary.get("model"),
                              "ts": moment, "agent": None, "exact": False, "resolved_model": None}
        self.queue.setdefault((session["id"], type_), []).append(use)
        if self._is_generic(type_):
            self.general_launches.append({"ts": moment, "type": type_, "description": summary.get("description")})

    def _subagent_starts(self, moment, session, inst):
        inst.start = min(inst.start or moment, moment)
        if inst.launch:
            return
        exact = next((l for l in self.launches.values() if l["agent"] == inst.agent_id), None)
        if exact:
            inst.launch = exact["id"]
            return
        queue = self.queue.get((session["id"], inst.type), [])
        while queue:
            use = queue.pop(0)
            launch = self.launches[use]
            if launch["agent"] is None:
                launch["agent"] = inst.agent_id
                inst.launch = use
                return

    def _exact_link(self, use, summary):
        launch = self.launches.get(use)
        agent = summary["launched_agent"]
        if launch is None:
            return
        launch["exact"] = True
        launch["resolved_model"] = summary.get("resolved_model") or launch["resolved_model"]
        queue = self.queue.get((launch["session"], launch["type"]), [])
        if use in queue:
            queue.remove(use)
        if launch["agent"] == agent:
            return
        holder = self.instances.get(launch["agent"]) if launch["agent"] else None
        inst = self.instances.get(agent)
        previous = inst.launch if inst else None
        launch["agent"] = agent
        if inst:
            inst.launch = use
        # The queue got it wrong: swap the labels.
        if holder is not None and holder.agent_id != agent:
            holder.launch = previous
            if previous:
                self.launches[previous]["agent"] = holder.agent_id
        elif previous and previous != use:
            self.launches[previous]["agent"] = None
            queue.insert(0, previous)

    def _is_generic(self, type_):
        return type_ in self.generic or (self.agents and type_ not in self.agents)

    # --- Output --------------------------------------------------------------------

    def active_subagents(self, inst, now=None):
        """The session's subagents that are still alive. With `now`, idle ones (no events for more than
        idle_s, no open tool and no wait) do not count: the main agent is not waiting for them."""
        alive = [i for i in self.instances.values()
                 if not i.is_main and i.session == inst.session and i.end is None]
        if now is None:
            return alive
        limit = self.thresholds["idle_s"]
        return [i for i in alive if i.open_calls or i.wait is not None or i.last_event is None
                or (now - i.last_event).total_seconds() <= limit]

    def state_of(self, inst, now):
        t = self.thresholds
        if inst.end is not None:
            return "done", inst.end
        if inst.wait is not None:
            return "waiting", inst.wait["since"]
        if inst.error and (now - inst.error["since"]).total_seconds() < t["error_s"] and \
                (inst.last_event is None or inst.last_event <= inst.error["since"] + dt.timedelta(seconds=1)):
            return "error", inst.error["since"]
        if inst.handing_off_since is not None:
            return "handing_off", inst.handing_off_since
        if inst.open_calls:
            return "working", inst.streak_start
        if inst.turn_ended is not None:
            # The main agent ended its turn but launched subagents that are still going: it is not done.
            if inst.is_main and self.active_subagents(inst, now):
                return "waiting_subagents", inst.turn_ended
            if (now - inst.turn_ended).total_seconds() > t["idle_s"]:
                return "idle", inst.turn_ended
            return "done", inst.turn_ended
        if inst.last_event and (now - inst.last_event).total_seconds() <= t["recent_activity_s"]:
            return "working", inst.streak_start
        if inst.last_event and (now - inst.last_event).total_seconds() > t["idle_s"]:
            return "idle", inst.last_event
        # No open tool and no recent events, but not idle yet: the model is thinking
        if inst.last_event:
            return "thinking", inst.last_event
        return "working", inst.streak_start

    def animation(self, inst, state):
        if state != "working":
            return {"done": "leave", "waiting": "wait", "error": "error", "idle": "idle",
                    "handing_off": "hand_off", "waiting_subagents": "wait_subagents",
                    "thinking": "think"}[state]
        open_call = next(iter(inst.open_calls.values()), None)
        tool = (open_call or {}).get("tool") or inst.last_tool or ""
        if tool in READING or tool.startswith("mcp__playwright") or tool.startswith("mcp__claude_ai_Google_Drive__read"):
            return "read"
        return "write"

    def model_of(self, inst):
        if inst.is_main:
            session = self.sessions.get(inst.session, {})
            return session.get("model") or self.agents.get(inst.type, {}).get("model"), "session" if session.get("model") else "frontmatter"
        launch = self.launches.get(inst.launch) if inst.launch else None
        if launch and launch.get("resolved_model"):
            return launch["resolved_model"], "launch"
        if launch and launch.get("model"):
            return launch["model"], "launch"
        return self.agents.get(inst.type, {}).get("model"), "frontmatter"

    def history_label(self, key):
        """For Activity and Flows: type and description, or type and short id. The #n is only for the floor."""
        inst = self.instances.get(key)
        if inst is None:
            return key
        if inst.is_main:
            return inst.type
        launch = self.launches.get(inst.launch) if inst.launch else None
        detail = (launch or {}).get("description") or (inst.agent_id or "")[:8]
        return f"{inst.type} · {detail}"

    def labels(self):
        return {key: self.history_label(key) for key in self.instances}

    def snapshot(self, now):
        t = self.thresholds
        instances = []
        for inst in self.instances.values():
            session = self.sessions.get(inst.session, {})
            closed = bool(session.get("end"))
            # A closed session never works again: it walks to the exit and leaves
            if closed and (now - session["end"]).total_seconds() > t["closed_retire_s"]:
                continue
            state, since = self.state_of(inst, now)
            # An open one that went silent (a forgotten terminal) leaves the floor; its next event brings it back.
            # Never while it waits for the owner: that wait is for them
            last = session.get("last_event")
            if (not closed and last and (now - last).total_seconds() > t["silent_retire_s"]
                    and state not in ("waiting", "error")):
                continue
            general = not inst.is_main and self._is_generic(inst.type)
            if general and inst.end and (now - inst.end).total_seconds() > t["general_retire_s"]:
                continue
            launch = self.launches.get(inst.launch) if inst.launch else None
            model, model_source = self.model_of(inst)
            open_call = next(iter(inst.open_calls.values()), None)
            instances.append({
                "key": inst.key,
                "session": inst.session,
                "type": inst.type,
                "main": inst.is_main,
                "general": general,
                "closed": closed,
                "number": inst.number,
                "label": (launch or {}).get("description"),
                "history_label": self.history_label(inst.key),
                "link": None if inst.is_main else ("exact" if launch and launch["exact"] else ("queue" if launch else "no_launch")),
                "state": state,
                "since": iso(since),
                "seconds_in_state": int((now - since).total_seconds()) if since else None,
                "animation": self.animation(inst, state),
                "model": model,
                "model_source": model_source,
                "effort": inst.effort,
                "tool": (open_call or {}).get("tool") or inst.last_tool,
                "resource": (open_call or {}).get("resource") or inst.last_resource,
                "document": inst.document,
                "wait": {**inst.wait, "since": iso(inst.wait["since"])} if inst.wait else None,
                "skills": inst.skills,
                "tools_used": inst.tool_count,
                "start": iso(inst.start),
                "end": iso(inst.end),
                "origin": session.get("origin"),
            })
        instances.sort(key=lambda i: (not i["main"], i["start"] or ""))
        sessions = [{**s, "start": iso(s["start"]), "end": iso(s["end"]), "last_event": iso(s["last_event"]),
                     "last_user_prompt": iso(s["last_user_prompt"])}
                    for s in sorted(self.sessions.values(), key=lambda s: s["start"])]
        return {
            "sessions": sessions,
            "instances": instances,
            "approvals": [{**a, "since": iso(a["since"])} for a in self.approvals.values()],
            "session_tasks": [{**t, "created": iso(t["created"]), "completed": iso(t["completed"])} for t in self.tasks.values()],
            "activity": [{**a, "ts": iso(a["ts"]), "who": self.history_label(a["instance"])}
                         for a in self.activity[-500:]],
            "objects": {
                "mailbox": [{**b, "ts": iso(b["ts"])} for b in self.mailbox[-20:]],
                "checks": [{**c, "ts": iso(c["ts"])} for c in self.checks[-20:]],
                "memory": [{**m, "ts": iso(m["ts"])} for m in self.memory_queries[-20:]],
            },
            "general_launches": [{**l, "ts": iso(l["ts"])} for l in self.general_launches],
        }


def zone_of(name, rules, generic, generic_zone="floating", unzoned_zone="reception", general=False):
    """Room of an agent: the first matching rule wins, also for a generic subagent (`general`, so that Explore
    can go to exploration); without a rule a generic one goes to the generic zone and anything else is unzoned."""
    for rule in rules:
        if fnmatch.fnmatchcase(name, rule["agent"]):
            return rule["zone"], False
    if general or name in generic:
        return generic_zone, False
    return unzoned_zone, True


def next_scheduled_run(now, weekday=2, hour=10):
    """Next scheduled run (weekday: Monday=0). The values come from `scheduled_run` in the profile."""
    candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0) + dt.timedelta(days=(weekday - now.weekday()) % 7)
    if candidate <= now:
        candidate += dt.timedelta(days=7)
    return candidate


def is_valid_name(name):
    return bool(re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", name or ""))
