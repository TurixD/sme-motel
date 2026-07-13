"""
asistente_turnos.py — Lógica de dominio de turnos para el asistente IA.

Todo el cálculo de fechas, la atomicidad y la validación de cobertura viven
aquí, en Python determinista. El modelo NUNCA escribe SQL para turnos: solo
llama tools que invocan estas funciones con parámetros validados. Así se
eliminan los problemas de producción (fechas enumeradas a mano, DELETE sin su
INSERT, conteos inventados).

El calendario de `asignaciones_turnos` son filas concretas por fecha (una fila
por empleado/turno/día). "Reasignar recurrente" = iterar las fechas del
calendario que caen en cierto día de la semana dentro de un rango.
"""

import difflib
import unicodedata
from datetime import date, datetime
from zoneinfo import ZoneInfo

_TZ = ZoneInfo("America/Mexico_City")

# weekday() de Python: lunes=0 … domingo=6
_DIAS = {
    "lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3,
    "viernes": 4, "sabado": 5, "domingo": 6,
}
_DIAS_NOMBRE = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


# ── Helpers de tiempo (America/Mexico_City) ──────────────────────────────────

def ahora_mx() -> datetime:
    return datetime.now(_TZ)


def hoy_iso() -> str:
    return ahora_mx().strftime("%Y-%m-%d")


def contexto_fecha() -> dict:
    """Fecha/hora actual para inyectar en el system prompt y en obtener_fecha_hoy."""
    a = ahora_mx()
    return {
        "fecha": a.strftime("%Y-%m-%d"),
        "hora": a.strftime("%H:%M"),
        "dia_semana": _DIAS_NOMBRE[a.weekday()],
        "mes": a.month,
        "anio": a.year,
        "mes_inicio": a.strftime("%Y-%m-01"),
    }


# ── Normalización / resolución de nombres, días y turnos ─────────────────────

def norm(s) -> str:
    """minúsculas sin acentos, para comparar tolerante a dedazos ('mañana'→'manana')."""
    s = (s or "").strip().lower()
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def dia_semana_int(valor):
    """Acepta 0-6 (lunes=0) o nombre en español; devuelve int 0-6 o None."""
    if valor is None:
        return None
    if isinstance(valor, bool):
        return None
    if isinstance(valor, int):
        return valor if 0 <= valor <= 6 else None
    v = norm(str(valor))
    if v.isdigit():
        n = int(v)
        return n if 0 <= n <= 6 else None
    return _DIAS.get(v)


_ALIAS_TURNO = {
    "manana": "manana", "am": "manana", "matutino": "manana",
    "tarde": "tarde", "pm": "tarde", "vespertino": "tarde",
    "noche": "noche", "nocturno": "noche",
}


def resolver_turno_id(conn, turno):
    """Acepta id (1-3) o nombre (mañana/tarde/noche, tolerante). Devuelve (id, nombre) o (None, None)."""
    if turno is None or (isinstance(turno, str) and not turno.strip()):
        return None, None
    # por id numérico
    try:
        tid = int(turno)
        row = conn.execute("SELECT id, nombre FROM turnos WHERE id=?", (tid,)).fetchone()
        if row:
            return row["id"], row["nombre"]
    except (ValueError, TypeError):
        pass
    v = norm(str(turno))
    for r in conn.execute("SELECT id, nombre FROM turnos").fetchall():
        if norm(r["nombre"]) == v:
            return r["id"], r["nombre"]
    if v in _ALIAS_TURNO:
        r = conn.execute("SELECT id, nombre FROM turnos WHERE nombre=?", (_ALIAS_TURNO[v],)).fetchone()
        if r:
            return r["id"], r["nombre"]
    return None, None


def _weekday(fecha_iso: str) -> int:
    return date.fromisoformat(fecha_iso).weekday()


def _nombres_empleados(conn, ids):
    if not ids:
        return {}
    q = "SELECT id, nombre FROM empleados WHERE id IN (%s)" % ",".join("?" * len(ids))
    return {r["id"]: r["nombre"] for r in conn.execute(q, list(ids)).fetchall()}


def _validar_empleados(conn, ids):
    """Devuelve (ok, error). Exige que existan y estén activos."""
    ids = [i for i in ids if i is not None]
    if not ids:
        return True, None
    rows = {r["id"]: r for r in conn.execute(
        "SELECT id, activo FROM empleados WHERE id IN (%s)" % ",".join("?" * len(ids)),
        ids,
    ).fetchall()}
    faltan = [i for i in ids if i not in rows]
    if faltan:
        return False, f"Empleado(s) inexistente(s): {faltan}"
    inactivos = [i for i in ids if not rows[i]["activo"]]
    if inactivos:
        nombres = _nombres_empleados(conn, inactivos)
        return False, "Empleado(s) inactivo(s): " + ", ".join(nombres.get(i, str(i)) for i in inactivos)
    return True, None


# ── Roster para inyectar en el system prompt (dinámico cada request) ─────────

_ORDEN_TURNO = {"manana": 0, "tarde": 1, "noche": 2}


def roster_texto(conn) -> str:
    """Lista compacta de empleados activos con ids, para el system prompt.
    Se regenera cada request desde la BD → nunca se desactualiza."""
    rows = conn.execute(
        "SELECT id, nombre, turno_default, es_socio FROM empleados WHERE activo=1 ORDER BY nombre"
    ).fetchall()
    grupos = {}
    for r in rows:
        etiqueta = f"{r['nombre']}({r['id']}" + (", socio" if r["es_socio"] else "") + ")"
        grupos.setdefault(r["turno_default"] or "otro", []).append(etiqueta)
    orden = sorted(grupos, key=lambda t: _ORDEN_TURNO.get(t, 9))
    lineas = [f"- {t}: " + ", ".join(grupos[t]) for t in orden]
    return ("EMPLEADOS ACTIVOS (nombre(id)); usa estos ids EXACTOS, no los inventes ni "
            "adivines. Si un nombre no aparece aquí, no existe o está inactivo:\n" + "\n".join(lineas))


# ── Tools de LECTURA (se ejecutan sin confirmación) ──────────────────────────

def tool_consultar_empleados(conn, inp):
    filtro = inp.get("nombre")
    rows = [dict(r) for r in conn.execute(
        "SELECT id, nombre, turno_default, es_socio, activo FROM empleados "
        "ORDER BY activo DESC, nombre"
    ).fetchall()]
    aproximado = False
    if filtro:
        n = norm(filtro)
        exactos = [e for e in rows if n in norm(e["nombre"])]
        if exactos:
            rows = exactos
        else:
            # Tolerancia a dedazos ('betzaida' ≈ 'Betzaira'): match aproximado
            por_norm = {norm(e["nombre"]): e for e in rows}
            cerca = difflib.get_close_matches(n, list(por_norm.keys()), n=3, cutoff=0.6)
            rows = [por_norm[k] for k in cerca]
            aproximado = bool(rows)
    return {"ok": True, "empleados": rows, "total": len(rows), "match_aproximado": aproximado}


def tool_consultar_asignaciones(conn, inp):
    fi = inp.get("fecha_inicio") or hoy_iso()
    ff = inp.get("fecha_fin")
    dia = dia_semana_int(inp.get("dia_semana"))
    emp = inp.get("empleado_id")
    tid, _tnom = resolver_turno_id(conn, inp.get("turno")) if inp.get("turno") else (None, None)
    if inp.get("turno") and tid is None:
        return {"ok": False, "error": f"Turno no reconocido: {inp.get('turno')!r}"}

    where, params = ["at.fecha >= ?"], [fi]
    if ff:
        where.append("at.fecha <= ?"); params.append(ff)
    if emp is not None:
        where.append("at.empleado_id = ?"); params.append(int(emp))
    if tid is not None:
        where.append("at.turno_id = ?"); params.append(tid)

    sql = (
        "SELECT at.fecha, t.nombre AS turno, e.id AS empleado_id, e.nombre AS empleado "
        "FROM asignaciones_turnos at "
        "JOIN turnos t ON t.id = at.turno_id "
        "JOIN empleados e ON e.id = at.empleado_id "
        "WHERE " + " AND ".join(where) +
        " ORDER BY at.fecha, at.turno_id, e.nombre"
    )
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    if dia is not None:
        rows = [r for r in rows if _weekday(r["fecha"]) == dia]

    total = len(rows)
    n_fechas = len({r["fecha"] for r in rows})
    # Compacto: no devolvemos cientos de filas al modelo (evita que enumere y gasta menos).
    truncado = total > 60
    return {
        "ok": True,
        "asignaciones": rows[:60],
        "total": total,
        "truncado": truncado,
        "fechas_distintas": n_fechas,
        "rango": {"desde": fi, "hasta": ff},
    }


def tool_resumen_cobertura(conn, inp):
    """Fechas/turnos que quedan SIN ningún empleado en un rango."""
    fi = inp.get("fecha_inicio") or hoy_iso()
    ff = inp.get("fecha_fin")
    tid, _tnom = resolver_turno_id(conn, inp.get("turno")) if inp.get("turno") else (None, None)
    if inp.get("turno") and tid is None:
        return {"ok": False, "error": f"Turno no reconocido: {inp.get('turno')!r}"}

    where, params = ["fecha >= ?"], [fi]
    if ff:
        where.append("fecha <= ?"); params.append(ff)
    w = " AND ".join(where)

    fechas = [r["fecha"] for r in conn.execute(
        f"SELECT DISTINCT fecha FROM asignaciones_turnos WHERE {w} ORDER BY fecha", params
    ).fetchall()]
    turnos = [dict(t) for t in conn.execute("SELECT id, nombre FROM turnos ORDER BY id").fetchall()]
    if tid:
        turnos = [t for t in turnos if t["id"] == tid]

    cnt = {}
    for r in conn.execute(
        f"SELECT fecha, turno_id, COUNT(*) n FROM asignaciones_turnos WHERE {w} "
        f"GROUP BY fecha, turno_id", params
    ).fetchall():
        cnt[(r["fecha"], r["turno_id"])] = r["n"]

    vacias = [
        {"fecha": f, "turno": t["nombre"]}
        for f in fechas for t in turnos
        if cnt.get((f, t["id"]), 0) == 0
    ]
    return {
        "ok": True,
        "sin_cobertura": vacias,
        "total_sin_cobertura": len(vacias),
        "rango": {"desde": fi, "hasta": ff or (fechas[-1] if fechas else fi)},
    }


# ── Planificación de reasignación recurrente (sin ejecutar) ──────────────────

def _empleados_en(conn, fecha, turno_id):
    return {r["empleado_id"] for r in conn.execute(
        "SELECT empleado_id FROM asignaciones_turnos WHERE fecha=? AND turno_id=?",
        (fecha, turno_id),
    ).fetchall()}


def planear_reasignar(conn, inp):
    """
    Calcula el plan completo SIN ejecutar. Devuelve un dict con:
      ok, turno, turno_id, dia_semana, desde, hasta, fechas_afectadas, n_fechas,
      eliminados, insertados, omitidos_dup, sin_cobertura (lista de fechas que
      quedarían vacías), ops {fecha: {quitar:[], agregar:[]}}, resumen.
    Si algo es inválido devuelve {ok: False, error}.
    """
    dia = dia_semana_int(inp.get("dia_semana"))
    if dia is None:
        return {"ok": False, "error": "dia_semana inválido (usa lunes..domingo o 0-6)."}
    tid, tnom = resolver_turno_id(conn, inp.get("turno"))
    if tid is None:
        return {"ok": False, "error": f"Turno no reconocido: {inp.get('turno')!r}"}

    def _ints(lst):
        return [int(x) for x in (lst or [])]

    quitar = _ints(inp.get("quitar_empleado_ids"))
    agregar = _ints(inp.get("agregar_empleado_ids"))
    excepciones = inp.get("excepciones") or []

    if not quitar and not agregar and not excepciones:
        return {"ok": False, "error": "No se indicó a quién quitar ni a quién agregar."}

    desde = inp.get("desde_fecha") or hoy_iso()
    hasta = inp.get("hasta_fecha")
    if not hasta:
        row = conn.execute("SELECT MAX(fecha) mx FROM asignaciones_turnos").fetchone()
        hasta = row["mx"] if row and row["mx"] else desde
    if desde > hasta:
        return {"ok": False, "error": f"Rango inválido: desde {desde} es posterior a hasta {hasta}."}

    # Excepciones por fecha (sobrescriben la regla general en esa fecha)
    exc_map = {}
    for exc in excepciones:
        f = (exc.get("fecha") or "").strip()
        if not f:
            continue
        exc_map[f] = {"quitar": _ints(exc.get("quitar_ids")), "agregar": _ints(exc.get("agregar_ids"))}

    # Validar que todos los empleados referidos existan y estén activos
    todos = set(quitar) | set(agregar)
    for v in exc_map.values():
        todos |= set(v["quitar"]) | set(v["agregar"])
    ok, err = _validar_empleados(conn, list(todos))
    if not ok:
        return {"ok": False, "error": err}

    # Fechas objetivo: calendario en [desde, hasta] que caen en 'dia'
    fechas = [r["fecha"] for r in conn.execute(
        "SELECT DISTINCT fecha FROM asignaciones_turnos WHERE fecha>=? AND fecha<=? ORDER BY fecha",
        (desde, hasta),
    ).fetchall()]
    fechas = [f for f in fechas if _weekday(f) == dia]
    # Incluye fechas de excepción que existan en el calendario aunque no cayeran en el filtro
    cal = set()
    if exc_map:
        marcadores = ",".join("?" * len(exc_map))
        cal = {r["fecha"] for r in conn.execute(
            f"SELECT DISTINCT fecha FROM asignaciones_turnos WHERE fecha IN ({marcadores})",
            list(exc_map.keys()),
        ).fetchall()}
    fechas = sorted(set(fechas) | cal)

    if not fechas:
        return {"ok": False, "error": f"No hay fechas de {_DIAS_NOMBRE[dia]} en el calendario entre {desde} y {hasta}."}

    ops = {}
    eliminados = insertados = omitidos = 0
    vacias = []
    for f in fechas:
        if f in exc_map:
            q, a = exc_map[f]["quitar"], exc_map[f]["agregar"]
        else:
            q, a = quitar, agregar
        ops[f] = {"quitar": q, "agregar": a}

        actuales = _empleados_en(conn, f, tid)
        a_quitar = set(q) & actuales
        tras_quitar = actuales - set(q)
        a_agregar = set(a) - tras_quitar          # los que aún no están
        dup = set(a) & tras_quitar                # pedidos pero ya presentes
        final = tras_quitar | set(a)

        eliminados += len(a_quitar)
        insertados += len(a_agregar)
        omitidos += len(dup)
        if not final:
            vacias.append(f)

    nombres = _nombres_empleados(conn, list(todos))
    resumen = (
        f"{_DIAS_NOMBRE[dia].capitalize()}s turno {tnom}, del {desde} al {hasta}: "
        + (f"quitar {', '.join(nombres.get(i, str(i)) for i in quitar)}; " if quitar else "")
        + (f"agregar {', '.join(nombres.get(i, str(i)) for i in agregar)}; " if agregar else "")
        + (f"{len(exc_map)} excepción(es); " if exc_map else "")
        + f"{len(fechas)} fecha(s) → {eliminados} quitado(s), {insertados} agregado(s), {omitidos} duplicado(s) omitido(s)."
    )
    return {
        "ok": True,
        "turno": tnom, "turno_id": tid, "dia_semana": dia,
        "desde": desde, "hasta": hasta,
        "fechas_afectadas": fechas, "n_fechas": len(fechas),
        "eliminados": eliminados, "insertados": insertados, "omitidos_dup": omitidos,
        "sin_cobertura": vacias,
        "ops": ops,
        "nombres": nombres,
        "resumen": resumen,
    }


def _fechas_vacias(conn, fechas, turno_id):
    """Dentro de la transacción: fechas que quedaron con 0 empleados en el turno."""
    vacias = []
    for f in fechas:
        n = conn.execute(
            "SELECT COUNT(*) n FROM asignaciones_turnos WHERE fecha=? AND turno_id=?",
            (f, turno_id),
        ).fetchone()["n"]
        if n == 0:
            vacias.append(f)
    return vacias


def ejecutar_reasignar(conn, inp, dry_run=False):
    """
    Ejecuta (o simula) la reasignación recurrente de forma 100% atómica.
    Re-planifica contra el estado ACTUAL de la BD para reflejar cambios recientes.
    Todos los DELETE/INSERT van en UNA transacción; si al final alguna fecha
    quedaría sin cobertura → ROLLBACK. Imposible que queden solo los DELETE.
    """
    plan = planear_reasignar(conn, inp)
    if not plan.get("ok"):
        return plan

    if plan["sin_cobertura"]:
        return {
            "ok": False, "error": "cobertura",
            "sin_cobertura": plan["sin_cobertura"],
            "mensaje": "El cambio dejaría estas fechas sin NADIE en el turno "
                       f"{plan['turno']}: {', '.join(plan['sin_cobertura'][:10])}"
                       + ("…" if len(plan['sin_cobertura']) > 10 else "")
                       + ". No se ejecutó nada.",
        }

    if dry_run:
        return {**plan, "ejecutado": False, "dry_run": True}

    tid = plan["turno_id"]
    try:
        el = ins = 0
        # La tabla NO tiene UNIQUE(fecha,turno_id,empleado_id): la idempotencia se
        # garantiza a nivel de app insertando solo a quien realmente falta y leyendo
        # el estado fresco por fecha.
        for f in plan["fechas_afectadas"]:
            q = set(plan["ops"][f]["quitar"])
            a = set(plan["ops"][f]["agregar"])
            actuales = _empleados_en(conn, f, tid)
            for eid in q & actuales:
                cur = conn.execute(
                    "DELETE FROM asignaciones_turnos WHERE fecha=? AND turno_id=? AND empleado_id=?",
                    (f, tid, eid),
                )
                el += cur.rowcount
            tras_quitar = actuales - q
            for eid in a - tras_quitar:          # solo los que aún no están
                conn.execute(
                    "INSERT INTO asignaciones_turnos (fecha, empleado_id, turno_id) VALUES (?, ?, ?)",
                    (f, eid, tid),
                )
                ins += 1
        # Validación de cobertura DENTRO de la transacción (lee cambios pendientes)
        vacias = _fechas_vacias(conn, plan["fechas_afectadas"], tid)
        if vacias:
            conn.rollback()
            return {
                "ok": False, "error": "cobertura", "sin_cobertura": vacias,
                "mensaje": "ROLLBACK: el cambio dejaría fechas sin cobertura. No se guardó nada.",
            }
        conn.commit()
    except Exception as exc:
        conn.rollback()
        return {"ok": False, "error": str(exc)}

    return {
        "ok": True, "ejecutado": True,
        "eliminados": el, "insertados": ins, "omitidos_dup": plan["omitidos_dup"],
        "n_fechas": plan["n_fechas"], "turno": plan["turno"],
        "resumen": plan["resumen"],
    }


# ── Operaciones puntuales de una sola fecha ──────────────────────────────────

def planear_asignar_fecha(conn, inp):
    fecha = (inp.get("fecha") or "").strip()
    if not fecha:
        return {"ok": False, "error": "Falta la fecha."}
    tid, tnom = resolver_turno_id(conn, inp.get("turno"))
    if tid is None:
        return {"ok": False, "error": f"Turno no reconocido: {inp.get('turno')!r}"}
    try:
        eid = int(inp.get("empleado_id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "empleado_id inválido."}
    ok, err = _validar_empleados(conn, [eid])
    if not ok:
        return {"ok": False, "error": err}
    ya = eid in _empleados_en(conn, fecha, tid)
    nombre = _nombres_empleados(conn, [eid]).get(eid, str(eid))
    return {
        "ok": True, "fecha": fecha, "turno": tnom, "turno_id": tid,
        "empleado_id": eid, "empleado": nombre, "ya_asignado": ya,
        "resumen": f"Asignar a {nombre} el {fecha} en turno {tnom}"
                   + (" (ya estaba, sin cambio)" if ya else "."),
    }


def ejecutar_asignar_fecha(conn, inp, dry_run=False):
    plan = planear_asignar_fecha(conn, inp)
    if not plan.get("ok"):
        return plan
    if dry_run:
        return {**plan, "ejecutado": False, "dry_run": True}
    # Re-lee estado fresco; sin UNIQUE en la tabla, evitamos duplicar comprobando aquí.
    if plan["empleado_id"] in _empleados_en(conn, plan["fecha"], plan["turno_id"]):
        return {"ok": True, "ejecutado": True, "insertados": 0, "omitidos_dup": 1,
                "resumen": plan["resumen"] + " (ya estaba, sin cambio)"}
    try:
        conn.execute(
            "INSERT INTO asignaciones_turnos (fecha, empleado_id, turno_id) VALUES (?, ?, ?)",
            (plan["fecha"], plan["empleado_id"], plan["turno_id"]),
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "ejecutado": True, "insertados": 1, "omitidos_dup": 0,
            "resumen": plan["resumen"]}


def planear_quitar_fecha(conn, inp):
    fecha = (inp.get("fecha") or "").strip()
    if not fecha:
        return {"ok": False, "error": "Falta la fecha."}
    tid, tnom = resolver_turno_id(conn, inp.get("turno"))
    if tid is None:
        return {"ok": False, "error": f"Turno no reconocido: {inp.get('turno')!r}"}
    try:
        eid = int(inp.get("empleado_id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "empleado_id inválido."}
    actuales = _empleados_en(conn, fecha, tid)
    nombre = _nombres_empleados(conn, [eid]).get(eid, str(eid))
    presente = eid in actuales
    dejaria_vacio = presente and len(actuales) == 1
    return {
        "ok": True, "fecha": fecha, "turno": tnom, "turno_id": tid,
        "empleado_id": eid, "empleado": nombre, "presente": presente,
        "dejaria_sin_cobertura": dejaria_vacio,
        "resumen": f"Quitar a {nombre} del {fecha} turno {tnom}"
                   + ("" if presente else " (no estaba asignado)") + ".",
    }


def ejecutar_quitar_fecha(conn, inp, dry_run=False):
    plan = planear_quitar_fecha(conn, inp)
    if not plan.get("ok"):
        return plan
    if plan["dejaria_sin_cobertura"]:
        return {
            "ok": False, "error": "cobertura",
            "mensaje": f"No se puede: {plan['empleado']} es el único en el turno "
                       f"{plan['turno']} el {plan['fecha']}; quedaría sin cobertura.",
        }
    if dry_run:
        return {**plan, "ejecutado": False, "dry_run": True}
    try:
        cur = conn.execute(
            "DELETE FROM asignaciones_turnos WHERE fecha=? AND turno_id=? AND empleado_id=?",
            (plan["fecha"], plan["turno_id"], plan["empleado_id"]),
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "ejecutado": True, "eliminados": cur.rowcount, "resumen": plan["resumen"]}


# ── Despacho por 'kind' (usado por el endpoint de ejecución de la tarjeta) ────

_EJECUTORES = {
    "reasignar": ejecutar_reasignar,
    "asignar_fecha": ejecutar_asignar_fecha,
    "quitar_fecha": ejecutar_quitar_fecha,
}

_PLANIFICADORES = {
    "reasignar": planear_reasignar,
    "asignar_fecha": planear_asignar_fecha,
    "quitar_fecha": planear_quitar_fecha,
}


def ejecutar_por_kind(conn, kind, params, dry_run=False):
    fn = _EJECUTORES.get(kind)
    if not fn:
        return {"ok": False, "error": f"kind desconocido: {kind}"}
    return fn(conn, params, dry_run=dry_run)


def planear_por_kind(conn, kind, params):
    fn = _PLANIFICADORES.get(kind)
    if not fn:
        return {"ok": False, "error": f"kind desconocido: {kind}"}
    return fn(conn, params)
