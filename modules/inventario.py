"""
inventario.py - Módulo de inventario: CRUD productos + conteo semanal (Fase 5a).
"""

import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from math import ceil

from flask import Blueprint, jsonify, make_response, redirect, render_template, request

from config import Config
from logger import get_logger, log_action
from modules.auth import _get_modo, solo_admin

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
    if not (_get_modo() or "empleado").startswith("admin_"):
        return redirect("/inventario/conteo")
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
        es_sabado=date.today().weekday() == 5,   # lista de compra: solo sábados
        hoy=date.today().isoformat(),
    )


# ── CRUD productos ─────────────────────────────────────────────

@inventario_bp.route("/inventario/productos", methods=["POST"])
@solo_admin
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
@solo_admin
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
@solo_admin
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
@solo_admin
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
    data = request.get_json(silent=True) or {}
    items = data.get("items", [])
    notas_globales = (data.get("notas") or "").strip() or None
    fecha = data.get("fecha") or date.today().isoformat()

    if not items:
        return jsonify({"ok": False, "error": "Sin items"}), 400
    try:
        date.fromisoformat(fecha)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Fecha inválida"}), 400

    diferencias = 0
    with _db() as conn:
        validos = {r["id"] for r in conn.execute("SELECT id FROM inventario WHERE activo=1").fetchall()}

        # Validar todos los items antes de escribir nada
        errores = []
        limpios = []
        for item in items:
            try:
                pid = int(item["id"])
            except (KeyError, TypeError, ValueError):
                errores.append(f"Producto inválido: {item.get('id')}")
                continue
            if pid not in validos:
                errores.append(f"Producto inexistente: {pid}")
                continue
            try:
                cant = float(item["cantidad"])
            except (KeyError, TypeError, ValueError):
                errores.append(f"Cantidad inválida para producto {pid}")
                continue
            if cant < 0:
                errores.append(f"Cantidad negativa para producto {pid}")
                continue
            try:
                esp = float(item.get("esperado", 0) or 0)
            except (TypeError, ValueError):
                esp = 0.0
            limpios.append((pid, cant, esp))
        if errores:
            return jsonify({"ok": False, "error": "; ".join(errores)}), 400

        for pid, cant, esp in limpios:
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
@solo_admin
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
@solo_admin
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
@solo_admin
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


# ── Lista de compra: consumo estimado + cantidad sugerida ──────

_SIN_PROVEEDOR = "Sin proveedor"
_CONSUMO_MAX_INTERVALOS = 8   # cuántos intervalos recientes promediar


def _consumo_semanal_por_producto(conn) -> dict:
    """Estima el consumo semanal de cada producto a partir del historial de
    conteos_semanales. En un intervalo entre dos conteos:
        gastado = cant_previa + entradas_registradas − cant_actual
    Solo cuenta intervalos con gastado >= 0 (los negativos = el stock subió, o
    sea hubo una compra no registrada → no es señal limpia de consumo).
    Devuelve {inventario_id: consumo_semanal_float} solo para los que tienen
    al menos un intervalo válido. Se topa a 2× el mínimo para acotar ruido."""
    filas = conn.execute("""
        SELECT inventario_id, fecha, AVG(cantidad) AS cantidad
        FROM conteos_semanales
        GROUP BY inventario_id, fecha
        ORDER BY inventario_id, fecha
    """).fetchall()

    series: dict[int, list] = {}
    for r in filas:
        series.setdefault(r["inventario_id"], []).append((r["fecha"], r["cantidad"]))

    consumo = {}
    for inv_id, serie in series.items():
        if len(serie) < 2:
            continue
        intervalos = []  # (consumo_semanal, peso_en_semanas)
        for (d_prev, c_prev), (d_curr, c_curr) in zip(serie, serie[1:]):
            try:
                dias = (date.fromisoformat(d_curr) - date.fromisoformat(d_prev)).days
            except (TypeError, ValueError):
                continue
            if dias <= 0:
                continue
            entradas = conn.execute(
                "SELECT COALESCE(SUM(cantidad),0) FROM movimientos_inventario "
                "WHERE inventario_id=? AND tipo='entrada' AND fecha > ? AND fecha <= ?",
                (inv_id, d_prev, d_curr),
            ).fetchone()[0]
            gastado = c_prev + (entradas or 0) - c_curr
            if gastado < 0:
                continue
            semanas = dias / 7.0
            intervalos.append((gastado / semanas, semanas))
        if not intervalos:
            continue
        intervalos = intervalos[-_CONSUMO_MAX_INTERVALOS:]
        num = sum(cs * w for cs, w in intervalos)
        den = sum(w for _, w in intervalos)
        consumo[inv_id] = (num / den) if den else 0.0

    return consumo


def calcular_lista_compra(conn, semanas: int = 1) -> dict:
    """Lista de compra para cubrir `semanas` semanas, agrupada por proveedor.

    Por producto (activo, con stock_minimo > 0):
        objetivo = consumo_semanal × semanas + stock_minimo
        comprar  = ceil(objetivo − stock_actual)   (se incluye solo si > 0)

    Fuente del consumo por producto:
      - 'historial': medido de sus propios conteos.
      - 'estimado' : no tiene señal propia → se usa la razón consumo/mínimo
                     promedio del negocio (de los productos que sí tienen).
      - 'minimo'   : no hay ningún historial en el negocio → solo repone al
                     mínimo (no escala por semanas).
    """
    semanas = max(1, int(semanas or 1))
    consumo_medido = _consumo_semanal_por_producto(conn)

    rows = conn.execute(f"""
        SELECT i.id, i.nombre, i.unidad, i.proveedor_default, i.stock_minimo,
               ({_stock_sql()}) AS stock_calculado
        FROM inventario i
        WHERE i.activo = 1 AND i.stock_minimo > 0
        ORDER BY i.nombre COLLATE NOCASE
    """).fetchall()

    # Razón global consumo/mínimo (para estimar productos sin señal propia).
    # Se topa cada razón a 1.0 para que un producto muy ruidoso (p. ej. mínimo
    # mal puesto) no infle el estimado de todos los demás.
    razones = [
        min(consumo_medido[r["id"]] / r["stock_minimo"], 1.0)
        for r in rows
        if r["id"] in consumo_medido and r["stock_minimo"]
    ]
    razon_global = (sum(razones) / len(razones)) if razones else None

    grupos: dict[str, list] = {}
    total = 0
    n_estimados = 0
    for r in rows:
        stock = round(r["stock_calculado"], 1)
        minimo = r["stock_minimo"]

        if r["id"] in consumo_medido:
            consumo = min(consumo_medido[r["id"]], 2 * minimo)  # tope anti-ruido
            fuente = "historial"
        elif razon_global is not None:
            consumo = min(razon_global * minimo, 2 * minimo)
            fuente = "estimado"
        else:
            consumo = None
            fuente = "minimo"

        if consumo is not None:
            objetivo = consumo * semanas + minimo
        else:
            objetivo = float(minimo)  # sin dato: solo repone al mínimo

        deficit = objetivo - stock
        if deficit <= 0:
            continue
        sugerido = max(1, ceil(deficit))

        if fuente == "estimado":
            n_estimados += 1

        proveedor = (r["proveedor_default"] or "").strip() or _SIN_PROVEEDOR
        grupos.setdefault(proveedor, []).append({
            "id": r["id"],
            "nombre": r["nombre"],
            "unidad": r["unidad"] or "",
            "stock_actual": stock,
            "stock_minimo": minimo,
            "consumo_semanal": round(consumo, 1) if consumo is not None else None,
            "fuente": fuente,
            "sugerido": sugerido,
        })
        total += 1

    def _orden(nombre: str):
        return (1, "") if nombre == _SIN_PROVEEDOR else (0, nombre.lower())

    lista = [
        {"proveedor": prov, "items": items}
        for prov, items in sorted(grupos.items(), key=lambda kv: _orden(kv[0]))
    ]

    return {
        "ok": True,
        "semanas": semanas,
        "total": total,
        "n_estimados": n_estimados,
        "hay_historial": bool(consumo_medido),
        "grupos": lista,
    }


@inventario_bp.route("/inventario/api/compras")
@solo_admin
def api_compras():
    """Lista de compra en JSON. ?semanas=N (default 1, para el botón del sábado)."""
    try:
        semanas = max(1, min(12, int(request.args.get("semanas", 1))))
    except (TypeError, ValueError):
        semanas = 1
    with _db() as conn:
        data = calcular_lista_compra(conn, semanas)
    return jsonify(data)


@inventario_bp.route("/inventario/compras.pdf")
@solo_admin
def compras_pdf():
    """Descarga la lista de compra como PDF. ?semanas=N (default 1)."""
    try:
        semanas = max(1, min(12, int(request.args.get("semanas", 1))))
    except (TypeError, ValueError):
        semanas = 1
    with _db() as conn:
        data = calcular_lista_compra(conn, semanas)

    pdf_bytes = _lista_compra_pdf(data)
    nombre = f"lista_compra_{semanas}sem_{date.today().isoformat()}.pdf"
    resp = make_response(bytes(pdf_bytes))
    resp.headers["Content-Type"] = "application/pdf"
    resp.headers["Content-Disposition"] = f'attachment; filename="{nombre}"'
    return resp


def _fmt_num(n) -> str:
    """9.0 → '9', 2.5 → '2.5'."""
    if n is None:
        return "—"
    n = round(float(n), 1)
    return str(int(n)) if n == int(n) else str(n)


def _lista_compra_pdf(data: dict) -> bytearray:
    """Genera el PDF (bytes) de una lista de compra ya calculada."""
    from fpdf import FPDF

    semanas = data["semanas"]
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    ancho = pdf.w - 2 * pdf.l_margin

    def txt(s):
        # fpdf core fonts = latin-1; reemplaza lo que no entre
        return str(s).encode("latin-1", "replace").decode("latin-1")

    periodo = "1 semana" if semanas == 1 else f"{semanas} semanas"
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 9, txt("Lista de compra"), ln=1)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(110, 110, 110)
    pdf.cell(0, 6, txt(f"Motel Hacienda del Sauz  ·  para {periodo}  ·  {date.today().isoformat()}"), ln=1)
    if data["total"]:
        n_prov = len(data["grupos"])
        pdf.cell(0, 6, txt(f"{data['total']} productos por surtir  ·  {n_prov} proveedor(es)"), ln=1)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(3)

    if not data["total"]:
        pdf.set_font("Helvetica", "", 12)
        pdf.cell(0, 8, txt("Todo el inventario esta por encima del objetivo. Nada por comprar."), ln=1)
        return pdf.output()

    # Anchos de columna
    w_comprar = 22
    w_stock = 26
    w_min = 20
    w_prod = ancho - (w_comprar + w_stock + w_min)

    for grupo in data["grupos"]:
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_fill_color(240, 240, 243)
        pdf.cell(0, 8, txt(f"  {grupo['proveedor']}  ({len(grupo['items'])})"), ln=1, fill=True)

        # Encabezado de columnas
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(120, 120, 120)
        pdf.cell(w_prod, 6, txt("PRODUCTO"))
        pdf.cell(w_stock, 6, txt("TIENES"), align="R")
        pdf.cell(w_min, 6, txt("MIN"), align="R")
        pdf.cell(w_comprar, 6, txt("COMPRAR"), align="R", ln=1)
        pdf.set_text_color(0, 0, 0)

        for it in grupo["items"]:
            pdf.set_font("Helvetica", "", 10)
            nombre = it["nombre"] + (" *" if it["fuente"] == "estimado" else "")
            unidad = f" {it['unidad']}" if it["unidad"] else ""
            pdf.cell(w_prod, 7, txt(nombre))
            pdf.cell(w_stock, 7, txt(_fmt_num(it["stock_actual"])), align="R")
            pdf.cell(w_min, 7, txt(_fmt_num(it["stock_minimo"])), align="R")
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(w_comprar, 7, txt(f"+{_fmt_num(it['sugerido'])}{unidad}"), align="R", ln=1)

    if data["n_estimados"]:
        pdf.ln(4)
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(120, 120, 120)
        pdf.multi_cell(0, 5, txt(
            "* Cantidad estimada con el consumo promedio del negocio (aun sin "
            "historial propio de conteos). Se afina conforme registres mas conteos semanales."
        ))
        pdf.set_text_color(0, 0, 0)

    return pdf.output()


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
