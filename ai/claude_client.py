"""
claude_client.py - Wrapper centralizado para llamadas a Claude API (SPEC §6.5).

Uso:
    from ai.claude_client import call_claude
    resp = call_claude(
        messages=[{"role": "user", "content": "..."}],
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        modulo_origen="recibos",
    )
    # resp: {text, tokens_in, tokens_out, costo_usd, error}
"""

import sqlite3
from datetime import date

import anthropic

from ai.cost_calculator import calcular_costo
from config import Config
from logger import get_logger, log_action

DEFAULT_MODEL = "claude-haiku-4-5-20251001"

_log = get_logger()


def _db():
    conn = sqlite3.connect(Config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _uso_mensual() -> tuple[float, float]:
    """Devuelve (gastado_usd_mes, limite_usd) del mes en curso."""
    hoy = date.today()
    mes_inicio = f"{hoy.year}-{hoy.month:02d}-01"
    conn = _db()
    try:
        total = conn.execute(
            "SELECT COALESCE(SUM(costo_usd), 0) FROM uso_ia WHERE fecha >= ?",
            (mes_inicio,),
        ).fetchone()[0]
        row = conn.execute(
            "SELECT valor FROM configuracion WHERE clave='limite_mensual_ia_usd'"
        ).fetchone()
        limite = float(row["valor"]) if row else 5.0
    finally:
        conn.close()
    return float(total), limite


def _registrar(
    modulo: str,
    modelo: str,
    tokens_in: int,
    tokens_out: int,
    costo: float,
    exito: int,
    error_msg: str | None,
) -> None:
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO uso_ia "
            "(funcion, modelo, tokens_input, tokens_output, costo_usd, exito, error_message) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (modulo, modelo, tokens_in, tokens_out, costo, exito, error_msg),
        )
        conn.commit()
    except Exception as exc:
        _log.error("No se pudo registrar uso_ia: %s", exc)
    finally:
        conn.close()


def call_claude(
    messages: list[dict],
    model: str = DEFAULT_MODEL,
    max_tokens: int = 1024,
    modulo_origen: str = "general",
) -> dict:
    """
    Llama a Claude API con tracking automático de tokens y costo.

    Siempre devuelve dict con: text, tokens_in, tokens_out, costo_usd, error.
    Si hubo error, text es None y error contiene el mensaje.
    """
    _err = lambda msg: {"text": None, "tokens_in": 0, "tokens_out": 0, "costo_usd": 0.0, "error": msg}

    if not Config.ANTHROPIC_API_KEY:
        return _err("ANTHROPIC_API_KEY no configurada")

    total_mes, limite = _uso_mensual()
    if total_mes >= limite:
        return _err(
            f"Límite mensual de IA alcanzado (${total_mes:.4f} / ${limite:.2f} USD)"
        )

    tokens_in = tokens_out = 0
    costo = 0.0
    text = None
    error_msg = None
    exito = 0

    try:
        client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=messages,
        )
        text = response.content[0].text
        tokens_in = response.usage.input_tokens
        tokens_out = response.usage.output_tokens
        costo = calcular_costo(model, tokens_in, tokens_out)
        exito = 1
    except anthropic.APIConnectionError as exc:
        error_msg = f"Error de conexión: {exc}"
        _log.error("Claude conexión fallida: %s", exc)
    except anthropic.RateLimitError as exc:
        error_msg = f"Rate limit excedido: {exc}"
        _log.error("Claude rate limit: %s", exc)
    except anthropic.APIStatusError as exc:
        error_msg = f"API error {exc.status_code}: {exc.message}"
        _log.error("Claude API status %s: %s", exc.status_code, exc.message)
    except Exception as exc:
        error_msg = f"Error inesperado: {exc}"
        _log.error("call_claude error inesperado: %s", exc)

    _registrar(modulo_origen, model, tokens_in, tokens_out, costo, exito, error_msg)
    log_action(
        "IA [%s] modelo=%s in=%d out=%d costo=$%.6f exito=%s%s",
        modulo_origen, model, tokens_in, tokens_out, costo, bool(exito),
        f" error={error_msg}" if error_msg else "",
    )

    return {
        "text": text,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "costo_usd": costo,
        "error": error_msg,
    }
