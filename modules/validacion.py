"""
validacion.py - Helpers de validación de entradas de las APIs.

Evitan que datos basura (montos no numéricos, fechas inválidas) revienten los
endpoints con un 500; devuelven un 400 limpio.
"""

from datetime import date


def parse_monto(valor, *, mayor_a_cero: bool = False):
    """
    Convierte `valor` a float de forma segura.
    Devuelve (monto, None) si es válido, o (None, error) si no.
    Con mayor_a_cero=True exige > 0.
    """
    try:
        monto = float(valor if valor not in (None, "") else 0)
    except (TypeError, ValueError):
        return None, "Monto inválido"
    if mayor_a_cero and monto <= 0:
        return None, "El monto debe ser mayor a cero"
    return monto, None


def fecha_ok(valor) -> bool:
    """True si `valor` es una fecha ISO 'YYYY-MM-DD' válida."""
    try:
        date.fromisoformat(valor)
        return True
    except (TypeError, ValueError):
        return False
