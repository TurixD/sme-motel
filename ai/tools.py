"""Definiciones de las 4 tools del asistente conversacional (Fase 4)."""

TOOLS = [
    {
        "name": "ejecutar_sql_lectura",
        "description": (
            "Ejecuta una query SELECT para leer datos del motel. "
            "SOLO lectura — nunca incluyas INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE ni REPLACE."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Query SQL SELECT completa con valores literales (sin parámetros ?).",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "proponer_cambio_datos",
        "description": (
            "Propone un cambio en la base de datos (INSERT, UPDATE o DELETE). "
            "El cambio NO se ejecuta hasta que Turi lo confirme en la interfaz. "
            "Devuelve un cambio_id que el frontend mostrará como tarjeta de confirmación."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "SQL de escritura con valores literales (no parámetros ?).",
                },
                "descripcion_humana": {
                    "type": "string",
                    "description": (
                        "Descripción clara en español del negocio. "
                        "Ej: 'Cambiar turno mañana del 26-jun de Wendy a Dulce'."
                    ),
                },
                "tabla": {
                    "type": "string",
                    "description": "Tabla principal que modifica.",
                },
                "tipo": {
                    "type": "string",
                    "enum": ["INSERT", "UPDATE", "DELETE"],
                    "description": "Tipo de operación SQL.",
                },
            },
            "required": ["sql", "descripcion_humana", "tabla", "tipo"],
        },
    },
    {
        "name": "generar_lista_compra",
        "description": (
            "Genera una lista de compra de inventario para cubrir cierto número de SEMANAS, "
            "con la cantidad sugerida a comprar por producto (basada en el consumo estimado de "
            "los conteos, NO en duplicar el mínimo) y agrupada por proveedor. Úsala cuando Turi "
            "pida algo como 'dame una lista para comprar que me dure dos semanas' o 'qué necesito "
            "surtir'. Devuelve el resumen para que lo comentes y además el sistema le ofrece a Turi "
            "un botón para descargar la lista en PDF. Si Turi no dice cuántas semanas, asume 1."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "semanas": {
                    "type": "integer",
                    "description": "Número de semanas que debe cubrir la compra (1 a 12). Default 1.",
                }
            },
            "required": [],
        },
    },
    {
        "name": "buscar_conversaciones_pasadas",
        "description": (
            "Busca en el historial de conversaciones anteriores del asistente. "
            "Úsala cuando Turi mencione sesiones pasadas: 'ayer hablamos de...', "
            "'qué te dije la semana pasada', 'busca la conversación del...'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fecha_desde": {
                    "type": "string",
                    "description": "YYYY-MM-DD inicio (inclusive). Omitir para sin límite inferior.",
                },
                "fecha_hasta": {
                    "type": "string",
                    "description": "YYYY-MM-DD fin (inclusive). Omitir para sin límite superior.",
                },
                "palabras_clave": {
                    "type": "string",
                    "description": "Texto a buscar en los mensajes (LIKE %texto%). Omitir para traer todos en el rango.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "obtener_fecha_hoy",
        "description": (
            "Devuelve la fecha y hora actual (America/Mexico_City) con el día de la semana. "
            "Ya viene inyectada en tu contexto, pero puedes llamarla para confirmar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },

    # ── Tools de DOMINIO de turnos (la BD calcula fechas/conteos; nunca escribas SQL de turnos) ──
    {
        "name": "consultar_empleados",
        "description": (
            "Lista empleados con id, nombre, turno_default, es_socio y activo. "
            "Filtro opcional 'nombre' (parcial, sin acentos, tolerante a dedazos). "
            "Úsala SIEMPRE para obtener el id de un empleado antes de reasignar turnos — "
            "nunca adivines ids ni nombres."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre": {"type": "string", "description": "Texto para filtrar por nombre (opcional)."}
            },
            "required": [],
        },
    },
    {
        "name": "consultar_asignaciones",
        "description": (
            "Consulta las asignaciones de turno del calendario. La BD calcula todo; "
            "NUNCA enumeres fechas tú. Todos los parámetros son opcionales."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fecha_inicio": {"type": "string", "description": "YYYY-MM-DD. Default: hoy."},
                "fecha_fin": {"type": "string", "description": "YYYY-MM-DD (opcional)."},
                "dia_semana": {"type": "string", "description": "lunes..domingo o 0-6 (lunes=0). Opcional."},
                "empleado_id": {"type": "integer", "description": "Filtra por empleado (opcional)."},
                "turno": {"type": "string", "description": "manana|tarde|noche (opcional)."},
            },
            "required": [],
        },
    },
    {
        "name": "resumen_cobertura",
        "description": (
            "Dado un rango de fechas, devuelve las fechas/turnos que quedan SIN ningún "
            "empleado asignado. Úsala para verificar cobertura antes y después de un cambio."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fecha_inicio": {"type": "string", "description": "YYYY-MM-DD. Default: hoy."},
                "fecha_fin": {"type": "string", "description": "YYYY-MM-DD (opcional)."},
                "turno": {"type": "string", "description": "manana|tarde|noche (opcional; default todos)."},
            },
            "required": [],
        },
    },
    {
        "name": "reasignar_turnos_recurrentes",
        "description": (
            "Propone reasignar un turno de forma recurrente por día de la semana (ej. 'todos los "
            "sábados en la tarde quita a Cecy y pon a Betzaira'). La BD calcula las fechas y ejecuta "
            "TODO en una sola transacción atómica; valida que ninguna fecha quede sin cobertura. "
            "NO ejecuta de inmediato: genera una tarjeta de confirmación con conteos reales que el "
            "usuario debe aprobar. Antes de llamarla, obtén los ids con consultar_empleados y presenta "
            "el plan al usuario. Pide confirmación UNA sola vez."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dia_semana": {"type": "string", "description": "lunes..domingo o 0-6 (lunes=0). Requerido."},
                "turno": {"type": "string", "description": "manana|tarde|noche. Requerido."},
                "quitar_empleado_ids": {"type": "array", "items": {"type": "integer"}, "description": "Ids a quitar (opcional)."},
                "agregar_empleado_ids": {"type": "array", "items": {"type": "integer"}, "description": "Ids a agregar (opcional)."},
                "desde_fecha": {"type": "string", "description": "YYYY-MM-DD. Default: hoy."},
                "hasta_fecha": {"type": "string", "description": "YYYY-MM-DD. Default: última fecha con calendario."},
                "excepciones": {
                    "type": "array",
                    "description": "Casos puntuales que sobrescriben la regla en una fecha concreta.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "fecha": {"type": "string", "description": "YYYY-MM-DD."},
                            "quitar_ids": {"type": "array", "items": {"type": "integer"}},
                            "agregar_ids": {"type": "array", "items": {"type": "integer"}},
                        },
                        "required": ["fecha"],
                    },
                },
            },
            "required": ["dia_semana", "turno"],
        },
    },
    {
        "name": "asignar_turno_fecha",
        "description": (
            "Propone asignar UN empleado a UN turno en UNA fecha concreta (ajuste puntual). "
            "Genera tarjeta de confirmación; no ejecuta de inmediato."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fecha": {"type": "string", "description": "YYYY-MM-DD. Requerido."},
                "turno": {"type": "string", "description": "manana|tarde|noche. Requerido."},
                "empleado_id": {"type": "integer", "description": "Id del empleado. Requerido."},
            },
            "required": ["fecha", "turno", "empleado_id"],
        },
    },
    {
        "name": "quitar_turno_fecha",
        "description": (
            "Propone quitar UN empleado de UN turno en UNA fecha concreta. Rechaza el cambio si "
            "dejaría esa fecha/turno sin nadie. Genera tarjeta de confirmación; no ejecuta de inmediato."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fecha": {"type": "string", "description": "YYYY-MM-DD. Requerido."},
                "turno": {"type": "string", "description": "manana|tarde|noche. Requerido."},
                "empleado_id": {"type": "integer", "description": "Id del empleado. Requerido."},
            },
            "required": ["fecha", "turno", "empleado_id"],
        },
    },
]
