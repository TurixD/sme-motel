"""
cuartos.py - Módulo de cuartos y rentas (v2.1).
"""

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime

from flask import Blueprint, jsonify, render_template, request

from config import Config
from logger import log_action

cuartos_bp = Blueprint("cuartos", __name__)

_DURACIONES_VALIDAS = {6, 12, 18, 24}
_PRECIO_KEY = {6: "precio_6h", 12: "precio_12h", 18: "precio_18h", 24: "precio_24h"}


@contextmanager
def _db():
    conn = sqlite3.connect(Config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _modo_actual() -> str:
    try:
        with _db() as conn:
            row = conn.execute(
                "SELECT valor FROM configuracion WHERE clave='modo_actual'"
            ).fetchone()
            return row["valor"] if row else "admin_turi"
    except Exception:
        return "admin_turi"


def _actividad_dia(conn, es_admin: bool) -> list[dict]:
    hoy = date.today().isoformat()
    base = """
        SELECT r.id, r.cuarto_id, r.hora_registro, r.duracion_horas,
               r.precio_default, r.precio_cobrado, r.notas, r.estado,
               r.registrado_por, r.cancelado_por, r.cancelado_at,
               r.motivo_cancelacion, r.editado, r.editado_por,
               c.nombre_display, c.tipo
        FROM rentas r
        JOIN cuartos c ON c.id = r.cuarto_id
        WHERE r.fecha = ?
    """
    if not es_admin:
        base += " AND r.estado = 'activo'"
    base += " ORDER BY r.hora_registro DESC"

    result = []
    for r in conn.execute(base, (hoy,)).fetchall():
        item = dict(r)
        item["editado"] = bool(item["editado"])
        result.append(item)
    return result


# ── Página principal ─────────────────────────────────────────

@cuartos_bp.route("/cuartos")
def index():
    modo = _modo_actual()
    es_admin = modo.startswith("admin_")

    with _db() as conn:
        cuartos = [dict(r) for r in conn.execute(
            "SELECT * FROM cuartos ORDER BY numero"
        ).fetchall()]
        rentas_dia = _actividad_dia(conn, es_admin)

    rentas_activas_json = [
        {
            "cuarto_id":    r["cuarto_id"],
            "hora_registro": r["hora_registro"],
            "duracion_horas": r["duracion_horas"],
        }
        for r in rentas_dia
        if r["estado"] == "activo"
    ]

    return render_template(
        "cuartos.html",
        cuartos=cuartos,
        rentas_dia=rentas_dia,
        rentas_activas_json=rentas_activas_json,
        es_admin=es_admin,
        modo_actual=modo,
    )


# ── API: actividad del día (polling) ────────────────────────

@cuartos_bp.route("/cuartos/api/actividad_dia")
def api_actividad_dia():
    modo = _modo_actual()
    es_admin = modo.startswith("admin_")
    with _db() as conn:
        items = _actividad_dia(conn, es_admin)
    return jsonify({"ok": True, "items": items, "es_admin": es_admin})


# ── API: registrar renta ─────────────────────────────────────

@cuartos_bp.route("/cuartos/api/registrar", methods=["POST"])
def api_registrar():
    data = request.get_json(silent=True) or {}
    cuarto_id     = data.get("cuarto_id")
    duracion      = data.get("duracion_horas")
    precio_cobrado = data.get("precio_cobrado")
    notas         = (data.get("notas") or "").strip() or None

    if not isinstance(cuarto_id, int) or duracion not in _DURACIONES_VALIDAS:
        return jsonify({"ok": False, "error": "Datos inválidos"}), 400
    if precio_cobrado is None or float(precio_cobrado) < 0:
        return jsonify({"ok": False, "error": "Precio inválido"}), 400

    precio_cobrado = float(precio_cobrado)
    modo = _modo_actual()

    with _db() as conn:
        cuarto = conn.execute(
            "SELECT * FROM cuartos WHERE id = ?", (cuarto_id,)
        ).fetchone()
        if not cuarto:
            return jsonify({"ok": False, "error": "Cuarto no encontrado"}), 404

        precio_def = float(cuarto[_PRECIO_KEY[duracion]])
        editado    = 1 if abs(precio_cobrado - precio_def) > 0.001 else 0

        ahora = datetime.now()
        cur = conn.execute(
            """INSERT INTO rentas
               (cuarto_id, fecha, hora_registro, duracion_horas,
                precio_default, precio_cobrado, notas, registrado_por, editado)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (cuarto_id,
             ahora.strftime("%Y-%m-%d"),
             ahora.strftime("%H:%M:%S"),
             duracion,
             precio_def,
             precio_cobrado,
             notas,
             modo,
             editado),
        )
        conn.commit()
        renta_id = cur.lastrowid

    descuento = f" (editado, orig=${precio_def:.0f})" if editado else ""
    log_action(
        "Renta registrada: cuarto=%d %dh $%.0f%s [%s] id=%d",
        cuarto_id, duracion, precio_cobrado, descuento, modo, renta_id,
    )
    return jsonify({"ok": True, "renta_id": renta_id})


# ── API: cancelar renta ──────────────────────────────────────

@cuartos_bp.route("/cuartos/api/cancelar/<int:renta_id>", methods=["POST"])
def api_cancelar(renta_id: int):
    data   = request.get_json(silent=True) or {}
    motivo = (data.get("motivo") or "").strip() or None
    modo   = _modo_actual()

    with _db() as conn:
        renta = conn.execute(
            "SELECT id, estado FROM rentas WHERE id=?", (renta_id,)
        ).fetchone()
        if not renta:
            return jsonify({"ok": False, "error": "Renta no encontrada"}), 404
        if renta["estado"] == "cancelado":
            return jsonify({"ok": False, "error": "Ya cancelada"}), 409

        ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """UPDATE rentas
               SET estado='cancelado', cancelado_por=?, cancelado_at=?, motivo_cancelacion=?
               WHERE id=?""",
            (modo, ahora, motivo, renta_id),
        )
        conn.commit()

    log_action(
        "Renta cancelada: id=%d por=%s motivo=%s",
        renta_id, modo, motivo or "(sin motivo)",
    )
    return jsonify({"ok": True})


# ── API: editar renta ────────────────────────────────────────

@cuartos_bp.route("/cuartos/api/editar/<int:renta_id>", methods=["POST"])
def api_editar(renta_id: int):
    data           = request.get_json(silent=True) or {}
    duracion       = data.get("duracion_horas")
    precio_cobrado = data.get("precio_cobrado")
    notas          = (data.get("notas") or "").strip() or None
    modo           = _modo_actual()
    es_admin       = modo.startswith("admin_")

    if duracion not in _DURACIONES_VALIDAS:
        return jsonify({"ok": False, "error": "Duración inválida"}), 400
    if precio_cobrado is None or float(precio_cobrado) < 0:
        return jsonify({"ok": False, "error": "Precio inválido"}), 400

    precio_cobrado = float(precio_cobrado)

    with _db() as conn:
        row = conn.execute(
            "SELECT r.*, c.precio_6h, c.precio_12h, c.precio_18h, c.precio_24h "
            "FROM rentas r JOIN cuartos c ON c.id=r.cuarto_id WHERE r.id=?",
            (renta_id,),
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "Renta no encontrada"}), 404

        if not es_admin and duracion != row["duracion_horas"]:
            return jsonify({"ok": False, "error": "Empleado no puede modificar la duración"}), 403

        precio_def = float(row[_PRECIO_KEY[duracion]])
        editado    = 1 if abs(precio_cobrado - precio_def) > 0.001 else 0

        conn.execute(
            "UPDATE rentas SET duracion_horas=?, precio_cobrado=?, notas=?, editado=?, editado_por=? WHERE id=?",
            (duracion, precio_cobrado, notas, editado, modo, renta_id),
        )
        conn.commit()

    log_action(
        "Renta editada: id=%d %dh $%.0f [%s]",
        renta_id, duracion, precio_cobrado, modo,
    )
    return jsonify({"ok": True})


# ── Historial completo ────────────────────────────────────────

@cuartos_bp.route("/cuartos/historial")
def historial():
    POR_PAGINA = 20
    pagina     = max(1, int(request.args.get("p", 1)))
    offset     = (pagina - 1) * POR_PAGINA

    filtro_fecha   = request.args.get("fecha", "")
    filtro_cuarto  = request.args.get("cuarto", "")
    filtro_estado  = request.args.get("estado", "")

    where_clauses, params = [], []
    if filtro_fecha:
        where_clauses.append("r.fecha = ?")
        params.append(filtro_fecha)
    if filtro_cuarto:
        where_clauses.append("r.cuarto_id = ?")
        params.append(filtro_cuarto)
    if filtro_estado:
        where_clauses.append("r.estado = ?")
        params.append(filtro_estado)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    with _db() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM rentas r {where_sql}", params
        ).fetchone()[0]

        rentas = [dict(r) for r in conn.execute(
            f"""SELECT r.*, c.nombre_display, c.tipo
                FROM rentas r JOIN cuartos c ON c.id=r.cuarto_id
                {where_sql}
                ORDER BY r.fecha DESC, r.hora_registro DESC
                LIMIT ? OFFSET ?""",
            params + [POR_PAGINA, offset],
        ).fetchall()]

        cuartos_lista = [dict(r) for r in conn.execute(
            "SELECT id, numero, nombre_display FROM cuartos ORDER BY numero"
        ).fetchall()]

    paginas_total = max(1, (total + POR_PAGINA - 1) // POR_PAGINA)

    return render_template(
        "cuartos_historial.html",
        rentas=rentas,
        cuartos_lista=cuartos_lista,
        pagina=pagina,
        paginas_total=paginas_total,
        total=total,
        filtro_fecha=filtro_fecha,
        filtro_cuarto=filtro_cuarto,
        filtro_estado=filtro_estado,
    )
