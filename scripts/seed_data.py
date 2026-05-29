"""
seed_data.py - Carga los datos iniciales precargados de SME (SPEC seccion 4).

Carga: turnos, empleados, gastos_fijos, configuracion, fondos, inventario.
NO toca tablas transaccionales (ingresos, asignaciones, movimientos, etc.).

Uso:
    python scripts/seed_data.py            # carga si las tablas estan vacias
    python scripts/seed_data.py --force    # borra los precargados y los recarga
"""

import argparse
import sqlite3
import sys
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
    ("Renta",      40000, "mensual",    None),
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Carga los datos iniciales de SME.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Borra los precargados existentes antes de recargar.",
    )
    args = parser.parse_args()
    cargar(force=args.force)
