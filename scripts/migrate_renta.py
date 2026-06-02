"""
migrate_renta.py - Migración puntual: convierte Renta de gasto_fijo a fondo.
Idempotente. Corre una sola vez contra la BD viva.
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "database" / "sme.db"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA foreign_keys = ON;")

# 1. Eliminar Renta de gastos_fijos
antes = conn.execute("SELECT COUNT(*) FROM gastos_fijos").fetchone()[0]
conn.execute("DELETE FROM gastos_fijos WHERE concepto='Renta'")
conn.commit()
despues = conn.execute("SELECT COUNT(*) FROM gastos_fijos").fetchone()[0]
print(f"gastos_fijos: {antes} -> {despues} registros")

# 2. Insertar fondo Renta si no existe
existe = conn.execute("SELECT id FROM fondos WHERE nombre='Renta'").fetchone()
if not existe:
    conn.execute(
        """INSERT INTO fondos (nombre, descripcion, meta_mensual, minimo_seguro,
           aporte_periodico, frecuencia_aporte, dia_aporte, pregunta_antes,
           categoria_enlazada, color, activo)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        ("Renta", "Fondo para pago semanal de renta ($10,000/semana).",
         40000, 0, 0, "semanal", "lunes", 0, "Renta", "#FFB84D", 1),
    )
    conn.commit()
    print("Fondo Renta insertado.")
else:
    print(f"Fondo Renta ya existe (id={existe['id']})")

# 3. Pago historico 2026-05-31
fondo = conn.execute("SELECT id FROM fondos WHERE nombre='Renta' AND activo=1").fetchone()
desc = "Pago renta semana del 2026-05-25 al 2026-05-31"
existe_pago = conn.execute(
    "SELECT id FROM gastos_extras WHERE descripcion=?", (desc,)
).fetchone()
if not existe_pago:
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
    print(f"Historico renta 2026-05-31 insertado (gasto_id={gasto_id}).")
else:
    print("Historico renta 2026-05-31 ya existe.")

# 4. Verificar estado final
print("\nFondos activos:")
for r in conn.execute(
    "SELECT id, nombre, categoria_enlazada, pregunta_antes FROM fondos WHERE activo=1"
).fetchall():
    print(f"  id={r['id']} nombre={r['nombre']} cat_enlazada={r['categoria_enlazada']} banner={r['pregunta_antes']}")

print("\ngastos_fijos activos:")
for r in conn.execute("SELECT concepto, frecuencia FROM gastos_fijos WHERE activo=1").fetchall():
    print(f"  {r['concepto']} ({r['frecuencia']})")

conn.close()
