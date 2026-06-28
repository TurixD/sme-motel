"""
empleados.py - Módulo de empleados y turnos (SPEC §5.5 — sin asistente IA, Fase 1).
"""

import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta

from flask import Blueprint, jsonify, render_template, request

from config import Config
from logger import get_logger, log_action
from modules.auth import solo_admin

empleados_bp = Blueprint("empleados", __name__)
_log = get_logger()

TURNOS_LABEL        = {"manana": "Mañana", "tarde": "Tarde", "noche": "Noche"}
COLOR_DEF_EMPLEADO  = "#7BB8FF"
COLOR_DEF_SOCIO     = "#A78BFA"
DIAS_LABEL          = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


@contextmanager
def _db():
    conn = sqlite3.connect(Config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _lunes_de(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _color(emp: dict) -> str:
    return emp.get("color_calendario") or (
        COLOR_DEF_SOCIO if emp.get("es_socio") else COLOR_DEF_EMPLEADO
    )


def _bitacora(conn, fecha_afectada: str, descripcion: str) -> None:
    conn.execute(
        """INSERT INTO bitacora_calendario
           (fecha_cambio, fecha_afectada, descripcion, usuario)
           VALUES (datetime('now','localtime'), ?, ?, 'Turi')""",
        (fecha_afectada, descripcion),
    )


# ── Página principal ──────────────────────────────────────────

@empleados_bp.route("/empleados")
@solo_admin
def index():
    semana_param = request.args.get("semana", "")
    try:
        lunes = _lunes_de(date.fromisoformat(semana_param))
    except (ValueError, TypeError):
        lunes = _lunes_de(date.today())

    domingo       = lunes + timedelta(days=6)
    semana_dates  = [lunes + timedelta(days=i) for i in range(7)]

    with _db() as db:
        empleados_rows = db.execute(
            "SELECT * FROM empleados WHERE activo=1 ORDER BY es_socio DESC, nombre"
        ).fetchall()
        empleados = [dict(e) for e in empleados_rows]
        for e in empleados:
            e["color"] = _color(e)

        turnos_rows = db.execute(
            "SELECT * FROM turnos ORDER BY hora_inicio"
        ).fetchall()
        turnos = [dict(t) for t in turnos_rows]

        asig_rows = db.execute(
            """
            SELECT at.id, at.fecha, at.notas,
                   e.id AS emp_id, e.nombre AS emp_nombre,
                   e.es_socio, e.color_calendario,
                   t.id AS turno_id, t.nombre AS turno_nombre, t.sueldo,
                   COALESCE(pe.pagado, 1) AS pagado,
                   pe.id AS pago_id
            FROM asignaciones_turnos at
            JOIN empleados e ON at.empleado_id = e.id
            JOIN turnos    t ON at.turno_id    = t.id
            LEFT JOIN pagos_empleados pe ON pe.asignacion_turno_id = at.id
            WHERE at.fecha BETWEEN ? AND ?
            ORDER BY at.fecha, t.hora_inicio
            """,
            (lunes.isoformat(), domingo.isoformat()),
        ).fetchall()
        asignaciones = [dict(a) for a in asig_rows]
        for a in asignaciones:
            a["color"] = _color(a)

        bitacora_rows = db.execute(
            "SELECT * FROM bitacora_calendario ORDER BY fecha_cambio DESC LIMIT 15"
        ).fetchall()
        bitacora = [dict(b) for b in bitacora_rows]

    # Mapa de calendario: {fecha_iso: {turno_nombre: [asig1, asig2, ...]}}
    cal_map: dict[str, dict] = {}
    for a in asignaciones:
        cal_map.setdefault(a["fecha"], {}).setdefault(a["turno_nombre"], []).append(a)

    # Nómina agrupada por empleado
    nomina: dict[int, dict] = {}
    for a in asignaciones:
        eid = a["emp_id"]
        if eid not in nomina:
            nomina[eid] = {
                "emp_id":       eid,
                "nombre":       a["emp_nombre"],
                "color":        a["color"],
                "dias":         0,
                "total":        0.0,
                "pagado_todos": True,
                "asig_ids":     [],
            }
        nomina[eid]["dias"]   += 1
        nomina[eid]["total"]  += float(a["sueldo"])
        if not a["pagado"]:
            nomina[eid]["pagado_todos"] = False
        nomina[eid]["asig_ids"].append(a["id"])
    nomina_list = sorted(nomina.values(), key=lambda x: x["nombre"])

    return render_template(
        "empleados.html",
        lunes=lunes,
        domingo=domingo,
        semana_dates=semana_dates,
        dias_label=DIAS_LABEL,
        turnos=turnos,
        turnos_label=TURNOS_LABEL,
        empleados=empleados,
        cal_map=cal_map,
        asignaciones=asignaciones,
        nomina=nomina_list,
        bitacora=bitacora,
        semana_prev=(lunes - timedelta(days=7)).isoformat(),
        semana_next=(lunes + timedelta(days=7)).isoformat(),
        hoy=date.today().isoformat(),
    )


# ── API: alta ─────────────────────────────────────────────────

@empleados_bp.route("/empleados/alta", methods=["POST"])
@solo_admin
def alta():
    data          = request.get_json(silent=True) or {}
    nombre        = (data.get("nombre") or "").strip()
    turno_default = (data.get("turno_default") or "").strip()
    es_socio      = int(bool(data.get("es_socio")))
    fecha_ingreso = data.get("fecha_ingreso") or date.today().isoformat()
    notas         = (data.get("notas") or "").strip()

    if not nombre:
        return jsonify({"error": "El nombre es requerido"}), 400
    if turno_default not in TURNOS_LABEL:
        return jsonify({"error": "Turno inválido"}), 400

    with _db() as db:
        cur = db.execute(
            """INSERT INTO empleados
               (nombre, turno_default, es_socio, activo, fecha_ingreso, notas)
               VALUES (?, ?, ?, 1, ?, ?)""",
            (nombre, turno_default, es_socio, fecha_ingreso, notas),
        )
        db.commit()
        nuevo_id = cur.lastrowid

    log_action("Alta empleado: id=%d nombre=%s turno=%s socio=%s",
               nuevo_id, nombre, turno_default, bool(es_socio))
    return jsonify({"ok": True, "id": nuevo_id})


# ── API: editar ───────────────────────────────────────────────

@empleados_bp.route("/empleados/<int:emp_id>", methods=["PUT"])
@solo_admin
def editar(emp_id):
    data          = request.get_json(silent=True) or {}
    nombre        = (data.get("nombre") or "").strip()
    turno_default = (data.get("turno_default") or "").strip()
    es_socio      = int(bool(data.get("es_socio")))
    notas         = (data.get("notas") or "").strip()

    if not nombre:
        return jsonify({"error": "El nombre es requerido"}), 400
    if turno_default not in TURNOS_LABEL:
        return jsonify({"error": "Turno inválido"}), 400

    with _db() as db:
        anterior = db.execute(
            "SELECT nombre FROM empleados WHERE id=?", (emp_id,)
        ).fetchone()
        if not anterior:
            return jsonify({"error": "Empleado no encontrado"}), 404

        db.execute(
            "UPDATE empleados SET nombre=?, turno_default=?, es_socio=?, notas=? WHERE id=?",
            (nombre, turno_default, es_socio, notas, emp_id),
        )
        db.commit()

    log_action("Edición empleado: id=%d %s→%s turno=%s",
               emp_id, anterior["nombre"], nombre, turno_default)
    return jsonify({"ok": True})


# ── API: baja ─────────────────────────────────────────────────

@empleados_bp.route("/empleados/<int:emp_id>/baja", methods=["POST"])
@solo_admin
def baja(emp_id):
    hoy = date.today().isoformat()

    with _db() as db:
        emp = db.execute(
            "SELECT nombre FROM empleados WHERE id=? AND activo=1", (emp_id,)
        ).fetchone()
        if not emp:
            return jsonify({"error": "Empleado no encontrado o ya inactivo"}), 404

        # Borrar asignaciones futuras (desde hoy)
        db.execute(
            "DELETE FROM asignaciones_turnos WHERE empleado_id=? AND fecha >= ?",
            (emp_id, hoy),
        )
        db.execute(
            "UPDATE empleados SET activo=0, fecha_baja=? WHERE id=?",
            (hoy, emp_id),
        )
        db.commit()

    log_action("Baja empleado: id=%d nombre=%s fecha=%s", emp_id, emp["nombre"], hoy)
    return jsonify({"ok": True})


# ── API: agregar asignación de turno (siempre INSERT) ─────────

@empleados_bp.route("/empleados/asignar", methods=["POST"])
@solo_admin
def asignar():
    data     = request.get_json(silent=True) or {}
    fecha    = (data.get("fecha") or "").strip()
    turno_id = data.get("turno_id")
    emp_id   = data.get("emp_id")
    notas    = (data.get("notas") or "").strip()

    if not fecha or not turno_id or not emp_id:
        return jsonify({"error": "Faltan parámetros"}), 400

    with _db() as db:
        # Idempotencia: mismo empleado+turno+día no se duplica
        duplicado = db.execute(
            "SELECT id FROM asignaciones_turnos WHERE fecha=? AND turno_id=? AND empleado_id=?",
            (fecha, turno_id, emp_id),
        ).fetchone()
        if duplicado:
            return jsonify({"error": "Este empleado ya está asignado a este turno ese día"}), 400

        emp = db.execute(
            "SELECT nombre, es_socio, color_calendario FROM empleados WHERE id=? AND activo=1",
            (emp_id,),
        ).fetchone()
        if not emp:
            return jsonify({"error": "Empleado no encontrado"}), 404

        turno = db.execute("SELECT nombre, sueldo FROM turnos WHERE id=?", (turno_id,)).fetchone()
        if not turno:
            return jsonify({"error": "Turno no encontrado"}), 404

        t_label    = TURNOS_LABEL.get(turno["nombre"], turno["nombre"])
        sueldo     = float(turno["sueldo"])
        emp_nombre = emp["nombre"]

        cur = db.execute(
            """INSERT INTO asignaciones_turnos
               (fecha, empleado_id, turno_id, es_doble_turno, notas, creado_en)
               VALUES (?, ?, ?, 0, ?, datetime('now','localtime'))""",
            (fecha, emp_id, turno_id, notas),
        )
        asig_id = cur.lastrowid
        db.execute(
            """INSERT INTO pagos_empleados
               (asignacion_turno_id, empleado_id, fecha, monto, pagado, creado_en)
               VALUES (?, ?, ?, ?, 1, datetime('now','localtime'))""",
            (asig_id, emp_id, fecha, sueldo),
        )
        desc = f"Asignado: {t_label} {fecha} → {emp_nombre}"
        _bitacora(db, fecha, desc)
        db.commit()
        log_action("%s", desc)

    color = _color({"color_calendario": emp["color_calendario"], "es_socio": emp["es_socio"]})
    return jsonify({"ok": True, "asig_id": asig_id, "emp_nombre": emp_nombre, "color": color})


# ── API: quitar asignación específica ────────────────────────

@empleados_bp.route("/empleados/asignar/<int:asig_id>", methods=["DELETE"])
@solo_admin
def quitar_asignacion(asig_id):
    with _db() as db:
        asig = db.execute(
            """SELECT at.fecha, t.nombre AS turno_nombre, e.nombre AS emp_nombre
               FROM asignaciones_turnos at
               JOIN turnos    t ON at.turno_id    = t.id
               JOIN empleados e ON at.empleado_id = e.id
               WHERE at.id=?""",
            (asig_id,),
        ).fetchone()
        if not asig:
            return jsonify({"error": "Asignación no encontrada"}), 404

        db.execute("DELETE FROM pagos_empleados WHERE asignacion_turno_id=?", (asig_id,))
        db.execute("DELETE FROM asignaciones_turnos WHERE id=?", (asig_id,))
        t_label = TURNOS_LABEL.get(asig["turno_nombre"], asig["turno_nombre"])
        _bitacora(db, asig["fecha"],
                  f"Quitado: {t_label} {asig['fecha']} - {asig['emp_nombre']}")
        db.commit()

    log_action("Asignación quitada: id=%d", asig_id)
    return jsonify({"ok": True})


# ── API: toggle pagado en nómina ──────────────────────────────

@empleados_bp.route("/empleados/nomina/pago", methods=["POST"])
@solo_admin
def nomina_pago():
    data    = request.get_json(silent=True) or {}
    asig_id = data.get("asig_id")
    pagado  = int(bool(data.get("pagado", True)))

    if not asig_id:
        return jsonify({"error": "Falta asig_id"}), 400

    with _db() as db:
        pago = db.execute(
            "SELECT id FROM pagos_empleados WHERE asignacion_turno_id=?", (asig_id,)
        ).fetchone()

        if pago:
            db.execute(
                "UPDATE pagos_empleados SET pagado=? WHERE asignacion_turno_id=?",
                (pagado, asig_id),
            )
        else:
            asig = db.execute(
                "SELECT empleado_id, fecha, turno_id FROM asignaciones_turnos WHERE id=?",
                (asig_id,),
            ).fetchone()
            if not asig:
                return jsonify({"error": "Asignación no encontrada"}), 404
            turno = db.execute("SELECT sueldo FROM turnos WHERE id=?", (asig["turno_id"],)).fetchone()
            db.execute(
                """INSERT INTO pagos_empleados
                   (asignacion_turno_id, empleado_id, fecha, monto, pagado, creado_en)
                   VALUES (?, ?, ?, ?, ?, datetime('now','localtime'))""",
                (asig_id, asig["empleado_id"], asig["fecha"],
                 turno["sueldo"] if turno else 0, pagado),
            )
        db.commit()

    return jsonify({"ok": True})
