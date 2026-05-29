"""
config.py - Configuracion central de SME. Lee variables desde .env.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# Carga las variables de entorno desde .env (si existe)
load_dotenv(BASE_DIR / ".env")


class Config:
    # --- Flask ---
    # Fallback de desarrollo para que la app arranque aunque .env este vacio.
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY") or "dev-inseguro-cambiar-en-produccion"
    ENV = os.getenv("FLASK_ENV", "development")
    HOST = os.getenv("FLASK_HOST", "0.0.0.0")
    PORT = int(os.getenv("FLASK_PORT") or 5000)
    DEBUG = ENV == "development"

    # --- Claude / Anthropic ---
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

    # --- Rutas ---
    DB_PATH = BASE_DIR / "database" / "sme.db"
    UPLOADS_DIR = BASE_DIR / "uploads" / "recibos"
    LOGS_DIR = BASE_DIR / "logs"
