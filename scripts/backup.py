"""
backup.py - Respaldo diario de la base de datos SME.

Uso manual:
    python scripts/backup.py

Para programar en Windows Task Scheduler:
    Programa : python
    Argumentos: C:\\ruta\\proyecto\\scripts\\backup.py
    Iniciar en: C:\\ruta\\proyecto
    (Usa la ruta completa o configura la variable PATH)
"""

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Raiz del proyecto (un nivel arriba de scripts/)
BASE_DIR = Path(__file__).resolve().parent.parent

DB_PATH = BASE_DIR / "database" / "sme.db"
BACKUPS_DIR = BASE_DIR / "backups"
RETENTION_DAYS = 30


def make_backup() -> Path:
    BACKUPS_DIR.mkdir(exist_ok=True)

    if not DB_PATH.exists():
        print(f"[ERROR] No se encontro la base de datos en: {DB_PATH}")
        sys.exit(1)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUPS_DIR / f"sme_{timestamp}.db"

    # API de backup de SQLite: consistente aunque la BD esté en uso o en modo WAL
    # (a diferencia de copiar el archivo, que puede quedar a medias).
    src = sqlite3.connect(DB_PATH)
    try:
        dst = sqlite3.connect(dest)
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    size_kb = dest.stat().st_size // 1024
    print(f"[OK] Respaldo creado: {dest.name} ({size_kb} KB)")
    return dest


def purge_old_backups() -> None:
    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
    removed = 0

    for f in BACKUPS_DIR.glob("sme_*.db"):
        if f.stat().st_mtime < cutoff.timestamp():
            f.unlink()
            removed += 1

    if removed:
        print(f"[OK] {removed} respaldo(s) eliminado(s) (mas de {RETENTION_DAYS} dias)")


if __name__ == "__main__":
    print(f"[SME Backup] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    make_backup()
    purge_old_backups()
    print("[SME Backup] Listo.")
