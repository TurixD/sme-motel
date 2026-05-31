"""
configuracion.py - Módulo de configuración del sistema (SPEC §5.8 — Fase 1).
"""

import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import sqlite3
from flask import Blueprint, jsonify, render_template, request

from config import Config
from logger import get_logger, log_action

configuracion_bp = Blueprint("configuracion", __name__)
_log = get_logger()

_ROOT        = Path(__file__).resolve().parent.parent
_BACKUPS_DIR = _ROOT / "backups"
_BACKUP_SCRIPT = _ROOT / "scripts" / "backup.py"

# Claves editables: (tipo, min, max)
# tipos: "pct" float 0-100, "decimal" float >0, "int" int >0, "int_range" int en [min,max]
_CONFIG_RULES: dict[str, tuple] = {
    "comision_tarjeta":           ("pct",       0,    100),
    "tipo_cambio_usd_mxn":        ("decimal",   0.01, None),
    "umbral_alerta_gasto_ia_usd": ("decimal",   0.01, None),
    "memoria_asistente_mensajes": ("int_range", 1,    50),
    "timeout_sesion_minutos":     ("int",       1,    None),
}

_TURNOS_LABEL = {"manana": "Mañana", "tarde": "Tarde", "noche": "Noche"}


@contextmanager
def _db():
    conn = sqlite3.connect(Config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _backup_info() -> dict:
    if not _BACKUPS_DIR.exists():
        return {"ruta": str(_BACKUPS_DIR), "cantidad": 0, "ultimo": None}
    archivos = sorted(
        _BACKUPS_DIR.glob("sme_*.db"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    ultimo = None
    if archivos:
        mtime = archivos[0].stat().st_mtime
        ultimo = datetime.fromtimestamp(mtime).strftime("%d/%m/%Y %H:%M")
    return {"ruta": str(_BACKUPS_DIR), "cantidad": len(archivos), "ultimo": ultimo}


def _validar(valor: str, tipo: str, vmin, vmax) -> str | None:
    try:
        if tipo in ("pct", "decimal"):
            n = float(valor)
            if vmin is not None and n < vmin:
                return f"Debe ser mayor a {vmin}"
            if vmax is not None and n > vmax:
                return f"Debe ser menor o igual a {vmax}"
        else:
            n = int(valor)
            if vmin is not None and n < vmin:
                return f"Debe ser mayor o igual a {vmin}"
            if vmax is not None and n > vmax:
                return f"Debe ser menor o igual a {vmax}"
    except (ValueError, TypeError):
        return "Valor numérico inválido"
    return None


# ── Página principal ──────────────────────────────────────────

@configuracion_bp.route("/configuracion")
def index():
    with _db() as db:
        config = {
            r["clave"]: r["valor"]
            for r in db.execute("SELECT clave, valor FROM configuracion").fetchall()
        }
        gastos_fijos = [
            dict(r) for r in db.execute(
                "SELECT id, concepto, monto_estimado, frecuencia, dia_recordatorio, activo "
                "FROM gastos_fijos ORDER BY id"
            ).fetchall()
        ]
        turnos = [
            dict(r) for r in db.execute(
                "SELECT id, nombre, hora_inicio, hora_fin, sueldo FROM turnos ORDER BY hora_inicio"
            ).fetchall()
        ]
        fondos = [
            dict(r) for r in db.execute(
                "SELECT id, nombre, aporte_periodico, frecuencia_aporte, meta_mensual, color "
                "FROM fondos WHERE activo=1 ORDER BY id"
            ).fetchall()
        ]

    return render_template(
        "configuracion.html",
        config=config,
        gastos_fijos=gastos_fijos,
        turnos=turnos,
        fondos=fondos,
        turnos_label=_TURNOS_LABEL,
        backup=_backup_info(),
    )


# ── API: actualizar configuracion ─────────────────────────────

@configuracion_bp.route("/configuracion/api/config", methods=["POST"])
def api_config():
    data  = request.get_json(silent=True) or {}
    clave = (data.get("clave") or "").strip()
    valor = str(data.get("valor") or "").strip()

    if clave not in _CONFIG_RULES:
        return jsonify({"ok": False, "error": "Clave no permitida"}), 400

    tipo, vmin, vmax = _CONFIG_RULES[clave]
    err = _validar(valor, tipo, vmin, vmax)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    with _db() as db:
        row = db.execute("SELECT valor FROM configuracion WHERE clave=?", (clave,)).fetchone()
        anterior = row["valor"] if row else "(vacío)"
        db.execute("UPDATE configuracion SET valor=? WHERE clave=?", (valor, clave))
        db.commit()

    log_action("Config: %s cambió de %r a %r", clave, anterior, valor)
    return jsonify({"ok": True})


# ── API: actualizar gasto fijo ─────────────────────────────────

@configuracion_bp.route("/configuracion/api/gasto-fijo/<int:gf_id>", methods=["POST"])
def api_gasto_fijo(gf_id):
    data     = request.get_json(silent=True) or {}
    monto_s  = str(data.get("monto_estimado") or "").strip()
    dia_s    = str(data.get("dia_recordatorio") or "").strip()
    activo   = int(bool(data.get("activo", True)))

    if not monto_s:
        return jsonify({"ok": False, "error": "El monto es requerido"}), 400
    err = _validar(monto_s, "decimal", 0.01, None)
    if err:
        return jsonify({"ok": False, "error": f"Monto: {err}"}), 400
    monto = float(monto_s)

    dia = None
    if dia_s:
        err = _validar(dia_s, "int_range", 1, 28)
        if err:
            return jsonify({"ok": False, "error": f"Día: {err}"}), 400
        dia = int(dia_s)

    with _db() as db:
        gf = db.execute(
            "SELECT concepto, monto_estimado FROM gastos_fijos WHERE id=?", (gf_id,)
        ).fetchone()
        if not gf:
            return jsonify({"ok": False, "error": "Registro no encontrado"}), 404

        db.execute(
            "UPDATE gastos_fijos SET monto_estimado=?, dia_recordatorio=?, activo=? WHERE id=?",
            (monto, dia, activo, gf_id),
        )
        db.commit()

    log_action(
        "Gasto fijo '%s': $%.2f → $%.2f, día=%s, activo=%s",
        gf["concepto"], float(gf["monto_estimado"] or 0), monto, dia or "—", bool(activo),
    )
    return jsonify({"ok": True})


# ── API: ejecutar backup manual ────────────────────────────────

@configuracion_bp.route("/configuracion/api/backup", methods=["POST"])
def api_backup():
    if not _BACKUP_SCRIPT.exists():
        return jsonify({"ok": False, "error": "Script de backup no encontrado"}), 500
    try:
        result = subprocess.run(
            [sys.executable, str(_BACKUP_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            _log.error("Backup falló: %s", result.stderr)
            return jsonify({"ok": False, "error": "El backup falló. Revisa los logs."}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "Timeout al ejecutar el backup"}), 500
    except Exception as exc:
        _log.error("Error al ejecutar backup: %s", exc)
        return jsonify({"ok": False, "error": "Error inesperado"}), 500

    log_action("Backup manual ejecutado desde Configuración")
    info = _backup_info()
    return jsonify({"ok": True, "cantidad": info["cantidad"], "ultimo": info["ultimo"]})
