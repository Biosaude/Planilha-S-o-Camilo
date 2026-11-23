import hashlib
import hmac
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from .models import QuoteError

ROLES = ('operador', 'administrador')


def local_role(password: str, role: str) -> bool:
    env_names = {'operador': 'BIOSAUDE_OPERATOR_PASSWORD', 'administrador': 'BIOSAUDE_ADMIN_PASSWORD'}
    operator = os.environ.get(env_names['operador'], '')
    admin = os.environ.get(env_names['administrador'], '')
    if not operator or len(operator) < 16 or (admin and (len(admin) < 16 or operator == admin)):
        raise QuoteError('Configure senhas locais distintas, com pelo menos 16 caracteres.')
    expected = os.environ.get(env_names.get(role, ''), '')
    if not expected or len(password) > 1024:
        return False
    return hmac.compare_digest(password.encode(), expected.encode())


def oidc_role(subject: str) -> str:
    if not subject:
        return ''
    for role, variable in (
        ('administrador', 'BIOSAUDE_ADMIN_SUBJECTS'), ('operador', 'BIOSAUDE_OPERATOR_SUBJECTS')
    ):
        if subject in {item.strip() for item in os.environ.get(variable, '').split(',') if item.strip()}:
            return role
    return ''


def record_audit(path: Path, quote_key: str, version: int, actor: str, role: str, decisions: list) -> None:
    digest = hashlib.sha256(json.dumps(decisions).encode()).hexdigest()
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.touch(mode=0o600, exist_ok=True)
        with closing(sqlite3.connect(path, timeout=10)) as db, db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS decisions (
                    quote_key TEXT NOT NULL, batch TEXT NOT NULL, item INTEGER NOT NULL,
                    hospital_row INTEGER, action TEXT NOT NULL, actor TEXT NOT NULL,
                    role TEXT NOT NULL, catalog_version INTEGER NOT NULL,
                    recorded_utc TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (quote_key, batch, item)
                )
            """)
            db.executemany(
                """INSERT INTO decisions (quote_key, batch, item, hospital_row, action, actor, role, catalog_version)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (quote_key, batch, item) DO NOTHING""",
                ((quote_key, digest, index, row, action, actor, role, version) for index, row, action in decisions),
            )
    except (OSError, sqlite3.Error) as exc:
        raise QuoteError('A revisão manual não pôde ser registrada. Verifique o banco de auditoria.') from exc
