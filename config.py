"""
config.py - Configuracion central de SME. Lee variables desde .env.
"""

import os
from datetime import timedelta
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
    PORT = int(os.getenv("FLASK_PORT") or 5050)
    DEBUG = ENV == "development"

    # --- Sesión / cookies (auth por dispositivo) ---
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Activar SESSION_COOKIE_SECURE=true en .env cuando se sirva por HTTPS (remoto)
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    # Si se accede por HTTP plano (ej. la IP de Tailscale), rebota a esta URL HTTPS.
    # Ej: desktop-01c8r6d.tail0eea51.ts.net  (vacío = sin redirección)
    HTTPS_REDIRECT_HOST = os.getenv("SME_HTTPS_HOST", "").strip()

    # --- Claude / Anthropic ---
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    # Modelo del asistente conversacional. Cambiable sin tocar código.
    # Barato por defecto (Haiku 4.5). Alternativas: claude-sonnet-5, claude-opus-4-8.
    ASSISTANT_MODEL = os.getenv("SME_ASSISTANT_MODEL", "claude-haiku-4-5")
    ASSISTANT_MAX_TOKENS = int(os.getenv("SME_ASSISTANT_MAX_TOKENS") or 4096)

    # --- Rutas ---
    BASE_DIR = BASE_DIR
    DB_PATH = BASE_DIR / "database" / "sme.db"
    UPLOADS_DIR = BASE_DIR / "uploads" / "recibos"
    RECIBOS_DIR = BASE_DIR / "database" / "recibos"
    LOGS_DIR = BASE_DIR / "logs"
