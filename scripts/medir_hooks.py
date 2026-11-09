"""Mide el costo de los hooks de una sesión a partir de su log de depuración.

Uso:
  claude ... --debug-file C:\\ruta\\debug.log
  py -3 scripts/medir_hooks.py C:\\ruta\\debug.log

Cuenta todos los hooks que Claude Code registra en el log: los de settings, los de cada
plugin (incluida la oficina) y los módulos de mods. Separa los que frenan al agente
(sincrónicos) de los que corren en segundo plano (async).
"""
import collections
import re
import sys

TERMINA = re.compile(r"Hooks: (\w+)(?::\S*)? \[(.*?)\](?: \(plugin ([^)]+)\))? finished with status (\d+) \((\d+)ms\)")
ASYNC = re.compile(r"Registering async hook (async_hook_\d+) \((\w+)")
ASYNC_CMD = re.compile(r"Hooks: (\w+)(?::\S*)? \[(.*?)\] \(plugin ([^)]+)\)")
MODULO = re.compile(r"hooks module (\S+) (\S+) settled in ([\d.]+)ms")


def origen(comando, plugin):
    if plugin:
        return plugin.split("@")[0]
    nombre = re.split(r"[\\/]", comando.replace('"', "").replace("'", ""))[-1]
    return "settings:" + nombre[:40]


def main(ruta):
    lineas = open(ruta, encoding="utf-8", errors="replace").read().splitlines()
    sincronicos = collections.defaultdict(list)
    modulos = collections.defaultdict(list)
    async_por_evento = collections.Counter()
    for linea in lineas:
        if (m := TERMINA.search(linea)):
            evento, comando, plugin, _, ms = m.groups()
            sincronicos[(evento, origen(comando, plugin))].append(int(ms))
        elif (m := ASYNC.search(linea)):
            async_por_evento[m.group(2)] += 1
        elif (m := MODULO.search(linea)):
            modulos[(m.group(2), m.group(1).split("@")[0])].append(float(m.group(3)))

    print("Hooks con duración medida (frenan al agente salvo que sean async):")
    for (evento, fuente), v in sorted(sincronicos.items()):
        v.sort()
        print(f"  {evento:20} {fuente:45} n={len(v):3}  mediana={v[len(v) // 2]:6} ms  max={v[-1]:6} ms")
    print("Hooks async lanzados (no frenan; costo de CPU):")
    for evento, n in sorted(async_por_evento.items()):
        print(f"  {evento:20} {n}")
    print("Módulos de mods (en proceso):")
    for (evento, fuente), v in sorted(modulos.items()):
        v.sort()
        print(f"  {evento:20} {fuente:45} n={len(v):3}  mediana={v[len(v) // 2]:6.1f} ms  max={v[-1]:6.1f} ms")


if __name__ == "__main__":
    main(sys.argv[1])
