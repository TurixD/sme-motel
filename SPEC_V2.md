# SME v2.0 — Especificación

> Documento maestro de planeación para SME v2. Complementa al `SPEC.md` original (v1).
> Branch de desarrollo: `v2-dev`. Merge a `main` cuando v2 esté completa.

---

## 0. Contexto

SME v1 (`main`, tag `v1.0`) es un ERP completo single-user para el motel Hacienda del Sauz en Calvillo, Aguascalientes. v1 cubre: dashboard, fondos, ingresos, gastos con IA, inventario inteligente con aprendizaje por SKU, asistente conversacional con tool use, mascota GERTY animada.

v2 introduce **multi-rol con autenticación**, una **nueva pantalla de cuartos** con precios por duración, **cortes de turno** con flujo de pagos físicos, y **restricciones visuales por rol**.

La arquitectura técnica (Flask + SQLite + IA agéntica) se mantiene. v2 NO es rewrite, es extensión.

---

## 1. Cambio fundamental respecto a v1

| Aspecto | v1 | v2 |
|---|---|---|
| Usuarios | Single-user (admin implícito) | 2 admins (Turi, Gabriel) + modo empleado genérico |
| Login | No requerido | Password individual por admin |
| Sesión | No tiene | Persistente en BD (PC del motel queda en modo activo) |
| Pantalla de cuartos | No existe | Nueva, central para operación diaria |
| Cortes de turno | No existe | Mañana / Tarde / Noche con flujo de aprobación |
| GERTY | Reacciona a todo el estado del sistema | En modo empleado: solo estado default |

---

## 2. Decisiones de arquitectura

### 2.1 Autenticación

- **Tabla `usuarios`** con dos registros fijos: Turi y Gabriel
- Login con password hasheada (bcrypt o equivalente)
- Sin recuperación de password automática — si se olvida, recuperación manual vía SQL directo a BD
- No hay 2FA por ahora (descartado por ser sistema local, sin justificación de complejidad)

### 2.2 Sesión persistente

El estado del sistema (`modo_actual`) vive en una fila de la tabla `configuracion` (o tabla nueva si conviene). Valores:

- `admin_turi` — Turi loggeado
- `admin_gabriel` — Gabriel loggeado
- `empleado` — modo empleado activo

Esto significa que **toda la PC del motel** queda en el modo activo. Refrescar página, reiniciar PC, limpiar cookies del navegador → no afecta el modo. Solo un nuevo login admin desbloquea.

### 2.3 Toggle de modo

- **Admin → Empleado**: modal de confirmación simple, SIN password. Instantáneo.
- **Empleado → Admin**: siempre requiere password (Turi o Gabriel, cualquiera de los dos).

Justificación del diseño asimétrico:
- El toggle a empleado es para "cerrar la caja fuerte" cuando admin se va. Debe ser rápido.
- El toggle a admin requiere autenticación porque desbloquea acceso total al sistema.
- Si un empleado curioso pulsa el toggle a empleado por joder, admin se desbloquea con su password en 5 segundos. Fricción aceptable.

### 2.4 Arquitectura física

- Una sola PC fija en recepción del motel
- Todos los empleados usan la misma instancia del navegador
- No hay multi-dispositivo (todavía — posible v3)

---

## 3. Pantalla nueva: `/cuartos`

### 3.1 Inventario de cuartos

10 cuartos numerados, con precios por duración:

| Cuarto | Tipo | 6h | 12h | 18h | 24h |
|---|---|---|---|---|---|
| 1 | Suite con jacuzzi + balcón | $700 | $1,050 | $1,400 | $1,550 |
| 2-8 | Sencilla | $350 | $500 | $700 | $800 |
| 9 | Sencilla con jacuzzi | $500 | $750 | $1,000 | $1,100 |
| 10 | Doble con jacuzzi | $600 | $900 | $1,200 | $1,350 |

### 3.2 Registro de renta

Click en cuarto → modal:

- Selector de duración (botones 6h / 12h / 18h / 24h)
- Precio autocompletado según duración (editable, por si hay descuento o ajuste)
- Notas opcionales (texto libre)
- Hora de registro automática (no editable)

**No hay manejo de estatus "libre/ocupado"** — solo se registra el cobro cuando se cierra la transacción.

### 3.3 Edición y eliminación

- **Empleado**: solo puede crear rentas. No puede editar ni eliminar.
- **Admin (NO en modo empleado)**:
  - Puede editar monto (para corregir errores del empleado)
  - Puede eliminar — soft-delete (`estatus = 'cancelado'`), no borra de tabla
  - Las canceladas no cuentan en totales pero quedan en BD para auditoría

### 3.4 Integración con ingresos del día

- Tabla nueva `rentas` para manejar los datos del módulo aparte
- Cada renta registrada se **sincroniza automáticamente con `ingresos_diarios`**
- Al hacer corte de turno, el monto agregado del turno entra en `ingresos_diarios` como bloque consolidado
- Los sueldos se descuentan a las **12 AM** (corte de turno noche)

---

## 4. Permisos por rol

| Pantalla / Acción | Admin | Empleado |
|---|---|---|
| Dashboard | ✅ | ✅ |
| Cuartos — ver y registrar | ✅ | ✅ |
| Cuartos — editar monto | ✅ | ❌ |
| Cuartos — eliminar (soft-delete) | ✅ | ❌ |
| Otros ingresos (catálogo cerrado) | ✅ | ✅ |
| Gastos | ✅ | ❌ |
| Recibos (subir + procesar IA) | ✅ | ❌ |
| Inventario — ver detalles | ✅ | ❌ |
| Inventario — conteo semanal | ✅ | ✅ |
| Fondos | ✅ | ❌ |
| Reportes | ✅ | ❌ |
| Configuración | ✅ | ❌ |
| Asistente conversacional | ✅ | ❌ |
| Empleados | ✅ | ❌ |
| Cortes de turno — declarar | ✅ | ✅ |
| Cortes de turno — confirmar | ✅ | ❌ |
| GERTY (reactivo a estado) | ✅ | solo default |
| Widget de clima | ✅ | ✅ |

Justificación del corte:
- El empleado no necesita ver finanzas profundas — su trabajo es operar cuartos y registrar lo que vende
- El asistente conversacional gastaría tokens en preguntas absurdas si se expone a empleados
- GERTY visible para empleado (en estado default) porque es parte del alma del SME, pero sin revelar estado financiero

---

## 5. Cortes de turno

### 5.1 Flujo físico del dinero

- **Turno mañana cierra (~16:00)** → dinero queda físicamente en la caja del motel
- **Turno tarde cierra (~23:00)** → dinero acumulado mañana + tarde sigue en caja
- **Turno noche cierra (~08:00 día siguiente)** → cierre completo del día, **se pagan los sueldos físicamente en efectivo**

### 5.2 Lógica de los cortes

| Corte | Muestra | Descuentos |
|---|---|---|
| Mañana | Ventas del turno mañana (rentas + otros ingresos) | Ninguno |
| Tarde | Ventas mañana + tarde acumuladas | Ninguno |
| Noche | Ventas mañana + tarde + noche - sueldos del día | **Sueldos de los 3 turnos** |

El resultado del corte noche = **neto del día** que se reporta a admin / queda en caja como fondo.

### 5.3 Flujo de aprobación

1. **Empleado declara el cierre** al final de su turno desde la pantalla de cortes
2. **Admin confirma** posteriormente (no en tiempo real — puede ser cuando admin pase al motel)
3. Si hay discrepancia (cantidad declarada vs cantidad real), **admin puede editar** antes de confirmar
4. Una vez confirmado, el corte se sella y no se puede modificar (queda en histórico)

### 5.4 Tabla `cortes_turno`

Estructura propuesta (a confirmar en implementación):

```
id INTEGER PRIMARY KEY
fecha DATE NOT NULL
turno TEXT NOT NULL  -- 'mañana' | 'tarde' | 'noche'
empleado_id INTEGER  -- FK a empleados
ventas_brutas REAL NOT NULL
sueldos_descontados REAL DEFAULT 0
neto REAL NOT NULL
estado TEXT NOT NULL  -- 'declarado' | 'confirmado' | 'editado'
declarado_at DATETIME
confirmado_at DATETIME
confirmado_por INTEGER  -- FK a usuarios (Turi o Gabriel)
notas TEXT
```

---

## 6. Catálogo de "otros ingresos"

Para que empleado pueda registrar ventas misceláneas (no rentas), se usa **catálogo cerrado + categoría obligatoria**.

### 6.1 Items iniciales del catálogo

A definir con Turi durante implementación. Sugerencia inicial:

- Condones
- Agua embotellada
- Papel de baño (extra)
- Snacks
- Toallas (extra)

### 6.2 Edición del catálogo

- Solo admin puede agregar/editar/eliminar items del catálogo
- Vive en `/configuracion`

### 6.3 Tabla `catalogo_otros_ingresos`

```
id INTEGER PRIMARY KEY
nombre TEXT NOT NULL
precio REAL NOT NULL
activo BOOLEAN DEFAULT 1
```

### 6.4 Tabla `otros_ingresos`

```
id INTEGER PRIMARY KEY
fecha DATE NOT NULL
hora TIME NOT NULL
item_id INTEGER  -- FK a catalogo_otros_ingresos
cantidad INTEGER NOT NULL
monto_total REAL NOT NULL
notas TEXT
registrado_por TEXT  -- 'admin_turi' | 'admin_gabriel' | 'empleado'
```

Al registrar, se suma a `ingresos_diarios` del día actual.

---

## 7. GERTY en modo empleado

GERTY sigue visible en modo empleado para mantener la identidad del producto, pero **restringido**:

- Solo muestra estado `default` (cara feliz neutra)
- NO reacciona a fondos bajos (no se le ve la cara de alerta)
- NO reacciona a turnos de Turi
- NO entra a estado dormido (siempre default)
- Parpadeo SÍ funciona (es estética pura)
- Easter egg de doble click SÍ funciona (enojado/chiveado)
- Click simple → no abre `/asistente` (empleado no tiene acceso al asistente)

En su lugar, click simple en GERTY para empleado podría:
- Mostrar un toast random ("¡A trabajar!" / "Sigue así" / "Buen turno")
- O simplemente no hacer nada

Decisión final pendiente en implementación.

---

## 8. Migración de datos

- **Datos de v1 se mantienen 100% iguales**
- Las tablas nuevas (`usuarios`, `rentas`, `cortes_turno`, `catalogo_otros_ingresos`, `otros_ingresos`) se crean fresh
- Migración idempotente desde `scripts/init_db.py` (mismo patrón que en v1)
- Seed inicial:
  - 2 registros en `usuarios` (Turi y Gabriel con passwords iniciales — Turi define)
  - 10 registros en una tabla `cuartos` (o constantes en código)
  - Catálogo inicial de otros_ingresos (a definir)

---

## 9. Plan de implementación por sub-fases

### Sub-fase v2.0 — Autenticación base
- Tabla `usuarios` con Turi y Gabriel
- Sistema de login/logout
- Persistencia de modo en BD (`modo_actual` en `configuracion`)
- Toggle admin ↔ empleado con sus respectivas reglas
- Página `/login` simple
- Middleware/decorator que checa rol antes de cada ruta
- **Sin afectar funcionalidad existente todavía** (todas las rutas siguen accesibles para admin)

### Sub-fase v2.1 — Pantalla de cuartos
- Tabla `rentas` y catálogo `cuartos`
- Vista nueva `/cuartos` con grid de 10 cuartos
- Modal de registro con precios por duración
- Integración automática con `ingresos_diarios`
- Edición y eliminación (solo admin)

### Sub-fase v2.2 — Permisos por rol aplicados
- Ocultar rutas no permitidas del menú flotante según rol
- Mensajes claros cuando intenta acceder a algo restringido
- Restricciones en GERTY para empleado
- Restricción de subir recibos / ver asistente / etc.

### Sub-fase v2.3 — Cortes de turno
- Tabla `cortes_turno`
- Vista `/cortes` con flujo declarar/confirmar
- Lógica de descuentos en corte noche
- Sincronización con `pagos_empleados`
- Auditoría de quién confirmó qué

### Sub-fase v2.4 — Otros ingresos
- Tabla `catalogo_otros_ingresos` + `otros_ingresos`
- Vista de registro rápido (modal o pantalla dedicada)
- Edición del catálogo desde `/configuracion`
- Integración con `ingresos_diarios`

### Sub-fase v2.5 — Polish y testing
- Verificación cruzada de permisos (intentar acceder con rol incorrecto)
- Refinar UX de cortes de turno
- Documentación y memoria de usuario

### Merge a `main`
- Cuando v2.5 esté validada en `v2-dev`
- Tag `v2.0`
- Continúa el desarrollo en `main`

---

## 10. Pendientes y consideraciones futuras

- **2FA (TOTP)**: descartado para v2, considerar para v3 si hay riesgo de seguridad real
- **Multi-dispositivo**: si en el futuro el empleado registra desde su cel y Turi desde su casa, requiere sesiones por dispositivo (no por BD global). v3 territory.
- **Asignaciones de turnos a 2 años**: NO se hace en v1 (decidido), SÍ se incluye en v2.x cuando estabilice el módulo de empleados
- **Auditoría completa**: tabla `acciones_log` con cada cambio importante (quién, cuándo, qué). v3 territory.

---

## Notas del proceso de planeación

Este documento se redactó en la madrugada del sábado 27 de junio 2026, en sesión continua con Claude. La motivación de v2 surgió de la necesidad práctica de:

1. Tener una pantalla de cuartos central para operación diaria (v1 nunca tuvo esto, las rentas se metían como "ingresos" genéricos sin desglose)
2. Restringir el acceso de empleados a información financiera sensible
3. Formalizar los cortes de turno que hoy se hacen mentalmente / en papel

La decisión de hacer un branch `v2-dev` (en lugar de seguir en `main`) responde a buena práctica de Git para cambios arquitectónicos de este tamaño. El tag `v1.0` en main marca el estado oficial del producto v1 como referencia y respaldo.

---

**Fecha de creación:** 27 de junio 2026
**Autor:** Turi (con asistencia de Claude)
**Versión del documento:** 1.0 (planeación inicial)
