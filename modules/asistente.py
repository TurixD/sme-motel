"""
asistente.py - Asistente conversacional IA con tool use (Fase 4).

Blueprint: asistente_bp
  GET  /asistente
  POST /asistente/api/mensaje
  POST /asistente/api/ejecutar_cambio/<int:cambio_id>
  POST /asistente/api/cancelar_cambio/<int:cambio_id>
  GET  /asistente/api/nueva_sesion
"""

import calendar
import json
import re
import sqlite3
import uuid
from datetime import date, datetime

import anthropic
from flask import Blueprint, jsonify, make_response, render_template, request

from ai.cost_calculator import calcular_costo
from ai.tools import TOOLS
from config import Config
from logger import get_logger, log_action
from modules import asistente_turnos as AT
from modules.auth import solo_admin

asistente_bp = Blueprint("asistente", __name__)
_log = get_logger()

_MODEL = Config.ASSISTANT_MODEL
_MAX_TOKENS = Config.ASSISTANT_MAX_TOKENS
_MAX_ITER = 15
_MODULO = "asistente"

_TABLAS_WHITELIST = {
    "gastos_extras", "ingresos_diarios", "asignaciones_turnos",
    "empleados", "gastos_fijos", "fondos", "movimientos_fondos",
    "inventario", "bitacora_calendario", "conteos_semanales",
    "movimientos_inventario",
}

_RE_ESCRITURA = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|ATTACH|DETACH|PRAGMA|VACUUM)\b",
    re.IGNORECASE,
)
# Bloquea lecturas de datos sensibles (hashes de contraseña) hacia el modelo
_RE_SENSIBLE = re.compile(r"\b(usuarios|password_hash|password)\b", re.IGNORECASE)
# Operaciones nunca permitidas dentro de un cambio de escritura propuesto
_RE_PELIGRO_SQL = re.compile(
    r"\b(ATTACH|DETACH|PRAGMA|DROP|ALTER|CREATE|VACUUM|TRUNCATE|REPLACE)\b",
    re.IGNORECASE,
)


def _tiene_multiples_sentencias(sql: str) -> bool:
    """True si hay un ';' que no sea el final (evita stacked queries)."""
    return ";" in sql.strip().rstrip(";")


def _validar_sql_cambio(sql: str):
    """
    Valida el SQL de un cambio de escritura. Deriva la tabla y el tipo del SQL
    REAL (no de lo que declare el modelo), exige que la tabla esté en la
    whitelist, prohíbe UPDATE/DELETE sin WHERE y solo permite una sentencia.
    Devuelve (ok, error, tabla, tipo).
    """
    s = (sql or "").strip()
    if not s:
        return False, "SQL vacío.", None, None
    if _tiene_multiples_sentencias(s):
        return False, "Solo se permite una sentencia SQL.", None, None
    if _RE_PELIGRO_SQL.search(s):
        return False, "El SQL contiene operaciones no permitidas.", None, None
    m = re.match(r"^\s*(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+[\"'`\[]?(\w+)", s, re.IGNORECASE)
    if not m:
        return False, "El SQL debe ser INSERT INTO / UPDATE / DELETE FROM sobre una tabla permitida.", None, None
    tipo  = m.group(1).split()[0].upper()          # INSERT | UPDATE | DELETE
    tabla = m.group(2).lower()
    if tabla not in _TABLAS_WHITELIST:
        return False, f"Tabla '{tabla}' no está permitida para escritura.", None, None
    if tipo in ("UPDATE", "DELETE") and not re.search(r"\bWHERE\b", s, re.IGNORECASE):
        return False, f"{tipo} sin WHERE no permitido (afectaría toda la tabla).", None, None
    return True, None, tabla, tipo

_SYSTEM_PROMPT = """Eres el asistente IA del SME, sistema interno del Motel Hacienda del Sauz en Aguascalientes, México. El usuario es Turi, dueño junto con su socio Gabriel (utilidades 50/50). Tres turnos: mañana 08-16, tarde 16-23, noche 23-08. Hablas español mexicano directo, honesto y CONCISO. NO usas emojis salvo que sean útiles.

REGLAS CLAVE (síguelas siempre):
1. FECHA: la fecha y hora actuales vienen inyectadas en tu contexto. NUNCA las calcules ni asumas por tu cuenta; úsalas para todo lo relativo ("hoy", "ayer", "este mes", "los sábados", etc.).
2. NUNCA enumeres listas largas de fechas en el chat. Habla en términos de RANGOS y CONTEOS que te devuelven las herramientas. Si algo abarca muchos días, di "51 sábados del 13-jul al 06-jul", no la lista.
3. NUNCA afirmes un conteo (cuántos registros, cuántas fechas, cuánto dinero) que no venga de un tool. Si no lo consultaste, consúltalo; no adivines.
4. TURNOS (empleados/asignaciones): usa SIEMPRE las herramientas de dominio, NUNCA escribas SQL para turnos:
   - Para leer: consultar_empleados (obtén ids aquí, nunca los adivines), consultar_asignaciones, resumen_cobertura.
   - Para cambiar recurrente por día de la semana: reasignar_turnos_recurrentes.
   - Para un ajuste puntual de una fecha: asignar_turno_fecha / quitar_turno_fecha.
5. FLUJO DE CAMBIO (una sola confirmación): (a) consulta el estado real y los ids, (b) presenta UN resumen del plan con los conteos reales que devolvió el tool, (c) el tool genera una TARJETA que el usuario confirma con un botón. NO ejecutes tú; NO vuelvas a preguntar "¿confirmas?" en cada paso. Una vez que el usuario confirma la tarjeta, el sistema aplica TODO el plan de forma atómica.
6. Si un tool devuelve un error o un problema de cobertura (una fecha quedaría sin nadie), explícalo en lenguaje claro y propón el siguiente paso concreto. NUNCA respondas solo "intenta de nuevo".
7. Nombres tolerantes a dedazos: si consultar_empleados devuelve un match aproximado único (ej. "betzaida" → "Betzaira"), confírmalo UNA vez con el usuario y sigue.
8. Para lecturas de dinero (ingresos, gastos, fondos, inventario) usa ejecutar_sql_lectura (solo SELECT). Para cambios de dinero de una sola operación usa proponer_cambio_datos.

REGLAS DE NEGOCIO:
- Utilidades 50/50 Turi y Gabriel.
- Renta: ~$10,000 semanal + ~$40,000 mensual. La renta es un gasto normal que sale del dinero de la semana (ya NO hay fondo de Renta).
- Los gastos por defecto salen del "dinero de la semana" (bajan la utilidad = ingresos − gastos). Los fondos (Reserva, CFE, etc.) son ahorros aparte y OPCIONALES: un gasto solo descuenta de un fondo si el usuario lo eligió (gastos_extras.fondo_descontado_id). Los fondos se pueden crear/borrar desde la pantalla Fondos.
- Un empleado NO debe tener dos turnos el mismo día. Antes de agregar, verifica con consultar_asignaciones.
- Los sueldos (turnos.sueldo: $400 mañana/tarde, $500 noche) YA se descuentan en los cortes de turno: ingresos_diarios.total_neto es NETO de sueldos. NUNCA vuelvas a restar la nómina de los ingresos ni de la utilidad.

ESQUEMA BD (para ejecutar_sql_lectura; los turnos NO se tocan por SQL):

ingresos_diarios(id, fecha TEXT YYYY-MM-DD, monto_efectivo, monto_tarjeta, monto_transferencia, comision_tarjeta=tarjeta×0.04, total_neto, notas, creado_en)
  * total_neto YA es NETO de sueldos (los cortes de turno descuentan la nómina). NO restes la nómina otra vez.
  * La mayoría de los días se genera automáticamente desde cortes_turno (efectivo = corte tarde + corte noche; tarjeta = rentas con es_tarjeta del día).

cortes_turno(id, fecha, turno [manana|tarde|noche], empleado_id FK, bruto_calculado, bruto_declarado, estado [declarado|editado|anulado], declarado_por_nombre, notas)
  * Corte del efectivo esperado en caja por turno. mañana = cuartos efectivo − sueldos mañana; tarde = (mañana+tarde efectivo) − sueldos mañana+tarde+noche (acumulativo); noche = cuartos efectivo. Solo estados 'declarado'/'editado' cuentan.

rentas(id, cuarto_id FK, fecha, hora_registro, duracion_horas, precio_default, precio_cobrado, notas, estado [activo|cancelado], registrado_por, editado INTEGER 0/1, es_tarjeta INTEGER 0/1 [pago con tarjeta, no entra a caja])
cuartos(id, numero, tipo, nombre_display, precio_6h, precio_12h, precio_18h, precio_24h)

gastos_extras(id, fecha, categoria TEXT [Gas|Luz|Agua-Pipas|Agua-Embotellada|Mantenimiento|Sam's|StarTV|Renta|Otro], monto, descripcion, recibo_id, fondo_descontado_id, creado_en)

empleados(id, nombre, turno_default [manana|tarde|noche], es_socio INTEGER 0/1, activo INTEGER 0/1, fecha_ingreso, fecha_baja, color_calendario)

turnos(id, nombre [manana|tarde|noche], hora_inicio, hora_fin, sueldo REAL)

asignaciones_turnos(id, fecha, empleado_id FK, turno_id FK, es_doble_turno INTEGER 0/1, notas, creado_en)
  * NO la consultes ni modifiques por SQL: usa las herramientas de turnos (consultar_asignaciones, reasignar_turnos_recurrentes, etc.).

pagos_empleados(id, asignacion_turno_id FK, empleado_id FK, fecha, monto, pagado INTEGER 0/1, creado_en)

fondos(id, nombre, descripcion, meta_mensual, minimo_seguro, aporte_periodico, frecuencia_aporte, dia_aporte, pregunta_antes, categoria_enlazada, color, activo)
movimientos_fondos(id, fondo_id FK, fecha, tipo [deposito|retiro|saltado], monto, concepto, razon_saltado, gasto_extra_id FK, creado_en)

gastos_fijos(id, concepto [Renta|CFE|StarTV|Contadores], monto_estimado, frecuencia, dia_recordatorio, proxima_fecha, activo)

inventario(id, nombre, unidad, stock_actual, stock_minimo, precio_unitario, ultima_compra, proveedor_default [Sam's|Mercado Libre|Abarrotera|Otro], activo)
conteos_semanales(id, fecha, inventario_id FK, cantidad, notas)
movimientos_inventario(id, inventario_id FK, fecha, tipo [entrada], cantidad, precio_total, recibo_id FK, notas)

bitacora_calendario(id, fecha_cambio, fecha_afectada, descripcion, solicitud_original, usuario)
uso_ia(id, fecha, funcion, modelo, tokens_input, tokens_output, costo_usd, costo_mxn, exito, error_message)
conversaciones_ia(id, sesion_id, rol [user|assistant], contenido, fecha, tokens_input, tokens_output, costo_usd)

QUERIES ÚTILES:
-- Saldo de un fondo:
SELECT COALESCE(SUM(CASE WHEN tipo='deposito' THEN monto ELSE 0 END),0) -
       COALESCE(SUM(CASE WHEN tipo='retiro' THEN monto ELSE 0 END),0) AS saldo
FROM movimientos_fondos WHERE fondo_id = (SELECT id FROM fondos WHERE nombre LIKE '%NombreFondo%')

-- Quién trabaja un día/turno:
SELECT e.nombre, e.id FROM asignaciones_turnos at
JOIN empleados e ON e.id=at.empleado_id JOIN turnos t ON t.id=at.turno_id
WHERE at.fecha='YYYY-MM-DD' AND t.nombre='manana'

-- Pagos a empleado en período:
SELECT e.nombre, SUM(p.monto) as total FROM pagos_empleados p
JOIN empleados e ON e.id=p.empleado_id
WHERE p.fecha BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD' GROUP BY e.id

ESTILO DE RESPUESTA:
- Conciso, máximo 3-4 oraciones para respuestas simples
- Listas con guiones
- Montos como $XX,XXX (sin decimales salvo que sean relevantes)
- 0 resultados → dilo claramente, no inventes
- Si falta información, pregúntale a Turi en lugar de adivinar"""


# Ejemplos de flujos ideales (Haiku imita ejemplos mucho mejor que reglas abstractas).
# Van en el bloque cacheado del system, así que su costo es marginal.
_FEWSHOT = """EJEMPLOS DE CÓMO ACTUAR (síguelos como molde):

Ejemplo 1 — lectura simple:
Usuario: "¿quién trabaja el sábado en la tarde?"
Tú: llamas consultar_asignaciones(dia_semana="sabado", turno="tarde") y respondes solo con los nombres del próximo sábado. No enumeras todos los sábados del año.

Ejemplo 2 — reasignación recurrente con excepción (caso típico):
Usuario: "quita a Dulce y Turi de los sábados en la tarde y pon a Betzaira, pero el sábado 18 va Martha en lugar de Betzaira"
Tú:
1. Tomas los ids del roster inyectado (Dulce, Turi, Betzaira, Martha). No preguntas a la BD si ya los tienes en el roster.
2. Llamas UNA vez:
   reasignar_turnos_recurrentes(
     dia_semana="sabado", turno="tarde",
     quitar_empleado_ids=[<Dulce>, <Turi>],
     agregar_empleado_ids=[<Betzaira>],
     excepciones=[{"fecha":"2026-07-18","quitar_ids":[<Betzaira>],"agregar_ids":[<Martha>]}]
   )
3. El tool te devuelve conteos reales (n_fechas, eliminados, insertados) y crea una tarjeta. Presentas UN resumen con esos conteos ("Son 51 sábados; quito a Dulce y Turi, pongo a Betzaira, y el 18 va Martha") y dices "confirma la tarjeta". NO vuelves a preguntar ni enumeras las 51 fechas.

Ejemplo 3 — el tool reporta cobertura:
Si un tool devuelve error "cobertura" con fechas que quedarían sin nadie, NO insistes: explicas cuáles fechas quedarían vacías y propones agregar a alguien o dejar a alguien. Nunca dices solo "intenta de nuevo"."""


# ── BD helpers ────────────────────────────────────────────────────────────────

def _db():
    conn = sqlite3.connect(Config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _roster_texto():
    """Roster de empleados activos (dinámico, para inyectar en el system prompt)."""
    conn = _db()
    try:
        return AT.roster_texto(conn)
    finally:
        conn.close()


def _uso_mensual():
    hoy = date.today()
    mes_inicio = f"{hoy.year}-{hoy.month:02d}-01"
    conn = _db()
    try:
        total = conn.execute(
            "SELECT COALESCE(SUM(costo_usd),0) FROM uso_ia WHERE fecha >= ?",
            (mes_inicio,),
        ).fetchone()[0]
        row = conn.execute(
            "SELECT valor FROM configuracion WHERE clave='limite_mensual_ia_usd'"
        ).fetchone()
        limite = float(row["valor"]) if row else 5.0
    finally:
        conn.close()
    return float(total), limite


def _registrar_uso(tokens_in, tokens_out, costo, exito, error_msg=None):
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO uso_ia (funcion, modelo, tokens_input, tokens_output, costo_usd, exito, error_message) "
            "VALUES (?,?,?,?,?,?,?)",
            (_MODULO, _MODEL, tokens_in, tokens_out, costo, exito, error_msg),
        )
        conn.commit()
    finally:
        conn.close()


def _guardar_mensaje(sesion_id, rol, contenido, tokens_in=None, tokens_out=None, costo=None):
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO conversaciones_ia "
            "(sesion_id, rol, contenido, fecha, tokens_input, tokens_output, costo_usd) "
            "VALUES (?, ?, ?, datetime('now','localtime'), ?, ?, ?)",
            (sesion_id, rol, contenido, tokens_in, tokens_out, costo),
        )
        conn.commit()
    finally:
        conn.close()


def _cargar_historial_claude(sesion_id, limite=20):
    """Últimos N mensajes en formato Claude API (role/content)."""
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT rol, contenido FROM conversaciones_ia "
            "WHERE sesion_id=? ORDER BY id DESC LIMIT ?",
            (sesion_id, limite),
        ).fetchall()
    finally:
        conn.close()
    rows.reverse()
    return [{"role": r["rol"], "content": r["contenido"]} for r in rows]


def _cargar_historial_render(sesion_id):
    """Todos los mensajes de la sesión para renderizar en la página."""
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT rol, contenido, fecha FROM conversaciones_ia "
            "WHERE sesion_id=? ORDER BY id ASC LIMIT 200",
            (sesion_id,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _cambios_pendientes_sesion(sesion_id):
    _asegurar_esquema()
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT id, descripcion_humana, sql, tabla, tipo, kind FROM cambios_pendientes "
            "WHERE sesion_id=? AND estado='pendiente' ORDER BY id",
            (sesion_id,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


# ── Migración / esquema de cambios estructurados ──────────────────────────────

_ESQUEMA_OK = False


def _asegurar_esquema():
    """Añade columnas kind/payload_json a cambios_pendientes si faltan (self-healing)."""
    global _ESQUEMA_OK
    if _ESQUEMA_OK:
        return
    conn = _db()
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(cambios_pendientes)")}
        if "kind" not in cols:
            conn.execute("ALTER TABLE cambios_pendientes ADD COLUMN kind TEXT NOT NULL DEFAULT 'sql'")
        if "payload_json" not in cols:
            conn.execute("ALTER TABLE cambios_pendientes ADD COLUMN payload_json TEXT")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS asistente_log ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " creado_en TEXT NOT NULL DEFAULT (datetime('now','localtime')),"
            " sesion_id TEXT, kind TEXT, params_json TEXT,"
            " registros_afectados INTEGER, exito INTEGER, error_message TEXT)"
        )
        conn.commit()
        _ESQUEMA_OK = True
    except Exception as exc:
        _log.error("No se pudo migrar cambios_pendientes/asistente_log: %s", exc)
    finally:
        conn.close()


def _registrar_asistente_log(sesion_id, kind, params, registros, exito, error=None):
    """Auditoría de escrituras del asistente (solo tools de escritura)."""
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO asistente_log "
            "(sesion_id, kind, params_json, registros_afectados, exito, error_message) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sesion_id, kind, json.dumps(params, ensure_ascii=False, default=str),
             registros, 1 if exito else 0, error),
        )
        conn.commit()
    except Exception as exc:
        _log.error("No se pudo registrar asistente_log: %s", exc)
    finally:
        conn.close()


# Turnos: qué kind es destructivo (tarjeta con CONFIRMAR tecleado)
_KIND_TIPO = {"reasignar": "DELETE", "quitar_fecha": "DELETE", "asignar_fecha": "INSERT"}


def _detalle_plan(kind, plan):
    """Texto legible del plan para mostrar bajo 'Ver detalle' en la tarjeta."""
    if kind == "reasignar":
        fechas = plan.get("fechas_afectadas", [])
        muestra = ", ".join(fechas[:8]) + ("…" if len(fechas) > 8 else "")
        return (
            f"Día: {AT._DIAS_NOMBRE[plan['dia_semana']]}  Turno: {plan['turno']}\n"
            f"Rango: {plan['desde']} → {plan['hasta']}\n"
            f"Fechas afectadas ({plan['n_fechas']}): {muestra}\n"
            f"A quitar: {plan['eliminados']}  |  A agregar: {plan['insertados']}  |  "
            f"Ya estaban (omitidos): {plan['omitidos_dup']}"
        )
    return plan.get("resumen", "")


def _registrar_cambio_estructurado(sesion_id, kind, params, plan):
    """Guarda un cambio de turnos como tarjeta pendiente (se ejecuta al confirmar)."""
    _asegurar_esquema()
    conn = _db()
    try:
        cur = conn.execute(
            "INSERT INTO cambios_pendientes "
            "(sesion_id, sql, descripcion_humana, tabla, tipo, kind, payload_json) "
            "VALUES (?, ?, ?, 'asignaciones_turnos', ?, ?, ?)",
            (
                sesion_id,
                _detalle_plan(kind, plan),
                plan.get("resumen", "Cambio de turnos"),
                _KIND_TIPO.get(kind, "UPDATE"),
                kind,
                json.dumps(params, ensure_ascii=False),
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _tool_turnos(nombre, inp, sesion_id):
    """Dispatch de las tools de dominio de turnos (lectura directa, escritura → tarjeta)."""
    conn = _db()
    try:
        if nombre == "consultar_empleados":
            return AT.tool_consultar_empleados(conn, inp)
        if nombre == "consultar_asignaciones":
            return AT.tool_consultar_asignaciones(conn, inp)
        if nombre == "resumen_cobertura":
            return AT.tool_resumen_cobertura(conn, inp)

        # Escritura: planificar (dry-run). Si hay error/cobertura, devolver al modelo.
        kind = {"reasignar_turnos_recurrentes": "reasignar",
                "asignar_turno_fecha": "asignar_fecha",
                "quitar_turno_fecha": "quitar_fecha"}[nombre]
        plan = AT.planear_por_kind(conn, kind, inp)
        if not plan.get("ok"):
            return plan
        if plan.get("sin_cobertura"):
            return {"ok": False, "error": "cobertura", "sin_cobertura": plan["sin_cobertura"],
                    "mensaje": "El cambio dejaría fechas sin cobertura; ajústalo antes de proponerlo."}
        if kind == "quitar_fecha" and plan.get("dejaria_sin_cobertura"):
            return {"ok": False, "error": "cobertura", "mensaje": plan["resumen"] +
                    " Dejaría el turno sin nadie; no se puede."}
    finally:
        conn.close()

    cambio_id = _registrar_cambio_estructurado(sesion_id, kind, inp, plan)
    # Preview COMPACTO para el modelo: conteos + muestra de fechas, nunca la lista completa.
    preview = {k: plan[k] for k in plan
               if k not in ("ops", "nombres", "fechas_afectadas")}
    fechas = plan.get("fechas_afectadas")
    if fechas is not None:
        preview["fechas_muestra"] = fechas[:5]
        preview["fechas_total"] = len(fechas)
    return {"ok": True, "cambio_id": cambio_id, "requiere_confirmacion": True, "preview": preview}


# ── Implementación de tools ───────────────────────────────────────────────────

def _tool_obtener_fecha_hoy(_input):
    ctx = AT.contexto_fecha()
    ultimo_dia = calendar.monthrange(ctx["anio"], ctx["mes"])[1]
    ctx["mes_fin"] = f"{ctx['anio']}-{ctx['mes']:02d}-{ultimo_dia:02d}"
    return ctx


def _tool_ejecutar_sql(_input):
    query = (_input.get("query") or "").strip()
    if not query:
        return {"ok": False, "error": "Query vacía"}
    if _RE_ESCRITURA.search(query):
        return {"ok": False, "error": "La query contiene operaciones no permitidas. Solo SELECT."}
    if _tiene_multiples_sentencias(query):
        return {"ok": False, "error": "Solo una sentencia SELECT a la vez."}
    if _RE_SENSIBLE.search(query):
        return {"ok": False, "error": "Consulta bloqueada: incluye datos sensibles (usuarios/contraseñas)."}
    conn = _db()
    try:
        cur = conn.execute(query)
        rows = [dict(r) for r in cur.fetchall()]
        columnas = [d[0] for d in cur.description] if cur.description else []
        return {"ok": True, "rows": rows, "columnas": columnas, "row_count": len(rows)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        conn.close()


def _tool_proponer_cambio(_input, sesion_id):
    sql = (_input.get("sql") or "").strip()
    desc = (_input.get("descripcion_humana") or "").strip()
    tabla = (_input.get("tabla") or "").strip().lower()
    tipo = (_input.get("tipo") or "").strip().upper()

    if not all([sql, desc]):
        return {"ok": False, "error": "Faltan parámetros requeridos (sql, descripcion_humana)"}

    # La tabla y el tipo se derivan del SQL REAL (no de lo que declare el modelo),
    # se exige tabla en whitelist y WHERE en UPDATE/DELETE.
    ok, error, tabla, tipo = _validar_sql_cambio(sql)
    if not ok:
        return {"ok": False, "error": error}

    conn = _db()
    try:
        cur = conn.execute(
            "INSERT INTO cambios_pendientes (sesion_id, sql, descripcion_humana, tabla, tipo) "
            "VALUES (?,?,?,?,?)",
            (sesion_id, sql, desc, tabla, tipo),
        )
        conn.commit()
        cambio_id = cur.lastrowid
    finally:
        conn.close()

    return {"ok": True, "cambio_id": cambio_id, "requiere_confirmacion": True}


def _tool_buscar_conversaciones(_input):
    fecha_desde = (_input.get("fecha_desde") or "").strip()
    fecha_hasta = (_input.get("fecha_hasta") or "").strip()
    palabras = (_input.get("palabras_clave") or "").strip()

    conditions = []
    params = []
    if fecha_desde:
        conditions.append("fecha >= ?")
        params.append(fecha_desde + " 00:00:00")
    if fecha_hasta:
        conditions.append("fecha <= ?")
        params.append(fecha_hasta + " 23:59:59")
    if palabras:
        conditions.append("contenido LIKE ?")
        params.append(f"%{palabras}%")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    query = (
        f"SELECT sesion_id, rol, contenido, fecha FROM conversaciones_ia "
        f"{where} ORDER BY fecha DESC LIMIT 20"
    )
    conn = _db()
    try:
        rows = [dict(r) for r in conn.execute(query, params).fetchall()]
    finally:
        conn.close()

    rows.reverse()
    return {"ok": True, "mensajes": rows, "total": len(rows)}


_TOOLS_TURNOS = {
    "consultar_empleados", "consultar_asignaciones", "resumen_cobertura",
    "reasignar_turnos_recurrentes", "asignar_turno_fecha", "quitar_turno_fecha",
}


def _ejecutar_tool(nombre, inp, sesion_id):
    if nombre == "obtener_fecha_hoy":
        return _tool_obtener_fecha_hoy(inp)
    elif nombre == "ejecutar_sql_lectura":
        return _tool_ejecutar_sql(inp)
    elif nombre == "proponer_cambio_datos":
        return _tool_proponer_cambio(inp, sesion_id)
    elif nombre == "buscar_conversaciones_pasadas":
        return _tool_buscar_conversaciones(inp)
    elif nombre in _TOOLS_TURNOS:
        return _tool_turnos(nombre, inp, sesion_id)
    return {"ok": False, "error": f"Tool desconocida: {nombre}"}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@asistente_bp.route("/asistente")
@solo_admin
def asistente_index():
    sesion_id = request.cookies.get("sesion_ia")
    es_nueva = not sesion_id
    if es_nueva:
        sesion_id = str(uuid.uuid4())

    historial = [] if es_nueva else _cargar_historial_render(sesion_id)
    cambios = [] if es_nueva else _cambios_pendientes_sesion(sesion_id)

    resp = make_response(render_template(
        "asistente.html",
        sesion_id=sesion_id,
        historial=historial,
        cambios_pendientes=cambios,
    ))
    if es_nueva:
        resp.set_cookie("sesion_ia", sesion_id, max_age=60 * 60 * 24 * 30)
    return resp


@asistente_bp.route("/asistente/api/mensaje", methods=["POST"])
@solo_admin
def api_mensaje():
    _asegurar_esquema()
    data = request.get_json(silent=True) or {}
    mensaje = (data.get("mensaje") or "").strip()
    sesion_id = (data.get("sesion_id") or "").strip()

    if not mensaje:
        return jsonify({"ok": False, "error": "Mensaje vacío"}), 400
    if not sesion_id:
        return jsonify({"ok": False, "error": "sesion_id requerido"}), 400

    total_mes, limite = _uso_mensual()
    if total_mes >= limite:
        return jsonify({
            "ok": False,
            "limite_alcanzado": True,
            "error": f"Límite mensual de IA alcanzado (${total_mes:.4f} / ${limite:.2f} USD)",
        }), 429

    _guardar_mensaje(sesion_id, "user", mensaje)

    messages = _cargar_historial_claude(sesion_id, limite=20)

    # SDK con reintentos automáticos (429/5xx/timeout) con backoff exponencial.
    client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY, max_retries=3)

    # System prompt en dos bloques: el estable (reglas + roster + ejemplos) se
    # cachea (~10% en requests subsecuentes); la fecha va aparte para no
    # invalidar la caché cada minuto. El roster se regenera de la BD cada request
    # pero cambia rara vez, así que la caché se mantiene entre mensajes.
    ctx = AT.contexto_fecha()
    bloque_estable = _SYSTEM_PROMPT + "\n\n" + _roster_texto() + "\n\n" + _FEWSHOT
    system_blocks = [
        {"type": "text", "text": bloque_estable, "cache_control": {"type": "ephemeral"}},
        {"type": "text",
         "text": f"FECHA Y HORA ACTUAL (America/Mexico_City): {ctx['dia_semana']} "
                 f"{ctx['fecha']}, {ctx['hora']}. Úsala para todo lo relativo."},
    ]

    tokens_totales_in = tokens_totales_out = 0
    costo_total = 0.0
    respuesta_final = None
    cambios_generados = []

    for _ in range(_MAX_ITER):
        try:
            response = client.messages.create(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                system=system_blocks,
                tools=TOOLS,
                messages=messages,
            )
        except Exception as exc:
            _log.error("asistente: error Claude: %s", exc)
            _registrar_uso(0, 0, 0.0, 0, str(exc))
            return jsonify({"ok": False, "error": f"Error de IA: {exc}"}), 500

        tokens_in = response.usage.input_tokens
        tokens_out = response.usage.output_tokens
        costo = calcular_costo(_MODEL, tokens_in, tokens_out)
        tokens_totales_in += tokens_in
        tokens_totales_out += tokens_out
        costo_total += costo
        _registrar_uso(tokens_in, tokens_out, costo, 1)

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason in ("end_turn", "max_tokens"):
            for block in response.content:
                if hasattr(block, "text"):
                    respuesta_final = block.text
                    break
            break

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                resultado = _ejecutar_tool(block.name, block.input, sesion_id)
                if resultado.get("cambio_id"):
                    cambios_generados.append(resultado["cambio_id"])
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(resultado, ensure_ascii=False, default=str),
                })
            messages.append({"role": "user", "content": tool_results})
            continue

        break

    if respuesta_final is None:
        respuesta_final = (
            "Hice varias consultas pero me quedé sin cerrar la respuesta. "
            "Dime en una frase qué necesitas exactamente y lo resuelvo."
        )

    _guardar_mensaje(
        sesion_id, "assistant", respuesta_final,
        tokens_totales_in, tokens_totales_out, costo_total,
    )
    log_action(
        "Asistente sesion=%s in=%d out=%d costo=$%.6f",
        sesion_id[:8], tokens_totales_in, tokens_totales_out, costo_total,
    )

    cambios_detalle = []
    if cambios_generados:
        conn = _db()
        try:
            for cid in cambios_generados:
                row = conn.execute(
                    "SELECT id, descripcion_humana, sql, tabla, tipo, kind FROM cambios_pendientes WHERE id=?",
                    (cid,),
                ).fetchone()
                if row:
                    cambios_detalle.append(dict(row))
        finally:
            conn.close()

    return jsonify({
        "ok": True,
        "respuesta": respuesta_final,
        "cambios_pendientes": cambios_detalle,
        "costo_usd": round(costo_total, 6),
    })


@asistente_bp.route("/asistente/api/ejecutar_cambio/<int:cambio_id>", methods=["POST"])
@solo_admin
def api_ejecutar_cambio(cambio_id):
    _asegurar_esquema()
    conn = _db()
    try:
        cambio = conn.execute(
            "SELECT * FROM cambios_pendientes WHERE id=? AND estado='pendiente'",
            (cambio_id,),
        ).fetchone()
        if not cambio:
            return jsonify({"ok": False, "error": "Cambio no encontrado o ya procesado"}), 404

        kind = (cambio["kind"] if "kind" in cambio.keys() else "sql") or "sql"
        sesion_id = cambio["sesion_id"]
        desc = cambio["descripcion_humana"]

        # ── Cambios de TURNOS: ejecución atómica en el módulo de dominio ──
        if kind != "sql":
            params = json.loads(cambio["payload_json"] or "{}")
            res = AT.ejecutar_por_kind(conn, kind, params, dry_run=False)
            if not res.get("ok"):
                _registrar_asistente_log(sesion_id, kind, params, 0, False, res.get("error"))
                motivo = res.get("mensaje") or res.get("error") or "No se pudo ejecutar."
                return jsonify({"ok": False, "error": motivo}), 400
            registros = res.get("eliminados", 0) + res.get("insertados", 0)
            conn.execute(
                "UPDATE cambios_pendientes SET estado='ejecutado', "
                "fecha_resolucion=datetime('now','localtime'), registros_afectados=? WHERE id=?",
                (registros, cambio_id),
            )
            conn.commit()
            _registrar_asistente_log(sesion_id, kind, params, registros, True, None)
            log_action(
                "Asistente EJECUTADO(turnos) cambio_id=%d sesion=%s kind=%s registros=%d",
                cambio_id, sesion_id[:8], kind, registros,
            )
            mensaje = "Listo. " + res.get("resumen", desc)
            _guardar_mensaje(sesion_id, "assistant", mensaje)
            return jsonify({"ok": True, "registros_afectados": registros, "mensaje": mensaje})

        # ── Cambios SQL de una sola sentencia (long-tail: gastos, fondos, etc.) ──
        ok_val, err_val, _, _ = _validar_sql_cambio(cambio["sql"])
        if not ok_val:
            conn.execute(
                "UPDATE cambios_pendientes SET estado='cancelado', "
                "fecha_resolucion=datetime('now','localtime') WHERE id=?",
                (cambio_id,),
            )
            conn.commit()
            log_action("Asistente cambio_id=%d BLOQUEADO por validación: %s", cambio_id, err_val)
            return jsonify({"ok": False, "error": f"Cambio bloqueado: {err_val}"}), 400

        try:
            cur = conn.execute(cambio["sql"])
            registros = cur.rowcount
            conn.execute(
                "UPDATE cambios_pendientes SET estado='ejecutado', "
                "fecha_resolucion=datetime('now','localtime'), registros_afectados=? WHERE id=?",
                (registros, cambio_id),
            )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            _log.error("asistente ejecutar_cambio id=%d error: %s", cambio_id, exc)
            return jsonify({"ok": False, "error": f"Error al ejecutar: {exc}"}), 500

        log_action(
            "Asistente EJECUTADO cambio_id=%d sesion=%s tabla=%s tipo=%s desc='%s' registros=%d",
            cambio_id, sesion_id[:8], cambio["tabla"],
            cambio["tipo"], desc, registros,
        )
        tipo = cambio["tipo"]
    finally:
        conn.close()

    _verbos = {"INSERT": "creado(s)", "UPDATE": "modificado(s)", "DELETE": "eliminado(s)"}
    verbo = _verbos.get(tipo, "afectado(s)")
    mensaje = f"Listo. {desc}. {registros} registro(s) {verbo}."
    _guardar_mensaje(sesion_id, "assistant", mensaje)

    return jsonify({
        "ok": True,
        "registros_afectados": registros,
        "mensaje": mensaje,
    })


@asistente_bp.route("/asistente/api/cancelar_cambio/<int:cambio_id>", methods=["POST"])
@solo_admin
def api_cancelar_cambio(cambio_id):
    conn = _db()
    try:
        cambio = conn.execute(
            "SELECT id, sesion_id, descripcion_humana, tabla FROM cambios_pendientes "
            "WHERE id=? AND estado='pendiente'",
            (cambio_id,),
        ).fetchone()
        if not cambio:
            return jsonify({"ok": False, "error": "Cambio no encontrado"}), 404
        conn.execute(
            "UPDATE cambios_pendientes SET estado='cancelado', "
            "fecha_resolucion=datetime('now','localtime') WHERE id=?",
            (cambio_id,),
        )
        conn.commit()
        log_action(
            "Asistente CANCELADO cambio_id=%d sesion=%s tabla=%s desc='%s'",
            cambio_id, cambio["sesion_id"][:8], cambio["tabla"], cambio["descripcion_humana"],
        )
        sesion_id = cambio["sesion_id"]
        desc = cambio["descripcion_humana"]
    finally:
        conn.close()

    mensaje = f"Cambio cancelado: {desc}."
    _guardar_mensaje(sesion_id, "assistant", mensaje)

    return jsonify({"ok": True, "mensaje": mensaje})


@asistente_bp.route("/asistente/api/nueva_sesion")
@solo_admin
def api_nueva_sesion():
    sesion_id = str(uuid.uuid4())
    resp = make_response(jsonify({"sesion_id": sesion_id}))
    resp.set_cookie("sesion_ia", sesion_id, max_age=60 * 60 * 24 * 30)
    return resp
