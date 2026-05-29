"""
logger.py - Sistema de logs de SME (SPEC seccion 3).

Tres archivos rotativos en /logs:
    - info.log     -> eventos generales (INFO y superiores)
    - error.log    -> solo errores (ERROR y superiores)
    - actions.log  -> acciones del usuario (registros, cambios, pagos, etc.)

Rotacion: ~1 MB por archivo, 5 backups (info.log.1, info.log.2, ...).

Uso tipico:
    from logger import setup_logging, get_logger, log_action

    setup_logging()                 # una vez al arrancar la app
    log = get_logger()
    log.info("Ingreso registrado")
    log.error("Fallo al leer recibo")
    log_action("Pago marcado: Renta $40,000")
"""

import logging
from logging.handlers import RotatingFileHandler

from config import Config

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES = 1_000_000   # ~1 MB por archivo
_BACKUPS = 5             # cantidad de archivos rotados a conservar


def _rotating_handler(filename: str, level: int) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        Config.LOGS_DIR / filename,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUPS,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(_FORMAT, _DATEFMT))
    return handler


def setup_logging() -> logging.Logger:
    """Configura los loggers de SME. Idempotente (no duplica handlers)."""
    Config.LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # --- Logger general: info.log (INFO+) y error.log (ERROR+) ---
    app_logger = logging.getLogger("sme")
    app_logger.setLevel(logging.INFO)
    if not app_logger.handlers:
        app_logger.addHandler(_rotating_handler("info.log", logging.INFO))
        app_logger.addHandler(_rotating_handler("error.log", logging.ERROR))
        # En desarrollo, tambien a consola.
        if Config.DEBUG:
            console = logging.StreamHandler()
            console.setLevel(logging.INFO)
            console.setFormatter(logging.Formatter(_FORMAT, _DATEFMT))
            app_logger.addHandler(console)

    # --- Logger de acciones del usuario: actions.log ---
    actions_logger = logging.getLogger("sme.actions")
    actions_logger.setLevel(logging.INFO)
    actions_logger.propagate = False  # no duplicar en info.log
    if not actions_logger.handlers:
        actions_logger.addHandler(_rotating_handler("actions.log", logging.INFO))

    return app_logger


def get_logger(name: str = "sme") -> logging.Logger:
    """Devuelve el logger general (o un hijo de 'sme')."""
    return logging.getLogger(name)


def log_action(message: str, *args) -> None:
    """Registra una accion del usuario en actions.log."""
    logging.getLogger("sme.actions").info(message, *args)
