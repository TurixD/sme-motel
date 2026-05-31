"""
app.py - Entry point de SME (Software de Manejo de Estres).

Fase 0 / Paso 3: Flask minimo ("Hello World") en localhost:5050.
El dashboard real llega en el Paso 5.
"""

from datetime import datetime

from flask import Flask, render_template

from config import Config
from logger import get_logger, log_action, setup_logging
from modules.configuracion import configuracion_bp
from modules.empleados import empleados_bp
from modules.gastos import gastos_bp
from modules.ingresos import ingresos_bp

_DIAS = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]
_MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def _fecha_es(dt: datetime) -> str:
    """Fecha en espanol sin depender del locale del SO."""
    return f"{_DIAS[dt.weekday()]}, {dt.day} de {_MESES[dt.month - 1]} {dt.year}"


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    setup_logging()
    log = get_logger()
    log.info("SME iniciado (puerto %s, debug=%s)", Config.PORT, Config.DEBUG)

    # --- Blueprints ---
    app.register_blueprint(ingresos_bp)
    app.register_blueprint(gastos_bp)
    app.register_blueprint(empleados_bp)
    app.register_blueprint(configuracion_bp)

    # --- Filtro de moneda ($1,234) ---
    @app.template_filter("moneda")
    def moneda_filter(value):
        try:
            return f"${float(value or 0):,.0f}"
        except (TypeError, ValueError):
            return "$0"

    # --- Variables globales de template ---
    @app.context_processor
    def inject_globals():
        return {
            "fecha_actual": _fecha_es(datetime.now()),
            "clima": "24 °C, soleado — Aguascalientes",
        }

    @app.route("/")
    def index():
        log_action("Visita al dashboard (/)")
        return render_template("dashboard.html")

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)
