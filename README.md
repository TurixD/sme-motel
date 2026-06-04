# SME — Software de Manejo de Estrés

Sistema de administración integral para un motel, de uso personal y local. Centraliza
ingresos, gastos, fondos de reserva, empleados/turnos, inventario y reportes, con
integración de IA (Claude) para lectura de recibos, asistente conversacional y reportes.

> El sistema existe para **reducir el estrés operativo**, no para demostrar capacidad
> técnica. Ante la duda, se elige siempre la opción más simple.

La especificación técnica completa vive en [`SPEC.md`](SPEC.md).

---

## Stack

| Componente        | Tecnología                          |
|-------------------|-------------------------------------|
| Lenguaje          | Python 3.14                         |
| Framework web     | Flask                               |
| Servidor WSGI     | waitress (producción en Windows)    |
| Base de datos     | SQLite (`sqlite3` nativo, SQL directo) |
| Frontend          | HTML + CSS + JavaScript vanilla     |
| IA                | API de Anthropic (Claude)           |
| Variables         | `.env` con python-dotenv            |

---

## Instalación

> Requiere **Python 3.14** instalado.

```bash
# 1. Clonar y entrar al proyecto
cd sme-motel

# 2. Crear y activar el entorno virtual
python -m venv .venv
.venv\Scripts\activate        # Windows (PowerShell/CMD)

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar variables de entorno
copy .env.example .env        # luego rellenar los valores en .env
```

---

## Uso

> _(Pendiente — se completará conforme avancen las fases de desarrollo.)_

```bash
python app.py
```

Abre el navegador en `http://localhost:5050`.

---

## Estructura del proyecto

Ver [`SPEC.md` §3](SPEC.md#3-arquitectura). En resumen:

```
sme-motel/
├── app.py            # Entry point Flask
├── config.py         # Configuración (lee .env)
├── database/         # SQLite + schema.sql + migraciones
├── modules/          # Lógica de cada módulo de negocio
├── ai/               # Integración con Claude
├── static/           # css / js / img
├── templates/        # HTML de Flask
├── uploads/recibos/  # Recibos subidos por el usuario
├── logs/             # info / error / actions
├── backups/          # Copias automáticas diarias
└── scripts/          # backup, autoarranque, seed
```

---

## Estado del desarrollo

El proyecto se desarrolla en **7 fases incrementales** (ver [`SPEC.md` §7](SPEC.md#7-plan-de-desarrollo-por-fases)).

- [x] **Fase 0 — Cimientos**
- [x] **Fase 1 — Operación básica** ✅
- [x] **Fase 2 — Fondos y reportes** ✅
- [ ] **Fase 3 — IA básica** _(siguiente)_
- [ ] Fase 4 — Asistente conversacional
- [ ] Fase 5 — Inventario inteligente
- [ ] Fase 6 — Pulido y mascota (GERTY-MOTEL)
- [ ] Fase 7 — Iteración continua

---

## Convenciones de código

### Frontend — atributos `onclick` inline

**Regla:** nunca pasar strings de datos como literales entre comillas simples en atributos HTML inline (`onclick`, `onchange`, etc.).

```html
<!-- ❌ MAL — se rompe si el dato contiene apóstrofes (ej. "Sam's") -->
<button onclick="eliminar({{ id }}, '{{ nombre }}')">

<!-- ✅ BIEN — pasar solo el ID y buscar el registro en el array en memoria -->
<button onclick="eliminar({{ id }})">
```

```javascript
// En el JS, buscar el registro completo por ID:
function eliminar(id) {
    const reg = DATA.find(r => r.id === id);
    // usar reg.nombre, reg.categoria, etc.
}
```

**Por qué:** categorías (`Sam's`), nombres de empleados o descripciones pueden contener apóstrofes u otros caracteres que rompen la sintaxis de JavaScript dentro del atributo HTML, causando que el handler falle silenciosamente sin error en consola.

**Aplica a:** cualquier campo de texto libre o categoría con nombre predefinido que pueda contener `'`, `"`, `\`, saltos de línea, u otros caracteres especiales.
