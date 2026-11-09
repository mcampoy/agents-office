"""Modelo de estados de la oficina a partir de los eventos capturados.

Es una función pura: `Modelo(contexto).aplicar(eventos)` y después `foto(ahora)`.
Los eventos se ordenan por la marca de tiempo del hook (`ts`) y, a igual marca, por orden de llegada.
Los hooks async pueden llegar desordenados, así que:
- Pre y Post se emparejan por `tool_use_id`; un Post que llega antes que su Pre cierra la llamada igual.
- Un evento de un subagente que llega antes que su SubagentStart crea la instancia, y el SubagentStart la completa.
- El vínculo lanzamiento -> subagente usa la cola por orden de llegada (por sesión y tipo) hasta que llega
  el vínculo exacto (`agente_lanzado` en el PostToolUse de Agent), que lo corrige si hace falta.
El servidor recalcula todo el día con cada lote nuevo: el orden final siempre es el de `ts`.
"""
import datetime as dt
import fnmatch
import re

ESCRITURA = {"Write", "Edit", "MultiEdit", "NotebookEdit", "Bash", "PowerShell"}
LECTURA = {"Read", "Grep", "Glob", "WebFetch", "WebSearch", "ToolSearch"}
LANZADORES = {"Agent", "Task"}
INTERNAS = {"SubagentHandback", "ToolSearch"}
ARCHIVOS_ESCRITOS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
ESPERAS_NOTIFICACION = {"permission_prompt", "agent_needs_input"}

UMBRALES = {
    "actividad_reciente_s": 90,   # sin herramienta abierta pero con eventos recientes: sigue trabajando
    "ocioso_s": 300,              # N minutos sin eventos con la sesión abierta
    "error_s": 120,               # cuánto dura la burbuja de error
    "retiro_general_s": 120,      # un agente general se retira del piso tras terminar
    "sesion_inactiva_s": 6 * 3600,
}


def leer_ts(valor):
    try:
        return dt.datetime.fromisoformat(valor)
    except (TypeError, ValueError):
        return None


def iso(momento):
    return momento.isoformat(timespec="seconds") if momento else None


def ordenar(eventos):
    """Por marca del hook; los que no tienen marca válida quedan afuera."""
    con_ts = []
    for i, e in enumerate(eventos):
        momento = leer_ts(e.get("ts"))
        if momento is not None:
            con_ts.append((momento, i, e))
    con_ts.sort(key=lambda t: (t[0], t[1]))
    return con_ts


class Instancia:
    def __init__(self, clave, sesion, tipo, es_principal, agent_id=None):
        self.clave = clave
        self.sesion = sesion
        self.tipo = tipo
        self.es_principal = es_principal
        self.agent_id = agent_id
        self.numero = 1
        self.lanzamiento = None
        self.inicio = None
        self.fin = None
        self.ultimo_evento = None
        self.inicio_racha = None
        self.abiertas = {}
        self.cerradas_antes = set()
        self.ultima_herramienta = None
        self.ultimo_recurso = None
        self.espera = None
        self.error = None
        self.turno_terminado = None
        self.entregando_desde = None
        self.effort = None
        self.documento = None
        self.skills = []
        self.herramientas = 0


class Modelo:
    def __init__(self, contexto=None):
        contexto = contexto or {}
        self.raiz = contexto.get("raiz_area")
        self.relativa = contexto.get("relativa")          # función (ruta, cwd) -> ruta relativa o None
        self.es_documento = contexto.get("es_documento")  # función (ruta relativa) -> bool
        self.agentes = contexto.get("agentes", {})        # nombre -> frontmatter (model, effort, ...)
        self.generales = set(contexto.get("generales", []))
        self.umbrales = {**UMBRALES, **contexto.get("umbrales", {})}
        # Del perfil: qué script es el buzón (avisos) y cuáles son controles; qué MCP es la memoria del equipo
        scripts = contexto.get("scripts") or {}
        self.script_buzon = scripts.get("buzon")
        self.canal_por_defecto = scripts.get("canal_por_defecto", "avisos")
        self.controles_equipo = set(scripts.get("controles", []))
        self.memoria_mcp = tuple(contexto.get("memoria_mcp", ("mcp__engram__", "mcp__plugin_engram")))
        self.sesiones = {}
        self.instancias = {}
        self.lanzamientos = {}
        self.cola = {}
        self.actividad = []
        self.aprobaciones = {}
        self.tareas = {}
        self.escrituras = []
        self.operaciones_drive = []
        self.buzon = []
        self.controles = []
        self.consultas_memoria = []
        self.lanzamientos_generales = []

    # --- Entrada -------------------------------------------------------------------

    def aplicar(self, eventos):
        for momento, _, e in ordenar(eventos):
            self._evento(momento, e)
        return self

    def _sesion(self, sid, momento):
        s = self.sesiones.get(sid)
        if s is None:
            s = self.sesiones[sid] = {"id": sid, "agente": None, "inicio": momento, "fin": None, "origen": "interactiva",
                                      "modelo": None, "ultimo_evento": momento, "ultimo_prompt_usuario": None,
                                      "cwd": None}
        s["ultimo_evento"] = max(s["ultimo_evento"], momento)
        return s

    def _instancia(self, e, momento):
        sid = e.get("session_id") or "?"
        sesion = self._sesion(sid, momento)
        agent_id = e.get("agent_id")
        if agent_id:
            inst = self.instancias.get(agent_id)
            if inst is None:
                inst = self.instancias[agent_id] = Instancia(agent_id, sid, e.get("agent_type") or "general-purpose", False, agent_id)
                inst.inicio = momento
                self._numerar(inst)
            elif e.get("agent_type") and inst.tipo != e["agent_type"]:
                inst.tipo = e["agent_type"]
        else:
            clave = f"{sid}:principal"
            inst = self.instancias.get(clave)
            tipo = e.get("agent_type") or sesion["agente"] or "principal"
            if sesion["agente"] is None and e.get("agent_type"):
                sesion["agente"] = e["agent_type"]
            if inst is None:
                inst = self.instancias[clave] = Instancia(clave, sid, tipo, True)
                inst.inicio = momento
            elif inst.tipo == "principal" and tipo != "principal":
                inst.tipo = tipo
        # Una instancia terminada que vuelve a tener actividad (la principal tras un Stop) arranca racha nueva.
        if inst.ultimo_evento is None or inst.turno_terminado or \
                (momento - inst.ultimo_evento).total_seconds() > self.umbrales["ocioso_s"]:
            inst.inicio_racha = momento
        inst.ultimo_evento = momento
        if e.get("effort"):
            inst.effort = e["effort"]
        return sesion, inst

    def _numerar(self, inst):
        usados = {i.numero for i in self.instancias.values()
                  if i is not inst and i.sesion == inst.sesion and i.tipo == inst.tipo and not i.es_principal and i.fin is None}
        n = 1
        while n in usados:
            n += 1
        inst.numero = n

    def _evento(self, momento, e):
        nombre = e.get("evento")
        resumen = e.get("resumen") or {}
        sesion, inst = self._instancia(e, momento)
        herramienta = e.get("tool_name")
        uso = e.get("tool_use_id")
        recurso = resumen.get("ruta") or resumen.get("patron") or resumen.get("dominio") or resumen.get("script") \
            or resumen.get("archivo") or resumen.get("description") or resumen.get("comando")
        if e.get("cwd"):
            sesion["cwd"] = e["cwd"]

        if nombre == "SessionStart":
            sesion["inicio"] = min(sesion["inicio"], momento)
            sesion["fin"] = None
            if resumen.get("origen"):
                sesion["origen"] = resumen["origen"]
            if resumen.get("model"):
                sesion["modelo"] = resumen["model"]
            inst.fin = None
        elif nombre == "SessionEnd":
            sesion["fin"] = momento
            for i in self.instancias.values():
                if i.sesion == sesion["id"] and i.fin is None:
                    i.fin = momento
                    i.abiertas.clear()
                    i.espera = None
        elif nombre == "UserPromptSubmit":
            inst.turno_terminado = None
            inst.fin = None
            if resumen.get("origen", "usuario") == "usuario":
                sesion["ultimo_prompt_usuario"] = momento
        elif nombre == "PreToolUse":
            self._pre(momento, e, sesion, inst, herramienta, uso, recurso, resumen)
        elif nombre in ("PostToolUse", "PostToolUseFailure"):
            self._post(momento, e, sesion, inst, herramienta, uso, recurso, resumen, nombre == "PostToolUseFailure")
        elif nombre == "PermissionRequest":
            inst.espera = {"tipo": "permiso", "herramienta": herramienta, "recurso": recurso, "desde": momento}
            self.aprobaciones[inst.clave] = {"instancia": inst.clave, "herramienta": herramienta, "recurso": recurso,
                                             "desde": momento, "modo": e.get("permission_mode")}
        elif nombre == "PermissionDenied":
            self._resolver_espera(inst, momento, "denegado")
        elif nombre == "Notification":
            tipo = resumen.get("tipo")
            if tipo in ESPERAS_NOTIFICACION and inst.espera is None:
                inst.espera = {"tipo": "permiso" if tipo == "permission_prompt" else "respuesta",
                               "herramienta": inst.ultima_herramienta, "recurso": inst.ultimo_recurso, "desde": momento}
                self.aprobaciones[inst.clave] = {"instancia": inst.clave, "herramienta": inst.ultima_herramienta,
                                                 "recurso": inst.ultimo_recurso, "desde": momento,
                                                 "modo": e.get("permission_mode"), "aviso": tipo}
        elif nombre == "SubagentStart":
            self._subagente_inicia(momento, sesion, inst)
        elif nombre == "SubagentStop":
            inst.fin = momento
            inst.abiertas.clear()
            self._resolver_espera(inst, momento, None)
        elif nombre == "Stop":
            inst.turno_terminado = momento
            inst.abiertas.clear()
            self._resolver_espera(inst, momento, None)
        elif nombre == "StopFailure":
            inst.error = {"desde": momento, "tipo": resumen.get("tipo_error") or "turno"}
            inst.turno_terminado = momento
        elif nombre in ("TaskCreated", "TaskCompleted"):
            clave = (sesion["id"], resumen.get("task_id") or resumen.get("titulo"))
            t = self.tareas.setdefault(clave, {"sesion": sesion["id"], "titulo": resumen.get("titulo"),
                                                "creada": None, "completada": None, "instancia": inst.clave})
            t["titulo"] = t["titulo"] or resumen.get("titulo")
            t["creada" if nombre == "TaskCreated" else "completada"] = momento

        if nombre not in ("PostToolUse",) and not (herramienta in INTERNAS):
            self.actividad.append({"ts": momento, "instancia": inst.clave, "evento": nombre,
                                   "herramienta": herramienta, "recurso": recurso,
                                   "origen": resumen.get("origen")})

    def _pre(self, momento, e, sesion, inst, herramienta, uso, recurso, resumen):
        if not herramienta:
            return
        if herramienta == "SubagentHandback":
            # El subagente devuelve su resultado: "entregando" hasta su SubagentStop.
            if not inst.es_principal and inst.fin is None:
                inst.entregando_desde = inst.entregando_desde or momento
            return
        inst.ultima_herramienta = herramienta
        inst.ultimo_recurso = recurso
        inst.turno_terminado = None
        if herramienta not in INTERNAS:
            inst.herramientas += 1
        if uso and uso not in inst.cerradas_antes:
            inst.abiertas[uso] = {"herramienta": herramienta, "recurso": recurso, "desde": momento}
        if herramienta in LANZADORES and uso:
            self._lanzamiento(momento, sesion, inst, uso, resumen)
        if herramienta == "Skill" and resumen.get("skill") and resumen["skill"] not in inst.skills:
            inst.skills.append(resumen["skill"])
        script = resumen.get("script")
        if script and script == self.script_buzon:
            self.buzon.append({"ts": momento, "canal": resumen.get("canal", self.canal_por_defecto), "instancia": inst.clave})
        elif script in self.controles_equipo:
            self.controles.append({"ts": momento, "script": script, "ruta": resumen.get("ruta"), "instancia": inst.clave})
        if self.memoria_mcp and herramienta.startswith(self.memoria_mcp):
            self.consultas_memoria.append({"ts": momento, "herramienta": herramienta.split("__")[-1], "instancia": inst.clave})

    def _post(self, momento, e, sesion, inst, herramienta, uso, recurso, resumen, es_falla):
        if uso in inst.abiertas:
            del inst.abiertas[uso]
        elif uso:
            inst.cerradas_antes.add(uso)
        self._resolver_espera(inst, momento, "resuelta")
        if es_falla:
            if not resumen.get("interrumpido"):
                inst.error = {"desde": momento, "tipo": "herramienta", "herramienta": herramienta}
            return
        if herramienta in LANZADORES and resumen.get("agente_lanzado"):
            self._vinculo_exacto(uso, resumen)
        if herramienta in ARCHIVOS_ESCRITOS and resumen.get("ruta"):
            rel = self.relativa(resumen["ruta"], e.get("cwd")) if self.relativa else None
            if rel:
                self.escrituras.append({"ts": momento, "instancia": inst.clave, "agente": inst.tipo, "ruta": rel})
                if self.es_documento is None or self.es_documento(rel):
                    inst.documento = rel
        if herramienta and herramienta.startswith("mcp__") and resumen.get("archivo"):
            self.operaciones_drive.append({"ts": momento, "instancia": inst.clave, "agente": inst.tipo,
                                           "herramienta": herramienta, "archivo": resumen["archivo"]})
            inst.documento = f"drive:{resumen['archivo']}"

    def _resolver_espera(self, inst, momento, como):
        if inst.espera is not None:
            inst.espera = None
        self.aprobaciones.pop(inst.clave, None)

    # --- Lanzamientos -----------------------------------------------------------

    def _lanzamiento(self, momento, sesion, inst, uso, resumen):
        if uso in self.lanzamientos:
            return
        tipo = resumen.get("subagent_type") or "general-purpose"
        self.lanzamientos[uso] = {"id": uso, "sesion": sesion["id"], "padre": inst.clave, "tipo": tipo,
                                  "description": resumen.get("description"), "model": resumen.get("model"),
                                  "ts": momento, "agente": None, "exacto": False, "modelo_resuelto": None}
        self.cola.setdefault((sesion["id"], tipo), []).append(uso)
        if self._es_general(tipo):
            self.lanzamientos_generales.append({"ts": momento, "tipo": tipo, "description": resumen.get("description")})

    def _subagente_inicia(self, momento, sesion, inst):
        inst.inicio = min(inst.inicio or momento, momento)
        if inst.lanzamiento:
            return
        exacto = next((l for l in self.lanzamientos.values() if l["agente"] == inst.agent_id), None)
        if exacto:
            inst.lanzamiento = exacto["id"]
            return
        cola = self.cola.get((sesion["id"], inst.tipo), [])
        while cola:
            uso = cola.pop(0)
            lanz = self.lanzamientos[uso]
            if lanz["agente"] is None:
                lanz["agente"] = inst.agent_id
                inst.lanzamiento = uso
                return

    def _vinculo_exacto(self, uso, resumen):
        lanz = self.lanzamientos.get(uso)
        agente = resumen["agente_lanzado"]
        if lanz is None:
            return
        lanz["exacto"] = True
        lanz["modelo_resuelto"] = resumen.get("modelo_resuelto") or lanz["modelo_resuelto"]
        cola = self.cola.get((lanz["sesion"], lanz["tipo"]), [])
        if uso in cola:
            cola.remove(uso)
        if lanz["agente"] == agente:
            return
        poseedor = self.instancias.get(lanz["agente"]) if lanz["agente"] else None
        inst = self.instancias.get(agente)
        previo = inst.lanzamiento if inst else None
        lanz["agente"] = agente
        if inst:
            inst.lanzamiento = uso
        # La cola se había equivocado: se intercambian las etiquetas.
        if poseedor is not None and poseedor.agent_id != agente:
            poseedor.lanzamiento = previo
            if previo:
                self.lanzamientos[previo]["agente"] = poseedor.agent_id
        elif previo and previo != uso:
            self.lanzamientos[previo]["agente"] = None
            cola.insert(0, previo)

    def _es_general(self, tipo):
        return tipo in self.generales or (self.agentes and tipo not in self.agentes)

    # --- Salida -----------------------------------------------------------------

    def subagentes_activos(self, inst):
        return [i for i in self.instancias.values()
                if not i.es_principal and i.sesion == inst.sesion and i.fin is None]

    def estado_de(self, inst, ahora):
        u = self.umbrales
        if inst.fin is not None:
            return "terminado", inst.fin
        if inst.espera is not None:
            return "esperando", inst.espera["desde"]
        if inst.error and (ahora - inst.error["desde"]).total_seconds() < u["error_s"] and \
                (inst.ultimo_evento is None or inst.ultimo_evento <= inst.error["desde"] + dt.timedelta(seconds=1)):
            return "error", inst.error["desde"]
        if inst.entregando_desde is not None:
            return "entregando", inst.entregando_desde
        if inst.abiertas:
            return "trabajando", inst.inicio_racha
        if inst.turno_terminado is not None:
            # La principal terminó su turno pero lanzó subagentes que siguen: no está terminada.
            if inst.es_principal and self.subagentes_activos(inst):
                return "esperando_subagentes", inst.turno_terminado
            if (ahora - inst.turno_terminado).total_seconds() > u["ocioso_s"]:
                return "ocioso", inst.turno_terminado
            return "terminado", inst.turno_terminado
        if inst.ultimo_evento and (ahora - inst.ultimo_evento).total_seconds() <= u["actividad_reciente_s"]:
            return "trabajando", inst.inicio_racha
        if inst.ultimo_evento and (ahora - inst.ultimo_evento).total_seconds() > u["ocioso_s"]:
            return "ocioso", inst.ultimo_evento
        return "trabajando", inst.inicio_racha

    def animacion(self, inst, estado):
        if estado != "trabajando":
            return {"terminado": "se_retira", "esperando": "espera", "error": "error", "ocioso": "idle",
                    "entregando": "entrega", "esperando_subagentes": "espera_subagentes"}[estado]
        abierta = next(iter(inst.abiertas.values()), None)
        h = (abierta or {}).get("herramienta") or inst.ultima_herramienta or ""
        if h in LECTURA or h.startswith("mcp__playwright") or h.startswith("mcp__claude_ai_Google_Drive__read"):
            return "lee"
        return "escribe"

    def modelo_de(self, inst):
        if inst.es_principal:
            sesion = self.sesiones.get(inst.sesion, {})
            return sesion.get("modelo") or self.agentes.get(inst.tipo, {}).get("model"), "sesion" if sesion.get("modelo") else "frontmatter"
        lanz = self.lanzamientos.get(inst.lanzamiento) if inst.lanzamiento else None
        if lanz and lanz.get("modelo_resuelto"):
            return lanz["modelo_resuelto"], "lanzamiento"
        if lanz and lanz.get("model"):
            return lanz["model"], "lanzamiento"
        return self.agentes.get(inst.tipo, {}).get("model"), "frontmatter"

    def etiqueta_historial(self, clave):
        """Para Actividad y Flujos: tipo y description, o tipo e id corto. El #n es solo del piso."""
        inst = self.instancias.get(clave)
        if inst is None:
            return clave
        if inst.es_principal:
            return inst.tipo
        lanz = self.lanzamientos.get(inst.lanzamiento) if inst.lanzamiento else None
        detalle = (lanz or {}).get("description") or (inst.agent_id or "")[:8]
        return f"{inst.tipo} · {detalle}"

    def etiquetas(self):
        return {clave: self.etiqueta_historial(clave) for clave in self.instancias}

    def foto(self, ahora):
        u = self.umbrales
        instancias = []
        for inst in self.instancias.values():
            sesion = self.sesiones.get(inst.sesion, {})
            if sesion.get("fin") and (ahora - sesion["fin"]).total_seconds() > u["sesion_inactiva_s"]:
                continue
            estado, desde = self.estado_de(inst, ahora)
            general = not inst.es_principal and self._es_general(inst.tipo)
            if general and inst.fin and (ahora - inst.fin).total_seconds() > u["retiro_general_s"]:
                continue
            lanz = self.lanzamientos.get(inst.lanzamiento) if inst.lanzamiento else None
            modelo, fuente_modelo = self.modelo_de(inst)
            abierta = next(iter(inst.abiertas.values()), None)
            instancias.append({
                "clave": inst.clave,
                "sesion": inst.sesion,
                "tipo": inst.tipo,
                "principal": inst.es_principal,
                "general": general,
                "numero": inst.numero,
                "etiqueta": (lanz or {}).get("description"),
                "etiqueta_historial": self.etiqueta_historial(inst.clave),
                "vinculo": None if inst.es_principal else ("exacto" if lanz and lanz["exacto"] else ("cola" if lanz else "sin_lanzamiento")),
                "estado": estado,
                "desde": iso(desde),
                "segundos_en_estado": int((ahora - desde).total_seconds()) if desde else None,
                "animacion": self.animacion(inst, estado),
                "modelo": modelo,
                "fuente_modelo": fuente_modelo,
                "effort": inst.effort,
                "herramienta": (abierta or {}).get("herramienta") or inst.ultima_herramienta,
                "recurso": (abierta or {}).get("recurso") or inst.ultimo_recurso,
                "documento": inst.documento,
                "espera": {**inst.espera, "desde": iso(inst.espera["desde"])} if inst.espera else None,
                "skills": inst.skills,
                "herramientas_usadas": inst.herramientas,
                "inicio": iso(inst.inicio),
                "fin": iso(inst.fin),
                "origen": sesion.get("origen"),
            })
        instancias.sort(key=lambda i: (not i["principal"], i["inicio"] or ""))
        sesiones = [{**s, "inicio": iso(s["inicio"]), "fin": iso(s["fin"]), "ultimo_evento": iso(s["ultimo_evento"]),
                     "ultimo_prompt_usuario": iso(s["ultimo_prompt_usuario"])}
                    for s in sorted(self.sesiones.values(), key=lambda s: s["inicio"])]
        return {
            "sesiones": sesiones,
            "instancias": instancias,
            "aprobaciones": [{**a, "desde": iso(a["desde"])} for a in self.aprobaciones.values()],
            "tareas_sesion": [{**t, "creada": iso(t["creada"]), "completada": iso(t["completada"])} for t in self.tareas.values()],
            "actividad": [{**a, "ts": iso(a["ts"]), "quien": self.etiqueta_historial(a["instancia"])}
                          for a in self.actividad[-500:]],
            "objetos": {
                "buzon": [{**b, "ts": iso(b["ts"])} for b in self.buzon[-20:]],
                "controles": [{**c, "ts": iso(c["ts"])} for c in self.controles[-20:]],
                "memoria": [{**m, "ts": iso(m["ts"])} for m in self.consultas_memoria[-20:]],
            },
            "lanzamientos_generales": [{**l, "ts": iso(l["ts"])} for l in self.lanzamientos_generales],
        }


def zona_de(nombre, reglas, generales, zona_generales="flotante", zona_sin_regla="recepcion"):
    for regla in reglas:
        if fnmatch.fnmatchcase(nombre, regla["agente"]):
            return regla["zona"], False
    if nombre in generales:
        return zona_generales, False
    return zona_sin_regla, True


def proxima_corrida(ahora, dia_semana=2, hora=10):
    """Próxima corrida programada (dia_semana: lunes=0). Los valores salen de `corrida` en el perfil."""
    candidato = ahora.replace(hour=hora, minute=0, second=0, microsecond=0) + dt.timedelta(days=(dia_semana - ahora.weekday()) % 7)
    if candidato <= ahora:
        candidato += dt.timedelta(days=7)
    return candidato


def es_nombre_valido(nombre):
    return bool(re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", nombre or ""))
