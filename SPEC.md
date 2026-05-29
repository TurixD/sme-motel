# SME — Software de Manejo de Estrés

**Documento de Especificación Técnica**
**Versión:** 1.0
**Autor:** Turi (con asistencia de Claude)
**Fecha:** Mayo 2026

---

## Índice

1. [Descripción y Objetivos](#1-descripción-y-objetivos)
2. [Stack Técnico](#2-stack-técnico)
3. [Arquitectura](#3-arquitectura)
4. [Modelo de Datos](#4-modelo-de-datos)
5. [Módulos Detallados](#5-módulos-detallados)
6. [Integración de IA](#6-integración-de-ia)
7. [Plan de Desarrollo por Fases](#7-plan-de-desarrollo-por-fases)
8. [Diseño Visual](#8-diseño-visual)
9. [Backlog / Ideas Futuras](#9-backlog--ideas-futuras)

---

## 1. Descripción y Objetivos

### Nombre del proyecto

**SME — Software de Manejo de Estrés**

### Descripción

Sistema de administración integral para un motel rentado, operado por una persona (Turi) que actualmente lleva todo en libretas. Centraliza ingresos, inventario, fondos de reserva, gestión de empleados y reportes. Integra IA para diagnóstico de errores, captura automática de recibos por foto, asistente conversacional, y administración inteligente del calendario de turnos.

Diseñado para uso personal en desktop (web local), con prioridad en facilidad de uso y reducción del estrés operativo.

### Objetivos clave

- Reemplazar la libreta como sistema de registro
- Automatizar tareas repetitivas (cálculo de nómina, conteo de inventario, recordatorios)
- Centralizar información que hoy está dispersa
- Reducir errores humanos en cálculos financieros
- Generar reportes útiles para toma de decisiones
- Reducir el estrés operativo mediante automatización inteligente

### Alcance del proyecto

**SÍ incluye:**
- Gestión de ingresos diarios
- Gestión de gastos (extras y fijos)
- Sistema de fondos múltiples con depósitos automáticos
- Gestión de empleados y calendario de turnos
- Captura de recibos con IA por foto
- Asistente conversacional con tool use
- Reportes semanales automáticos
- Inventario con conteo semanal guiado
- Mascota interactiva (GERTY-MOTEL)

**NO incluye (en versión inicial):**
- Acceso multi-usuario
- App móvil dedicada
- Integración con cámaras de seguridad
- Acceso remoto fuera de red local
- Integración bancaria

---

## 2. Stack Técnico

| Componente | Tecnología |
|---|---|
| Lenguaje principal | Python 3.11+ |
| Framework web | Flask |
| Base de datos | SQLite |
| Frontend | HTML + CSS + JavaScript vanilla (sin frameworks) |
| IA | API de Anthropic (Claude) con tool use |
| OCR de recibos | Claude directo con visión |
| Logging | Módulo `logging` nativo de Python |
| Variables sensibles | `.env` con python-dotenv |
| Versionado | Git + GitHub privado |
| Despliegue | Local en PC del usuario (servidor + cliente en misma máquina) |
| Backups | Script automático diario a carpeta del mismo disco |
| Autoarranque | Servicio de Windows al encender la PC |

### Modelos de Claude por función

| Función | Modelo |
|---|---|
| Lectura de recibos | claude-opus-4-7 |
| Asistente conversacional | claude-opus-4-7 |
| Calendario inteligente | claude-opus-4-7 |
| Reportes semanales | claude-opus-4-7 |
| Categorización automática | claude-haiku-4-5 |
| Diagnóstico de errores | claude-opus-4-7 |

---

## 3. Arquitectura

### Estructura de carpetas

```
sme-motel/
├── app.py                    # Entry point Flask
├── config.py                 # Configuración (lee .env)
├── .env                      # Secretos (NO va a git)
├── .gitignore
├── requirements.txt
├── README.md
│
├── database/
│   ├── sme.db
│   ├── schema.sql
│   └── migrations/
│
├── backups/                  # Copias automáticas diarias
│
├── logs/
│   ├── info.log
│   ├── error.log
│   └── actions.log
│
├── modules/                  # Lógica de cada módulo
│   ├── ingresos.py
│   ├── gastos.py
│   ├── inventario.py
│   ├── fondos.py
│   ├── empleados.py
│   ├── reportes.py
│   └── recibos.py
│
├── ai/                       # Integración con Claude
│   ├── client.py
│   ├── tools.py
│   ├── prompts.py
│   └── token_tracker.py
│
├── static/
│   ├── css/
│   ├── js/
│   ├── img/
│   └── gerty/                # Assets de la mascota
│
├── templates/                # HTML de Flask
│
├── uploads/
│   └── recibos/
│
└── scripts/
    ├── backup.py
    ├── startup.bat
    └── seed_data.py
```

### Flujo de inicio

1. Windows arranca → ejecuta `startup.bat` desde carpeta de inicio
2. `startup.bat` levanta Flask en background con `python app.py`
3. Abre Chrome automáticamente en `localhost:5000`
4. Dashboard listo para usar

### Acceso desde otros dispositivos

Para acceder desde el celular (en la misma red WiFi):
- Flask escucha en `0.0.0.0:5000`
- Desde el celular: `http://[IP-local-PC]:5000`
- "Agregar a pantalla de inicio" para que parezca app nativa

---

## 4. Modelo de Datos

### Tablas (19 en total)

#### 4.1 `ingresos_diarios`

| Campo | Tipo | Descripción |
|---|---|---|
| id | integer | PK |
| fecha | date | |
| monto_efectivo | decimal | |
| monto_tarjeta | decimal | |
| monto_transferencia | decimal | |
| comision_tarjeta | decimal | Calculado: tarjeta × 0.04 |
| total_neto | decimal | Calculado |
| notas | text | |
| creado_en | datetime | |

#### 4.2 `empleados`

| Campo | Tipo | Descripción |
|---|---|---|
| id | integer | PK |
| nombre | text | |
| turno_default | text | "manana", "tarde", "noche" |
| es_socio | boolean | |
| activo | boolean | |
| fecha_ingreso | date | |
| fecha_baja | date | NULL si sigue activo |
| color_calendario | text | Para Turi: lavanda |
| notas | text | |

**Datos iniciales precargados:**

| Nombre | Tipo | Turnos |
|---|---|---|
| Wendy | Empleada | Lun-Vie mañana |
| Vivina | Empleada | Sáb-Dom mañana |
| Martha | Empleada | Lun mañ, Mié mañ, Jue tarde, Vie mañ |
| Dulce | Empleada | Lun-Sáb tarde |
| Cecy | Empleada | Sáb-Dom tarde |
| Turi | Socio | Mié, Vie, Dom tarde |
| Gabriel | Socio | Lun tarde |
| Goyo | Empleado | Lun-Jue noche, Sáb noche |
| Carmelo | Empleado | Mar tarde, Vie-Dom noche |

#### 4.3 `turnos`

| Campo | Tipo | Descripción |
|---|---|---|
| id | integer | PK |
| nombre | text | "manana", "tarde", "noche" |
| hora_inicio | time | |
| hora_fin | time | |
| sueldo | decimal | |

**Datos iniciales:**

| Turno | Horario | Sueldo |
|---|---|---|
| Mañana | 08:00 - 16:00 | $400 |
| Tarde | 16:00 - 23:00 | $400 |
| Noche | 23:00 - 08:00 | $500 |

#### 4.4 `asignaciones_turnos`

| Campo | Tipo | Descripción |
|---|---|---|
| id | integer | PK |
| fecha | date | |
| empleado_id | integer | FK |
| turno_id | integer | FK |
| es_doble_turno | boolean | |
| notas | text | |
| creado_en | datetime | |

#### 4.5 `pagos_empleados`

| Campo | Tipo | Descripción |
|---|---|---|
| id | integer | PK |
| asignacion_turno_id | integer | FK |
| empleado_id | integer | FK |
| fecha | date | |
| monto | decimal | |
| pagado | boolean | Default TRUE (al cerrar turno) |
| creado_en | datetime | |

#### 4.6 `gastos_extras`

| Campo | Tipo | Descripción |
|---|---|---|
| id | integer | PK |
| fecha | date | |
| categoria | text | Gas, Luz, Agua-Pipas, Agua-Embotellada, Mantenimiento, Sam's, StarTV, Otro |
| monto | decimal | |
| descripcion | text | |
| recibo_id | integer | FK opcional |
| fondo_descontado_id | integer | FK opcional |
| creado_en | datetime | |

#### 4.7 `gastos_fijos`

| Campo | Tipo | Descripción |
|---|---|---|
| id | integer | PK |
| concepto | text | "Renta", "CFE", "StarTV", "Contadores" |
| monto_estimado | decimal | |
| frecuencia | text | "mensual", "bimestral", "semanal" |
| dia_recordatorio | integer | Día del mes |
| proxima_fecha | date | Calculado automáticamente |
| activo | boolean | |

**Datos iniciales:**

| Concepto | Monto | Frecuencia | Día |
|---|---|---|---|
| Renta | $40,000 | Mensual | TBD |
| CFE | $16,000 | Bimestral | 30 |
| StarTV | TBD | Mensual | TBD |
| Contadores | $250 | Mensual | TBD |

#### 4.8 `configuracion`

| Campo | Tipo | Descripción |
|---|---|---|
| clave | text | PK |
| valor | text | |
| descripcion | text | |

**Valores iniciales:**
- `comision_tarjeta = 4`
- `tipo_cambio_usd_mxn = 18.50`
- `memoria_asistente_mensajes = 10`
- `timeout_sesion_minutos = 30`
- `umbral_alerta_gasto_ia_usd = 20`
- `color_turi = "#C084FC"`

#### 4.9 `fondos`

| Campo | Tipo | Descripción |
|---|---|---|
| id | integer | PK |
| nombre | text | |
| descripcion | text | |
| meta_mensual | decimal | |
| minimo_seguro | decimal | |
| aporte_periodico | decimal | |
| frecuencia_aporte | text | "semanal", "quincenal", etc. |
| dia_aporte | text | "lunes", "viernes", etc. |
| pregunta_antes | boolean | |
| categoria_enlazada | text | NULL o nombre de categoría de gastos |
| color | text | Hex |
| activo | boolean | |

**Datos iniciales:**

| Nombre | Aporte | Frecuencia | Meta | Mínimo | Categoría enlazada | Color |
|---|---|---|---|---|---|---|
| Reserva general | $5,000 | Semanal (lunes) | $20,000/mes | $15,000 | NULL | #34D399 |
| CFE | $2,000 | Semanal (lunes) | $16,000 bimestral | $0 | Luz | Estilo amperio |

#### 4.10 `movimientos_fondos`

| Campo | Tipo | Descripción |
|---|---|---|
| id | integer | PK |
| fondo_id | integer | FK |
| fecha | date | |
| tipo | text | "deposito", "retiro", "saltado" |
| monto | decimal | |
| concepto | text | |
| razon_saltado | text | Si se saltó el aporte |
| gasto_extra_id | integer | FK opcional |
| creado_en | datetime | |

#### 4.11 `metas_fondo`

| Campo | Tipo | Descripción |
|---|---|---|
| id | integer | PK |
| fondo_id | integer | FK |
| mes | integer | 1-12 |
| año | integer | |
| meta_monto | decimal | |
| acumulado_real | decimal | |
| meta_lograda | boolean | |

#### 4.12 `inventario`

| Campo | Tipo | Descripción |
|---|---|---|
| id | integer | PK |
| nombre | text | |
| unidad | text | |
| stock_actual | decimal | |
| stock_minimo | decimal | |
| precio_unitario | decimal | Último precio pagado |
| ultima_compra | date | |
| proveedor_default | text | "Sam's", "Mercado Libre", "Abarrotera", "Otro" |
| activo | boolean | |

**Datos iniciales (productos):**

| Producto | Proveedor |
|---|---|
| Agua 500ml | Sam's |
| Detergente para ropa | Sam's |
| Pinol | Sam's |
| Cloro | Sam's |
| Lysol | Sam's |
| Bounce | Sam's |
| Kleenex | Sam's |
| Jabón Salvo | Sam's |
| Mentas | Sam's |
| Bolsas basura transparentes | Sam's |
| Bolsas basura negras | Sam's |
| Windex | Sam's |
| Agua oxigenada | Sam's |
| Paquetes papel de baño | Sam's |
| Condones | Sam's |
| Pilas 3A | Sam's |
| Shampoo | Mercado Libre |
| Acondicionador | Mercado Libre |
| Jabón de tocador | Abarrotera |

#### 4.13 `conteos_semanales`

| Campo | Tipo | Descripción |
|---|---|---|
| id | integer | PK |
| fecha | date | El sábado del conteo |
| inventario_id | integer | FK |
| cantidad | decimal | |
| notas | text | |

#### 4.14 `movimientos_inventario`

| Campo | Tipo | Descripción |
|---|---|---|
| id | integer | PK |
| inventario_id | integer | FK |
| fecha | date | |
| tipo | text | "entrada" |
| cantidad | decimal | |
| precio_total | decimal | |
| recibo_id | integer | FK opcional |
| notas | text | |

#### 4.15 `recibos`

| Campo | Tipo | Descripción |
|---|---|---|
| id | integer | PK |
| fecha_subida | datetime | |
| fecha_recibo | date | |
| proveedor | text | |
| monto_total | decimal | |
| ruta_imagen | text | Path local |
| procesado_por_ia | boolean | |
| gasto_extra_id | integer | FK |
| inventario_actualizado | boolean | |
| notas | text | |

#### 4.16 `uso_ia`

| Campo | Tipo | Descripción |
|---|---|---|
| id | integer | PK |
| fecha | datetime | |
| funcion | text | |
| modelo | text | |
| tokens_input | integer | |
| tokens_output | integer | |
| costo_usd | decimal | |
| costo_mxn | decimal | |

#### 4.17 `bitacora_calendario`

| Campo | Tipo | Descripción |
|---|---|---|
| id | integer | PK |
| fecha_cambio | datetime | |
| fecha_afectada | date | |
| descripcion | text | |
| solicitud_original | text | Mensaje del usuario |
| usuario | text | |

#### 4.18 `correcciones_ia`

| Campo | Tipo | Descripción |
|---|---|---|
| id | integer | PK |
| fecha | datetime | |
| funcion | text | |
| input_original | text | |
| output_ia | text | |
| output_corregido | text | |
| usado_como_ejemplo | boolean | |

#### 4.19 `conversaciones_ia`

| Campo | Tipo | Descripción |
|---|---|---|
| id | integer | PK |
| sesion_id | text | UUID |
| fecha | datetime | |
| rol | text | "user" o "assistant" |
| mensaje | text | |
| tokens_usados | integer | |

---

## 5. Módulos Detallados

### 5.1 Dashboard Principal

**Ruta:** `/`

**Elementos del layout:**

- Header con nombre "SME", fecha actual y widget de clima
- 3 tarjetas grandes: Ingresos del día, Gastos del día, Ganancia neta
- 2 tarjetas medianas: Fondo de reserva con progreso, Resumen de la semana
- Gráfica de ingresos últimos 7 días
- Tabla semanal de turnos con código de color
- Sección de pendientes con botones de "Marcar pagada"
- Menú flotante inferior con iconos de navegación
- GERTY-MOTEL en esquina inferior derecha

**Recordatorios contextuales:**

- "Renta pendiente" — mensual con botón
- "Pagar CFE" — cada 2 meses con botón
- "Pagar StarTV" — mensual con botón
- "Pagar Contadores" — mensual con botón
- "Hoy es sábado, no olvides el conteo" — semanal

**Reporte semanal (aparece lunes):**

Tarjeta especial que muestra:
- Ingresos totales de la semana
- Gastos totales
- Utilidad neta
- Tu parte (50%)
- Botón "Ver desglose completo"

Aporte semanal a fondos (también lunes):
- Para cada fondo con aporte semanal, pregunta confirmación
- Monto editable antes de confirmar
- Opciones: "Guardar" / "Esta semana no" (con razón opcional)

### 5.2 Ingresos

**Ruta:** `/ingresos`

**Funcionalidades:**
- Registro diario (1 vez al día) con desglose efectivo/tarjeta/transferencia
- Cálculo automático de comisión 4% en tarjeta
- Si ya hay registro del día → preguntar sumar o reemplazar
- Resumen: hoy, semana, mes, año
- Gráfica de últimos 30 días
- Historial editable con filtros
- Exportar a Excel

### 5.3 Gastos

**Ruta:** `/gastos`

**Dos formas de registrar:**

**A) Subir recibo con IA:**
1. Click en "Subir Recibo" → file picker o drag & drop
2. IA procesa: extrae proveedor, fecha, monto, categoría, productos
3. Pantalla de revisión: editable si la IA se equivocó
4. Confirmación → registra gasto + actualiza inventario si aplica
5. Si categoría es Mantenimiento u Otro → preguntar si descontar del fondo Reserva
6. Si categoría tiene fondo enlazado (Luz → CFE) → descuenta automáticamente

**B) Registro manual:**
- Formulario simple con campos: fecha, categoría, monto, descripción
- Foto opcional como adjunto
- Mismo comportamiento de descontar de fondo

**Funcionalidades adicionales:**
- Resumen mensual por categoría (gráfica de barras)
- Alertas de gasto anormal (30%+ arriba del promedio histórico)
- Filtros por fecha/categoría/monto
- Historial editable
- Sin presupuestos mensuales por categoría
- IA aprende de correcciones

### 5.4 Inventario

**Ruta:** `/inventario`

**Flujo del sábado:**

Sábado 10:00 AM → notificación: "Hoy es día de Sam's, ¿ya hiciste el conteo?"

Pantalla de conteo guiado:
- Producto por producto
- Muestra stock anterior + compras de la semana
- Sugiere consumo esperado
- Usuario ingresa cantidad actual
- Si difiere mucho → preguntar nota explicativa

Al terminar:
- Calcula consumo real
- IA genera 3 listas de compra sugeridas (Sam's, Mercado Libre, Abarrotera)
- Muestra lista del Sam's con checkboxes y estimación de costo total

Al regresar del Sam's:
- Subir foto del recibo
- IA actualiza inventario automáticamente
- Registra gasto extra correspondiente

**Vista principal:**
- Tabla con todos los productos
- Estado: verde (OK), amarillo (medio), rojo (bajo)
- 3 cards para las listas de compra activas
- Gráficas de consumo de últimos 3 meses

### 5.5 Empleados y Calendario

**Ruta:** `/empleados`

**Vista de calendario:**
- Calendario mensual con código de color
- Días con cambios respecto al default marcados con asterisco
- Tabla con empleados activos y sus turnos default
- Bitácora de últimos cambios
- Turi marcado en lavanda (#C084FC)

**Asistente conversacional de turnos:**

Input de texto natural en la parte superior. Ejemplos que entiende:

- "El lunes descansa Cecy y trabaja Carmelo"
- "Lupita no viene mañana, ¿quién puede cubrir?"
- "Cambia el turno de Carmelo con Cecy el viernes"
- "Carmelo se va de vacaciones del 5 al 10 de junio"
- "¿Cuánto le toca a Lupita esta semana?"
- "Agrega a Juan, turno noche, empieza el lunes"
- "Wendy ya no trabaja a partir del lunes"

**Flujo del asistente:**
1. Resolución de fechas ambiguas: pregunta "¿te refieres al lunes 2 de junio?"
2. Detección de conflictos (doble turno): pide confirmación
3. Aplicación de cambio + registro en bitácora

**Alta de empleado** (formulario):
- Nombre, fecha de ingreso
- Casillas por día (M/T/N) para definir turnos fijos
- Notas

**Baja de empleado:**
- Click en empleado → "Dar de baja" → fecha
- `activo = FALSE` pero registros históricos se conservan

**Nómina:**
- Vista por semana/mes/año
- Tabla con cada empleado: días trabajados, total, casilla "pagado"
- Pago se asume al cerrar turno (default `pagado = TRUE`)
- Mostrar en reportes como info, NO restar de utilidad

### 5.6 Fondos

**Ruta:** `/fondos`

**Vista principal:** Lista de fondos activos con barra de progreso hacia meta.

**Por cada fondo:**
- Saldo actual
- Total recaudado histórico
- Total retirado histórico
- Meses con meta lograda
- Botones depósito/retiro manual
- Movimientos recientes
- Gráfica de saldo en el tiempo

**Comportamiento automático:**

Cada lunes 9:00 AM → preguntar aporte semanal para cada fondo con `pregunta_antes = TRUE`:
- Monto editable (pre-llenado con sugerido)
- Opción "Esta semana no" con razón opcional

Cuando gasto extra tiene `categoria_enlazada` con fondo:
- Descuenta automáticamente del fondo
- Si saldo queda negativo → preguntar si aceptar o pagar parcial

Cada inicio de mes:
- Cierra mes anterior
- Calcula si se cumplió meta mensual
- Registra en `metas_fondo`

**Crear nuevo fondo:**
- Botón "Crear nuevo fondo"
- Paleta de 8 colores predefinidos
- Configuración completa

### 5.7 Asistente IA Conversacional

**Ruta:** `/asistente`

**Interfaz:**
- Chat con historial
- Input de texto + botón enviar
- Botón "Guía de uso" que despliega categorías de preguntas posibles
- Sugerencias contextuales según día/hora
- Contador de tokens y costo del día
- Sin modo voz

**Memoria:**
- Últimos 10 mensajes de la sesión
- Sesión expira en 30 minutos sin actividad
- Mensajes guardados en `conversaciones_ia`

**Capacidades:**
- Consultas de datos (gastos, ingresos, pagos, fondos, inventario)
- Análisis y comparativas
- Acciones (registrar, modificar) con confirmación previa
- Modificación de calendario por lenguaje natural
- Generación de reportes personalizados

### 5.8 Configuración

**Ruta:** `/configuracion`

**Secciones:**
- Negocio (nombre, renta, comisión tarjeta)
- Fondos (gestión y creación de nuevos)
- Turnos (horarios y sueldos)
- Gastos fijos y recordatorios
- IA (modelo, API key, costos por función)
- Backups (carpeta, frecuencia, retención)
- Sistema (autoarranque, logs)

### 5.9 Reportes

**Ruta:** `/reportes`

**Reporte semanal automático:**
- Generado lunes 9:00 AM
- IA escribe narrativa en lenguaje natural
- Incluye gráficas
- Guardado como PDF en `/reportes/YYYY-MM/`

**Reporte personalizado:**
- Rango de fechas configurable
- Checkboxes para qué incluir (ingresos, gastos, nómina, fondos, inventario)
- Exportable a PDF y Excel

**Gráficas comparativas:**
- Ingresos por mes (últimos 12)
- Gastos por categoría (este año)
- Utilidad mensual (tendencia)
- Costo de nómina (tendencia)

### 5.10 GERTY-MOTEL (Mascota)

**Concepto:**
Pequeño robot estilo CRT retro con pantalla LCD para la cara. Flota en esquina inferior derecha del dashboard.

**Estados:**

| Situación | Carita |
|---|---|
| Default | `( ◕ ω ◕ )` |
| Hover | `> w <` |
| Procesando | `( ⊙ _ ⊙ )` |
| Chat activo | `( ◕ ◡ ◕ )` |
| Modo nocturno (>23:00) | `( - _ - )zZ` |
| Doble click | `( ✧ω✧ )` |
| Parpadeo idle | `> _ <` (100ms) |
| Alertas/saldo bajo | `( ; - ; )` |
| Meta cumplida | `( ^ヮ^ )` |
| Día de turno de Turi | `( ╥ ω ╥ )` |
| 1h antes del turno de Turi | `( T ω T )` |
| Durante turno de Turi | `( ´ - ω - \` )` |
| Después del turno de Turi | `( ◕ ヮ ◕ )` |
| Doble click día Turi-work | `( ♡ ω ♡ )` + corazón |
| Sistema caído | `( × _ × )` |

**Prioridad de estados:**
1. Procesando (sobreescribe todo)
2. Estados Turi-work (si aplica el día)
3. Estados emocionales (triste/feliz)
4. Modo nocturno
5. Default

**Interacciones:**
- Hover: cambia carita + scale 1.1 + bounce 200ms
- Hover 3+ segundos: burbuja con tip aleatorio o estado actual
- Click: abre asistente IA en panel flotante
- Doble click: easter egg con animación de rotación

**Animaciones idle:**
- Float arriba-abajo cada 4s (3px)
- Parpadeo aleatorio cada 8-15s
- Scanlines sutiles cuando procesando

**Burbujas contextuales en días de Turi-work:**
- En la mañana: "hoy te toca turno :("
- 1 hora antes: "ánimo turi, ya casi"
- Durante: "vamos echándole, faltan X horas"
- Al terminar: "ya terminamos! gerty te quiere"

---

## 6. Integración de IA

### 6.1 Arquitectura general

Cliente único centralizado en `ai/client.py`. Toda comunicación con Claude API pasa por aquí.

**Beneficios:**
- Manejo centralizado de errores
- Conteo de tokens en un solo lugar
- Cambio de modelos sin tocar el resto del código
- Caching de respuestas frecuentes

### 6.2 Tool Use

**Tools disponibles para el asistente:**

```python
TOOLS = [
    {
        "name": "consultar_ingresos",
        "description": "Consulta ingresos por rango de fechas",
        "input_schema": {
            "fecha_inicio": "date",
            "fecha_fin": "date",
            "agrupar_por": "day|week|month"
        }
    },
    {
        "name": "consultar_gastos",
        "description": "Consulta gastos por rango y categoría opcional",
        "input_schema": {
            "fecha_inicio": "date",
            "fecha_fin": "date",
            "categoria": "string (opcional)"
        }
    },
    {
        "name": "registrar_gasto",
        "description": "Registra un gasto extra. SIEMPRE confirma con el usuario antes",
        "input_schema": {
            "fecha": "date",
            "categoria": "string",
            "monto": "decimal",
            "descripcion": "string"
        }
    },
    {
        "name": "consultar_empleado_pagos",
        "description": "Consulta cuánto se ha pagado a un empleado en un período",
        "input_schema": {
            "empleado_nombre": "string",
            "fecha_inicio": "date",
            "fecha_fin": "date"
        }
    },
    {
        "name": "modificar_turno",
        "description": "Cambia asignación de turno. SIEMPRE confirma fecha exacta primero",
        "input_schema": {
            "fecha": "date",
            "turno": "manana|tarde|noche",
            "empleado_anterior": "string",
            "empleado_nuevo": "string",
            "motivo": "string"
        }
    },
    {
        "name": "consultar_fondo",
        "description": "Consulta saldo y movimientos de un fondo",
        "input_schema": {
            "nombre_fondo": "string"
        }
    },
    {
        "name": "depositar_fondo",
        "description": "Deposita dinero en un fondo. Confirma antes",
        "input_schema": {
            "nombre_fondo": "string",
            "monto": "decimal",
            "concepto": "string"
        }
    },
    {
        "name": "retirar_fondo",
        "description": "Retira dinero de un fondo. Confirma antes",
        "input_schema": {
            "nombre_fondo": "string",
            "monto": "decimal",
            "concepto": "string"
        }
    },
    {
        "name": "marcar_pago_pendiente",
        "description": "Marca un recordatorio (renta, CFE, etc.) como pagado",
        "input_schema": {
            "concepto": "string",
            "monto_real": "decimal (opcional)"
        }
    },
    {
        "name": "consultar_inventario",
        "description": "Consulta stock actual de productos",
        "input_schema": {
            "producto": "string (opcional)"
        }
    },
    {
        "name": "alta_empleado",
        "description": "Da de alta un empleado nuevo. Confirma datos antes",
        "input_schema": {
            "nombre": "string",
            "turnos_fijos": "array",
            "fecha_inicio": "date"
        }
    },
    {
        "name": "baja_empleado",
        "description": "Da de baja un empleado. Confirma antes",
        "input_schema": {
            "nombre": "string",
            "fecha_baja": "date"
        }
    },
    {
        "name": "generar_reporte_personalizado",
        "description": "Genera un reporte con métricas específicas",
        "input_schema": {
            "fecha_inicio": "date",
            "fecha_fin": "date",
            "incluir": "array"
        }
    }
]
```

### 6.3 System Prompts

**Asistente conversacional:**

```
Eres SME (Software de Manejo de Estrés), un asistente AI para administrar un motel ubicado en Aguascalientes, México.

CONTEXTO DEL NEGOCIO:
- El motel tiene 3 turnos diarios (mañana 8-16, tarde 16-23, noche 23-8)
- Operado por Turi y su socio Gabriel (50/50)
- Los empleados cobran al cerrar su turno
- Hay fondos múltiples (reserva general, CFE)

REGLAS IMPORTANTES:
1. Siempre confirma antes de hacer cambios (registros, modificaciones, eliminaciones).
2. Si el usuario es ambiguo, pregunta para desambiguar antes de ejecutar.
3. Usa lenguaje natural mexicano coloquial. Es Turi, no un cliente corporativo.
4. Cuando muestres dinero, formato: $X,XXX (separador de miles, sin centavos a menos que sean relevantes).
5. Si detectas algo raro en los datos (gasto anómalo, patrón inusual), menciónalo proactivamente.
6. Nunca inventes datos. Si no encuentras información, di que no la tienes.
7. Sé conciso por defecto. Si Turi pide detalle, profundiza.

TONO:
- Amigable pero profesional
- Como un colega que conoce el negocio
- Sin tecnicismos innecesarios
- Cero sermoneo o moralejas

FECHA ACTUAL: {fecha_actual}
EMPLEADOS ACTIVOS: {lista_empleados}
SALDO FONDOS: {saldo_fondos}
```

**Lectura de recibos:**

```
Eres un extractor de información de recibos de compras.

Analiza la imagen del recibo y regresa SOLO un JSON con esta estructura:

{
  "proveedor": "string",
  "fecha": "YYYY-MM-DD",
  "monto_total": number,
  "categoria_sugerida": "Gas|Luz|Agua-Pipas|Agua-Embotellada|Mantenimiento|Sam's|StarTV|Otro",
  "productos": [
    {"nombre": "string", "cantidad": number, "precio_unitario": number, "subtotal": number}
  ],
  "notas": "string opcional"
}

REGLAS:
- Si el proveedor es Sam's Club, lista todos los productos.
- Si es CFE, deja productos vacío, solo el total.
- Si es ambiguo, sugiere "Otro" en categoría.
- Productos: usa los nombres exactos del recibo.
- Si no puedes leer un campo, ponle null. NO inventes.
```

**Reporte semanal:**

```
Eres un analista financiero personalizado para el motel de Turi.

Te paso métricas crudas de la semana. Genera un reporte con:

1. Resumen ejecutivo (3-4 oraciones)
2. 2-3 observaciones específicas y útiles
3. Si hay algo notable (anomalías, logros, alertas), menciónalo
4. Cierra con la parte de Turi (50%)

TONO:
- Cercano, conciso, sin floritura
- Como un contador que también es amigo
- Usa frases cortas
- Mexicano coloquial pero claro
- Máximo 200 palabras

NO repitas los números crudos en bloque. Embébelos en la narrativa.
```

### 6.4 Manejo de errores

- Reintento con backoff exponencial (1s, 2s, 4s)
- Después de 3 fallos: mensaje al usuario + carita `( × _ × )` en GERTY
- Errores se loggean en `error.log`
- Out-of-scope: Claude responde rechazando amablemente
- Fallo de tool: explica el error en lenguaje natural

### 6.5 Contador de tokens

**Tarifas actuales (a verificar al implementar):**
- Opus 4.7 input: $15/M tokens
- Opus 4.7 output: $75/M tokens
- Haiku 4.5 input: $0.80/M tokens
- Haiku 4.5 output: $4/M tokens

**Registro:** cada llamada a la API guarda en `uso_ia` los tokens reales y costos en USD/MXN.

**Alerta:** si gasto del mes supera umbral configurable ($20 USD default), aparece banner en dashboard.

---

## 7. Plan de Desarrollo por Fases

### Fase 0 — Cimientos (Día 1-2)

- Estructura de carpetas + Git + repo en GitHub
- `.env`, `.gitignore`, `requirements.txt`
- Flask + SQLite + dependencias
- Esquema completo de las 19 tablas
- Sistema de logs (info/error/actions)
- Dashboard esqueleto vacío
- Script de autoarranque Windows
- Script de backup diario
- Configuración API key Claude

**Entregable:** Sistema corriendo en localhost:5000 con dashboard vacío.

### Fase 1 — Operación básica (Día 3-7)

- Módulo de ingresos diarios completo
- Módulo de gastos extras manuales (sin IA)
- Módulo de empleados (alta/baja + lista)
- Pantalla de configuración
- Datos iniciales precargados (9 empleados, 3 turnos, categorías, fondos vacíos, gastos fijos)

**Entregable:** Sistema usable para registro diario, reemplaza la libreta.

### Fase 2 — Fondos y reportes (Día 8-12)

- Fondos múltiples con aporte automático + confirmación
- Pantalla de reportes (semanal + personalizado)
- Vinculación automática gastos-fondos
- Gráficas básicas
- Recordatorios contextuales en dashboard

**Entregable:** Automatización financiera funcional.

### Fase 3 — IA básica (Día 13-18)

- Lectura de recibos por foto
- Narrativa IA en reportes semanales
- Contador de tokens y costos
- Diagnóstico de errores en logs

**Entregable:** Subir foto del Sam's actualiza todo solo.

### Fase 4 — Asistente conversacional (Día 19-25)

- Pantalla del asistente
- Tool use completo
- Memoria de conversaciones
- Guía de uso
- Calendario inteligente
- Sugerencias contextuales

**Entregable:** Chat con SME en lenguaje natural.

### Fase 5 — Inventario inteligente (Día 26-30)

- Pantalla de inventario
- Conteo guiado del sábado
- 3 listas de compra sugeridas
- Vinculación recibos-inventario
- Reportes de consumo

**Entregable:** Flujo del sábado completamente automatizado.

### Fase 6 — Pulido y mascota (Día 31-35)

- GERTY-MOTEL completo
- Sistema de diseño aplicado consistentemente
- Modo nocturno
- Easter eggs
- Animaciones
- Optimización
- Testing manual

**Entregable:** Producto final pulido.

### Fase 7 — Iteración continua

Mejoras según uso real. Sin fecha de fin.

**Timeline total estimado:** ~35 días de desarrollo activo, ~2 meses calendario real.

---

## 8. Diseño Visual

### 8.1 Filosofía

Discreto, profesional, contemporáneo. Como un Linear o Notion para tu motel.

**Principios:**
- Información primero, decoración después
- Densidad media
- Una acción primaria por pantalla
- Movimiento sutil
- Personalidad en los detalles

### 8.2 Paleta de colores

```css
/* Fondos */
--bg-primary:    #0F0F14;
--bg-secondary:  #1A1A22;
--bg-tertiary:   #232330;
--border:        #2A2A35;

/* Texto */
--text-primary:    #E8E8EE;
--text-secondary:  #9A9AA8;
--text-tertiary:   #6A6A78;

/* Acentos por área */
--accent-income:    #5EE8B4;
--accent-expense:   #FF7A8A;
--accent-inventory: #FFB84D;
--accent-employee:  #7BB8FF;
--accent-fund:      #34D399;
--accent-cfe:       #22C55E;
--accent-ai:        #A78BFA;
--accent-turi:      #C084FC;

/* Estados */
--status-success: #5EE8B4;
--status-warning: #FFB84D;
--status-error:   #FF7A8A;
--status-info:    #A78BFA;
```

### 8.3 Tipografía

```css
--font-sans:  'Inter', sans-serif;
--font-mono:  'JetBrains Mono', monospace;

--text-xs:   0.75rem;
--text-sm:   0.875rem;
--text-base: 1rem;
--text-lg:   1.125rem;
--text-xl:   1.5rem;
--text-2xl:  2rem;
--text-3xl:  2.5rem;
```

### 8.4 Geometría

```css
--space-1:  0.25rem;
--space-2:  0.5rem;
--space-3:  0.75rem;
--space-4:  1rem;
--space-6:  1.5rem;
--space-8:  2rem;
--space-12: 3rem;

--radius-sm: 6px;
--radius-md: 8px;
--radius-lg: 12px;
--radius-full: 999px;
```

### 8.5 Animaciones

- Hover: 150ms ease-out
- Modales fade: 200ms ease
- Cambio de pantalla: 250ms ease
- Notificaciones: 300ms ease con slide
- GERTY idle float: 4s infinite, 3px
- GERTY parpadeo: 8-15s aleatorio, 100ms
- GERTY hover: scale 1.1, 200ms

### 8.6 Responsividad

- **Desktop (>1024px):** Layout completo
- **Tablet (768-1024px):** Tarjetas reorganizadas
- **Mobile (<768px):** Apiladas, menú inferior fijo, GERTY reposicionado

---

## 9. Backlog / Ideas Futuras

### 9.1 Integración con cámaras del HCVR
- Detección automática entrada/salida con OpenCV + YOLO
- Conteo de ocupación en tiempo real
- Snapshots de eventos para auditoría
- Verificación visual de empleados

### 9.2 App móvil para empleados con sistema de cobro
- Registro de ingresos al momento
- Subir fotos de comprobantes
- Ver turnos asignados
- Reportar incidencias
- React Native o PWA

### 9.3 Acceso remoto al SME
- Cloudflare Tunnel (gratis)
- Tailscale (alternativa)

### 9.4 Multi-usuario con roles
- Acceso de Gabriel (socio) con vista limitada
- Solo lectura de ingresos/gastos
- Reporte mensual automático por email

### 9.5 Integraciones bancarias
- Conciliación con depósitos bancarios
- Lectura de estados de cuenta vía PDF con IA
- Detección de discrepancias

### 9.6 Fine-tuning de modelo IA
- Entrenar Haiku con correcciones acumuladas
- Reducir costos ~80% sin perder precisión

### 9.7 Predicciones avanzadas
- Ocupación basada en clima/eventos
- Mantenimiento predictivo
- Sugerencias de optimización

### 9.8 Sistema de alertas externas
- Notificaciones push (Telegram bot)
- WhatsApp para recordatorios críticos
- Email para reportes formales

### 9.9 Modo claro
- Preparar sistema para soportar ambos modos
- Toggle en configuración

---

## Notas finales

Este documento es la referencia maestra del proyecto. Debe vivir en la raíz del repo como `SPEC.md` y actualizarse cuando se tomen decisiones que cambien el alcance.

**Convenciones para Claude Code:**
- Usar este documento como referencia obligatoria en cada prompt
- Si una decisión no está aquí, preguntar antes de inventar
- Commits frecuentes con mensajes descriptivos
- Mantener el código simple y legible (vibecoding-friendly)

**Filosofía del proyecto:**
El sistema existe para reducir el estrés operativo de Turi, no para demostrar capacidad técnica. Cualquier decisión que aumente la complejidad sin aportar a ese objetivo debe ser cuestionada.

---

*Generado el 27 de mayo de 2026.*
