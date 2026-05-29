"""
ingresos.py - Módulo de ingresos diarios (SPEC §5.2).
"""

import csv
import sqlite3
from contextlib import contextmanager
from datetime import date
from io import StringIO

from flask import Blueprint, Response, jsonify, render_template, request

from config import Config
from logger import get_logger, log_action

ingresos_bp = Blueprint("ingresos", __name__)
_log = get_logger()


@contextmanager
def _db():
    conn = sqlite3.connect(Config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _calcular(efectivo: float, tarjeta: float, transferencia: float) -> tuple[float, float]:
    comision = round(tarjeta * 0.04, 2)
    total    = round(efectivo + tarjeta + transferencia - comision, 2)
    return comision, total


# ── Página principal ──────────────────────────────────────────

@ingresos_bp.route("/ingresos")
def index():
    hoy         = date.today().isoformat()
    fecha_desde = request.args.get("desde", "")
    fecha_hasta = request.args.get("hasta", "")

    with _db() as db:
        registro_hoy = db.execute(
            "SELECT * FROM ingresos_diarios WHERE fecha = ? LIMIT 1", (hoy,)
        ).fetchone()
        registro_hoy = dict(registro_hoy) if registro_hoy else None

        resumen = {
            "hoy":    db.execute("SELECT COALESCE(SUM(total_neto),0) FROM ingresos_diarios WHERE fecha = ?", (hoy,)).fetchone()[0],
            "semana": db.execute("SELECT COALESCE(SUM(total_neto),0) FROM ingresos_diarios WHERE fecha >= date('now','localtime','-6 days')").fetchone()[0],
            "mes":    db.execute("SELECT COALESCE(SUM(total_neto),0) FROM ingresos_diarios WHERE strftime('%Y-%m',fecha)=strftime('%Y-%m','now','localtime')").fetchone()[0],
            "anio":   db.execute("SELECT COALESCE(SUM(total_neto),0) FROM ingresos_diarios WHERE strftime('%Y',fecha)=strftime('%Y','now','localtime')").fetchone()[0],
        }

        if fecha_desde and fecha_hasta:
            rows = db.execute(
                "SELECT * FROM ingresos_diarios WHERE fecha BETWEEN ? AND ? ORDER BY fecha DESC",
                (fecha_desde, fecha_hasta),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM ingresos_diarios ORDER BY fecha DESC LIMIT 90"
            ).fetchall()
        historial = [dict(r) for r in rows]

        chart_rows = db.execute(
            "SELECT fecha, total_neto FROM ingresos_diarios "
            "WHERE fecha >= date('now','localtime','-29 days') ORDER BY fecha"
        ).fetchall()
        chart_data = [{"fecha": r["fecha"], "total": float(r["total_neto"])} for r in chart_rows]

    return render_template(
        "ingresos.html",
        hoy=hoy,
        registro_hoy=registro_hoy,
        resumen=resumen,
        historial=historial,
        chart_data=chart_data,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
    )


# ── API: registrar (nuevo / sumar / reemplazar) ───────────────

@ingresos_bp.route("/ingresos/registrar", methods=["POST"])
def registrar():
    data    = request.get_json(silent=True) or {}
    fecha   = data.get("fecha") or date.today().isoformat()
    efect   = float(data.get("monto_efectivo", 0) or 0)
    tarj    = float(data.get("monto_tarjeta",  0) or 0)
    transf  = float(data.get("monto_transferencia", 0) or 0)
    notas   = (data.get("notas") or "").strip()
    modo    = data.get("modo", "nuevo")

    comision, total = _calcular(efect, tarj, transf)

    with _db() as db:
        existente = db.execute(
            "SELECT * FROM ingresos_diarios WHERE fecha = ? LIMIT 1", (fecha,)
        ).fetchone()

        # Si ya existe y el modo es "nuevo", devolver el registro para que el frontend pregunte
        if existente and modo == "nuevo":
            return jsonify({"existe": True, "registro": dict(existente)})

        if modo == "sumar" and existente:
            ne   = existente["monto_efectivo"]      + efect
            nt   = existente["monto_tarjeta"]        + tarj
            ntr  = existente["monto_transferencia"]  + transf
            nc, ntotal = _calcular(ne, nt, ntr)
            notas_f = "\n".join(filter(None, [existente["notas"], notas])).strip()
            db.execute(
                """UPDATE ingresos_diarios
                   SET monto_efectivo=?, monto_tarjeta=?, monto_transferencia=?,
                       comision_tarjeta=?, total_neto=?, notas=?
                   WHERE id=?""",
                (ne, nt, ntr, nc, ntotal, notas_f, existente["id"]),
            )
            db.commit()
            log_action(
                "Ingreso sumado: fecha=%s +efectivo=%.2f +tarjeta=%.2f +transf=%.2f → total=$%.2f",
                fecha, efect, tarj, transf, ntotal,
            )
            return jsonify({"ok": True, "total_neto": ntotal, "modo": "sumado"})

        if modo == "reemplazar" and existente:
            anterior = existente["total_neto"]
            db.execute(
                """UPDATE ingresos_diarios
                   SET monto_efectivo=?, monto_tarjeta=?, monto_transferencia=?,
                       comision_tarjeta=?, total_neto=?, notas=?
                   WHERE id=?""",
                (efect, tarj, transf, comision, total, notas, existente["id"]),
            )
            db.commit()
            log_action(
                "Ingreso reemplazado: fecha=%s antes=$%.2f → ahora=$%.2f",
                fecha, anterior, total,
            )
            return jsonify({"ok": True, "total_neto": total, "modo": "reemplazado"})

        # Nuevo registro
        db.execute(
            """INSERT INTO ingresos_diarios
               (fecha, monto_efectivo, monto_tarjeta, monto_transferencia,
                comision_tarjeta, total_neto, notas, creado_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))""",
            (fecha, efect, tarj, transf, comision, total, notas),
        )
        db.commit()
        log_action(
            "Ingreso registrado: fecha=%s efectivo=%.2f tarjeta=%.2f transf=%.2f total=$%.2f",
            fecha, efect, tarj, transf, total,
        )

    return jsonify({"ok": True, "total_neto": total, "modo": "nuevo"})


# ── API: editar registro del historial ────────────────────────

@ingresos_bp.route("/ingresos/<int:registro_id>", methods=["PUT"])
def editar(registro_id):
    data   = request.get_json(silent=True) or {}
    efect  = float(data.get("monto_efectivo", 0) or 0)
    tarj   = float(data.get("monto_tarjeta",  0) or 0)
    transf = float(data.get("monto_transferencia", 0) or 0)
    notas  = (data.get("notas") or "").strip()
    comision, total = _calcular(efect, tarj, transf)

    with _db() as db:
        anterior = db.execute(
            "SELECT fecha, total_neto FROM ingresos_diarios WHERE id=?", (registro_id,)
        ).fetchone()
        if not anterior:
            return jsonify({"error": "Registro no encontrado"}), 404

        db.execute(
            """UPDATE ingresos_diarios
               SET monto_efectivo=?, monto_tarjeta=?, monto_transferencia=?,
                   comision_tarjeta=?, total_neto=?, notas=?
               WHERE id=?""",
            (efect, tarj, transf, comision, total, notas, registro_id),
        )
        db.commit()
        log_action(
            "Ingreso editado: id=%d fecha=%s antes=$%.2f → después=$%.2f",
            registro_id, anterior["fecha"], anterior["total_neto"], total,
        )

    return jsonify({"ok": True, "total_neto": total})


# ── API: eliminar ─────────────────────────────────────────────

@ingresos_bp.route("/ingresos/<int:registro_id>", methods=["DELETE"])
def eliminar(registro_id):
    with _db() as db:
        registro = db.execute(
            "SELECT fecha, total_neto FROM ingresos_diarios WHERE id=?", (registro_id,)
        ).fetchone()
        if not registro:
            return jsonify({"error": "Registro no encontrado"}), 404

        db.execute("DELETE FROM ingresos_diarios WHERE id=?", (registro_id,))
        db.commit()
        log_action(
            "Ingreso eliminado: id=%d fecha=%s total=$%.2f",
            registro_id, registro["fecha"], registro["total_neto"],
        )

    return jsonify({"ok": True})


# ── Exportar CSV ──────────────────────────────────────────────

@ingresos_bp.route("/ingresos/exportar")
def exportar():
    with _db() as db:
        rows = db.execute(
            "SELECT * FROM ingresos_diarios ORDER BY fecha DESC"
        ).fetchall()

    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(["ID", "Fecha", "Efectivo", "Tarjeta", "Transferencia",
                     "Comision", "Total Neto", "Notas"])
    for r in rows:
        writer.writerow([
            r["id"], r["fecha"],
            r["monto_efectivo"], r["monto_tarjeta"], r["monto_transferencia"],
            r["comision_tarjeta"], r["total_neto"], r["notas"] or "",
        ])

    filename = f"ingresos_{date.today().isoformat()}.csv"
    return Response(
        "﻿" + buf.getvalue(),   # BOM para que Excel detecte UTF-8
        mimetype="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
