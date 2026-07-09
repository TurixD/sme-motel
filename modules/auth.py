"""
auth.py - Utilitarios de autorización por rol (v2.5).

El modo (admin_turi | admin_gabriel | empleado) vive en la SESIÓN de cada
dispositivo (cookie firmada), no en una bandera global de BD. Así, que Turi
inicie sesión en su celular no vuelve admin al mostrador ni a nadie más.
"""

from functools import wraps

from flask import flash, jsonify, redirect, request, session

from logger import log_action


def _get_modo() -> str:
    """Modo del dispositivo actual según su sesión ('' si no ha iniciado sesión)."""
    return session.get("modo", "")


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
