"""
cost_calculator.py - Calcula costo en USD de una llamada a Claude API.
Precios: USD por millón de tokens (input / output).
"""

_PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5-20251001": (1.00,  5.00),
    "claude-haiku-4-5":          (1.00,  5.00),
    "claude-sonnet-4-6":         (3.00,  15.00),
    "claude-sonnet-5":           (3.00,  15.00),
    "claude-opus-4-7":           (5.00,  25.00),
    "claude-opus-4-8":           (5.00,  25.00),
}

_FALLBACK = (3.00, 15.00)


def calcular_costo(modelo: str, tokens_in: int, tokens_out: int) -> float:
    precio_in, precio_out = _PRICES.get(modelo, _FALLBACK)
    return (tokens_in * precio_in + tokens_out * precio_out) / 1_000_000
