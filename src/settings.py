import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def database_path() -> Path:
    return Path(os.environ.get('BIOSAUDE_TUSS_DB', str(ROOT / 'data' / 'tuss.sqlite3')))


def audit_path() -> Path:
    return Path(os.environ.get('BIOSAUDE_AUDIT_DB', str(ROOT / 'data' / 'audit.sqlite3')))
