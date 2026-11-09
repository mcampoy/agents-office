"""Flujos por documento: tipo y etapa (de flujos.json del perfil), cruces del verificador y esperas del responsable.

Los documentos se descubren por las escrituras de los agentes. Del archivo se lee solo la tabla de
encabezado y, en los informes de verificación, los títulos de ronda.

Ronda de cada cruce: el informe de verificación es uno por ciclo y cada ronda es una sección. Si
hoy lo escribieron k ejecuciones del verificador y el archivo termina en la ronda R, la i-ésima
ejecución (en orden) fue la ronda R - k + i. Si el número de títulos no alcanza, se usa la columna
`Rondas` del encabezado y, si tampoco está, la ronda 1.
"""
import re

from .util import coincide



class Flujos:
    def __init__(self, config, area):
        self.config = config
        self.area = area
        self.maximo = config.get("rondas_maximas", 2)
        # Convenciones del equipo (flujos.json del perfil):
        # - tipo_pendiente_externo: documentos que hace alguien fuera del equipo (se marcan como pendientes)
        # - tipos_con_revision_inicial: el responsable los revisa antes de que pasen por el verificador
        # - tipos_con_revision_final: después de verificados esperan una "revisión final" y no la común
        # - estados_cerrados: estados del encabezado que dan el documento por terminado
        self.tipo_externo = config.get("tipo_pendiente_externo")
        self.revision_inicial = set(config.get("tipos_con_revision_inicial", []))
        self.revision_final = set(config.get("tipos_con_revision_final", []))
        self.estados_cerrados = set(config.get("estados_cerrados", []))
        esperas = config.get("esperas_del_responsable", {})
        self.espera_revision = esperas.get("revision", "revisión del responsable")
        self.espera_final = esperas.get("final", "revisión final")

    def clasificar(self, rel):
        if not rel or any(coincide(rel, p) for p in self.config.get("ignorar", [])):
            return None
        for regla in self.config.get("reglas", []):
            if coincide(rel, regla["patron"]):
                return {"tipo": regla["tipo"], "etapa": regla["etapa"]}
        return None

    def es_documento(self, rel):
        return self.clasificar(rel) is not None

    def espejo(self, informe, conocidos):
        """Documentos que verifica un informe: los que nombra su encabezado o los de la regla de espejo."""
        nombrados = self.area.documentos_nombrados(informe) if self.area else []
        encontrados = []
        for nombre in nombrados:
            base = nombre.rsplit("/", 1)[-1].lower()
            encontrados += [c for c in conocidos if c.lower().endswith("/" + base) and c != informe]
        if encontrados:
            return sorted(set(encontrados)), self._tipo_por_espejo(informe)
        for regla in self.config.get("espejo", []):
            m = re.match(regla["informe"], informe)
            if not m:
                continue
            patron = regla["documento"].format(**{k: v for k, v in m.groupdict().items() if v is not None})
            docs = [c for c in conocidos if coincide(c, patron) and c != informe]
            if not docs and "*" not in patron:
                docs = [patron]
            return sorted(set(docs)), regla["tipo"]
        return [], None

    def _tipo_por_espejo(self, informe):
        for regla in self.config.get("espejo", []):
            if re.match(regla["informe"], informe):
                return regla["tipo"]
        return None

    def construir(self, modelo_foto, escrituras, operaciones_drive, pendientes=None, conocidos=None, etiquetas=None):
        """Documentos en curso del día a partir de las escrituras (ya ordenadas por ts)."""
        instancias = {i["clave"]: i for i in modelo_foto["instancias"]}
        etiquetas = etiquetas or {}
        if conocidos is None:
            conocidos = sorted(set(w["ruta"] for w in escrituras) | set(self.area.archivos() if self.area else []))
        documentos = {}
        cruces = []
        ejecuciones_por_informe = {}

        def doc(rel, cls):
            d = documentos.get(rel)
            if d is None:
                d = documentos[rel] = {"ruta": rel, "tipo": cls["tipo"], "etapa": cls["etapa"], "historial": [],
                                       "cruces": [], "ultima_escritura": None, "verificado_en": None,
                                       "pendiente_codex": bool(self.tipo_externo) and cls["tipo"] == self.tipo_externo}
            return d

        # Primer pase: las ejecuciones del verificador por informe, para numerar sus rondas.
        for w in escrituras:
            cls = self.clasificar(w["ruta"])
            if cls and cls["tipo"] == "verificacion":
                ejecuciones = ejecuciones_por_informe.setdefault(w["ruta"], [])
                if w["instancia"] not in [e["instancia"] for e in ejecuciones]:
                    ejecuciones.append(w)
        cruce_de = {}
        for informe, ejecuciones in ejecuciones_por_informe.items():
            rondas = (self.area.rondas(informe) if self.area else None) or {}
            final = rondas.get("ronda") or 1
            ciclo = rondas.get("ciclo") or 1
            fuente = rondas.get("fuente") or "supuesta"
            docs, tipo_doc = self.espejo(informe, conocidos)
            k = len(ejecuciones)
            # Concluyente: la ronda sale de los títulos o del encabezado, y el informe tiene al menos tantas
            # rondas como ejecuciones del verificador hubo hoy. Si no, "ronda ?" en vez de adivinar.
            concluyente = fuente != "supuesta" and k <= final
            for i, w in enumerate(ejecuciones, 1):
                ronda = final - k + i if concluyente else None
                cruce = {"ts": w["ts"], "instancia": w["instancia"], "quien": etiquetas.get(w["instancia"], w["instancia"]),
                         "informe": informe, "documentos": docs, "tipo_documento": tipo_doc or "desconocido",
                         "ronda": ronda, "ciclo": ciclo, "concluyente": concluyente, "fuente_ronda": fuente,
                         "etiqueta": f"{ronda}/{self.maximo}" if concluyente else "?"}
                cruces.append(cruce)
                cruce_de[(informe, w["instancia"])] = cruce

        # Segundo pase, en orden de tiempo: etapas, correcciones y cruces.
        for w in escrituras:
            cls = self.clasificar(w["ruta"])
            if cls is None:
                continue
            if cls["tipo"] == "verificacion":
                cruce = cruce_de.get((w["ruta"], w["instancia"]))
                if cruce is None or cruce["ts"] != w["ts"]:
                    continue  # el mismo verificador reescribiendo su informe: un solo cruce
                for rel in cruce["documentos"]:
                    d = doc(rel, self.clasificar(rel) or {"tipo": cruce["tipo_documento"], "etapa": "investigación"})
                    d["cruces"].append(cruce)
                    d["historial"].append({"ts": w["ts"], "instancia": w["instancia"], "agente": w["agente"],
                                           "quien": cruce["quien"], "accion": f"verifica (ronda {cruce['etiqueta']})"})
                    d["etapa"] = f"verificación {cruce['etiqueta']}" if cruce["concluyente"] else "verificación ronda ?"
                    d["verificado_en"] = w["ts"]
                continue
            d = doc(w["ruta"], cls)
            d["etapa"] = "corrección" if d["verificado_en"] and w["ts"] > d["verificado_en"] else cls["etapa"]
            d["historial"].append({"ts": w["ts"], "instancia": w["instancia"], "agente": w["agente"],
                                   "quien": etiquetas.get(w["instancia"], w["instancia"]), "accion": "escribe"})
            d["ultima_escritura"] = w["ts"]

        for op in operaciones_drive:
            if op["agente"] not in self.config.get("maquetado", {}).get("agentes", []):
                continue
            rel = f"drive:{op['archivo']}"
            maq = self.config.get("maquetado", {})
            d = doc(rel, {"tipo": maq.get("tipo", "maquetado"), "etapa": maq.get("etapa", "maquetado")})
            d["historial"].append({"ts": op["ts"], "instancia": op["instancia"], "agente": op["agente"],
                                   "quien": etiquetas.get(op["instancia"], op["instancia"]), "accion": "maqueta"})
            d["ultima_escritura"] = op["ts"]

        entradas_pendientes = (pendientes or {}).get("entradas", [])
        salida = []
        for d in documentos.values():
            d["historial"].sort(key=lambda h: h["ts"])
            d["cruces"].sort(key=lambda c: c["ts"])
            enc = self.area.encabezado(d["ruta"]) if self.area and not d["ruta"].startswith("drive:") else None
            d["encabezado"] = {k: enc[k] for k in ("titulo", "estado", "version", "ultima_revision")} if enc else None
            activo = any(instancias.get(h["instancia"], {}).get("estado") in ("trabajando", "esperando")
                         for h in d["historial"][-1:])
            d["pendientes"] = relacionados(d["ruta"], entradas_pendientes)
            d["bloqueado"] = bool(d["cruces"] and (d["cruces"][-1]["ronda"] or 0) >= self.maximo and d["pendientes"]
                                  and (d["ultima_escritura"] is None or d["ultima_escritura"] <= d["cruces"][-1]["ts"]))
            d["espera_responsable"] = None
            estado_doc = (d["encabezado"] or {}).get("estado")
            if not activo and estado_doc in (None, "borrador"):
                if d["bloqueado"]:
                    d["etapa"] = f"bloqueado tras {self.maximo} rondas"
                    d["espera_responsable"] = "pendientes"
                elif d["tipo"] in self.revision_inicial and not d["cruces"]:
                    d["espera_responsable"] = self.espera_revision
                elif d["tipo"] in self.revision_final and d["cruces"]:
                    d["espera_responsable"] = self.espera_final
                elif d["cruces"] and (d["ultima_escritura"] is None or d["cruces"][-1]["ts"] >= d["ultima_escritura"]):
                    d["espera_responsable"] = self.espera_revision
            if d["espera_responsable"] and d["espera_responsable"] != "pendientes":
                d["etapa"] = d["espera_responsable"]
            if estado_doc in self.estados_cerrados and not activo:
                d["etapa"] = estado_doc
            for h in d["historial"]:
                h["ts"] = h["ts"].isoformat(timespec="seconds")
            d["ultima_escritura"] = d["ultima_escritura"].isoformat(timespec="seconds") if d["ultima_escritura"] else None
            d["verificado_en"] = d["verificado_en"].isoformat(timespec="seconds") if d["verificado_en"] else None
            salida.append(d)

        def serializar(c):
            return {**c, "ts": c["ts"].isoformat(timespec="seconds")}

        cruces_salida = [serializar(c) for c in sorted(cruces, key=lambda c: c["ts"])]
        for d in salida:
            d["cruces"] = [serializar(c) for c in d["cruces"]]
        salida.sort(key=lambda d: d["ultima_escritura"] or d["verificado_en"] or "", reverse=True)
        return {"documentos": salida, "cruces": cruces_salida, "resumen_cruces": resumir_cruces(cruces_salida)}


def relacionados(ruta, entradas):
    """Entradas de pendientes.md que nombran el documento (ruta o nombre de archivo)."""
    nombre = ruta.rsplit("/", 1)[-1].lower()
    salida = []
    for e in entradas:
        rutas = [r.lower() for r in e.get("rutas", [])]
        if any(r == ruta.lower() or r.endswith("/" + nombre) or r == nombre for r in rutas) or nombre in e.get("texto", "").lower():
            salida.append({"fecha": e.get("fecha"), "titulo": e.get("titulo")})
    return salida


def resumir_cruces(cruces):
    """Cruces del día por tipo de documento y ronda, para el verificador del piso."""
    resumen = {}
    for c in cruces:
        clave = f"{c['tipo_documento']} {c['etiqueta'] if c['concluyente'] else 'ronda ?'}"
        resumen[clave] = resumen.get(clave, 0) + 1
    return resumen
