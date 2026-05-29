"""
init_db.py - Inicializa la base de datos SQLite de SME.

Crea database/sme.db ejecutando el DDL de database/schema.sql.
No carga datos: para los precargados usa scripts/seed_data.py.

Uso:
    python scripts/init_db.py            # crea la BD si no existe
    python scripts/init_db.py --reset    # borra la BD existente y la recrea
"""

import argparse
import sqlite3
import sys
from pathlib import Path

# Raiz del proyecto = carpeta padre de /scripts
ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "database" / "sme.db"
SCHEMA_PATH = ROOT / "database" / "schema.sql"


def crear_bd(reset: bool = False) -> None:
    if SCHEMA_PATH.exists() is False:
        sys.exit(f"ERROR: no se encontro el esquema en {SCHEMA_PATH}")

    if reset and DB_PATH.exists():
        DB_PATH.unlink()
        print(f"BD anterior eliminada: {DB_PATH}")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript(schema_sql)
        conn.commit()

        tablas = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name;"
        ).fetchall()
    finally:
        conn.close()

    print(f"Base de datos lista: {DB_PATH}")
    print(f"Tablas creadas ({len(tablas)}):")
    for (nombre,) in tablas:
        print(f"  - {nombre}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inicializa la BD de SME.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Borra la BD existente antes de recrearla.",
    )
    args = parser.parse_args()
    crear_bd(reset=args.reset)
