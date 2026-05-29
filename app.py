"""
app.py - Entry point de SME (Software de Manejo de Estres).

Fase 0 / Paso 3: Flask minimo ("Hello World") en localhost:5000.
El dashboard real llega en el Paso 5.
"""

from flask import Flask

from config import Config


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    @app.route("/")
    def index():
        return (
            "<h1>SME - Software de Manejo de Estres</h1>"
            "<p>Flask corriendo correctamente en localhost:5000.</p>"
            "<p>Dashboard pendiente (Paso 5).</p>"
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)
