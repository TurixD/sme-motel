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

from werkzeug.security import generate_password_hash

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


_CUARTOS_SEED = [
    (1,  1,  "suite",            "Suite con jacuzzi y balcón", 700.0, 1050.0, 1400.0, 1550.0),
    (2,  2,  "sencilla",         "Sencilla",                   350.0,  500.0,  700.0,  800.0),
    (3,  3,  "sencilla",         "Sencilla",                   350.0,  500.0,  700.0,  800.0),
    (4,  4,  "sencilla",         "Sencilla",                   350.0,  500.0,  700.0,  800.0),
    (5,  5,  "sencilla",         "Sencilla",                   350.0,  500.0,  700.0,  800.0),
    (6,  6,  "sencilla",         "Sencilla",                   350.0,  500.0,  700.0,  800.0),
    (7,  7,  "sencilla",         "Sencilla",                   350.0,  500.0,  700.0,  800.0),
    (8,  8,  "sencilla",         "Sencilla",                   350.0,  500.0,  700.0,  800.0),
    (9,  9,  "sencilla_jacuzzi", "Sencilla con jacuzzi",       500.0,  750.0, 1000.0, 1100.0),
    (10, 10, "doble_jacuzzi",    "Doble con jacuzzi",          600.0,  900.0, 1200.0, 1350.0),
]


def _recalcular_ingresos_diarios(conn, fecha: str) -> None:
    """
    Recalcula ingresos_diarios para una fecha sumando cortes_turno válidos
    (estado 'declarado' o 'editado'). Solo actualiza si ya existen los 3
    turnos del día para esa fecha. Espejo de _actualizar_ingresos_diarios
    en modules/cortes.py, duplicado aquí para no acoplar init_db.py al
    paquete de la app.
    """
    turnos_presentes = conn.execute(
        "SELECT COUNT(DISTINCT turno) FROM cortes_turno WHERE fecha = ?", (fecha,)
    ).fetchone()[0]
    if turnos_presentes < 3:
        print(f"  ingresos_diarios: {fecha} no tiene los 3 turnos, no se recalcula")
        return

    bruto_total = float(conn.execute(
        """SELECT COALESCE(SUM(bruto_declarado), 0) FROM cortes_turno
           WHERE fecha = ? AND estado IN ('declarado', 'editado')""",
        (fecha,),
    ).fetchone()[0])
    notas_sync = "Generado desde cortes de turno v2.3"

    existente = conn.execute(
        "SELECT id FROM ingresos_diarios WHERE fecha = ?", (fecha,)
    ).fetchone()
    if existente:
        conn.execute(
            """UPDATE ingresos_diarios
               SET monto_efectivo=?, monto_tarjeta=0, monto_transferencia=0,
                   comision_tarjeta=0, total_neto=?, notas=?
               WHERE fecha=?""",
            (bruto_total, bruto_total, notas_sync, fecha),
        )
    else:
        conn.execute(
            """INSERT INTO ingresos_diarios
               (fecha, monto_efectivo, monto_tarjeta, monto_transferencia,
                comision_tarjeta, total_neto, notas, creado_en)
               VALUES (?, ?, 0, 0, 0, ?, ?, datetime('now','localtime'))""",
            (fecha, bruto_total, bruto_total, notas_sync),
        )
    print(f"  ingresos_diarios: recalculado para {fecha} = {bruto_total:.2f}")


def _seed_cuartos(conn) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO cuartos "
        "(id, numero, tipo, nombre_display, precio_6h, precio_12h, precio_18h, precio_24h) "
        "VALUES (?,?,?,?,?,?,?,?)",
        _CUARTOS_SEED,
    )


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

        # matches_aprendidos (Sub-fase 5C)
        tablas = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        if "matches_aprendidos" not in tablas:
            conn.execute("""
                CREATE TABLE matches_aprendidos (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    sku_sams            TEXT    NOT NULL UNIQUE,
                    texto_ticket        TEXT    NOT NULL,
                    inventario_id       INTEGER NOT NULL,
                    veces_confirmado    INTEGER NOT NULL DEFAULT 1,
                    primera_vez         TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
                    ultima_vez          TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
                    FOREIGN KEY (inventario_id) REFERENCES inventario(id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_matches_sku ON matches_aprendidos(sku_sams)")
            migraciones += 1
            print("  matches_aprendidos: tabla creada")

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

        # v2.0 — tabla usuarios
        tablas = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        if "usuarios" not in tablas:
            conn.execute("""
                CREATE TABLE usuarios (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    username       TEXT    UNIQUE NOT NULL,
                    password_hash  TEXT    NOT NULL,
                    nombre_display TEXT    NOT NULL,
                    activo         INTEGER NOT NULL DEFAULT 1
                )
            """)
            for uname, display in [("turi", "Turi"), ("gabriel", "Gabriel")]:
                conn.execute(
                    "INSERT OR IGNORE INTO usuarios "
                    "(username, password_hash, nombre_display) VALUES (?,?,?)",
                    (uname, generate_password_hash("cambiar123"), display),
                )
            migraciones += 1
            print("  usuarios: tabla creada con 2 admins (pass inicial: cambiar123)")

        # v2.0 — clave modo_actual en configuracion
        existe_modo = conn.execute(
            "SELECT 1 FROM configuracion WHERE clave='modo_actual'"
        ).fetchone()
        if not existe_modo:
            conn.execute(
                "INSERT INTO configuracion (clave, valor, descripcion) VALUES (?,?,?)",
                ("modo_actual", "admin_turi",
                 "Modo activo del sistema: admin_turi | admin_gabriel | empleado"),
            )
            migraciones += 1
            print("  configuracion: clave 'modo_actual' agregada (valor inicial: admin_turi)")

        # v2.1 — columna editado_por en rentas (si la tabla ya existía sin ella)
        tablas = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        if "rentas" in tablas:
            cols_rentas = {row[1] for row in conn.execute("PRAGMA table_info(rentas)").fetchall()}
            if "editado_por" not in cols_rentas:
                conn.execute("ALTER TABLE rentas ADD COLUMN editado_por TEXT")
                migraciones += 1
                print("  rentas: columna 'editado_por' agregada (v2.1)")

        # v2.1 — tabla cuartos (catálogo estático)
        tablas = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        if "cuartos" not in tablas:
            conn.execute("""
                CREATE TABLE cuartos (
                    id             INTEGER PRIMARY KEY,
                    numero         INTEGER UNIQUE NOT NULL,
                    tipo           TEXT    NOT NULL,
                    nombre_display TEXT    NOT NULL,
                    precio_6h      REAL    NOT NULL,
                    precio_12h     REAL    NOT NULL,
                    precio_18h     REAL    NOT NULL,
                    precio_24h     REAL    NOT NULL
                )
            """)
            _seed_cuartos(conn)
            migraciones += 1
            print("  cuartos: tabla creada con 10 registros (seed v2.1)")
        else:
            # Tabla existe — verificar que tiene datos y rellenar si está vacía
            count = conn.execute("SELECT COUNT(*) FROM cuartos").fetchone()[0]
            if count == 0:
                _seed_cuartos(conn)
                migraciones += 1
                print("  cuartos: seed aplicado (tabla estaba vacía)")

        # v2.1 — tabla rentas
        tablas = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        if "rentas" not in tablas:
            conn.execute("""
                CREATE TABLE rentas (
                    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                    cuarto_id          INTEGER NOT NULL,
                    fecha              TEXT    NOT NULL,
                    hora_registro      TEXT    NOT NULL,
                    duracion_horas     INTEGER NOT NULL,
                    precio_default     REAL    NOT NULL,
                    precio_cobrado     REAL    NOT NULL,
                    notas              TEXT,
                    estado             TEXT    NOT NULL DEFAULT 'activo',
                    registrado_por     TEXT    NOT NULL,
                    cancelado_por      TEXT,
                    cancelado_at       TEXT,
                    motivo_cancelacion TEXT,
                    editado            INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (cuarto_id) REFERENCES cuartos(id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rentas_fecha  ON rentas(fecha)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rentas_cuarto ON rentas(cuarto_id)")
            migraciones += 1
            print("  rentas: tabla creada (v2.1)")

        # v2.3 — tabla cortes_turno (schema simplificado: sin sueldos ni descuentos)
        tablas = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        _CORTES_SQL = """
            CREATE TABLE cortes_turno (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha            TEXT    NOT NULL,
                turno            TEXT    NOT NULL,
                empleado_id      INTEGER NOT NULL,
                bruto_calculado  REAL    NOT NULL DEFAULT 0,
                bruto_declarado  REAL    NOT NULL DEFAULT 0,
                estado           TEXT    NOT NULL DEFAULT 'declarado',
                declarado_at     TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
                confirmado_por   TEXT,
                confirmado_at    TEXT,
                editado_por      TEXT,
                editado_at       TEXT,
                motivo_rechazo   TEXT,
                notas            TEXT,
                UNIQUE(fecha, turno),
                FOREIGN KEY (empleado_id) REFERENCES empleados(id)
            )
        """
        if "cortes_turno" not in tablas:
            conn.execute(_CORTES_SQL)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cortes_fecha ON cortes_turno(fecha)")
            migraciones += 1
            print("  cortes_turno: tabla creada (v2.3)")
        else:
            # Si la tabla existe con schema viejo (tiene sueldo_empleado), recrear si está vacía
            cols_cortes = {r[1] for r in conn.execute("PRAGMA table_info(cortes_turno)").fetchall()}
            if "sueldo_empleado" in cols_cortes or "declarado_por_nombre" in cols_cortes:
                cnt = conn.execute("SELECT COUNT(*) FROM cortes_turno").fetchone()[0]
                if cnt == 0:
                    conn.execute("DROP TABLE cortes_turno")
                    conn.execute(_CORTES_SQL)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_cortes_fecha ON cortes_turno(fecha)")
                    migraciones += 1
                    print("  cortes_turno: recreada con schema simplificado (v2.3b)")

        # v2.3c — eliminar estado 'confirmado' (ya no existe en el flujo nuevo)
        tablas = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        if "cortes_turno" in tablas:
            fechas_afectadas = {
                r[0] for r in conn.execute(
                    "SELECT DISTINCT fecha FROM cortes_turno WHERE estado = 'confirmado'"
                ).fetchall()
            }
            if fechas_afectadas:
                conn.execute(
                    "UPDATE cortes_turno SET estado = 'declarado' WHERE estado = 'confirmado'"
                )
                migraciones += 1
                print(f"  cortes_turno: {len(fechas_afectadas)} fecha(s) con estado "
                      f"'confirmado' migradas a 'declarado' (v2.3c)")

                # '2026-07-06' son datos de prueba: se excluyen del recálculo automático
                # de ingresos_diarios (se van a borrar manualmente).
                fechas_afectadas.discard("2026-07-06")
                for fecha in sorted(fechas_afectadas):
                    _recalcular_ingresos_diarios(conn, fecha)

        conn.commit()
        if migraciones == 0:
            print("Sin cambios: la BD ya está actualizada.")
        else:
            print(f"Migración completada ({migraciones} cambios).")

        count_asignaciones = conn.execute(
            "SELECT COUNT(*) FROM asignaciones_turnos"
        ).fetchone()[0]
    finally:
        conn.close()

    if count_asignaciones < 100:
        print("[MIGRAR] Ejecutando seed de asignaciones de turnos...")
        from seed_asignaciones import seed as seed_asignaciones
        seed_asignaciones()


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
