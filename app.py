"""
app.py - Entry point de SME (Software de Manejo de Estres).

Fase 0 / Paso 3: Flask minimo ("Hello World") en localhost:5050.
El dashboard real llega en el Paso 5.
"""

from flask import Flask

from config import Config
from logger import get_logger, log_action, setup_logging


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    setup_logging()
    log = get_logger()
    log.info("SME iniciado (puerto %s, debug=%s)", Config.PORT, Config.DEBUG)

    @app.route("/")
    def index():
        log_action("Visita al dashboard (/)")
        return (
            "<h1>SME - Software de Manejo de Estres</h1>"
            "<p>Flask corriendo correctamente en localhost:5050.</p>"
            "<p>Dashboard pendiente (Paso 5).</p>"
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)
