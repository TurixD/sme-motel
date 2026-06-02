"""
gastos.py - Módulo de gastos extras manuales (SPEC §5.3 — sin IA, Fase 1).
"""

import csv
import sqlite3
from contextlib import contextmanager
from datetime import date
from io import StringIO

from flask import Blueprint, Response, jsonify, render_template, request

from config import Config
from logger import get_logger, log_action

gastos_bp = Blueprint("gastos", __name__)
_log = get_logger()

CATEGORIAS = ["Gas", "Luz", "Agua-Pipas", "Agua-Embotellada", "Mantenimiento", "Sam's", "StarTV", "Renta", "Otro"]

_CATEGORIAS_CON_FONDO     = {"Luz": "CFE", "Renta": "Renta"}
_CATEGORIAS_PEDIR_RESERVA = {"Mantenimiento", "Otro"}


@contextmanager
def _db():
    conn = sqlite3.connect(Config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _saldo_fondo(db, fondo_id: int) -> float:
    row = db.execute(
        "SELECT COALESCE(SUM(CASE WHEN tipo='deposito' THEN monto ELSE 0 END),0)"
        "      -COALESCE(SUM(CASE WHEN tipo='retiro'   THEN monto ELSE 0 END),0) AS s"
        " FROM movimientos_fondos WHERE fondo_id=?",
        (fondo_id,),
    ).fetchone()
    return float(row["s"])


def _calcular_alertas(db) -> list[dict]:
    """
    Alerta si el gasto del mes actual en una categoría es ≥30% arriba del
    promedio mensual de los últimos 3 meses completos.
    Solo alerta si hay ≥2 meses de histórico para esa categoría.
    """
    historico_rows = db.execute("""
        SELECT categoria, strftime('%Y-%m', fecha) AS mes, SUM(monto) AS total_mes
        FROM gastos_extras
        WHERE strftime('%Y-%m', fecha) != strftime('%Y-%m', 'now', 'localtime')
          AND fecha >= date('now', 'localtime', '-92 days')
        GROUP BY categoria, mes
    """).fetchall()

    historico: dict[str, list[float]] = {}
    for r in historico_rows:
        historico.setdefault(r["categoria"], []).append(float(r["total_mes"]))

    actual_rows = db.execute("""
        SELECT categoria, SUM(monto) AS total
        FROM gastos_extras
        WHERE strftime('%Y-%m', fecha) = strftime('%Y-%m', 'now', 'localtime')
        GROUP BY categoria
    """).fetchall()

    alertas = []
    for r in actual_rows:
        meses = historico.get(r["categoria"], [])
        if len(meses) < 2:
            continue
        promedio = sum(meses) / len(meses)
        if promedio > 0 and float(r["total"]) >= promedio * 1.30:
            pct = round((float(r["total"]) / promedio - 1) * 100)
            alertas.append({
                "categoria":  r["categoria"],
                "total_mes":  float(r["total"]),
                "promedio":   round(promedio, 2),
                "pct_arriba": pct,
            })
    return alertas


# ── Página principal ──────────────────────────────────────────

@gastos_bp.route("/gastos")
def index():
    hoy         = date.today().isoformat()
    fecha_desde = request.args.get("desde", "")
    fecha_hasta = request.args.get("hasta", "")
    cat_filtro  = request.args.get("categoria", "")

    with _db() as db:
        resumen = {
            "hoy":    db.execute("SELECT COALESCE(SUM(monto),0) FROM gastos_extras WHERE fecha = ?", (hoy,)).fetchone()[0],
            "semana": db.execute("SELECT COALESCE(SUM(monto),0) FROM gastos_extras WHERE fecha >= date('now','localtime','-6 days')").fetchone()[0],
            "mes":    db.execute("SELECT COALESCE(SUM(monto),0) FROM gastos_extras WHERE strftime('%Y-%m',fecha)=strftime('%Y-%m','now','localtime')").fetchone()[0],
            "anio":   db.execute("SELECT COALESCE(SUM(monto),0) FROM gastos_extras WHERE strftime('%Y',fecha)=strftime('%Y','now','localtime')").fetchone()[0],
        }

        chart_rows = db.execute("""
            SELECT categoria, SUM(monto) AS total
            FROM gastos_extras
            WHERE strftime('%Y-%m', fecha) = strftime('%Y-%m', 'now', 'localtime')
            GROUP BY categoria ORDER BY total DESC
        """).fetchall()
        chart_data = [{"categoria": r["categoria"], "total": float(r["total"])} for r in chart_rows]

        # Historial con filtros combinables
        params: list = []
        sql = "SELECT * FROM gastos_extras WHERE 1=1"
        if fecha_desde and fecha_hasta:
            sql += " AND fecha BETWEEN ? AND ?"
            params += [fecha_desde, fecha_hasta]
        if cat_filtro:
            sql += " AND categoria = ?"
            params.append(cat_filtro)
        sql += " ORDER BY fecha DESC LIMIT 90"
        historial = [dict(r) for r in db.execute(sql, params).fetchall()]

        alertas = _calcular_alertas(db)

        fondo_reserva = db.execute(
            "SELECT id FROM fondos WHERE categoria_enlazada IS NULL AND activo=1 LIMIT 1"
        ).fetchone()
        fondo_reserva_id = fondo_reserva["id"] if fondo_reserva else None

    return render_template(
        "gastos.html",
        hoy=hoy,
        resumen=resumen,
        historial=historial,
        chart_data=chart_data,
        alertas=alertas,
        categorias=CATEGORIAS,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        cat_filtro=cat_filtro,
        fondo_reserva_id=fondo_reserva_id,
    )


# ── API: registrar ────────────────────────────────────────────

@gastos_bp.route("/gastos/registrar", methods=["POST"])
def registrar():
    data            = request.get_json(silent=True) or {}
    fecha           = data.get("fecha") or date.today().isoformat()
    categoria       = (data.get("categoria") or "").strip()
    monto           = float(data.get("monto", 0) or 0)
    descripcion     = (data.get("descripcion") or "").strip()
    descontar_fondo = bool(data.get("descontar_fondo", False))

    if categoria not in CATEGORIAS:
        return jsonify({"error": "Categoría inválida"}), 400
    if monto <= 0:
        return jsonify({"error": "El monto debe ser mayor a cero"}), 400

    with _db() as db:
        cur = db.execute(
            """INSERT INTO gastos_extras (fecha, categoria, monto, descripcion, creado_en)
               VALUES (?, ?, ?, ?, datetime('now','localtime'))""",
            (fecha, categoria, monto, descripcion),
        )
        nuevo_id = cur.lastrowid

        fondo_row      = None
        saldo_resultado = None

        if categoria in _CATEGORIAS_CON_FONDO:
            # Luz → descuento automático del fondo con categoria_enlazada='Luz'
            fondo_row = db.execute(
                "SELECT id, nombre FROM fondos WHERE categoria_enlazada=? AND activo=1 LIMIT 1",
                (categoria,),
            ).fetchone()

        elif categoria in _CATEGORIAS_PEDIR_RESERVA and descontar_fondo:
            # Mantenimiento/Otro → usuario confirmó descontar de Reserva General
            fondo_row = db.execute(
                "SELECT id, nombre FROM fondos WHERE categoria_enlazada IS NULL AND activo=1 LIMIT 1"
            ).fetchone()

        if fondo_row:
            db.execute(
                "INSERT INTO movimientos_fondos "
                "(fondo_id, fecha, tipo, monto, concepto, gasto_extra_id) "
                "VALUES (?, ?, 'retiro', ?, ?, ?)",
                (fondo_row["id"], fecha, monto, descripcion or categoria, nuevo_id),
            )
            db.execute(
                "UPDATE gastos_extras SET fondo_descontado_id=? WHERE id=?",
                (fondo_row["id"], nuevo_id),
            )
            saldo_resultado = _saldo_fondo(db, fondo_row["id"])

        db.commit()

    log_action(
        "Gasto registrado: id=%d fecha=%s cat=%s monto=$%.2f desc=%s%s",
        nuevo_id, fecha, categoria, monto, descripcion or "—",
        f" → fondo '{fondo_row['nombre']}'" if fondo_row else "",
    )

    resp: dict = {"ok": True, "id": nuevo_id}
    if fondo_row and saldo_resultado is not None:
        resp["saldo_fondo"]    = saldo_resultado
        resp["saldo_negativo"] = saldo_resultado < 0
        resp["nombre_fondo"]   = fondo_row["nombre"]
    return jsonify(resp)


# ── API: editar ───────────────────────────────────────────────

@gastos_bp.route("/gastos/<int:gasto_id>", methods=["PUT"])
def editar(gasto_id):
    data        = request.get_json(silent=True) or {}
    fecha       = (data.get("fecha") or "").strip()
    categoria   = (data.get("categoria") or "").strip()
    monto       = float(data.get("monto", 0) or 0)
    descripcion = (data.get("descripcion") or "").strip()

    if categoria not in CATEGORIAS:
        return jsonify({"error": "Categoría inválida"}), 400
    if monto <= 0:
        return jsonify({"error": "El monto debe ser mayor a cero"}), 400

    with _db() as db:
        anterior = db.execute(
            "SELECT fecha, categoria, monto FROM gastos_extras WHERE id=?", (gasto_id,)
        ).fetchone()
        if not anterior:
            return jsonify({"error": "Registro no encontrado"}), 404

        db.execute(
            "UPDATE gastos_extras SET fecha=?, categoria=?, monto=?, descripcion=? WHERE id=?",
            (fecha or anterior["fecha"], categoria, monto, descripcion, gasto_id),
        )
        db.commit()

    log_action(
        "Gasto editado: id=%d antes=%s/$%.2f → ahora=%s/$%.2f",
        gasto_id, anterior["categoria"], anterior["monto"], categoria, monto,
    )
    return jsonify({"ok": True})


# ── API: eliminar ─────────────────────────────────────────────

@gastos_bp.route("/gastos/<int:gasto_id>", methods=["DELETE"])
def eliminar(gasto_id):
    with _db() as db:
        registro = db.execute(
            "SELECT fecha, categoria, monto, fondo_descontado_id FROM gastos_extras WHERE id=?",
            (gasto_id,),
        ).fetchone()
        if not registro:
            return jsonify({"error": "Registro no encontrado"}), 404

        fondo_id = registro["fondo_descontado_id"]
        if fondo_id:
            db.execute(
                "DELETE FROM movimientos_fondos WHERE gasto_extra_id=?", (gasto_id,)
            )

        db.execute("DELETE FROM gastos_extras WHERE id=?", (gasto_id,))
        db.commit()

    log_action(
        "Gasto eliminado: id=%d fecha=%s cat=%s monto=$%.2f%s",
        gasto_id, registro["fecha"], registro["categoria"], registro["monto"],
        " (movimiento fondo revertido)" if fondo_id else "",
    )
    return jsonify({"ok": True})


# ── Exportar CSV ──────────────────────────────────────────────

@gastos_bp.route("/gastos/exportar")
def exportar():
    with _db() as db:
        rows = db.execute("SELECT * FROM gastos_extras ORDER BY fecha DESC").fetchall()

    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(["ID", "Fecha", "Categoria", "Monto", "Descripcion", "Creado En"])
    for r in rows:
        writer.writerow([r["id"], r["fecha"], r["categoria"], r["monto"],
                         r["descripcion"] or "", r["creado_en"]])

    filename = f"gastos_{date.today().isoformat()}.csv"
    return Response(
        "﻿" + buf.getvalue(),
        mimetype="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
