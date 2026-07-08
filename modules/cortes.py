"""
cortes.py - Módulo de cortes de turno (v2.3).

Flujo simplificado: empleado declara bruto en caja y cuenta de inmediato para
ingresos_diarios. Admin puede editar (corrige) o anular (invalida) después,
en cualquier momento. No hay paso de "confirmar".
Sueldos se manejan por separado (lógica semanal automática de v1).
"""

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, render_template, request

from config import Config
from logger import log_action
from modules.auth import _get_modo, solo_admin

cortes_bp = Blueprint("cortes", __name__)

_TURNOS_ORDEN  = ["manana", "tarde", "noche"]
_TURNO_LABELS  = {"manana": "Mañana", "tarde": "Tarde", "noche": "Noche"}
_FRANJA_INICIO = {"manana": "08:00:00", "tarde": "16:00:00"}
_FRANJA_FIN    = {"manana": "15:59:59", "tarde": "22:59:59"}

# Ventanas horarias para que el EMPLEADO pueda declarar (hora inicio inclusiva, fin inclusiva)
_VENTANA_HORAS = {"manana": (15, 16), "tarde": (22, 23), "noche": (7, 8)}
_VENTANA_LABEL = {"manana": "Ventana: 15:00 – 17:00", "tarde": "Ventana: 22:00 – 00:00", "noche": "Ventana: 07:00 – 09:00"}


def _ventanas_activas() -> dict:
    hora = datetime.now().hour
    return {
        t: (inicio <= hora <= fin)
        for t, (inicio, fin) in _VENTANA_HORAS.items()
    }


@contextmanager
def _db():
    conn = sqlite3.connect(Config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ── Cálculo de bruto ──────────────────────────────────────────

def _calcular_bruto(conn, turno: str, fecha: str) -> dict:
    """Suma rentas activas del sistema para la franja del turno."""
    if turno in ("manana", "tarde"):
        row = conn.execute(
            """SELECT COALESCE(SUM(precio_cobrado), 0) AS bruto, COUNT(*) AS cnt
               FROM rentas
               WHERE fecha = ? AND hora_registro BETWEEN ? AND ?
                 AND estado = 'activo'""",
            (fecha, _FRANJA_INICIO[turno], _FRANJA_FIN[turno]),
        ).fetchone()
    else:  # noche: 23:00–07:59, cruza la medianoche
        fecha_sig = (date.fromisoformat(fecha) + timedelta(days=1)).isoformat()
        row = conn.execute(
            """SELECT COALESCE(SUM(precio_cobrado), 0) AS bruto, COUNT(*) AS cnt
               FROM rentas
               WHERE (
                   (fecha = ? AND hora_registro >= '23:00:00')
                   OR
                   (fecha = ? AND hora_registro < '08:00:00')
               ) AND estado = 'activo'""",
            (fecha, fecha_sig),
        ).fetchone()
    return {"bruto": float(row["bruto"]), "count_rentas": int(row["cnt"])}


def _actualizar_ingresos_diarios(conn, fecha: str) -> dict:
    """
    Recalcula ingresos_diarios para una fecha sumando los cortes válidos
    (estado 'declarado' o 'editado'; los 'anulado' no cuentan).

    Siempre recalcula con los cortes existentes, sin importar cuántos turnos
    haya declarados (1, 2 o 3). El total se actualiza de forma incremental en
    cada declaración/edición/anulación, reflejando lo declarado hasta el momento.
    """

    bruto_total = conn.execute(
        """SELECT COALESCE(SUM(bruto_declarado), 0) FROM cortes_turno
           WHERE fecha = ? AND estado IN ('declarado', 'editado')""",
        (fecha,),
    ).fetchone()[0]
    bruto_total = float(bruto_total)
    notas_sync  = "Generado desde cortes de turno v2.3"

    existente = conn.execute(
        "SELECT id FROM ingresos_diarios WHERE fecha = ?", (fecha,)
    ).fetchone()
    if existente:
        conn.execute(
            """UPDATE ingresos_diarios
               SET monto_efectivo=?, monto_tarjeta=0, monto_transferencia=0,
                   comision_tarjeta=0, total_neto=?, notas=?
               WHERE fecha=?""",
            (bruto_total, bruto_total, notas_sync, fecha),
        )
        log_action("ingresos_diarios ACTUALIZADO vía cortes de turno: fecha=%s bruto=%.2f", fecha, bruto_total)
    else:
        conn.execute(
            """INSERT INTO ingresos_diarios
               (fecha, monto_efectivo, monto_tarjeta, monto_transferencia,
                comision_tarjeta, total_neto, notas, creado_en)
               VALUES (?, ?, 0, 0, 0, ?, ?, datetime('now','localtime'))""",
            (fecha, bruto_total, bruto_total, notas_sync),
        )
        log_action("ingresos_diarios CREADO vía cortes de turno: fecha=%s bruto=%.2f", fecha, bruto_total)

    return {"ok": True, "bruto_total": bruto_total}


# ── Vista principal ───────────────────────────────────────────

@cortes_bp.route("/cortes")
def index():
    hoy      = date.today().isoformat()
    modo     = _get_modo()
    es_admin = modo.startswith("admin_")

    # Noche declarada en ventana matutina (07-08h) corresponde al día anterior
    hora_actual = datetime.now().hour
    fecha_noche = (date.today() - timedelta(days=1)).isoformat() if 7 <= hora_actual <= 8 else hoy

    with _db() as conn:
        # Cargar manana+tarde para HOY, noche para fecha_noche
        cortes_rows = conn.execute(
            """SELECT ct.*, e.nombre AS emp_nombre
               FROM cortes_turno ct
               LEFT JOIN empleados e ON e.id = ct.empleado_id
               WHERE (ct.fecha = ? AND ct.turno IN ('manana', 'tarde'))
                  OR (ct.fecha = ? AND ct.turno = 'noche')
               ORDER BY CASE ct.turno WHEN 'manana' THEN 1 WHEN 'tarde' THEN 2 ELSE 3 END""",
            (hoy, fecha_noche),
        ).fetchall()
        cortes_hoy = {c["turno"]: dict(c) for c in cortes_rows}

        # Empleados activos + sueldo del turno que trabajan (por turno_default)
        turnos_sueldos = {
            r["nombre"]: float(r["sueldo"])
            for r in conn.execute("SELECT nombre, sueldo FROM turnos").fetchall()
        }
        empleados_raw = conn.execute(
            "SELECT id, nombre, turno_default FROM empleados WHERE activo=1 ORDER BY nombre"
        ).fetchall()
        empleados = [
            {
                "id":            e["id"],
                "nombre":        e["nombre"],
                "turno_default": e["turno_default"],
                "sueldo":        turnos_sueldos.get(e["turno_default"], 0),
            }
            for e in empleados_raw
        ]

        # Asignaciones del día: {turno: [lista de empleados]} — puede haber múltiples por turno
        asig_rows = conn.execute(
            """SELECT at.empleado_id, t.nombre AS turno_nombre,
                      t.sueldo, e.nombre AS emp_nombre
               FROM asignaciones_turnos at
               JOIN turnos t ON t.id = at.turno_id
               JOIN empleados e ON e.id = at.empleado_id
               WHERE at.fecha = ? AND e.activo = 1
               ORDER BY t.nombre, e.nombre""",
            (hoy,),
        ).fetchall()
        asignaciones_hoy: dict = {}
        for a in asig_rows:
            t = a["turno_nombre"]
            if t not in asignaciones_hoy:
                asignaciones_hoy[t] = []
            asignaciones_hoy[t].append({
                "empleado_id": a["empleado_id"],
                "emp_nombre":  a["emp_nombre"],
                "sueldo":      float(a["sueldo"]),
            })

        # Nombres de admins (turi, gabriel) — para el campo "Declarado por".
        # Match usuarios.nombre_display == empleados.nombre (no hay FK directa).
        admin_nombres = [
            r["nombre_display"]
            for r in conn.execute(
                "SELECT nombre_display FROM usuarios WHERE activo=1 ORDER BY nombre_display"
            ).fetchall()
        ]

        historico_7 = []
        if es_admin:
            hace7 = (date.today() - timedelta(days=6)).isoformat()
            hist_rows = conn.execute(
                """SELECT ct.*, e.nombre AS emp_nombre
                   FROM cortes_turno ct
                   LEFT JOIN empleados e ON e.id = ct.empleado_id
                   WHERE ct.fecha BETWEEN ? AND ?
                   ORDER BY ct.fecha DESC,
                            CASE ct.turno WHEN 'manana' THEN 1 WHEN 'tarde' THEN 2 ELSE 3 END""",
                (hace7, hoy),
            ).fetchall()
            historico_7 = [dict(r) for r in hist_rows]

    ventanas = _ventanas_activas()

    return render_template(
        "cortes.html",
        hoy=hoy,
        fecha_noche=fecha_noche,
        es_admin=es_admin,
        cortes_hoy=cortes_hoy,
        empleados=empleados,
        asignaciones_hoy=asignaciones_hoy,
        admin_nombres=admin_nombres,
        turnos_sueldos=turnos_sueldos,
        historico_7=historico_7,
        turno_labels=_TURNO_LABELS,
        ventanas=ventanas,
        ventana_label=_VENTANA_LABEL,
    )


# ── API: calcular bruto ───────────────────────────────────────

@cortes_bp.route("/cortes/api/calcular_bruto/<turno>/<fecha>")
def api_calcular_bruto(turno, fecha):
    if turno not in _TURNOS_ORDEN:
        return jsonify({"ok": False, "error": "Turno inválido"}), 400
    try:
        date.fromisoformat(fecha)
    except ValueError:
        return jsonify({"ok": False, "error": "Fecha inválida"}), 400

    with _db() as conn:
        r = _calcular_bruto(conn, turno, fecha)
        return jsonify({"ok": True, "bruto_calculado": r["bruto"], "count_rentas": r["count_rentas"]})


# ── API: declarar corte ───────────────────────────────────────

@cortes_bp.route("/cortes/api/declarar", methods=["POST"])
def api_declarar():
    data            = request.get_json(silent=True) or {}
    turno           = (data.get("turno") or "").strip()
    fecha           = data.get("fecha") or date.today().isoformat()
    empleado_id     = data.get("empleado_id")
    bruto_declarado = data.get("bruto_declarado")
    declarado_por   = (data.get("declarado_por_nombre") or "").strip()
    notas           = (data.get("notas") or "").strip() or None

    if turno not in _TURNOS_ORDEN:
        return jsonify({"ok": False, "error": "Turno inválido"}), 400
    if empleado_id is None or bruto_declarado is None:
        return jsonify({"ok": False, "error": "Faltan campos requeridos"}), 400
    if not declarado_por:
        return jsonify({"ok": False, "error": "Indica quién declaró el corte"}), 400

    # Empleado solo puede declarar dentro de su ventana horaria
    modo = _get_modo()
    if not modo.startswith("admin_"):
        ventanas = _ventanas_activas()
        if not ventanas.get(turno, False):
            label = _VENTANA_LABEL.get(turno, "")
            return jsonify({"ok": False, "error": f"Fuera de ventana horaria. {label}"}), 403

    bruto_declarado = float(bruto_declarado)
    ahora           = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with _db() as conn:
        bruto_calc = _calcular_bruto(conn, turno, fecha)["bruto"]

        try:
            cur = conn.execute(
                """INSERT INTO cortes_turno
                   (fecha, turno, empleado_id, bruto_calculado, bruto_declarado,
                    estado, declarado_at, declarado_por_nombre, notas)
                   VALUES (?,?,?,?,?,'declarado',?,?,?)""",
                (fecha, turno, int(empleado_id), bruto_calc, bruto_declarado,
                 ahora, declarado_por, notas),
            )
            corte_id = cur.lastrowid
            _actualizar_ingresos_diarios(conn, fecha)
            conn.commit()
        except Exception as exc:
            if "UNIQUE" in str(exc):
                return jsonify({"ok": False, "error": f"Ya existe un corte de {_TURNO_LABELS[turno]} para esta fecha"}), 409
            raise

    log_action(
        "Corte DECLARADO id=%d turno=%s fecha=%s empleado_id=%d bruto=%.2f",
        corte_id, turno, fecha, int(empleado_id), bruto_declarado,
    )
    return jsonify({"ok": True, "corte_id": corte_id})


# ── API: editar corte (admin) ─────────────────────────────────

@cortes_bp.route("/cortes/api/editar/<int:corte_id>", methods=["POST"])
@solo_admin
def api_editar(corte_id):
    data            = request.get_json(silent=True) or {}
    empleado_id     = data.get("empleado_id")
    bruto_declarado = data.get("bruto_declarado")
    notas           = (data.get("notas") or "").strip() or None
    modo            = _get_modo()
    ahora           = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if empleado_id is None or bruto_declarado is None:
        return jsonify({"ok": False, "error": "Faltan campos requeridos"}), 400

    bruto_declarado = float(bruto_declarado)

    with _db() as conn:
        corte = conn.execute(
            "SELECT turno, fecha FROM cortes_turno WHERE id=?", (corte_id,)
        ).fetchone()
        if not corte:
            return jsonify({"ok": False, "error": "Corte no encontrado"}), 404

        conn.execute(
            """UPDATE cortes_turno
               SET empleado_id=?, bruto_declarado=?, notas=?,
                   estado='editado', editado_por=?, editado_at=?
               WHERE id=?""",
            (int(empleado_id), bruto_declarado, notas, modo, ahora, corte_id),
        )
        _actualizar_ingresos_diarios(conn, corte["fecha"])
        conn.commit()

    log_action("Corte EDITADO id=%d turno=%s fecha=%s por=%s bruto=%.2f",
               corte_id, corte["turno"], corte["fecha"], modo, bruto_declarado)
    return jsonify({"ok": True})


# ── API: anular corte (admin) ─────────────────────────────────

@cortes_bp.route("/cortes/api/anular/<int:corte_id>", methods=["POST"])
@solo_admin
def api_anular(corte_id):
    data   = request.get_json(silent=True) or {}
    motivo = (data.get("motivo") or "").strip() or None
    modo   = _get_modo()
    ahora  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with _db() as conn:
        corte = conn.execute(
            "SELECT turno, fecha FROM cortes_turno WHERE id=?", (corte_id,)
        ).fetchone()
        if not corte:
            return jsonify({"ok": False, "error": "Corte no encontrado"}), 404

        conn.execute(
            """UPDATE cortes_turno
               SET estado='anulado', motivo_rechazo=?, confirmado_por=?, confirmado_at=?
               WHERE id=?""",
            (motivo, modo, ahora, corte_id),
        )
        _actualizar_ingresos_diarios(conn, corte["fecha"])
        conn.commit()

    log_action("Corte ANULADO id=%d turno=%s fecha=%s por=%s motivo=%s",
               corte_id, corte["turno"], corte["fecha"], modo, motivo or "(sin motivo)")
    return jsonify({"ok": True})


# ── Historial paginado (admin) ────────────────────────────────

@cortes_bp.route("/cortes/historial")
@solo_admin
def historial():
    POR_PAGINA   = 20
    pagina       = max(1, int(request.args.get("p", 1)))
    filtro_fecha = request.args.get("fecha", "")
    filtro_turno = request.args.get("turno", "")
    filtro_est   = request.args.get("estado", "")

    where, params = [], []
    if filtro_fecha:
        where.append("ct.fecha = ?");  params.append(filtro_fecha)
    if filtro_turno:
        where.append("ct.turno = ?");  params.append(filtro_turno)
    if filtro_est:
        where.append("ct.estado = ?"); params.append(filtro_est)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    offset    = (pagina - 1) * POR_PAGINA

    with _db() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM cortes_turno ct {where_sql}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"""SELECT ct.*, e.nombre AS emp_nombre
                FROM cortes_turno ct
                LEFT JOIN empleados e ON e.id = ct.empleado_id
                {where_sql}
                ORDER BY ct.fecha DESC,
                         CASE ct.turno WHEN 'manana' THEN 1 WHEN 'tarde' THEN 2 ELSE 3 END
                LIMIT ? OFFSET ?""",
            params + [POR_PAGINA, offset],
        ).fetchall()

    return render_template(
        "cortes_historial.html",
        cortes=[dict(r) for r in rows],
        total=total,
        pagina=pagina,
        por_pagina=POR_PAGINA,
        paginas=max(1, (total + POR_PAGINA - 1) // POR_PAGINA),
        filtro_fecha=filtro_fecha,
        filtro_turno=filtro_turno,
        filtro_estado=filtro_est,
        turno_labels=_TURNO_LABELS,
    )
