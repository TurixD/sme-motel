"""
fondos.py - Módulo de fondos múltiples (SPEC §5.6 — Fase 2).
"""

import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta

from flask import Blueprint, jsonify, render_template, request

from config import Config
from logger import get_logger, log_action

fondos_bp = Blueprint("fondos", __name__)
_log = get_logger()


@contextmanager
def _db():
    conn = sqlite3.connect(Config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _lunes_actual() -> date:
    hoy = date.today()
    return hoy - timedelta(days=hoy.weekday())


def _saldo(db, fondo_id: int) -> float:
    row = db.execute(
        """SELECT
               COALESCE(SUM(CASE WHEN tipo='deposito' THEN monto ELSE 0 END), 0) -
               COALESCE(SUM(CASE WHEN tipo='retiro'   THEN monto ELSE 0 END), 0) AS s
           FROM movimientos_fondos WHERE fondo_id = ?""",
        (fondo_id,),
    ).fetchone()
    return float(row["s"])


def _cerrar_meses_pendientes(db, fondo_id: int, meta_mensual: float) -> None:
    """Inserta en metas_fondo todos los meses sin cerrar desde el primer movimiento."""
    primer = db.execute(
        "SELECT MIN(fecha) AS f FROM movimientos_fondos WHERE fondo_id=?", (fondo_id,)
    ).fetchone()
    if not primer or not primer["f"]:
        return

    hoy = date.today()
    mes_actual = date(hoy.year, hoy.month, 1)
    mes = date.fromisoformat(primer["f"]).replace(day=1)

    while mes < mes_actual:
        existe = db.execute(
            "SELECT id FROM metas_fondo WHERE fondo_id=? AND mes=? AND anio=?",
            (fondo_id, mes.month, mes.year),
        ).fetchone()
        if not existe:
            sig = (
                date(mes.year + 1, 1, 1)
                if mes.month == 12
                else date(mes.year, mes.month + 1, 1)
            )
            acum = db.execute(
                "SELECT COALESCE(SUM(monto), 0) AS t FROM movimientos_fondos "
                "WHERE fondo_id=? AND tipo='deposito' AND fecha>=? AND fecha<?",
                (fondo_id, mes.isoformat(), sig.isoformat()),
            ).fetchone()["t"]
            db.execute(
                "INSERT OR IGNORE INTO metas_fondo "
                "(fondo_id, mes, anio, meta_monto, acumulado_real, meta_lograda) "
                "VALUES (?,?,?,?,?,?)",
                (
                    fondo_id, mes.month, mes.year, meta_mensual, acum,
                    1 if (meta_mensual > 0 and acum >= meta_mensual) else 0,
                ),
            )
        mes = (
            date(mes.year + 1, 1, 1)
            if mes.month == 12
            else date(mes.year, mes.month + 1, 1)
        )


def _fmt(n: float) -> str:
    """Formatea un saldo como '$1,234' o '-$1,234'."""
    sign = "-" if n < 0 else ""
    return f"{sign}${abs(n):,.0f}"


# ── Página principal ──────────────────────────────────────────

@fondos_bp.route("/fondos")
def index():
    lunes   = _lunes_actual()
    domingo = lunes + timedelta(days=6)
    hoy     = date.today().isoformat()

    with _db() as db:
        fondos_rows = db.execute(
            "SELECT * FROM fondos WHERE activo=1 ORDER BY id"
        ).fetchall()

        fondos = []
        for f in fondos_rows:
            fid  = f["id"]
            meta = float(f["meta_mensual"] or 0)

            _cerrar_meses_pendientes(db, fid, meta)
            db.commit()

            stats = db.execute(
                """SELECT
                       COALESCE(SUM(CASE WHEN tipo='deposito' THEN monto ELSE 0 END),0) AS dep,
                       COALESCE(SUM(CASE WHEN tipo='retiro'   THEN monto ELSE 0 END),0) AS ret
                   FROM movimientos_fondos WHERE fondo_id=?""",
                (fid,),
            ).fetchone()

            saldo    = float(stats["dep"]) - float(stats["ret"])
            progreso = min(100, int(saldo / meta * 100)) if (meta > 0 and saldo > 0) else 0

            movs = [
                dict(m) for m in db.execute(
                    "SELECT * FROM movimientos_fondos WHERE fondo_id=? "
                    "ORDER BY fecha DESC, creado_en DESC LIMIT 10",
                    (fid,),
                ).fetchall()
            ]

            metas_rows = db.execute(
                "SELECT meta_lograda FROM metas_fondo WHERE fondo_id=? "
                "ORDER BY anio DESC, mes DESC LIMIT 6",
                (fid,),
            ).fetchall()
            meses_logrados = sum(1 for m in metas_rows if m["meta_lograda"])
            meses_totales  = len(metas_rows)

            fondos.append({
                **dict(f),
                "saldo":          saldo,
                "saldo_display":  _fmt(saldo),
                "total_dep":      float(stats["dep"]),
                "total_ret":      float(stats["ret"]),
                "movimientos":    movs,
                "meses_logrados": meses_logrados,
                "meses_totales":  meses_totales,
                "saldo_negativo": saldo < 0,
                "progreso_pct":   progreso,
            })

        ap_rows = db.execute(
            """SELECT f.id, f.nombre, f.aporte_periodico, f.color
               FROM fondos f
               WHERE f.activo=1 AND f.frecuencia_aporte='semanal' AND f.pregunta_antes=1
               AND NOT EXISTS (
                   SELECT 1 FROM movimientos_fondos m
                   WHERE m.fondo_id = f.id
                     AND m.fecha BETWEEN ? AND ?
                     AND m.tipo IN ('deposito','saltado')
               )""",
            (lunes.isoformat(), domingo.isoformat()),
        ).fetchall()

        aportes_pendientes = []
        for ap in ap_rows:
            ap_dict = dict(ap)
            ap_dict["saldo"]         = next((f["saldo"] for f in fondos if f["id"] == ap["id"]), 0.0)
            ap_dict["saldo_display"] = _fmt(ap_dict["saldo"])
            aportes_pendientes.append(ap_dict)

    return render_template(
        "fondos.html",
        fondos=fondos,
        aportes_pendientes=aportes_pendientes,
        hoy=hoy,
    )


# ── API: saldo en tiempo real ─────────────────────────────────

@fondos_bp.route("/fondos/<int:fondo_id>/saldo")
def api_saldo(fondo_id):
    with _db() as db:
        fondo = db.execute(
            "SELECT nombre FROM fondos WHERE id=? AND activo=1", (fondo_id,)
        ).fetchone()
        if not fondo:
            return jsonify({"ok": False, "error": "Fondo no encontrado"}), 404
        saldo = _saldo(db, fondo_id)
    return jsonify({"ok": True, "saldo": saldo, "nombre": fondo["nombre"], "saldo_negativo": saldo < 0})


# ── API: movimientos de un fondo (para carga dinámica) ───────

@fondos_bp.route("/fondos/<int:fondo_id>/movimientos")
def api_movimientos(fondo_id):
    with _db() as db:
        movs = [
            dict(m) for m in db.execute(
                "SELECT * FROM movimientos_fondos WHERE fondo_id=? "
                "ORDER BY fecha DESC, creado_en DESC LIMIT 10",
                (fondo_id,),
            ).fetchall()
        ]
        count = db.execute(
            "SELECT COUNT(*) AS n FROM movimientos_fondos WHERE fondo_id=?", (fondo_id,)
        ).fetchone()["n"]
    return jsonify({"ok": True, "movimientos": movs, "count": count})


# ── API: depósito manual ──────────────────────────────────────

@fondos_bp.route("/fondos/<int:fondo_id>/depositar", methods=["POST"])
def depositar(fondo_id):
    data     = request.get_json(silent=True) or {}
    monto    = float(data.get("monto") or 0)
    concepto = (data.get("concepto") or "").strip()
    fecha    = (data.get("fecha") or "").strip() or date.today().isoformat()

    if monto <= 0:
        return jsonify({"ok": False, "error": "El monto debe ser mayor a cero"}), 400

    with _db() as db:
        fondo = db.execute(
            "SELECT nombre FROM fondos WHERE id=? AND activo=1", (fondo_id,)
        ).fetchone()
        if not fondo:
            return jsonify({"ok": False, "error": "Fondo no encontrado"}), 404

        db.execute(
            "INSERT INTO movimientos_fondos (fondo_id, fecha, tipo, monto, concepto) "
            "VALUES (?, ?, 'deposito', ?, ?)",
            (fondo_id, fecha, monto, concepto or "Depósito manual"),
        )
        db.commit()
        saldo = _saldo(db, fondo_id)

    log_action("Fondo '%s': depósito $%.2f", fondo["nombre"], monto)
    return jsonify({"ok": True, "saldo": saldo, "saldo_display": _fmt(saldo), "saldo_negativo": saldo < 0})


# ── API: retiro manual ────────────────────────────────────────

@fondos_bp.route("/fondos/<int:fondo_id>/retirar", methods=["POST"])
def retirar(fondo_id):
    data     = request.get_json(silent=True) or {}
    monto    = float(data.get("monto") or 0)
    concepto = (data.get("concepto") or "").strip()
    fecha    = (data.get("fecha") or "").strip() or date.today().isoformat()

    if monto <= 0:
        return jsonify({"ok": False, "error": "El monto debe ser mayor a cero"}), 400

    with _db() as db:
        fondo = db.execute(
            "SELECT nombre FROM fondos WHERE id=? AND activo=1", (fondo_id,)
        ).fetchone()
        if not fondo:
            return jsonify({"ok": False, "error": "Fondo no encontrado"}), 404

        db.execute(
            "INSERT INTO movimientos_fondos (fondo_id, fecha, tipo, monto, concepto) "
            "VALUES (?, ?, 'retiro', ?, ?)",
            (fondo_id, fecha, monto, concepto or "Retiro manual"),
        )
        db.commit()
        saldo = _saldo(db, fondo_id)

    log_action("Fondo '%s': retiro $%.2f (nuevo saldo: $%.2f)", fondo["nombre"], monto, saldo)
    return jsonify({"ok": True, "saldo": saldo, "saldo_display": _fmt(saldo), "saldo_negativo": saldo < 0})


# ── API: aporte semanal ───────────────────────────────────────

@fondos_bp.route("/fondos/api/aporte", methods=["POST"])
def api_aporte():
    data     = request.get_json(silent=True) or {}
    fondo_id = data.get("fondo_id")
    accion   = (data.get("accion") or "").strip()
    monto    = float(data.get("monto") or 0)
    razon    = (data.get("razon") or "").strip()

    if not fondo_id or accion not in ("confirmar", "saltar"):
        return jsonify({"ok": False, "error": "Parámetros inválidos"}), 400

    lunes = _lunes_actual().isoformat()

    with _db() as db:
        fondo = db.execute(
            "SELECT nombre, aporte_periodico FROM fondos WHERE id=? AND activo=1", (fondo_id,)
        ).fetchone()
        if not fondo:
            return jsonify({"ok": False, "error": "Fondo no encontrado"}), 404

        if accion == "confirmar":
            if monto <= 0:
                return jsonify({"ok": False, "error": "El monto debe ser mayor a cero"}), 400
            db.execute(
                "INSERT INTO movimientos_fondos (fondo_id, fecha, tipo, monto, concepto) "
                "VALUES (?, ?, 'deposito', ?, 'Aporte semanal')",
                (fondo_id, lunes, monto),
            )
            db.commit()
            saldo = _saldo(db, fondo_id)
            log_action("Aporte semanal confirmado: '%s' $%.2f", fondo["nombre"], monto)
            return jsonify({
                "ok": True, "saldo": saldo,
                "saldo_display": _fmt(saldo), "saldo_negativo": saldo < 0,
            })
        else:
            db.execute(
                "INSERT INTO movimientos_fondos "
                "(fondo_id, fecha, tipo, monto, concepto, razon_saltado) "
                "VALUES (?, ?, 'saltado', 0, 'Aporte semanal saltado', ?)",
                (fondo_id, lunes, razon or None),
            )
            db.commit()
            log_action("Aporte semanal saltado: '%s' razón: %s", fondo["nombre"], razon or "—")
            return jsonify({"ok": True})


# ── API: vincular gasto ya registrado a un fondo ──────────────

@fondos_bp.route("/fondos/api/descontar-gasto", methods=["POST"])
def api_descontar_gasto():
    data     = request.get_json(silent=True) or {}
    gasto_id = data.get("gasto_id")
    fondo_id = data.get("fondo_id")

    if not gasto_id or not fondo_id:
        return jsonify({"ok": False, "error": "Faltan parámetros"}), 400

    with _db() as db:
        gasto = db.execute(
            "SELECT monto, categoria, fecha FROM gastos_extras WHERE id=?", (gasto_id,)
        ).fetchone()
        if not gasto:
            return jsonify({"ok": False, "error": "Gasto no encontrado"}), 404

        fondo = db.execute(
            "SELECT nombre FROM fondos WHERE id=? AND activo=1", (fondo_id,)
        ).fetchone()
        if not fondo:
            return jsonify({"ok": False, "error": "Fondo no encontrado"}), 404

        db.execute(
            "INSERT INTO movimientos_fondos "
            "(fondo_id, fecha, tipo, monto, concepto, gasto_extra_id) "
            "VALUES (?, ?, 'retiro', ?, ?, ?)",
            (fondo_id, gasto["fecha"], float(gasto["monto"]),
             f"Gasto: {gasto['categoria']}", gasto_id),
        )
        db.execute(
            "UPDATE gastos_extras SET fondo_descontado_id=? WHERE id=?", (fondo_id, gasto_id)
        )
        db.commit()
        saldo = _saldo(db, fondo_id)

    log_action(
        "Gasto id=%d ($%.2f) descontado del fondo '%s' (saldo: $%.2f)",
        gasto_id, float(gasto["monto"]), fondo["nombre"], saldo,
    )
    return jsonify({"ok": True, "saldo": saldo, "saldo_display": _fmt(saldo), "saldo_negativo": saldo < 0})
