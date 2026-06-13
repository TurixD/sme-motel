"""
inventario.py - Módulo de inventario: CRUD productos + conteo semanal (Fase 5a).
"""

import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta

from flask import Blueprint, jsonify, render_template, request

from config import Config
from logger import get_logger, log_action

inventario_bp = Blueprint("inventario", __name__)
_log = get_logger()

_UMBRAL_DIFERENCIA_PCT  = 0.20   # 20 % de diferencia → warning
_UMBRAL_DIFERENCIA_ABS  = 3      # o ≥3 unidades de diferencia → warning
_HISTORIAL_PAGE_SIZE    = 20


@contextmanager
def _db():
    conn = sqlite3.connect(Config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _stock_sql() -> str:
    """SQL fragment que calcula stock actual de un producto dado su inventario_id."""
    return """
        COALESCE(
            (SELECT cs.cantidad
             FROM conteos_semanales cs
             WHERE cs.inventario_id = i.id
             ORDER BY cs.fecha DESC
             LIMIT 1),
            0
        )
        + COALESCE(
            (SELECT SUM(
                CASE WHEN mi.tipo = 'entrada' THEN mi.cantidad
                     ELSE -mi.cantidad END
             )
             FROM movimientos_inventario mi
             WHERE mi.inventario_id = i.id
               AND mi.fecha > COALESCE(
                    (SELECT cs2.fecha FROM conteos_semanales cs2
                     WHERE cs2.inventario_id = i.id
                     ORDER BY cs2.fecha DESC LIMIT 1),
                    '1900-01-01'
               )
            ),
            0
        )
    """


def _ultimo_conteo_sql() -> str:
    return """
        (SELECT cs.fecha FROM conteos_semanales cs
         WHERE cs.inventario_id = i.id
         ORDER BY cs.fecha DESC LIMIT 1)
    """


def _mostrar_boton_conteo() -> bool:
    hoy = date.today()
    es_fin_de_semana = hoy.weekday() >= 5
    if es_fin_de_semana:
        return True
    with _db() as conn:
        row = conn.execute(
            "SELECT MAX(fecha) as ultimo FROM conteos_semanales"
        ).fetchone()
        if not row["ultimo"]:
            return True
        ultimo = date.fromisoformat(row["ultimo"])
        return (hoy - ultimo).days >= 7


# ── Vista principal ────────────────────────────────────────────

@inventario_bp.route("/inventario")
def index():
    with _db() as conn:
        rows = conn.execute(f"""
            SELECT
                i.id,
                i.nombre,
                i.proveedor_default,
                i.unidad,
                i.stock_minimo,
                ({_stock_sql()})          AS stock_calculado,
                ({_ultimo_conteo_sql()})  AS ultimo_conteo
            FROM inventario i
            WHERE i.activo = 1
            ORDER BY i.nombre COLLATE NOCASE
        """).fetchall()

    productos = [dict(r) for r in rows]
    return render_template(
        "inventario.html",
        productos=productos,
        mostrar_conteo=_mostrar_boton_conteo(),
        hoy=date.today().isoformat(),
    )


# ── CRUD productos ─────────────────────────────────────────────

@inventario_bp.route("/inventario/productos", methods=["POST"])
def crear_producto():
    data = request.get_json(force=True)
    nombre = (data.get("nombre") or "").strip()
    if not nombre:
        return jsonify({"ok": False, "error": "Nombre requerido"}), 400

    proveedor = (data.get("proveedor_default") or "").strip() or None
    unidad = (data.get("unidad") or "").strip() or None
    stock_minimo = data.get("stock_minimo", 0)
    try:
        stock_minimo = max(0, float(stock_minimo))
    except (TypeError, ValueError):
        stock_minimo = 0

    with _db() as conn:
        existente = conn.execute(
            "SELECT id FROM inventario WHERE nombre = ? AND activo = 1",
            (nombre,)
        ).fetchone()
        if existente:
            return jsonify({"ok": False, "error": "Ya existe un producto con ese nombre"}), 409

        cur = conn.execute(
            """INSERT INTO inventario (nombre, proveedor_default, unidad, stock_minimo)
               VALUES (?, ?, ?, ?)""",
            (nombre, proveedor, unidad, stock_minimo),
        )
        conn.commit()
        pid = cur.lastrowid

    log_action(f"inventario: producto creado id={pid} nombre={nombre!r}")
    return jsonify({"ok": True, "id": pid}), 201


@inventario_bp.route("/inventario/productos/<int:pid>", methods=["PUT"])
def editar_producto(pid: int):
    data = request.get_json(force=True)
    nombre = (data.get("nombre") or "").strip()
    if not nombre:
        return jsonify({"ok": False, "error": "Nombre requerido"}), 400

    proveedor = (data.get("proveedor_default") or "").strip() or None
    unidad = (data.get("unidad") or "").strip() or None
    stock_minimo = data.get("stock_minimo", 0)
    try:
        stock_minimo = max(0, float(stock_minimo))
    except (TypeError, ValueError):
        stock_minimo = 0

    with _db() as conn:
        existente = conn.execute(
            "SELECT id FROM inventario WHERE nombre = ? AND activo = 1 AND id != ?",
            (nombre, pid)
        ).fetchone()
        if existente:
            return jsonify({"ok": False, "error": "Ya existe otro producto con ese nombre"}), 409

        conn.execute(
            """UPDATE inventario
               SET nombre=?, proveedor_default=?, unidad=?, stock_minimo=?
               WHERE id=? AND activo=1""",
            (nombre, proveedor, unidad, stock_minimo, pid),
        )
        conn.commit()

    log_action(f"inventario: producto editado id={pid} nombre={nombre!r}")
    return jsonify({"ok": True})


@inventario_bp.route("/inventario/productos/<int:pid>", methods=["DELETE"])
def eliminar_producto(pid: int):
    accion = request.args.get("accion", "eliminar")  # eliminar | desactivar

    with _db() as conn:
        tiene_movs = conn.execute(
            "SELECT 1 FROM movimientos_inventario WHERE inventario_id=? LIMIT 1",
            (pid,)
        ).fetchone()
        tiene_conteos = conn.execute(
            "SELECT 1 FROM conteos_semanales WHERE inventario_id=? LIMIT 1",
            (pid,)
        ).fetchone()

        if (tiene_movs or tiene_conteos) and accion != "desactivar":
            return jsonify({
                "ok": False,
                "tiene_historial": True,
                "error": "El producto tiene historial. Usa accion=desactivar para ocultarlo.",
            }), 409

        if accion == "desactivar":
            conn.execute("UPDATE inventario SET activo=0 WHERE id=?", (pid,))
            conn.commit()
            log_action(f"inventario: producto desactivado id={pid}")
            return jsonify({"ok": True, "accion": "desactivado"})

        conn.execute("DELETE FROM inventario WHERE id=? AND activo=1", (pid,))
        conn.commit()

    log_action(f"inventario: producto eliminado id={pid}")
    return jsonify({"ok": True, "accion": "eliminado"})


# ── Historial de movimientos ───────────────────────────────────

@inventario_bp.route("/inventario/productos/<int:pid>/movimientos")
def historial_movimientos(pid: int):
    offset = max(0, int(request.args.get("offset", 0)))

    with _db() as conn:
        producto = conn.execute(
            "SELECT id, nombre FROM inventario WHERE id=?", (pid,)
        ).fetchone()
        if not producto:
            return jsonify({"ok": False, "error": "Producto no encontrado"}), 404

        total_movs = conn.execute(
            "SELECT COUNT(*) FROM movimientos_inventario WHERE inventario_id=?", (pid,)
        ).fetchone()[0]
        total_conteos = conn.execute(
            "SELECT COUNT(*) FROM conteos_semanales WHERE inventario_id=?", (pid,)
        ).fetchone()[0]

        movs = conn.execute(
            """SELECT fecha, tipo, cantidad, descripcion, origen, notas
               FROM movimientos_inventario
               WHERE inventario_id=?
               ORDER BY fecha DESC, id DESC
               LIMIT ? OFFSET ?""",
            (pid, _HISTORIAL_PAGE_SIZE, offset),
        ).fetchall()

        conteos = conn.execute(
            """SELECT fecha, 'conteo' as tipo, cantidad, notas
               FROM conteos_semanales
               WHERE inventario_id=?
               ORDER BY fecha DESC
               LIMIT ? OFFSET ?""",
            (pid, _HISTORIAL_PAGE_SIZE, offset),
        ).fetchall()

        # Combinar y ordenar por fecha desc
        entradas = []
        for r in movs:
            entradas.append({
                "fecha": r["fecha"],
                "tipo": r["tipo"],
                "cantidad": r["cantidad"],
                "descripcion": r["descripcion"] or r["notas"] or "",
                "origen": r["origen"] or "",
            })
        for r in conteos:
            entradas.append({
                "fecha": r["fecha"],
                "tipo": "conteo",
                "cantidad": r["cantidad"],
                "descripcion": r["notas"] or "",
                "origen": "conteo_semanal",
            })
        entradas.sort(key=lambda x: x["fecha"], reverse=True)
        entradas = entradas[:_HISTORIAL_PAGE_SIZE]

    return jsonify({
        "ok": True,
        "producto": dict(producto),
        "total": total_movs + total_conteos,
        "offset": offset,
        "items": entradas,
        "hay_mas": (total_movs + total_conteos) > offset + _HISTORIAL_PAGE_SIZE,
    })


# ── Conteo semanal ─────────────────────────────────────────────

@inventario_bp.route("/inventario/conteo")
def vista_conteo():
    with _db() as conn:
        rows = conn.execute(f"""
            SELECT
                i.id,
                i.nombre,
                i.unidad,
                ({_stock_sql()})          AS stock_calculado,
                ({_ultimo_conteo_sql()})  AS ultimo_conteo
            FROM inventario i
            WHERE i.activo = 1
            ORDER BY i.nombre COLLATE NOCASE
        """).fetchall()

    productos = [dict(r) for r in rows]
    return render_template(
        "inventario_conteo.html",
        productos=productos,
        hoy=date.today().isoformat(),
    )


@inventario_bp.route("/inventario/conteo", methods=["POST"])
def guardar_conteo():
    data = request.get_json(force=True)
    items = data.get("items", [])
    notas_globales = (data.get("notas") or "").strip() or None
    fecha = data.get("fecha") or date.today().isoformat()

    if not items:
        return jsonify({"ok": False, "error": "Sin items"}), 400

    errores = []
    for item in items:
        try:
            if float(item.get("cantidad", -1)) < 0:
                errores.append(f"Cantidad negativa para producto {item.get('id')}")
        except (TypeError, ValueError):
            errores.append(f"Cantidad inválida para producto {item.get('id')}")
    if errores:
        return jsonify({"ok": False, "error": "; ".join(errores)}), 400

    diferencias = 0
    with _db() as conn:
        for item in items:
            pid    = int(item["id"])
            cant   = float(item["cantidad"])
            esp    = float(item.get("esperado", 0) or 0)
            diff   = abs(cant - esp)
            if esp > 0 and (diff / esp >= _UMBRAL_DIFERENCIA_PCT or diff >= _UMBRAL_DIFERENCIA_ABS):
                diferencias += 1
            elif diff >= _UMBRAL_DIFERENCIA_ABS:
                diferencias += 1

            conn.execute(
                """INSERT INTO conteos_semanales (fecha, inventario_id, cantidad, notas)
                   VALUES (?, ?, ?, ?)""",
                (fecha, pid, cant, notas_globales),
            )
        conn.commit()

    log_action(f"inventario: conteo semanal guardado fecha={fecha} items={len(items)} diferencias={diferencias}")
    return jsonify({
        "ok": True,
        "contados": len(items),
        "diferencias": diferencias,
    })


# ── API matches aprendidos (Sub-fase 5C) ──────────────────────

@inventario_bp.route("/inventario/api/matches")
def api_matches():
    with _db() as conn:
        rows = conn.execute("""
            SELECT ma.id, ma.sku_sams, ma.texto_ticket, ma.inventario_id,
                   i.nombre AS producto_nombre, ma.veces_confirmado,
                   ma.primera_vez, ma.ultima_vez
            FROM matches_aprendidos ma
            JOIN inventario i ON i.id = ma.inventario_id
            ORDER BY ma.ultima_vez DESC
        """).fetchall()
    return jsonify([dict(r) for r in rows])


@inventario_bp.route("/inventario/api/matches/<int:mid>", methods=["PUT"])
def actualizar_match(mid: int):
    data = request.get_json(force=True)
    try:
        inv_id = int(data.get("inventario_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "inventario_id inválido"}), 400

    with _db() as conn:
        match = conn.execute(
            "SELECT sku_sams FROM matches_aprendidos WHERE id=?", (mid,)
        ).fetchone()
        if not match:
            return jsonify({"ok": False, "error": "Match no encontrado"}), 404

        existe_prod = conn.execute(
            "SELECT id FROM inventario WHERE id=? AND activo=1", (inv_id,)
        ).fetchone()
        if not existe_prod:
            return jsonify({"ok": False, "error": "Producto no encontrado o inactivo"}), 404

        conn.execute(
            "UPDATE matches_aprendidos SET inventario_id=?, ultima_vez=datetime('now','localtime') WHERE id=?",
            (inv_id, mid),
        )
        conn.commit()

    log_action(f"matches_aprendidos: actualizado id={mid} sku={match['sku_sams']} → inventario_id={inv_id}")
    return jsonify({"ok": True})


@inventario_bp.route("/inventario/api/matches/<int:mid>", methods=["DELETE"])
def borrar_match(mid: int):
    with _db() as conn:
        match = conn.execute(
            "SELECT sku_sams FROM matches_aprendidos WHERE id=?", (mid,)
        ).fetchone()
        if not match:
            return jsonify({"ok": False, "error": "Match no encontrado"}), 404
        conn.execute("DELETE FROM matches_aprendidos WHERE id=?", (mid,))
        conn.commit()

    log_action(f"matches_aprendidos: borrado id={mid} sku={match['sku_sams']}")
    return jsonify({"ok": True})


# ── API stock JSON ─────────────────────────────────────────────

@inventario_bp.route("/inventario/api/stock")
def api_stock():
    with _db() as conn:
        rows = conn.execute(f"""
            SELECT
                i.id,
                i.nombre,
                i.unidad,
                i.stock_minimo,
                ({_stock_sql()})          AS stock_calculado,
                ({_ultimo_conteo_sql()})  AS ultimo_conteo
            FROM inventario i
            WHERE i.activo = 1
            ORDER BY i.nombre COLLATE NOCASE
        """).fetchall()
    return jsonify([dict(r) for r in rows])
