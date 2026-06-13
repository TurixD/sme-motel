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


def migrar() -> None:
    """Aplica migraciones de esquema sobre BD existente (idempotente)."""
    if not DB_PATH.exists():
        sys.exit("ERROR: la BD no existe. Corre primero: python scripts/init_db.py")

    conn = sqlite3.connect(DB_PATH)
    try:
        columnas = {row[1] for row in conn.execute("PRAGMA table_info(uso_ia)").fetchall()}
        migraciones = 0
        if "exito" not in columnas:
            conn.execute("ALTER TABLE uso_ia ADD COLUMN exito INTEGER NOT NULL DEFAULT 1")
            migraciones += 1
            print("  uso_ia: columna 'exito' agregada")
        if "error_message" not in columnas:
            conn.execute("ALTER TABLE uso_ia ADD COLUMN error_message TEXT")
            migraciones += 1
            print("  uso_ia: columna 'error_message' agregada")

        # gastos_extras: recibo_path
        columnas_gastos = {row[1] for row in conn.execute("PRAGMA table_info(gastos_extras)").fetchall()}
        if "recibo_path" not in columnas_gastos:
            conn.execute("ALTER TABLE gastos_extras ADD COLUMN recibo_path TEXT")
            migraciones += 1
            print("  gastos_extras: columna 'recibo_path' agregada")

        # recibos: hash_md5
        columnas_recibos = {row[1] for row in conn.execute("PRAGMA table_info(recibos)").fetchall()}
        if "hash_md5" not in columnas_recibos:
            conn.execute("ALTER TABLE recibos ADD COLUMN hash_md5 TEXT")
            migraciones += 1
            print("  recibos: columna 'hash_md5' agregada")

        # Agregar config limite_mensual_ia_usd si no existe
        existe = conn.execute(
            "SELECT 1 FROM configuracion WHERE clave='limite_mensual_ia_usd'"
        ).fetchone()
        if not existe:
            conn.execute(
                "INSERT INTO configuracion (clave, valor, descripcion) VALUES (?,?,?)",
                ("limite_mensual_ia_usd", "5.00",
                 "Límite mensual de gasto en IA (USD) — bloquea llamadas al superarse"),
            )
            migraciones += 1
            print("  configuracion: clave 'limite_mensual_ia_usd' agregada")

        # conversaciones_ia: renombrar columnas y agregar nuevas (Fase 4)
        cols_conv = {row[1] for row in conn.execute("PRAGMA table_info(conversaciones_ia)").fetchall()}
        if "mensaje" in cols_conv and "contenido" not in cols_conv:
            conn.execute("ALTER TABLE conversaciones_ia RENAME COLUMN mensaje TO contenido")
            migraciones += 1
            print("  conversaciones_ia: columna 'mensaje' renombrada a 'contenido'")
        if "tokens_usados" in cols_conv and "tokens_input" not in cols_conv:
            conn.execute("ALTER TABLE conversaciones_ia RENAME COLUMN tokens_usados TO tokens_input")
            migraciones += 1
            print("  conversaciones_ia: columna 'tokens_usados' renombrada a 'tokens_input'")
        cols_conv = {row[1] for row in conn.execute("PRAGMA table_info(conversaciones_ia)").fetchall()}
        if "tokens_output" not in cols_conv:
            conn.execute("ALTER TABLE conversaciones_ia ADD COLUMN tokens_output INTEGER")
            migraciones += 1
            print("  conversaciones_ia: columna 'tokens_output' agregada")
        if "costo_usd" not in cols_conv:
            conn.execute("ALTER TABLE conversaciones_ia ADD COLUMN costo_usd REAL")
            migraciones += 1
            print("  conversaciones_ia: columna 'costo_usd' agregada")

        # cambios_pendientes (nueva tabla Fase 4)
        tablas = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        if "cambios_pendientes" not in tablas:
            conn.execute("""
                CREATE TABLE cambios_pendientes (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    sesion_id           TEXT    NOT NULL,
                    sql                 TEXT    NOT NULL,
                    descripcion_humana  TEXT    NOT NULL,
                    tabla               TEXT    NOT NULL,
                    tipo                TEXT    NOT NULL,
                    estado              TEXT    NOT NULL DEFAULT 'pendiente',
                    fecha_propuesta     TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
                    fecha_resolucion    TEXT,
                    registros_afectados INTEGER
                )
            """)
            migraciones += 1
            print("  cambios_pendientes: tabla creada")

        # movimientos_inventario: descripcion + origen (Fase 5a)
        cols_mov = {row[1] for row in conn.execute("PRAGMA table_info(movimientos_inventario)").fetchall()}
        if "descripcion" not in cols_mov:
            conn.execute("ALTER TABLE movimientos_inventario ADD COLUMN descripcion TEXT")
            migraciones += 1
            print("  movimientos_inventario: columna 'descripcion' agregada")
        if "origen" not in cols_mov:
            conn.execute("ALTER TABLE movimientos_inventario ADD COLUMN origen TEXT")
            migraciones += 1
            print("  movimientos_inventario: columna 'origen' agregada")

        # reportes_narrativas
        tablas = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        if "reportes_narrativas" not in tablas:
            conn.execute("""
                CREATE TABLE reportes_narrativas (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    tipo            TEXT    NOT NULL,
                    periodo_clave   TEXT    NOT NULL,
                    parrafo         TEXT    NOT NULL,
                    bullets         TEXT    NOT NULL,
                    hash_datos      TEXT    NOT NULL,
                    costo_usd       REAL    NOT NULL,
                    fecha_generada  TEXT    NOT NULL,
                    UNIQUE(tipo, periodo_clave)
                )
            """)
            migraciones += 1
            print("  reportes_narrativas: tabla creada")

        conn.commit()
        if migraciones == 0:
            print("Sin cambios: la BD ya está actualizada.")
        else:
            print(f"Migración completada ({migraciones} cambios).")
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inicializa la BD de SME.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Borra la BD existente antes de recrearla.",
    )
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Aplica migraciones de esquema sobre BD existente (idempotente).",
    )
    args = parser.parse_args()
    if args.migrate:
        migrar()
    else:
        crear_bd(reset=args.reset)
