"""
seed_data.py - Carga los datos iniciales precargados de SME (SPEC seccion 4).

Carga: turnos, empleados, gastos_fijos, configuracion, fondos, inventario.

Uso:
    python scripts/seed_data.py                   # carga datos base si estan vacios
    python scripts/seed_data.py --force           # borra y recarga datos base
    python scripts/seed_data.py --asignaciones    # siembra turnos 4 semanas (idempotente)
"""

import argparse
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "database" / "sme.db"

# -------------------------------------------------------------
# Datos precargados (SPEC seccion 4)
# -------------------------------------------------------------

# 4.3 turnos: (nombre, hora_inicio, hora_fin, sueldo)
TURNOS = [
    ("manana", "08:00", "16:00", 400),
    ("tarde",  "16:00", "23:00", 400),
    ("noche",  "23:00", "08:00", 500),
]

# 4.2 empleados: (nombre, turno_default, es_socio, color_calendario, notas)
COLOR_TURI = "#C084FC"
EMPLEADOS = [
    ("Wendy",   "manana", 0, None,       "Lun-Vie manana"),
    ("Vivina",  "manana", 0, None,       "Sab-Dom manana"),
    ("Martha",  "manana", 0, None,       "Lun man, Mie man, Jue tarde, Vie man"),
    ("Dulce",   "tarde",  0, None,       "Lun-Sab tarde"),
    ("Cecy",    "tarde",  0, None,       "Sab-Dom tarde"),
    ("Turi",    "tarde",  1, COLOR_TURI, "Mie, Vie, Dom tarde"),
    ("Gabriel", "tarde",  1, None,       "Lun tarde"),
    ("Goyo",    "noche",  0, None,       "Lun-Jue noche, Sab noche"),
    ("Carmelo", "noche",  0, None,       "Mar tarde, Vie-Dom noche"),
]

# 4.7 gastos_fijos: (concepto, monto_estimado, frecuencia, dia_recordatorio)
GASTOS_FIJOS = [
    ("CFE",        16000, "bimestral",  30),
    ("StarTV",     None,  "mensual",    None),
    ("Contadores", 250,   "mensual",    None),
]

# 4.8 configuracion: (clave, valor, descripcion)
CONFIGURACION = [
    ("comision_tarjeta",           "4",       "Comision % sobre pagos con tarjeta"),
    ("tipo_cambio_usd_mxn",        "18.50",   "Tipo de cambio USD a MXN"),
    ("memoria_asistente_mensajes", "10",      "Mensajes de contexto del asistente IA"),
    ("timeout_sesion_minutos",     "30",      "Minutos de inactividad antes de expirar sesion IA"),
    ("umbral_alerta_gasto_ia_usd", "20",      "Umbral mensual de gasto IA (USD) para alertar"),
    ("color_turi",                 COLOR_TURI, "Color de Turi en el calendario"),
]

# 4.9 fondos: (nombre, descripcion, meta_mensual, minimo_seguro,
#              aporte_periodico, frecuencia_aporte, dia_aporte,
#              pregunta_antes, categoria_enlazada, color)
FONDOS = [
    ("Reserva general", "Fondo de reserva general",
     20000, 15000, 5000, "semanal", "lunes", 1, None, "#34D399"),
    ("CFE", "Fondo para pago de luz (CFE). Meta real bimestral $16,000.",
     8000, 0, 2000, "semanal", "lunes", 1, "Luz", "#22C55E"),
    ("Renta", "Fondo para pago semanal de renta ($10,000/semana).",
     40000, 0, 0, "semanal", "lunes", 0, "Renta", "#FFB84D"),
]

# 4.12 inventario: (nombre, proveedor_default)
INVENTARIO = [
    ("Agua 500ml",                    "Sam's"),
    ("Detergente para ropa",          "Sam's"),
    ("Pinol",                         "Sam's"),
    ("Cloro",                         "Sam's"),
    ("Lysol",                         "Sam's"),
    ("Bounce",                        "Sam's"),
    ("Kleenex",                       "Sam's"),
    ("Jabon Salvo",                   "Sam's"),
    ("Mentas",                        "Sam's"),
    ("Bolsas basura transparentes",   "Sam's"),
    ("Bolsas basura negras",          "Sam's"),
    ("Windex",                        "Sam's"),
    ("Agua oxigenada",                "Sam's"),
    ("Paquetes papel de bano",        "Sam's"),
    ("Condones",                      "Sam's"),
    ("Pilas 3A",                      "Sam's"),
    ("Shampoo",                       "Mercado Libre"),
    ("Acondicionador",                "Mercado Libre"),
    ("Jabon de tocador",              "Abarrotera"),
]

# Tabla -> (columnas, filas).  Orden de carga.
SEED = [
    ("turnos",        "(nombre, hora_inicio, hora_fin, sueldo)", TURNOS),
    ("empleados",     "(nombre, turno_default, es_socio, color_calendario, notas)", EMPLEADOS),
    ("gastos_fijos",  "(concepto, monto_estimado, frecuencia, dia_recordatorio)", GASTOS_FIJOS),
    ("configuracion", "(clave, valor, descripcion)", CONFIGURACION),
    ("fondos",        "(nombre, descripcion, meta_mensual, minimo_seguro, aporte_periodico, "
                      "frecuencia_aporte, dia_aporte, pregunta_antes, categoria_enlazada, color)", FONDOS),
    ("inventario",    "(nombre, proveedor_default)", INVENTARIO),
]


def _placeholders(n: int) -> str:
    return "(" + ", ".join(["?"] * n) + ")"


def cargar(force: bool = False) -> None:
    if DB_PATH.exists() is False:
        sys.exit("ERROR: la BD no existe. Corre primero: python scripts/init_db.py")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        # Si ya hay datos y no es --force, no duplicar.
        ya_cargado = any(
            conn.execute(f"SELECT 1 FROM {tabla} LIMIT 1;").fetchone()
            for tabla, _, _ in SEED
        )
        if ya_cargado and force is False:
            print("Los precargados ya existen. Usa --force para recargarlos.")
            return

        if force:
            for tabla, _, _ in reversed(SEED):
                conn.execute(f"DELETE FROM {tabla};")
            print("Precargados anteriores eliminados.")

        for tabla, columnas, filas in SEED:
            ncols = len(filas[0])
            conn.executemany(
                f"INSERT INTO {tabla} {columnas} VALUES {_placeholders(ncols)};",
                filas,
            )
            print(f"  {tabla}: {len(filas)} filas")

        conn.commit()
    finally:
        conn.close()

    print("Datos iniciales cargados correctamente.")


# -------------------------------------------------------------
# Patrón semanal de asignaciones por empleado (SPEC sección 4.2)
# {emp_id: [(weekday, turno_id), ...]}
# weekday: 0=Lun … 6=Dom  |  turno_id: 1=mañana, 2=tarde, 3=noche
# -------------------------------------------------------------
SCHEDULE_ASIGNACIONES = {
    1: [(0,1),(1,1),(2,1),(3,1),(4,1)],          # Wendy     Lun-Vie mañana
    2: [(5,1),(6,1)],                             # Vivina    Sáb-Dom mañana
    3: [(0,1),(2,1),(3,2),(4,1)],                 # Martha    Lun/Mié/Vie mañana · Jue tarde
    4: [(0,2),(1,2),(2,2),(3,2),(4,2),(5,2)],     # Dulce     Lun-Sáb tarde
    5: [(5,2),(6,2)],                             # Cecy      Sáb-Dom tarde
    6: [(2,2),(4,2),(6,2)],                       # Turi      Mié/Vie/Dom tarde
    7: [(0,2)],                                   # Gabriel   Lun tarde
    8: [(0,3),(1,3),(2,3),(3,3),(5,3)],           # Goyo      Lun-Jue/Sáb noche
    9: [(1,2),(4,3),(5,3),(6,3)],                 # Carmelo   Mar tarde · Vie-Dom noche
}


def sembrar_asignaciones(semanas: int = 4) -> None:
    """
    Siembra asignaciones_turnos + pagos_empleados para las próximas N semanas.
    Empieza en el lunes de la semana actual. Es idempotente: salta
    duplicados (misma fecha + turno_id + empleado_id).
    """
    if not DB_PATH.exists():
        sys.exit("ERROR: la BD no existe. Corre primero: python scripts/init_db.py")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Sueldos por turno_id
    sueldos = {row[0]: row[1] for row in conn.execute("SELECT id, sueldo FROM turnos").fetchall()}

    hoy   = date.today()
    lunes = hoy - timedelta(days=hoy.weekday())
    fin   = lunes + timedelta(weeks=semanas) - timedelta(days=1)

    insertados = 0
    saltados   = 0

    try:
        for semana in range(semanas):
            week_start = lunes + timedelta(weeks=semana)
            for emp_id, slots in SCHEDULE_ASIGNACIONES.items():
                for (weekday, turno_id) in slots:
                    fecha = (week_start + timedelta(days=weekday)).isoformat()

                    # Idempotencia: skip si ya existe esta combinación
                    existe = conn.execute(
                        "SELECT 1 FROM asignaciones_turnos WHERE fecha=? AND turno_id=? AND empleado_id=?",
                        (fecha, turno_id, emp_id),
                    ).fetchone()
                    if existe:
                        saltados += 1
                        continue

                    cur = conn.execute(
                        """INSERT INTO asignaciones_turnos
                           (fecha, empleado_id, turno_id, es_doble_turno, creado_en)
                           VALUES (?, ?, ?, 0, datetime('now','localtime'))""",
                        (fecha, emp_id, turno_id),
                    )
                    asig_id = cur.lastrowid
                    conn.execute(
                        """INSERT INTO pagos_empleados
                           (asignacion_turno_id, empleado_id, fecha, monto, pagado, creado_en)
                           VALUES (?, ?, ?, ?, 1, datetime('now','localtime'))""",
                        (asig_id, emp_id, fecha, sueldos.get(turno_id, 0)),
                    )
                    insertados += 1

        conn.commit()
        print(f"Asignaciones sembradas: {insertados} nuevas, {saltados} ya existían.")
        print(f"Rango: {lunes} al {fin} ({semanas} semanas).")
    finally:
        conn.close()


def sembrar_historico_renta() -> None:
    """
    Registra el pago de renta del domingo 2026-05-31 si no existe.
    Idempotente: no duplica si ya fue sembrado.
    """
    if not DB_PATH.exists():
        sys.exit("ERROR: la BD no existe. Corre primero: python scripts/init_db.py")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        fondo = conn.execute(
            "SELECT id FROM fondos WHERE nombre='Renta' AND activo=1"
        ).fetchone()
        if not fondo:
            print("Fondo 'Renta' no encontrado — corre seed_data.py primero.")
            return

        desc = "Pago renta semana del 2026-05-25 al 2026-05-31"
        existe = conn.execute(
            "SELECT id FROM gastos_extras WHERE descripcion=?", (desc,)
        ).fetchone()
        if existe:
            print("Histórico de renta 2026-05-31 ya existe, omitiendo.")
            return

        cur = conn.execute(
            "INSERT INTO gastos_extras (fecha, categoria, monto, descripcion) VALUES (?,?,?,?)",
            ("2026-05-31", "Renta", 10000.0, desc),
        )
        gasto_id = cur.lastrowid
        conn.execute(
            "INSERT INTO movimientos_fondos "
            "(fondo_id, fecha, tipo, monto, concepto, gasto_extra_id) VALUES (?,?,?,?,?,?)",
            (fondo["id"], "2026-05-31", "retiro", 10000.0, desc, gasto_id),
        )
        conn.execute(
            "UPDATE gastos_extras SET fondo_descontado_id=? WHERE id=?",
            (fondo["id"], gasto_id),
        )
        conn.commit()
        print("Histórico renta 2026-05-31 sembrado correctamente.")
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Carga los datos iniciales de SME.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Borra los precargados existentes antes de recargar.",
    )
    parser.add_argument(
        "--asignaciones",
        action="store_true",
        help="Siembra asignaciones_turnos para las próximas 4 semanas (idempotente).",
    )
    parser.add_argument(
        "--historico-renta",
        action="store_true",
        help="Siembra el pago histórico de renta del 2026-05-31 (idempotente).",
    )
    args = parser.parse_args()

    if args.asignaciones:
        sembrar_asignaciones(semanas=4)
    elif args.historico_renta:
        sembrar_historico_renta()
    else:
        cargar(force=args.force)
