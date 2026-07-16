"""
app.py - Entry point de SME (Software de Manejo de Estres).
"""

import calendar
import json
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash

from config import Config
from logger import get_logger, log_action, setup_logging
from modules.auth import solo_admin, _es_ajax, _get_modo
from modules.asistente import asistente_bp
from modules.configuracion import configuracion_bp
from modules.cortes import cortes_bp
from modules.cuartos import cuartos_bp
from modules.empleados import empleados_bp
from modules.fondos import fondos_bp
from modules.gastos import _descontar_de_fondo, gastos_bp
from modules.inventario import inventario_bp
from modules.ingresos import ingresos_bp
from modules.reportes import reportes_bp
from modules.tiempo import dia_operativo

_DIAS_HEADER = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]
_DIAS_SHORT  = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
_MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

_CATEGORIA_MAP = {
    "Renta":      "Otro",
    "CFE":        "Luz",
    "StarTV":     "Otro",
    "Contadores": "Otro",
}


def _fecha_es(dt: datetime) -> str:
    return f"{_DIAS_HEADER[dt.weekday()]}, {dt.day} de {_MESES[dt.month - 1]} {dt.year}"


def _lunes_semana(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _add_months(d: date, n: int) -> date:
    m = d.month + n
    a = d.year + (m - 1) // 12
    m = (m - 1) % 12 + 1
    max_d = calendar.monthrange(a, m)[1]
    return date(a, m, min(d.day, max_d))


def _proxima_fecha_gf(concepto: str, frecuencia: str, dia: int, ultimo_pago: str | None) -> date | None:
    hoy = date.today()
    intervalos = {"mensual": 1, "bimestral": 2}
    meses = intervalos.get(frecuencia, 1)

    def en_mes(a: int, m: int, d_target: int) -> date:
        max_d = calendar.monthrange(a, m)[1]
        return date(a, m, min(d_target, max_d))

    if ultimo_pago:
        base = date.fromisoformat(ultimo_pago)
        nxt  = _add_months(base.replace(day=1), meses)
        prox = en_mes(nxt.year, nxt.month, dia)
    else:
        prox = en_mes(hoy.year, hoy.month, dia)
        if prox < hoy:
            prox = _add_months(prox, meses)

    return prox if prox >= hoy else None


def _auto_renta_semanal(conn) -> None:
    """Crea el pago semanal de renta del último domingo si todavía no existe."""
    hoy = date.today()
    dias_hasta_dom = (hoy.weekday() + 1) % 7
    ultimo_domingo  = hoy - timedelta(days=dias_hasta_dom)
    lunes_esa_semana = ultimo_domingo - timedelta(days=6)
    descripcion = f"Pago renta semana del {lunes_esa_semana} al {ultimo_domingo}"

    existe = conn.execute(
        "SELECT id FROM gastos_extras WHERE descripcion=?", (descripcion,)
    ).fetchone()
    if existe:
        return

    fondo = conn.execute(
        "SELECT id FROM fondos WHERE nombre='Renta' AND activo=1"
    ).fetchone()
    if not fondo:
        return

    cur = conn.execute(
        "INSERT INTO gastos_extras (fecha, categoria, monto, descripcion) VALUES (?,?,?,?)",
        (ultimo_domingo.isoformat(), "Renta", 10000.0, descripcion),
    )
    gasto_id = cur.lastrowid
    conn.execute(
        "INSERT INTO movimientos_fondos "
        "(fondo_id, fecha, tipo, monto, concepto, gasto_extra_id) VALUES (?,?,?,?,?,?)",
        (fondo["id"], ultimo_domingo.isoformat(), "retiro", 10000.0, descripcion, gasto_id),
    )
    conn.execute(
        "UPDATE gastos_extras SET fondo_descontado_id=? WHERE id=?",
        (fondo["id"], gasto_id),
    )
    conn.commit()
    log_action("Pago renta semanal automático registrado: %s ($10,000)", descripcion)


def _dash_data(db_path: str) -> dict:
    hoy      = date.today()
    lunes    = _lunes_semana(hoy)
    domingo  = lunes + timedelta(days=6)
    hace7    = hoy - timedelta(days=6)
    lim15    = hoy + timedelta(days=15)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row

        # --- Pago automático de renta semanal (antes de cualquier query) ---
        _auto_renta_semanal(conn)

        # --- Tarjetas del día ---
        # El ingreso se registra por día operativo (los cortes lo escriben bajo
        # esa fecha), así que "hoy" usa el día operativo, no el de calendario.
        op_hoy = dia_operativo().isoformat()
        ing_dia = float(conn.execute(
            "SELECT COALESCE(SUM(total_neto),0) AS t FROM ingresos_diarios WHERE fecha=?",
            (op_hoy,)
        ).fetchone()["t"])
        gas_dia = float(conn.execute(
            "SELECT COALESCE(SUM(monto),0) AS t FROM gastos_extras WHERE fecha=?",
            (hoy.isoformat(),)
        ).fetchone()["t"])

        # --- Resumen semana ---
        ing_sem = float(conn.execute(
            "SELECT COALESCE(SUM(total_neto),0) AS t FROM ingresos_diarios WHERE fecha BETWEEN ? AND ?",
            (lunes.isoformat(), hoy.isoformat())
        ).fetchone()["t"])
        gas_sem = float(conn.execute(
            "SELECT COALESCE(SUM(monto),0) AS t FROM gastos_extras WHERE fecha BETWEEN ? AND ?",
            (lunes.isoformat(), hoy.isoformat())
        ).fetchone()["t"])
        utilidad_sem = ing_sem - gas_sem

        # --- Desglose efectivo / tarjeta / transferencia (día y semana) ---
        # total_neto = efectivo + tarjeta + transferencia − comisión_tarjeta.
        # La tarjeta y la transferencia caen en el banco; el efectivo es físico.
        dsg_dia = conn.execute(
            "SELECT COALESCE(SUM(monto_efectivo),0) efe, COALESCE(SUM(monto_tarjeta),0) tarj, "
            "COALESCE(SUM(monto_transferencia),0) transf FROM ingresos_diarios WHERE fecha=?",
            (op_hoy,),
        ).fetchone()
        dsg_sem = conn.execute(
            "SELECT COALESCE(SUM(monto_efectivo),0) efe, COALESCE(SUM(monto_tarjeta),0) tarj, "
            "COALESCE(SUM(monto_transferencia),0) transf, COALESCE(SUM(comision_tarjeta),0) comis "
            "FROM ingresos_diarios WHERE fecha BETWEEN ? AND ?",
            (lunes.isoformat(), hoy.isoformat()),
        ).fetchone()

        # --- Fondo Reserva ---
        fondo_res = conn.execute(
            """SELECT f.nombre, f.meta_mensual,
                      COALESCE(SUM(CASE WHEN m.tipo='deposito' THEN m.monto ELSE 0 END),0) -
                      COALESCE(SUM(CASE WHEN m.tipo='retiro'   THEN m.monto ELSE 0 END),0) AS saldo
               FROM fondos f
               LEFT JOIN movimientos_fondos m ON m.fondo_id = f.id
               WHERE f.activo=1 AND LOWER(f.nombre) LIKE '%reserva%'
               GROUP BY f.id"""
        ).fetchone()
        reserva = None
        if fondo_res:
            s = float(fondo_res["saldo"])
            meta = float(fondo_res["meta_mensual"] or 0)
            reserva = {
                "nombre": fondo_res["nombre"],
                "saldo": s,
                "meta": meta,
                "pct": min(100, int(s / meta * 100)) if (meta > 0 and s > 0) else 0,
            }

        # --- Aportes semanales pendientes ---
        ap_rows = conn.execute(
            """SELECT f.nombre, f.aporte_periodico
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
        aportes_pendientes = [dict(r) for r in ap_rows]

        # Fondos activos (para el selector "pagar desde" en los recordatorios)
        fondos_dash = [
            {"id": r["id"], "nombre": r["nombre"]}
            for r in conn.execute(
                "SELECT id, nombre FROM fondos WHERE activo=1 ORDER BY id"
            ).fetchall()
        ]

        # --- Gráfica últimos 7 días ---
        raw_chart = {
            r["fecha"]: float(r["t"])
            for r in conn.execute(
                "SELECT fecha, COALESCE(SUM(total_neto),0) AS t FROM ingresos_diarios "
                "WHERE fecha BETWEEN ? AND ? GROUP BY fecha",
                (hace7.isoformat(), hoy.isoformat()),
            ).fetchall()
        }
        chart_dias = []
        for i in range(7):
            d = hace7 + timedelta(days=i)
            chart_dias.append({
                "fecha": d.isoformat(),
                "label": _DIAS_SHORT[d.weekday()],
                "total": raw_chart.get(d.isoformat(), 0.0),
                "es_hoy": d == hoy,
            })
        max_chart = max((c["total"] for c in chart_dias), default=0) or 1
        for c in chart_dias:
            c["pct"] = int(c["total"] / max_chart * 100)

        # --- Turnos de la semana ---
        dias_semana = [(lunes + timedelta(days=i)).isoformat() for i in range(7)]
        dias_info   = [
            {"fecha": d, "label": _DIAS_SHORT[(lunes + timedelta(days=i)).weekday()]}
            for i, d in enumerate(dias_semana)
        ]
        turno_matrix = {t: {d: [] for d in dias_semana} for t in ("manana", "tarde", "noche")}
        for row in conn.execute(
            """SELECT at.fecha, e.nombre, e.es_socio, t.nombre AS turno
               FROM asignaciones_turnos at
               JOIN empleados e ON e.id = at.empleado_id
               JOIN turnos    t ON t.id = at.turno_id
               WHERE at.fecha BETWEEN ? AND ?
               ORDER BY at.fecha, t.id""",
            (lunes.isoformat(), domingo.isoformat()),
        ).fetchall():
            t = row["turno"]
            if t in turno_matrix:
                turno_matrix[t][row["fecha"]].append(
                    {"nombre": row["nombre"], "es_socio": row["es_socio"]}
                )
        turnos_rows = [
            {"key": "manana", "label": "Mañana"},
            {"key": "tarde",  "label": "Tarde"},
            {"key": "noche",  "label": "Noche"},
        ]

        # --- Recordatorios gastos fijos (próximos 15 días) ---
        gf_rows = conn.execute(
            "SELECT id, concepto, monto_estimado, frecuencia, dia_recordatorio "
            "FROM gastos_fijos WHERE activo=1 AND dia_recordatorio IS NOT NULL"
        ).fetchall()
        recordatorios = []
        for gf in gf_rows:
            ultimo_row = conn.execute(
                "SELECT MAX(fecha) AS f FROM gastos_extras WHERE descripcion=?",
                (f"Pago {gf['concepto']}",)
            ).fetchone()
            proxima = _proxima_fecha_gf(
                gf["concepto"], gf["frecuencia"],
                gf["dia_recordatorio"], ultimo_row["f"] if ultimo_row else None
            )
            if proxima is None or proxima > lim15:
                continue
            dias_f = (proxima - hoy).days
            recordatorios.append({
                "id":             gf["id"],
                "concepto":       gf["concepto"],
                "monto_estimado": float(gf["monto_estimado"] or 0),
                "proxima_fecha":  proxima.isoformat(),
                "dias_faltantes": dias_f,
                "texto_dias": (
                    "hoy" if dias_f == 0
                    else "mañana" if dias_f == 1
                    else f"en {dias_f} días"
                ),
            })
        recordatorios.sort(key=lambda x: x["proxima_fecha"])

        # --- Costo e interacciones IA del mes ---
        mes_inicio = f"{hoy.year}-{hoy.month:02d}-01"
        costo_ia_mes = float(conn.execute(
            "SELECT COALESCE(SUM(costo_usd), 0) FROM uso_ia WHERE fecha >= ?",
            (mes_inicio,),
        ).fetchone()[0])
        llamadas_ia_mes = int(conn.execute(
            "SELECT COUNT(*) FROM uso_ia WHERE fecha >= ?",
            (mes_inicio,),
        ).fetchone()[0])

    return {
        "ing_dia":          ing_dia,
        "gas_dia":          gas_dia,
        "gan_dia":          ing_dia - gas_dia,
        "ing_sem":          ing_sem,
        "gas_sem":          gas_sem,
        "utilidad_sem":     utilidad_sem,
        "tu_parte":         utilidad_sem * 0.5,
        "ing_efe_dia":      float(dsg_dia["efe"]),
        "ing_tarj_dia":     float(dsg_dia["tarj"]),
        "ing_transf_dia":   float(dsg_dia["transf"]),
        "ing_efe_sem":      float(dsg_sem["efe"]),
        "ing_tarj_sem":     float(dsg_sem["tarj"]),
        "ing_transf_sem":   float(dsg_sem["transf"]),
        "ing_comis_sem":    float(dsg_sem["comis"]),
        "ing_banco_sem":    float(dsg_sem["tarj"]) + float(dsg_sem["transf"]),
        "reserva":          reserva,
        "aportes_pendientes": aportes_pendientes,
        "fondos":           fondos_dash,
        "chart_dias":       chart_dias,
        "dias_info":        dias_info,
        "turno_matrix":     turno_matrix,
        "turnos_rows":      turnos_rows,
        "recordatorios":    recordatorios,
        "costo_ia_mes":     costo_ia_mes,
        "llamadas_ia_mes":  llamadas_ia_mes,
    }


_CLIMA_CACHE: dict = {"data": None, "ts": 0.0}

_WMO = {
    0: "despejado",
    1: "mayormente despejado", 2: "parcialmente nublado", 3: "nublado",
    45: "neblina", 48: "neblina",
    51: "llovizna", 53: "llovizna", 55: "llovizna",
    61: "lluvia leve", 63: "lluvia", 65: "lluvia intensa",
    71: "nieve leve", 73: "nieve", 75: "nieve intensa", 77: "granizo",
    80: "chubascos", 81: "chubascos", 82: "chubascos fuertes",
    95: "tormenta", 96: "tormenta", 99: "tormenta intensa",
}

_CLIMA_FALLBACK: dict = {
    "valor": "Calvillo, Ags.", "temp": None, "code": None,
    "desc": "", "categoria": "nublado", "forecast": [],
}


def _wmo_categoria(code: int) -> str:
    if code == 0:        return "despejado"
    if 1  <= code <= 3:  return "nublado"
    if 45 <= code <= 48: return "neblina"
    if 51 <= code <= 67: return "lluvia"
    if 71 <= code <= 77: return "nieve"
    if 80 <= code <= 82: return "chubascos"
    if 95 <= code <= 99: return "tormenta"
    return "nublado"


def _obtener_clima() -> dict:
    """Consulta Open-Meteo con forecast horario. Cachea 15 min. Falla silencioso."""
    global _CLIMA_CACHE
    ahora = time.time()
    if ahora - _CLIMA_CACHE["ts"] < 600 and _CLIMA_CACHE["data"]:
        return _CLIMA_CACHE["data"]

    url = (
        "https://api.open-meteo.com/v1/forecast"
        "?latitude=21.880775&longitude=-102.632289"
        "&current=temperature_2m,weather_code,is_day"
        "&hourly=temperature_2m,weather_code,is_day"
        "&forecast_days=2"
        "&timezone=America/Mexico_City"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SME-Motel/1.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())

        temp   = round(data["current"]["temperature_2m"])
        code   = int(data["current"]["weather_code"])
        es_dia = bool(data["current"].get("is_day", 1))
        desc   = _WMO.get(code, "variable")
        cat    = _wmo_categoria(code)

        # Próximas 6 horas desde la hora actual
        cur_hora  = int(data["current"]["time"][11:13])
        h_times   = data["hourly"]["time"]
        h_temps   = data["hourly"]["temperature_2m"]
        h_codes   = data["hourly"]["weather_code"]
        h_isday   = data["hourly"].get("is_day", [])
        forecast  = []
        for i in range(1, 7):
            idx = cur_hora + i
            if idx < len(h_times):
                hc = int(h_codes[idx])
                forecast.append({
                    "hora":      h_times[idx][11:16],
                    "temp":      round(h_temps[idx]),
                    "code":      hc,
                    "desc":      _WMO.get(hc, "variable"),
                    "categoria": _wmo_categoria(hc),
                    "es_dia":    bool(h_isday[idx]) if idx < len(h_isday) else True,
                })

        resultado = {
            "valor":     f"{temp}°C, {desc} — Calvillo",
            "temp":      temp,
            "code":      code,
            "desc":      desc,
            "categoria": cat,
            "es_dia":    es_dia,
            "forecast":  forecast,
        }
        _CLIMA_CACHE = {"data": resultado, "ts": ahora}
        return resultado

    except Exception:
        _CLIMA_CACHE["ts"] = ahora - 540  # cache 10 min: reintenta en ~60s
        return _CLIMA_CACHE.get("data") or _CLIMA_FALLBACK


def _gerty_context() -> dict:
    """Computa el estado de GERTY. En modo empleado siempre devuelve default."""
    modo = get_modo_actual() or "empleado"
    if not modo.startswith("admin_"):
        return {"estado": "default", "contexto": {}}

    hora = datetime.now().hour
    try:
        with sqlite3.connect(Config.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row

            fondos_rows = conn.execute(
                """SELECT LOWER(f.nombre) AS nombre,
                          COALESCE(SUM(CASE WHEN m.tipo='deposito' THEN m.monto ELSE 0 END), 0) -
                          COALESCE(SUM(CASE WHEN m.tipo='retiro'   THEN m.monto ELSE 0 END), 0) AS saldo
                   FROM fondos f
                   LEFT JOIN movimientos_fondos m ON m.fondo_id = f.id
                   WHERE f.activo = 1
                     AND (LOWER(f.nombre) LIKE '%reserva%' OR LOWER(f.nombre) LIKE '%renta%')
                   GROUP BY f.id"""
            ).fetchall()

            reserva_baja = any(
                float(r["saldo"]) < 5000 for r in fondos_rows if "reserva" in r["nombre"]
            )
            renta_baja = any(
                float(r["saldo"]) < 5000 for r in fondos_rows if "renta" in r["nombre"]
            )

            hoy_str = date.today().isoformat()
            hay_turno = conn.execute(
                """SELECT 1 FROM asignaciones_turnos at
                   JOIN empleados e ON e.id = at.empleado_id
                   WHERE at.fecha = ? AND LOWER(e.nombre) LIKE '%turi%'
                   LIMIT 1""",
                (hoy_str,),
            ).fetchone() is not None

    except Exception:
        reserva_baja = renta_baja = hay_turno = False

    if 1 <= hora <= 6:
        estado = "dormido"
    elif reserva_baja or renta_baja:
        estado = "alerta"
    elif hay_turno:
        estado = "turno_turi"
    else:
        estado = "default"

    return {
        "estado": estado,
        "contexto": {
            "hora_servidor": hora,
            "hay_turno_turi": hay_turno,
            "fondo_reserva_bajo": reserva_baja,
            "fondo_renta_bajo": renta_baja,
        },
    }


def get_modo_actual() -> str:
    """Modo del dispositivo actual (según su sesión). '' si no ha iniciado sesión."""
    return _get_modo()


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    # Detrás de un proxy (tailscale serve para HTTPS): confiar en
    # X-Forwarded-Proto/Host para que Flask sepa que es HTTPS (url_for https,
    # cookies seguras). Sin proxy (HTTP directo) no cambia nada.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    setup_logging()
    log = get_logger()
    log.info("SME iniciado (puerto %s, debug=%s)", Config.PORT, Config.DEBUG)

    # --- Blueprints ---
    app.register_blueprint(asistente_bp)
    app.register_blueprint(cortes_bp)
    app.register_blueprint(cuartos_bp)
    app.register_blueprint(ingresos_bp)
    app.register_blueprint(gastos_bp)
    app.register_blueprint(empleados_bp)
    app.register_blueprint(configuracion_bp)
    app.register_blueprint(fondos_bp)
    app.register_blueprint(inventario_bp)
    app.register_blueprint(reportes_bp)

    # --- Filtro de moneda ($1,234) ---
    @app.template_filter("moneda")
    def moneda_filter(value):
        try:
            return f"${float(value or 0):,.0f}"
        except (TypeError, ValueError):
            return "$0"

    # --- Variables globales de template ---
    @app.context_processor
    def inject_globals():
        clima_obj = _obtener_clima()
        modo = get_modo_actual()
        es_admin = modo.startswith("admin_")
        admin_nombre = None
        if modo == "admin_turi":
            admin_nombre = "Turi"
        elif modo == "admin_gabriel":
            admin_nombre = "Gabriel"
        usuario_nombre = admin_nombre or ("Mostrador" if modo == "empleado" else "")
        return {
            "fecha_actual":  _fecha_es(datetime.now()),
            "clima":         clima_obj["valor"],
            "clima_data":    clima_obj,
            "gerty_state":   _gerty_context(),
            "modo_actual":   modo,
            "es_admin":      es_admin,
            "admin_nombre":  admin_nombre,
            "usuario_nombre": usuario_nombre,
        }

    @app.route("/")
    def index():
        if not (get_modo_actual() or "empleado").startswith("admin_"):
            return redirect("/cuartos")
        data = _dash_data(Config.DB_PATH)
        log_action("Visita al dashboard (/)")
        return render_template("dashboard.html", **data)

    @app.route("/api/clima")
    def api_clima():
        # Devuelve solo el HTML del widget del clima (clima_data lo inyecta el
        # context processor). Lo consume el auto-refresco del dashboard.
        return render_template("_clima_widget.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "GET" and get_modo_actual():
            return redirect(url_for("index"))

        with sqlite3.connect(Config.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            usuarios = [
                dict(row) for row in conn.execute(
                    "SELECT id, username, nombre_display, rol FROM usuarios "
                    "WHERE activo = 1 ORDER BY rol DESC, nombre_display"
                ).fetchall()
            ]

        error = None
        prefill_username = None
        if request.method == "POST":
            username = (request.form.get("username") or "").strip().lower()
            password = request.form.get("password") or ""
            with sqlite3.connect(Config.DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                usuario = conn.execute(
                    "SELECT username, password_hash, nombre_display, activo, rol "
                    "FROM usuarios WHERE username=?",
                    (username,),
                ).fetchone()
            if usuario and usuario["activo"] and check_password_hash(usuario["password_hash"], password):
                # El modo se deriva del rol; solo 'admin' obtiene privilegios de admin.
                session["modo"] = (
                    f"admin_{usuario['username']}" if usuario["rol"] == "admin" else "empleado"
                )
                session.permanent = True
                log_action("Login exitoso: %s (rol=%s)", usuario["username"], usuario["rol"])
                return redirect(url_for("index"))
            else:
                log_action("Login fallido: usuario '%s'", username)
                error = "Usuario o contraseña incorrectos"
                prefill_username = username
        return render_template(
            "login.html", error=error, usuarios=usuarios, prefill_username=prefill_username
        )

    @app.route("/logout", methods=["POST"])
    def logout():
        modo = get_modo_actual()
        session.clear()
        log_action("Logout: %s", modo or "(sin sesión)")
        return redirect(url_for("login"))

    # ── Gate global: todo requiere sesión iniciada (seguro para remoto) ──
    _ENDPOINTS_PUBLICOS = {"login", "static"}

    @app.before_request
    def _forzar_https():
        # Rebota a la URL HTTPS SOLO si entran por otro host (ej. la IP de
        # Tailscale por HTTP). Se decide por el HOST, no por is_secure: detrás
        # de `tailscale serve` is_secure llega en False y usarlo causaba un
        # bucle de redirección en la propia URL HTTPS. El host destino ya se
        # sirve por HTTPS, así que nunca se redirige a sí mismo.
        destino = Config.HTTPS_REDIRECT_HOST
        if not destino:
            return
        host = (request.host or "").split(":")[0]
        if host in (destino, "localhost", "127.0.0.1", "::1"):
            return
        url = f"https://{destino}{request.path}"
        if request.query_string:
            url += "?" + request.query_string.decode("latin-1")
        return redirect(url, code=301)

    @app.before_request
    def _requiere_login():
        if request.endpoint in _ENDPOINTS_PUBLICOS:
            return
        if not get_modo_actual():
            if _es_ajax():
                return jsonify({"error": "No autenticado"}), 401
            return redirect(url_for("login"))

    @app.route("/api/gerty/estado")
    def gerty_estado():
        return jsonify(_gerty_context())

    @app.route("/dashboard/api/marcar-pagada", methods=["POST"])
    @solo_admin
    def marcar_pagada():
        data  = request.get_json(silent=True) or {}
        gf_id = data.get("gasto_fijo_id")
        if not gf_id:
            return jsonify({"ok": False, "error": "Falta gasto_fijo_id"}), 400

        with sqlite3.connect(Config.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            gf = conn.execute(
                "SELECT concepto, monto_estimado FROM gastos_fijos WHERE id=? AND activo=1",
                (gf_id,)
            ).fetchone()
            if not gf:
                return jsonify({"ok": False, "error": "Gasto fijo no encontrado"}), 404

            concepto    = gf["concepto"]
            monto       = float(gf["monto_estimado"] or 0)
            categoria   = _CATEGORIA_MAP.get(concepto, "Otro")
            descripcion = f"Pago {concepto}"
            hoy         = date.today().isoformat()

            cur = conn.execute(
                "INSERT INTO gastos_extras (fecha, categoria, monto, descripcion) VALUES (?,?,?,?)",
                (hoy, categoria, monto, descripcion),
            )
            gasto_id = cur.lastrowid

            # Fondo opcional: si el usuario eligió pagarlo desde un fondo, se
            # descuenta de ahí; si no, sale del dinero de la semana (baja utilidad).
            fondo_row, _saldo = _descontar_de_fondo(
                conn, data.get("fondo_id"), monto, hoy, descripcion, gasto_id
            )
            conn.commit()
            nombre_fondo = fondo_row["nombre"] if fondo_row else None

        log_action(
            "Gasto fijo '%s' marcado pagado → gastos_extras id=%d ($%.2f)%s",
            concepto, gasto_id, monto,
            f" desde fondo '{nombre_fondo}'" if nombre_fondo else " (dinero de la semana)",
        )
        return jsonify({"ok": True, "gasto_id": gasto_id, "nombre_fondo": nombre_fondo})

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)
