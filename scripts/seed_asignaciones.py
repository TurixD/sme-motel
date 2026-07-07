"""
seed_asignaciones.py - Seed de asignaciones de turnos a 1 año.

Borra las asignaciones/pagos de prueba y genera asignaciones para 365 dias
desde HOY siguiendo el patron semanal fijo del motel. Desactiva a Vivina
(ya no trabaja).

Se puede correr solo:
    python scripts/seed_asignaciones.py

Se ejecuta automaticamente desde scripts/init_db.py (migrar()) cuando
asignaciones_turnos tiene menos de 100 registros (data de prueba).
"""

import sqlite3
from datetime import date, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "database" / "sme.db"

# Dias de la semana: 0=Lunes, 1=Martes, ..., 6=Domingo
# Patron: dia_semana -> {turno_id: [empleado_id, ...]}
PATRON_SEMANAL = {
    0: {  # Lunes
        1: [1, 3],   # Manana: Wendy, Martha
        2: [4, 7],   # Tarde: Dulce, Gabriel
        3: [8],      # Noche: Goyo
    },
    1: {  # Martes
        1: [1],       # Manana: Wendy
        2: [4, 9],    # Tarde: Dulce, Carmelo
        3: [8],       # Noche: Goyo
    },
    2: {  # Miercoles
        1: [1, 3],    # Manana: Wendy, Martha
        2: [4, 6],    # Tarde: Dulce, Turi
        3: [8],       # Noche: Goyo
    },
    3: {  # Jueves
        1: [1],       # Manana: Wendy
        2: [4, 3],    # Tarde: Dulce, Martha
        3: [8],       # Noche: Goyo
    },
    4: {  # Viernes
        1: [4, 3],    # Manana: Dulce, Martha
        2: [1, 6],    # Tarde: Wendy, Turi
        3: [9],       # Noche: Carmelo
    },
    5: {  # Sabado
        1: [1],       # Manana: Wendy
        2: [4, 5],    # Tarde: Dulce, Cecy
        3: [8, 9],    # Noche: Goyo, Carmelo (dos empleados)
    },
    6: {  # Domingo
        1: [1],       # Manana: Wendy
        2: [5, 6],    # Tarde: Cecy, Turi
        3: [9],       # Noche: Carmelo
    },
}

DIAS_A_GENERAR = 365


def seed(db_path: Path = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    print("[SEED] Desactivando a Vivina...")
    cur.execute("UPDATE empleados SET activo = 0 WHERE nombre = 'Vivina'")

    print("[SEED] Borrando asignaciones existentes...")
    cur.execute("DELETE FROM asignaciones_turnos")

    print("[SEED] Borrando pagos_empleados existentes...")
    cur.execute("DELETE FROM pagos_empleados")

    print(f"[SEED] Generando {DIAS_A_GENERAR} dias de asignaciones desde HOY...")

    fecha_inicio = date.today()
    insertadas = 0

    for offset in range(DIAS_A_GENERAR):
        fecha_actual = fecha_inicio + timedelta(days=offset)
        dia_semana = fecha_actual.weekday()  # 0=Lunes, 6=Domingo
        fecha_str = fecha_actual.isoformat()

        patron_dia = PATRON_SEMANAL[dia_semana]
        for turno_id, empleados in patron_dia.items():
            for emp_id in empleados:
                cur.execute(
                    """
                    INSERT INTO asignaciones_turnos (fecha, empleado_id, turno_id, es_doble_turno)
                    VALUES (?, ?, ?, 0)
                    """,
                    (fecha_str, emp_id, turno_id),
                )
                insertadas += 1

    conn.commit()
    print(f"[SEED] Total insertadas: {insertadas} asignaciones")

    total = cur.execute("SELECT COUNT(*) FROM asignaciones_turnos").fetchone()[0]
    fecha_min, fecha_max = cur.execute(
        "SELECT MIN(fecha), MAX(fecha) FROM asignaciones_turnos"
    ).fetchone()
    print(f"[SEED] Total en BD ahora: {total}")
    print(f"[SEED] Rango de fechas: {fecha_min} a {fecha_max}")

    conn.close()


if __name__ == "__main__":
    print("=" * 50)
    print("SEED DE ASIGNACIONES DE TURNOS")
    print("=" * 50)
    seed()
    print("[SEED] Completado.")
