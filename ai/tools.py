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
            "Devuelve la fecha y hora actual del servidor. "
            "Llámala ANTES de cualquier query que use referencias relativas: "
            "'hoy', 'ayer', 'esta semana', 'el mes pasado', 'mañana', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]
