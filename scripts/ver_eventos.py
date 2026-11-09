"""Muestra los eventos capturados de un día, uno por línea.

Uso: py -3 scripts/ver_eventos.py [AAAA-MM-DD]
"""
import datetime as dt
import json
import os
import sys
from pathlib import Path

DATOS = Path(os.environ.get("AGENTS_OFFICE_DATOS") or Path.home() / ".agents-office")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dia = sys.argv[1] if len(sys.argv) > 1 else dt.date.today().isoformat()
    ruta = DATOS / "eventos" / f"{dia}.jsonl"
    if not ruta.exists():
        print(f"No hay eventos en {ruta}")
        return 1
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        e = json.loads(linea)
        quien = e.get("agent_type") or "?"
        if e.get("agent_id"):
            quien += f"#{e['agent_id'][:8]}"
        print(f"{e['ts'][11:19]}  {e['evento']:18} {quien:32} {e.get('tool_name', ''):24} "
              f"{json.dumps(e.get('resumen', {}), ensure_ascii=False)}")
    errores = DATOS / "errores.log"
    if errores.exists():
        print(f"\nerrores.log:\n{errores.read_text(encoding='utf-8')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
