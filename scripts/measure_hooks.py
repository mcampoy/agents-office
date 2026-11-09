"""Measures the cost of a session's hooks from its debug log.

Usage:
  claude ... --debug-file C:\\path\\debug.log
  py -3 scripts/measure_hooks.py C:\\path\\debug.log

Counts every hook Claude Code records in the log: the ones from settings, the ones from each
plugin (including the office) and the mod modules. Separates the ones that block the agent
(synchronous) from the ones that run in the background (async).
"""
import collections
import re
import sys

FINISHED = re.compile(r"Hooks: (\w+)(?::\S*)? \[(.*?)\](?: \(plugin ([^)]+)\))? finished with status (\d+) \((\d+)ms\)")
ASYNC = re.compile(r"Registering async hook (async_hook_\d+) \((\w+)")
MODULE = re.compile(r"hooks module (\S+) (\S+) settled in ([\d.]+)ms")


def source(command, plugin):
    if plugin:
        return plugin.split("@")[0]
    name = re.split(r"[\\/]", command.replace('"', "").replace("'", ""))[-1]
    return "settings:" + name[:40]


def main(path):
    lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    synchronous = collections.defaultdict(list)
    modules = collections.defaultdict(list)
    async_by_event = collections.Counter()
    for line in lines:
        if (m := FINISHED.search(line)):
            event, command, plugin, _, ms = m.groups()
            synchronous[(event, source(command, plugin))].append(int(ms))
        elif (m := ASYNC.search(line)):
            async_by_event[m.group(2)] += 1
        elif (m := MODULE.search(line)):
            modules[(m.group(2), m.group(1).split("@")[0])].append(float(m.group(3)))

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("Hooks con duración medida (frenan al agente salvo que sean async):")
    for (event, origin), v in sorted(synchronous.items()):
        v.sort()
        print(f"  {event:20} {origin:45} n={len(v):3}  mediana={v[len(v) // 2]:6} ms  max={v[-1]:6} ms")
    print("Hooks async lanzados (no frenan; costo de CPU):")
    for event, n in sorted(async_by_event.items()):
        print(f"  {event:20} {n}")
    print("Módulos de mods (en proceso):")
    for (event, origin), v in sorted(modules.items()):
        v.sort()
        print(f"  {event:20} {origin:45} n={len(v):3}  mediana={v[len(v) // 2]:6.1f} ms  max={v[-1]:6.1f} ms")


if __name__ == "__main__":
    main(sys.argv[1])
