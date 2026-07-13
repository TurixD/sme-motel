"""
Tests del módulo de dominio de turnos del asistente (modules/asistente_turnos.py).

Deterministas y autocontenidos: cada test crea una BD temporal con un esquema
mínimo (turnos, empleados, asignaciones_turnos) y datos controlados. No dependen
de la BD de producción.

Cubre (criterios de aceptación del refactor):
  - transacción atómica con rollback por cobertura
  - validación de cobertura (planear y ejecutar)
  - dry-run vs ejecución real
  - idempotencia de inserts (recurrente y puntual)

Correr:  venv/Scripts/python.exe -m pytest tests/ -q
"""

import sqlite3

import pytest

import modules.asistente_turnos as AT

# Sábados de julio 2026 (2026-07-13 es lunes) y un lunes de control
SAB1, SAB2, SAB3 = "2026-07-11", "2026-07-18", "2026-07-25"
LUN = "2026-07-13"
DESDE, HASTA = "2026-07-01", "2026-07-31"
TARDE = 2


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(
        """
        CREATE TABLE turnos (id INTEGER PRIMARY KEY, nombre TEXT, sueldo REAL);
        INSERT INTO turnos VALUES (1,'manana',400),(2,'tarde',400),(3,'noche',500);

        CREATE TABLE empleados (
            id INTEGER PRIMARY KEY, nombre TEXT, turno_default TEXT,
            es_socio INTEGER DEFAULT 0, activo INTEGER DEFAULT 1
        );
        INSERT INTO empleados (id,nombre,turno_default,activo) VALUES
            (1,'Ana','tarde',1), (2,'Beto','tarde',1),
            (3,'Caro','tarde',1), (4,'Dora','tarde',0);   -- Dora inactiva

        CREATE TABLE asignaciones_turnos (
            id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT, empleado_id INTEGER,
            turno_id INTEGER, es_doble_turno INTEGER DEFAULT 0, notas TEXT,
            creado_en TEXT DEFAULT (datetime('now'))
        );
        """
    )
    # Calendario tarde: SAB1={Ana,Caro}, SAB2={Ana}, SAB3={Ana,Beto}, LUN={Ana}
    filas = [
        (SAB1, 1), (SAB1, 3),
        (SAB2, 1),
        (SAB3, 1), (SAB3, 2),
        (LUN, 1),
    ]
    c.executemany(
        "INSERT INTO asignaciones_turnos (fecha, empleado_id, turno_id) VALUES (?, ?, 2)",
        filas,
    )
    # Cobertura de mañana (turno 1) en cada sábado: en producción toda fecha tiene
    # sus 3 turnos, así que la fecha existe aunque se vacíe un turno concreto.
    c.executemany(
        "INSERT INTO asignaciones_turnos (fecha, empleado_id, turno_id) VALUES (?, 3, 1)",
        [(SAB1,), (SAB2,), (SAB3,)],
    )
    c.commit()
    yield c
    c.close()


def _ids(conn, fecha, turno_id=TARDE):
    return {r["empleado_id"] for r in conn.execute(
        "SELECT empleado_id FROM asignaciones_turnos WHERE fecha=? AND turno_id=?",
        (fecha, turno_id),
    )}


def _total(conn):
    return conn.execute("SELECT COUNT(*) n FROM asignaciones_turnos").fetchone()["n"]


# ── Parsers ──────────────────────────────────────────────────────────────────

def test_dia_semana_parse():
    assert AT.dia_semana_int("sabado") == 5
    assert AT.dia_semana_int("Sábado") == 5
    assert AT.dia_semana_int(5) == 5
    assert AT.dia_semana_int("domingo") == 6
    assert AT.dia_semana_int("no-existe") is None


def test_resolver_turno(conn):
    assert AT.resolver_turno_id(conn, "tarde") == (2, "tarde")
    assert AT.resolver_turno_id(conn, "mañana")[0] == 1   # tolerante a acento
    assert AT.resolver_turno_id(conn, 3) == (3, "noche")
    assert AT.resolver_turno_id(conn, "xyz") == (None, None)


# ── Reasignación recurrente ──────────────────────────────────────────────────

def test_reasignar_solo_sabados(conn):
    inp = {"dia_semana": "sabado", "turno": "tarde",
           "quitar_empleado_ids": [1], "agregar_empleado_ids": [2],
           "desde_fecha": DESDE, "hasta_fecha": HASTA}
    plan = AT.planear_reasignar(conn, inp)
    assert plan["ok"]
    assert plan["fechas_afectadas"] == [SAB1, SAB2, SAB3]     # el lunes NO entra
    assert plan["eliminados"] == 3 and plan["insertados"] == 2 and plan["omitidos_dup"] == 1


def test_reasignar_ejecuta_y_es_idempotente(conn):
    inp = {"dia_semana": "sabado", "turno": "tarde",
           "quitar_empleado_ids": [1], "agregar_empleado_ids": [2], "desde_fecha": DESDE}
    res = AT.ejecutar_reasignar(conn, inp, dry_run=False)
    assert res["ok"] and res["ejecutado"]
    # Ana fuera de todos los sábados tarde, Beto dentro; el lunes intacto
    assert _ids(conn, SAB1) == {3, 2}
    assert _ids(conn, SAB2) == {2}
    assert _ids(conn, SAB3) == {2}
    assert _ids(conn, LUN) == {1}
    # Repetir agregar Beto no duplica (la tabla no tiene UNIQUE; idempotencia por app)
    res2 = AT.ejecutar_reasignar(conn, {"dia_semana": "sabado", "turno": "tarde",
                                        "agregar_empleado_ids": [2], "desde_fecha": DESDE}, dry_run=False)
    assert res2["insertados"] == 0


def test_dry_run_no_escribe(conn):
    antes = _total(conn)
    inp = {"dia_semana": "sabado", "turno": "tarde",
           "quitar_empleado_ids": [1], "agregar_empleado_ids": [2], "desde_fecha": DESDE}
    res = AT.ejecutar_reasignar(conn, inp, dry_run=True)
    assert res["dry_run"] and not res["ejecutado"]
    assert _total(conn) == antes                 # nada cambió
    assert _ids(conn, SAB1) == {1, 3}


def test_rollback_por_cobertura(conn):
    antes_total = _total(conn)
    antes_sab1 = _ids(conn, SAB1)
    # Quitar a TODOS de los sábados sin agregar → SAB2 (solo Ana) quedaría vacío
    inp = {"dia_semana": "sabado", "turno": "tarde",
           "quitar_empleado_ids": [1, 2, 3], "desde_fecha": DESDE}
    plan = AT.planear_reasignar(conn, inp)
    assert SAB2 in plan["sin_cobertura"]
    res = AT.ejecutar_reasignar(conn, inp, dry_run=False)
    assert not res["ok"] and res["error"] == "cobertura"
    # ROLLBACK total: ni un DELETE quedó aplicado
    assert _total(conn) == antes_total
    assert _ids(conn, SAB1) == antes_sab1


def test_empleado_inactivo_rechazado(conn):
    res = AT.planear_reasignar(conn, {"dia_semana": "sabado", "turno": "tarde",
                                      "agregar_empleado_ids": [4], "desde_fecha": DESDE})
    assert not res["ok"] and "inactiv" in res["error"].lower()


def test_excepcion_por_fecha(conn):
    # Regla general: quitar Ana, poner Beto. Excepción SAB2: dejar a Caro en vez de Beto.
    inp = {"dia_semana": "sabado", "turno": "tarde",
           "quitar_empleado_ids": [1], "agregar_empleado_ids": [2], "desde_fecha": DESDE,
           "excepciones": [{"fecha": SAB2, "quitar_ids": [1], "agregar_ids": [3]}]}
    res = AT.ejecutar_reasignar(conn, inp, dry_run=False)
    assert res["ok"]
    assert _ids(conn, SAB2) == {3}               # la excepción mandó
    assert _ids(conn, SAB1) == {3, 2}


# ── Operaciones puntuales ────────────────────────────────────────────────────

def test_asignar_fecha_idempotente(conn):
    r1 = AT.ejecutar_asignar_fecha(conn, {"fecha": SAB2, "turno": "tarde", "empleado_id": 2}, dry_run=False)
    assert r1["insertados"] == 1
    r2 = AT.ejecutar_asignar_fecha(conn, {"fecha": SAB2, "turno": "tarde", "empleado_id": 2}, dry_run=False)
    assert r2["insertados"] == 0 and r2["omitidos_dup"] == 1


def test_quitar_unico_rechazado(conn):
    # SAB2 solo tiene a Ana; quitarla dejaría el turno sin nadie
    res = AT.ejecutar_quitar_fecha(conn, {"fecha": SAB2, "turno": "tarde", "empleado_id": 1}, dry_run=False)
    assert not res["ok"] and res["error"] == "cobertura"
    assert _ids(conn, SAB2) == {1}               # sigue ahí


def test_quitar_fecha_ok(conn):
    # SAB1 tiene {Ana,Caro}; quitar Caro deja a Ana → permitido
    res = AT.ejecutar_quitar_fecha(conn, {"fecha": SAB1, "turno": "tarde", "empleado_id": 3}, dry_run=False)
    assert res["ok"] and res["eliminados"] == 1
    assert _ids(conn, SAB1) == {1}


# ── Cobertura ────────────────────────────────────────────────────────────────

def test_resumen_cobertura_detecta_vacios(conn):
    # Vaciar SAB2 tarde por debajo (directo) y pedir resumen
    conn.execute("DELETE FROM asignaciones_turnos WHERE fecha=? AND turno_id=2", (SAB2,))
    conn.commit()
    res = AT.tool_resumen_cobertura(conn, {"fecha_inicio": DESDE, "fecha_fin": HASTA, "turno": "tarde"})
    fechas_vacias = {v["fecha"] for v in res["sin_cobertura"]}
    assert SAB2 in fechas_vacias
    assert SAB1 not in fechas_vacias
