"""
tiempo.py - Helpers de la frontera del "día operativo" del motel.

El día de negocio corre de 08:00 a 08:00 del día siguiente. Entre 00:00 y
07:59 el momento actual todavía pertenece al día operativo ANTERIOR. El turno
de noche (23:00–08:00) cruza la medianoche dentro del mismo día operativo.

Usar este helper en todos lados (cuartos, cortes, dashboard, ingresos) para
que compartan la misma frontera y nada se "reinicie" a medianoche.
"""

from datetime import date, datetime, timedelta


def dia_operativo(now: datetime | None = None) -> date:
    """Fecha del día operativo vigente para `now` (o el momento actual)."""
    now = now or datetime.now()
    return now.date() - timedelta(days=1) if now.hour < 8 else now.date()
