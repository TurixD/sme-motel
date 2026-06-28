"""
reportes.py - Módulo de reportes (SPEC §5.9 — Fase 2, sin narrativa IA).
"""

import csv
import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from io import StringIO

from flask import Blueprint, Response, jsonify, render_template, request

from ai.claude_client import call_claude
from config import Config
from logger import get_logger, log_action
from modules.auth import solo_admin

reportes_bp = Blueprint("reportes", __name__)
_log = get_logger()

_MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


@contextmanager
def _db():
    conn = sqlite3.connect(Config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ── Helpers de fechas ─────────────────────────────────────────

def _semana_anterior() -> tuple[date, date]:
    hoy = date.today()
    lunes_actual = hoy - timedelta(days=hoy.weekday())
    lunes_prev   = lunes_actual - timedelta(days=7)
    return lunes_prev, lunes_prev + timedelta(days=6)


def _mes_anterior() -> tuple[date, date]:
    hoy = date.today()
    ultimo_prev  = hoy.replace(day=1) - timedelta(days=1)
    primer_prev  = ultimo_prev.replace(day=1)
    return primer_prev, ultimo_prev


def _ultimo_dia_mes(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1) - timedelta(days=1)
    return date(d.year, d.month + 1, 1) - timedelta(days=1)


def _sig_mes(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def _label_semana(d: date, h: date) -> str:
    if d.month == h.month:
        return f"{d.day}–{h.day} {_MESES[d.month-1]} {d.year}"
    return f"{d.day} {_MESES[d.month-1]} – {h.day} {_MESES[h.month-1]} {h.year}"


def _label_mes(d: date) -> str:
    return f"{_MESES[d.month-1].capitalize()} {d.year}"


def _delta_pct(actual: float, anterior: float) -> float | None:
    if anterior == 0:
        return None
    return round((actual - anterior) / abs(anterior) * 100, 1)


# ── Queries de datos ──────────────────────────────────────────

def _tarjetas(db, desde: str, hasta: str, prev_desde: str, prev_hasta: str) -> dict:
    def ing(d1, d2):
        return float(db.execute(
            "SELECT COALESCE(SUM(total_neto),0) FROM ingresos_diarios WHERE fecha BETWEEN ? AND ?",
            (d1, d2),
        ).fetchone()[0])

    def gas(d1, d2):
        return float(db.execute(
            "SELECT COALESCE(SUM(monto),0) FROM gastos_extras WHERE fecha BETWEEN ? AND ?",
            (d1, d2),
        ).fetchone()[0])

    ia, ia_p = ing(desde, hasta), ing(prev_desde, prev_hasta)
    ga, ga_p = gas(desde, hasta), gas(prev_desde, prev_hasta)
    ua, ua_p = ia - ga, ia_p - ga_p

    return {
        "ingresos": {"actual": ia,      "anterior": ia_p, "delta_pct": _delta_pct(ia, ia_p)},
        "gastos":   {"actual": ga,      "anterior": ga_p, "delta_pct": _delta_pct(ga, ga_p)},
        "utilidad": {"actual": ua,      "anterior": ua_p, "delta_pct": _delta_pct(ua, ua_p)},
        "tu_parte": {"actual": ua * .5, "anterior": ua_p * .5, "delta_pct": _delta_pct(ua, ua_p)},
    }


def _gastos_por_cat(db, desde: str, hasta: str, prev_desde: str, prev_hasta: str) -> list[dict]:
    actual = {r["categoria"]: float(r["t"]) for r in db.execute(
        "SELECT categoria, COALESCE(SUM(monto),0) AS t FROM gastos_extras "
        "WHERE fecha BETWEEN ? AND ? GROUP BY categoria",
        (desde, hasta),
    ).fetchall()}
    anterior = {r["categoria"]: float(r["t"]) for r in db.execute(
        "SELECT categoria, COALESCE(SUM(monto),0) AS t FROM gastos_extras "
        "WHERE fecha BETWEEN ? AND ? GROUP BY categoria",
        (prev_desde, prev_hasta),
    ).fetchall()}
    cats = sorted(set(list(actual) + list(anterior)))
    return sorted(
        [{"categoria": c, "actual": actual.get(c, 0), "anterior": anterior.get(c, 0)} for c in cats],
        key=lambda x: x["actual"], reverse=True,
    )


def _fondos(db, desde: str, hasta: str) -> list[dict]:
    rows = db.execute("""
        SELECT f.id, f.nombre, f.color,
            COALESCE(
                SUM(CASE WHEN m.tipo='deposito' AND m.fecha <  ? THEN  m.monto ELSE 0 END) -
                SUM(CASE WHEN m.tipo='retiro'   AND m.fecha <  ? THEN  m.monto ELSE 0 END)
            , 0) AS saldo_inicial,
            COALESCE(SUM(CASE WHEN m.tipo='deposito' AND m.fecha BETWEEN ? AND ? THEN m.monto ELSE 0 END), 0) AS entradas,
            COALESCE(SUM(CASE WHEN m.tipo='retiro'   AND m.fecha BETWEEN ? AND ? THEN m.monto ELSE 0 END), 0) AS salidas
        FROM fondos f
        LEFT JOIN movimientos_fondos m ON m.fondo_id = f.id
        WHERE f.activo = 1
        GROUP BY f.id
        ORDER BY f.id
    """, (desde, desde, desde, hasta, desde, hasta)).fetchall()

    result = []
    for r in rows:
        si = float(r["saldo_inicial"])
        en = float(r["entradas"])
        sa = float(r["salidas"])
        result.append({
            "nombre": r["nombre"], "color": r["color"],
            "saldo_inicial": si, "entradas": en, "salidas": sa,
            "saldo_final": si + en - sa,
        })
    return result


def _nomina(db, desde: str, hasta: str) -> tuple[list[dict], float]:
    rows = db.execute("""
        SELECT e.nombre, COUNT(*) AS dias, COALESCE(SUM(t.sueldo), 0) AS total
        FROM asignaciones_turnos a
        JOIN empleados e ON e.id = a.empleado_id
        JOIN turnos    t ON t.id = a.turno_id
        WHERE a.fecha BETWEEN ? AND ?
        GROUP BY e.id, e.nombre
        ORDER BY total DESC
    """, (desde, hasta)).fetchall()
    nomina = [{"nombre": r["nombre"], "dias": r["dias"], "total": float(r["total"])} for r in rows]
    return nomina, sum(n["total"] for n in nomina)


def _payload(db, desde: str, hasta: str, prev_desde: str, prev_hasta: str,
             prev_param: str | None, next_param: str | None, label: str) -> dict:
    tarjetas    = _tarjetas(db, desde, hasta, prev_desde, prev_hasta)
    gastos_cat  = _gastos_por_cat(db, desde, hasta, prev_desde, prev_hasta)
    fondos      = _fondos(db, desde, hasta)
    nomina, nt  = _nomina(db, desde, hasta)
    return {
        "periodo":      {"desde": desde, "hasta": hasta, "label": label},
        "anterior":     {"desde": prev_desde, "hasta": prev_hasta},
        "tarjetas":     tarjetas,
        "gastos_por_cat": gastos_cat,
        "fondos":       fondos,
        "nomina":       nomina,
        "nomina_total": nt,
        "prev_param":   prev_param,
        "next_param":   next_param,
    }


# ── Página principal ──────────────────────────────────────────

@reportes_bp.route("/reportes")
@solo_admin
def index():
    return render_template("reportes.html")


# ── API: semanal ──────────────────────────────────────────────

@reportes_bp.route("/reportes/api/semanal")
@solo_admin
def api_semanal():
    param = request.args.get("lunes", "")
    try:
        lunes = date.fromisoformat(param)
        lunes = lunes - timedelta(days=lunes.weekday())   # normalizar a lunes
    except (ValueError, TypeError):
        lunes, _ = _semana_anterior()

    domingo     = lunes + timedelta(days=6)
    prev_lunes  = lunes - timedelta(days=7)
    prev_dom    = prev_lunes + timedelta(days=6)

    hoy          = date.today()
    lunes_actual = hoy - timedelta(days=hoy.weekday())
    next_lunes   = lunes + timedelta(days=7)
    next_param   = next_lunes.isoformat() if next_lunes <= lunes_actual else None

    with _db() as db:
        data = _payload(
            db,
            lunes.isoformat(), domingo.isoformat(),
            prev_lunes.isoformat(), prev_dom.isoformat(),
            prev_lunes.isoformat(), next_param,
            _label_semana(lunes, domingo),
        )
    return jsonify(data)


# ── API: mensual ──────────────────────────────────────────────

@reportes_bp.route("/reportes/api/mensual")
@solo_admin
def api_mensual():
    param = request.args.get("mes", "")
    try:
        y, m   = param.split("-")
        desde_d = date(int(y), int(m), 1)
    except (ValueError, AttributeError):
        desde_d, _ = _mes_anterior()

    hasta_d    = _ultimo_dia_mes(desde_d)
    prev_hasta = desde_d - timedelta(days=1)
    prev_desde = prev_hasta.replace(day=1)

    hoy       = date.today()
    mes_act   = date(hoy.year, hoy.month, 1)
    next_mes  = _sig_mes(desde_d)
    next_param = f"{next_mes.year}-{next_mes.month:02d}" if next_mes <= mes_act else None
    prev_param = f"{prev_desde.year}-{prev_desde.month:02d}"

    with _db() as db:
        data = _payload(
            db,
            desde_d.isoformat(), hasta_d.isoformat(),
            prev_desde.isoformat(), prev_hasta.isoformat(),
            prev_param, next_param,
            _label_mes(desde_d),
        )
    return jsonify(data)


# ── API: anual (solo 4 tarjetas sin comparación) ──────────────

@reportes_bp.route("/reportes/api/anual")
@solo_admin
def api_anual():
    try:
        anio = int(request.args.get("anio", ""))
    except (ValueError, TypeError):
        anio = date.today().year

    desde = date(anio, 1, 1).isoformat()
    hasta = date(anio, 12, 31).isoformat()

    with _db() as db:
        ing = float(db.execute(
            "SELECT COALESCE(SUM(total_neto),0) FROM ingresos_diarios WHERE fecha BETWEEN ? AND ?",
            (desde, hasta),
        ).fetchone()[0])
        gas = float(db.execute(
            "SELECT COALESCE(SUM(monto),0) FROM gastos_extras WHERE fecha BETWEEN ? AND ?",
            (desde, hasta),
        ).fetchone()[0])

    util = ing - gas
    return jsonify({
        "periodo": {"desde": desde, "hasta": hasta, "label": f"Año {anio}"},
        "tarjetas": {
            "ingresos": {"actual": ing},
            "gastos":   {"actual": gas},
            "utilidad": {"actual": util},
            "tu_parte": {"actual": util * 0.5},
        },
    })


# ── Narrativa IA ──────────────────────────────────────────────

def _calcular_hash(tarjetas: dict, nomina_total: float) -> str:
    datos = (
        f"{tarjetas['ingresos']['actual']:.2f},"
        f"{tarjetas['gastos']['actual']:.2f},"
        f"{tarjetas['utilidad']['actual']:.2f},"
        f"{tarjetas['ingresos']['anterior']:.2f},"
        f"{tarjetas['gastos']['anterior']:.2f},"
        f"{nomina_total:.2f}"
    )
    return hashlib.md5(datos.encode()).hexdigest()


def _construir_prompt(tipo: str, label: str, tarjetas: dict,
                      gastos_cat: list, fondos: list,
                      nomina: list, nomina_total: float) -> str:
    t = tarjetas
    tipo_str = "Semanal" if tipo == "semanal" else "Mensual"

    def fmt(n):
        return f"${n:,.2f}"

    def delta(v):
        return f"{v:+.1f}%" if v is not None else "N/D"

    gastos_lines = "\n".join(
        f"    - {g['categoria']}: {fmt(g['actual'])}"
        for g in gastos_cat if g["actual"] > 0
    ) or "    (sin gastos registrados)"

    fondos_lines = "\n".join(
        f"  - {f['nombre']}: entradas {fmt(f['entradas'])} / salidas {fmt(f['salidas'])} / saldo {fmt(f['saldo_final'])}"
        for f in fondos
    ) or "  (sin fondos activos)"

    nomina_lines = ", ".join(
        f"{n['nombre']} {fmt(n['total'])}" for n in nomina
    ) if nomina else "sin nómina registrada"

    return (
        "Eres un asistente de negocios para un motel en Aguascalientes, México. "
        "Analiza este reporte y escribe un resumen breve y honesto, sin ser corporativo ni falso.\n\n"
        f"REPORTE [{tipo_str}]: {label}\n\n"
        "INGRESOS\n"
        f"  Este periodo:   {fmt(t['ingresos']['actual'])}\n"
        f"  Periodo ant.:   {fmt(t['ingresos']['anterior'])}  ({delta(t['ingresos']['delta_pct'])})\n\n"
        "GASTOS\n"
        f"  Este periodo:   {fmt(t['gastos']['actual'])}\n"
        f"  Periodo ant.:   {fmt(t['gastos']['anterior'])}  ({delta(t['gastos']['delta_pct'])})\n"
        f"  Por categoría:\n{gastos_lines}\n\n"
        "UTILIDAD\n"
        f"  Este periodo:   {fmt(t['utilidad']['actual'])}\n"
        f"  Periodo ant.:   {fmt(t['utilidad']['anterior'])}  ({delta(t['utilidad']['delta_pct'])})\n\n"
        "NÓMINA\n"
        f"  Total pagado:   {fmt(nomina_total)}  ({len(nomina)} empleados)\n"
        f"  Detalle: {nomina_lines}\n\n"
        f"FONDOS (movimientos del periodo):\n{fondos_lines}\n\n"
        'Responde SOLO con este JSON, sin texto antes ni después:\n'
        '{\n'
        '  "parrafo": "MÁXIMO 80 palabras totales. 2-3 oraciones cortas y directas.",\n'
        '  "bullets": [\n'
        '    "Acción concreta o cosa a vigilar",\n'
        '    "Segunda observación accionable",\n'
        '    "Tercera oportunidad o decisión"\n'
        '  ]\n'
        '}\n'
        '(Cada bullet máximo 12 palabras)\n\n'
        'REGLAS DE CONCISIÓN ESTRICTAS:\n'
        '- Párrafo: máximo 80 palabras\n'
        '- Cada bullet: máximo 12 palabras\n'
        '- Sin frases huecas tipo "es importante destacar", "cabe mencionar", "vale la pena"\n'
        '- Sin emojis\n'
        '- Sin contexto innecesario que ya está en los datos\n'
        '- Si quieres incluir un detalle, decide si es esencial; si no, corta'
    )


@reportes_bp.route("/reportes/api/narrativa/<tipo>/<periodo_clave>", methods=["GET", "POST"])
@solo_admin
def api_narrativa(tipo, periodo_clave):
    if tipo not in ("semanal", "mensual"):
        return jsonify({"ok": False, "error": "tipo invalido"}), 400

    forzar = request.method == "POST"

    try:
        if tipo == "semanal":
            lunes = date.fromisoformat(periodo_clave.removeprefix("semana_"))
            desde = lunes.isoformat()
            hasta = (lunes + timedelta(days=6)).isoformat()
            prev_lunes = lunes - timedelta(days=7)
            prev_desde = prev_lunes.isoformat()
            prev_hasta = (prev_lunes + timedelta(days=6)).isoformat()
            label = _label_semana(lunes, lunes + timedelta(days=6))
        else:
            y, m = periodo_clave.removeprefix("mes_").split("-")
            desde_d = date(int(y), int(m), 1)
            desde = desde_d.isoformat()
            hasta = _ultimo_dia_mes(desde_d).isoformat()
            prev_hasta_d = desde_d - timedelta(days=1)
            prev_desde_d = prev_hasta_d.replace(day=1)
            prev_desde = prev_desde_d.isoformat()
            prev_hasta = prev_hasta_d.isoformat()
            label = _label_mes(desde_d)
    except (ValueError, AttributeError):
        return jsonify({"ok": False, "error": "periodo_clave invalido"}), 400

    with _db() as db:
        tarjetas   = _tarjetas(db, desde, hasta, prev_desde, prev_hasta)
        gastos_cat = _gastos_por_cat(db, desde, hasta, prev_desde, prev_hasta)
        fondos     = _fondos(db, desde, hasta)
        nomina, nt = _nomina(db, desde, hasta)
        hash_datos = _calcular_hash(tarjetas, nt)

        if not forzar:
            cached = db.execute(
                "SELECT parrafo, bullets, costo_usd, fecha_generada, hash_datos "
                "FROM reportes_narrativas WHERE tipo=? AND periodo_clave=?",
                (tipo, periodo_clave),
            ).fetchone()
            if cached and cached["hash_datos"] == hash_datos:
                return jsonify({
                    "ok": True,
                    "parrafo": cached["parrafo"],
                    "bullets": json.loads(cached["bullets"]),
                    "costo_usd": cached["costo_usd"],
                    "generada_ahora": False,
                    "fecha_generada": cached["fecha_generada"],
                })

        existe = db.execute(
            "SELECT id FROM reportes_narrativas WHERE tipo=? AND periodo_clave=?",
            (tipo, periodo_clave),
        ).fetchone()

    prompt = _construir_prompt(tipo, label, tarjetas, gastos_cat, fondos, nomina, nt)
    resp = call_claude(
        messages=[{"role": "user", "content": prompt}],
        model="claude-sonnet-4-6",
        max_tokens=2000,
        modulo_origen="narrativa_reportes",
    )

    if resp["error"]:
        if "Límite mensual" in resp["error"]:
            return jsonify({
                "ok": False,
                "error": "limite_ia",
                "mensaje": "Resumen no disponible: límite mensual IA alcanzado",
            })
        return jsonify({"ok": False, "error": "api_error", "mensaje": "Resumen no disponible"})

    try:
        texto = (resp["text"] or "").strip()
        texto = re.sub(r"```(?:json)?\s*", "", texto).strip().rstrip("`").strip()
        parsed  = json.loads(texto)
        parrafo = str(parsed["parrafo"])
        bullets = list(parsed["bullets"])
        if len(bullets) != 3:
            raise ValueError("bullets count != 3")
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        _log.error("narrativa JSON invalido: %s", (resp["text"] or "")[:300])
        return jsonify({"ok": False, "error": "json_invalido", "mensaje": "Resumen no disponible"})

    fecha_generada = datetime.now().strftime("%Y-%m-%d %H:%M")
    costo_usd = resp["costo_usd"]

    with _db() as db:
        if existe:
            db.execute(
                "UPDATE reportes_narrativas "
                "SET parrafo=?, bullets=?, hash_datos=?, costo_usd=?, fecha_generada=? "
                "WHERE tipo=? AND periodo_clave=?",
                (parrafo, json.dumps(bullets, ensure_ascii=False), hash_datos,
                 costo_usd, fecha_generada, tipo, periodo_clave),
            )
        else:
            db.execute(
                "INSERT INTO reportes_narrativas "
                "(tipo, periodo_clave, parrafo, bullets, hash_datos, costo_usd, fecha_generada) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (tipo, periodo_clave, parrafo, json.dumps(bullets, ensure_ascii=False),
                 hash_datos, costo_usd, fecha_generada),
            )
        db.commit()

    log_action("narrativa_reportes: generada %s %s costo=$%.6f", tipo, periodo_clave, costo_usd)

    return jsonify({
        "ok": True,
        "parrafo": parrafo,
        "bullets": bullets,
        "costo_usd": costo_usd,
        "generada_ahora": True,
        "fecha_generada": fecha_generada,
    })


# ── Exportar CSV ──────────────────────────────────────────────

@reportes_bp.route("/reportes/exportar")
@solo_admin
def exportar():
    tipo = request.args.get("tipo", "semanal")

    if tipo == "semanal":
        param = request.args.get("lunes", "")
        try:
            lunes = date.fromisoformat(param)
            lunes = lunes - timedelta(days=lunes.weekday())
        except (ValueError, TypeError):
            lunes, _ = _semana_anterior()
        domingo = lunes + timedelta(days=6)
        desde   = lunes.isoformat()
        hasta   = domingo.isoformat()
        label   = _label_semana(lunes, domingo)
    else:
        param = request.args.get("mes", "")
        try:
            y, m    = param.split("-")
            desde_d = date(int(y), int(m), 1)
        except (ValueError, AttributeError):
            desde_d, _ = _mes_anterior()
        desde = desde_d.isoformat()
        hasta = _ultimo_dia_mes(desde_d).isoformat()
        label = _label_mes(desde_d)

    with _db() as db:
        ing = float(db.execute(
            "SELECT COALESCE(SUM(total_neto),0) FROM ingresos_diarios WHERE fecha BETWEEN ? AND ?",
            (desde, hasta),
        ).fetchone()[0])
        gas = float(db.execute(
            "SELECT COALESCE(SUM(monto),0) FROM gastos_extras WHERE fecha BETWEEN ? AND ?",
            (desde, hasta),
        ).fetchone()[0])
        util = ing - gas

        cat_rows = db.execute(
            "SELECT categoria, COALESCE(SUM(monto),0) AS t FROM gastos_extras "
            "WHERE fecha BETWEEN ? AND ? GROUP BY categoria ORDER BY t DESC",
            (desde, hasta),
        ).fetchall()

        nom_rows = db.execute("""
            SELECT e.nombre, COUNT(*) AS d, COALESCE(SUM(t.sueldo),0) AS tot
            FROM asignaciones_turnos a
            JOIN empleados e ON e.id = a.empleado_id
            JOIN turnos    t ON t.id = a.turno_id
            WHERE a.fecha BETWEEN ? AND ?
            GROUP BY e.id ORDER BY tot DESC
        """, (desde, hasta)).fetchall()

    buf = StringIO()
    w   = csv.writer(buf)

    w.writerow([f"Reporte {tipo.capitalize()} — {label}"])
    w.writerow([])
    w.writerow(["Resumen", "Monto"])
    w.writerow(["Ingresos", f"${ing:,.0f}"])
    w.writerow(["Gastos",   f"${gas:,.0f}"])
    w.writerow(["Utilidad", f"${util:,.0f}"])
    w.writerow(["Tu parte (50%)", f"${util*.5:,.0f}"])
    w.writerow([])
    w.writerow(["Gastos por categoría", "Monto"])
    for r in cat_rows:
        w.writerow([r["categoria"], f"${float(r['t']):,.0f}"])
    w.writerow([])
    w.writerow(["Nómina (informativa)", "Días", "Total"])
    total_nom = 0.0
    for r in nom_rows:
        t = float(r["tot"])
        w.writerow([r["nombre"], r["d"], f"${t:,.0f}"])
        total_nom += t
    w.writerow(["Total nómina", "", f"${total_nom:,.0f}"])

    filename = f"reporte_{tipo}_{desde}.csv"
    return Response(
        "﻿" + buf.getvalue(),
        mimetype="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
