-- =============================================================
--  SME - Software de Manejo de Estres
--  Esquema de base de datos (SQLite)
--  Referencia maestra: SPEC.md seccion 4 (19 tablas)
--
--  Convenciones de tipos (SQLite no tiene DECIMAL/BOOLEAN nativos):
--    - decimal  -> REAL
--    - boolean  -> INTEGER (0 = falso, 1 = verdadero)
--    - date     -> TEXT 'YYYY-MM-DD'
--    - time     -> TEXT 'HH:MM'
--    - datetime -> TEXT 'YYYY-MM-DD HH:MM:SS'
-- =============================================================

PRAGMA foreign_keys = ON;

-- -------------------------------------------------------------
-- 4.1  ingresos_diarios
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ingresos_diarios (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha               TEXT    NOT NULL,                 -- date
    monto_efectivo      REAL    NOT NULL DEFAULT 0,
    monto_tarjeta       REAL    NOT NULL DEFAULT 0,
    monto_transferencia REAL    NOT NULL DEFAULT 0,
    comision_tarjeta    REAL    NOT NULL DEFAULT 0,       -- calculado: tarjeta x 0.04
    total_neto          REAL    NOT NULL DEFAULT 0,       -- calculado
    notas               TEXT,
    creado_en           TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

-- -------------------------------------------------------------
-- 4.2  empleados
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS empleados (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre           TEXT    NOT NULL,
    turno_default    TEXT,                                -- 'manana' | 'tarde' | 'noche'
    es_socio         INTEGER NOT NULL DEFAULT 0,          -- boolean
    activo           INTEGER NOT NULL DEFAULT 1,          -- boolean
    fecha_ingreso    TEXT,                                -- date
    fecha_baja       TEXT,                                -- date, NULL si sigue activo
    color_calendario TEXT,
    notas            TEXT
);

-- -------------------------------------------------------------
-- 4.3  turnos
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS turnos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre      TEXT    NOT NULL,                          -- 'manana' | 'tarde' | 'noche'
    hora_inicio TEXT    NOT NULL,                          -- time
    hora_fin    TEXT    NOT NULL,                          -- time
    sueldo      REAL    NOT NULL DEFAULT 0
);

-- -------------------------------------------------------------
-- 4.4  asignaciones_turnos
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS asignaciones_turnos (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha          TEXT    NOT NULL,                       -- date
    empleado_id    INTEGER NOT NULL,
    turno_id       INTEGER NOT NULL,
    es_doble_turno INTEGER NOT NULL DEFAULT 0,             -- boolean
    notas          TEXT,
    creado_en      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (empleado_id) REFERENCES empleados(id),
    FOREIGN KEY (turno_id)    REFERENCES turnos(id)
);

-- -------------------------------------------------------------
-- 4.5  pagos_empleados
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pagos_empleados (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    asignacion_turno_id  INTEGER,
    empleado_id          INTEGER NOT NULL,
    fecha                TEXT    NOT NULL,                  -- date
    monto                REAL    NOT NULL DEFAULT 0,
    pagado               INTEGER NOT NULL DEFAULT 1,        -- boolean (default TRUE al cerrar turno)
    creado_en            TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (asignacion_turno_id) REFERENCES asignaciones_turnos(id),
    FOREIGN KEY (empleado_id)         REFERENCES empleados(id)
);

-- -------------------------------------------------------------
-- 4.6  gastos_extras
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gastos_extras (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha               TEXT    NOT NULL,                  -- date
    categoria           TEXT    NOT NULL,                  -- Gas|Luz|Agua-Pipas|Agua-Embotellada|Mantenimiento|Sam's|StarTV|Otro
    monto               REAL    NOT NULL DEFAULT 0,
    descripcion         TEXT,
    recibo_id           INTEGER,                           -- FK opcional
    fondo_descontado_id INTEGER,                           -- FK opcional
    creado_en           TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (recibo_id)           REFERENCES recibos(id),
    FOREIGN KEY (fondo_descontado_id) REFERENCES fondos(id)
);

-- -------------------------------------------------------------
-- 4.7  gastos_fijos
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gastos_fijos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    concepto        TEXT    NOT NULL,                      -- 'Renta' | 'CFE' | 'StarTV' | 'Contadores'
    monto_estimado  REAL,
    frecuencia      TEXT,                                  -- 'mensual' | 'bimestral' | 'semanal'
    dia_recordatorio INTEGER,                              -- dia del mes
    proxima_fecha   TEXT,                                  -- date, calculado
    activo          INTEGER NOT NULL DEFAULT 1             -- boolean
);

-- -------------------------------------------------------------
-- 4.8  configuracion
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS configuracion (
    clave       TEXT PRIMARY KEY,
    valor       TEXT,
    descripcion TEXT
);

-- -------------------------------------------------------------
-- 4.9  fondos
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fondos (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre            TEXT    NOT NULL,
    descripcion       TEXT,
    meta_mensual      REAL,
    minimo_seguro     REAL,
    aporte_periodico  REAL,
    frecuencia_aporte TEXT,                                -- 'semanal' | 'quincenal' | ...
    dia_aporte        TEXT,                                -- 'lunes' | 'viernes' | ...
    pregunta_antes    INTEGER NOT NULL DEFAULT 1,          -- boolean
    categoria_enlazada TEXT,                               -- NULL o nombre de categoria de gastos
    color             TEXT,                                -- hex
    activo            INTEGER NOT NULL DEFAULT 1           -- boolean
);

-- -------------------------------------------------------------
-- 4.10 movimientos_fondos
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS movimientos_fondos (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    fondo_id       INTEGER NOT NULL,
    fecha          TEXT    NOT NULL,                       -- date
    tipo           TEXT    NOT NULL,                       -- 'deposito' | 'retiro' | 'saltado'
    monto          REAL    NOT NULL DEFAULT 0,
    concepto       TEXT,
    razon_saltado  TEXT,
    gasto_extra_id INTEGER,                                -- FK opcional
    creado_en      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (fondo_id)       REFERENCES fondos(id),
    FOREIGN KEY (gasto_extra_id) REFERENCES gastos_extras(id)
);

-- -------------------------------------------------------------
-- 4.11 metas_fondo
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS metas_fondo (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fondo_id      INTEGER NOT NULL,
    mes           INTEGER NOT NULL,                        -- 1-12
    anio          INTEGER NOT NULL,                        -- SPEC: "año" (se usa 'anio' por compatibilidad)
    meta_monto    REAL,
    acumulado_real REAL    NOT NULL DEFAULT 0,
    meta_lograda  INTEGER NOT NULL DEFAULT 0,              -- boolean
    FOREIGN KEY (fondo_id) REFERENCES fondos(id)
);

-- -------------------------------------------------------------
-- 4.12 inventario
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS inventario (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre            TEXT    NOT NULL,
    unidad            TEXT,
    stock_actual      REAL    NOT NULL DEFAULT 0,
    stock_minimo      REAL    NOT NULL DEFAULT 0,
    precio_unitario   REAL,                                -- ultimo precio pagado
    ultima_compra     TEXT,                                -- date
    proveedor_default TEXT,                                -- "Sam's" | "Mercado Libre" | "Abarrotera" | "Otro"
    activo            INTEGER NOT NULL DEFAULT 1           -- boolean
);

-- -------------------------------------------------------------
-- 4.13 conteos_semanales
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS conteos_semanales (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha         TEXT    NOT NULL,                        -- date (el sabado del conteo)
    inventario_id INTEGER NOT NULL,
    cantidad      REAL    NOT NULL DEFAULT 0,
    notas         TEXT,
    FOREIGN KEY (inventario_id) REFERENCES inventario(id)
);

-- -------------------------------------------------------------
-- 4.14 movimientos_inventario
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS movimientos_inventario (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    inventario_id INTEGER NOT NULL,
    fecha         TEXT    NOT NULL,                        -- date
    tipo          TEXT    NOT NULL,                        -- 'entrada'
    cantidad      REAL    NOT NULL DEFAULT 0,
    precio_total  REAL,
    recibo_id     INTEGER,                                 -- FK opcional
    notas         TEXT,
    FOREIGN KEY (inventario_id) REFERENCES inventario(id),
    FOREIGN KEY (recibo_id)     REFERENCES recibos(id)
);

-- -------------------------------------------------------------
-- 4.15 recibos
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS recibos (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_subida           TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    fecha_recibo           TEXT,                           -- date
    proveedor              TEXT,
    monto_total            REAL,
    ruta_imagen            TEXT,                           -- path relativo al proyecto
    hash_md5               TEXT,                           -- para detectar duplicados
    procesado_por_ia       INTEGER NOT NULL DEFAULT 0,     -- boolean
    gasto_extra_id         INTEGER,                        -- FK
    inventario_actualizado INTEGER NOT NULL DEFAULT 0,     -- boolean
    notas                  TEXT,
    FOREIGN KEY (gasto_extra_id) REFERENCES gastos_extras(id)
);

-- -------------------------------------------------------------
-- 4.16 uso_ia
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uso_ia (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha         TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    funcion       TEXT,                               -- modulo_origen: 'recibos' | 'asistente' | ...
    modelo        TEXT,
    tokens_input  INTEGER,
    tokens_output INTEGER,
    costo_usd     REAL,
    costo_mxn     REAL,
    exito         INTEGER NOT NULL DEFAULT 1,         -- boolean
    error_message TEXT
);

-- -------------------------------------------------------------
-- 4.17 bitacora_calendario
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bitacora_calendario (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_cambio       TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    fecha_afectada     TEXT,                               -- date
    descripcion        TEXT,
    solicitud_original TEXT,                               -- mensaje del usuario
    usuario            TEXT
);

-- -------------------------------------------------------------
-- 4.18 correcciones_ia
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS correcciones_ia (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha            TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    funcion          TEXT,
    input_original   TEXT,
    output_ia        TEXT,
    output_corregido TEXT,
    usado_como_ejemplo INTEGER NOT NULL DEFAULT 0          -- boolean
);

-- -------------------------------------------------------------
-- 4.19 conversaciones_ia
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS conversaciones_ia (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    sesion_id     TEXT    NOT NULL,                        -- UUID
    fecha         TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    rol           TEXT    NOT NULL,                        -- 'user' | 'assistant'
    mensaje       TEXT,
    tokens_usados INTEGER
);

-- -------------------------------------------------------------
-- 4.20 reportes_narrativas (Sub-fase 3C)
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reportes_narrativas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo            TEXT    NOT NULL,  -- 'semanal' | 'mensual'
    periodo_clave   TEXT    NOT NULL,  -- 'semana_2026-05-25' | 'mes_2026-05'
    parrafo         TEXT    NOT NULL,
    bullets         TEXT    NOT NULL,  -- JSON array de 3 strings
    hash_datos      TEXT    NOT NULL,  -- MD5 de los 5 agregados clave
    costo_usd       REAL    NOT NULL,
    fecha_generada  TEXT    NOT NULL,  -- 'YYYY-MM-DD HH:MM'
    UNIQUE(tipo, periodo_clave)
);

-- -------------------------------------------------------------
-- 4.21 cambios_pendientes (Fase 4: asistente conversacional)
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cambios_pendientes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    sesion_id           TEXT    NOT NULL,
    sql                 TEXT    NOT NULL,
    descripcion_humana  TEXT    NOT NULL,
    tabla               TEXT    NOT NULL,
    tipo                TEXT    NOT NULL,          -- 'INSERT' | 'UPDATE' | 'DELETE'
    estado              TEXT    NOT NULL DEFAULT 'pendiente', -- 'pendiente' | 'ejecutado' | 'cancelado'
    fecha_propuesta     TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    fecha_resolucion    TEXT,
    registros_afectados INTEGER
);

-- -------------------------------------------------------------
-- Indices utiles para consultas frecuentes
-- -------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_ingresos_fecha            ON ingresos_diarios(fecha);
CREATE INDEX IF NOT EXISTS idx_gastos_extras_fecha       ON gastos_extras(fecha);
CREATE INDEX IF NOT EXISTS idx_gastos_extras_categoria   ON gastos_extras(categoria);
CREATE INDEX IF NOT EXISTS idx_asignaciones_fecha        ON asignaciones_turnos(fecha);
CREATE INDEX IF NOT EXISTS idx_pagos_empleado            ON pagos_empleados(empleado_id);
CREATE INDEX IF NOT EXISTS idx_mov_fondos_fondo          ON movimientos_fondos(fondo_id);
CREATE INDEX IF NOT EXISTS idx_conteos_inventario        ON conteos_semanales(inventario_id);
CREATE INDEX IF NOT EXISTS idx_mov_inventario_inventario ON movimientos_inventario(inventario_id);
CREATE INDEX IF NOT EXISTS idx_conversaciones_sesion     ON conversaciones_ia(sesion_id);

-- -------------------------------------------------------------
-- 4.22 matches_aprendidos (Sub-fase 5C)
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS matches_aprendidos (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    sku_sams            TEXT    NOT NULL UNIQUE,
    texto_ticket        TEXT    NOT NULL,
    inventario_id       INTEGER NOT NULL,
    veces_confirmado    INTEGER NOT NULL DEFAULT 1,
    primera_vez         TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    ultima_vez          TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (inventario_id) REFERENCES inventario(id)
);

CREATE INDEX IF NOT EXISTS idx_matches_sku ON matches_aprendidos(sku_sams);

-- -------------------------------------------------------------
-- v2.0  usuarios (admins con login)
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS usuarios (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    username       TEXT    UNIQUE NOT NULL,              -- 'turi' | 'gabriel'
    password_hash  TEXT    NOT NULL,
    nombre_display TEXT    NOT NULL,                     -- 'Turi' | 'Gabriel'
    activo         INTEGER NOT NULL DEFAULT 1            -- boolean
);

-- -------------------------------------------------------------
-- v2.1  cuartos (catálogo estático — 10 cuartos del motel)
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cuartos (
    id             INTEGER PRIMARY KEY,                  -- igual que numero
    numero         INTEGER UNIQUE NOT NULL,
    tipo           TEXT    NOT NULL,                     -- 'suite' | 'sencilla' | 'sencilla_jacuzzi' | 'doble_jacuzzi'
    nombre_display TEXT    NOT NULL,
    precio_6h      REAL    NOT NULL,
    precio_12h     REAL    NOT NULL,
    precio_18h     REAL    NOT NULL,
    precio_24h     REAL    NOT NULL
);

-- -------------------------------------------------------------
-- v2.1  rentas (transacciones de renta de cuartos)
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rentas (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    cuarto_id          INTEGER NOT NULL,
    fecha              TEXT    NOT NULL,                 -- date 'YYYY-MM-DD'
    hora_registro      TEXT    NOT NULL,                 -- time 'HH:MM:SS' — servidor, inmutable
    duracion_horas     INTEGER NOT NULL,                 -- 6 | 12 | 18 | 24
    precio_default     REAL    NOT NULL,                 -- precio de tabla al registrar
    precio_cobrado     REAL    NOT NULL,                 -- precio real cobrado
    notas              TEXT,
    estado             TEXT    NOT NULL DEFAULT 'activo',-- 'activo' | 'cancelado'
    registrado_por     TEXT    NOT NULL,                 -- 'admin_turi' | 'admin_gabriel' | 'empleado'
    cancelado_por      TEXT,
    cancelado_at       TEXT,                             -- datetime 'YYYY-MM-DD HH:MM:SS'
    motivo_cancelacion TEXT,
    editado            INTEGER NOT NULL DEFAULT 0,       -- boolean: precio_cobrado != precio_default
    editado_por        TEXT,                             -- quién hizo la última edición
    FOREIGN KEY (cuarto_id) REFERENCES cuartos(id)
);

CREATE INDEX IF NOT EXISTS idx_rentas_fecha   ON rentas(fecha);
CREATE INDEX IF NOT EXISTS idx_rentas_cuarto  ON rentas(cuarto_id);
