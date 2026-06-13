"""
gastos.py - Módulo de gastos extras (SPEC §5.3). Sub-fase 3B: lectura de recibos con IA.
"""

import base64
import csv
import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import date
from io import StringIO

from flask import Blueprint, Response, jsonify, render_template, request

from ai.claude_client import call_claude
from config import Config
from logger import get_logger, log_action

gastos_bp = Blueprint("gastos", __name__)
_log = get_logger()

CATEGORIAS = ["Gas", "Luz", "Agua-Pipas", "Agua-Embotellada", "Mantenimiento", "Sam's", "StarTV", "Renta", "Otro"]

PROMPT_RECIBO = (
    "Analiza este recibo o comprobante de un negocio en Mexico y extrae los datos en formato JSON.\n"
    "Responde SOLO con el JSON, sin texto adicional.\n\n"
    "REGLAS IMPORTANTES:\n"
    "- El recibo puede aparecer rotado (vertical, horizontal o invertido). Lee el texto en su orientacion natural sin importar la rotacion de la imagen.\n"
    "- El recibo puede ser impreso o manuscrito. Los manuscritos son mas dificiles de leer; se conservador con la confianza si es manuscrito.\n"
    "- NUNCA inventes informacion. NUNCA infieras contexto que no este escrito en el recibo. Si un dato no es claro, ponlo como null en vez de inventarlo.\n"
    "- monto: busca la linea 'TOTAL' del ticket. NO uses subtotal, NO uses el efectivo entregado, NO uses impuestos individuales ni cambio. Si hay descuentos, el TOTAL es despues del descuento. Si no hay linea TOTAL clara, usa SUBTOTAL menos descuentos visibles.\n"
    "- concepto: maximo 5 palabras estilo telegrama (ejemplos: 'Compra Sams semanal', 'Gas tanque cuarto 3', 'Recarga StarTV agosto'). Sin guiones ni listas de productos. Si el concepto no esta claro, deja concepto=null.\n"
    "- fecha: la fecha impresa en el recibo en formato YYYY-MM-DD.\n"
    "- confianza: 'alta' si TODOS los datos son legibles claramente y consistentes. 'media' si algunos datos son dudosos pero la mayoria son legibles. 'baja' si el recibo es manuscrito poco legible, la foto es borrosa, los datos son inciertos, o tuviste que adivinar algun campo.\n\n"
    "Categorias disponibles (copia el texto exacto de la opcion elegida):\n"
    "Gas, Luz, Agua-Pipas, Agua-Embotellada, Mantenimiento, Sam's, StarTV, Renta, Otro\n\n"
    'Formato esperado:\n'
    '{\n'
    '  "concepto": "maximo 5 palabras o null",\n'
    '  "monto": 0.00,\n'
    '  "fecha": "YYYY-MM-DD",\n'
    '  "categoria_sugerida": "una de las categorias listadas",\n'
    '  "confianza": "alta"\n'
    '}\n\n'
    "Si no puedes leer algun dato con certeza, ponlo como null."
)

PROMPT_RECIBO_SAMS = (
    "Eres un asistente analizando un ticket de Sam's Club de un motel en Aguascalientes, Mexico.\n\n"
    "Catalogo de productos disponibles en inventario (usa los IDs y nombres EXACTOS):\n"
    "{lista_catalogo}\n\n"
    "Para CADA linea del ticket que represente un producto comprado, extrae:\n"
    "- sku_sams: el codigo numerico del producto (6-12 digitos) que aparece antes o junto al texto descriptivo. Si no lo encuentras, pon null.\n"
    "- texto_ticket: SOLO el texto descriptivo del producto, SIN incluir el sku_sams. Si el SKU aparece junto al texto en el ticket, separalos.\n"
    "- cantidad: numero de unidades compradas\n"
    "- precio_unitario: precio por unidad en MXN\n"
    "- precio_total: cantidad x precio_unitario\n"
    "- match_producto_id: ID del catalogo que mejor coincide, o null si no hay match razonable\n"
    "- match_producto_nombre: nombre del catalogo matcheado, o null si no hay match\n"
    "- confianza_match: 'alta' / 'media' / 'baja' / 'sin_match'\n\n"
    "Reglas criticas:\n"
    "- El SKU es un numero de 6-12 digitos que identifica al producto en Sam's. Aparece tipicamente antes o al lado del texto descriptivo.\n"
    "- Si una linea no tiene SKU claramente identificable, pon sku_sams: null.\n"
    "- NUNCA uses un ID que no aparezca en la lista de arriba.\n"
    "- Si el texto es ambiguo, prefiere sin_match antes que adivinar.\n"
    "- 'alta': el nombre del catalogo describe claramente el mismo producto.\n"
    "- 'media': alta probabilidad pero nombres no identicos (ej. 'MM AGU 500' -> 'Agua 500ml').\n"
    "- 'baja': plausible pero podria ser otra cosa.\n"
    "- Ignora lineas de impuestos, descuentos, totales y folio — esas NO son productos.\n\n"
    "Responde SOLO con este JSON, sin texto adicional:\n"
    '{\n'
    '  "productos": [\n'
    '    {\n'
    '      "sku_sams": "980037346",\n'
    '      "texto_ticket": "...",\n'
    '      "cantidad": 0,\n'
    '      "precio_unitario": 0.00,\n'
    '      "precio_total": 0.00,\n'
    '      "match_producto_id": null,\n'
    '      "match_producto_nombre": null,\n'
    '      "confianza_match": "alta"\n'
    '    }\n'
    '  ]\n'
    '}'
)


def _normalizar_sku(sku_raw) -> str | None:
    """Devuelve SKU como string si es válido (6-12 dígitos numéricos), sino None."""
    if sku_raw is None:
        return None
    sku_str = str(sku_raw).strip()
    if re.match(r"^\d{6,12}$", sku_str):
        return sku_str
    return None

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

        catalogo_inventario = [
            {"id": r["id"], "nombre": r["nombre"]}
            for r in db.execute(
                "SELECT id, nombre FROM inventario WHERE activo=1 ORDER BY nombre COLLATE NOCASE"
            ).fetchall()
        ]

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
        catalogo_inventario=catalogo_inventario,
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
    recibo_id       = data.get("recibo_id")

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
            fondo_row = db.execute(
                "SELECT id, nombre FROM fondos WHERE categoria_enlazada=? AND activo=1 LIMIT 1",
                (categoria,),
            ).fetchone()

        elif categoria in _CATEGORIAS_PEDIR_RESERVA and descontar_fondo:
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

        if recibo_id:
            recibo = db.execute(
                "SELECT ruta_imagen FROM recibos WHERE id=?", (recibo_id,)
            ).fetchone()
            if recibo:
                db.execute(
                    "UPDATE recibos SET gasto_extra_id=?, procesado_por_ia=1 WHERE id=?",
                    (nuevo_id, recibo_id),
                )
                if recibo["ruta_imagen"]:
                    db.execute(
                        "UPDATE gastos_extras SET recibo_path=? WHERE id=?",
                        (recibo["ruta_imagen"], nuevo_id),
                    )

        db.commit()

    log_action(
        "Gasto registrado: id=%d fecha=%s cat=%s monto=$%.2f desc=%s%s%s",
        nuevo_id, fecha, categoria, monto, descripcion or "—",
        f" → fondo '{fondo_row['nombre']}'" if fondo_row else "",
        f" recibo_id={recibo_id}" if recibo_id else "",
    )

    resp: dict = {"ok": True, "id": nuevo_id}
    if fondo_row and saldo_resultado is not None:
        resp["saldo_fondo"]    = saldo_resultado
        resp["saldo_negativo"] = saldo_resultado < 0
        resp["nombre_fondo"]   = fondo_row["nombre"]
    return jsonify(resp)


# ── API: registrar con desglose Sam's ────────────────────────

@gastos_bp.route("/gastos/registrar_con_desglose", methods=["POST"])
def registrar_con_desglose():
    data            = request.get_json(silent=True) or {}
    gasto           = data.get("gasto") or {}
    productos       = data.get("productos") or []

    fecha           = gasto.get("fecha") or date.today().isoformat()
    categoria       = (gasto.get("categoria") or "").strip()
    monto           = float(gasto.get("monto") or 0)
    descripcion     = (gasto.get("descripcion") or "").strip()
    recibo_id       = gasto.get("recibo_id")
    descontar_fondo = bool(gasto.get("descontar_fondo", False))

    if categoria not in CATEGORIAS:
        return jsonify({"error": "Categoría inválida"}), 400
    if monto <= 0:
        return jsonify({"error": "El monto debe ser mayor a cero"}), 400

    movimientos_creados = 0

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
            fondo_row = db.execute(
                "SELECT id, nombre FROM fondos WHERE categoria_enlazada=? AND activo=1 LIMIT 1",
                (categoria,),
            ).fetchone()
        elif categoria in _CATEGORIAS_PEDIR_RESERVA and descontar_fondo:
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

        if recibo_id:
            recibo = db.execute(
                "SELECT ruta_imagen FROM recibos WHERE id=?", (recibo_id,)
            ).fetchone()
            if recibo:
                db.execute(
                    "UPDATE recibos SET gasto_extra_id=?, procesado_por_ia=1 WHERE id=?",
                    (nuevo_id, recibo_id),
                )
                if recibo["ruta_imagen"]:
                    db.execute(
                        "UPDATE gastos_extras SET recibo_path=? WHERE id=?",
                        (recibo["ruta_imagen"], nuevo_id),
                    )

        for p in productos:
            inv_id      = p.get("inventario_id")
            cantidad    = float(p.get("cantidad") or 0)
            precio_tot  = float(p.get("precio_total") or 0)
            texto       = str(p.get("texto_ticket") or "")[:80]
            sku         = _normalizar_sku(p.get("sku_sams"))

            if not inv_id or cantidad <= 0:
                continue

            existe = db.execute(
                "SELECT id FROM inventario WHERE id=? AND activo=1", (inv_id,)
            ).fetchone()
            if not existe:
                continue

            db.execute(
                """INSERT INTO movimientos_inventario
                   (inventario_id, fecha, tipo, cantidad, precio_total, recibo_id, origen, descripcion)
                   VALUES (?, ?, 'entrada', ?, ?, ?, 'compra', ?)""",
                (inv_id, fecha, cantidad, precio_tot, recibo_id, "Compra Sam's — " + texto),
            )
            movimientos_creados += 1

            if sku:
                db.execute(
                    """INSERT INTO matches_aprendidos
                           (sku_sams, texto_ticket, inventario_id, veces_confirmado)
                       VALUES (?, ?, ?, 1)
                       ON CONFLICT(sku_sams) DO UPDATE SET
                           inventario_id    = excluded.inventario_id,
                           texto_ticket     = excluded.texto_ticket,
                           veces_confirmado = veces_confirmado + 1,
                           ultima_vez       = datetime('now','localtime')""",
                    (sku, texto, inv_id),
                )
                log_action("matches_aprendidos: upsert sku=%s → inventario_id=%d", sku, inv_id)

        db.commit()

    log_action(
        "Gasto+desglose registrado: id=%d fecha=%s cat=%s monto=$%.2f movimientos=%d%s",
        nuevo_id, fecha, categoria, monto, movimientos_creados,
        f" recibo_id={recibo_id}" if recibo_id else "",
    )

    resp: dict = {"ok": True, "gasto_id": nuevo_id, "movimientos_creados": movimientos_creados}
    if fondo_row and saldo_resultado is not None:
        resp["saldo_fondo"]    = saldo_resultado
        resp["saldo_negativo"] = saldo_resultado < 0
        resp["nombre_fondo"]   = fondo_row["nombre"]
    return jsonify(resp)


# ── API: subir foto de recibo ─────────────────────────────────

@gastos_bp.route("/gastos/recibos/subir", methods=["POST"])
def subir_recibo():
    if "imagen" not in request.files:
        return jsonify({"ok": False, "error": "No se recibió ninguna imagen"}), 400

    archivo = request.files["imagen"]
    if not archivo.content_type.startswith("image/"):
        return jsonify({"ok": False, "error": "El archivo no es una imagen válida"}), 400

    data_bytes = archivo.read()
    if len(data_bytes) > 2 * 1024 * 1024:
        return jsonify({
            "ok": False,
            "error": f"Imagen demasiado grande ({len(data_bytes) // 1024} KB). Máximo 2 MB.",
        }), 400

    hash_md5 = hashlib.md5(data_bytes).hexdigest()

    with _db() as db:
        existente = db.execute(
            "SELECT id, gasto_extra_id, fecha_subida FROM recibos WHERE hash_md5=?",
            (hash_md5,),
        ).fetchone()

        if existente:
            if existente["gasto_extra_id"] is not None:
                gasto = db.execute(
                    "SELECT fecha, categoria FROM gastos_extras WHERE id=?",
                    (existente["gasto_extra_id"],),
                ).fetchone()
                desc = (
                    f"{gasto['categoria']} del {gasto['fecha']}"
                    if gasto else f"#{existente['gasto_extra_id']}"
                )
                return jsonify({
                    "ok": False,
                    "error": f"Este recibo ya está asociado al gasto #{existente['gasto_extra_id']} ({desc})",
                }), 409
            return jsonify({"ok": True, "recibo_id": existente["id"], "duplicado": True})

        # Guardar archivo en disco
        hoy = date.today()
        mes_dir = Config.RECIBOS_DIR / f"{hoy.year}-{hoy.month:02d}"
        mes_dir.mkdir(parents=True, exist_ok=True)

        cur = db.execute(
            "INSERT INTO recibos (hash_md5, fecha_subida) VALUES (?, datetime('now','localtime'))",
            (hash_md5,),
        )
        recibo_id = cur.lastrowid

        nombre_original = archivo.filename or "recibo"
        slug = re.sub(r"[^a-z0-9]+", "-", nombre_original.lower().rsplit(".", 1)[0])[:20] or "recibo"
        nombre_archivo = f"{recibo_id}_{hoy.isoformat()}_{slug}.jpg"
        ruta_abs = mes_dir / nombre_archivo
        ruta_abs.write_bytes(data_bytes)

        ruta_rel = str(ruta_abs.relative_to(Config.BASE_DIR)).replace("\\", "/")
        db.execute("UPDATE recibos SET ruta_imagen=? WHERE id=?", (ruta_rel, recibo_id))
        db.commit()

    log_action("Recibo subido: id=%d hash=%s…%s ruta=%s", recibo_id, hash_md5[:8], hash_md5[-4:], ruta_rel)
    return jsonify({"ok": True, "recibo_id": recibo_id, "duplicado": False})


# ── API: analizar recibo con Claude ──────────────────────────

@gastos_bp.route("/gastos/recibos/<int:recibo_id>/analizar", methods=["POST"])
def analizar_recibo(recibo_id):
    with _db() as db:
        recibo = db.execute(
            "SELECT ruta_imagen FROM recibos WHERE id=?", (recibo_id,)
        ).fetchone()

    if not recibo or not recibo["ruta_imagen"]:
        return jsonify({"ok": False, "error": "Recibo no encontrado"}), 404

    ruta = Config.BASE_DIR / recibo["ruta_imagen"]
    if not ruta.exists():
        return jsonify({"ok": False, "error": "Archivo de imagen no encontrado en disco"}), 404

    img_b64 = base64.b64encode(ruta.read_bytes()).decode()

    resp = call_claude(
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": img_b64,
                    },
                },
                {"type": "text", "text": PROMPT_RECIBO},
            ],
        }],
        model="claude-sonnet-4-6",
        max_tokens=200,
        modulo_origen="recibos",
    )

    if resp["error"]:
        return jsonify({"ok": False, "error": resp["error"], "costo_usd": resp["costo_usd"]})

    texto = (resp["text"] or "").strip()
    texto = re.sub(r"```(?:json)?\s*", "", texto).strip().rstrip("`").strip()

    try:
        datos = json.loads(texto)
    except (json.JSONDecodeError, ValueError):
        return jsonify({
            "ok": False,
            "error": "La IA no devolvió un JSON válido. Puedes llenar el formulario manualmente.",
            "costo_usd": resp["costo_usd"],
        })

    categoria = datos.get("categoria_sugerida")
    confianza = datos.get("confianza") or "baja"
    if categoria not in CATEGORIAS:
        categoria = "Otro"
        confianza = "baja"

    concepto = str(datos.get("concepto") or "")[:60] or None

    try:
        monto = float(datos["monto"]) if datos.get("monto") is not None else None
    except (TypeError, ValueError):
        monto = None

    fecha = datos.get("fecha")
    if fecha:
        try:
            date.fromisoformat(str(fecha))
            fecha = str(fecha)
        except ValueError:
            fecha = None

    # --- Segunda llamada: desglose Sam's ---
    productos = []
    costo_total = resp["costo_usd"]

    if categoria == "Sam's" and confianza in ("alta", "media"):
        with _db() as db:
            cat_rows = db.execute(
                "SELECT id, nombre FROM inventario WHERE activo=1 ORDER BY nombre COLLATE NOCASE"
            ).fetchall()
        lista_catalogo = "\n".join(f"(ID={r['id']}) {r['nombre']}" for r in cat_rows)
        prompt_sams = PROMPT_RECIBO_SAMS.replace("{lista_catalogo}", lista_catalogo)

        resp2 = call_claude(
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64},
                    },
                    {"type": "text", "text": prompt_sams},
                ],
            }],
            model="claude-sonnet-4-6",
            max_tokens=2000,
            modulo_origen="recibos_sams",
        )
        costo_total += resp2["costo_usd"]

        if not resp2["error"]:
            txt2 = (resp2["text"] or "").strip()
            txt2 = re.sub(r"```(?:json)?\s*", "", txt2).strip().rstrip("`").strip()
            try:
                datos2 = json.loads(txt2)
                lista_prods = [p for p in (datos2.get("productos") or []) if isinstance(p, dict)]

                # Buscar todos los SKUs válidos en matches_aprendidos
                skus_validos = [s for s in (_normalizar_sku(p.get("sku_sams")) for p in lista_prods) if s]
                aprendidos = {}
                if skus_validos:
                    with _db() as db2:
                        placeholders = ",".join("?" * len(skus_validos))
                        rows = db2.execute(
                            f"SELECT ma.sku_sams, ma.inventario_id, ma.veces_confirmado, i.nombre"
                            f" FROM matches_aprendidos ma"
                            f" JOIN inventario i ON i.id = ma.inventario_id"
                            f" WHERE ma.sku_sams IN ({placeholders})",
                            skus_validos,
                        ).fetchall()
                        aprendidos = {
                            r["sku_sams"]: {
                                "inventario_id":   r["inventario_id"],
                                "nombre":          r["nombre"],
                                "veces_confirmado": r["veces_confirmado"],
                            }
                            for r in rows
                        }

                for p in lista_prods:
                    sku = _normalizar_sku(p.get("sku_sams"))
                    texto_ticket_raw = str(p.get("texto_ticket") or "").strip()
                    if sku and texto_ticket_raw.startswith(sku):
                        texto_ticket_raw = texto_ticket_raw[len(sku):].strip()

                    if sku and sku in aprendidos:
                        aprendido = aprendidos[sku]
                        mid = aprendido["inventario_id"]
                        nombre_match = aprendido["nombre"]
                        confianza = "aprendido"
                        veces = aprendido["veces_confirmado"]
                    else:
                        raw_mid = p.get("match_producto_id")
                        try:
                            mid = int(raw_mid) if raw_mid is not None else None
                        except (TypeError, ValueError):
                            mid = None
                        nombre_match = p.get("match_producto_nombre")
                        confianza = p.get("confianza_match") or "sin_match"
                        veces = None

                    productos.append({
                        "sku_sams":            sku,
                        "texto_ticket":        texto_ticket_raw[:80],
                        "cantidad":            max(0.0, float(p.get("cantidad") or 0)),
                        "precio_unitario":     max(0.0, float(p.get("precio_unitario") or 0)),
                        "precio_total":        max(0.0, float(p.get("precio_total") or 0)),
                        "match_producto_id":   mid,
                        "match_producto_nombre": nombre_match,
                        "confianza_match":     confianza,
                        "veces_confirmado":    veces,
                    })
            except (json.JSONDecodeError, ValueError, TypeError):
                productos = []

    log_action(
        "Recibo analizado: id=%d cat=%s monto=%s confianza=%s productos=%d costo=$%.6f",
        recibo_id, categoria, monto, confianza, len(productos), costo_total,
    )
    return jsonify({
        "ok":               True,
        "concepto":         concepto,
        "monto":            monto,
        "fecha":            fecha,
        "categoria_sugerida": categoria,
        "confianza":        confianza,
        "costo_usd":        costo_total,
        "productos":        productos,
    })


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
