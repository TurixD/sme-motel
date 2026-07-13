"""
cortes.py - Módulo de cortes de turno (v2.3).

Flujo simplificado: empleado declara bruto en caja y cuenta de inmediato para
ingresos_diarios. Admin puede editar (corrige) o anular (invalida) después,
en cualquier momento. No hay paso de "confirmar".
Sueldos se manejan por separado (lógica semanal automática de v1).
"""

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, time as dtime, timedelta

from flask import Blueprint, jsonify, render_template, request

from config import Config
from logger import log_action
from modules.auth import _get_modo, solo_admin
from modules.tiempo import dia_operativo

cortes_bp = Blueprint("cortes", __name__)

_TURNOS_ORDEN  = ["manana", "tarde", "noche"]
_TURNO_LABELS  = {"manana": "Mañana", "tarde": "Tarde", "noche": "Noche"}

# Ventanas horarias para que el EMPLEADO pueda declarar (hora inicio inclusiva, fin inclusiva)
_VENTANA_HORAS = {"manana": (15, 16), "tarde": (22, 23), "noche": (7, 9)}
_VENTANA_LABEL = {"manana": "Ventana: 15:00 – 17:00", "tarde": "Ventana: 22:00 – 00:00", "noche": "Ventana: 07:00 – 10:00"}


def _ventanas_activas() -> dict:
    hora = datetime.now().hour
    return {
        t: (inicio <= hora <= fin)
        for t, (inicio, fin) in _VENTANA_HORAS.items()
    }


def _noche_declarada(conn, fecha_iso: str) -> bool:
    """True si la noche de ese día operativo ya tiene corte válido."""
    return conn.execute(
        """SELECT 1 FROM cortes_turno
           WHERE fecha = ? AND turno = 'noche' AND estado IN ('declarado', 'editado', 'auto')
           LIMIT 1""",
        (fecha_iso,),
    ).fetchone() is not None


def dia_operativo_efectivo(conn, now=None):
    """
    Día operativo que debe MOSTRARSE, considerando el corte de la noche pendiente.

    El ciclo (08:00–08:00) no se "completa" solo por dar las 8am: se mantiene el
    ciclo anterior hasta que su corte de noche esté hecho, o hasta las 10am como
    tope. Así, si la noche se corta tarde (8–10am), la lista y el corte siguen
    mostrando los cuartos del ciclo en vez de reiniciarse a cero.
    """
    now = now or datetime.now()
    hoy = now.date()
    if now.hour < 8:
        return hoy - timedelta(days=1)          # madrugada: noche del ciclo anterior en curso
    prev = hoy - timedelta(days=1)              # ciclo cuya noche terminó a las 8am de hoy
    if now.hour < 10 and not _noche_declarada(conn, prev.isoformat()):
        return prev                             # esperar el corte de la noche (margen 8–10am)
    return hoy


@contextmanager
def _db():
    conn = sqlite3.connect(Config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ── Cálculo de bruto ──────────────────────────────────────────

def _declarado_at(conn, fecha: str, turno: str):
    """Hora de declaración del corte de un turno (declarado/editado/auto)."""
    row = conn.execute(
        """SELECT declarado_at FROM cortes_turno
           WHERE fecha = ? AND turno = ? AND estado IN ('declarado', 'editado', 'auto') LIMIT 1""",
        (fecha, turno),
    ).fetchone()
    return row["declarado_at"] if row and row["declarado_at"] else None


def _limites_turnos(conn, fecha: str, now=None) -> dict:
    """
    Límites (datetime 'YYYY-MM-DD HH:MM:SS') entre turnos del día operativo.

    La ventana de un turno se mantiene ABIERTA hasta que ese turno hace su corte:
    el límite mañana|tarde es la hora en que se declaró el corte de la mañana (si
    ya se hizo), o el tope fijo 16:00 —extendido hasta 'ahora' si aún no se corta
    y ya pasaron las 16:00—. Igual para tarde|noche con 23:00. Así, un cuarto
    registrado después del cambio de turno pero antes del corte cuenta en el
    turno que todavía no ha cortado. El total del día es invariante (la tarde es
    acumulativa): solo cambia el reparto entre turnos.
    """
    now = now or datetime.now()
    now_str   = now.strftime("%Y-%m-%d %H:%M:%S")
    fecha_sig = (date.fromisoformat(fecha) + timedelta(days=1)).isoformat()
    ini = f"{fecha} 08:00:00"
    fin = f"{fecha_sig} 08:00:00"
    dm  = _declarado_at(conn, fecha, "manana")
    dt  = _declarado_at(conn, fecha, "tarde")

    def _clamp(x, lo, hi):
        return max(lo, min(x, hi))

    # Sin corte: la ventana se extiende hasta 'ahora', pero ACOTADA al fin de la
    # ventana de declaración del turno (mañana ≤16:59, tarde ≤23:59). Así un
    # turno nunca declarado no se traga el siguiente (protege la noche 23:00–08:00).
    b_mt = dm if dm else _clamp(now_str, f"{fecha} 16:00:00", f"{fecha} 16:59:59")
    b_tn = dt if dt else _clamp(now_str, f"{fecha} 23:00:00", f"{fecha} 23:59:59")
    b_mt = min(max(b_mt, ini), fin)          # ini <= b_mt <= fin
    b_tn = min(max(b_tn, b_mt), fin)         # b_mt <= b_tn <= fin
    return {"ini": ini, "b_mt": b_mt, "b_tn": b_tn, "fin": fin}


def _calcular_bruto(conn, turno: str, fecha: str) -> dict:
    """
    Suma rentas activas del turno, separando efectivo (entra a caja) de tarjeta
    (va al banco). Los límites entre turnos son dinámicos: la ventana de cada
    turno queda abierta hasta que ese turno declara su corte (ver _limites_turnos).
    """
    lim = _limites_turnos(conn, fecha)
    lo, hi = {
        "manana": (lim["ini"],  lim["b_mt"]),
        "tarde":  (lim["b_mt"], lim["b_tn"]),
        "noche":  (lim["b_tn"], lim["fin"]),
    }[turno]
    row = conn.execute(
        """SELECT COALESCE(SUM(precio_cobrado), 0) AS bruto,
                  COALESCE(SUM(CASE WHEN es_tarjeta = 1 THEN precio_cobrado ELSE 0 END), 0) AS tarjeta,
                  COUNT(*) AS cnt
           FROM rentas
           WHERE (fecha || ' ' || hora_registro) >= ?
             AND (fecha || ' ' || hora_registro) <  ?
             AND estado = 'activo'""",
        (lo, hi),
    ).fetchone()
    bruto   = float(row["bruto"])
    tarjeta = float(row["tarjeta"])
    return {
        "bruto":          bruto,             # total cuartos (efectivo + tarjeta)
        "bruto_tarjeta":  tarjeta,           # porción pagada con tarjeta
        "bruto_efectivo": bruto - tarjeta,   # porción en efectivo (lo que entra a caja)
        "count_rentas":   int(row["cnt"]),
    }


def _sueldos_turno(conn, turno: str, fecha: str) -> dict:
    """Suma de sueldos de los empleados asignados a un turno según el calendario."""
    row = conn.execute(
        """SELECT COALESCE(SUM(t.sueldo), 0) AS total, COUNT(*) AS cnt
           FROM asignaciones_turnos a
           JOIN turnos    t ON t.id = a.turno_id
           JOIN empleados e ON e.id = a.empleado_id
           WHERE a.fecha = ? AND t.nombre = ? AND e.activo = 1""",
        (fecha, turno),
    ).fetchone()
    return {"sueldos": float(row["total"]), "empleados": int(row["cnt"])}


def _calcular_corte(conn, turno: str, fecha: str) -> dict:
    """
    Monto esperado del corte según el flujo operativo (v2.5). Los sueldos salen
    del calendario (asignaciones_turnos), no de un valor fijo:

      mañana: cuartos_mañana − sueldos_mañana
      tarde:  (cuartos_mañana + cuartos_tarde) − (sueldos mañana + tarde + noche)
              → acumulativo: incluye la mañana, porque el efectivo se recoge a las
                11pm (junto con la mañana) y el sueldo de la noche se paga con el
                de la tarde.
      noche:  cuartos_noche, sin descontar nada (su sueldo ya se restó en la tarde).

    Devuelve el desglose para mostrarlo en la UI. `neto` es el monto del corte.
    """
    r_manana = _calcular_bruto(conn, "manana", fecha)

    if turno == "manana":
        s = _sueldos_turno(conn, "manana", fecha)
        return {
            "turno":             "manana",
            "cuartos_turno":     r_manana["bruto_efectivo"],
            "cuartos_acumulado": r_manana["bruto_efectivo"],
            "cuartos_tarjeta":   r_manana["bruto_tarjeta"],
            "count_rentas":      r_manana["count_rentas"],
            "sueldos":           s["sueldos"],
            "empleados":         s["empleados"],
            "neto":              r_manana["bruto_efectivo"] - s["sueldos"],
        }

    if turno == "tarde":
        r_tarde = _calcular_bruto(conn, "tarde", fecha)
        s_m = _sueldos_turno(conn, "manana", fecha)["sueldos"]
        s_t = _sueldos_turno(conn, "tarde",  fecha)["sueldos"]
        s_n = _sueldos_turno(conn, "noche",  fecha)["sueldos"]
        acumulado = r_manana["bruto_efectivo"] + r_tarde["bruto_efectivo"]
        sueldos   = s_m + s_t + s_n
        return {
            "turno":             "tarde",
            "cuartos_turno":     r_tarde["bruto_efectivo"],
            "cuartos_acumulado": acumulado,
            "cuartos_tarjeta":   r_manana["bruto_tarjeta"] + r_tarde["bruto_tarjeta"],
            "count_rentas":      r_tarde["count_rentas"],
            "sueldos":           sueldos,
            "empleados":         None,
            "neto":              acumulado - sueldos,
        }

    # noche: cuartos de 23:00 a 08:00, sin descuento
    r_noche = _calcular_bruto(conn, "noche", fecha)
    return {
        "turno":             "noche",
        "cuartos_turno":     r_noche["bruto_efectivo"],
        "cuartos_acumulado": r_noche["bruto_efectivo"],
        "cuartos_tarjeta":   r_noche["bruto_tarjeta"],
        "count_rentas":      r_noche["count_rentas"],
        "sueldos":           0.0,
        "empleados":         0,
        "neto":              r_noche["bruto_efectivo"],
    }


def _actualizar_ingresos_diarios(conn, fecha: str) -> dict:
    """
    Recalcula ingresos_diarios para una fecha usando los cortes válidos
    (estado 'declarado' o 'editado'; los 'anulado' no cuentan).

    El corte de la tarde es ACUMULATIVO (ya incluye la mañana), porque el
    efectivo se recoge a las 11pm y a las 8am. Por eso el total del día NO suma
    los tres cortes (duplicaría la mañana): usa el corte de la tarde —o el de
    la mañana si aún no hay tarde— más el de la noche.

    El efectivo sale de lo declarado en los cortes (lo contado en caja). La
    TARJETA se calcula aparte, de las rentas marcadas como tarjeta en el día
    operativo (no entra a caja), y la transferencia manual se preserva. Así los
    cortes ya no borran los pagos con tarjeta/transferencia.
    """

    cortes = {
        r["turno"]: float(r["bruto_declarado"])
        for r in conn.execute(
            """SELECT turno, bruto_declarado FROM cortes_turno
               WHERE fecha = ? AND estado IN ('declarado', 'editado', 'auto')""",
            (fecha,),
        ).fetchall()
    }
    pickup_dia   = cortes.get("tarde", cortes.get("manana", 0.0))  # 11pm (tarde incluye mañana)
    pickup_noche = cortes.get("noche", 0.0)                        # 8am
    efectivo     = pickup_dia + pickup_noche

    # Tarjeta del día operativo (suma de las 3 franjas: noche cruza la medianoche)
    tarjeta = sum(
        _calcular_bruto(conn, t, fecha)["bruto_tarjeta"]
        for t in ("manana", "tarde", "noche")
    )
    notas_sync = "Generado desde cortes de turno v2.5"

    existente = conn.execute(
        "SELECT id, monto_transferencia FROM ingresos_diarios WHERE fecha = ?", (fecha,)
    ).fetchone()
    transferencia = float(existente["monto_transferencia"]) if existente else 0.0
    comision   = round(tarjeta * 0.04, 2)
    total_neto = round(efectivo + tarjeta + transferencia - comision, 2)

    if existente:
        conn.execute(
            """UPDATE ingresos_diarios
               SET monto_efectivo=?, monto_tarjeta=?, monto_transferencia=?,
                   comision_tarjeta=?, total_neto=?, notas=?
               WHERE fecha=?""",
            (efectivo, tarjeta, transferencia, comision, total_neto, notas_sync, fecha),
        )
        log_action("ingresos_diarios ACTUALIZADO vía cortes: fecha=%s efec=%.2f tarj=%.2f total=%.2f",
                   fecha, efectivo, tarjeta, total_neto)
    else:
        conn.execute(
            """INSERT INTO ingresos_diarios
               (fecha, monto_efectivo, monto_tarjeta, monto_transferencia,
                comision_tarjeta, total_neto, notas, creado_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))""",
            (fecha, efectivo, tarjeta, transferencia, comision, total_neto, notas_sync),
        )
        log_action("ingresos_diarios CREADO vía cortes: fecha=%s efec=%.2f tarj=%.2f total=%.2f",
                   fecha, efectivo, tarjeta, total_neto)

    return {"ok": True, "efectivo": efectivo, "tarjeta": tarjeta, "total_neto": total_neto}


# ── Auto-corte (si nadie declara al llegar la hora límite) ────────

# Por turno: cierre = fin de su ventana (límite del cálculo, offset_días + hora);
# limite = hora a partir de la cual, si no hay corte, el sistema lo genera solo.
_AUTO_TURNOS = {
    "manana": {"cierre": (0, dtime(16, 59, 59)), "limite": (0, 17)},
    "tarde":  {"cierre": (0, dtime(23, 59, 59)), "limite": (1,  0)},
    "noche":  {"cierre": (1, dtime(8,  0,  0)),  "limite": (1, 10)},
}


def _auto_cortes(conn, now=None) -> int:
    """
    Genera cortes AUTOMÁTICOS (estado 'auto', por aprobar) de los turnos que ya
    pasaron su hora límite sin declararse, en los últimos días operativos. Usa la
    ventana FIJA del turno (no la extendida) y los deja listos para que un admin
    los apruebe/edite/anule. Cuenta provisionalmente en el ingreso del día.
    """
    now = now or datetime.now()
    fechas_tocadas = set()
    for base in (now.date() - timedelta(days=1), now.date()):
        for turno, cfg in _AUTO_TURNOS.items():
            ld, lh = cfg["limite"]
            limite = datetime.combine(base + timedelta(days=ld), dtime(hour=lh))
            if now < limite:
                continue
            fecha = base.isoformat()
            if conn.execute(
                "SELECT 1 FROM cortes_turno WHERE fecha=? AND turno=? LIMIT 1", (fecha, turno)
            ).fetchone():
                continue  # ya existe corte (declarado/auto/anulado) — no recrear

            r = _calcular_corte(conn, turno, fecha)  # ventana fija (topada) por _limites_turnos
            emp = conn.execute(
                """SELECT a.empleado_id AS eid FROM asignaciones_turnos a
                   JOIN turnos t ON t.id = a.turno_id
                   WHERE a.fecha=? AND t.nombre=? LIMIT 1""",
                (fecha, turno),
            ).fetchone()
            if not emp:
                emp = conn.execute(
                    "SELECT id AS eid FROM empleados WHERE activo=1 ORDER BY id LIMIT 1"
                ).fetchone()
            if not emp:
                continue
            cd, ch = cfg["cierre"]
            cierre_at = f"{(base + timedelta(days=cd)).isoformat()} {ch.strftime('%H:%M:%S')}"
            conn.execute(
                """INSERT INTO cortes_turno
                   (fecha, turno, empleado_id, bruto_calculado, bruto_declarado,
                    estado, declarado_at, declarado_por_nombre, notas)
                   VALUES (?,?,?,?,?,'auto',?,?,?)""",
                (fecha, turno, emp["eid"], r["neto"], r["neto"], cierre_at,
                 "Sistema (automático)", "Corte generado automáticamente — por aprobar"),
            )
            log_action("Corte AUTO generado turno=%s fecha=%s neto=%.2f", turno, fecha, r["neto"])
            fechas_tocadas.add(fecha)

    for fecha in fechas_tocadas:
        _actualizar_ingresos_diarios(conn, fecha)
    if fechas_tocadas:
        conn.commit()
    return len(fechas_tocadas)


# ── Vista principal ───────────────────────────────────────────

@cortes_bp.route("/cortes")
def index():
    modo     = _get_modo()
    es_admin = modo.startswith("admin_")

    with _db() as conn:
        _auto_cortes(conn)   # genera cortes automáticos de turnos vencidos sin declarar

        # Día operativo efectivo: se mantiene el ciclo anterior hasta que su
        # corte de noche esté hecho (o hasta las 10am), para que el corte de la
        # noche y la lista no se reinicien a cero al dar las 8am.
        op       = dia_operativo_efectivo(conn)
        hoy      = op.isoformat()        # día operativo (etiqueta + fecha de los 3 turnos)
        fecha_noche = hoy                 # la noche pertenece al mismo día operativo

        # Cargar los tres turnos del día operativo
        cortes_rows = conn.execute(
            """SELECT ct.*, e.nombre AS emp_nombre
               FROM cortes_turno ct
               LEFT JOIN empleados e ON e.id = ct.empleado_id
               WHERE ct.fecha = ?
               ORDER BY CASE ct.turno WHEN 'manana' THEN 1 WHEN 'tarde' THEN 2 ELSE 3 END""",
            (hoy,),
        ).fetchall()
        cortes_hoy = {c["turno"]: dict(c) for c in cortes_rows}

        # Cuartos registrados por turno (para avisar de turnos con cuartos sin declarar)
        rentas_por_turno = {
            t: _calcular_bruto(conn, t, hoy)["count_rentas"]
            for t in ("manana", "tarde", "noche")
        }

        # Empleados activos + sueldo del turno que trabajan (por turno_default)
        turnos_sueldos = {
            r["nombre"]: float(r["sueldo"])
            for r in conn.execute("SELECT nombre, sueldo FROM turnos").fetchall()
        }
        empleados_raw = conn.execute(
            "SELECT id, nombre, turno_default FROM empleados WHERE activo=1 ORDER BY nombre"
        ).fetchall()
        empleados = [
            {
                "id":            e["id"],
                "nombre":        e["nombre"],
                "turno_default": e["turno_default"],
                "sueldo":        turnos_sueldos.get(e["turno_default"], 0),
            }
            for e in empleados_raw
        ]

        # Asignaciones del día: {turno: [lista de empleados]} — puede haber múltiples por turno
        asig_rows = conn.execute(
            """SELECT at.empleado_id, t.nombre AS turno_nombre,
                      t.sueldo, e.nombre AS emp_nombre
               FROM asignaciones_turnos at
               JOIN turnos t ON t.id = at.turno_id
               JOIN empleados e ON e.id = at.empleado_id
               WHERE at.fecha = ? AND e.activo = 1
               ORDER BY t.nombre, e.nombre""",
            (hoy,),
        ).fetchall()
        asignaciones_hoy: dict = {}
        for a in asig_rows:
            t = a["turno_nombre"]
            if t not in asignaciones_hoy:
                asignaciones_hoy[t] = []
            asignaciones_hoy[t].append({
                "empleado_id": a["empleado_id"],
                "emp_nombre":  a["emp_nombre"],
                "sueldo":      float(a["sueldo"]),
            })

        # Nombres de admins (turi, gabriel) — para el campo "Declarado por".
        # Match usuarios.nombre_display == empleados.nombre (no hay FK directa).
        admin_nombres = [
            r["nombre_display"]
            for r in conn.execute(
                "SELECT nombre_display FROM usuarios WHERE activo=1 ORDER BY nombre_display"
            ).fetchall()
        ]

        historico_7 = []
        if es_admin:
            hace7 = (date.today() - timedelta(days=6)).isoformat()
            hist_rows = conn.execute(
                """SELECT ct.*, e.nombre AS emp_nombre
                   FROM cortes_turno ct
                   LEFT JOIN empleados e ON e.id = ct.empleado_id
                   WHERE ct.fecha BETWEEN ? AND ?
                   ORDER BY ct.fecha DESC,
                            CASE ct.turno WHEN 'manana' THEN 1 WHEN 'tarde' THEN 2 ELSE 3 END""",
                (hace7, hoy),
            ).fetchall()
            historico_7 = [dict(r) for r in hist_rows]

    ventanas = _ventanas_activas()

    return render_template(
        "cortes.html",
        hoy=hoy,
        fecha_noche=fecha_noche,
        es_admin=es_admin,
        cortes_hoy=cortes_hoy,
        rentas_por_turno=rentas_por_turno,
        empleados=empleados,
        asignaciones_hoy=asignaciones_hoy,
        admin_nombres=admin_nombres,
        turnos_sueldos=turnos_sueldos,
        historico_7=historico_7,
        turno_labels=_TURNO_LABELS,
        ventanas=ventanas,
        ventana_label=_VENTANA_LABEL,
    )


# ── API: calcular bruto ───────────────────────────────────────

@cortes_bp.route("/cortes/api/calcular_bruto/<turno>/<fecha>")
def api_calcular_bruto(turno, fecha):
    if turno not in _TURNOS_ORDEN:
        return jsonify({"ok": False, "error": "Turno inválido"}), 400
    try:
        date.fromisoformat(fecha)
    except ValueError:
        return jsonify({"ok": False, "error": "Fecha inválida"}), 400

    with _db() as conn:
        r = _calcular_corte(conn, turno, fecha)
        return jsonify({
            "ok":                True,
            "bruto_calculado":   r["neto"],            # monto esperado del corte (neto de sueldos)
            "count_rentas":      r["count_rentas"],
            "cuartos_turno":     r["cuartos_turno"],   # efectivo de este turno
            "cuartos_acumulado": r["cuartos_acumulado"],  # efectivo acumulado (tarde incluye mañana)
            "cuartos_tarjeta":   r["cuartos_tarjeta"], # pagos con tarjeta (no entran a caja)
            "sueldos":           r["sueldos"],         # sueldos descontados
        })


# ── API: declarar corte ───────────────────────────────────────

@cortes_bp.route("/cortes/api/declarar", methods=["POST"])
def api_declarar():
    data            = request.get_json(silent=True) or {}
    turno           = (data.get("turno") or "").strip()
    fecha           = data.get("fecha") or dia_operativo().isoformat()
    empleado_id     = data.get("empleado_id")
    bruto_declarado = data.get("bruto_declarado")
    declarado_por   = (data.get("declarado_por_nombre") or "").strip()
    notas           = (data.get("notas") or "").strip() or None

    if turno not in _TURNOS_ORDEN:
        return jsonify({"ok": False, "error": "Turno inválido"}), 400
    if empleado_id is None or bruto_declarado is None:
        return jsonify({"ok": False, "error": "Faltan campos requeridos"}), 400
    if not declarado_por:
        return jsonify({"ok": False, "error": "Indica quién declaró el corte"}), 400

    # Empleado solo puede declarar dentro de su ventana horaria
    modo = _get_modo()
    if not modo.startswith("admin_"):
        ventanas = _ventanas_activas()
        if not ventanas.get(turno, False):
            label = _VENTANA_LABEL.get(turno, "")
            return jsonify({"ok": False, "error": f"Fuera de ventana horaria. {label}"}), 403

    bruto_declarado = float(bruto_declarado)
    ahora           = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with _db() as conn:
        bruto_calc = _calcular_corte(conn, turno, fecha)["neto"]

        try:
            cur = conn.execute(
                """INSERT INTO cortes_turno
                   (fecha, turno, empleado_id, bruto_calculado, bruto_declarado,
                    estado, declarado_at, declarado_por_nombre, notas)
                   VALUES (?,?,?,?,?,'declarado',?,?,?)""",
                (fecha, turno, int(empleado_id), bruto_calc, bruto_declarado,
                 ahora, declarado_por, notas),
            )
            corte_id = cur.lastrowid
            _actualizar_ingresos_diarios(conn, fecha)
            conn.commit()
        except Exception as exc:
            if "UNIQUE" in str(exc):
                return jsonify({"ok": False, "error": f"Ya existe un corte de {_TURNO_LABELS[turno]} para esta fecha"}), 409
            raise

    log_action(
        "Corte DECLARADO id=%d turno=%s fecha=%s empleado_id=%d bruto=%.2f",
        corte_id, turno, fecha, int(empleado_id), bruto_declarado,
    )
    return jsonify({"ok": True, "corte_id": corte_id})


# ── API: editar corte (admin) ─────────────────────────────────

@cortes_bp.route("/cortes/api/editar/<int:corte_id>", methods=["POST"])
@solo_admin
def api_editar(corte_id):
    data            = request.get_json(silent=True) or {}
    empleado_id     = data.get("empleado_id")
    bruto_declarado = data.get("bruto_declarado")
    notas           = (data.get("notas") or "").strip() or None
    modo            = _get_modo()
    ahora           = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if empleado_id is None or bruto_declarado is None:
        return jsonify({"ok": False, "error": "Faltan campos requeridos"}), 400

    bruto_declarado = float(bruto_declarado)

    with _db() as conn:
        corte = conn.execute(
            "SELECT turno, fecha FROM cortes_turno WHERE id=?", (corte_id,)
        ).fetchone()
        if not corte:
            return jsonify({"ok": False, "error": "Corte no encontrado"}), 404

        conn.execute(
            """UPDATE cortes_turno
               SET empleado_id=?, bruto_declarado=?, notas=?,
                   estado='editado', editado_por=?, editado_at=?
               WHERE id=?""",
            (int(empleado_id), bruto_declarado, notas, modo, ahora, corte_id),
        )
        _actualizar_ingresos_diarios(conn, corte["fecha"])
        conn.commit()

    log_action("Corte EDITADO id=%d turno=%s fecha=%s por=%s bruto=%.2f",
               corte_id, corte["turno"], corte["fecha"], modo, bruto_declarado)
    return jsonify({"ok": True})


# ── API: anular corte (admin) ─────────────────────────────────

@cortes_bp.route("/cortes/api/anular/<int:corte_id>", methods=["POST"])
@solo_admin
def api_anular(corte_id):
    data   = request.get_json(silent=True) or {}
    motivo = (data.get("motivo") or "").strip() or None
    modo   = _get_modo()
    ahora  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with _db() as conn:
        corte = conn.execute(
            "SELECT turno, fecha FROM cortes_turno WHERE id=?", (corte_id,)
        ).fetchone()
        if not corte:
            return jsonify({"ok": False, "error": "Corte no encontrado"}), 404

        conn.execute(
            """UPDATE cortes_turno
               SET estado='anulado', motivo_rechazo=?, confirmado_por=?, confirmado_at=?
               WHERE id=?""",
            (motivo, modo, ahora, corte_id),
        )
        _actualizar_ingresos_diarios(conn, corte["fecha"])
        conn.commit()

    log_action("Corte ANULADO id=%d turno=%s fecha=%s por=%s motivo=%s",
               corte_id, corte["turno"], corte["fecha"], modo, motivo or "(sin motivo)")
    return jsonify({"ok": True})


# ── API: aprobar corte automático (admin) ─────────────────────

@cortes_bp.route("/cortes/api/aprobar/<int:corte_id>", methods=["POST"])
@solo_admin
def api_aprobar(corte_id):
    modo  = _get_modo()
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with _db() as conn:
        corte = conn.execute(
            "SELECT turno, fecha, estado FROM cortes_turno WHERE id=?", (corte_id,)
        ).fetchone()
        if not corte:
            return jsonify({"ok": False, "error": "Corte no encontrado"}), 404
        if corte["estado"] != "auto":
            return jsonify({"ok": False, "error": "Solo se aprueban cortes automáticos"}), 400

        # Aprobar = confirmarlo tal cual (pasa a 'declarado', deja de estar pendiente)
        conn.execute(
            "UPDATE cortes_turno SET estado='declarado', editado_por=?, editado_at=? WHERE id=?",
            (modo, ahora, corte_id),
        )
        _actualizar_ingresos_diarios(conn, corte["fecha"])
        conn.commit()

    log_action("Corte AUTO aprobado id=%d turno=%s fecha=%s por=%s",
               corte_id, corte["turno"], corte["fecha"], modo)
    return jsonify({"ok": True})


# ── Historial paginado (admin) ────────────────────────────────

@cortes_bp.route("/cortes/historial")
@solo_admin
def historial():
    POR_PAGINA   = 20
    pagina       = max(1, int(request.args.get("p", 1)))
    filtro_fecha = request.args.get("fecha", "")
    filtro_turno = request.args.get("turno", "")
    filtro_est   = request.args.get("estado", "")

    where, params = [], []
    if filtro_fecha:
        where.append("ct.fecha = ?");  params.append(filtro_fecha)
    if filtro_turno:
        where.append("ct.turno = ?");  params.append(filtro_turno)
    if filtro_est:
        where.append("ct.estado = ?"); params.append(filtro_est)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    offset    = (pagina - 1) * POR_PAGINA

    with _db() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM cortes_turno ct {where_sql}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"""SELECT ct.*, e.nombre AS emp_nombre
                FROM cortes_turno ct
                LEFT JOIN empleados e ON e.id = ct.empleado_id
                {where_sql}
                ORDER BY ct.fecha DESC,
                         CASE ct.turno WHEN 'manana' THEN 1 WHEN 'tarde' THEN 2 ELSE 3 END
                LIMIT ? OFFSET ?""",
            params + [POR_PAGINA, offset],
        ).fetchall()

    return render_template(
        "cortes_historial.html",
        cortes=[dict(r) for r in rows],
        total=total,
        pagina=pagina,
        por_pagina=POR_PAGINA,
        paginas=max(1, (total + POR_PAGINA - 1) // POR_PAGINA),
        filtro_fecha=filtro_fecha,
        filtro_turno=filtro_turno,
        filtro_estado=filtro_est,
        turno_labels=_TURNO_LABELS,
    )
