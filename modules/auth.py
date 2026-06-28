"""
auth.py - Utilitarios de autorización por rol (v2.2).
"""

import sqlite3
from functools import wraps

from flask import flash, jsonify, redirect, request

from config import Config
from logger import log_action


def _get_modo() -> str:
    try:
        with sqlite3.connect(Config.DB_PATH) as conn:
            row = conn.execute(
                "SELECT valor FROM configuracion WHERE clave='modo_actual'"
            ).fetchone()
            return row[0] if row else "admin_turi"
    except Exception:
        return "admin_turi"


def _es_ajax() -> bool:
    """Detecta si la request espera respuesta JSON (API/AJAX)."""
    return (
        request.is_json
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.headers.get("Accept", "").startswith("application/json")
        or "/api/" in request.path
    )


def solo_admin(f):
    """Decorator: bloquea acceso a empleados. JSON → 403; GET normal → flash + redirect /."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        modo = _get_modo() or "empleado"
        if not modo.startswith("admin_"):
            log_action("Acceso denegado a '%s' (modo=%s)", request.path, modo)
            if _es_ajax():
                return jsonify({"error": "Solo admin"}), 403
            flash("Solo admin", "error")
            return redirect("/")
        return f(*args, **kwargs)
    return wrapper
